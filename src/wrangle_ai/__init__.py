"""wrangle-ai — a persistent, credentialed agent for harnessed LLM and script work.

The agent is an always-on process that holds the credentials the web tier must
not, and spins off workers to run bounded, deterministic-wrapped tasks the instant
the bell rings. The core here is small and transport-agnostic; an app plugs in its
own bell, bullpen, and handlers.
"""
from .protocols import Bell, Bullpen
from .worker import Worker
from .wrangler import Handler, KeyFn, Wrangler

__all__ = ["Worker", "Bullpen", "Bell", "Wrangler", "Handler", "KeyFn"]
__version__ = "0.0.1"
