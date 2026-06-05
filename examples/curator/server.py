#!/usr/bin/env python3
"""Local curate endpoint + picks viewer — the web-tier cousin, for the extension.

Receives a page (or an Indico event's exported JSON) from the browser extension,
stages it, drops a worker in the bullpen, rings the bell. Holds NO LLM credentials —
the agent (run separately, same --work dir) does the curated work. Serves the picks
at /picks.

    python server.py [--work DIR] [--port 8765] [--token TOKEN]

The token (printed on startup; default $WRANGLE_TOKEN, else generated into the work
dir) must match the one you set in the extension. Localhost only — bound to 127.0.0.1.
This process never authenticates to anyone; the browser does, then hands the agent
the bytes. That is the whole point: the server reaches no protected site.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import fetch_indico
import submit as submit_mod
from store import PicksStore, SqliteBullpen


class Curator(BaseHTTPRequestHandler):
    work = None
    token = None
    bullpen = None
    picks = None

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/picks":
            return self._picks_page()
        self._json(200, {"ok": True, "hint": "POST /curate (Bearer token), GET /picks"})

    def do_POST(self):
        if self.path.split("?")[0] != "/curate":
            return self._json(404, {"error": "not found"})
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.token:
            return self._json(403, {"error": "bad or missing token"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": f"bad body: {e}"})

        url = (body.get("url") or "").strip()
        if not url:
            return self._json(400, {"error": "url required"})
        title = body.get("title") or ""
        content = body.get("content") or ""
        interests = body.get("interests") or ""

        # 'indico': content is the event's exported JSON, fetched by the browser in
        # the user's session (protected events included). Digest it for the LLM.
        if body.get("mode") == "indico" and content:
            try:
                eid = fetch_indico.event_id(url)
                page = fetch_indico.digest(json.loads(content), "https://indico.cern.ch", eid)
            except Exception as e:
                return self._json(400, {"error": f"indico digest failed: {e}"})
        else:
            page = content

        wid = submit_mod.submit(str(self.work), url, title, page,
                                source=body.get("source"), interests=interests,
                                bullpen=self.bullpen, ring=True)
        self._json(200, {"status": "queued", "worker": wid})

    def _picks_page(self):
        rows = self.picks.all()
        items = "\n".join(
            f'<li><a href="{html.escape(p["url"])}">{html.escape(p["title"])}</a>'
            f'<span class="src">{html.escape(p.get("source") or "")}</span></li>'
            for p in rows)
        page = f"""<!doctype html><meta charset=utf-8>
<title>my picks</title>
<style>
 body{{background:#15171c;color:#e6e6e6;font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
 h1{{color:#d8a070;font-size:20px}} a{{color:#7db4ff;text-decoration:none}} a:hover{{text-decoration:underline}}
 li{{margin:.5rem 0}} .src{{color:#9aa;font-size:13px;margin-left:.5rem}}
</style>
<h1>my picks &middot; {len(rows)}</h1>
<ol>{items}</ol>"""
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quieter
        sys.stderr.write("server: " + (a[0] % a[1:]) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(pathlib.Path(__file__).resolve().parent / ".curator"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=None)
    a = ap.parse_args()

    work = pathlib.Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    import os
    token = a.token or os.getenv("WRANGLE_TOKEN")
    if not token:
        tf = work / "token.txt"
        token = tf.read_text().strip() if tf.exists() else secrets.token_urlsafe(18)
        tf.write_text(token)

    Curator.work = work
    Curator.token = token
    Curator.bullpen = SqliteBullpen(str(work / "curator.db"))
    Curator.picks = PicksStore(str(work / "curator.db"))

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Curator)
    print(f"curate endpoint: http://127.0.0.1:{a.port}/curate")
    print(f"picks view:      http://127.0.0.1:{a.port}/picks")
    print(f"token:           {token}")
    print("(set this token in the extension; run agent.py with the same --work)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
