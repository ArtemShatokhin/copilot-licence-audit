"""Tests for audit.py. Run with: python3 -m unittest discover -s tests"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit  # noqa: E402


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _paths(self, licences, licence_header, usage, usage_header):
        lp = os.path.join(self.dir, "licences.csv")
        up = os.path.join(self.dir, "usage.csv")
        write_csv(lp, licence_header, licences)
        write_csv(up, usage_header, usage)
        return lp, up

    def test_counts_and_spend(self):
        lp, up = self._paths(
            [
                ("a@x", "Copilot", "30", "Enabled"),
                ("b@x", "Copilot", "30", "Enabled"),
                ("c@x", "Copilot", "30", "Disabled"),
            ],
            ["user", "sku", "monthly_price_usd", "state"],
            [("a@x", "10", "2026-10-20"), ("b@x", "0", "")],
            ["user", "active_days_28", "last_activity_date"],
        )
        result = audit.load(lp, up)
        data = result.as_dict()
        self.assertEqual(data["seats_paid"], 2)
        self.assertEqual(data["seats_active"], 1)
        self.assertEqual(data["seats_idle"], 1)
        self.assertEqual(data["monthly_spend_usd"], 60.0)
        self.assertEqual(data["idle_monthly_spend_usd"], 30.0)
        self.assertEqual(data["idle_annual_spend_usd"], 360.0)

    def test_missing_usage_row_counts_as_idle(self):
        lp, up = self._paths(
            [("a@x", "Copilot", "30", "Enabled")],
            ["user", "sku", "monthly_price_usd", "state"],
            [("b@x", "20", "2026-10-20")],
            ["user", "active_days_28", "last_activity_date"],
        )
        result = audit.load(lp, up)
        self.assertEqual(result.as_dict()["seats_idle"], 1)
        self.assertEqual(result.as_dict()["seats_without_usage_row"], ["a@x"])

    def test_two_skus_for_one_user_collapse_to_one_seat(self):
        lp, up = self._paths(
            [
                ("a@x", "Copilot", "30", "Enabled"),
                ("a@x", "Copilot Studio", "200", "Enabled"),
            ],
            ["user", "sku", "monthly_price_usd", "state"],
            [("a@x", "14", "2026-10-20")],
            ["user", "active_days_28", "last_activity_date"],
        )
        result = audit.load(lp, up)
        data = result.as_dict()
        self.assertEqual(data["seats_paid"], 1)
        self.assertEqual(data["monthly_spend_usd"], 230.0)

    def test_active_day_floor(self):
        lp, up = self._paths(
            [("a@x", "Copilot", "30", "Enabled")],
            ["user", "sku", "monthly_price_usd", "state"],
            [("a@x", "2", "2026-10-20")],
            ["user", "active_days_28", "last_activity_date"],
        )
        self.assertEqual(audit.load(lp, up, min_active_days=1).as_dict()["seats_active"], 1)
        self.assertEqual(audit.load(lp, up, min_active_days=5).as_dict()["seats_active"], 0)

    def test_header_aliases_are_matched(self):
        lp, up = self._paths(
            [("a@x", "Copilot", "$30.00", "Enabled")],
            ["User Principal Name", "Product Name", "Unit Price", "Status"],
            [("a@x", "12", "2026-10-20")],
            ["User Principal Name", "Active Days", "Last Activity Date"],
        )
        result = audit.load(lp, up)
        self.assertEqual(result.as_dict()["monthly_spend_usd"], 30.0)

    def test_missing_column_raises(self):
        lp, up = self._paths(
            [("a@x", "Copilot", "30", "Enabled")],
            ["user", "sku", "monthly_price_usd", "state"],
            [("a@x", "12")],
            ["user", "active_days_28"],
        )
        with self.assertRaises(audit.AuditError):
            audit.load(lp, up)

    def test_agent_hours_use_list_rate(self):
        lp, up = self._paths(
            [("a@x", "Copilot", "11", "Enabled")],
            ["user", "sku", "monthly_price_usd", "state"],
            [("a@x", "0", "")],
            ["user", "active_days_28", "last_activity_date"],
        )
        result = audit.load(lp, up)
        # $11 idle / $0.11 per agent hour = 100 hours
        self.assertAlmostEqual(result.break_even_agent_hours(), 100.0, places=1)


if __name__ == "__main__":
    unittest.main()
