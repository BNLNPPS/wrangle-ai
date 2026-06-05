"""SQLite Bullpen + a tiny picks store for the example curator.

The Bullpen is the wrangle-ai seam: it implements claim_pending / mark_done /
mark_failed over a ``workers`` table — the durable source of truth. It is the close
cousin of tjai's Postgres bullpen: same row-as-truth, same status transitions, same
crash recovery, the only real difference being SQLite's transaction in place of
``FOR UPDATE SKIP LOCKED``.

PicksStore is app data: where curated picks land (url-unique, so re-curating a page
never duplicates). In a production consumer this is the app's own picks table.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from wrangle_ai import Worker

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    result     TEXT,
    error      TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    claimed_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS workers_status ON workers(status);

CREATE TABLE IF NOT EXISTS picks (
    url        TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    precis     TEXT,
    rationale  TEXT,
    source     TEXT,
    worker_id  TEXT,
    created_at REAL NOT NULL
);
"""


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.isolation_level = None  # autocommit; we manage the one real transaction by hand
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path):
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


class SqliteBullpen:
    """Implements the wrangle_ai.Bullpen protocol over a SQLite ``workers`` table."""

    def __init__(self, db_path, *, stale_after=1800.0):
        self.db_path = db_path
        self.stale_after = stale_after
        init_db(db_path)

    # producer side (the submit / web tier) -------------------------------
    def enqueue(self, worker_type, payload):
        wid = str(uuid.uuid4())
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO workers (id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                (wid, worker_type, json.dumps(payload), time.time()),
            )
        finally:
            conn.close()
        return wid

    # wrangle-ai Bullpen protocol -----------------------------------------
    def claim_pending(self, limit):
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # crash recovery: anything left running past the TTL is claimable again.
            conn.execute(
                "UPDATE workers SET status='pending', claimed_at=NULL "
                "WHERE status='running' AND claimed_at < ?",
                (time.time() - self.stale_after,),
            )
            rows = conn.execute(
                "SELECT id, type, payload, attempts FROM workers "
                "WHERE status='pending' ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
            now = time.time()
            workers = []
            for r in rows:
                conn.execute(
                    "UPDATE workers SET status='running', claimed_at=?, attempts=attempts+1 WHERE id=?",
                    (now, r["id"]),
                )
                workers.append(Worker(id=r["id"], type=r["type"],
                                      payload=json.loads(r["payload"]),
                                      attempts=r["attempts"] + 1))
            conn.execute("COMMIT")
            return workers
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def mark_done(self, worker_id, result):
        self._finish(worker_id, "done", result=result)

    def mark_failed(self, worker_id, error):
        self._finish(worker_id, "failed", error=error)

    def _finish(self, worker_id, status, *, result=None, error=None):
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "UPDATE workers SET status=?, result=?, error=?, claimed_at=NULL WHERE id=?",
                (status, json.dumps(result) if result is not None else None, error, worker_id),
            )
        finally:
            conn.close()

    # read side (for run_demo / a status view) ----------------------------
    def rows(self):
        conn = _connect(self.db_path)
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id, type, status, result, error FROM workers ORDER BY created_at")]
        finally:
            conn.close()


class PicksStore:
    """Where curated picks land. url is the primary key, so re-curating never dups."""

    def __init__(self, db_path):
        self.db_path = db_path
        init_db(db_path)

    def add(self, pick, worker_id):
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO picks (url, title, precis, rationale, source, worker_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pick.get("url"), pick.get("title"), pick.get("precis"),
                 pick.get("rationale"), pick.get("source"), worker_id, time.time()),
            )
            return cur.rowcount > 0  # newly inserted (not a duplicate url)
        finally:
            conn.close()

    def all(self):
        conn = _connect(self.db_path)
        try:
            return [dict(r) for r in conn.execute(
                "SELECT url, title, source FROM picks ORDER BY created_at")]
        finally:
            conn.close()
