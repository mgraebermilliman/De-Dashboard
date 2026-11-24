"""Turn normalized ticket bundles into the workbook tables Power BI reads.

Pure functions only (no API calls), so the same code runs on live data and on mock data.
Table and column names are the data contract with the Power BI model. Don't rename them.
"""

import re
from collections import defaultdict
from datetime import date, datetime

from . import classify as c

REQUESTS_COLUMNS = [
    "Ticket ID", "Ticket URL", "Created Date", "Requester Name", "Requester Email", "Department",
    "Computer Provided To", "Recipient Differs From Requester", "Requested For", "Outcome",
    "Outcome Source", "Outcome Evidence", "Approver", "Decision Date", "Device Type",
    "PC Make and Model", "PC Serial Number", "Most Recent PC Name", "Frequent (Requester)",
    "Requester Request #", "Days Since Previous (Requester)", "Frequent (Recipient)",
    "Recipient Request #", "Days Since Previous (Recipient)", "Same Serial Seen Before",
    "Holiday Season", "Certificate Attached", "Certificate File", "Certificate Missing",
    "Match Source", "Matched Phrase", "Matched Field", "Match Needs Review", "Ticket Type",
    "Status", "Item Stage", "Closed Date", "Subject", "Resolution Note", "Last Updated",
    # Additions to Michael's schema: technician-listed (charity) handling.
    "Requester Is Technician", "Recipient Is Technician",
]
PEOPLE_COLUMNS = [
    "Person", "Email", "Department", "Frequent", "Requests Made", "Requests Made For Others",
    "Times Named As Recipient", "Approved", "Denied", "Pending", "Needs Review", "First Request",
    "Last Request", "Shortest Gap (Days)", "Technician",
]
PERSON_REQUESTS_COLUMNS = ["Person", "Role", "Ticket ID"]
FORM_ANSWERS_COLUMNS = ["Ticket ID", "Field", "Value"]
RUNLOG_COLUMNS = [
    "Run", "Started (UTC)", "Finished (UTC)", "Mode", "Status", "Tickets Listed", "Forms Checked",
    "Matched Total", "API Calls", "Message", "Finished (Local)",
]

_FIELD_SUFFIX = re.compile(r"_\d+$")


def field_label(key: str) -> str:
    """'pc_serial_number_252801' -> 'Pc serial number' (Freshservice appends item-specific suffixes)."""
    text = _FIELD_SUFFIX.sub("", key).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def form_value(items: list[dict], needle: str) -> str | None:
    for item in items:
        for key, value in (item.get("fields") or {}).items():
            if needle in key.lower() and value not in (None, ""):
                return str(value).strip()
    return None


