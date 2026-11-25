"""Turn normalized ticket bundles into the workbook tables Power BI reads.

Pure functions only (no API calls), so the same code runs on live data and on mock data.
Table and column names are the data contract with the Power BI model. Don't rename them.
"""

import re
from collections import Counter, defaultdict
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
    # Details read from the Certificate of Destruction PDF (extract/cod.py).
    "COD Erase Date", "COD Erase Method", "COD Erase Result", "COD Erase Errors", "COD Motherboard",
    "COD Processor", "COD Memory", "COD Drive Size", "COD OS", "COD BIOS", "COD Device Serial",
    "COD Serial Matches Ticket",
    # Cleaned model names (extract/classify.py model_name) for the dashboard's model chart and filter.
    "Model", "Model Line", "Model Source", "Model Group",
    # High (form or strong wording) or Confirmed (a person confirmed it in match_confirmations.csv).
    "Match Confidence", "Archived",
    # Where the recipient came from: Form, Requested for, Subject, Subject (name only), Resolution note,
    # Resolution note (name only), or blank.
    "Recipient Source",
]
# Tickets the wording rules aren't sure about. They stay out of Requests until a person confirms them.
UNCONFIRMED_COLUMNS = ["Ticket ID", "Ticket URL", "Created Date", "Requester Name", "Subject", "Confidence",
                       "Evidence", "Excerpt", "Resolution Note", "Archived"]
