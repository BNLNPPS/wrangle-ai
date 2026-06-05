"""The unit of work the agent spins off.

A Worker is a plain record: an id, a type that selects its handler, and an opaque
payload the handler understands. Where workers live and how their outcomes are
recorded is the app's business (see protocols.Bullpen); the core only holds a
Worker in memory while its handler runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Worker:
    id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
