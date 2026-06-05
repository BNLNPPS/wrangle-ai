"""The two seams every app fills in.

The agent core is transport- and storage-agnostic. An app makes it concrete by
supplying:

  * a Bullpen — where workers live and how their outcomes are written; and
  * a Bell — how the agent is woken the instant work arrives.

These are Protocols, not base classes: implement the methods on any object. A
typical pairing is a Postgres-backed bullpen (``SELECT … FOR UPDATE SKIP LOCKED``)
and a ``LISTEN``/``NOTIFY`` bell.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .worker import Worker


@runtime_checkable
class Bullpen(Protocol):
    """The durable record of workers. The bullpen is the source of truth; the bell is
    only a hint that it is worth looking."""

    def claim_pending(self, limit: int) -> list[Worker]:
        """Atomically claim up to ``limit`` runnable workers, mark them running, and
        return them. Must be concurrency-safe (e.g. ``FOR UPDATE SKIP LOCKED``) so a
        startup sweep racing a live ring — or two agents — never double-claims one
        worker.

        The bullpen also owns crash recovery: a worker left *running* by an agent
        that died should become claimable again here once it is stale by the
        bullpen's own age/heartbeat policy (the bullpen knows the timeouts; the core
        does not). That is what makes a crash self-heal without a poller.
        """
        ...

    def mark_done(self, worker_id: str, result: dict) -> None:
        """Record success. ``result`` is whatever the handler returned (or
        ``{"skipped": …}`` when the core deduped a duplicate)."""
        ...

    def mark_failed(self, worker_id: str, error: str) -> None:
        """Record failure where the triggering surface will see it."""
        ...


@runtime_checkable
class Bell(Protocol):
    """How the agent sleeps until there is work, without polling."""

    def wait(self, timeout: float) -> None:
        """Block until a work-ready ring arrives or ``timeout`` seconds elapse.
        Returning on timeout is required, not optional: it drives the periodic
        safety sweep so a dropped signal can never strand a worker. Spurious early
        returns are harmless — ``Bullpen.claim_pending`` is the truth."""
        ...

    def close(self) -> None:
        """Release the underlying resource (connection, socket) on shutdown."""
        ...
