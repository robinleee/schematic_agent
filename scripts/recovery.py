#!/usr/bin/env python3
"""Offline-first recovery planner. Restore is intentionally never executed here."""
import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEO = ROOT / "hardware_ai_expert/data/neo4j/neo4j-community-5.26.0"
CHROMA = ROOT / "chroma_data"
SERVICES = ("neo4j", "chromadb", "api", "ollama")
NEO_ENV = {**os.environ, "JAVA_HOME": os.environ.get("JAVA_HOME") or "/data/tools/jdk-17"}


def plan(action, service, target):
    """Return a human-readable, credential-free operation and required tool."""
    if service == "neo4j":
        admin = NEO / "bin/neo4j-admin"
        if action == "backup":
            return [str(admin), "database", "dump", "neo4j", f"--to-path={target}"], admin
        return [str(admin), "database", "load", "neo4j",
                f"--from-path={target}", "--overwrite-destination=false"], admin
    if service == "chromadb":
        return (["copy offline directory", str(CHROMA), str(target)] if action == "backup"
                else ["restore offline directory", str(target), str(CHROMA)]), None
    return (["no data backup: API is stateless; preserve deployment/configuration separately"]
            if service == "api" and action == "backup" else
            ["no model backup: preserve OLLAMA_MODELS separately"] if action == "backup" else
            ["restart via scripts/start_dev.sh; verify via scripts/healthcheck.sh"]), None


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def offline(service):
    if service == "neo4j":
        tool = NEO / "bin/neo4j"
        if not tool.is_file() or not tool.stat().st_mode & 0o111:
            raise ValueError("Neo4j status tool missing")
        # Nonzero means stopped per neo4j status. Network check catches alternate instances.
        status = subprocess.run([str(tool), "status"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, check=False, env=NEO_ENV)
        return status.returncode != 0 and not port_open(7687) and not port_open(7474)
    # API can fall back to a local PersistentClient even when Chroma's server is down.
    return not (port_open(8000) or port_open(8501))


def checked_path(value):
    if not value:
        raise ValueError("explicit absolute --target required")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("target must be an absolute non-symlink path")
    path = path.resolve()
    if path == Path("/") or path == ROOT or path == CHROMA or path == NEO:
        raise ValueError("target cannot be an active service or repository root")
    if path in CHROMA.parents or path in NEO.parents or CHROMA in path.parents or NEO in path.parents:
        raise ValueError("target overlaps active service data")
    return path


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("service", choices=SERVICES)
    parser.add_argument("--target", help="absolute backup destination or restore source")
    parser.add_argument("--confirm", help="restore: exact text RESTORE <service> <target>")
    parser.add_argument("--execute", action="store_true", help="execute offline backup only")
    args = parser.parse_args(argv)
    try:
        # Restore plans always require explicit source and exact confirmation.
        target = checked_path(args.target) if args.target else None
        if args.action == "restore":
            if target is None or args.confirm != f"RESTORE {args.service} {target}":
                raise ValueError("restore requires --target and exact --confirm 'RESTORE <service> <target>'")
            if args.execute:
                raise ValueError("restore execution is disabled; use reviewed manual procedure")
        if args.action == "backup" and args.service in ("neo4j", "chromadb") and target is None:
            raise ValueError("backup requires explicit --target")
        if args.execute and args.service in ("api", "ollama"):
            raise ValueError("no supported data backup for this process service")
        command, tool = plan(args.action, args.service, target)
        if tool is not None and (not tool.is_file() or not tool.stat().st_mode & 0o111):
            raise ValueError("Neo4j admin tool missing; cannot construct executable operation")
        if args.execute:
            if not offline(args.service):
                raise ValueError("service is running; stop it and verify offline before backup")
            if target.exists():
                raise ValueError("backup destination already exists; never overwrite")
            if not target.parent.is_dir() or target.parent.is_symlink():
                raise ValueError("backup parent directory missing or symlinked")
            if args.service == "neo4j":
                # neo4j-admin requires an existing output directory.
                target.mkdir()
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=NEO_ENV)
            else:
                if not CHROMA.is_dir() or CHROMA.is_symlink():
                    raise ValueError("ChromaDB data directory missing or symlinked")
                if any(p.is_symlink() for p in CHROMA.rglob("*")):
                    raise ValueError("ChromaDB source contains symlinks; refuse to follow them")
                shutil.copytree(CHROMA, target, symlinks=False)
            print("Backup command completed; verify artifact separately (not a restore drill).")
        else:
            print("DRY RUN / DESCRIPTION ONLY:", " ".join(command))
            if args.action == "restore":
                print("Restore NOT performed. Review source, version, downtime and rollback before manual work.")
            elif args.service in ("neo4j", "chromadb"):
                print("Offline backup only; --execute requires stopped service and new destination.")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Never print subprocess arguments, environment, or raw exception text.
        print(f"Unavailable: {exc}" if isinstance(exc, ValueError) else
              "Unavailable: filesystem/tool operation failed (details suppressed)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
