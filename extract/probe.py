"""One-time discovery of the Freshservice API.

Prints the *shape* of the data (field names and types) without printing any values
that could identify an employee. The report is also saved to data/probe_report.json.

Run as the ADM account:  tools\\probe.cmd
"""

import json
import sys

from . import config
from .classify import mentions_denial
from .freshservice import FreshserviceClient, FreshserviceError

RATE_HEADERS = ("X-Ratelimit-Total", "X-Ratelimit-Remaining", "X-Ratelimit-Used-Currentrequest")


def describe(value, depth: int = 0):
    """Replace values with their type names so no personal data is shown."""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: describe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {"list_length": len(value), "item": describe(value[0], depth + 1) if value else None}
    return type(value).__name__


def step(report: dict, name: str, func):
    try:
        report[name] = {"ok": True, **func()}
    except FreshserviceError as err:
        report[name] = {"ok": False, "error": str(err)}
    except (AttributeError, TypeError, ValueError) as err:
        report[name] = {"ok": False, "error": f"Unexpected response format ({type(err).__name__})"}
    print(f"[{'OK' if report[name]['ok'] else 'FAILED'}] {name}")


def main() -> int:
    client = FreshserviceClient(config.BASE_URL, config.get_api_key())
    report: dict = {"base_url": config.BASE_URL}

    def connection():
        me = client.get("agents/me").get("agent", {})
        body = client.get("tickets", {"per_page": 1})
        tickets = body.get("tickets", [])
        rate = {h: client.last_headers.get(h) for h in RATE_HEADERS if h in client.last_headers}
        return {
            "key_belongs_to_an_agent": bool(me.get("id")),
            "ticket_shape": describe(tickets[0]) if tickets else None,
            "rate_limit_headers": rate,
        }

    def volume():
        body = client.get("tickets/filter", {"query": "\"created_at:>'2015-01-01'\""})
        return {"tickets_created_since_2015": body.get("total")}

    def statuses():
        body = client.get("ticket_form_fields")
        for field in body.get("ticket_fields", []):
            if field.get("name") == "status":
                return {"status_choices": {c.get("id"): c.get("value") for c in field.get("choices", [])}}
        return {"status_choices": None, "note": "status field not found"}

    def agents():
        body = client.get("agents", {"per_page": 1})
        items = body.get("agents", [])
        return {"agent_shape": describe(items[0]) if items else None}

    step(report, "connection", connection)
    if not report["connection"]["ok"]:
        print(json.dumps(report, indent=2))
        return 1
    step(report, "volume", volume)
    step(report, "statuses", statuses)
    step(report, "agents", agents)

    raw = input("\nTicket numbers to inspect, separated by spaces\n"
                "(ideally one form ticket and one older/archived ticket, digits only): ")
    for ticket_id in [t for t in raw.split() if t.isdigit()]:
        def ticket(tid=ticket_id):
            body = client.get(f"tickets/{tid}", {"include": "conversations,requested_for,stats"})
            t = body.get("ticket", {})
            convs = t.get("conversations", [])
            return {
                "ticket_shape": describe(t),
                "private_notes": sum(1 for c in convs if c.get("private")),
                "any_note_mentions_denial": any(mentions_denial(c.get("body_text")) for c in convs),
            }

        def items(tid=ticket_id):
            body = client.get(f"tickets/{tid}/requested_items")
            return {"requested_items_shape": describe(body)}

        step(report, f"ticket {ticket_id}", ticket)
        step(report, f"ticket {ticket_id} requested_items", items)

    print(json.dumps(report, indent=2))
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        out = config.DATA_DIR / "probe_report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved to {out}")
    except OSError as err:
        print(f"\nCould not save report ({err}). This account may not have write access to the folder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
