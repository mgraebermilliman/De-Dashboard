"""Tests for the workbook tables, using the fake-data generator (AGENTS.md rule 1.3)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from extract.run_extract import load_overrides
from extract.tables import REQUESTS_COLUMNS, build_tables, field_label
from extract.workbook import write_workbook
from sample_data import make_mock_workbook as mock

TECHS = set(mock.TECHS) | {n.lower() for n in mock.TECHS.values()}


def build(overrides=None):
    tables = build_tables(mock.mock_bundles(), TECHS, overrides or {}, mock.FAKE_URL)
    return {name: {r.get("Ticket ID", r.get("Person")): r for r in rows} if name != "PersonRequests" else rows
            for name, (_, rows) in tables.items()}


class RequestsTableTests(unittest.TestCase):
    def setUp(self):
        self.t = build()
        self.req = self.t["Requests"]

    def test_every_ticket_has_every_column(self):
        for row in self.req.values():
            self.assertEqual(list(row), REQUESTS_COLUMNS)

    def test_recipient_frequency_within_120_days(self):
        self.assertEqual(self.req[900004]["Frequent (Recipient)"], "Yes")
        self.assertEqual(self.req[900004]["Days Since Previous (Recipient)"], 99)
        self.assertEqual(self.req[900009]["Frequent (Recipient)"], "No")
        self.assertEqual(self.req[900009]["Recipient Request #"], 3)

    def test_technician_requester_not_counted(self):
        self.assertIsNone(self.req[900003]["Frequent (Requester)"])
        self.assertEqual(self.req[900003]["Requester Is Technician"], "Yes")

    def test_technician_listed_charity_excluded(self):
        row = self.req[900006]
        self.assertEqual(row["Recipient Is Technician"], "Yes")
        self.assertIsNone(row["Frequent (Recipient)"])

    def test_same_serial_and_holiday(self):
        self.assertEqual(self.req[900010]["Same Serial Seen Before"], "Yes")
        self.assertEqual(self.req[900010]["Holiday Season"], "Yes")
        self.assertIsNone(self.req[900001]["Same Serial Seen Before"])

    def test_certificate_missing_only_for_closed_forms(self):
        self.assertEqual(self.req[900007]["Certificate Missing"], "Yes")
        self.assertEqual(self.req[900013]["Certificate Missing"], "No")
        self.assertEqual(self.req[900001]["Certificate Missing"], "No")

    def test_phrase_only_needs_review(self):
        self.assertEqual(self.req[900001]["Match Source"], "Phrase")
        self.assertEqual(self.req[900001]["Match Needs Review"], "Yes")
        self.assertEqual(self.req[900003]["Match Source"], "Both")

    def test_outcomes(self):
        self.assertEqual(self.req[900001]["Outcome"], "Approved")
        self.assertEqual(self.req[900002]["Outcome"], "Denied")
        self.assertEqual(self.req[900011]["Outcome"], "Needs Review")
        self.assertEqual(self.req[900013]["Outcome"], "Pending")

    def test_override_applies(self):
        req = build({900012: {"Outcome": "Denied", "Reason": "x"}})["Requests"]
        self.assertEqual(req[900012]["Outcome Source"], "Manual Override")


class PeopleTableTests(unittest.TestCase):
    def setUp(self):
        self.t = build()

    def test_search_finds_person_as_recipient(self):
        jane = [l for l in self.t["PersonRequests"] if l["Person"] == "Jane Example"]
        self.assertEqual({l["Ticket ID"] for l in jane}, {900003, 900004, 900009})
        self.assertTrue(all(l["Role"] == "Recipient" for l in jane))

    def test_people_summary(self):
        jane = self.t["People"]["Jane Example"]
        self.assertEqual(jane["Frequent"], "Yes")
        self.assertEqual(jane["Times Named As Recipient"], 3)
        self.assertEqual(jane["Approved"], 3)
        self.assertEqual(jane["Shortest Gap (Days)"], 99)

    def test_technician_filing_for_others(self):
        alex = self.t["People"]["Alex Tech"]
        self.assertEqual(alex["Technician"], "Yes")
        self.assertGreater(alex["Requests Made For Others"], 0)
        self.assertEqual(alex["Frequent"], "No")

    def test_bridge_people_match_people_table(self):
        people = set(self.t["People"])
        self.assertTrue(all(l["Person"] in people for l in self.t["PersonRequests"]))


class WorkbookTests(unittest.TestCase):
    def test_tables_and_formula_injection(self):
        tables = {"Requests": (["Ticket ID", "Subject", "Created Date"],
                               [{"Ticket ID": 1, "Subject": "=HYPERLINK(\"x\")", "Created Date": datetime(2026, 1, 2)}]),
                  "Empty": (["A", "B"], [])}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.xlsx"
            write_workbook(path, tables)
            wb = load_workbook(path)
            self.assertEqual(list(wb["Requests"].tables), ["Requests"])
            self.assertEqual(list(wb["Empty"].tables), ["Empty"])
            cell = wb["Requests"]["B2"]
            self.assertEqual(cell.data_type, "s")

    def test_field_label_strips_suffix(self):
        self.assertEqual(field_label("pc_serial_number_252801"), "Pc serial number")


class OverrideFileTests(unittest.TestCase):
    def test_valid_and_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "overrides.csv"
            path.write_text("Ticket ID,Outcome,Reason,Reviewed By,Reviewed On\n"
                            "123,denied,Checked,Reviewer,2026-01-02\nabc,Approved,,,\n", encoding="utf-8")
            overrides, problems = load_overrides(path)
            self.assertEqual(overrides[123]["Outcome"], "Denied")
            self.assertEqual(len(problems), 1)

    def test_template_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "overrides.csv"
            self.assertEqual(load_overrides(path), ({}, []))
            self.assertTrue(path.read_text(encoding="utf-8").startswith("Ticket ID,Outcome"))


if __name__ == "__main__":
    unittest.main()
