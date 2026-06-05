#!/usr/bin/env python3
"""Fetch an Indico event as an LLM-friendly digest.

The standard timetable view — the whole conference on one page — is the human's
favorite and the LLM's nightmare. Indico's HTTP export API carries the same content
as structured JSON; this turns it into a compact text digest, one block per
contribution (title, track/session, speakers, a trimmed abstract, and the
contribution URL), which is what the curator's doer reads.

    python fetch_indico.py 1471803 > page.txt
    python fetch_indico.py https://indico.cern.ch/event/1471803/timetable/?view-standard

Works on any public Indico event; no credentials. It is also the server-side answer
for the browser extension: the human invokes the picker on their favorite timetable
page, and we resolve that URL to this clean export rather than scraping the HTML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def event_id(s):
    m = re.search(r"event/(\d+)", s)
    return m.group(1) if m else s


def fetch(eid, base):
    url = f"{base}/export/event/{eid}.json?detail=contributions&pretty=no"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _label(c):
    t = c.get("track")
    if isinstance(t, dict):
        t = t.get("title")
    s = c.get("session")
    if isinstance(s, dict):
        s = s.get("title")
    return t or s or ""


def _people(c):
    names = []
    for p in (c.get("speakers") or []):
        n = p.get("fullName") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")]))
        if n:
            names.append(n.strip())
    return ", ".join(names)


def _abstract(c, n):
    return _WS.sub(" ", _TAG.sub(" ", c.get("description") or "")).strip()[:n]


def digest(data, base, eid, abstract_chars=400):
    results = data.get("results") or []
    if not results:
        return ""
    ev = results[0]
    out = [f"# {ev.get('title', '')}", f"({ev.get('startDate', {}).get('date', '')})", ""]
    for c in (ev.get("contributions") or []):
        title = (c.get("title") or "").strip()
        if not title:
            continue
        url = c.get("url") or f"{base}/event/{eid}/contributions/{c.get('id', '')}/"
        line = f"- {title}"
        label = _label(c)
        if label:
            line += f"  [{label}]"
        people = _people(c)
        if people:
            line += f"  — {people}"
        line += f"\n  {url}"
        abstract = _abstract(c, abstract_chars)
        if abstract:
            line += f"\n  {abstract}"
        out.append(line)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event", help="event id or any Indico event URL")
    ap.add_argument("--base", default="https://indico.cern.ch")
    ap.add_argument("--abstract-chars", type=int, default=400)
    a = ap.parse_args()
    eid = event_id(a.event)
    sys.stdout.write(digest(fetch(eid, a.base), a.base, eid, a.abstract_chars))


if __name__ == "__main__":
    main()