def person_key(person: dict | None) -> str | None:
    if not person:
        return None
    if person.get("email"):
        return person["email"].strip().lower()
    if person.get("id"):
        return f"id:{person['id']}"
    name = c.normalize_name(person.get("name"))
    return f"name:{name}" if name else None


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _to_dt(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


def _with_times(b: dict) -> dict:
    b = {**b, **{k: _to_dt(b.get(k)) for k in ("created_at", "updated_at", "closed_at")}}
    b["approvals"] = [{**a, "decided_at": _to_dt(a.get("decided_at"))} for a in b.get("approvals", [])]
    return b


def _is_technician(person: dict | None, technicians: set[str]) -> bool:
    """technicians holds lower-cased emails, normalized names and 'id:<user id>' entries."""
    if not person:
        return False
    email = (person.get("email") or "").strip().lower()
    return bool((email and email in technicians)
                or (person.get("id") and f"id:{person['id']}" in technicians)
                or c.normalize_name(person.get("name")) in technicians)


def build_tables(
    bundles: list[dict],
    technicians: set[str],
    overrides: dict[int, dict],
    ticket_url_base: str,
    practices: dict[str, str | None] | None = None,
) -> dict[str, tuple[list[str], list[dict]]]:
    """technicians: lower-cased emails, normalized names and 'id:<user id>' of technicians.
    practices: lower-cased email -> practice code from Active Directory."""
    practices = practices or {}
    tickets = []
    for b in map(_with_times, bundles):
        item_names = [i.get("name") or "" for i in b.get("items", [])]
        matched = c.match(b.get("subject"), b.get("description_text"), item_names)
        if matched:
            tickets.append((b, matched))
    tickets.sort(key=lambda t: (t[0].get("created_at") or datetime.min, t[0]["id"]))

    persons: dict[str, dict] = {}
    name_to_key: dict[str, str] = {}

    def register(person: dict | None) -> str | None:
        key = person_key(person)
        if key is None:
            return None
        if key.startswith("name:") and key[5:] in name_to_key:
            key = name_to_key[key[5:]]
        record = persons.setdefault(key, {"name": None, "email": None, "department": None, "id": None})
        for field in ("name", "email", "department"):
            if not record[field] and person.get(field):
                record[field] = person[field].strip()
        record["id"] = record["id"] or person.get("id")
        # Active Directory practice wins over the Freshservice department (often unreadable: HTTP 403).
        practice = practices.get((record["email"] or "").lower())
        if practice:
            record["department"] = practice
        if record["name"]:
            name_to_key.setdefault(c.normalize_name(record["name"]), key)
        return key

    # Register people with email first so name-only mentions can join them.
    for b, _ in tickets:
        for p in (b.get("requester"), b.get("requested_for"), b.get("recipient")):
            if p and p.get("email"):
                register(p)

    rows, links = [], []
    history: dict[tuple[str, str], list[date]] = defaultdict(list)
    seen_serials: set[str] = set()

    for b, (source, phrase, field) in tickets:
        items = b.get("items", [])
        requester = b.get("requester")
        requester_key = register(requester)
        requested_for_key = register(b.get("requested_for"))
        recipient = b.get("recipient")
        if recipient is None and requested_for_key and requested_for_key != requester_key:
            recipient = b.get("requested_for")
        recipient_key = register(recipient)

        requester_tech = _is_technician(requester, technicians)
        recipient_tech = _is_technician(recipient, technicians)
        created = _day(b.get("created_at"))

        def sequence(role: str, key: str | None, excluded: bool):
            if key is None or excluded or created is None:
                return None, None, None
            previous = history[(role, key)]
            gap = (created - previous[-1]).days if previous else None
            previous.append(created)
            return c.yes_no(gap is not None and gap <= c.FREQUENT_WINDOW_DAYS), len(previous), gap

        freq_req, num_req, gap_req = sequence("requester", requester_key, requester_tech)
        freq_rec, num_rec, gap_rec = sequence("recipient", recipient_key, recipient_tech)

        serial = form_value(items, "serial")
        serial_norm = serial.upper().replace(" ", "") if serial else None
        same_serial = None if not serial_norm else serial_norm in seen_serials
        if serial_norm:
            seen_serials.add(serial_norm)

        certificates = [n for n in b.get("attachments", []) if c.is_certificate(n)]
        status = b.get("status")
        status_label = status or (f"Unknown ({b['status_code']})" if b.get("status_code") is not None else None)
        is_form = source in ("Form", "Both")
        closed_texts = [n.get("text") for n in b.get("notes", [])] + [b.get("resolution_note")]
        decision = c.decide_outcome(status, b.get("approvals", []), closed_texts, overrides.get(b["id"]))
        make_model = form_value(items, "make")

        rows.append({
            "Ticket ID": b["id"],
            "Ticket URL": f"{ticket_url_base.rstrip('/')}/{b['id']}",
            "Created Date": created,
            "Requester Name": (requester or {}).get("name"),
            "Requester Email": (requester or {}).get("email"),
            "Department": persons.get(recipient_key or requester_key, {}).get("department") or b.get("department"),
            "Computer Provided To": (b.get("recipient") or {}).get("name") or form_value(items, "provided_to"),
            "Recipient Differs From Requester": None if recipient_key is None else c.yes_no(recipient_key != requester_key),
            "Requested For": (b.get("requested_for") or {}).get("name"),
            **decision,
            "Device Type": c.device_type(make_model, b.get("sub_category")),
            "PC Make and Model": make_model,
            "PC Serial Number": serial,
            "Most Recent PC Name": form_value(items, "pc_name"),
            "Frequent (Requester)": freq_req,
            "Requester Request #": num_req,
            "Days Since Previous (Requester)": gap_req,
            "Frequent (Recipient)": freq_rec,
            "Recipient Request #": num_rec,
            "Days Since Previous (Recipient)": gap_rec,
            "Same Serial Seen Before": c.yes_no(same_serial),
            "Holiday Season": c.yes_no(c.is_holiday_season(created)),
            "Certificate Attached": c.yes_no(bool(certificates)),
            "Certificate File": certificates[0] if certificates else None,
            "Certificate Missing": c.yes_no(is_form and (status or "").lower() == "closed" and not certificates),
            "Match Source": source,
            "Matched Phrase": phrase,
            "Matched Field": field,
            "Match Needs Review": c.yes_no(source == "Phrase"),
            "Ticket Type": b.get("type"),
            "Status": status_label,
            "Item Stage": next((i.get("stage") for i in items if i.get("stage")), None),
            "Closed Date": b.get("closed_at"),
            "Subject": b.get("subject"),
            "Resolution Note": b.get("resolution_note"),
            "Last Updated": b.get("updated_at"),
            "Requester Is Technician": c.yes_no(requester_tech) if requester_key else None,
            "Recipient Is Technician": c.yes_no(recipient_tech) if recipient_key else None,
        })

        roles: dict[str, set[str]] = defaultdict(set)
        if requester_key:
            roles[requester_key].add("Requester")
        if recipient_key:
            roles[recipient_key].add("Recipient")
        for key, role_set in roles.items():
            role = "Both" if len(role_set) == 2 else next(iter(role_set))
            links.append({"key": key, "Role": role, "Ticket ID": b["id"]})

    display = _display_names(persons)
    people = _people_rows(persons, display, rows, links, technicians)
    person_requests = [{"Person": display[l["key"]], "Role": l["Role"], "Ticket ID": l["Ticket ID"]} for l in links]
    form_answers = [
        {"Ticket ID": b["id"], "Field": field_label(key), "Value": str(value)}
        for b, _ in tickets
        for item in b.get("items", [])
        for key, value in (item.get("fields") or {}).items()
        if value not in (None, "")
    ]
    return {
        "Requests": (REQUESTS_COLUMNS, rows),
        "People": (PEOPLE_COLUMNS, people),
        "PersonRequests": (PERSON_REQUESTS_COLUMNS, person_requests),
        "FormAnswers": (FORM_ANSWERS_COLUMNS, form_answers),
    }


def _display_names(persons: dict[str, dict]) -> dict[str, str]:
    """Person names must be unique because Person is the relationship key in Power BI."""
    counts = defaultdict(int)
    for record in persons.values():
        counts[c.normalize_name(record["name"]) or None] += 1
    display = {}
    for key, record in persons.items():
        name = record["name"] or record["email"] or key
        if counts[c.normalize_name(record["name"]) or None] > 1:
            name = f"{name} ({record['email'] or 'no email'})"
        display[key] = name
    return display


def _people_rows(persons, display, rows, links, technicians) -> list[dict]:
    by_ticket = {r["Ticket ID"]: r for r in rows}
    people = []
    for key, record in persons.items():
        mine = [l for l in links if l["key"] == key]
        if not mine:
            continue
        tickets = [by_ticket[l["Ticket ID"]] for l in mine]
        as_requester = [t for l, t in zip(mine, tickets) if l["Role"] in ("Requester", "Both")]
        as_recipient = [t for l, t in zip(mine, tickets) if l["Role"] in ("Recipient", "Both")]
        # Outcome counts cover requests where this person is the one receiving the device.
        own = as_recipient + [t for t in as_requester if t["Recipient Differs From Requester"] != "Yes"
                              and t not in as_recipient]
        gaps = [t["Days Since Previous (Requester)"] for t in as_requester] + \
               [t["Days Since Previous (Recipient)"] for t in as_recipient]
        # Also compare across roles (e.g. asked once for themselves, then named on a form).
        own_dates = sorted(t["Created Date"] for t in own
                           if t["Created Date"] and "Yes" not in (t["Requester Is Technician"], t["Recipient Is Technician"]))
        gaps += [(b - a).days for a, b in zip(own_dates, own_dates[1:])]
        gaps = [g for g in gaps if g is not None]
        flags = [t["Frequent (Requester)"] for t in as_requester] + [t["Frequent (Recipient)"] for t in as_recipient]
        flags += ["Yes" for g in gaps if g <= c.FREQUENT_WINDOW_DAYS]
        dates = [t["Created Date"] for t in tickets if t["Created Date"]]
        people.append({
            "Person": display[key],
            "Email": record["email"],
            "Department": record["department"],
            "Frequent": c.yes_no("Yes" in flags),
            "Requests Made": len(as_requester),
            "Requests Made For Others": sum(1 for t in as_requester if t["Recipient Differs From Requester"] == "Yes"),
            "Times Named As Recipient": len(as_recipient),
            **{o: sum(1 for t in own if t["Outcome"] == o) for o in c.OUTCOMES},
            "First Request": min(dates) if dates else None,
            "Last Request": max(dates) if dates else None,
            "Shortest Gap (Days)": min(gaps) if gaps else None,
            "Technician": c.yes_no(_is_technician(record, technicians)),
        })
    people.sort(key=lambda p: p["Person"].lower())
    return people
