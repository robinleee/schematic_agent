"""Shared test fixtures."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# agent_runs reads this at import time; set it before any test module imports the API,
# so chat/WS route tests never append fake runs to the live gate metrics log.
os.environ["HERMES_METRICS_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="test_agent_runs_"), "agent_runs.jsonl")
# The API defaults to production mode (API_TOKEN required). Developer machines get
# "offline" from the untracked hardware_ai_expert/.env; a clean checkout or CI does not.
os.environ.setdefault("API_SECURITY_MODE", "offline")


@pytest.fixture(autouse=True)
def _isolate_agent_run_metrics(tmp_path, monkeypatch):
    # The router is importable under two package names; patch whichever copies are loaded.
    for name in ("api.routers.agent_runs", "hardware_ai_expert.api.routers.agent_runs"):
        module = sys.modules.get(name)
        if module is not None:
            monkeypatch.setattr(module, "METRICS_FILE", str(tmp_path / "agent_runs.jsonl"))
