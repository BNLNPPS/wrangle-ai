"""The wrangler: a persistent, bounded, self-healing agent.

This is the whole shared core. An app supplies a Bullpen and a Bell and registers
one handler per worker type; the agent then spins off workers as they arrive, and
everything that keeps it robust lives here and is shared by every consumer:

  * bounded concurrency, so a slow worker never blocks the next;
  * backpressure — only as many workers are claimed as can run at once;
  * dedup of in-flight work, so a double-click can't run the same worker twice;
  * exception capture, so one sick worker can never take the agent down;
  * a graceful drain on shutdown.

Hard bounding of a single worker (a runaway model call, a hung xrootd) belongs in
the *doer* its handler runs — a subprocess with its own timeout is the one place a
runaway can actually be killed. The core's role is the loop, not the kill.
"""
from __future__ import annotations

import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from .protocols import Bell, Bullpen
from .worker import Worker

logger = logging.getLogger("wrangle_ai")

Handler = Callable[[Worker], Optional[dict]]
KeyFn = Callable[[Worker], str]


@dataclass
class _Registration:
    handler: Handler
    timeout: float
    key_fn: KeyFn


class Wrangler:
    def __init__(self, bullpen: Bullpen, bell: Bell, *,
                 max_workers: int = 4, idle_timeout: float = 15.0,
                 name: str = "wrangler"):
        self.bullpen = bullpen
        self.bell = bell
        self.max_workers = max_workers
        self.idle_timeout = idle_timeout
        self.name = name
        self._handlers: dict[str, _Registration] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix=f"{name}-w")
        self._lock = threading.Lock()
        self._inflight_keys: set[str] = set()
        self._inflight = 0
        self._stop = threading.Event()
        self._exit_code = 0

    # -- registration ------------------------------------------------------
    def register(self, worker_type: str, handler: Handler, *,
                 timeout: float = 300.0, key_fn: Optional[KeyFn] = None) -> "Wrangler":
        """Register ``handler`` for ``worker_type``. ``key_fn`` derives a dedup key
        from a worker; a worker whose key is already in flight is recorded as a skip
        rather than run a second time. The default key is per-worker-id (no dedup)."""
        if key_fn is None:
            key_fn = lambda w: f"{w.type}:{w.id}"
        self._handlers[worker_type] = _Registration(handler, timeout, key_fn)
        return self

    # -- main loop ---------------------------------------------------------
    def run(self) -> int:
        """Block until stopped: clear any backlog, then sleep on the bell, waking to
        spin off workers as they arrive. Returns the intended process exit code."""
        self._install_signals()
        logger.info("%s: starting (max_workers=%d, idle_timeout=%.0fs)",
                    self.name, self.max_workers, self.idle_timeout)
        while not self._stop.is_set():
            try:
                self._dispatch_available()
            except Exception:
                logger.exception("%s: dispatch cycle failed; continuing", self.name)
            try:
                # Wake on a ring, or on idle_timeout for a safety re-check. When the
                # agent is saturated this also bounds how long a freed slot waits
                # before the next claim — fine for low-volume long workers.
                self.bell.wait(self.idle_timeout)
            except Exception:
                logger.exception("%s: bell wait failed; backing off", self.name)
                self._stop.wait(self.idle_timeout)
        self._drain()
        logger.info("%s: stopped (exit=%d)", self.name, self._exit_code)
        return self._exit_code

    def _dispatch_available(self) -> None:
        with self._lock:
            free = self.max_workers - self._inflight
        if free <= 0:
            return
        for worker in self.bullpen.claim_pending(free):
            self._submit(worker)

    def _submit(self, worker: Worker) -> None:
        reg = self._handlers.get(worker.type)
        if reg is None:
            logger.error("%s: no handler for worker type %r (worker %s)",
                         self.name, worker.type, worker.id)
            self.bullpen.mark_failed(worker.id, f"no handler for type {worker.type!r}")
            return
        key = reg.key_fn(worker)
        with self._lock:
            if key in self._inflight_keys:
                logger.info("%s: worker %s skipped (dedup key %r already in flight)",
                            self.name, worker.id, key)
                self.bullpen.mark_done(worker.id, {"skipped": f"duplicate of in-flight {key}"})
                return
            self._inflight_keys.add(key)
            self._inflight += 1
        self._pool.submit(self._run, worker, reg, key)

    def _run(self, worker: Worker, reg: _Registration, key: str) -> None:
        logger.info("%s: worker %s (%s) start", self.name, worker.id, worker.type)
        try:
            result = reg.handler(worker) or {}
            self.bullpen.mark_done(worker.id, result)
            logger.info("%s: worker %s done", self.name, worker.id)
        except Exception as e:
            logger.exception("%s: worker %s failed", self.name, worker.id)
            try:
                self.bullpen.mark_failed(worker.id, str(e))
            except Exception:
                logger.exception("%s: worker %s: mark_failed also failed", self.name, worker.id)
        finally:
            with self._lock:
                self._inflight_keys.discard(key)
                self._inflight -= 1

    # -- shutdown ----------------------------------------------------------
    def request_stop(self, *, exit_code: int = 0) -> None:
        """Ask the agent to stop after the current drain. ``exit_code`` lets a
        deliberate stop signal systemd to leave the unit down (see the deploy unit's
        ``SuccessExitStatus``)."""
        self._exit_code = exit_code
        self._stop.set()

    def _drain(self) -> None:
        with self._lock:
            n = self._inflight
        logger.info("%s: draining %d in-flight", self.name, n)
        self._pool.shutdown(wait=True)
        try:
            self.bell.close()
        except Exception:
            logger.exception("%s: bell close failed", self.name)

    def _install_signals(self) -> None:
        def _on_signal(signum, _frame):
            logger.info("%s: signal %d → graceful stop", self.name, signum)
            self.request_stop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _on_signal)
            except ValueError:
                pass  # not running on the main thread (e.g. under tests)
