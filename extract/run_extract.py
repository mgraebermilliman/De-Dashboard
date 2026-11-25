"""Daily extract: Freshservice (read-only) -> 'DeMillimanize Requests.xlsx'.

Full mode lists every ticket updated since FULL_RUN_SINCE. Incremental mode lists tickets updated
since the last successful run (minus a two-day overlap) and merges them into the cached set.
A failed run keeps the previous data and records the failure in RunLog.
"""

import csv
import json
import sys
from itertools import chain
from datetime import date, datetime, timedelta, timezone

from . import classify as c
from . import config
from .fetch import Fetcher
from .freshservice import FreshserviceClient, FreshserviceError
from .tables import RUNLOG_COLUMNS, build_tables
from .workbook import write_workbook

OVERRIDE_COLUMNS = ["Ticket ID", "Outcome", "Reason", "Reviewed By", "Reviewed On"]
CONFIRMATION_COLUMNS = ["Ticket ID", "Is De-Millimanize", "Reviewed By", "Reviewed On", "Note"]
RUNLOG_TIME_COLUMNS = {"Started (UTC)", "Finished (UTC)", "Finished (Local)"}


def _load_json(name: str, default):
    path = config.STATE_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save_json(name: str, value) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = config.STATE_DIR / f"{name}.tmp"
    temp.write_text(json.dumps(value, indent=1, default=str), encoding="utf-8")
    temp.replace(config.STATE_DIR / name)


def save_cod_cache(cod_cache: dict) -> None:
    # The extract and the archive scan can run at the same time, so add to the file instead of replacing it.
    _save_json("cod.json", {**_load_json("cod.json", {}), **cod_cache})


def unmatched_names(bundles: dict[str, dict]) -> tuple[dict[int, str], dict[int, str]]:
    """Names that say who got a device but match no person on the ticket: (resolution-note names, subject names).

    Only tickets with no "Computer provided to" value are looked at. A subject name that is the requester or the
    requested-for person is already known, so only the others need a Freshservice lookup.
    """
    note_names = {b["id"]: name for b in bundles.values() if not b.get("recipient")
                  for name in [c.recipient_from_note(b.get("resolution_note"))] if name}
    subject_names = {}
    for b in bundles.values():
        name = None if b.get("recipient") else c.recipient_from_subject(b.get("subject"))
        known = {c.normalize_name((p or {}).get("name")) for p in (b.get("requester"), b.get("requested_for"))}
        if name and c.normalize_name(name) not in known:
            subject_names[b["id"]] = name
    return note_names, subject_names


def load_overrides(path=None) -> tuple[dict[int, dict], list[str]]:
    """Manual outcome decisions. Creates an empty template the first time."""
    path = path or config.OVERRIDES_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(OVERRIDE_COLUMNS)
        return {}, []
    overrides, problems = {}, []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            ticket, outcome = (row.get("Ticket ID") or "").strip(), (row.get("Outcome") or "").strip().title()
            if not ticket.isdigit() or outcome not in c.OUTCOMES:
                problems.append(f"Override line {line} ignored (needs a numeric Ticket ID and one of {', '.join(c.OUTCOMES)}).")
                continue
            reviewed_on = (row.get("Reviewed On") or "").strip()
            try:
                reviewed = date.fromisoformat(reviewed_on) if reviewed_on else None
            except ValueError:
                reviewed = None
                problems.append(f"Override line {line}: 'Reviewed On' must be YYYY-MM-DD.")
            overrides[int(ticket)] = {"Outcome": outcome, "Reason": (row.get("Reason") or "").strip(),
                                      "Reviewed By": (row.get("Reviewed By") or "").strip() or None,
                                      "Reviewed On": reviewed}
    return overrides, problems


def load_confirmations(path=None) -> tuple[dict[int, bool], list[str]]:
    """A person's yes/no on tickets the wording rules weren't sure about. Creates an empty template the first time."""
    path = path or config.CONFIRMATIONS_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CONFIRMATION_COLUMNS)
        return {}, []
    confirmations, problems = {}, []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            ticket = (row.get("Ticket ID") or "").strip()
            answer = (row.get("Is De-Millimanize") or "").strip().lower()
            if not ticket.isdigit() or answer not in ("yes", "no"):
                problems.append(f"Confirmation line {line} ignored (needs a numeric Ticket ID and Yes or No).")
                continue
            confirmations[int(ticket)] = answer == "yes"
    return confirmations, problems


def archive_message(state: dict | None) -> str | None:
    if not state:
        return "Archived tickets haven't been scanned yet. Run 'python run.py archive'."
    if not state.get("complete"):
        return f"The archived-ticket scan isn't finished (next page {state.get('next_page')}). Run 'python run.py archive'."
    return None


