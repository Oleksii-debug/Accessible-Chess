from __future__ import annotations

"""Exact model-cost budget primitive for the Universal Chess Agent.

Adapted from first-party donor:
Oleksii-debug/AutoTrade@main
mvp/autotrade_mvp/model_gateway.py (BudgetLedger/Model routing budget concepts)

This module is intentionally independent from trading/journal code.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


def _decimal(value: Decimal | str | int, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be an exact decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class AgentBudgetSnapshot:
    ceiling: Decimal
    reserved: Decimal
    incurred: Decimal
    estimated_unbilled: Decimal

    @property
    def available(self) -> Decimal:
        remaining = self.ceiling - self.reserved - self.incurred - self.estimated_unbilled
        return remaining if remaining > 0 else Decimal("0")


class AgentBudgetLedger:
    """In-memory exact accounting with idempotent reservations.

    Persistence can later wrap this projection; the arithmetic/rules stay here.
    """

    def __init__(self, ceiling: Decimal | str | int) -> None:
        self._ceiling = _decimal(ceiling, "budget ceiling")
        if self._ceiling < 0:
            raise ValueError("budget ceiling cannot be negative")
        self._reserved: dict[str, Decimal] = {}
        self._incurred = Decimal("0")
        self._unbilled: dict[str, Decimal] = {}
        self._settled: set[str] = set()
        self._bills: dict[str, tuple[str, Decimal]] = {}

    def snapshot(self) -> AgentBudgetSnapshot:
        return AgentBudgetSnapshot(
            ceiling=self._ceiling,
            reserved=_sum(self._reserved.values()),
            incurred=self._incurred,
            estimated_unbilled=_sum(self._unbilled.values()),
        )

    def reserve(self, request_id: str, amount: Decimal | str | int) -> None:
        request = _id(request_id, "request_id")
        exact = _decimal(amount, "reservation")
        if exact < 0:
            raise ValueError("reservation cannot be negative")
        prior = self._reserved.get(request)
        if prior is not None:
            if prior != exact:
                raise ValueError("reservation conflict")
            return
        if exact > self.snapshot().available:
            raise ValueError("budget exhausted")
        self._reserved[request] = exact

    def release(self, request_id: str) -> Decimal:
        request = _id(request_id, "request_id")
        if request in self._settled:
            raise ValueError("cannot release after model call settlement")
        return self._reserved.pop(request, Decimal("0"))

    def settle(
        self,
        request_id: str,
        *,
        incurred: Decimal | str | int,
        estimated_unbilled: Decimal | str | int = Decimal("0"),
    ) -> None:
        request = _id(request_id, "request_id")
        cost = _decimal(incurred, "incurred cost")
        unbilled = _decimal(estimated_unbilled, "estimated unbilled cost")
        if cost < 0 or unbilled < 0:
            raise ValueError("costs cannot be negative")
        reserved = self._reserved.get(request)
        if reserved is None:
            raise ValueError("unknown reservation")
        if cost + unbilled > reserved:
            raise ValueError("settlement exceeds reserved ceiling")
        del self._reserved[request]
        self._incurred += cost
        self._unbilled[request] = unbilled
        self._settled.add(request)

    def reconcile_unbilled(
        self,
        *,
        billing_id: str,
        request_id: str,
        billed: Decimal | str | int,
    ) -> None:
        bill = _id(billing_id, "billing_id")
        request = _id(request_id, "request_id")
        exact = _decimal(billed, "billed cost")
        if exact < 0:
            raise ValueError("billed cost cannot be negative")
        prior = self._bills.get(bill)
        if prior is not None:
            if prior != (request, exact):
                raise ValueError("billing reconciliation conflict")
            return
        if request not in self._settled:
            raise ValueError("billing has no matching settled request")
        estimate = self._unbilled.get(request, Decimal("0"))
        self._unbilled[request] = max(Decimal("0"), estimate - exact)
        self._incurred += exact
        self._bills[bill] = (request, exact)


__all__ = ["AgentBudgetLedger", "AgentBudgetSnapshot"]
