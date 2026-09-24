from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Iterable


class EconomicModelError(ValueError):
    """Stable validation error for deterministic planning inputs."""


def _d(value: str | int | Decimal) -> Decimal:
    if isinstance(value, bool):
        raise EconomicModelError("boolean values are not valid financial inputs")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except Exception as exc:
            raise EconomicModelError("invalid decimal input") from exc
    else:
        raise EconomicModelError(
            "financial inputs must be Decimal, int, or decimal string"
        )
    if not result.is_finite():
        raise EconomicModelError("financial inputs must be finite")
    return result


def _rate(value: str | int | Decimal, name: str) -> Decimal:
    result = _d(value)
    if result < 0 or result > 1:
        raise EconomicModelError(f"{name} must be between 0 and 1")
    return result


def _money(
    value: str | int | Decimal,
    name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    result = _d(value)
    if result < 0 or (not allow_zero and result == 0):
        relation = "non-negative" if allow_zero else "positive"
        raise EconomicModelError(f"{name} must be {relation}")
    return result


@dataclass(frozen=True)
class PriceMix:
    monthly_price: Decimal
    annual_price: Decimal
    monthly_share: Decimal
    annual_share: Decimal

    @classmethod
    def create(
        cls,
        *,
        monthly_price: str | int | Decimal,
        annual_price: str | int | Decimal,
        monthly_share: str | int | Decimal,
        annual_share: str | int | Decimal,
    ) -> "PriceMix":
        monthly = _money(monthly_price, "monthly_price", allow_zero=False)
        annual = _money(annual_price, "annual_price", allow_zero=False)
        monthly_ratio = _rate(monthly_share, "monthly_share")
        annual_ratio = _rate(annual_share, "annual_share")
        if monthly_ratio + annual_ratio != Decimal("1"):
            raise EconomicModelError(
                "monthly_share and annual_share must sum to 1"
            )
        return cls(monthly, annual, monthly_ratio, annual_ratio)

    @property
    def gross_monthly_revenue_per_paid_customer(self) -> Decimal:
        return (
            self.monthly_price * self.monthly_share
            + (self.annual_price / Decimal("12")) * self.annual_share
        )


@dataclass(frozen=True)
class UnitEconomicsInputs:
    refund_rate: Decimal
    indirect_tax_rate: Decimal
    payment_fee_rate: Decimal
    payment_fee_fixed: Decimal
    variable_support_cost: Decimal
    variable_hosting_cost: Decimal
    variable_other_cost: Decimal
    monthly_fixed_costs: Decimal
    customer_acquisition_cost: Decimal
    monthly_churn_rate: Decimal

    @classmethod
    def create(
        cls,
        *,
        refund_rate: str | int | Decimal = "0",
        indirect_tax_rate: str | int | Decimal = "0",
        payment_fee_rate: str | int | Decimal = "0",
        payment_fee_fixed: str | int | Decimal = "0",
        variable_support_cost: str | int | Decimal = "0",
        variable_hosting_cost: str | int | Decimal = "0",
        variable_other_cost: str | int | Decimal = "0",
        monthly_fixed_costs: str | int | Decimal = "0",
        customer_acquisition_cost: str | int | Decimal = "0",
        monthly_churn_rate: str | int | Decimal = "0",
    ) -> "UnitEconomicsInputs":
        return cls(
            refund_rate=_rate(refund_rate, "refund_rate"),
            indirect_tax_rate=_rate(indirect_tax_rate, "indirect_tax_rate"),
            payment_fee_rate=_rate(payment_fee_rate, "payment_fee_rate"),
            payment_fee_fixed=_money(payment_fee_fixed, "payment_fee_fixed"),
            variable_support_cost=_money(
                variable_support_cost, "variable_support_cost"
            ),
            variable_hosting_cost=_money(
                variable_hosting_cost, "variable_hosting_cost"
            ),
            variable_other_cost=_money(
                variable_other_cost, "variable_other_cost"
            ),
            monthly_fixed_costs=_money(
                monthly_fixed_costs, "monthly_fixed_costs"
            ),
            customer_acquisition_cost=_money(
                customer_acquisition_cost, "customer_acquisition_cost"
            ),
            monthly_churn_rate=_rate(
                monthly_churn_rate, "monthly_churn_rate"
            ),
        )


@dataclass(frozen=True)
class UnitEconomicsResult:
    gross_monthly_revenue_per_paid_customer: Decimal
    recognized_revenue_after_refunds: Decimal
    indirect_tax_cost: Decimal
    payment_cost: Decimal
    variable_cost: Decimal
    contribution_per_paid_customer: Decimal
    contribution_margin: Decimal
    break_even_paid_customers: int | None
    cac_payback_months: Decimal | None
    expected_customer_lifetime_months: Decimal | None
    expected_lifetime_contribution: Decimal | None
    lifetime_contribution_to_cac: Decimal | None
    monthly_fixed_costs: Decimal

    def monthly_operating_result(self, paid_customers: int) -> Decimal:
        if isinstance(paid_customers, bool) or not isinstance(
            paid_customers, int
        ):
            raise EconomicModelError("paid_customers must be an integer")
        if paid_customers < 0:
            raise EconomicModelError("paid_customers must be non-negative")
        return (
            self.contribution_per_paid_customer * Decimal(paid_customers)
            - self.monthly_fixed_costs
        )


def calculate_unit_economics(
    prices: PriceMix,
    costs: UnitEconomicsInputs,
) -> UnitEconomicsResult:
    gross = prices.gross_monthly_revenue_per_paid_customer
    recognized = gross * (Decimal("1") - costs.refund_rate)
    tax = recognized * costs.indirect_tax_rate
    payment = (
        recognized * costs.payment_fee_rate + costs.payment_fee_fixed
    )
    variable = (
        costs.variable_support_cost
        + costs.variable_hosting_cost
        + costs.variable_other_cost
    )
    contribution = recognized - tax - payment - variable
    margin = contribution / recognized if recognized > 0 else Decimal("0")

    if contribution <= 0:
        break_even = None
        payback = None
    else:
        break_even = int(
            (costs.monthly_fixed_costs / contribution).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        payback = (
            costs.customer_acquisition_cost / contribution
            if costs.customer_acquisition_cost > 0
            else Decimal("0")
        )

    if costs.monthly_churn_rate == 0:
        lifetime = None
        lifetime_contribution = None
        ratio = None
    else:
        lifetime = Decimal("1") / costs.monthly_churn_rate
        lifetime_contribution = contribution * lifetime
        ratio = (
            lifetime_contribution / costs.customer_acquisition_cost
            if costs.customer_acquisition_cost > 0
            else None
        )

    return UnitEconomicsResult(
        gross_monthly_revenue_per_paid_customer=gross,
        recognized_revenue_after_refunds=recognized,
        indirect_tax_cost=tax,
        payment_cost=payment,
        variable_cost=variable,
        contribution_per_paid_customer=contribution,
        contribution_margin=margin,
        break_even_paid_customers=break_even,
        cac_payback_months=payback,
        expected_customer_lifetime_months=lifetime,
        expected_lifetime_contribution=lifetime_contribution,
        lifetime_contribution_to_cac=ratio,
        monthly_fixed_costs=costs.monthly_fixed_costs,
    )


@dataclass(frozen=True)
class CustomerScenario:
    name: str
    paid_customers: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise EconomicModelError("scenario name must be non-empty")
        if isinstance(self.paid_customers, bool) or not isinstance(
            self.paid_customers, int
        ):
            raise EconomicModelError("paid_customers must be an integer")
        if self.paid_customers < 0:
            raise EconomicModelError("paid_customers must be non-negative")


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    paid_customers: int
    monthly_operating_result: Decimal
    annualized_operating_result: Decimal


def evaluate_scenarios(
    result: UnitEconomicsResult,
    scenarios: Iterable[CustomerScenario],
) -> tuple[ScenarioResult, ...]:
    output: list[ScenarioResult] = []
    seen: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, CustomerScenario):
            raise EconomicModelError(
                "scenarios must contain CustomerScenario values"
            )
        key = scenario.name.strip()
        if key in seen:
            raise EconomicModelError("scenario names must be unique")
        seen.add(key)
        monthly = result.monthly_operating_result(
            scenario.paid_customers
        )
        output.append(
            ScenarioResult(
                name=key,
                paid_customers=scenario.paid_customers,
                monthly_operating_result=monthly,
                annualized_operating_result=monthly * Decimal("12"),
            )
        )
    return tuple(output)
