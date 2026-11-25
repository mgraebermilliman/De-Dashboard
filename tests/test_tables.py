"""Tests for the workbook tables, using the fake-data generator (AGENTS.md rule 1.3)."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from extract.run_extract import load_confirmations, load_overrides
from extract.tables import REQUESTS_COLUMNS, build_tables, field_label
from extract.workbook import write_workbook
from sample_data import make_mock_workbook as mock

TECHS = set(mock.TECHS) | {n.lower() for n in mock.TECHS.values()}


def build(overrides=None, confirmations=None):
    tables = build_tables(mock.mock_bundles(), TECHS, overrides or {}, mock.FAKE_URL, confirmations=confirmations)
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
        self.assertEqual(row["Frequent (Recipient)"], "No", "technicians are counted as recipients too")

    def test_same_serial_and_holiday(self):
        self.assertEqual(self.req[900010]["Same Serial Seen Before"], "Yes")
        self.assertEqual(self.req[900010]["Holiday Season"], "Yes")
        self.assertIsNone(self.req[900001]["Same Serial Seen Before"])

    def test_certificate_missing_only_for_closed_forms(self):
        self.assertEqual(self.req[900007]["Certificate Missing"], "Yes")
        self.assertEqual(self.req[900013]["Certificate Missing"], "No")
        self.assertEqual(self.req[900001]["Certificate Missing"], "No")

    def test_phrase_tickets_are_high_or_held_back(self):
        self.assertEqual(self.req[900001]["Match Source"], "Phrase")
        self.assertEqual(self.req[900001]["Match Confidence"], "High")
        self.assertEqual(self.req[900003]["Match Source"], "Both")
        self.assertNotIn(900015, self.req)
        waiting = self.t["Unconfirmed"][900015]
        self.assertEqual(waiting["Confidence"], "Medium")
        self.assertIn("de-millimanized", waiting["Excerpt"])

    def test_confirmation_is_only_needed_once(self):
        yes = build(confirmations={900015: True})
        self.assertEqual(yes["Requests"][900015]["Match Confidence"], "Confirmed")
        self.assertEqual(yes["Unconfirmed"], {})
        no = build(confirmations={900015: False, 900001: False})
        self.assertNotIn(900015, no["Requests"])
        self.assertNotIn(900001, no["Requests"], "a person's No also removes a ticket the rules were sure about")
        self.assertEqual(no["Unconfirmed"], {})

    def test_model_chart_groups(self):
        groups = {r["Model Group"] for r in self.req.values()}
        self.assertIn("Not identified", groups)
        self.assertLessEqual(groups, {"Not identified", "Other ThinkPad", "Other ThinkCentre", "Dell"})

    def test_outcomes(self):
        self.assertEqual(self.req[900001]["Outcome"], "Approved")
        self.assertEqual(self.req[900002]["Outcome"], "Denied")
        self.assertEqual(self.req[900011]["Outcome"], "Needs Review")
        self.assertEqual(self.req[900013]["Outcome"], "Pending")

    def test_override_applies(self):
        req = build({900012: {"Outcome": "Denied", "Reason": "x"}})["Requests"]
        self.assertEqual(req[900012]["Outcome Source"], "Manual Override")

    def test_anyone_named_as_recipient_twice_within_120_days_is_frequent(self):
        def form(tid, day, recipient, requester="alex"):
            return mock.form_ticket(tid, f"{day}T10:00:00", requester, recipient, "ThinkPad T14s", f"PF{tid}")

        bundles = [
            form(900030, "2025-07-13", "alex", "alex"), form(900031, "2025-08-10", "alex", "alex"),  # a technician: listed too
            form(900032, "2025-03-01", "sam"), form(900033, "2025-09-01", "sam"),                    # 184 days apart
            form(900034, "2025-03-01", "pat"), form(900035, "2025-03-01", "pat"),                    # two devices, one day
            # A free-text request, then the form for her a week later: she is the recipient once.
            mock.legacy_ticket(900036, "2025-03-01T09:00:00", "taylor", "Demillimanize old laptop"),
            form(900037, "2025-03-07", "taylor"),
            # Someone who files forms for others is not frequent for that.
            form(900038, "2025-03-01", "robin", requester="morgan"), form(900039, "2025-03-20", "casey", requester="morgan"),
        ]
        tables = build_tables(bundles, TECHS, {}, mock.FAKE_URL)
        rows = {r["Ticket ID"]: r for r in tables["Requests"][1]}
        people = {p["Person"]: p for p in tables["People"][1]}

        def seen(name):
            return people[name]["Frequent"], people[name]["Shortest Gap (Days)"]

        self.assertEqual(seen("Alex Tech"), ("Yes", 28))
        self.assertEqual(people["Alex Tech"]["Technician"], "Yes")
        self.assertEqual(seen("Sam Sample"), ("No", 184))
        self.assertEqual(seen("Pat Placeholder"), ("Yes", 0))
        self.assertEqual(seen("Taylor Test"), ("No", None))
        self.assertEqual(people["Morgan Manager"]["Frequent"], "No")
        self.assertEqual(people["Morgan Manager"]["Requests Made For Others"], 2)
        self.assertEqual((seen("Robin Sample")[0], seen("Casey Fake")[0]), ("No", "No"))
        # Row by row, the recipient columns follow the same rule.
        self.assertEqual([rows[t]["Frequent (Recipient)"] for t in (900030, 900031)], ["No", "Yes"])
        self.assertEqual(rows[900031]["Days Since Previous (Recipient)"], 28)
        self.assertEqual([rows[t]["Recipient Request #"] for t in (900032, 900033)], [1, 2])

    def test_tickets_before_the_start_date_are_left_out(self):
        tables = build_tables(mock.mock_bundles(), TECHS, {}, mock.FAKE_URL, earliest=date(2025, 6, 1))
        ids = {r["Ticket ID"] for r in tables["Requests"][1]}
        self.assertNotIn(900003, ids)  # 2025-02-10
        self.assertIn(900005, ids)     # 2025-06-15
        self.assertTrue(all(r["Created Date"] >= date(2025, 6, 1) for r in tables["Requests"][1]))
        # People and links only cover the tickets that are left.
        self.assertEqual({l["Ticket ID"] for l in tables["PersonRequests"][1]} - ids, set())
        everything = build_tables(mock.mock_bundles(), TECHS, {}, mock.FAKE_URL)
        self.assertGreater(len(everything["Requests"][1]), len(tables["Requests"][1]))

    def test_older_forms_name_the_recipient_in_the_subject(self):
        # Before December 2025 the form has no recipient field. The subject, "Request for <Name> :", names the
        # recipient. A technician who files the form without changing it is named there (technician-listed).
        def old_form(tid, note, requester="alex", subject_for=None):
            b = mock.form_ticket(tid, "2024-03-01T10:00:00", requester, requester, "ThinkPad T490s", f"PF{tid}")
            b.update(recipient=None, resolution_note=note)
            if subject_for:
                b["subject"] = f'Request for {subject_for} : {mock.FORM_ITEM}'
            for item in b["items"]:
                item["fields"]["computer_provided_to_100001"] = None
            return b

        jane = {"name": "Jane Example", "email": "jane.example@example.com", "department": "CMH"}
        pat = {"name": "Pat Placeholder", "email": "pat.placeholder@example.com", "department": "CMH Health"}
        conflict = mock.form_ticket(900026, "2024-03-02T10:00:00", "alex", "jane", "ThinkPad T14s", "PF900026")
        conflict["subject"] = f"Request for Alex Tech : {mock.FORM_ITEM}"
        bundles = [
            old_form(900020, "De-Millimanized for Jane Example"),     # note names one employee: beats the technician
            old_form(900021, "De-Millimanized for Good Cause"),       # a bare name in the note doesn't
            old_form(900022, "Done."),
            old_form(900023, "Done.", subject_for="Pat Placeholder"),  # subject names someone AD found
            old_form(900024, "Done.", subject_for="Nobody Known"),     # subject names someone nobody found
            conflict,                                                  # the form field beats the subject
        ]
        tables = build_tables(bundles, TECHS, {}, mock.FAKE_URL, note_recipients={900020: jane},
                              subject_recipients={900023: pat})
        rows = {r["Ticket ID"]: r for r in tables["Requests"][1]}
        people = {p["Person"] for p in tables["People"][1]}

        def check(tid, to, source, tech):
            row = rows[tid]
            self.assertEqual((row["Computer Provided To"], row["Recipient Source"], row["Recipient Is Technician"]),
                             (to, source, tech), tid)

        check(900020, "Jane Example", "Resolution note", "No")
        self.assertEqual(rows[900020]["Department"], "CMH")
        check(900021, "Alex Tech", "Subject", "Yes")
        check(900022, "Alex Tech", "Subject", "Yes")
        self.assertEqual(rows[900022]["Department"], "IT", "the technician's own practice, as for live technician-listed forms")
        check(900023, "Pat Placeholder", "Subject", "No")
        self.assertEqual(rows[900023]["Department"], "CMH Health")
        self.assertEqual((rows[900024]["Computer Provided To"], rows[900024]["Recipient Source"]),
                         ("Nobody Known", "Subject (name only)"))
        self.assertIsNone(rows[900024]["Recipient Is Technician"])
        self.assertEqual(rows[900024]["Department"], "Not recorded")
        check(900026, "Jane Example", "Form", "No")
        self.assertIn("Pat Placeholder", people)
        self.assertNotIn("Nobody Known", people)


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

    def test_confirmation_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "confirm.csv"
            self.assertEqual(load_confirmations(path), ({}, []))
            path.write_text("Ticket ID,Is De-Millimanize,Reviewed By,Reviewed On,Note\n"
                            "123,yes,Reviewer,2026-01-02,\n124,No,,,\n125,maybe,,,\n", encoding="utf-8")
            confirmations, problems = load_confirmations(path)
            self.assertEqual(confirmations, {123: True, 124: False})
            self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
