"""Interactive command-line chat with the store agent."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from emporio.agent import AgentReply, StoreAgent, build_tool_context
from emporio.config import RUNTIME_DIR, load_settings
from emporio.prompts import PERSONA_NAME
from emporio.transcript import Transcript, format_tool_call

EXIT_COMMANDS = {"/sair", "/exit", "/quit"}
HELP = "Comandos: /novo (nova conversa) · /debug (mostrar ferramentas) · /sair"

console = Console()


def _print_debug(reply: AgentReply) -> None:
    for call in reply.tool_calls:
        preview = json.dumps(call.result, ensure_ascii=False)
        if len(preview) > 300:
            preview = preview[:300] + "…"
        console.print(f"  [yellow]🔧 {format_tool_call(call)}[/]\n  [dim]{preview}[/]")
    u = reply.usage
    console.print(
        f"  [dim]{u.model_calls} model call(s) · in {u.input_tokens} · cache read {u.cache_read_tokens} · "
        f"cache write {u.cache_write_tokens} · out {u.output_tokens} tokens[/]"
    )


def _save(transcript: Transcript) -> None:
    if transcript.turns:
        path = RUNTIME_DIR / "transcripts" / f"{datetime.now():%Y%m%d-%H%M%S}.md"
        transcript.save(path)
        console.print(f"[dim]Conversa salva em {path}[/]")


def chat(debug: bool) -> None:
    settings = load_settings()
    try:
        agent = StoreAgent(build_tool_context(settings), settings.model, settings.effort)
    except anthropic.AnthropicError as exc:
        console.print(f"[red]Não foi possível iniciar o cliente da Anthropic:[/] {exc}")
        console.print("Copie .env.example para .env e preencha ANTHROPIC_API_KEY.")
        return

    def new_transcript() -> Transcript:
        return Transcript(title="CLI session", model=settings.model, now=settings.now())

    clock_note = "relógio real" if settings.reference_now is None else f"data simulada {settings.now():%d/%m/%Y %H:%M}"
    console.print(Panel.fit(
        f"[bold]Empório da Música[/] — atendimento virtual ({PERSONA_NAME})\n"
        f"[dim]modelo {settings.model} · effort {settings.effort} · {clock_note}[/]\n[dim]{HELP}[/]",
        border_style="magenta",
    ))
    transcript = new_transcript()
    while True:
        try:
            user_text = console.input("[bold cyan]Você:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not user_text:
            continue
        if user_text.lower() in EXIT_COMMANDS:
            break
        if user_text.lower() == "/novo":
            _save(transcript)
            agent.reset()
            transcript = new_transcript()
            console.print("[dim]Nova conversa iniciada.[/]")
            continue
        if user_text.lower() == "/debug":
            debug = not debug
            console.print(f"[dim]Debug {'ligado' if debug else 'desligado'}.[/]")
            continue

        try:
            with console.status(f"{PERSONA_NAME} está digitando…"):
                reply = agent.send(user_text)
        except KeyboardInterrupt:
            console.print("[dim]Consulta cancelada.[/]")
            continue
        except TypeError as exc:
            if "authentication method" not in str(exc):
                raise
            console.print(
                "[red]Nenhuma chave da API encontrada. Copie .env.example para .env e preencha ANTHROPIC_API_KEY.[/]"
            )
            break
        except anthropic.AuthenticationError:
            console.print("[red]Chave da API inválida. Verifique ANTHROPIC_API_KEY no arquivo .env.[/]")
            break
        except anthropic.APIConnectionError:
            console.print("[red]Sem conexão com a API. Verifique sua internet e tente de novo.[/]")
            continue
        except anthropic.APIStatusError as exc:
            console.print(f"[red]Erro da API ({exc.status_code}): {exc.message}[/]")
            continue

        transcript.add(user_text, reply)
        if debug:
            _print_debug(reply)
        console.print(Panel(Markdown(reply.text), title=PERSONA_NAME, title_align="left", border_style="green"))
    _save(transcript)


def check_data() -> None:
    settings = load_settings()
    ctx = build_tool_context(settings)
    console.print(f"[bold]Policy sections:[/] {', '.join(ctx.policies.topics)}\n")
    console.print("[bold]Data-quality findings:[/]")
    for issue in ctx.data.quality_report():
        console.print(f"- {issue}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m emporio", description="Chat with Empório da Música's virtual assistant."
    )
    parser.add_argument("--debug", action="store_true", help="show tool calls and token usage for every reply")
    parser.add_argument("--check-data", action="store_true", help="print the data-quality report and exit")
    args = parser.parse_args(argv)
    # Tool failures are logged to a file so tracebacks don't clutter the chat.
    RUNTIME_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=RUNTIME_DIR / "agent.log",
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.check_data:
        check_data()
    else:
        chat(args.debug)
