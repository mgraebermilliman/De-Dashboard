"""Read De-Millimanize tickets from Freshservice and normalize them into bundles.

A bundle is a plain dict (JSON-safe; times as ISO strings) consumed by tables.build_tables.
Shapes marked UNVERIFIED haven't been seen from this Freshservice account yet; the probe
reports them. Every lookup tolerates missing fields and never writes to Freshservice.
"""

import re
from datetime import datetime, timezone

from . import classify as c
from . import cod
from .freshservice import FreshserviceClient, FreshserviceError
from .practices import DEPARTMENT_NAMES

# Freshservice's documented default status values, used only if ticket fields can't be read.
DEFAULT_STATUSES = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")


def local_iso(value) -> str | None:
    """Freshservice UTC timestamp -> local wall-clock ISO string (what people see in the portal)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _full_name(record: dict) -> str | None:
    name = record.get("name") or " ".join(filter(None, [record.get("first_name"), record.get("last_name")]))
    return name.strip() or None


class Fetcher:
    def __init__(self, client: FreshserviceClient, cod_cache: dict | None = None):
        self.client = client
        # Parsed certificate details by attachment id, so each certificate is downloaded once.
        self.cod_cache: dict[str, dict] = cod_cache if cod_cache is not None else {}
        self._cod_unavailable = False
        self._messages: list[str] = []
        self._failures: dict[str, tuple[int, str]] = {}
        self._forbidden: set[str] = set()
        self.forms_checked = 0
        self.statuses: dict[int, str] = dict(DEFAULT_STATUSES)
        self._users: dict[object, dict | None] = {}
        self._departments: dict[int, str | None] = {}
        self._agents: dict[int, dict] = {}
        self._approvals_allowed = True

    @property
    def notes(self) -> list[str]:
        return self._messages + [f"{kind} lookups failed {count} time(s); first error: {first}."
                                 for kind, (count, first) in self._failures.items()]

    def note(self, message: str) -> None:
        self._messages.append(message)

    def _try_get(self, kind: str, path: str, params: dict | None = None) -> dict | None:
        if kind in self._forbidden:
            return None
        try:
            return self.client.get(path, params)
        except FreshserviceError as err:
            self._record_failure(kind, str(err))
            return None

    def _record_failure(self, kind: str, error: str) -> None:
        count, first = self._failures.get(kind, (0, error))
        self._failures[kind] = (count + 1, first)
        # A 403 won't change during the run; stop spending rate limit on it.
        if "HTTP 403" in error:
            self._forbidden.add(kind)

    # ---- reference data -------------------------------------------------
    def load_statuses(self) -> None:
        try:
            body = self.client.get("ticket_form_fields")
        except FreshserviceError as err:
            self._messages.append(f"Status names from Freshservice defaults ({err}).")
            return
        for field in body.get("ticket_fields", []):
            if field.get("name") == "status":
                choices = {int(ch["id"]): str(ch.get("value")) for ch in field.get("choices", [])
                           if isinstance(ch, dict) and str(ch.get("id", "")).isdigit()}
                if choices:
                    self.statuses = choices
                    return
        self._messages.append("Status names from Freshservice defaults (status field not found).")

    def load_technicians(self) -> set[str]:
        """Lower-cased emails and normalized names of Freshservice agents (needs permission to list agents)."""
        technicians: set[str] = set()
        try:
            for agent in self.client.get_all("agents", "agents"):
                name = _full_name(agent)
                self._agents[agent.get("id")] = {"name": name, "email": agent.get("email"),
                                                 "department_ids": agent.get("department_ids") or []}
                if agent.get("email"):
                    technicians.add(agent["email"].strip().lower())
                if name:
                    technicians.add(c.normalize_name(name))
        except FreshserviceError as err:
            self._messages.append(f"Agent list unavailable ({err}); technicians detected from ticket assignees only.")
        return technicians

    def list_tickets(self, updated_since: str):
        yield from self.client.get_all("tickets", "tickets", {"updated_since": updated_since})

    def archived_page(self, page: int) -> list[dict]:
        """One page of archived tickets, oldest first. Subjects only: this list has no description."""
        body = self.client.get("tickets", {"filter": "archived", "order_type": "asc", "per_page": 100, "page": page})
        return body.get("tickets", [])

    # ---- lookups ------------------------------------------------------------
    def department_name(self, department_id) -> str | None:
        if not department_id:
            return None
        if department_id not in self._departments:
            body = None if department_id in DEPARTMENT_NAMES else self._try_get("Department", f"departments/{department_id}")
            self._departments[department_id] = DEPARTMENT_NAMES.get(department_id) or \
                ((body or {}).get("department") or {}).get("name")
        return self._departments[department_id]

    def user_by_id(self, user_id) -> dict | None:
        if not user_id:
            return None
        if user_id not in self._users:
            record = None
            # Agents aren't returned by /requesters/{id}, so a 404 there is expected for technicians.
            for path, key, kind in ((f"requesters/{user_id}", "requester", "Requester"),
                                    (f"agents/{user_id}", "agent", "Agent")):
                body = self._try_get(kind, path)
                if body and body.get(key):
                    record = body[key]
                    break
            self._users[user_id] = self._person(record) if record else None
        return self._users[user_id]

    def user_by_email(self, email: str) -> dict | None:
        key = ("email", email.lower())
        if key not in self._users:
            record = None
            for path, list_key in (("requesters", "requesters"), ("agents", "agents")):
                found = (self._try_get("Email", path, {"email": email}) or {}).get(list_key) or []
                if found:
                    record = found[0]
                    break
            self._users[key] = self._person(record) if record else None
        return self._users[key]

    def person_by_name(self, name: str) -> dict | None:
        """The one employee or technician with this full name, or None when nobody or more than one matches.

        Freshservice searches first and last name, so a middle name is tried both ways. A name with a quote in it
        is skipped rather than put into a search query.
        """
        parts = name.split()
        key = ("name", " ".join(parts).lower())
        if key not in self._users:
            found: list[dict] = []
            if len(parts) >= 2 and not re.search(r"[\'\"\\]", name):
                splits = [(parts[0], " ".join(parts[1:]))]
                if len(parts) > 2:
                    splits.append((" ".join(parts[:-1]), parts[-1]))
                for first, last in splits:
                    query = f"\"first_name:'{first}' AND last_name:'{last}'\""
                    for path in ("requesters", "agents"):
                        found += (self._try_get(f"{path} by name", path, {"query": query}) or {}).get(path) or []
                    if found:
                        break
            self._users[key] = self._person(found[0]) if len(found) == 1 else None
        return self._users[key]

    def _person(self, record: dict) -> dict:
        department_ids = record.get("department_ids") or []
        return {
            "id": record.get("id"),
            "name": _full_name(record),
            "email": record.get("primary_email") or record.get("email"),
            "department": self.department_name(department_ids[0]) if department_ids else None,
        }

    def resolve_person(self, raw, known: dict | None = None) -> dict | None:
        """'Computer provided to' is a user ID on this account (probe, 2026-11-20); emails and text are handled too."""
        if raw in (None, ""):
            return None
        text = str(raw).strip()
        if text.isdigit():
            user_id = int(text)
            # Usually the same person as the ticket's requester or requested-for, which we already have.
            if known and known.get(user_id):
                return known[user_id]
            return self.user_by_id(user_id) or {"id": user_id, "name": f"Unknown user (ID {user_id})",
                                                "email": None, "department": None}
        email = _EMAIL.search(text)
        if email:
            found = self.user_by_email(email.group(0))
            name = re.sub(r"<[^>]*>", "", text).replace(email.group(0), "").strip() or None
            return found or {"name": name or email.group(0), "email": email.group(0), "department": None}
        return {"name": text, "email": None, "department": None}

    # ---- one ticket ------------------------------------------------------------
    def ticket_bundle(self, ticket_id: int) -> dict:
        t = self.client.get(f"tickets/{ticket_id}", {"include": "requester,requested_for,stats"}).get("ticket", {})
        requester = self._embedded_person(t.get("requester"), t.get("requester_id"))
        requested_for = self._embedded_person(t.get("requested_for"), t.get("requested_for_id"))
        known = {t.get("requester_id"): requester, t.get("requested_for_id"): requested_for}
        items = self._requested_items(ticket_id) if t.get("type") == "Service Request" else []
        raw_recipient = next((v for i in items for k, v in i["fields"].items() if "provided_to" in k.lower() and v), None)
        custom = t.get("custom_fields") or {}
        status_code = t.get("status")
        approvals = self._approvals(ticket_id)
        ticket_approval = (t.get("approval_status_name") or "").strip().lower()
        if not approvals and ticket_approval in ("approved", "rejected"):
            approvals = [{"status": ticket_approval, "approver": None, "decided_at": None}]
        # The certificate is attached to the form item, not the ticket (probe, 2026-11-20).
        files = [{"id": a.get("id"), "name": a.get("name"), "url": a.get("attachment_url")}
                 for a in t.get("attachments") or []]
        files += [f for i in items for f in i.pop("files")]
        attachments = [f["name"] for f in files if f["name"]]
        certificate_details = self.certificate_details(files)
        return {
            "id": ticket_id,
            "type": t.get("type"),
            "subject": t.get("subject"),
            "description_text": t.get("description_text"),
            "status": self.statuses.get(status_code),
            "status_code": status_code,
            "archived": bool(t.get("archived")),
            "created_at": local_iso(t.get("created_at")),
            "updated_at": local_iso(t.get("updated_at")),
            "closed_at": local_iso((t.get("stats") or {}).get("closed_at")),
            "sub_category": t.get("sub_category"),
            "department": self.department_name(t.get("department_id")),
            "responder_id": t.get("responder_id"),
            "requester": requester,
            "requested_for": requested_for,
            "recipient": self.resolve_person(raw_recipient, known),
            "items": items,
            "approvals": approvals,
            "notes": self._notes(ticket_id),
            "attachments": attachments,
            "cod": certificate_details,
            "resolution_note": t.get("resolution_notes") or next(
                (str(v) for k, v in custom.items() if "resolution" in k.lower() and v), None),
        }

    def _embedded_person(self, embedded: dict | None, user_id) -> dict | None:
        user_id = user_id or (embedded or {}).get("id")
        looked_up = self.user_by_id(user_id)
        if looked_up:
            return looked_up
        if embedded:
            return {"id": user_id, "name": _full_name(embedded),
                    "email": embedded.get("email") or embedded.get("primary_email"), "department": None}
        return None

    def _requested_items(self, ticket_id: int) -> list[dict]:
        self.forms_checked += 1
        try:
            body = self.client.get(f"tickets/{ticket_id}/requested_items")
        except FreshserviceError as err:
            self._messages.append(f"Requested items unavailable for ticket {ticket_id} ({err}).")
            return []
        return [{"name": i.get("service_item_name") or i.get("name"),
                 "stage": None if i.get("stage") is None else str(i.get("stage")),
                 "fields": i.get("custom_fields") or {},
                 "files": [{"id": a.get("id"), "name": a.get("name"), "url": a.get("attachment_url")}
                           for a in i.get("attachments") or []],
                 "attachments": [a.get("name") for a in i.get("attachments") or [] if a.get("name")]}
                for i in body.get("requested_items", [])]

    def certificate_details(self, files: list[dict]) -> dict | None:
        """Details printed on the ticket's Certificate of Destruction, or None if unavailable."""
        for f in files:
            if not c.is_certificate(f.get("name")):
                continue
            key = str(f.get("id") or f["name"])
            if key in self.cod_cache:
                return self.cod_cache[key]
            if self._cod_unavailable or not f.get("url"):
                continue
            try:
                details = cod.parse_cod_text(cod.pdf_text(self.client.download(f["url"])))
            except cod.CodUnavailable as err:
                self._cod_unavailable = True
                self._messages.append(f"Certificate details skipped ({err}).")
                return None
            except Exception as err:  # pypdf raises its own error types on damaged files
                self._record_failure("Certificate", f"{type(err).__name__}: {err}")
                continue
            if not details:
                self._record_failure("Certificate", "layout not recognized")
                continue
            self.cod_cache[key] = details
            return details
        return None

    def _approvals(self, ticket_id: int) -> list[dict]:
        if not self._approvals_allowed:
            return []
        try:
            body = self.client.get(f"tickets/{ticket_id}/approvals")  # UNVERIFIED path and shape
        except FreshserviceError as err:
            if "HTTP 403" in str(err):
                self._approvals_allowed = False
                self._messages.append("Approvals not readable with this API key; outcomes use ticket status and notes.")
            return []
        approvals = []
        for a in body.get("approvals", []):
            status = a.get("approval_status")
            if isinstance(status, dict):
                status = status.get("name")
            approver = self._agents.get(a.get("approver_id"), {}).get("name") or \
                (self.user_by_id(a.get("approver_id")) or {}).get("name")
            approvals.append({"status": str(status or "").lower(), "approver": approver,
                              "decided_at": local_iso(a.get("updated_at"))})
        return approvals

    def _notes(self, ticket_id: int) -> list[dict]:
        try:
            return [{"private": bool(n.get("private")), "text": n.get("body_text")}
                    for n in self.client.get_all(f"tickets/{ticket_id}/conversations", "conversations")]
        except FreshserviceError as err:
            self._messages.append(f"Notes unavailable for ticket {ticket_id} ({err}).")
            return []
