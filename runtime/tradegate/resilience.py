"""Resilience primitives: reconnect backoff and bounded sync retries.

Two small, honest tools shared by the feed and broker layers:

- ``Backoff`` — exponential reconnect delays with jitter and a
  success-aware reset: a connection that stayed up long enough earns a
  fresh attempt counter, so a flaky hour doesn't permanently pin the
  delay at the cap.
- ``retry`` — bounded retries for synchronous calls (urllib), retrying
  only transient failures the caller marks retryable. Client errors
  (4xx other than 429) fail fast — retrying a malformed request is a
  placebo, not recovery.

No sleeping inside async code: ``Backoff.next()`` returns the delay;
callers ``await asyncio.sleep(delay)`` or ``time.sleep`` as fits.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable


class Backoff:
    """Exponential backoff: base, doubling to cap, ±jitter, health reset.

    ``mark_connected()`` records a successful connect; if the connection
    survived at least ``reset_after`` seconds before the next failure,
    the delay counter resets — long-lived connections are healthy even
    if they eventually drop.
    """

    def __init__(self, base: float = 5.0, cap: float = 300.0,
                 jitter: float = 0.2, reset_after: float = 60.0,
                 rng: random.Random | None = None):
        self.base, self.cap, self.jitter = base, cap, jitter
        self.reset_after = reset_after
        self._rng = rng or random.Random()
        self._delay = base
        self._connected_at: float | None = None
        self.attempts = 0  # consecutive failures since last healthy conn

    def mark_connected(self) -> None:
        self._connected_at = time.monotonic()

    def next(self) -> float:
        """Delay before the next reconnect attempt."""
        if (self._connected_at is not None
                and time.monotonic() - self._connected_at >= self.reset_after):
            self._delay = self.base
            self.attempts = 0
        self._connected_at = None
        self.attempts += 1
        d = self._delay * (1 + self._rng.uniform(-self.jitter, self.jitter))
        self._delay = min(self._delay * 2, self.cap)
        return max(0.0, d)


def retry(fn: Callable, is_retryable: Callable[[Exception], bool],
          attempts: int = 3, base_delay: float = 0.5, cap: float = 8.0,
          sleep: Callable[[float], None] = time.sleep):
    """Call ``fn()`` up to ``attempts`` times, retrying only failures
    ``is_retryable`` accepts. Sleeping is injectable for tests.
    """
    delay = base_delay
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — filtered by is_retryable
            if i == attempts - 1 or not is_retryable(e):
                raise
            sleep(min(delay, cap))
            delay *= 2
    return None  # unreachable — last attempt raises
