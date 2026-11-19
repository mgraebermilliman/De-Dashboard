"""Tests use made-up names and text only (AGENTS.md rule 1.3)."""

import unittest

from extract import classify as c


class TicketKindTests(unittest.TestCase):
    def test_form_subject(self):
        subject = 'Request for Jane Example : "De-Millimanize" Device with Milliman Data'
        self.assertEqual(c.ticket_kind(subject, None), c.FORM)

    def test_legacy_spelling_variants(self):
        for text in ["Demillimanize recent old laptop", "please de-millimanize my PC",
                     "De Millimanized laptop", "demilimanize request", "DEMILLIMANIZING"]:
            with self.subTest(text=text):
                self.assertEqual(c.ticket_kind(text, None), c.LEGACY)

    def test_legacy_found_in_description(self):
        self.assertEqual(c.ticket_kind("Old laptop", "Can it be demillimanized?"), c.LEGACY)

    def test_unrelated_tickets_ignored(self):
        for text in ["Milliman laptop replacement", "Outlook not syncing", "Demo of new tool"]:
            with self.subTest(text=text):
                self.assertIsNone(c.ticket_kind(text, text))


class OutcomeTests(unittest.TestCase):
    def test_closed_is_completed(self):
        self.assertEqual(c.outcome("Closed"), c.COMPLETED)

    def test_other_status_shown_as_is(self):
        self.assertEqual(c.outcome("Pending"), "Not completed (Pending)")

    def test_missing_status_unknown(self):
        self.assertEqual(c.outcome(None), c.UNKNOWN)

    def test_denial_flag_wins(self):
        self.assertEqual(c.outcome("Closed", denial_flagged=True), c.POSSIBLE_DENIAL)


class DenialTests(unittest.TestCase):
    def test_detects_denial_words(self):
        for text in ["Request denied by supervisor", "Approval was rejected", "Not approved."]:
            with self.subTest(text=text):
                self.assertTrue(c.mentions_denial(text))

    def test_ignores_normal_notes(self):
        self.assertFalse(c.mentions_denial("Laptop wiped and handed over"))
        self.assertFalse(c.mentions_denial(None))


class TechnicianTests(unittest.TestCase):
    def test_matches_ignoring_case_email_and_spacing(self):
        techs = {c.normalize_name("Alex Tech")}
        self.assertTrue(c.is_technician("  alex   TECH <alex.tech@example.com>", techs))
        self.assertFalse(c.is_technician("Jane Example", techs))


if __name__ == "__main__":
    unittest.main()
