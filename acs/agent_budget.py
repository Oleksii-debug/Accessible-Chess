from __future__ import annotations

"""Exact model-cost budget for the Accessible Chess Universal Chess Agent.

Adapted from Oleksii-debug/AutoTrade@60e7c95b3b572810dcfb6c4ab34e0b338b0ace02
mvp/autotrade_mvp/model_gateway.py (BudgetSnapshot/BudgetLedger).

This is deliberately provider-neutral and in-memory. A future durable adapter
may persist the same semantics without changing the admission boundary.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be decimal-compatible")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be decimal-compatible") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    ceiling: Decimal
    reserved: Decimal
    incurred: Decimal
    estimated_unbilled: Decimal

    @property
    def available(self) -> Decimal:
        used = self.reserved + self.incurred + self.estimated_unbilled
        remaining = self.ceiling - used
        return remaining if remaining > 0 else Decimal("0")


class ModelCostBudget:
    """Fail-closed exact-decimal ceiling for agent model calls."""

    def __init__(self, ceiling: object) -> None:
        self._ceiling = _decimal(ceiling, "budget ceiling")
        self._reserved: dict[str, Decimal] = {}
        self._incurred = Decimal("0")
        self._estimated_unbilled: dict[str, Decimal] = {}
        self._settled: set[str] = set()
        self._reconciled_bills: dict[str, tuple[str, Decimal]] = {}

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            ceiling=self._ceiling,
            reserved=sum(self._reserved.values(), Decimal("0")),
            incurred=self._incurred,
            estimated_unbilled=sum(self._estimated_unbilled.values(), Decimal("0")),
        )

    def reserve(self, request_id: str, amount: object) -> None:
        request = _identifier(request_id, "request_id")
        value = _decimal(amount, "reservation")
        prior = self._reserved.get(request)
        if prior is not None:
            if prior != value:
                raise ValueError("reservation conflict")
            return
        if request in self._settled:
            raise ValueError("request_id is already settled")
        if value > self.snapshot().available:
            raise ValueError("budget exhausted")
        self._reserved[request] = value

    def release(self, request_id: str) -> Decimal:
        request = _identifier(request_id, "request_id")
        if request in self._settled:
            raise ValueError("cannot release after model call boundary")
        return self._reserved.pop(request, Decimal("0"))

    def settle(
        self,
        request_id: str,
        *,
        incurred: object,
        estimated_unbilled: object = Decimal("0"),
    ) -> None:
        request = _identifier(request_id, "request_id")
        actual = _decimal(incurred, "incurred cost")
        estimate = _decimal(estimated_unbilled, "estimated unbilled cost")
        reserved = self._reserved.get(request)
        if reserved is None:
            raise ValueError("unknown reservation")
        if actual + estimate > reserved:
            raise ValueError("settlement exceeds reserved ceiling")

        # Compute first, publish only after every check succeeds.
        new_incurred = self._incurred + actual
        new_estimates = dict(self._estimated_unbilled)
        new_estimates[request] = estimate
        del self._reserved[request]
        self._incurred = new_incurred
        self._estimated_unbilled = new_estimates
        self._settled.add(request)

    def reconcile_unbilled(
        self,
        *,
        billing_id: str,
        request_id: str,
        billed: object,
    ) -> None:
        bill = _identifier(billing_id, "billing_id")
        request = _identifier(request_id, "request_id")
        amount = _decimal(billed, "billed cost")
        prior = self._reconciled_bills.get(bill)
        if prior is not None:
            if prior != (request, amount):
                raise ValueError("billing reconciliation conflict")
            return
        if request not in self._settled:
            raise ValueError("billing has no matching settled request")

        estimate = self._estimated_unbilled.get(request, Decimal("0"))
        remaining = estimate - min(estimate, amount)
        self._estimated_unbilled[request] = remaining
        self._incurred += amount
        self._reconciled_bills[bill] = (request, amount)
