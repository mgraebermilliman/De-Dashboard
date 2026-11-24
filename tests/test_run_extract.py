"""End-to-end extract run against a fake Freshservice client (no network, fake data only)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

from extract import config, run_extract
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
}
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
        if path in RESPONSES:
            return RESPONSES[path]
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
            mock.patch.object(config, "get_api_key", return_value="fake-key"),
            mock.patch.object(run_extract, "FreshserviceClient", FakeClient),
            mock.patch.object(run_extract, "ad_practices",
                              return_value=({"jane.example@example.com": "CMH"}, "1 of 2 people not found in Active Directory.")),
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
        self.assertEqual(row["Department"], "CMH", "Department is the recipient's practice")
        self.assertEqual(row["Resolution Note"], "Demillimanized laptop for Jane Example")
        first_log = self.rows("RunLog")[-1]
        self.assertEqual(first_log["Mode"], "Full")
        self.assertIn("Agent list unavailable", first_log["Message"])
        self.assertIn("not found in Active Directory", first_log["Message"])

        self.assertEqual(run_extract.main([]), 0)
        self.assertEqual(self.rows("RunLog")[-1]["Mode"], "Incremental")

        FakeClient.fail_listing = True
        self.assertEqual(run_extract.main([]), 1)
        last = self.rows("RunLog")[-1]
        self.assertEqual(last["Status"], "Failed")
        self.assertEqual(len(self.rows("Requests")), 1, "previous data must be kept on failure")


if __name__ == "__main__":
    unittest.main()
