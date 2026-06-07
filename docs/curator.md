# Curator — a conference-pick example

Curator builds a shortlist of talks and papers from a conference agenda, selected and ranked by an LLM based on your specified prompt, on your own machine. It is also the worked example of
the wrangle-ai pattern: a submit side that holds no credentials, and an always-on
agent that does the credentialed work. The code is under
[`examples/curator/`](../examples/curator).

> Run the commands below from the example directory (`cd examples/curator`). The demo
> needs only Python 3.10+; an LLM backend (Claude Code on your PATH, or an API key) is
> needed for real curation, not the demo.

## Demo (no keys, no browser)

```
python run_demo.py
```

Starts the agent, submits four pages, and reports each outcome: one page curated, the
same page resubmitted and deduped, a malformed page recorded as failed without
stopping the agent, and a page delivered by ringing the bell. It asserts each outcome
and exits nonzero on a mismatch, so it also serves as the repo's smoke test.

## Curate a public agenda

Two terminals, one shared work dir. Choose the LLM backend on the agent:

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

`fetch_indico.py` converts the event's JSON export into a text digest for the model;
the rendered timetable is not usable as model input. Picks are stored in local
SQLite, deduplicated by URL, and viewable at `/picks` when the server is running.

## Curate a protected agenda — the browser extension

An ATLAS-internal meeting on Indico is readable only by the authenticated user in the
browser; a server cannot reach it. The extension fetches the event's export in your
own browser session and passes it to the local agent. Run the agent and the local
endpoint on the same work dir:

```
WRANGLE_LLM=claude python agent.py  --work ~/.curator
python server.py --work ~/.curator --port 8765       # prints a token on startup
```

Then load `examples/curator/extension/` unpacked in Chrome (`chrome://extensions` →
Developer mode → Load unpacked), open the Indico event page, click the extension,
paste the token once, and click **Curate**. Picks appear at
`http://127.0.0.1:8765/picks`.

## The prompt

Curation behaviour — number of picks, strictness, ranking — is set in `prompt.md`.
The default ranks by fit and prefers a short list; edit it, or point the agent at
another file with `WRANGLE_PROMPT=…`. Through the prompt you can express any basis for
selection you want — a research interest, a named author, novelty, a single track —
and the LLM interprets it. The interests file (`--interests`, or the extension's box)
is one optional input it folds in.

## Backends

| `WRANGLE_LLM` | Needs | Notes |
|---|---|---|
| `stub` | nothing | deterministic; extracts the page's markdown links. The fallback; forced in `run_demo.py`. |
| `claude` | `claude` on PATH | `claude -p`, subscription auth, no API cost; also reads staged PDFs. |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic API (stdlib urllib, no SDK). |
| `openai` | `OPENAI_API_KEY` | OpenAI API (stdlib urllib, no SDK). |

## Trust boundary

The submit side and server talk only to the local agent over localhost. Protected
content is fetched by your own browser, never by the server, and reaches the agent as
bytes you were already authorized to read. The only outbound traffic is to the LLM you
choose.

## How it maps to a wrangle-ai consumer

The agent side is used directly, as a production consumer uses it; only the two seams
and the doer differ:

| This example | A production consumer |
|---|---|
| `SqliteBullpen` | Postgres bullpen (`FOR UPDATE SKIP LOCKED`) |
| `FifoBell` | Postgres `LISTEN`/`NOTIFY` |
| `server.py` / `submit.py` / extension | the app's authenticated endpoint + its own client |
| local SQLite picks | the app's picks table |
| `doer_curate.py` | the same doer shape, the app's LLM + store |

The `Wrangler`, `Worker`, and handler-runs-a-doer pattern are identical.

## Files (`examples/curator/`)

- `agent.py` — the Wrangler host (the always-on side).
- `server.py` — local curate endpoint + `/picks` viewer (the web-tier side).
- `submit.py` — CLI submit: stage, enqueue, ring.
- `fetch_indico.py` — Indico event → text digest.
- `store.py` — `SqliteBullpen` (the wrangle-ai seam) + `PicksStore`.
- `bell.py` — `FifoBell` (the wrangle-ai seam).
- `doer_curate.py` — the curation doer; selectable LLM backend.
- `handler.py` — runs the doer under a timeout, records picks.
- `prompt.md` — the curation prompt.
- `interests.sample.txt` — an example interests file.
- `extension/` — the Chrome extension for protected Indico events.
- `run_demo.py` — the headless end-to-end run.
