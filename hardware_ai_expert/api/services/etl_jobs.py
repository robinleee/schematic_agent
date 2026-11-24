"""SQLite-backed ETL job ledger, safe across threads and processes."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "etl_jobs.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path=None):
        self.path = str(path or os.environ.get("ETL_JOB_DB", DEFAULT_DB))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS etl_jobs (
                job_id TEXT PRIMARY KEY, project_name TEXT NOT NULL,
                status TEXT NOT NULL, step TEXT NOT NULL, progress REAL NOT NULL,
                message TEXT NOT NULL, error TEXT, result TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                owner_pid INTEGER NOT NULL, owner_start TEXT NOT NULL)""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, project_name):
        job_id = uuid4().hex
        timestamp = now()
        with self.connect() as db:
            db.execute("INSERT INTO etl_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (job_id, project_name, "queued", "pending", 0, "Waiting for worker",
                        None, None, timestamp, timestamp, os.getpid(), _process_start()))
        return job_id

    def update(self, job_id, status, step, progress, message, error=None, result=None,
               expected=("queued", "running")):
        with self.connect() as db:
            placeholders = ",".join("?" for _ in expected)
            cursor = db.execute(
                f"""UPDATE etl_jobs SET status=?, step=?, progress=?, message=?,
                    error=?, result=?, updated_at=?
                    WHERE job_id=? AND status IN ({placeholders})""",
                (status, step, progress, message, error,
                 json.dumps(result) if result is not None else None, now(), job_id, *expected))
            return cursor.rowcount == 1

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM etl_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        if record["status"] in ("queued", "running") and (
            record["owner_pid"] != os.getpid() or record["owner_start"] != _process_start()
        ) and not _owner_alive(record["owner_pid"], record["owner_start"]):
            self.update(job_id, "cancelled", record["step"], record["progress"],
                        "Worker exited before completing the job", "Worker process stopped")
            return self.get(job_id)
        record["result"] = json.loads(record["result"]) if record["result"] else None
        return record


def _process_start():
    # Linux PID reuse protection; fallback keeps the PID for other platforms.
    try:
        return Path(f"/proc/{os.getpid()}/stat").read_text().split(") ")[1].split()[19]
    except OSError:
        return str(os.getpid())


def _owner_alive(pid, start):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1].split()[19] == start
    except OSError:
        return False
