"""FifoBell — the example's wake channel, a named pipe.

Implements the wrangle_ai.Bell protocol. The submit side writes a byte; the agent
blocks in ``select()`` on the read end with the safety-sweep timeout. Same role as
tjai's Postgres ``LISTEN``/``NOTIFY``: a doorbell, not a datastore — the bullpen
stays the source of truth, so a missed ring costs at most one ``idle_timeout`` of
latency, never a lost worker.
"""
from __future__ import annotations

import errno
import os
import select


class FifoBell:
    def __init__(self, fifo_path):
        self.path = fifo_path
        if not os.path.exists(fifo_path):
            os.mkfifo(fifo_path, 0o600)
        # Read end, non-blocking. Also hold a write end open so the pipe never
        # reports all-writers-closed (EOF), which would wedge select() readable.
        self._rfd = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
        self._wfd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)

    def wait(self, timeout):
        try:
            r, _, _ = select.select([self._rfd], [], [], timeout)
        except (OSError, ValueError):
            return
        if not r:
            return
        try:
            while os.read(self._rfd, 4096):
                pass
        except OSError as e:
            if e.errno != errno.EAGAIN:
                raise

    def close(self):
        for fd in (self._rfd, self._wfd):
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def ring(fifo_path):
        """Producer side: wake the agent. Safe if nobody is listening — the worker
        is already durable in the bullpen, and the safety sweep will catch it."""
        try:
            fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno == errno.ENXIO:
                return  # no reader yet; the sweep will pick the worker up
            raise
        try:
            os.write(fd, b"\x01")
        except OSError as e:
            if e.errno != errno.EAGAIN:
                raise
        finally:
            os.close(fd)