def main(argv: list[str]) -> int:
    started = datetime.now(timezone.utc)
    cache: dict[str, dict] = _load_json("tickets.json", {})
    meta: dict = _load_json("meta.json", {})
    runlog: list[dict] = _load_json("runlog.json", [])
    mode = "Full" if "--full" in argv or not meta.get("last_success_started") else "Incremental"
    if mode == "Incremental" and any("cod" not in b or "archived" not in b for b in cache.values()):
        mode = "Full"  # tickets cached before certificate details or the wider wording rules need one full pass
    cod_cache: dict[str, dict] = _load_json("cod.json", {})

    status, messages, listed, forms, calls = "Success", [], 0, 0, 0
    technicians = set(meta.get("technicians", []))
    try:
        client = FreshserviceClient(config.BASE_URL, config.get_api_key())
        fetcher = Fetcher(client, cod_cache)
        try:
            fetcher.load_statuses()
            technicians = fetcher.load_technicians() or technicians
            if mode == "Full":
                since, fresh = config.FULL_RUN_SINCE, {}
            else:
                last = datetime.fromisoformat(meta["last_success_started"])
                since, fresh = (last - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), dict(cache)
            seen = set()
            for summary in fetcher.list_tickets(since):
                listed += 1
                key = str(summary.get("id"))
                seen.add(key)
                if c.is_candidate(summary.get("subject"), summary.get("description_text")):
                    try:
                        fresh[key] = fetcher.ticket_bundle(int(key))
                    except FreshserviceError as err:
                        fetcher.note(f"Ticket {key} skipped this run ({err}).")
                else:
                    fresh.pop(key, None)
            if mode == "Full":
                # Matched earlier but no longer listed: archived since then (still readable by number) or deleted.
                for key in sorted(set(cache) - seen):
                    try:
                        fresh[key] = fetcher.ticket_bundle(int(key))
                    except FreshserviceError as err:
                        fetcher.note(f"Ticket {key} is no longer readable and was dropped ({err}).")
            cache = fresh
            meta.update(last_success_started=started.isoformat(), technicians=sorted(technicians))
            _save_json("tickets.json", cache)
            save_cod_cache(cod_cache)
            # Find the people that those names stand for, once. A name nobody matched is tried again next run.
            people = _load_json("people.json", {})
            for name in sorted(set(chain(*(d.values() for d in unmatched_names(
                    {**_load_json("archive_tickets.json", {}), **cache}))))):
                if people.get(name.lower()) is None:
                    people[name.lower()] = fetcher.person_by_name(name)
            _save_json("people.json", people)
            _save_json("meta.json", meta)
        finally:
            forms, calls = fetcher.forms_checked, client.request_count
            messages += fetcher.notes
    except (FreshserviceError, OSError) as err:
        status = "Failed"
        messages.insert(0, f"Run failed; showing data from the last successful run. {err}")

    overrides, problems = load_overrides()
    messages += problems
    confirmations, problems = load_confirmations()
    messages += problems
    # Archived tickets come from the separate archive scan (extract/archive.py). The live copy of a ticket wins.
    bundles: dict[str, dict] = {**_load_json("archive_tickets.json", {}), **cache}
    archive_note = archive_message(_load_json("archive_scan.json", None))
    if archive_note:
        messages.append(archive_note)

    # The agent list needs extra permission (403 on this key), so assignees also count as technicians.
    technicians |= {f"id:{b['responder_id']}" for b in bundles.values() if b.get("responder_id")}
    # A name in the subject or the closing note counts as a person only when Freshservice has exactly one by that name.
    people = _load_json("people.json", {})
    note_names, subject_names = unmatched_names(bundles)
    note_recipients = {t: people[n.lower()] for t, n in note_names.items() if people.get(n.lower())}
    subject_recipients = {t: people[n.lower()] for t, n in subject_names.items() if people.get(n.lower())}

    tables = build_tables(list(bundles.values()), technicians, overrides, config.TICKET_URL_BASE,
                          confirmations=confirmations, note_recipients=note_recipients,
                          subject_recipients=subject_recipients,
                          earliest=date.fromisoformat(config.DATA_START) if config.DATA_START else None)
    waiting = len(tables["Unconfirmed"][1])
    if waiting:
        messages.append(f"{waiting} ticket(s) are waiting for a yes/no in {config.CONFIRMATIONS_PATH.name}.")

    finished = datetime.now(timezone.utc)
    runlog.append({
        "Run": len(runlog) + 1,
        "Started (UTC)": started.replace(tzinfo=None).isoformat(timespec="seconds"),
        "Finished (UTC)": finished.replace(tzinfo=None).isoformat(timespec="seconds"),
        "Mode": mode, "Status": status, "Tickets Listed": listed, "Forms Checked": forms,
        "Matched Total": len(tables["Requests"][1]), "API Calls": calls, "Message": " ".join(messages)[:1000],
        "Finished (Local)": finished.astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
    })
    _save_json("runlog.json", runlog)

    tables["RunLog"] = (RUNLOG_COLUMNS, [
        {k: (datetime.fromisoformat(v) if k in RUNLOG_TIME_COLUMNS else v) for k, v in r.items()}
        for r in runlog])
    try:
        write_workbook(config.WORKBOOK_PATH, tables)
    except OSError as err:
        print(f"Could not write the workbook: {err}")
        return 1
    print(f"{status}: {mode} run, {listed} tickets listed, {len(tables['Requests'][1])} requests, "
          f"{waiting} waiting for confirmation, {calls} API calls.")
    print(f"Workbook: {config.WORKBOOK_PATH}")
    for message in messages:
        print(f" - {message}")
    return 0 if status == "Success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
