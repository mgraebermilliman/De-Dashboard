"""Find De-Millimanize requests among archived tickets (read-only, can be stopped and restarted).

Archived tickets aren't in the normal ticket list. `GET /tickets?filter=archived` lists them, 100 a page, at about
12 seconds a page (1,141 pages on 2026-11-24). That list has no description, so only the subject is screened. A
ticket whose subject passes is then read in full and kept in data/state/archive_tickets.json for the extract.

Progress is saved after every batch of pages. Archived tickets don't change and the list is read oldest first, so a
finished scan only reads the pages added since. A new scan starts at tickets created on or after
config.ARCHIVE_SINCE (2024-01-01); --all scans from the very first ticket. Use --restart after the wording rules change.

Run:  python run.py archive [--restart] [--all]
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from . import classify as c
from . import config
from .fetch import Fetcher
from .freshservice import FreshserviceClient, FreshserviceError
from .run_extract import _load_json, _save_json, save_cod_cache

PAGE_SIZE = 100
NEW_STATE = {"next_page": 1, "complete": False, "finished_at": None, "retry": []}


def _created(ticket: dict) -> date:
    try:
        return datetime.fromisoformat(str(ticket.get("created_at")).replace("Z", "+00:00")).date()
    except ValueError:
        return date.max  # unreadable date: don't skip past it


def first_page_since(fetcher: Fetcher, since: date) -> int:
    """The first archived page with a ticket created on or after `since`. The list is oldest first."""
    def reaches(page: int) -> bool:
        tickets = fetcher.archived_page(page)
        return not tickets or _created(tickets[-1]) >= since

    low, high = 0, 1
    while not reaches(high):
        low, high = high, high * 2
    while high - low > 1:
        middle = (low + high) // 2
        if reaches(middle):
            high = middle
        else:
            low = middle
    return high


def main(argv: list[str]) -> int:
    state = dict(NEW_STATE) if "--restart" in argv else {**NEW_STATE, **_load_json("archive_scan.json", {})}
    archive: dict[str, dict] = _load_json("archive_tickets.json", {})
    cod_cache: dict[str, dict] = _load_json("cod.json", {})
    client = FreshserviceClient(config.BASE_URL, config.get_api_key())
    fetcher = Fetcher(client, cod_cache)
    fetcher.load_statuses()

    def keep(ticket_id) -> bool:
        try:
            archive[str(ticket_id)] = fetcher.ticket_bundle(int(ticket_id))
            return True
        except FreshserviceError as err:
            print(f" - Ticket {ticket_id} could not be read and will be retried next time ({err}).", flush=True)
            return False

    def save() -> None:
        _save_json("archive_tickets.json", archive)
        save_cod_cache(cod_cache)
        _save_json("archive_scan.json", state)

    state["retry"] = [t for t in state["retry"] if not keep(t)]
    state["complete"] = False
    if state["next_page"] == 1 and config.ARCHIVE_SINCE and "--all" not in argv:
        print(f"Finding the first archived page from {config.ARCHIVE_SINCE} (about 12 quick checks).", flush=True)
        try:
            state["next_page"] = first_page_since(fetcher, date.fromisoformat(config.ARCHIVE_SINCE))
        except ValueError:
            print(f"DEDASH_ARCHIVE_SINCE must be a date like 2024-01-01, not '{config.ARCHIVE_SINCE}'.")
            return 1
        except FreshserviceError as err:
            print(f"Could not find the starting page: {err}. Run it again to continue.")
            return 1
        state["since"] = config.ARCHIVE_SINCE
    page, status = state["next_page"], 0
    print(f"Archive scan from page {page} ({config.ARCHIVE_WORKERS} at a time). Safe to stop; it resumes.", flush=True)
    try:
        with ThreadPoolExecutor(config.ARCHIVE_WORKERS) as pool:
            while True:
                batch = list(range(page, page + config.ARCHIVE_WORKERS))
                results = list(pool.map(fetcher.archived_page, batch))
                last = None
                for number, tickets in zip(batch, results):
                    for t in tickets:
                        if c.is_candidate(t.get("subject"), t.get("description_text")) and not keep(t.get("id")):
                            state["retry"].append(t.get("id"))
                    if tickets:
                        last = tickets[-1]
                    if len(tickets) < PAGE_SIZE:
                        # The last page is read again next time, because it fills up as more tickets are archived.
                        state.update(next_page=number, complete=True,
                                     finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                        break
                    state["next_page"] = number + 1
                save()
                if last:
                    print(f"Page {state['next_page'] - 1}: tickets created up to {str(last.get('created_at'))[:10]}, "
                          f"{len(archive)} possible requests kept, {client.request_count} API calls.", flush=True)
                if state["complete"]:
                    break
                page = state["next_page"]
    except FreshserviceError as err:
        save()
        print(f"Stopped at page {state['next_page']}: {err}. Run it again to continue.")
        status = 1
    except KeyboardInterrupt:
        save()
        print(f"Stopped at page {state['next_page']}. Run it again to continue.")
        status = 1
    for note in fetcher.notes:
        print(f" - {note}")
    if not status:
        print(f"Archive scan complete: {len(archive)} possible requests kept. Run 'python run.py extract' to rebuild "
              f"the workbook.")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
