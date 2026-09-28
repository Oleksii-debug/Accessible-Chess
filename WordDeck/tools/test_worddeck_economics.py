import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worddeck_economics import EconomicsInputError, EconomicsInputs, calculate, load_scenario


def baseline(**overrides):
    raw = {
        "scenario_name": "test", "currency": "EUR",
        "monthly_price_gross": 9.99, "annual_price_gross": 69.99,
        "monthly_plan_share": 0.35, "annual_plan_share": 0.65,
        "indirect_tax_rate": 0.20, "payment_fee_rate": 0.15, "refund_rate": 0.03,
        "variable_infra_per_active_month": 0.20, "support_per_active_month": 0.30,
        "monthly_fixed_cost": 1500, "customer_acquisition_cost": 20,
        "expected_paid_lifetime_months": 14, "active_paid_customers": 500,
    }
    raw.update(overrides)
    return raw


class EconomicsTests(unittest.TestCase):
    def test_baseline_is_deterministic(self):
        result = calculate(EconomicsInputs.from_mapping(baseline()))
        self.assertEqual("7.29", result["monthly_equivalent_gross_revenue_per_payer"])
        self.assertEqual("4.33", result["monthly_contribution_per_payer"])
        self.assertEqual("0.7351", result["contribution_margin_ratio"])
        self.assertEqual(347, result["break_even_paid_customers"])
        self.assertEqual("4.6184", result["cac_payback_months"])
        self.assertEqual("3.0313", result["ltv_to_cac_ratio"])
        self.assertEqual("665.24", result["monthly_operating_result_at_active_customer_count"])

    def test_plan_shares_must_sum_to_one(self):
        with self.assertRaisesRegex(EconomicsInputError, "must equal 1"):
            EconomicsInputs.from_mapping(baseline(monthly_plan_share=0.5, annual_plan_share=0.4))

    def test_non_positive_contribution_has_no_break_even_or_payback(self):
        result = calculate(EconomicsInputs.from_mapping(baseline(variable_infra_per_active_month=10, support_per_active_month=10)))
        self.assertIsNone(result["break_even_paid_customers"])
        self.assertIsNone(result["cac_payback_months"])
        self.assertIsNone(result["ltv_to_cac_ratio"])

    def test_annual_price_is_normalized_to_monthly_equivalent(self):
        result = calculate(EconomicsInputs.from_mapping(baseline(
            monthly_price_gross=12, annual_price_gross=120,
            monthly_plan_share=0, annual_plan_share=1,
            indirect_tax_rate=0, payment_fee_rate=0, refund_rate=0,
            variable_infra_per_active_month=0, support_per_active_month=0,
            monthly_fixed_cost=0, customer_acquisition_cost=0,
        )))
        self.assertEqual("10.00", result["monthly_equivalent_gross_revenue_per_payer"])
        self.assertEqual("10.00", result["monthly_contribution_per_payer"])
        self.assertEqual(0, result["break_even_paid_customers"])
        self.assertIsNone(result["ltv_to_cac_ratio"])

    def test_invalid_rate_is_rejected(self):
        with self.assertRaisesRegex(EconomicsInputError, r"\[0, 1\)"):
            EconomicsInputs.from_mapping(baseline(refund_rate=1))

    def test_json_loader_requires_object_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with self.assertRaisesRegex(EconomicsInputError, "root must be an object"):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
