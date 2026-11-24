"""Task 4 tests use temporary SQLite and fake ETL; never connect to Neo4j."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import sleep

from fastapi.testclient import TestClient

from hardware_ai_expert.api.main import app
from hardware_ai_expert.api import dependencies
from hardware_ai_expert.api.services.etl_jobs import JobStore
from hardware_ai_expert.api.services import uploads
from agent_system import etl_web_bridge

client = TestClient(app)
BASE = "/api/v1"


def fixture_files():
    return {name: ("same.dat", name.encode()) for name in ("pstxnet", "pstxprt", "pstchip")}


def wait_for(job):
    for _ in range(100):
        result = client.get(BASE + "/etl/progress/" + job).json()
        if result["status"] not in ("queued", "running"):
            return result
        sleep(.02)
    raise AssertionError("job did not complete")


def test_invalid_upload_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    from hardware_ai_expert.api.routers import etl
    assert client.post(BASE + "/etl/preview", files={
            **fixture_files(), "bom": ("../escape.exe", b"x")}).status_code == 400
    monkeypatch.setattr(etl, "ETL_LIMIT", 2)
    assert client.post(BASE + "/etl/run", files=fixture_files()).status_code == 413
    assert client.get(BASE + "/etl/progress/unknown").status_code == 404
    assert list(tmp_path.glob("*.dat")) == []
    assert JobStore().get("unknown") is None


def test_concurrent_jobs_restart_and_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    seen = []
    gate = Event()

    class FakeExecutor:
        def run_etl(self, paths, project):
            seen.append((project, {name: Path(path).read_bytes() for name, path in paths.items()},
                         list(paths.values())))
            gate.wait(2)
            return {"success": project != "bad", "quality_passed": project != "bad",
                    "message": "quality failed" if project == "bad" else "done",
                    "quality_report": {"passed": project != "bad", "summary": {"total_components": 3}}}

    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", FakeExecutor)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda name: client.post(BASE + "/etl/run",
                        files=fixture_files(), data={"project_name": name}).json()["job_id"],
                        ["ok", "bad"]))
    assert len(set(jobs)) == 2
    assert all(client.get(BASE + "/etl/progress/" + job).json()["progress"] < 100 for job in jobs)
    gate.set()
    ok, bad = map(wait_for, jobs)
    assert ok["status"] == "succeeded" and ok["progress"] == 100
    assert bad["status"] == "failed" and bad["progress"] < 100
    assert bad["result"]["quality_report"]["passed"] is False
    assert len(seen) == 2
    assert all(paths == {"pstxnet": b"pstxnet", "pstxprt": b"pstxprt",
                         "pstchip": b"pstchip"} for _, paths, _ in seen)
    assert len({p for _, _, paths in seen for p in paths}) == 6
    assert all(not Path(p).exists() for _, _, paths in seen for p in paths)
    assert JobStore().get(jobs[0])["status"] == "succeeded"
    store = JobStore()
    orphan = store.create("orphan")
    with store.connect() as db:
        db.execute("UPDATE etl_jobs SET owner_pid=? WHERE job_id=?", (99999999, orphan))
    assert JobStore().get(orphan)["status"] == "cancelled"


def test_knowledge_size_and_cleanup(monkeypatch, tmp_path):
    from hardware_ai_expert.api.routers import knowledge
    monkeypatch.setattr(knowledge, "KNOWLEDGE_LIMIT", 2)
    monkeypatch.setattr(dependencies, "get_knowledge_router",
                        lambda **scope: type("Fake", (), {"upload_document": lambda self, **kw:
                            (_ for _ in ()).throw(ValueError("invalid"))})())
    assert client.post(BASE + "/knowledge/upload", data={"mpn": "M", "project_id": "A"},
                       files={"file": ("a.txt", b"abcd")}).status_code == 413
    assert client.post(BASE + "/knowledge/upload", data={"mpn": "M", "project_id": "A"},
                       files={"file": ("a.txt", b"a")}).status_code == 400


def test_worker_exception_and_queue_timeout(monkeypatch, tmp_path):
    from hardware_ai_expert.api.routers import etl
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))

    class Broken:
        def run_etl(self, paths, name):
            raise RuntimeError("private /secret/path")

    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", Broken)
    job = client.post(BASE + "/etl/run", files=fixture_files()).json()["job_id"]
    progress = wait_for(job)
    assert progress["status"] == "failed"
    assert "/secret/" not in progress["error"]
    store = JobStore()
    queued = store.create("waiting")
    with store.connect() as db:
        db.execute("UPDATE etl_jobs SET created_at=? WHERE job_id=?",
                   ("2020-01-01T00:00:00+00:00", queued))
    monkeypatch.setenv("ETL_QUEUE_TIMEOUT_SECONDS", "3600")
    etl._run_job(store, queued, {}, "waiting")
    assert JobStore().get(queued)["status"] == "timeout"
    assert client.get(BASE + "/etl/progress/" + queued).json()["progress"] == 0

    class NoQueue:
        def submit(self, *args):
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(etl, "_workers", NoQueue())
    response = client.post(BASE + "/etl/run", files=fixture_files())
    assert response.status_code == 503
    with store.connect() as db:
        record = db.execute("SELECT job_id FROM etl_jobs WHERE message='Could not schedule ETL'").fetchone()
    assert record is not None
    assert client.get(BASE + "/etl/progress/" + record["job_id"]).json()["status"] == "failed"


def test_real_process_restart_and_orphan_upload_recovery(monkeypatch, tmp_path):
    """The writer really exits without finally; reader is a distinct Python process."""
    db = tmp_path / "jobs.sqlite3"
    root = tmp_path / "private-uploads"
    env = dict(os.environ, ETL_JOB_DB=str(db), UPLOAD_STAGING_DIR=str(root))
    writer = """
