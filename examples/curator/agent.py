#!/usr/bin/env python3
"""Run the example curator agent: a Wrangler over a SQLite bullpen and a FIFO bell.

This is the wrangle-ai side — used directly, exactly as a production consumer uses
it. Only the bullpen/bell implementations and the handler's doer differ between this
example and a real deployment.

    python agent.py [work_dir]

Leave it running; submit pages with submit.py (or run run_demo.py for the whole
thing in one command). Set WRANGLE_LLM=claude|anthropic|openai (and the matching
key) to choose the curation backend; default is claude if present, else stub.
"""
from __future__ import annotations

import functools
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from wrangle_ai import Wrangler

from bell import FifoBell
from handler import handle_curate_page
from store import PicksStore, SqliteBullpen

DEFAULT_WORK = pathlib.Path(__file__).resolve().parent / ".curator"


def build(work_dir, *, stub=False, max_workers=4):
    work = pathlib.Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    db = str(work / "curator.db")
    bullpen = SqliteBullpen(db)
    picks = PicksStore(db)
    bell = FifoBell(str(work / "bell.fifo"))
    wrangler = Wrangler(bullpen, bell, max_workers=max_workers, idle_timeout=5.0, name="curator")
    wrangler.register(
        "curate_page",
        functools.partial(handle_curate_page, picks_store=picks, timeout=600.0, stub=stub),
        timeout=600.0,
        key_fn=lambda w: f"curate:{w.payload.get('url')}",
    )
    return wrangler, bullpen, picks, bell, work


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    ap.add_argument("--max-workers", type=int, default=4)
    a = ap.parse_args()
    wrangler, *_ = build(a.work, max_workers=a.max_workers)
    raise SystemExit(wrangler.run())


if __name__ == "__main__":
    main()
