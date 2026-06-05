#!/usr/bin/env python3
"""Submit a page to the curator — the web-tier cousin.

Stages a job dir (meta.json + page.txt [+ interests.txt]), drops a worker in the
bullpen, rings the bell. Holds no credentials, runs nothing privileged — exactly the
boundary the real extension + endpoint keep.

    python submit.py --url https://indico.cern.ch/event/<chep>/ --title "CHEP agenda" \\
                     --interests interests.txt --fetch
    echo "[A](https://a.org) [B](https://b.org)" | python submit.py --url u --title t

--fetch GETs the URL for its text (fine for a public agenda); otherwise the page
text comes from the file arg or stdin (e.g. piped from the browser extension).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from bell import FifoBell
from store import SqliteBullpen

DEFAULT_WORK = pathlib.Path(__file__).resolve().parent / ".curator"


def submit(work_dir, url, title, page_text, *, source=None, interests="",
           bullpen=None, ring=True):
    work = pathlib.Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    job_dir = work / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "meta.json").write_text(json.dumps({"url": url, "title": title, "source": source}))
    (job_dir / "page.txt").write_text(page_text or "")
    if interests:
        (job_dir / "interests.txt").write_text(interests)
    bp = bullpen or SqliteBullpen(str(work / "curator.db"))
    wid = bp.enqueue("curate_page", {"url": url, "title": title, "source": source,
                                     "job_dir": str(job_dir)})
    if ring:
        FifoBell.ring(str(work / "bell.fifo"))
    return wid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", help="page text file (default: stdin unless --fetch)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--source", default=None)
    ap.add_argument("--interests", default=None, help="interests text file")
    ap.add_argument("--fetch", action="store_true", help="GET --url for the page text")
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    a = ap.parse_args()
    if a.fetch:
        with urllib.request.urlopen(a.url, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    elif a.page:
        text = pathlib.Path(a.page).read_text()
    else:
        text = sys.stdin.read()
    interests = pathlib.Path(a.interests).read_text() if a.interests else ""
    wid = submit(a.work, a.url, a.title, text, source=a.source, interests=interests)
    print(f"submitted worker {wid}")


if __name__ == "__main__":
    main()
