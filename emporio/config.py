"""Runtime configuration, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
POLICY_PDF = DATA_DIR / "políticas_da_loja.pdf"
RUNTIME_DIR = ROOT_DIR / "runtime"
CONVERSATIONS_DIR = ROOT_DIR / "conversations"
ENV_FILE = ROOT_DIR / ".env"

DEFAULT_MODEL = "claude-opus-5-5"
# The dataset ends in March 2026, so by default the store's clock is pinned just after the last order.
DEMO_REFERENCE_DATE = "2026-03-25T10:00"
STORE_TZ = ZoneInfo("America/Campo_Grande")


@dataclass(frozen=True)
class Settings:
    model: str
    # Thinking depth/latency trade-off: low | medium | high | xhigh | max.
    effort: str = "low"
    # Fixed "now" for reproducible demos; None means the real clock.
    reference_now: datetime | None = None

    def now(self) -> datetime:
        """Current store-local time (naive), honouring the reference date if set."""
        if self.reference_now is not None:
            return self.reference_now
        return datetime.now(STORE_TZ).replace(tzinfo=None)


def load_settings(env_file: Path = ENV_FILE) -> Settings:
    load_dotenv(env_file)
    # Unset → the demo date; set to an empty value → the real clock.
    raw_now = os.getenv("EMPORIO_REFERENCE_DATE", DEMO_REFERENCE_DATE).strip()
    return Settings(
        model=os.getenv("EMPORIO_MODEL", "").strip() or DEFAULT_MODEL,
        effort=os.getenv("EMPORIO_EFFORT", "").strip() or "low",
        reference_now=datetime.fromisoformat(raw_now) if raw_now else None,
    )
