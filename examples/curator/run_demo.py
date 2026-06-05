#!/usr/bin/env python3
"""End-to-end smoke run of the example curator — no browser, no LLM, no framework.

Starts the agent in a thread and submits four pages chosen to exercise the core: a
normal page (curated), the same url again (deduped in flight), a poison page (doer
fails -> recorded failed, agent survives), and a live page delivered by ringing the
bell. Then it prints the bullpen rows and picks, asserts the outcomes, and exits
nonzero on any surprise. This doubles as the repo's run-it-and-watch test.

    python run_demo.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import agent as agent_mod
import submit as submit_mod

NORMAL = "[Higgs combination](https://indico.cern.ch/higgs) and [Tracking ML](https://indico.cern.ch/trk)"
POISON = "POISON: this page makes the doer fail on purpose"
LIVE = "[Streaming readout](https://indico.cern.ch/daq)"


def _wait_settled(bullpen, n, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = bullpen.rows()
        if len(rows) >= n and all(r["status"] in ("done", "failed") for r in rows):
            return rows
        time.sleep(0.1)
    return bullpen.rows()


def main():
    work = tempfile.mkdtemp(prefix="wrangle-curator-")
    wrangler, bullpen, picks, bell, _ = agent_mod.build(work, stub=True)

    # Backlog enqueued BEFORE the agent runs, so the first claim batch holds the
    # normal + duplicate(url) + poison together and the in-flight dedup is
    # deterministic regardless of doer speed.
    submit_mod.submit(work, "https://indico.cern.ch/chep", "CHEP agenda", NORMAL,
                      bullpen=bullpen, ring=False)
    submit_mod.submit(work, "https://indico.cern.ch/chep", "CHEP agenda (again)", NORMAL,
                      bullpen=bullpen, ring=False)
    submit_mod.submit(work, "https://indico.cern.ch/poison", "Poison", POISON,
                      bullpen=bullpen, ring=False)

    t = threading.Thread(target=wrangler.run, name="agent", daemon=True)
    t.start()

    # A live page delivered by the bell after the agent is up.
    time.sleep(0.4)
    submit_mod.submit(work, "https://indico.cern.ch/daq", "DAQ", LIVE,
                      bullpen=bullpen, ring=True)

    rows = _wait_settled(bullpen, 4)
    wrangler.request_stop()
    t.join(timeout=5)

    print("\n=== workers ===")
    for r in rows:
        print(f"  {r['status']:7} {r['type']:12} {r['error'] or r['result'] or ''}")
    print("=== picks ===")
    for p in picks.all():
        print(f"  {p['title']}  <{p['url']}>")

    # The demo is also the test.
    failed = [r for r in rows if r["status"] == "failed"]
    skipped = [r for r in rows if r["status"] == "done" and r["result"] and '"skipped"' in r["result"]]
    pick_urls = {p["url"] for p in picks.all()}
    ok = (len(rows) == 4 and len(failed) == 1 and len(skipped) == 1
          and pick_urls == {"https://indico.cern.ch/higgs",
                            "https://indico.cern.ch/trk",
                            "https://indico.cern.ch/daq"})
    shutil.rmtree(work, ignore_errors=True)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
