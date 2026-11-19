"""Rules for recognising De-Millimanize tickets and deriving dashboard outcomes.

Every rule here is documented in OVERVIEW.md. Change both together.
"""

import re

# Spelling variants seen or expected: Demillimanize, De-Millimanize, de millimanized, Demilimanize.
DEMILL_PATTERN = re.compile(r"\bde[\s\-]*mil+i?man+[a-z]*", re.IGNORECASE)

FORM_ITEM_NAME = '"De-Millimanize" Device with Milliman Data'
FORM_SUBJECT_PATTERN = re.compile(r'"?De-Millimanize"?\s+Device with Milliman Data', re.IGNORECASE)

DENIAL_PATTERN = re.compile(
    r"\b(denied|deny|declined?|rejected|reject|not approved|disapproved)\b", re.IGNORECASE
)

COMPLETED = "Completed"
UNKNOWN = "Unknown"
POSSIBLE_DENIAL = "Possible denial - review"

FORM = "Form"
LEGACY = "Legacy - matched by keywords"


def ticket_kind(subject: str | None, description: str | None) -> str | None:
    """Return FORM, LEGACY, or None if the ticket doesn't look like a De-Millimanize request."""
    subject = subject or ""
    if FORM_SUBJECT_PATTERN.search(subject):
        return FORM
    if DEMILL_PATTERN.search(subject) or DEMILL_PATTERN.search(description or ""):
        return LEGACY
    return None


def outcome(status_name: str | None, denial_flagged: bool = False) -> str:
    if denial_flagged:
        return POSSIBLE_DENIAL
    if not status_name:
        return UNKNOWN
    if status_name.strip().lower() == "closed":
        return COMPLETED
    return f"Not completed ({status_name.strip()})"


def mentions_denial(text: str | None) -> bool:
    return bool(text and DENIAL_PATTERN.search(text))


def normalize_name(name: str | None) -> str:
    """Lower-case, drop any '<email>' part, and collapse whitespace."""
    if not name:
        return ""
    name = re.sub(r"<[^>]*>", "", name)
    return " ".join(name.lower().split())


def is_technician(recipient: str | None, technician_names: set[str]) -> bool:
    return normalize_name(recipient) in technician_names
