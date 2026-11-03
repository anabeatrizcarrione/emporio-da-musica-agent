"""Conversation agent: a hand-written tool-use loop around the Claude Messages API.

The loop is explicit (instead of the SDK's beta tool runner) so each model call
and tool execution is easy to follow, trace in the CLI's debug mode, and record
in transcripts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic

from emporio.config import DATA_DIR, POLICY_PDF, RUNTIME_DIR, Settings
from emporio.data import load_store_data
from emporio.policies import PolicyManual
from emporio.prompts import SYSTEM_PROMPT
from emporio.tools import ToolContext, run_tool, tool_definitions

MAX_TOKENS = 16000  # thinking counts toward this limit, so leave headroom
MAX_MODEL_CALLS_PER_TURN = 8
# Models that accept server-side refusal fallbacks in "default" routing mode.
FALLBACK_CAPABLE_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

REFUSAL_REPLY = (
    "Desculpe, não consigo ajudar com isso por aqui. "
    "Posso te ajudar com instrumentos, pedidos ou dúvidas sobre a loja?"
)
GIVE_UP_REPLY = "Desculpe, não consegui concluir essa consulta agora. Pode tentar de novo em instantes?"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    is_error: bool


@dataclass
class Usage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.model_calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0


@dataclass
class AgentReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class StoreAgent:
    def __init__(self, ctx: ToolContext, model: str, effort: str = "low", client: anthropic.Anthropic | None = None):
        self.ctx = ctx
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()
        self.tools = tool_definitions(ctx)
        self.history: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.history = []

    def send(self, user_text: str) -> AgentReply:
        """Process one customer message, running tools until the model answers."""
        checkpoint = len(self.history)
        self.history.append({"role": "user", "content": user_text})
        reply = AgentReply()
        try:
            for _ in range(MAX_MODEL_CALLS_PER_TURN):
                response = self._call_model()
                reply.usage.add(response.usage)
                if response.stop_reason in ("refusal", "max_tokens"):
                    # Refused, or cut off (possibly in the middle of a tool call): drop the whole turn so
                    # it doesn't carry into the conversation and the history stays valid for the API.
                    del self.history[checkpoint:]
                    reply.text = REFUSAL_REPLY if response.stop_reason == "refusal" else GIVE_UP_REPLY
                    return reply
                # History is append-only and keeps the full content (thinking blocks included),
                # which the API requires and which keeps the prompt cache warm.
                self.history.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    reply.text = _text_of(response) or GIVE_UP_REPLY
                    return reply
                self.history.append({"role": "user", "content": self._run_tools(response, reply)})
            reply.text = GIVE_UP_REPLY
            return reply
        except BaseException:  # API errors, but also Ctrl-C in the middle of a turn
            del self.history[checkpoint:]  # leave history consistent for the next attempt
            raise

    def _call_model(self) -> Any:
        params: dict[str, Any] = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.history,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},  # caches tools + system + history prefix
        )
        if self.model in FALLBACK_CAPABLE_MODELS:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        return self.client.beta.messages.create(**params)

    def _run_tools(self, response: Any, reply: AgentReply) -> list[dict[str, Any]]:
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            arguments = dict(block.input)
            result, is_error = run_tool(self.ctx, block.name, arguments)
            reply.tool_calls.append(ToolCall(block.name, arguments, result, is_error))
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
                "is_error": is_error,
            })
        return results


def _text_of(response: Any) -> str:
    return "\n\n".join(b.text for b in response.content if b.type == "text").strip()


def build_tool_context(settings: Settings) -> ToolContext:
    return ToolContext(
        data=load_store_data(DATA_DIR),
        policies=PolicyManual.from_pdf(POLICY_PDF),
        clock=settings.now,
        handoff_log=RUNTIME_DIR / "handoffs.jsonl",
    )
