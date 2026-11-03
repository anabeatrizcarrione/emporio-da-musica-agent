from datetime import datetime

import pytest

from emporio.config import DATA_DIR, POLICY_PDF
from emporio.data import load_store_data
from emporio.policies import PolicyManual
from emporio.tools import ToolContext

DEMO_NOW = datetime(2026, 3, 25, 10, 0)  # Wednesday, store open


@pytest.fixture(scope="session")
def store_data():
    return load_store_data(DATA_DIR)


@pytest.fixture(scope="session")
def policies():
    return PolicyManual.from_pdf(POLICY_PDF)


@pytest.fixture
def make_ctx(store_data, policies, tmp_path):
    def factory(now: datetime = DEMO_NOW) -> ToolContext:
        return ToolContext(store_data, policies, clock=lambda: now, handoff_log=tmp_path / "handoffs.jsonl")

    return factory


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()
