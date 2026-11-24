"""Generate a MOCK workbook with made-up people and tickets for building the Power BI report.

Everything here is fake (AGENTS.md rule 1.3). Output: sample_data/DeMillimanize Requests.mock.xlsx
Run:  python run.py mock
"""

from datetime import datetime
from pathlib import Path

from extract.tables import RUNLOG_COLUMNS, build_tables
from extract.workbook import write_workbook

OUTPUT = Path(__file__).resolve().parent / "DeMillimanize Requests.mock.xlsx"
FAKE_URL = "https://example.invalid/a/tickets"

TECHS = {"alex.tech@example.com": "Alex Tech", "riley.support@example.com": "Riley Support"}
PEOPLE = {
    "jane": ("Jane Example", "jane.example@example.com", "Retirement"),
    "sam": ("Sam Sample", "sam.sample@example.com", "Life"),
    "pat": ("Pat Placeholder", "pat.placeholder@example.com", "CMH Health"),
    "chris": ("Chris Demo", "chris.demo@example.com", "Property & Casualty"),
    "taylor": ("Taylor Test", "taylor.test@example.com", "CMH Health"),
    "jordan": ("Jordan Mock", "jordan.mock@example.com", "Retirement"),
    "casey": ("Casey Fake", "casey.fake@example.com", "Life"),
    "drew": ("Drew Dummy", "drew.dummy@example.com", "Employee Benefits"),
    "robin": ("Robin Sample", "robin.sample@example.com", "CMH Health"),
    "morgan": ("Morgan Manager", "morgan.manager@example.com", "Life"),
    "alex": ("Alex Tech", "alex.tech@example.com", "IT"),
    "riley": ("Riley Support", "riley.support@example.com", "IT"),
}
FORM_ITEM = '"De-Millimanize" Device with Milliman Data'


def person(key):
    name, email, dept = PEOPLE[key]
    return {"name": name, "email": email, "department": dept}


def form_ticket(tid, created, requester, recipient, model, serial, status="Closed", cert=True, notes=(), approvals=()):
    recipient_name = PEOPLE[recipient][0]
    return {
        "id": tid, "type": "Service Request",
        "subject": f"Request for {recipient_name} : {FORM_ITEM}",
        "description_text": "Use this form to track De-Millimanizing Milliman machines.",
        "status": status, "status_code": None,
        "created_at": created, "updated_at": created, "closed_at": created if status == "Closed" else None,
        "sub_category": "Laptop" if "ThinkPad" in model else None,
        "department": PEOPLE[requester][2],
        "requester": person(requester), "requested_for": person(recipient), "recipient": person(recipient),
        "items": [{"name": FORM_ITEM, "stage": "Fulfilled" if status == "Closed" else "Requested", "fields": {
            "pc_serial_number_100001": serial, "pc_make_and_model_100001": model,
            "most_recent_pc_name_100001": f"MOCK-{serial}", "computer_provided_to_100001": recipient_name}}],
        "approvals": list(approvals),
        "notes": [{"private": True, "text": n} for n in notes],
        "attachments": [f"Certificate-MOCK-{serial}-Success-{created[:10]}-10-00-00.pdf"] if cert else [],
        "resolution_note": f"Demillimanized laptop for {recipient_name}" if status == "Closed" else None,
    }


def legacy_ticket(tid, created, requester, subject, status="Closed", approvals=(), notes=()):
    return {
        "id": tid, "type": "Service Request", "subject": subject,
        "description_text": "I would like to keep my old laptop for personal use.",
        "status": status, "status_code": None,
        "created_at": created, "updated_at": created, "closed_at": created if status == "Closed" else None,
        "sub_category": None, "department": PEOPLE[requester][2],
        "requester": person(requester), "requested_for": person(requester), "recipient": None,
        "items": [], "approvals": list(approvals), "notes": [{"private": True, "text": n} for n in notes],
        "attachments": [], "resolution_note": None,
    }


def approval(status, approver, when):
    return {"status": status, "approver": PEOPLE[approver][0], "decided_at": when}


def mock_bundles() -> list[dict]:
    return [
        legacy_ticket(900001, "2024-07-24T09:52:00", "chris", "Demillimanize recent old laptop",
                      approvals=[approval("approved", "morgan", "2024-07-24T15:48:00")]),
        legacy_ticket(900002, "2024-12-02T11:00:00", "taylor", "Can I de-millimanize my old PC?",
                      approvals=[approval("rejected", "morgan", "2024-12-03T09:00:00")]),
        form_ticket(900003, "2025-02-10T10:00:00", "alex", "jane", "ThinkPad X1 Carbon Gen 9", "PF1111AA"),
        form_ticket(900004, "2025-05-20T10:00:00", "riley", "jane", "ThinkPad T14 Gen 2", "PF2222BB"),
        form_ticket(900005, "2025-06-15T10:00:00", "alex", "sam", "Lenovo ThinkPad E14", "MJ3333CC"),
        form_ticket(900006, "2025-08-01T10:00:00", "alex", "alex", "ThinkPad L14", "PF4444DD"),
        form_ticket(900007, "2025-09-12T10:00:00", "riley", "pat", "ThinkCentre M920x", "MJ5555EE", cert=False),
        form_ticket(900008, "2025-11-20T10:00:00", "alex", "robin", "ThinkPad X13", "PF6666FF"),
        form_ticket(900009, "2025-12-01T10:00:00", "riley", "jane", "ThinkPad X1 Carbon Gen 11", "PF7777GG"),
        form_ticket(900010, "2026-01-03T10:00:00", "alex", "robin", "ThinkPad T14s", "PF2222BB"),
        form_ticket(900011, "2026-03-05T10:00:00", "riley", "casey", "ThinkPad X1 Yoga", "PF8888HH",
                    notes=["Supervisor approval was denied, device returned to stock."]),
        form_ticket(900012, "2026-06-18T10:00:00", "alex", "drew", "Latitude 7420", "DL9999II"),
        form_ticket(900013, "2026-10-28T14:50:00", "alex", "jordan", "Lenovo ThinkPad E14", "MJ0000JJ",
                    status="Open", cert=False),
        legacy_ticket(900014, "2026-11-12T14:43:00", "sam", "Question about demillimanized laptops",
                      status="Pending"),
    ]


def mock_runlog() -> list[dict]:
    runs = [("2026-11-17T11:30:00", "Success", ""), ("2026-11-17T18:30:00", "Failed", "MOCK: HTTP 429 for GET /api/v2/tickets"),
            ("2026-11-18T11:30:00", "Success", ""), ("2026-11-18T18:30:00", "Success", "")]
    return [{"Run": i, "Started (UTC)": datetime.fromisoformat(t), "Finished (UTC)": datetime.fromisoformat(t),
             "Mode": "Full" if i == 1 else "Incremental", "Status": s, "Tickets Listed": 100, "Forms Checked": 12,
             "Matched Total": 14, "API Calls": 150, "Message": m,
             "Finished (Local)": datetime.fromisoformat(t)} for i, (t, s, m) in enumerate(runs, start=1)]


def main() -> int:
    technicians = set(TECHS) | {n.lower() for n in TECHS.values()}
    overrides = {900012: {"Outcome": "Denied", "Reason": "MOCK: reviewed with program owner",
                          "Reviewed By": "Morgan Manager", "Reviewed On": datetime(2026, 6, 20)}}
    tables = build_tables(mock_bundles(), technicians, overrides, FAKE_URL)
    tables["RunLog"] = (RUNLOG_COLUMNS, mock_runlog())
    write_workbook(OUTPUT, tables)
    print(f"Mock workbook written: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
