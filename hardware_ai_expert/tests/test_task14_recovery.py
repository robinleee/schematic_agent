"""Offline recovery-plan checks; no backup/restore command is run against real services."""
import asyncio
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("recovery", ROOT / "scripts/recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def test_neo4j_command_construction(tmp_path):
    dump, tool = recovery.plan("backup", "neo4j", tmp_path / "snapshot")
    assert dump == [str(tool), "database", "dump", "neo4j",
                    f"--to-path={tmp_path / 'snapshot'}"]
    load, _ = recovery.plan("restore", "neo4j", tmp_path / "snapshot")
    assert load[-2:] == [f"--from-path={tmp_path / 'snapshot'}",
                         "--overwrite-destination=false"]
    assert "password" not in " ".join(dump + load).lower()


def test_restore_requires_source_confirmation_and_never_executes(tmp_path, monkeypatch, capsys):
    source = tmp_path / "snapshot"
    monkeypatch.setattr(recovery, "NEO", tmp_path / "missing")
    assert recovery.run(["restore", "chromadb"]) == 2
    assert recovery.run(["restore", "chromadb", "--target", str(source)]) == 2
    confirm = f"RESTORE chromadb {source}"
    assert recovery.run(["restore", "chromadb", "--target", str(source),
                         "--confirm", confirm]) == 0
    assert "NOT performed" in capsys.readouterr().out
    assert recovery.run(["restore", "chromadb", "--target", str(source),
                         "--confirm", confirm, "--execute"]) == 2


def test_missing_config_tools_and_non_overwrite(tmp_path, monkeypatch, capsys):
    target = tmp_path / "new"
    monkeypatch.setattr(recovery, "NEO", tmp_path / "missing")
    assert recovery.run(["backup", "neo4j", "--target", str(target)]) == 2
    assert recovery.run(["backup", "chromadb"]) == 2
    assert recovery.run(["backup", "api", "--execute"]) == 2
    assert recovery.run(["backup", "ollama", "--execute"]) == 2
    assert recovery.run(["backup", "chromadb", "--target", "relative"]) == 2
    target.mkdir()
    monkeypatch.setattr(recovery, "offline", lambda service: True)
    assert recovery.run(["backup", "chromadb", "--target", str(target),
                         "--execute"]) == 2
    assert "never overwrite" in capsys.readouterr().err


def test_backup_dry_run_and_offline_guard(tmp_path, monkeypatch, capsys):
    target = tmp_path / "new"
    monkeypatch.setattr(recovery, "CHROMA", tmp_path / "source")
    assert recovery.run(["backup", "chromadb", "--target", str(target)]) == 0
    assert not target.exists()
    assert "DRY RUN" in capsys.readouterr().out
    monkeypatch.setattr(recovery, "offline", lambda service: False)
    assert recovery.run(["backup", "chromadb", "--target", str(target),
                         "--execute"]) == 2
    assert not target.exists()


def test_healthcheck_degraded_and_recovered_without_network(tmp_path):
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\ncase \"$*\" in\n  *8000*) exit 1;;\n  *) exit 0;;\nesac\n")
    curl.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}
    script = str(ROOT / "scripts/healthcheck.sh")
    degraded = subprocess.run(["bash", script], env=env, capture_output=True, text=True)
    assert degraded.returncode == 1
    assert "FAIL ChromaDB" in degraded.stdout
    assert "DEGRADED: 3/4 services" in degraded.stdout
    curl.write_text("#!/bin/sh\nexit 0\n")
    healthy = subprocess.run(["bash", script], env=env, capture_output=True, text=True)
    assert healthy.returncode == 0
    assert "HEALTHY: 4/4 services" in healthy.stdout


def test_system_status_reports_dependency_degraded(monkeypatch):
    import chromadb
    from agent_system import connection_pool
    from hardware_ai_expert.api.routers.system import get_system_status

    def unavailable():
        raise ConnectionError("secret details should not leak")

    monkeypatch.setattr(connection_pool, "get_neo4j_driver", unavailable)
    monkeypatch.setattr(connection_pool, "get_ollama_client", unavailable)
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: unavailable())
    response = asyncio.run(get_system_status())
    statuses = {item.name: item for item in response.data.services}
    assert all(statuses[name].status.value == "degraded"
               for name in ("Neo4j", "Ollama", "ChromaDB"))
    assert statuses["API Server"].status.value == "running"
    assert "secret" not in str(response)
