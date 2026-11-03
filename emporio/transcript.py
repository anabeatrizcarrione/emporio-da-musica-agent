"""Render conversations as Markdown, including which tools the agent used."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from emporio.agent import AgentReply, ToolCall
from emporio.prompts import PERSONA_NAME
from emporio.store import WEEKDAY_NAMES


def format_tool_call(call: ToolCall) -> str:
    args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in call.arguments.items())
    marker = " (error)" if call.is_error else ""
    return f"{call.name}({args}){marker}"


@dataclass
class Transcript:
    title: str
    model: str
    now: datetime
    description: str = ""
    turns: list[tuple[str, AgentReply]] = field(default_factory=list)

    def add(self, user_text: str, reply: AgentReply) -> None:
        self.turns.append((user_text, reply))

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        if self.description:
            lines += [self.description, ""]
        lines += [
            f"*Model: `{self.model}` · Simulated store time: {WEEKDAY_NAMES[self.now.weekday()]}, "
            f"{self.now:%d/%m/%Y %H:%M}*",
            "",
            "---",
        ]
        for user_text, reply in self.turns:
            lines += ["", f"**Cliente:** {user_text}", ""]
            if reply.tool_calls:
                lines += [f"> 🔧 `{format_tool_call(c)}`  " for c in reply.tool_calls]
                lines.append("")
            lines += [f"**{PERSONA_NAME}:** {reply.text}", "", "---"]
        return "\n".join(lines) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
