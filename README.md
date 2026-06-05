# wrangle-ai

A persistent, credentialed worker for harnessed LLM and script work: the
always-on process that holds the credentials a public web tier must not, and runs
bounded, deterministic-wrapped work the instant the bell rings.

The name is the model: a wrangler works the animal on a line in the ring —
teaching it, keeping it in line, while it does the work. Here the animal is an LLM
(`claude -p` and kin) under a deterministic harness. The process owns the flow; the
model only judges and writes; deterministic steps run before and after; every run
is recorded.

## See it work

The repo ships a real example — **build your own curated CHEP picks**: point it at a
conference agenda and get *your* shortlist, judged by the LLM you choose, on your own
machine.

```
git clone https://github.com/BNLNPPS/wrangle-ai
cd wrangle-ai
python examples/curator/run_demo.py     # no keys, no browser — watch the whole loop
```

Full guide — public agendas, the browser extension for protected ones, choosing your
LLM: **[`docs/curator.md`](docs/curator.md)**.

## Why it exists

The public web tier (Apache/Django, an internet-facing service account) should hold
no credentials and run nothing privileged. But real work — drive a privileged
client, fetch bytes over an authenticated protocol, run a credentialed `claude -p`
— needs those keys.

wrangle-ai answers this: one always-on agent, running as the
credentialed user, that is the single executor agent through which every privileged
action passes — whatever surface triggered it. The web tier only authenticates the
request, leaves a durable worker, and reads the result the agent writes back. A
compromised web tier inherits a "please do X" button, not the keys.

This is the same separation proven by the ePIC production-ops agent in
[swf-monitor](https://github.com/BNLNPPS/swf-monitor); wrangle-ai is that pattern
rebuilt as a small, standalone, transport-agnostic core so it can serve any app.

## The boundary

The core (this repo) is small and knows nothing about the transport or storage:

- **`Wrangler`** — the agent: the dispatch loop. Bounded concurrency, backpressure,
  dedup of in-flight work, exception capture so one sick worker never downs the
  agent, and a graceful drain. This is the shared robustness, written once.
- **`Worker`** — id, type, payload.

Each app fills in two seams and its handlers:

- **`Bullpen`** — where workers live and how outcomes are recorded; also owns crash
  recovery (re-claiming workers the agent left running when it died). The bullpen is
  the source of truth.
- **`Bell`** — how the agent is woken without polling, e.g. Postgres
  `LISTEN`/`NOTIFY`, or a message bus.
- **Handlers** — one per worker type. Creating a wrangler is adding a handler, which
  runs a standalone *doer* (a subprocess with its own hard timeout — the one place a
  runaway is actually killed).

```python
from wrangle_ai import Wrangler

wrangler = Wrangler(bullpen=my_bullpen, bell=my_bell, max_workers=4)
wrangler.register("curate_page", handle_curate_page, timeout=1800,
                  key_fn=lambda w: f"curate:{w.payload['url']}")
raise SystemExit(wrangler.run())
```

## License

Apache-2.0.
