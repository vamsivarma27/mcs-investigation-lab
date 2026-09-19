from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .case import canonical


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Ledger:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, phase TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, case_hash TEXT NOT NULL, config TEXT NOT NULL, error TEXT,
                    last_event_sequence INTEGER NOT NULL DEFAULT 0,
                    last_event_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_id TEXT, lead_id TEXT NOT NULL,
                    role TEXT NOT NULL, task TEXT NOT NULL, depth INTEGER NOT NULL, status TEXT NOT NULL,
                    private_state TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL,
                    terminated_at TEXT, tool_calls INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL, agent_id TEXT, event_type TEXT NOT NULL,
                    payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence), UNIQUE(event_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, sender TEXT NOT NULL,
                    recipient TEXT NOT NULL, type TEXT NOT NULL, content TEXT NOT NULL,
                    related_evidence TEXT NOT NULL, related_task TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    suspect_id TEXT NOT NULL, claim TEXT NOT NULL, confidence REAL NOT NULL,
                    support TEXT NOT NULL, contradict TEXT NOT NULL, reason TEXT NOT NULL,
                    supersedes TEXT, created_at TEXT NOT NULL, event_sequence INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    text TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accusations (
                    run_id TEXT NOT NULL, agent_id TEXT NOT NULL, stage TEXT NOT NULL,
                    report TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, agent_id, stage)
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    run_id TEXT PRIMARY KEY, result TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if "last_event_sequence" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN last_event_sequence INTEGER NOT NULL DEFAULT 0")
            if "last_event_hash" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN last_event_hash TEXT NOT NULL DEFAULT ''")
            if "last_event_sequence" not in columns or "last_event_hash" not in columns:
                db.execute("""UPDATE runs SET
                    last_event_sequence=COALESCE((SELECT MAX(sequence) FROM events WHERE events.run_id=runs.id),0),
                    last_event_hash=COALESCE((SELECT event_hash FROM events WHERE events.run_id=runs.id
                        ORDER BY sequence DESC LIMIT 1),'')""")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def append(self, run_id: str, event_type: str, payload: dict, agent_id: str | None = None) -> dict:
        with self.lock, self.connect() as db:
            row = db.execute("SELECT sequence,event_hash FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
            sequence = row["sequence"] + 1 if row else 1
            previous_hash = row["event_hash"] if row else "0" * 64
            event = {"event_id": f"{run_id}:{sequence}", "sequence": sequence,
                     "timestamp": utcnow(), "run_id": run_id, "agent_id": agent_id,
                     "event_type": event_type, "payload": payload, "previous_hash": previous_hash}
            event_hash = hashlib.sha256(canonical(event).encode()).hexdigest()
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                       (run_id, sequence, event["event_id"], event["timestamp"], agent_id,
                        event_type, canonical(payload), previous_hash, event_hash))
            db.execute("UPDATE runs SET last_event_sequence=?,last_event_hash=? WHERE id=?",
                       (sequence, event_hash, run_id))
            if sequence % 25 == 0:
                db.execute("INSERT INTO checkpoints VALUES (?,?,?)", (run_id, sequence, event_hash))
            return {**event, "event_hash": event_hash}

    def events(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def verify(self, run_id: str) -> dict:
        events = self.events(run_id)
        previous_hash = "0" * 64
        errors = []
        for index, event in enumerate(events, 1):
            if event["sequence"] != index:
                errors.append(f"sequence {index}")
            if event["previous_hash"] != previous_hash:
                errors.append(f"chain {index}")
            data = {key: event[key] for key in ("event_id", "sequence", "timestamp", "run_id", "agent_id", "event_type", "payload", "previous_hash")}
            expected = hashlib.sha256(canonical(data).encode()).hexdigest()
            if expected != event["event_hash"]:
                errors.append(f"hash {index}")
            previous_hash = event["event_hash"]
        with self.connect() as db:
            checkpoints = db.execute("SELECT * FROM checkpoints WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        by_sequence = {event["sequence"]: event["event_hash"] for event in events}
        for point in checkpoints:
            if by_sequence.get(point["sequence"]) != point["event_hash"]:
                errors.append(f"checkpoint {point['sequence']}")
        with self.connect() as db:
            anchor = db.execute("SELECT last_event_sequence,last_event_hash FROM runs WHERE id=?", (run_id,)).fetchone()
        if anchor and (anchor["last_event_sequence"] != len(events) or anchor["last_event_hash"] != previous_hash):
            errors.append("run anchor")
        return {"valid": not errors, "event_count": len(events), "checkpoint_count": len(checkpoints), "errors": errors}
