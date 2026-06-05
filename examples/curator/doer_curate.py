#!/usr/bin/env python3
"""Standalone curation doer — the slot where the LLM goes.

Reads a staged job dir (``meta.json`` + ``page.txt`` [+ ``pdfs/`` + ``interests.txt``])
and emits curated picks as JSON on stdout:

    {"picks": [{"title", "url", "precis", "rationale"}]}

Exits nonzero on failure so the agent records the worker as failed. Runnable on its
own: ``python doer_curate.py <job_dir>``.

The LLM backend is selectable (``WRANGLE_LLM``), so the same curator works on a
laptop with Claude Code or on a server with an API key:

  * ``stub``      — deterministic, no LLM (extract the page's markdown links). The
                    default when no backend is available; forced by WRANGLE_DEMO_STUB=1.
  * ``claude``    — ``claude -p`` (Claude Code CLI, subscription auth, no API cost);
                    also reads staged PDFs with the Read tool.
  * ``anthropic`` — Anthropic API (``ANTHROPIC_API_KEY``), model ``WRANGLE_ANTHROPIC_MODEL``.
  * ``openai``    — OpenAI API (``OPENAI_API_KEY``), model ``WRANGLE_OPENAI_MODEL``.

The API backends use only the standard library (urllib) — no SDK dependency.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

CLAUDE_TIMEOUT = 600

# Fallback if prompt.md is missing. The shipped prompt.md is the real, editable knob.
DEFAULT_PROMPT = (
    "You are curating the genuinely worthwhile items from a conference agenda or web "
    "page — talks, papers, sessions worth a researcher's time. Judge relevance against "
    "the reader's INTERESTS and rank by fit, best first; prefer a focused list over an "
    'exhaustive one. Return ONLY JSON of the form {"picks":[{"title","url","precis",'
    '"rationale"}]}, no prose around it. precis: one sentence on what the item is; '
    "rationale: one sentence tying it to the reader's interests."
)


def load_prompt():
    """The curation prompt — the user's knob. Read prompt.md (or $WRANGLE_PROMPT),
    stripping <!-- --> notes; fall back to DEFAULT_PROMPT."""
    path = os.getenv("WRANGLE_PROMPT") or str(Path(__file__).resolve().parent / "prompt.md")
    try:
        text = Path(path).read_text()
    except OSError:
        return DEFAULT_PROMPT
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    return text or DEFAULT_PROMPT


# -- backends -------------------------------------------------------------
def stub_curate(meta, page, interests):
    """Deterministic stand-in for the model: the markdown links on the page."""
    if "POISON" in page:
        raise RuntimeError("poison page: simulated doer failure")
    picks = []
    for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", page):
        title, url = m.group(1).strip(), m.group(2).strip()
        picks.append({
            "title": title,
            "url": url,
            "precis": f"{title} — linked from {meta.get('title') or meta.get('url') or 'the page'}.",
            "rationale": "Selected by the stub doer (a markdown link on the page).",
        })
    return picks


def _prompt(meta, page, pdfs, interests):
    parts = [load_prompt(), "\n\n===== INTERESTS =====\n", interests or "(none given — pick broadly substantive items)"]
    parts += ["\n\n===== PAGE =====\nurl: ", meta.get("url", ""), "\ntitle: ", meta.get("title", ""), "\n\n", page]
    if pdfs:
        parts += ["\n\n===== STAGED PDFS (read each) =====\n", "\n".join(pdfs)]
    return "".join(parts)


def claude_curate(meta, page, pdfs, interests, job_dir):
    cmd = [shutil.which("claude"), "-p", "--output-format", "text",
           "--model", os.getenv("WRANGLE_CLAUDE_MODEL", "opus"), "--allowedTools", "Read"]
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)  # force subscription auth, no API cost
    out = subprocess.run(cmd, input=_prompt(meta, page, pdfs, interests),
                         capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
                         env=env, cwd=str(job_dir))
    if out.returncode != 0:
        raise RuntimeError(f"claude -p exited {out.returncode}: {(out.stderr or '')[:300]}")
    return out.stdout


def _http_json(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=CLAUDE_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def anthropic_curate(meta, page, pdfs, interests, job_dir):
    key = os.environ["ANTHROPIC_API_KEY"]
    data = _http_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": os.getenv("WRANGLE_ANTHROPIC_MODEL", "claude-opus-4-8"),
         "max_tokens": 4096,
         "messages": [{"role": "user", "content": _prompt(meta, page, pdfs, interests)}]},
    )
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def openai_curate(meta, page, pdfs, interests, job_dir):
    key = os.environ["OPENAI_API_KEY"]
    data = _http_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "content-type": "application/json"},
        {"model": os.getenv("WRANGLE_OPENAI_MODEL", "gpt-4o"),
         "messages": [{"role": "user", "content": _prompt(meta, page, pdfs, interests)}]},
    )
    return data["choices"][0]["message"]["content"]


LLM_BACKENDS = {"claude": claude_curate, "anthropic": anthropic_curate, "openai": openai_curate}


# -- driver ---------------------------------------------------------------
def _choose_backend():
    if os.getenv("WRANGLE_DEMO_STUB") == "1":
        return "stub"
    explicit = os.getenv("WRANGLE_LLM")
    if explicit:
        return explicit
    if shutil.which("claude"):
        return "claude"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "stub"


def load_job(job_dir):
    d = Path(job_dir)
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    page = (d / "page.txt").read_text() if (d / "page.txt").exists() else ""
    interests = (d / "interests.txt").read_text() if (d / "interests.txt").exists() else ""
    pdfs = sorted(str(p) for p in (d / "pdfs").glob("*.pdf")) if (d / "pdfs").is_dir() else []
    return meta, page, pdfs, interests


def parse_picks(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        return json.loads(text).get("picks", [])
    except json.JSONDecodeError:
        start = text.find("{")
        if start >= 0:
            return json.loads(text[start:text.rfind("}") + 1]).get("picks", [])
        raise


def main(job_dir):
    meta, page, pdfs, interests = load_job(job_dir)
    backend = _choose_backend()
    if backend == "stub":
        picks = stub_curate(meta, page, interests)
    else:
        fn = LLM_BACKENDS.get(backend)
        if fn is None:
            raise RuntimeError(f"unknown WRANGLE_LLM backend {backend!r}")
        picks = parse_picks(fn(meta, page, pdfs, interests, job_dir))
    json.dump({"picks": picks, "backend": backend}, sys.stdout)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: doer_curate.py <job_dir>", file=sys.stderr)
        sys.exit(2)
    try:
        main(sys.argv[1])
    except Exception as e:
        print(f"doer failed: {e}", file=sys.stderr)
        sys.exit(1)
