"""Agent-loop mechanics, tested offline with a scripted fake client."""

import json
from types import SimpleNamespace

import pytest

from emporio.agent import GIVE_UP_REPLY, REFUSAL_REPLY, StoreAgent

USAGE = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=80, cache_creation_input_tokens=0)


def text_response(text):
    return SimpleNamespace(stop_reason="end_turn", usage=USAGE, content=[SimpleNamespace(type="text", text=text)])


def tool_response(name, arguments, tool_id="toolu_1"):
    block = SimpleNamespace(type="tool_use", id=tool_id, name=name, input=arguments)
    return SimpleNamespace(stop_reason="tool_use", usage=USAGE, content=[block])


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append({**params, "messages": list(params["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_agent(ctx, *responses, model="claude-opus-5-5"):
    client = FakeClient(*responses)
    return StoreAgent(ctx, model=model, effort="low", client=client), client


def test_tool_round_trip(ctx):
    agent, client = make_agent(
        ctx,
        tool_response("search_products", {"category": "violoes", "max_price": 1000}),
        text_response("Temos 12 opções!"),
    )
    reply = agent.send("violões até 1000?")

    assert reply.text == "Temos 12 opções!"
    assert [c.name for c in reply.tool_calls] == ["search_products"]
    assert reply.usage.model_calls == 2
    assert [m["role"] for m in agent.history] == ["user", "assistant", "user", "assistant"]
    tool_result = client.requests[1]["messages"][2]["content"][0]
    assert tool_result["tool_use_id"] == "toolu_1" and tool_result["is_error"] is False
    assert json.loads(tool_result["content"])["total_found"] == 12


def test_request_parameters(ctx):
    agent, client = make_agent(ctx, text_response("Oi!"))
    agent.send("oi")
    params = client.requests[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"] == {"effort": "low"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["fallbacks"] == "default"
    assert {t["name"] for t in params["tools"]} >= {"search_products", "check_order", "get_store_policy"}


def test_no_fallback_parameter_for_models_without_support(ctx):
    agent, client = make_agent(ctx, text_response("Oi!"), model="claude-haiku-5-5")
    agent.send("oi")
    assert "fallbacks" not in client.requests[0]


def test_tool_errors_are_returned_to_the_model(ctx):
    agent, client = make_agent(ctx, tool_response("get_store_policy", {"topics": ["nope"]}), text_response("ok"))
    reply = agent.send("política?")
    assert reply.tool_calls[0].is_error
    assert client.requests[1]["messages"][2]["content"][0]["is_error"] is True


def test_refusal_drops_the_turn(ctx):
    refusal = SimpleNamespace(stop_reason="refusal", usage=USAGE, content=[])
    agent, _ = make_agent(ctx, text_response("Oi!"), refusal)
    agent.send("oi")
    reply = agent.send("algo recusado")
    assert reply.text == REFUSAL_REPLY
    assert len(agent.history) == 2  # only the first exchange remains


def test_api_error_rolls_back_history(ctx):
    agent, _ = make_agent(ctx, RuntimeError("network down"))
    with pytest.raises(RuntimeError):
        agent.send("oi")
    assert agent.history == []


def test_response_cut_off_mid_tool_call_drops_the_turn(ctx):
    # Keeping an unanswered tool_use in history would make every later request fail.
    truncated = SimpleNamespace(
        stop_reason="max_tokens", usage=USAGE,
        content=[SimpleNamespace(type="tool_use", id="toolu_x", name="search_products", input={})],
    )
    agent, _ = make_agent(ctx, text_response("Oi!"), truncated)
    agent.send("oi")
    reply = agent.send("violões?")
    assert reply.text == GIVE_UP_REPLY
    assert len(agent.history) == 2  # only the first exchange remains


def test_interruption_mid_turn_rolls_back_history(ctx):
    agent, _ = make_agent(ctx, tool_response("get_store_info", {}), KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        agent.send("onde fica a loja?")
    assert agent.history == []
