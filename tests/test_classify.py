"""Tests use made-up names and text only (AGENTS.md rule 1.3)."""

import unittest
from datetime import date, datetime

from extract import classify as c

FORM_ITEM = '"De-Millimanize" Device with Milliman Data'


class MatchTests(unittest.TestCase):
    def assess(self, subject=None, description=None, resolution=None, items=()):
        return c.assess(subject, description, resolution, list(items))

    def test_form_is_always_high(self):
        both = self.assess(f"Request for Jane Example : {FORM_ITEM}", items=[FORM_ITEM])
        self.assertEqual((both["Match Source"], both["Confidence"]), ("Both", "High"))
        form = self.assess("Request for Jane", items=[FORM_ITEM])
        self.assertEqual((form["Match Source"], form["Matched Phrase"], form["Matched Field"], form["Confidence"]),
                         ("Form", FORM_ITEM, "Requested Item", "High"))

    def test_phrase_spelling_variants(self):
        for text in ["Demillimanize recent old laptop", "please de-millimanize my PC",
                     "De Millimanized laptop", "demilimanize request", "DEMILLIMANIZING"]:
            with self.subTest(text=text):
                self.assertEqual(self.assess(text)["Match Source"], "Phrase")

    def test_phrase_in_description(self):
        self.assertEqual(self.assess("Old laptop", "Can it be demillimanized?")["Matched Field"], "Description")

    def test_unrelated_tickets_ignored(self):
        for text in ["Milliman laptop replacement", "Outlook not syncing", "Demo of new tool",
                     "How do I keep my laptop from sleeping", "Install an app for personal use",
                     "I have to keep a desktop fan on it", "I can't keep my laptop with me on the trip",
                     "Files to keep on this device"]:
            with self.subTest(text=text):
                self.assertIsNone(self.assess(text, text, items=["Laptop request"]))
                self.assertFalse(c.is_candidate(text, text))

    def test_keep_and_personal_use_wording_is_a_candidate(self):
        for text in ["Request to keep company laptop", "Laptop for personal use",
                     "Can I keep my old ThinkPad when I retire?"]:
            with self.subTest(text=text):
                self.assertTrue(c.is_candidate(text, None))
                self.assertEqual(self.assess(text)["Confidence"], "Medium")

    def test_confidence_levels(self):
        clear = self.assess("Demillimanize old laptop", "I would like to keep my old laptop for personal use.",
                            "Demillimanized laptop for Jane Example")
        self.assertEqual(clear["Confidence"], "High")
        keep_only = self.assess("Keep company laptop", "Can I keep my laptop for personal use after the refresh?")
        self.assertEqual(keep_only["Confidence"], "High")
        # A mention in the description or the technician's note doesn't make the ticket a request.
        mention = self.assess("Remote restart", "I am travelling with a de-millimanized laptop.")
        self.assertEqual(mention["Confidence"], "Medium")
        notes_only = self.assess("Test laptop for a project", "We chose option 2: a de-millimanized spare.",
                                 "De-Millimanized a spare laptop")
        self.assertEqual(notes_only["Confidence"], "Medium")
        weak = self.assess("New laptop", "My laptop is slow. " + "x" * 200 + " I use this app for personal use.")
        self.assertEqual(weak["Confidence"], "Low")
        self.assertIn("no device named nearby", weak["Evidence"])

    def test_excerpt_is_cut_around_the_wording(self):
        text = "a " * 200 + "please de-millimanize it " + "b " * 200
        cut = c.excerpt(text)
        self.assertIn("de-millimanize", cut)
        self.assertLess(len(cut), 260)

    def test_recipient_named_in_the_subject(self):
        item = '"De-Millimanize" Device with Milliman Data'
        self.assertEqual(c.recipient_from_subject(f"Request for Jane Example : {item}"), "Jane Example")
        self.assertEqual(c.recipient_from_subject(f'Request for  Jane   Example :{item}'), "Jane Example")
        self.assertEqual(c.recipient_from_subject('Request for Jane Example : De-millimanized Device with Milliman Data'),
                         "Jane Example")
        for subject in ("Demillimanize recent old laptop", "Request for a new monitor : Hardware", None, ""):
            with self.subTest(subject=subject):
                self.assertIsNone(c.recipient_from_subject(subject))

    def test_recipient_named_in_the_resolution_note(self):
        cases = {
            "De-Millimanized laptop for Jane Example": "Jane Example",
            "Machine has been wiped and given to Jane Example": "Jane Example",
            "De-Millimanized for Goodcause": "Goodcause",
            "Provided to Jane": "Jane",
            "Donation to a school. Jane Example.": None,
            "De-millimanized for local charity (For Jane)": None,
            "Successful PC wipe for ABC-HLTH-10-I-1.": None,
            "Wiped laptop securely to provide to EP.": None,
            "Moved personal data to Desktop folder.": None,
            "laptop wiped and shipped back to user": None,
            "Done.": None,
            None: None,
        }
        for note, expected in cases.items():
            with self.subTest(note=note):
                self.assertEqual(c.recipient_from_note(note), expected)


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

    def test_model_names_are_tidied(self):
        cases = {
            "lenovo t14s": "ThinkPad T14s", "Lenovo ThinkPad T14s Gen 2i": "ThinkPad T14s Gen 2",
            "Lenovo M90Q Gen3": "ThinkCentre M90q Gen 3", "Lenovo Think Centre M920X": "ThinkCentre M920x",
            "ThinkPad X1 2in1 Gen 9": "ThinkPad X1 2in1 Gen 9", "lenovo x1": "ThinkPad X1",
            "Lenovo X1 Carbon": "ThinkPad X1 Carbon", "P16s Gen 2": "ThinkPad P16s Gen 2",
            "Dell Latitude 7420": "Dell Latitude 7420", "Latitude 7410": "Dell Latitude 7410",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(c.model_name(raw), expected)

    def test_serial_numbers_and_codes_typed_as_the_model_are_not_model_names(self):
        for raw in ("Mj0e843g", "PF4RYB96", "20ny", "20ny-s20v00", "S09b00", "Test", "n/a"):
            with self.subTest(raw=raw):
                self.assertIsNone(c.model_name(raw))
        # ...but a real name that happens to be long, or has a space in it, is kept.
        self.assertEqual(c.model_name("Lenovo T14s"), "ThinkPad T14s")
        self.assertEqual(c.model_name("ThinkPad E490"), "ThinkPad E490")

    def test_the_old_pc_name_spells_out_the_model(self):
        cases = {
            "MILWI-T15-JF": "ThinkPad T15", "milwh-t480s-ab": "ThinkPad T480s", "CMH-P14S-JF": "ThinkPad P14s",
            "MilwH-M920x-AB": "ThinkCentre M920x", "HEBO-T590-AB": "ThinkPad T590", "MilwH-SURFP-AB": "Surface Pro",
            "CMHH-7410-AB": "Dell Latitude 7410", "NYMHG-X1C-AB": "ThinkPad X1 Carbon",
            "CMH-ITS-AB": None, "WR1-AB": None, "MKE-AB": None, "HEBM-POOL-AB": None, "N/A": None, None: None,
            "NYMHG-5CG03474Y.milliman.com": None,
        }
        for pc_name, expected in cases.items():
            with self.subTest(pc_name=pc_name):
                self.assertEqual(c.model_from_pc_name(pc_name), expected)

    def test_pc_name_is_found_inside_the_certificate_file_name(self):
        name = "Certificate-INT-P14S-JF-PF4H490T-0025-Success-2025-11-20-15-49-37.pdf"
        self.assertEqual(c.certificate_pc_name(name), "INT-P14S-JF")
        self.assertEqual(c.model_from_pc_name(c.certificate_pc_name(name)), "ThinkPad P14s")
        # The serial and disk number are never read as part of the model.
        self.assertIsNone(c.model_from_pc_name(c.certificate_pc_name(
            "Certificate-ABC-JF-PF7034AB-7034-Success-2025-11-20-15-49-37.pdf")))
        self.assertIsNone(c.certificate_pc_name("screenshot.png"))

    def test_machine_type_codes_and_blanks_are_not_model_names(self):
        for raw in (None, "", "  ", "21HLS1WQ00", "21BT001KUS"):
            with self.subTest(raw=raw):
                self.assertIsNone(c.model_name(raw))
        self.assertEqual(c.machine_type("LENOVO 21HLS1WQ00"), "21HL")
        self.assertIsNone(c.machine_type("Dell Inc. 07MHG4"))

    def test_model_line_drops_generation_and_latitude_number(self):
        self.assertEqual(c.model_line("ThinkPad T14s Gen 2"), "ThinkPad T14s")
        self.assertEqual(c.model_line("Dell Latitude 7420"), "Dell Latitude")
        self.assertEqual(c.model_line("ThinkPad X1 Carbon"), "ThinkPad X1 Carbon")

    def test_normalize_name(self):
        self.assertEqual(c.normalize_name("  alex   TECH <alex.tech@example.com>"), "alex tech")


if __name__ == "__main__":
    unittest.main()
