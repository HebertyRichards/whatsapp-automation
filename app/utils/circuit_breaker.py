import logging
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitBreaker:
    """
    States:
      - closed: calls go through; consecutive failures are counted.
      - open: after `failure_threshold` failures, calls are short-circuited for
        `recovery_timeout` seconds instead of hammering a dependency that is down.
      - half_open: once the cooldown passes a probe is let through. Success closes
        the circuit; failure reopens it for another cooldown.

    The app runs on a single event loop, so transitions need no lock: there is no
    await between reading and writing the state.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "circuit",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._name = name
        self._state = CircuitState.closed
        self._failures = 0
        self._opened_at = 0.0

    def is_tripped(self) -> bool:
        """True while open and still cooling down. Side-effect free: does not consume the half-open probe."""
        if self._state is CircuitState.open:
            return (time.monotonic() - self._opened_at) < self._recovery_timeout
        return False

    def allow(self) -> bool:
        """Decides whether a call may proceed. Call once per attempt to use the dependency."""
        if self._state is CircuitState.open:
            if (time.monotonic() - self._opened_at) >= self._recovery_timeout:
                self._state = CircuitState.half_open
                logger.info("Circuit '%s' -> half_open (probing)", self._name)
                return True
            return False
        return True

    def record_success(self) -> None:
        if self._state is not CircuitState.closed:
            logger.info("Circuit '%s' -> closed (recovered)", self._name)
        self._state = CircuitState.closed
        self._failures = 0

    def record_failure(self) -> None:
        if self._state is CircuitState.half_open:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._trip()

    def reset(self) -> None:
        self._state = CircuitState.closed
        self._failures = 0
        self._opened_at = 0.0

    def _trip(self) -> None:
        self._state = CircuitState.open
        self._opened_at = time.monotonic()
        self._failures = 0
        logger.warning("Circuit '%s' -> open for %.0fs (dependency unavailable)", self._name, self._recovery_timeout)
