"""Daily extract: Freshservice (read-only) -> 'DeMillimanize Requests.xlsx'.

Full mode lists every ticket updated since FULL_RUN_SINCE. Incremental mode lists tickets updated
since the last successful run (minus a two-day overlap) and merges them into the cached set.
A failed run keeps the previous data and records the failure in RunLog.
"""

import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone

from . import classify as c
from . import config
from .fetch import Fetcher
from .freshservice import FreshserviceClient, FreshserviceError
from .practices import ad_practices
from .tables import RUNLOG_COLUMNS, build_tables
from .workbook import write_workbook

OVERRIDE_COLUMNS = ["Ticket ID", "Outcome", "Reason", "Reviewed By", "Reviewed On"]
RUNLOG_TIME_COLUMNS = {"Started (UTC)", "Finished (UTC)", "Finished (Local)"}


def _load_json(name: str, default):
    path = config.STATE_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save_json(name: str, value) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = config.STATE_DIR / f"{name}.tmp"
    temp.write_text(json.dumps(value, indent=1, default=str), encoding="utf-8")
    temp.replace(config.STATE_DIR / name)


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


def main(argv: list[str]) -> int:
    started = datetime.now(timezone.utc)
    cache: dict[str, dict] = _load_json("tickets.json", {})
    meta: dict = _load_json("meta.json", {})
    runlog: list[dict] = _load_json("runlog.json", [])
    mode = "Full" if "--full" in argv or not meta.get("last_success_started") else "Incremental"

    status, messages, listed, forms, calls = "Success", [], 0, 0, 0
    technicians = set(meta.get("technicians", []))
    try:
        client = FreshserviceClient(config.BASE_URL, config.get_api_key())
        fetcher = Fetcher(client)
        try:
            fetcher.load_statuses()
            technicians = fetcher.load_technicians() or technicians
            if mode == "Full":
                since, fresh = config.FULL_RUN_SINCE, {}
            else:
                last = datetime.fromisoformat(meta["last_success_started"])
                since, fresh = (last - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), dict(cache)
            for summary in fetcher.list_tickets(since):
                listed += 1
                key = str(summary.get("id"))
                if c.is_candidate(summary.get("subject"), summary.get("description_text")):
                    try:
                        fresh[key] = fetcher.ticket_bundle(int(key))
                    except FreshserviceError as err:
                        fetcher.note(f"Ticket {key} skipped this run ({err}).")
                else:
                    fresh.pop(key, None)
            cache = fresh
            meta.update(last_success_started=started.isoformat(), technicians=sorted(technicians))
            _save_json("tickets.json", cache)
            _save_json("meta.json", meta)
        finally:
            forms, calls = fetcher.forms_checked, client.request_count
            messages += fetcher.notes
    except (FreshserviceError, OSError) as err:
        status = "Failed"
        messages.insert(0, f"Run failed; showing data from the last successful run. {err}")

    overrides, problems = load_overrides()
    messages += problems
    if mode == "Full" and status == "Success":
        messages.append("Archived tickets may not be returned by the ticket list API (unconfirmed).")

    # The agent list needs extra permission (403 on this key), so assignees also count as technicians.
    technicians |= {f"id:{b['responder_id']}" for b in cache.values() if b.get("responder_id")}
    # Freshservice person/department reads are 403 on this key, so practice comes from AD (SPARK's method).
    emails = [p.get("email") for b in cache.values()
              for p in (b.get("requester"), b.get("requested_for"), b.get("recipient")) if p]
    practices, ad_problem = ad_practices(emails)
    if ad_problem:
        messages.append(ad_problem)

    finished = datetime.now(timezone.utc)
    runlog.append({
        "Run": len(runlog) + 1,
        "Started (UTC)": started.replace(tzinfo=None).isoformat(timespec="seconds"),
        "Finished (UTC)": finished.replace(tzinfo=None).isoformat(timespec="seconds"),
        "Mode": mode, "Status": status, "Tickets Listed": listed, "Forms Checked": forms,
        "Matched Total": len(cache), "API Calls": calls, "Message": " ".join(messages)[:1000],
        "Finished (Local)": finished.astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
    })
    _save_json("runlog.json", runlog)

    tables = build_tables(list(cache.values()), technicians, overrides, config.TICKET_URL_BASE, practices)
    tables["RunLog"] = (RUNLOG_COLUMNS, [
        {k: (datetime.fromisoformat(v) if k in RUNLOG_TIME_COLUMNS else v) for k, v in r.items()}
        for r in runlog])
    try:
        write_workbook(config.WORKBOOK_PATH, tables)
    except OSError as err:
        print(f"Could not write the workbook: {err}")
        return 1
    print(f"{status}: {mode} run, {listed} tickets listed, {len(cache)} matched, {calls} API calls.")
    print(f"Workbook: {config.WORKBOOK_PATH}")
    for message in messages:
        print(f" - {message}")
    return 0 if status == "Success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
