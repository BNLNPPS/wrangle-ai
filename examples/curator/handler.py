"""The ``curate_page`` handler: the thin event front end the agent registers.

It runs the standalone doer as a subprocess under a hard timeout (the one place a
runaway is actually killed), parses the picks the doer emits, writes them to the
picks store (url-deduped), and returns a small result the bullpen records. This is
the close cousin of a production handler; only the doer's innards (which LLM, which
picks table) differ.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DOER = str(Path(__file__).resolve().parent / "doer_curate.py")


def handle_curate_page(worker, *, picks_store, timeout=600.0, stub=False):
    env = os.environ.copy()
    if stub:
        env["WRANGLE_DEMO_STUB"] = "1"
    proc = subprocess.run([sys.executable, DOER, worker.payload["job_dir"]],
                          capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "doer failed").strip())
    out = json.loads(proc.stdout or "{}")
    picks = out.get("picks", [])
    created = 0
    for p in picks:
        if not p.get("url") or not p.get("title"):
            continue
        p.setdefault("source", worker.payload.get("source") or worker.payload.get("title"))
        if picks_store.add(p, worker.id):
            created += 1
    return {"backend": out.get("backend"), "picks_found": len(picks),
            "created": created, "url": worker.payload.get("url")}
