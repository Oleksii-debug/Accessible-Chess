from __future__ import annotations

"""Section 54 per-run INPUT and OUTPUT token accounting.

This policy is the guarded local orchestration boundary, not a provider client.
It never invokes a model. A provider must enforce the reserved max output size.
Unknown post-dispatch billing is a hard gate: no automatic paid retry.
"""

from dataclasses import dataclass
from threading import RLock


class FactoryTokenLimitError(ValueError):
    """An exact non-monetary per-run token envelope cannot be guaranteed."""


@dataclass(frozen=True, slots=True)
class FactoryTokenReservation:
    request_id: str
    model_id: str
    input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class FactoryTokenUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class FactoryTokenSnapshot:
    max_input_tokens: int
    max_output_tokens: int
    committed_input_tokens: int
    committed_output_tokens: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    remaining_input_tokens: int
    remaining_output_tokens: int
    calls_completed: int
    blocked_reason: str | None


def _positive_exact_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1 or value > 2**63 - 1:
        raise FactoryTokenLimitError(name + " must be a positive bounded integer")
    return value


def _valid_request_id(value: object, name: str) -> str:
    if type(value) is not str or not (1 <= len(value) <= 128):
        raise FactoryTokenLimitError(name + " must be bounded non-empty text")
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise FactoryTokenLimitError(name + " must be printable ASCII without whitespace")
    return value


class FactoryTokenGovernor:
    """Concurrency-safe, fail-closed run-scope token envelopes.

    Before each call reserve the entire predicted input and configured maximum
    output. No reserve succeeds without provider enforceable output cap.
    In-flight overshoot or missing billing requires a fresh run/reconciliation:
    the provider may have consumed tokens that cannot be remotely cancelled.
    """

    def __init__(self, *, max_input_tokens: int, max_output_tokens: int) -> None:
        self._max_in = _positive_exact_int(max_input_tokens, "max_input_tokens")
        self._max_out = _positive_exact_int(max_output_tokens, "max_output_tokens")
        self._lock = RLock()
        self._reserved: dict[str, FactoryTokenReservation] = {}
        self._completed: dict[str, tuple[str, FactoryTokenUsage]] = {}
        self._used_in = 0
        self._used_out = 0
        self._blocked: str | None = None

    def reserve(
        self, *, request_id: str, model_id: str,
        predicted_input_tokens: int, max_output_tokens: int,
        provider_enforces_output_cap: bool,
    ) -> FactoryTokenReservation:
        req = _valid_request_id(request_id, "request_id")
        model = _valid_request_id(model_id, "model_id")
        predicted = _positive_exact_int(predicted_input_tokens, "predicted_input_tokens")
        output_cap = _positive_exact_int(max_output_tokens, "max_output_tokens")
        if provider_enforces_output_cap is not True:
            raise FactoryTokenLimitError("Provider cannot enforce a strict output cap")
        with self._lock:
            if self._blocked is not None:
                raise FactoryTokenLimitError("Run requires token-usage reconciliation")
            if req in self._reserved or req in self._completed:
                raise FactoryTokenLimitError("Duplicate request identity")
            held_in = sum(x.input_tokens for x in self._reserved.values())
            held_out = sum(x.max_output_tokens for x in self._reserved.values())
            if self._used_in + held_in + predicted > self._max_in:
                raise FactoryTokenLimitError("Input token limit would be exceeded")
            if self._used_out + held_out + output_cap > self._max_out:
                raise FactoryTokenLimitError("Output token limit would be exceeded")
            reservation = FactoryTokenReservation(req, model, predicted, output_cap)
            self._reserved[req] = reservation
            return reservation

    def settle(
        self, reservation: FactoryTokenReservation, *,
        actual_input_tokens: int, actual_output_tokens: int,
        cached_input_tokens: int = 0, reasoning_output_tokens: int = 0,
    ) -> FactoryTokenUsage:
        if type(reservation) is not FactoryTokenReservation:
            raise FactoryTokenLimitError("Invalid reservation")
        values = (actual_input_tokens, actual_output_tokens,
                  cached_input_tokens, reasoning_output_tokens)
        if any(type(v) is not int or v < 0 or v > 2**63 - 1 for v in values):
            raise FactoryTokenLimitError("Reported usage is invalid")
        if cached_input_tokens > actual_input_tokens:
            raise FactoryTokenLimitError("Cached input exceeds reported total")
        if reasoning_output_tokens > actual_output_tokens:
            raise FactoryTokenLimitError("Reasoning output exceeds reported total")
        usage = FactoryTokenUsage(*values)
        with self._lock:
            prior = self._reserved.get(reservation.request_id)
            if prior != reservation:
                raise FactoryTokenLimitError("Reservation is unknown or already settled")
            del self._reserved[reservation.request_id]
            self._used_in += actual_input_tokens
            self._used_out += actual_output_tokens
            self._completed[reservation.request_id] = (reservation.model_id, usage)
            if (actual_input_tokens > reservation.input_tokens or
                actual_output_tokens > reservation.max_output_tokens or
                self._used_in > self._max_in or self._used_out > self._max_out):
                self._blocked = "REPORTED_OVER_ENVELOPE"
                raise FactoryTokenLimitError("Provider reported tokens over reservation")
            return usage

    def fail_after_dispatch(self, reservation: FactoryTokenReservation) -> None:
        """Retain unknown-spend reservation; never silently refund or retry."""
        with self._lock:
            if self._reserved.get(reservation.request_id) != reservation:
                raise FactoryTokenLimitError("Unknown pending reservation")
            self._blocked = "UNKNOWN_PROVIDER_USAGE"

    def cancel_before_dispatch(self, reservation: FactoryTokenReservation) -> None:
        """Release only calls which definitively never reached a provider."""
        with self._lock:
            if self._reserved.get(reservation.request_id) != reservation:
                raise FactoryTokenLimitError("Unknown pending reservation")
            del self._reserved[reservation.request_id]

    def snapshot(self) -> FactoryTokenSnapshot:
        with self._lock:
            held_in = sum(x.input_tokens for x in self._reserved.values())
            held_out = sum(x.max_output_tokens for x in self._reserved.values())
            return FactoryTokenSnapshot(
                self._max_in, self._max_out, self._used_in, self._used_out,
                held_in, held_out,
                max(0, self._max_in - held_in - self._used_in),
                max(0, self._max_out - held_out - self._used_out),
                len(self._completed), self._blocked,
            )

    def usage_by_model(self) -> dict[str, FactoryTokenUsage]:
        """Read-only aggregate copy; cached/reasoning tokens are subsets."""
        with self._lock:
            combined: dict[str, FactoryTokenUsage] = {}
            for model, usage in self._completed.values():
                prev = combined.get(model, FactoryTokenUsage(0, 0))
                combined[model] = FactoryTokenUsage(
                    prev.input_tokens + usage.input_tokens,
                    prev.output_tokens + usage.output_tokens,
                    prev.cached_input_tokens + usage.cached_input_tokens,
                    prev.reasoning_output_tokens + usage.reasoning_output_tokens,
                )
            return combined