import asyncio, json, os
from io import BytesIO
from starlette.datastructures import UploadFile
from hardware_ai_expert.api.services.etl_jobs import JobStore
from hardware_ai_expert.api.services.uploads import stage
s = JobStore()
completed = s.create("done")
s.update(completed, "succeeded", "completed", 100, "done", result={"success": True})
running = s.create("unfinished")
s.update(running, "running", "parsing", 5, "working")
path = asyncio.run(stage(UploadFile(filename="same.dat", file=BytesIO(b"ab")),
                         {".dat"}, 20))
os.write(1, (json.dumps({"completed": completed, "running": running,
                          "path": path}) + "\\n").encode())
os._exit(0)
"""
    created = subprocess.run([sys.executable, "-c", writer], cwd=str(Path(__file__).parents[2]),
                             env=env, capture_output=True, text=True, check=True, timeout=15)
    info = json.loads(created.stdout)
    assert Path(info["path"]).exists()  # hard exit bypasses finally
    reader = """
import json, os
from hardware_ai_expert.api.services.etl_jobs import JobStore
s = JobStore()
os.write(1, (json.dumps([s.get(os.environ["DONE"])["status"],
                          s.get(os.environ["RUNNING"])["status"]]) + "\\n").encode())
"""
    read = subprocess.run([sys.executable, "-c", reader], cwd=str(Path(__file__).parents[2]),
                          env=dict(env, DONE=info["completed"], RUNNING=info["running"]),
                          capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(read.stdout) == ["succeeded", "cancelled"]
    assert JobStore(db).get(info["running"])["error"] == "Worker process stopped"

    # A separate *live* process keeps its upload; reclamation must not touch it.
    live_script = """
import asyncio, json, sys
from io import BytesIO
from starlette.datastructures import UploadFile
from hardware_ai_expert.api.services.uploads import stage, cleanup
path = asyncio.run(stage(UploadFile(filename="same.dat", file=BytesIO(b"live")),
                         {".dat"}, 20))
print(path, flush=True)
sys.stdin.readline()
cleanup([path])
"""
    live = subprocess.Popen([sys.executable, "-c", live_script],
                            cwd=str(Path(__file__).parents[2]), env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        live_path = Path(live.stdout.readline().strip())
        assert live_path.exists()
        monkeypatch.setenv("UPLOAD_STAGING_DIR", str(root))
        assert uploads.reclaim_orphans(grace_seconds=3600) == 0
        assert Path(info["path"]).exists()  # new orphan remains during grace period
        assert uploads.reclaim_orphans(grace_seconds=0) == 1
        assert not Path(info["path"]).exists()
        assert live_path.read_bytes() == b"live"
    finally:
        live.stdin.write("\n")
        live.stdin.flush()
        assert live.wait(timeout=15) == 0


def test_orphan_sweep_is_bounded_and_does_not_touch_foreign_files(monkeypatch, tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(root))
    foreign = root / "user-data.dat"
    foreign.write_bytes(b"preserve")
    directory = root / "worker-dead"
    directory.mkdir(mode=0o700)
    (directory / ".owner").write_text(json.dumps({"pid": 99999999, "start": "old"}))
    (directory / "hardware-upload-test.dat").write_bytes(b"owned")
    (directory / "other.txt").write_bytes(b"not ours")
    assert uploads.reclaim_orphans(grace_seconds=0, max_dirs=128) == 0
    assert foreign.read_bytes() == b"preserve"
    assert (directory / "hardware-upload-test.dat").exists()