MODEL_LINE_MIN_REQUESTS = 10  # a model line with fewer requests joins its family in the model chart
PEOPLE_COLUMNS = [
    "Person", "Email", "Department", "Frequent", "Requests Made", "Requests Made For Others",
    "Times Named As Recipient", "Approved", "Denied", "Pending", "Needs Review", "First Request",
    "Last Request", "Shortest Gap (Days)", "Technician", "Last Received",
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


_MODEL_NAMED = ("Ticket", "PC name", "Certificate (same machine type)")


def _fill_models(rows: list[dict]) -> None:
    """Complete Model, Model Line, Model Source and Model Group for every row.

    In order: the model typed on the form; the model the old PC name spells out ('MILWI-T15-JF' is a T15), on
    the form or in the certificate's file name; the model other tickets with the same Lenovo machine type have,
    when they all agree. Otherwise the machine type or "Not recorded" is shown, never a guess.
    """
    for r in rows:
        if r["Model"]:
            r["Model Source"] = "Ticket"
            continue
        found = c.model_from_pc_name(r["Most Recent PC Name"]) or \
            c.model_from_pc_name(c.certificate_pc_name(r["Certificate File"]))
        if found:
            r["Model"], r["Model Source"] = found, "PC name"
    lines_by_type: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        key = c.machine_type(r["COD Motherboard"]) or c.machine_type(r["PC Make and Model"])
        if key and r["Model"]:
            lines_by_type[key].add(c.model_line(r["Model"]))
    for r in rows:
        if r["Model"]:
            continue
        key = c.machine_type(r["COD Motherboard"]) or c.machine_type(r["PC Make and Model"])
        if key and len(lines_by_type[key]) == 1:
            r["Model"], r["Model Source"] = next(iter(lines_by_type[key])), "Certificate (same machine type)"
        elif key:
            r["Model"], r["Model Source"] = f"Lenovo machine type {key}", "Machine type only"
        else:
            r["Model"], r["Model Source"] = "Not recorded", "Not recorded"
    for r in rows:
        r["Model Line"] = c.model_line(r["Model"])
        if r["Device Type"] == "Unknown" and r["Model Source"] in _MODEL_NAMED:
            r["Device Type"] = c.device_type(r["Model"], None)
    # The model chart stays readable: a model line with enough requests is shown by name, a rarer one joins its
    # family ("Other ThinkPad"), and a ticket with no model name is "Not identified".
    count = Counter(r["Model Line"] for r in rows if r["Model Source"] in _MODEL_NAMED)
    for r in rows:
        if r["Model Source"] not in _MODEL_NAMED:
            r["Model Group"] = "Not identified"
        elif count[r["Model Line"]] >= MODEL_LINE_MIN_REQUESTS:
            r["Model Group"] = r["Model Line"]
        else:
            r["Model Group"] = c.model_family(r["Model Line"])


def cod_columns(details: dict | None, ticket_serial: str | None) -> dict:
    """COD columns for one ticket; all blank when no certificate could be read."""
    details = details or {}
    row = {name: details.get(name) for name in REQUESTS_COLUMNS if name.startswith("COD ")}
    erased = details.get("COD Erase Date")
    row["COD Erase Date"] = date.fromisoformat(erased) if erased else None
    device_serial = details.get("COD Device Serial")
    if ticket_serial and device_serial:
        same = ticket_serial.replace(" ", "").upper() == device_serial.replace(" ", "").upper()
        row["COD Serial Matches Ticket"] = c.yes_no(same)
    else:
        row["COD Serial Matches Ticket"] = None
    return row


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
    confirmations: dict[int, bool] | None = None,
    note_recipients: dict[int, dict] | None = None,
    subject_recipients: dict[int, dict] | None = None,
    earliest: date | None = None,
) -> dict[str, tuple[list[str], list[dict]]]:
    """technicians: lower-cased emails, normalized names and 'id:<user id>' of technicians.
    confirmations: ticket id -> True (is a De-Millimanize request) or False (is not), decided by a person.
    note_recipients: ticket id -> the employee (name, email, department) that Active Directory found for the
    name in the ticket's resolution note. Used only when the ticket has no other recipient.
    subject_recipients: the same for the name in the ticket's subject, when that name is neither the requester nor
    the requested-for person.
    earliest: tickets created before this date are left out of every table."""
    confirmations = confirmations or {}
    note_recipients = note_recipients or {}
    subject_recipients = subject_recipients or {}
    tickets, unconfirmed = [], []
    for b in map(_with_times, bundles):
        if earliest and (_day(b.get("created_at")) or date.max) < earliest:
            continue
        item_names = [i.get("name") or "" for i in b.get("items", [])]
        matched = c.assess(b.get("subject"), b.get("description_text"), b.get("resolution_note"), item_names)
        confirmed = confirmations.get(b["id"])
        if not matched or confirmed is False:
            continue
        if confirmed:
            matched["Confidence"] = c.CONFIRMED
        if matched["Confidence"] in (c.HIGH, c.CONFIRMED):
            tickets.append((b, matched))
        else:
            unconfirmed.append({
                "Ticket ID": b["id"], "Ticket URL": f"{ticket_url_base.rstrip('/')}/{b['id']}",
                "Created Date": _day(b.get("created_at")), "Requester Name": (b.get("requester") or {}).get("name"),
                "Subject": b.get("subject"), "Confidence": matched["Confidence"], "Evidence": matched["Evidence"],
                "Excerpt": c.excerpt(b.get("description_text")),
                "Resolution Note": b.get("resolution_note"), "Archived": c.yes_no(bool(b.get("archived"))),
            })
    tickets.sort(key=lambda t: (t[0].get("created_at") or datetime.min, t[0]["id"]))
    unconfirmed.sort(key=lambda r: (r["Created Date"] or date.min, r["Ticket ID"]), reverse=True)

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
        if record["name"]:
            name_to_key.setdefault(c.normalize_name(record["name"]), key)
        return key

    # Register people with email first so name-only mentions can join them.
    for b, _ in tickets:
        for p in (b.get("requester"), b.get("requested_for"), b.get("recipient"), note_recipients.get(b["id"]),
                  subject_recipients.get(b["id"])):
            if p and p.get("email"):
                register(p)

    rows, links = [], []
    history: dict[tuple[str, str], list[date]] = defaultdict(list)
    seen_serials: set[str] = set()

    for b, matched in tickets:
        source, phrase, field = matched["Match Source"], matched["Matched Phrase"], matched["Matched Field"]
        items = b.get("items", [])
        requester = b.get("requester")
        requester_key = register(requester)
        requested_for_key = register(b.get("requested_for"))
        recipient = b.get("recipient")
        recipient_source = "Form" if recipient else None
        if recipient is None and requested_for_key and requested_for_key != requester_key:
            recipient, recipient_source = b.get("requested_for"), "Requested for"
        # Forms before December 2025 have no "Computer provided to" value. The subject ("Request for <Name> :")
        # names the recipient (Michael, 2026-11-25). Usually that is the requester or requested-for person; a
        # technician who files the form without changing it is named there too (technician-listed).
        subject_name = c.recipient_from_subject(b.get("subject")) if recipient is None else None
        if subject_name:
            same_name = [p for p in (b.get("requested_for"), requester)
                         if p and c.normalize_name(p.get("name")) == c.normalize_name(subject_name)]
            found = same_name[0] if same_name else subject_recipients.get(b["id"])
            if found:
                recipient, recipient_source = found, "Subject"
            else:
                recipient_source = "Subject (name only)"
        # The technician's closing note sometimes names who got the device. That beats a technician's own name in
        # the subject, but only when AD found exactly one employee; a bare name (a charity, a first name) doesn't.
        note_name = c.recipient_from_note(b.get("resolution_note")) if recipient is None or recipient_source == "Subject" else None
        if note_name and b["id"] in note_recipients and (recipient is None or _is_technician(recipient, technicians)):
            recipient, recipient_source = note_recipients[b["id"]], "Resolution note"
        elif note_name and recipient is None and recipient_source is None:
            recipient_source = "Resolution note (name only)"
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
        freq_rec, num_rec, gap_rec = sequence("recipient", recipient_key, False)  # technicians too (Michael, 2026-11-25)

        serial = form_value(items, "serial")
        serial_norm = serial.upper().replace(" ", "") if serial else None
        same_serial = None if not serial_norm else serial_norm in seen_serials
        if serial_norm:
            seen_serials.add(serial_norm)

        is_form = source in ("Form", "Both")
        # The practice is the department on the receiver's own Freshservice account. A technician who filed the
        # form isn't the receiver, and the ticket's own department is the filer's, so neither is used.
        owner_key = recipient_key or (None if requester_tech and is_form else requester_key)
        practice = persons.get(owner_key, {}).get("department") if owner_key else None

        certificates = [n for n in b.get("attachments", []) if c.is_certificate(n)]
        status = b.get("status")
        status_label = status or (f"Unknown ({b['status_code']})" if b.get("status_code") is not None else None)
        closed_texts = [n.get("text") for n in b.get("notes", [])] + [b.get("resolution_note")]
        decision = c.decide_outcome(status, b.get("approvals", []), closed_texts, overrides.get(b["id"]))
        make_model = form_value(items, "make")

        rows.append({
            "Ticket ID": b["id"],
            "Ticket URL": f"{ticket_url_base.rstrip('/')}/{b['id']}",
            "Created Date": created,
            "Requester Name": (requester or {}).get("name"),
            "Requester Email": (requester or {}).get("email"),
            "Department": practice or "Not recorded",
            "Computer Provided To": (recipient or {}).get("name") or subject_name or note_name
            or form_value(items, "provided_to"),
            "Recipient Differs From Requester": None if recipient_key is None else c.yes_no(recipient_key != requester_key),
            "Requested For": (b.get("requested_for") or {}).get("name"),
            **decision,
            "Device Type": c.device_type(c.model_name(make_model) or make_model, b.get("sub_category")),
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
            # Kept for the data contract. Unsure tickets are now held in the Unconfirmed table instead.
            "Match Needs Review": "No",
            "Ticket Type": b.get("type"),
            "Status": status_label,
            "Item Stage": next((i.get("stage") for i in items if i.get("stage")), None),
            "Closed Date": b.get("closed_at"),
            "Subject": b.get("subject"),
            "Resolution Note": b.get("resolution_note"),
            "Last Updated": b.get("updated_at"),
            "Requester Is Technician": c.yes_no(requester_tech) if requester_key else None,
            "Recipient Is Technician": c.yes_no(recipient_tech) if recipient_key else None,
            **cod_columns(b.get("cod"), serial),
            "Model": c.model_name(make_model),
            "Model Line": None,
            "Model Source": None,
            "Model Group": None,
            "Match Confidence": matched["Confidence"],
            "Archived": c.yes_no(bool(b.get("archived"))),
            "Recipient Source": recipient_source,
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
    _fill_models(rows)
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
        "Unconfirmed": (UNCONFIRMED_COLUMNS, unconfirmed),
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
        # Frequent (Michael, 2026-11-25): anyone named as the recipient ("Computer provided to") on tickets less than
        # 120 days apart, technicians included. Only tickets that name them as the recipient count, so asking for
        # others, or a free-text request before the form, does not.
        received = sorted(t["Created Date"] for t in as_recipient if t["Created Date"])
        gaps = [(b - a).days for a, b in zip(received, received[1:])]
        dates = [t["Created Date"] for t in tickets if t["Created Date"]]
        people.append({
            "Person": display[key],
            "Email": record["email"],
            "Department": record["department"],
            "Frequent": c.yes_no(any(g <= c.FREQUENT_WINDOW_DAYS for g in gaps)),
            "Requests Made": len(as_requester),
            "Requests Made For Others": sum(1 for t in as_requester if t["Recipient Differs From Requester"] == "Yes"),
            "Times Named As Recipient": len(as_recipient),
            **{o: sum(1 for t in own if t["Outcome"] == o) for o in c.OUTCOMES},
            "First Request": min(dates) if dates else None,
            "Last Request": max(dates) if dates else None,
            "Shortest Gap (Days)": min(gaps) if gaps else None,
            "Technician": c.yes_no(_is_technician(record, technicians)),
            "Last Received": received[-1] if received else None,
        })
    people.sort(key=lambda p: p["Person"].lower())
    return people
