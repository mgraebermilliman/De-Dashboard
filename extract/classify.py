"""Rules for recognising De-Millimanize tickets and deriving dashboard values.

Every rule here is documented in OVERVIEW.md ("Business rules"). Change both together.
"""

import re
from datetime import date, datetime

# Spelling variants seen or expected: Demillimanize, De-Millimanize, de millimanized, Demilimanize.
DEMILL_PATTERN = re.compile(r"\bde[\s\-]*mil+i?man+[a-z]*", re.IGNORECASE)
FORM_ITEM_PATTERN = re.compile(r'"?De-Millimanize"?\s+Device with Milliman Data', re.IGNORECASE)
DENIAL_PATTERN = re.compile(
    r"\b(denied|deny|declined?|rejected|reject|not approved|disapproved)\b", re.IGNORECASE
)
CERTIFICATE_PATTERN = re.compile(r"^certificate-.*\.pdf$", re.IGNORECASE)

APPROVED, DENIED, PENDING, NEEDS_REVIEW = "Approved", "Denied", "Pending", "Needs Review"
OUTCOMES = (APPROVED, DENIED, PENDING, NEEDS_REVIEW)

FREQUENT_WINDOW_DAYS = 120

# Model-name families only; anything else is "Unknown" rather than a guess.
_LAPTOP = re.compile(r"thinkpad|latitude|elitebook|probook|zbook|surface laptop|surface pro|macbook", re.I)
_DESKTOP = re.compile(r"thinkcentre|optiplex|elitedesk|prodesk|precision tower|imac|mac mini", re.I)


def is_candidate(subject: str | None, description: str | None) -> bool:
    """Cheap pre-filter applied to every listed ticket before any extra API calls."""
    return bool(DEMILL_PATTERN.search(subject or "") or DEMILL_PATTERN.search(description or ""))


def match(subject: str | None, description: str | None, item_names: list[str]) -> tuple[str, str, str] | None:
    """Return (Match Source, Matched Phrase, Matched Field) or None when the ticket doesn't match."""
    form_item = next((n for n in item_names if FORM_ITEM_PATTERN.search(n or "")), None)
    phrase, field = None, None
    for field_name, text in (("Subject", subject), ("Description", description)):
        found = DEMILL_PATTERN.search(text or "")
        if found:
            phrase, field = found.group(0), field_name
            break
    if form_item and phrase:
        return "Both", phrase, field
    if form_item:
        return "Form", form_item, "Requested Item"
    if phrase:
        return "Phrase", phrase, field
    return None


def denial_snippet(texts: list[str | None], width: int = 60) -> str | None:
    """Return a short excerpt around the first denial word found, or None."""
    for text in texts:
        found = DENIAL_PATTERN.search(text or "")
        if found:
            start, end = max(found.start() - width, 0), min(found.end() + width, len(text))
            return " ".join(text[start:end].split())
    return None


def decide_outcome(
    status_name: str | None,
    approvals: list[dict],
    closed_texts: list[str | None],
    override: dict | None = None,
) -> dict:
    """Outcome, Outcome Source, Outcome Evidence, Approver and Decision Date for one ticket.

    Order: manual override, approver decision, closed ticket (denial wording means Needs Review,
    never an automatic Denied), open ticket = Pending, anything unclear = Needs Review.
    """
    decided = [a for a in approvals if (a.get("status") or "").lower() in ("approved", "rejected")]
    latest = max(decided, key=lambda a: a.get("decided_at") or datetime.min) if decided else None
    approver = latest.get("approver") if latest else None
    approval_date = latest.get("decided_at") if latest else None

    if override:
        return {
            "Outcome": override["Outcome"],
            "Outcome Source": "Manual Override",
            "Outcome Evidence": override.get("Reason") or "",
            "Approver": override.get("Reviewed By") or approver,
            "Decision Date": override.get("Reviewed On") or approval_date,
        }
    if latest:
        rejected = latest["status"].lower() == "rejected"
        return {
            "Outcome": DENIED if rejected else APPROVED,
            "Outcome Source": "Approval",
            "Outcome Evidence": f"{latest['status'].capitalize()} by {approver or 'unknown approver'}",
            "Approver": approver,
            "Decision Date": approval_date,
        }
    status = (status_name or "").strip()
    if not status:
        return _result(NEEDS_REVIEW, "Unknown status", "Ticket status could not be read")
    if status.lower() == "closed":
        snippet = denial_snippet(closed_texts)
        if snippet:
            return _result(NEEDS_REVIEW, "Closed ticket text", f'Denial wording: "{snippet}"')
        return _result(APPROVED, "Closed ticket text", "Ticket closed; no denial wording in notes")
    return _result(PENDING, f"Status: {status}", "Ticket is not closed and has no approval decision")


def _result(outcome: str, source: str, evidence: str) -> dict:
    return {"Outcome": outcome, "Outcome Source": source, "Outcome Evidence": evidence,
            "Approver": None, "Decision Date": None}


def device_type(make_model: str | None, sub_category: str | None) -> str:
    if make_model and _LAPTOP.search(make_model):
        return "Laptop"
    if make_model and _DESKTOP.search(make_model):
        return "Desktop"
    if sub_category and sub_category.strip().lower() in ("laptop", "desktop"):
        return sub_category.strip().capitalize()
    return "Unknown"


def is_holiday_season(day: date | None) -> bool:
    """Nov 15 through Jan 5."""
    if day is None:
        return False
    return (day.month == 11 and day.day >= 15) or day.month == 12 or (day.month == 1 and day.day <= 5)


def is_certificate(file_name: str | None) -> bool:
    return bool(file_name and CERTIFICATE_PATTERN.match(file_name.strip()))


def normalize_name(name: str | None) -> str:
    """Lower-case, drop any '<email>' part, and collapse whitespace."""
    if not name:
        return ""
    return " ".join(re.sub(r"<[^>]*>", "", name).lower().split())


def yes_no(value: bool | None) -> str | None:
    return None if value is None else ("Yes" if value else "No")
