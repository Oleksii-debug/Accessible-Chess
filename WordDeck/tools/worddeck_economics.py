#!/usr/bin/env python3
"""Deterministic unit-economics calculator for WordDeck planning scenarios."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

FOUR_DP = Decimal("0.0001")
MONEY_DP = Decimal("0.01")
ONE = Decimal("1")
ZERO = Decimal("0")


class EconomicsInputError(ValueError):
    pass


def _d(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EconomicsInputError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise EconomicsInputError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class EconomicsInputs:
    scenario_name: str
    currency: str
    monthly_price_gross: Decimal
    annual_price_gross: Decimal
    monthly_plan_share: Decimal
    annual_plan_share: Decimal
    indirect_tax_rate: Decimal
    payment_fee_rate: Decimal
    refund_rate: Decimal
    variable_infra_per_active_month: Decimal
    support_per_active_month: Decimal
    monthly_fixed_cost: Decimal
    customer_acquisition_cost: Decimal
    expected_paid_lifetime_months: Decimal
    active_paid_customers: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EconomicsInputs":
        scenario_name = str(raw.get("scenario_name", "")).strip()
        currency = str(raw.get("currency", "")).strip().upper()
        if not scenario_name:
            raise EconomicsInputError("scenario_name is required")
        if not currency or len(currency) > 8:
            raise EconomicsInputError("currency is required and must be at most 8 characters")
        try:
            active = int(raw["active_paid_customers"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EconomicsInputError("active_paid_customers must be an integer") from exc
        instance = cls(
            scenario_name=scenario_name,
            currency=currency,
            monthly_price_gross=_d(raw.get("monthly_price_gross"), "monthly_price_gross"),
            annual_price_gross=_d(raw.get("annual_price_gross"), "annual_price_gross"),
            monthly_plan_share=_d(raw.get("monthly_plan_share"), "monthly_plan_share"),
            annual_plan_share=_d(raw.get("annual_plan_share"), "annual_plan_share"),
            indirect_tax_rate=_d(raw.get("indirect_tax_rate"), "indirect_tax_rate"),
            payment_fee_rate=_d(raw.get("payment_fee_rate"), "payment_fee_rate"),
            refund_rate=_d(raw.get("refund_rate"), "refund_rate"),
            variable_infra_per_active_month=_d(raw.get("variable_infra_per_active_month"), "variable_infra_per_active_month"),
            support_per_active_month=_d(raw.get("support_per_active_month"), "support_per_active_month"),
            monthly_fixed_cost=_d(raw.get("monthly_fixed_cost"), "monthly_fixed_cost"),
            customer_acquisition_cost=_d(raw.get("customer_acquisition_cost"), "customer_acquisition_cost"),
            expected_paid_lifetime_months=_d(raw.get("expected_paid_lifetime_months"), "expected_paid_lifetime_months"),
            active_paid_customers=active,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        for name, value in {
            "monthly_price_gross": self.monthly_price_gross,
            "annual_price_gross": self.annual_price_gross,
            "expected_paid_lifetime_months": self.expected_paid_lifetime_months,
        }.items():
            if value <= ZERO:
                raise EconomicsInputError(f"{name} must be > 0")
        for name, value in {
            "variable_infra_per_active_month": self.variable_infra_per_active_month,
            "support_per_active_month": self.support_per_active_month,
            "monthly_fixed_cost": self.monthly_fixed_cost,
            "customer_acquisition_cost": self.customer_acquisition_cost,
        }.items():
            if value < ZERO:
                raise EconomicsInputError(f"{name} must be >= 0")
        for name, value in {
            "monthly_plan_share": self.monthly_plan_share,
            "annual_plan_share": self.annual_plan_share,
        }.items():
            if value < ZERO or value > ONE:
                raise EconomicsInputError(f"{name} must be in [0, 1]")
        for name, value in {
            "indirect_tax_rate": self.indirect_tax_rate,
            "payment_fee_rate": self.payment_fee_rate,
            "refund_rate": self.refund_rate,
        }.items():
            if value < ZERO or value >= ONE:
                raise EconomicsInputError(f"{name} must be in [0, 1)")
        if self.monthly_plan_share + self.annual_plan_share != ONE:
            raise EconomicsInputError("monthly_plan_share + annual_plan_share must equal 1")
        if self.active_paid_customers < 0:
            raise EconomicsInputError("active_paid_customers must be >= 0")


def _q(value: Decimal) -> str:
    return format(value.quantize(FOUR_DP, rounding=ROUND_HALF_UP), "f")


def _money(value: Decimal) -> str:
    return format(value.quantize(MONEY_DP, rounding=ROUND_HALF_UP), "f")


def calculate(inputs: EconomicsInputs) -> dict[str, Any]:
    gross = inputs.monthly_plan_share * inputs.monthly_price_gross + inputs.annual_plan_share * (inputs.annual_price_gross / Decimal(12))
    post_refund = gross * (ONE - inputs.refund_rate)
    net = post_refund / (ONE + inputs.indirect_tax_rate)
    fees = post_refund * inputs.payment_fee_rate
    variable = inputs.variable_infra_per_active_month + inputs.support_per_active_month
    contribution = net - fees - variable
    operating = Decimal(inputs.active_paid_customers) * contribution - inputs.monthly_fixed_cost
    margin = contribution / net
    lifetime_before_cac = contribution * inputs.expected_paid_lifetime_months
    lifetime_after_cac = lifetime_before_cac - inputs.customer_acquisition_cost
    if contribution > ZERO:
        break_even = int((inputs.monthly_fixed_cost / contribution).to_integral_value(rounding=ROUND_CEILING))
        payback = inputs.customer_acquisition_cost / contribution
        ratio = lifetime_before_cac / inputs.customer_acquisition_cost if inputs.customer_acquisition_cost > ZERO else None
    else:
        break_even = None
        payback = None
        ratio = None
    return {
        "scenario_name": inputs.scenario_name,
        "currency": inputs.currency,
        "assumption_warning": "Planning assumptions only; not market facts, tax/legal advice, or release authorization.",
        "monthly_equivalent_gross_revenue_per_payer": _money(gross),
        "monthly_post_refund_gross_per_payer": _money(post_refund),
        "monthly_net_revenue_after_indirect_tax_per_payer": _money(net),
        "monthly_payment_fees_per_payer": _money(fees),
        "monthly_variable_cost_per_payer": _money(variable),
        "monthly_contribution_per_payer": _money(contribution),
        "contribution_margin_ratio": _q(margin),
        "break_even_paid_customers": break_even,
        "cac_payback_months": _q(payback) if payback is not None else None,
        "lifetime_contribution_before_cac": _money(lifetime_before_cac),
        "lifetime_contribution_after_cac": _money(lifetime_after_cac),
        "ltv_to_cac_ratio": _q(ratio) if ratio is not None else None,
        "monthly_operating_result_at_active_customer_count": _money(operating),
        "annualized_operating_result_at_active_customer_count": _money(operating * Decimal(12)),
    }


def load_scenario(path: str | Path) -> EconomicsInputs:
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise EconomicsInputError("scenario root must be an object")
    return EconomicsInputs.from_mapping(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate WordDeck planning unit economics.")
    parser.add_argument("scenario")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    try:
        result = calculate(load_scenario(args.scenario))
    except (OSError, json.JSONDecodeError, EconomicsInputError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=None if args.compact else 2, separators=(",", ":") if args.compact else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
