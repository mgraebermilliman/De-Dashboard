"""Tests use made-up names and text only (AGENTS.md rule 1.3)."""

import unittest
from datetime import date, datetime

from extract import classify as c

FORM_ITEM = '"De-Millimanize" Device with Milliman Data'


class MatchTests(unittest.TestCase):
    def test_form_with_subject_phrase_is_both(self):
        subject = f"Request for Jane Example : {FORM_ITEM}"
        self.assertEqual(c.match(subject, None, [FORM_ITEM])[0], "Both")

    def test_form_only(self):
        self.assertEqual(c.match("Request for Jane", None, [FORM_ITEM]), ("Form", FORM_ITEM, "Requested Item"))

    def test_phrase_spelling_variants(self):
        for text in ["Demillimanize recent old laptop", "please de-millimanize my PC",
                     "De Millimanized laptop", "demilimanize request", "DEMILLIMANIZING"]:
            with self.subTest(text=text):
                self.assertEqual(c.match(text, None, [])[0], "Phrase")

    def test_phrase_in_description(self):
        self.assertEqual(c.match("Old laptop", "Can it be demillimanized?", [])[2], "Description")

    def test_unrelated_tickets_ignored(self):
        for text in ["Milliman laptop replacement", "Outlook not syncing", "Demo of new tool"]:
            with self.subTest(text=text):
                self.assertIsNone(c.match(text, text, ["Laptop request"]))
                self.assertFalse(c.is_candidate(text, text))


class OutcomeTests(unittest.TestCase):
    def test_override_wins(self):
        result = c.decide_outcome("Closed", [], [], {"Outcome": "Denied", "Reason": "Reviewed"})
        self.assertEqual((result["Outcome"], result["Outcome Source"]), ("Denied", "Manual Override"))

    def test_rejected_approval_is_denied(self):
        approvals = [{"status": "rejected", "approver": "Morgan Manager", "decided_at": datetime(2025, 1, 2)}]
        result = c.decide_outcome("Closed", approvals, [])
        self.assertEqual((result["Outcome"], result["Approver"]), ("Denied", "Morgan Manager"))

    def test_latest_approval_decides(self):
        approvals = [{"status": "rejected", "approver": "A", "decided_at": datetime(2025, 1, 1)},
                     {"status": "approved", "approver": "B", "decided_at": datetime(2025, 1, 5)}]
        self.assertEqual(c.decide_outcome("Open", approvals, [])["Outcome"], "Approved")

    def test_closed_without_denial_wording_is_approved(self):
        self.assertEqual(c.decide_outcome("Closed", [], ["Laptop wiped and handed over"])["Outcome"], "Approved")

    def test_closed_with_denial_wording_needs_review(self):
        result = c.decide_outcome("Closed", [], ["Supervisor approval was denied."])
        self.assertEqual(result["Outcome"], "Needs Review")
        self.assertIn("denied", result["Outcome Evidence"])

    def test_open_ticket_is_pending(self):
        self.assertEqual(c.decide_outcome("Pending", [], [])["Outcome"], "Pending")

    def test_unknown_status_needs_review(self):
        self.assertEqual(c.decide_outcome(None, [], [])["Outcome"], "Needs Review")

    def test_requested_approval_not_a_decision(self):
        approvals = [{"status": "requested", "approver": "A", "decided_at": None}]
        self.assertEqual(c.decide_outcome("Open", approvals, [])["Outcome"], "Pending")


class HelperTests(unittest.TestCase):
    def test_holiday_season_bounds(self):
        self.assertTrue(c.is_holiday_season(date(2025, 11, 15)))
        self.assertTrue(c.is_holiday_season(date(2026, 1, 5)))
        self.assertFalse(c.is_holiday_season(date(2025, 11, 14)))
        self.assertFalse(c.is_holiday_season(date(2026, 1, 6)))

    def test_device_type(self):
        self.assertEqual(c.device_type("Lenovo ThinkPad E14", None), "Laptop")
        self.assertEqual(c.device_type("ThinkCentre M920x", None), "Desktop")
        self.assertEqual(c.device_type(None, "Laptop"), "Laptop")
        self.assertEqual(c.device_type("Mystery Box 3000", "Hardware"), "Unknown")

    def test_certificate_names(self):
        self.assertTrue(c.is_certificate("Certificate-PC1-ABC-Success-2026-11-12-14-15-49.pdf"))
        self.assertFalse(c.is_certificate("screenshot.png"))

    def test_normalize_name(self):
        self.assertEqual(c.normalize_name("  alex   TECH <alex.tech@example.com>"), "alex tech")


if __name__ == "__main__":
    unittest.main()
