from decimal import Decimal
import unittest

from acs.economic_planning import (
    CustomerScenario,
    EconomicModelError,
    PriceMix,
    UnitEconomicsInputs,
    calculate_unit_economics,
    evaluate_scenarios,
)


class EconomicPlanningTests(unittest.TestCase):
    def setUp(self):
        self.prices = PriceMix.create(
            monthly_price="9.90",
            annual_price="99",
            monthly_share="0.4",
            annual_share="0.6",
        )
        self.costs = UnitEconomicsInputs.create(
            refund_rate="0.03",
            indirect_tax_rate="0.20",
            payment_fee_rate="0.029",
            payment_fee_fixed="0.30",
            variable_support_cost="0.80",
            variable_hosting_cost="0.50",
            variable_other_cost="0.20",
            monthly_fixed_costs="1500",
            customer_acquisition_cost="25",
            monthly_churn_rate="0.03",
        )

    def test_price_mix_monthly_equivalent_is_deterministic(self):
        self.assertEqual(
            self.prices.gross_monthly_revenue_per_paid_customer,
            Decimal("8.910"),
        )

    def test_unit_economics_baseline(self):
        result = calculate_unit_economics(self.prices, self.costs)
        self.assertEqual(
            result.contribution_per_paid_customer,
            Decimal("4.86352170"),
        )
        self.assertEqual(result.break_even_paid_customers, 309)
        self.assertEqual(
            result.monthly_operating_result(500),
            Decimal("931.76085000"),
        )

    def test_non_positive_contribution_has_no_break_even(self):
        costs = UnitEconomicsInputs.create(variable_support_cost="100")
        result = calculate_unit_economics(self.prices, costs)
        self.assertIsNone(result.break_even_paid_customers)
        self.assertIsNone(result.cac_payback_months)

    def test_zero_churn_does_not_invent_lifetime(self):
        costs = UnitEconomicsInputs.create(
            customer_acquisition_cost="10",
            monthly_churn_rate="0",
        )
        result = calculate_unit_economics(self.prices, costs)
        self.assertIsNone(result.expected_customer_lifetime_months)
        self.assertIsNone(result.expected_lifetime_contribution)
        self.assertIsNone(result.lifetime_contribution_to_cac)

    def test_invalid_rates_and_price_mix_fail_closed(self):
        with self.assertRaises(EconomicModelError):
            UnitEconomicsInputs.create(refund_rate="1.01")
        with self.assertRaises(EconomicModelError):
            PriceMix.create(
                monthly_price="9.90",
                annual_price="99",
                monthly_share="0.4",
                annual_share="0.5",
            )
        with self.assertRaises(EconomicModelError):
            PriceMix.create(
                monthly_price=True,
                annual_price="99",
                monthly_share="0.4",
                annual_share="0.6",
            )

    def test_scenarios_are_unique_and_annualized(self):
        result = calculate_unit_economics(self.prices, self.costs)
        scenarios = evaluate_scenarios(
            result,
            (
                CustomerScenario("pilot", 100),
                CustomerScenario("growth", 500),
            ),
        )
        self.assertEqual(len(scenarios), 2)
        self.assertEqual(
            scenarios[1].annualized_operating_result,
            scenarios[1].monthly_operating_result * Decimal("12"),
        )
        with self.assertRaises(EconomicModelError):
            evaluate_scenarios(
                result,
                (
                    CustomerScenario("pilot", 100),
                    CustomerScenario("pilot", 200),
                ),
            )

    def test_customer_count_validation_is_exact(self):
        result = calculate_unit_economics(self.prices, self.costs)
        with self.assertRaises(EconomicModelError):
            result.monthly_operating_result(-1)
        with self.assertRaises(EconomicModelError):
            result.monthly_operating_result(True)
        with self.assertRaises(EconomicModelError):
            CustomerScenario("bad", True)


if __name__ == "__main__":
    unittest.main()
