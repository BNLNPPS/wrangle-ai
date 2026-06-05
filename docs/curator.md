# Build your own curated conference picks

A small, real curator built on wrangle-ai. Point it at a conference agenda — CHEP,
say — and it builds *your* shortlist of the talks and papers worth your time, judged
by the LLM you choose, on your own machine. It is also the worked example of the
whole wrangle-ai pattern: a submit side that holds nothing, and an always-on agent
that does the credentialed work. The code is under
[`examples/curator/`](../examples/curator).

> Run the commands below from the example directory (`cd examples/curator`). You need
> Python 3.10+ and nothing else for the demo; an LLM backend (Claude Code on your
> PATH, or an API key) is needed only for real curation, not the demo.

## 30-second demo (no keys, no browser)

```
python run_demo.py
```

Starts the agent, submits four pages, and prints what happened — a page curated, the
same page again deduped, a poison page recorded failed (the agent shrugs and
continues), and a live page delivered by ringing the bell. It asserts the outcomes
and exits nonzero on a surprise, so it doubles as the repo's run-it-and-watch test.

## Curate a public agenda

Two terminals, one shared work dir. Pick your LLM backend on the agent:

```
# terminal 1 — the always-on agent (holds the LLM credentials)
WRANGLE_LLM=claude python agent.py --work ~/.curator
#  or: WRANGLE_LLM=anthropic ANTHROPIC_API_KEY=…  python agent.py --work ~/.curator
#  or: WRANGLE_LLM=openai    OPENAI_API_KEY=…     python agent.py --work ~/.curator

# terminal 2 — fetch a public Indico agenda and submit it
python fetch_indico.py 1471803 | python submit.py --work ~/.curator \
       --url "https://indico.cern.ch/event/1471803/" --title "CHEP 2026" \
       --interests interests.sample.txt
```

`fetch_indico.py` turns the event's JSON export into an LLM-friendly digest — the
one-page timetable is perfect for a human and hopeless for a model. Picks land in
local SQLite, url-deduped, and are viewable at `/picks` if the server is running.

## Curate a protected agenda — the browser extension

An ATLAS-internal meeting on Indico is readable only by the authenticated human in
the browser; a server cannot reach it. The extension fetches the event's export *in
your own session* and hands it to your local agent. Run the agent and the local
endpoint on the same work dir:

```
WRANGLE_LLM=claude python agent.py  --work ~/.curator
python server.py --work ~/.curator --port 8765       # prints a token on startup
```

Then load `examples/curator/extension/` unpacked in Chrome (`chrome://extensions` →
Developer mode → Load unpacked), open the Indico event page you're interested in,
click the extension, paste the token once, and hit **Curate**. Your picks appear at
`http://127.0.0.1:8765/picks`.

## The prompt is the knob

Curation behaviour — how many picks, how strict, how to rank — lives entirely in
`prompt.md`. It ships as a sensible default (rank by fit, prefer a focused list);
edit it however you like, or point the agent at another file with `WRANGLE_PROMPT=…`.
The interests file (`--interests`, or the extension's box) is what each rationale
ties back to.

## Backends

| `WRANGLE_LLM` | Needs | Notes |
|---|---|---|
| `stub` | nothing | deterministic; extracts the page's markdown links. The fallback; forced in `run_demo.py`. |
| `claude` | `claude` on PATH | `claude -p`, subscription auth, no API cost; also reads staged PDFs. |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic API (stdlib urllib, no SDK). |
| `openai` | `OPENAI_API_KEY` | OpenAI API (stdlib urllib, no SDK). |

## Not exfiltration

The submit side talks only to your own agent on your own machine (localhost), and the
server reaches no protected site — *you* do, in your browser, and it hands the agent
only bytes you were already authorized to see. Nothing leaves your box except to the
LLM you chose.

## How it maps to a wrangle-ai consumer

The agent side is used **directly**, exactly as a production consumer uses it; only
the two seams and the doer's innards differ:

| This example | A production consumer |
|---|---|
| `SqliteBullpen` | Postgres bullpen (`FOR UPDATE SKIP LOCKED`) |
| `FifoBell` | Postgres `LISTEN`/`NOTIFY` |
| `server.py` / `submit.py` / extension | the app's authenticated endpoint + its own client |
| local SQLite picks | the app's picks table |
| `doer_curate.py` | the same doer shape, the app's LLM + store |

Same `Wrangler`, same `Worker`, same handler-runs-a-doer pattern.

## Files (`examples/curator/`)

- `agent.py` — the Wrangler host (the always-on side).
- `server.py` — local curate endpoint + `/picks` viewer (the web-tier side).
- `submit.py` — CLI submit: stage + enqueue + ring.
- `fetch_indico.py` — Indico event → LLM-friendly digest.
- `store.py` — `SqliteBullpen` (the wrangle-ai seam) + `PicksStore`.
- `bell.py` — `FifoBell` (the wrangle-ai seam).
- `doer_curate.py` — the curation doer; selectable LLM backend.
- `handler.py` — runs the doer under a timeout, records picks.
- `prompt.md` — the curation prompt (your knob).
- `interests.sample.txt` — an example interests file.
- `extension/` — the Chrome extension for protected Indico events.
- `run_demo.py` — the headless end-to-end smoke run.
