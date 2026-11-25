"""End-to-end extract run against a fake Freshservice client (no network, fake data only)."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

from extract import archive, config, run_extract
from extract.freshservice import FreshserviceError

FORM_ITEM = '"De-Millimanize" Device with Milliman Data'
# Shapes follow the live probe of 2026-11-20: recipient is a user ID, the certificate is on the form
# item, /agents is 403 and /requesters/{id} is 404 for technicians. All values are fake.
RESPONSES = {
    "ticket_form_fields": {"ticket_fields": [{"name": "status", "choices": [
        {"id": 2, "value": "Open"}, {"id": 5, "value": "Closed"}]}]},
    "tickets/101": {"ticket": {
        "id": 101, "type": "Service Request", "subject": f"Request for Jane Example : {FORM_ITEM}",
        "status": 5, "created_at": "2026-01-02T15:00:00Z", "updated_at": "2026-01-03T15:00:00Z",
        "stats": {"closed_at": "2026-01-03T15:00:00Z"}, "requester_id": 1, "requested_for_id": 2,
        "responder_id": 1, "department_id": 10, "approval_status_name": "Not Requested",
        "requester": {"id": 1, "name": "Alex Tech", "email": "alex.tech@example.com"},
        "requested_for": {"id": 2, "name": "Jane Example", "email": "jane.example@example.com"},
        "attachments": [], "custom_fields": {}, "resolution_notes": "Demillimanized laptop for Jane Example"}},
    "tickets/101/requested_items": {"requested_items": [{"service_item_name": FORM_ITEM, "stage": 1, "custom_fields": {
        "computer_provided_to": 2, "pc_serial_number": "PF1", "pc_make_and_model": "ThinkPad T14",
        "most_recent_pc_name": "MOCK-PC1"},
        "attachments": [{"name": "Certificate-MOCK-PF1-Success-2026-01-02-10-00-00.pdf"}]}]},
    "tickets/101/approvals": {"approvals": []},
    # The recipient's own Freshservice record carries her practice; the technician's can't be read (403).
    "requesters/2": {"requester": {"id": 2, "first_name": "Jane", "last_name": "Example",
                                   "primary_email": "jane.example@example.com", "department_ids": [14000218908]}},
    # An archived free-text request. It is only reachable through the archived list and by its number.
    "tickets/201": {"ticket": {
        "id": 201, "type": "Incident", "subject": "Keep company laptop", "archived": True,
        "description_text": "Can I keep my laptop for personal use after the refresh?",
        "status": 5, "created_at": "2023-09-02T15:00:00Z", "updated_at": "2023-09-03T15:00:00Z",
        "requester_id": 2, "requester": {"id": 2, "name": "Jane Example", "email": "jane.example@example.com"},
        "attachments": [], "custom_fields": {}}},
}
ARCHIVED_PAGES = {1: [{"id": 201, "subject": "Keep company laptop"}, {"id": 202, "subject": "VPN issue"}]}
LISTS = {
    "tickets": [{"id": 101, "subject": f"Request for Jane Example : {FORM_ITEM}"},
                {"id": 102, "subject": "Printer is broken"}],
    "tickets/101/conversations": [{"private": True, "body_text": "Laptop wiped."}],
}
FORBIDDEN = ("agents", "requesters", "departments")  # all HTTP 403 on the real key (probe, 2026-11-20)


class FakeClient:
    fail_listing = False

    def __init__(self, *args, **kwargs):
        self.request_count = 0

    def get(self, path, params=None):
        self.request_count += 1
        if path == "tickets" and (params or {}).get("filter") == "archived":
            return {"tickets": ARCHIVED_PAGES.get(params["page"], [])}
        if path in RESPONSES:
            return RESPONSES[path]
        if path == "requesters/1":  # a technician is an agent, not a requester
            raise FreshserviceError("HTTP 404 for GET /api/v2/requesters/1")
        if path.startswith(FORBIDDEN):
            raise FreshserviceError(f"HTTP 403 for GET /api/v2/{path}")
        raise FreshserviceError(f"HTTP 404 for GET /api/v2/{path}")

    def get_all(self, path, key, params=None):
        self.request_count += 1
        if path == "tickets" and FakeClient.fail_listing:
            raise FreshserviceError("HTTP 429 for GET /api/v2/tickets")
        if path.startswith(FORBIDDEN):
            raise FreshserviceError(f"HTTP 403 for GET /api/v2/{path}")
        yield from LISTS.get(path, [])


class ExtractRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(config, "STATE_DIR", tmp / "state"),
            mock.patch.object(config, "WORKBOOK_PATH", tmp / "book.xlsx"),
            mock.patch.object(config, "OVERRIDES_PATH", tmp / "overrides.csv"),
            mock.patch.object(config, "CONFIRMATIONS_PATH", tmp / "confirmations.csv"),
            mock.patch.object(config, "ARCHIVE_WORKERS", 2),
            mock.patch.object(config, "get_api_key", return_value="fake-key"),
            mock.patch.object(run_extract, "FreshserviceClient", FakeClient),
            mock.patch.object(archive, "FreshserviceClient", FakeClient),
        ]
        for p in self.patches:
            p.start()
        FakeClient.fail_listing = False

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def rows(self, sheet):
        ws = load_workbook(config.WORKBOOK_PATH)[sheet]
        header = [c.value for c in ws[1]]
        return [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]

    def test_full_then_incremental_then_failure(self):
        self.assertEqual(run_extract.main([]), 0)
        requests = self.rows("Requests")
        self.assertEqual(len(requests), 1)
        row = requests[0]
        self.assertEqual(row["Computer Provided To"], "Jane Example")
        self.assertEqual(row["Requester Is Technician"], "Yes")
        self.assertEqual(row["Recipient Differs From Requester"], "Yes")
        self.assertEqual(row["Outcome"], "Approved")
        self.assertEqual(row["Certificate Attached"], "Yes")
        self.assertEqual(row["Device Type"], "Laptop")
        people = {p["Person"]: p for p in self.rows("People")}
        self.assertEqual(people["Jane Example"]["Department"], "CMH")
        self.assertEqual(people["Alex Tech"]["Technician"], "Yes")
        self.assertEqual(row["Department"], "CMH", "Department is the recipient's practice from her own account")
        self.assertEqual(row["Resolution Note"], "Demillimanized laptop for Jane Example")
        first_log = self.rows("RunLog")[-1]
        self.assertEqual(first_log["Mode"], "Full")
        self.assertIn("Agent list unavailable", first_log["Message"])

        self.assertEqual(run_extract.main([]), 0)
        self.assertEqual(self.rows("RunLog")[-1]["Mode"], "Incremental")

        FakeClient.fail_listing = True
        self.assertEqual(run_extract.main([]), 1)
        last = self.rows("RunLog")[-1]
        self.assertEqual(last["Status"], "Failed")
        self.assertEqual(len(self.rows("Requests")), 1, "previous data must be kept on failure")

    def test_archived_tickets_are_scanned_once_and_joined(self):
        self.assertEqual(run_extract.main([]), 0)
        self.assertIn("haven't been scanned", self.rows("RunLog")[-1]["Message"])

        self.assertEqual(archive.main([]), 0)
        state = run_extract._load_json("archive_scan.json", {})
        self.assertTrue(state["complete"])
        self.assertEqual(state["next_page"], 1, "the last, partly filled page is read again next time")
        self.assertEqual(list(run_extract._load_json("archive_tickets.json", {})), ["201"])

        self.assertEqual(run_extract.main(["--full"]), 0)
        requests = {r["Ticket ID"]: r for r in self.rows("Requests")}
        self.assertEqual(set(requests), {101, 201})
        self.assertEqual((requests[201]["Archived"], requests[201]["Match Confidence"]), ("Yes", "High"))
        self.assertNotIn("scan", self.rows("RunLog")[-1]["Message"])

    def test_new_archive_scan_starts_at_the_since_date(self):
        # 40 pages, one day per page from 2023-12-01. 2024-01-01 is first reached on page 32.
        class Pages:
            calls = 0

            def archived_page(self, page):
                Pages.calls += 1
                if page > 40:
                    return []
                day = date(2023, 12, 1) + timedelta(days=page - 1)
                return [{"id": page, "created_at": f"{day.isoformat()}T09:00:00-06:00"}]

        self.assertEqual(archive.first_page_since(Pages(), date(2024, 1, 1)), 32)
        self.assertLess(Pages.calls, 15, "found by halving, not by reading every page")
        self.assertEqual(archive.first_page_since(Pages(), date(2020, 1, 1)), 1)
        self.assertEqual(archive.first_page_since(Pages(), date(2030, 1, 1)), 41, "nothing that new: start past the end")

    def test_requests_before_the_start_date_are_left_out_of_the_workbook(self):
        self.assertEqual(archive.main([]), 0)
        with mock.patch.object(config, "DATA_START", "2024-01-01"):
            self.assertEqual(run_extract.main(["--full"]), 0)
        self.assertEqual([r["Ticket ID"] for r in self.rows("Requests")], [101], "the 2023 archived ticket is dropped")

    def test_only_names_no_ticket_record_explains_are_looked_up(self):
        form = "Request for {} : \"De-Millimanize\" Device with Milliman Data"
        bundles = {
            "1": {"id": 1, "subject": form.format("Jane Example"), "requester": {"name": "Jane Example"},
                  "requested_for": {"name": "Jane Example"}, "resolution_note": "Done."},
            "2": {"id": 2, "subject": form.format("Alex Tech"), "requester": {"name": "Alex Tech"},
                  "requested_for": {"name": "Alex Tech"}, "resolution_note": "De-Millimanized for Pat Placeholder"},
            "3": {"id": 3, "subject": form.format("Sam Sample"), "requester": {"name": "Alex Tech"},
                  "requested_for": {"name": "Alex Tech"}, "resolution_note": "Done."},
            "4": {"id": 4, "subject": form.format("Pat Placeholder"), "requester": {"name": "Alex Tech"},
                  "requested_for": {"name": "Alex Tech"}, "recipient": {"name": "Pat Placeholder"},
                  "resolution_note": "De-Millimanized for Someone Else"},
        }
        notes, subjects = run_extract.unmatched_names(bundles)
        self.assertEqual(notes, {2: "Pat Placeholder"})
        self.assertEqual(subjects, {3: "Sam Sample"}, "1 is the requester, 4 already has a recipient")

    def test_full_run_keeps_a_matched_ticket_that_was_archived_since(self):
        self.assertEqual(run_extract.main([]), 0)
        with mock.patch.dict(LISTS, {"tickets": [{"id": 102, "subject": "Printer is broken"}]}):
            self.assertEqual(run_extract.main(["--full"]), 0)
        self.assertEqual([r["Ticket ID"] for r in self.rows("Requests")], [101])


if __name__ == "__main__":
    unittest.main()
