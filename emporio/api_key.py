"""Start-up step of the terminal programs: make sure an Anthropic API key is available.

Kept apart from config.py, which only reads settings: this asks on the terminal and can end the program,
so only the entry points (chat, scenarios, red-team runner) call it.
"""

from __future__ import annotations

import getpass
import os


def ensure_api_key() -> None:
    """Ask for the API key if none is configured. It is kept in memory for this session only."""
    current = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if current and not current.endswith("..."):  # "sk-ant-..." is the template's placeholder
        return
    print("Nenhuma chave da API da Anthropic encontrada (crie uma em https://console.anthropic.com).")
    print("Ela só é usada nesta sessão e não é salva.")
    try:
        key = getpass.getpass("Cole a sua chave e pressione Enter (ela não aparece na tela): ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    if not key:
        raise SystemExit("\nNenhuma chave informada. Encerrando.")
    os.environ["ANTHROPIC_API_KEY"] = key
