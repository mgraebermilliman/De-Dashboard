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


# Wording for keeping or getting a company device for personal use ("keep company laptop",
# "laptop for personal use"). "keep my laptop from sleeping" and similar are not requests to keep it.
_DEVICE = r"(?:laptops?|computers?|pcs?|desktops?|devices?|machines?|macbooks?|macs?|thinkpads?|notebooks?)"
DEVICE_PATTERN = re.compile(rf"\b{_DEVICE}\b", re.IGNORECASE)
_OWNED = r"(?:my|the|this|that|his|her|their|our|your|a|an|company|work|old|older|current|existing|previous|former|milliman|same|own)"
KEEP_PATTERN = re.compile(
    rf"\bkeep(?:ing)?\s+(?:{_OWNED}\s+){{0,4}}{_DEVICE}\b"
    r"(?!\s+(?:from|on|awake|running|open|connected|plugged|updated|charged|locked|unlocked|logged|turned|up|in|"
    r"with|at|while|until|safe|secure|cool|fan|name|names)\b)",
    re.IGNORECASE)
PERSONAL_USE_PATTERN = re.compile(r"\bfor\s+(?:(?:my|his|her|their|your|our)\s+)?(?:own\s+)?personal\s+use\b", re.IGNORECASE)
_NEAR = 80  # characters between a device word and "for personal use" for them to count as one phrase

HIGH, MEDIUM, LOW, CONFIRMED = "High", "Medium", "Low", "Confirmed"
HIGH_SCORE, MEDIUM_SCORE = 4, 2
# Points per piece of evidence. Subject and resolution-note wording count more than a mention in the description.
_POINTS = {"Subject": 3, "Resolution Note": 3, "Description": 2}


def _keep_phrase(text: str | None) -> tuple[str, bool] | None:
    """A keep-the-device phrase in the text: (phrase, strong). Weak = "for personal use" far from any device word."""
    text = text or ""
    found = KEEP_PATTERN.search(text)
    if found:
        return " ".join(found.group(0).split()), True
    for personal in PERSONAL_USE_PATTERN.finditer(text):
        window = text[max(personal.start() - _NEAR, 0):personal.end() + _NEAR]
        if DEVICE_PATTERN.search(window):
            return " ".join(personal.group(0).split()), True
    personal = PERSONAL_USE_PATTERN.search(text)
    return (" ".join(personal.group(0).split()), False) if personal else None


def is_candidate(subject: str | None, description: str | None) -> bool:
    """Cheap pre-filter applied to every listed ticket before any extra API calls.

    Archived tickets are listed without a description, so only their subject is screened.
    """
    texts = (subject or "", description or "")
    if any(DEMILL_PATTERN.search(t) for t in texts):
        return True
    if not DEVICE_PATTERN.search(" ".join(texts)):
        return False
    return any(_keep_phrase(t) for t in texts)


def assess(subject: str | None, description: str | None, resolution_note: str | None,
           item_names: list[str]) -> dict | None:
    """How sure we are that a ticket is a De-Millimanize request, or None when nothing points to one.

    Returns Match Source, Matched Phrase, Matched Field, Confidence (High / Medium / Low), Score and Evidence.
    The form item is always High. Otherwise the points of every piece of wording are added up.
    """
    form_item = next((n for n in item_names if FORM_ITEM_PATTERN.search(n or "")), None)
    fields = (("Subject", subject), ("Resolution Note", resolution_note), ("Description", description))
    has_device = bool(DEVICE_PATTERN.search(" ".join(text or "" for _, text in fields)))
    score, evidence, phrase, field, clear_request = 0, [], None, None, False
    for name, text in fields:
        found = DEMILL_PATTERN.search(text or "")
        if found:
            score += _POINTS[name]
            clear_request = clear_request or name == "Subject"
            evidence.append(f'"{found.group(0)}" in {name.lower()}')
            if phrase is None:
                phrase, field = found.group(0), name
    for name, text in fields:
        if name == "Resolution Note" or not has_device:
            continue
        kept = _keep_phrase(text)
        if kept:
            wording, strong = kept
            score += _POINTS[name] if strong else 1
            clear_request = clear_request or strong
            evidence.append(f'"{wording}" in {name.lower()}' + ("" if strong else " (no device named nearby)"))
            if phrase is None:
                phrase, field = wording, name
    if not form_item and not score:
        return None
    if form_item:
        source = "Both" if phrase else "Form"
        confidence = HIGH
        evidence.insert(0, "De-Millimanize form")
    else:
        source = "Phrase"
        # High needs the request itself to be clear: wording in the subject or a keep / personal-use phrase,
        # backed by a second piece of evidence. A passing mention in the description or notes is not enough.
        confidence = HIGH if score >= HIGH_SCORE and clear_request else MEDIUM if score >= MEDIUM_SCORE else LOW
    return {"Match Source": source, "Matched Phrase": phrase or form_item,
            "Matched Field": field or "Requested Item", "Confidence": confidence, "Score": score,
            "Evidence": "; ".join(evidence)}


# Who the technician's closing note says the device went to: "De-Millimanized for Jane Example",
# "given to Jane Example". A word must look like a name (letters, with a lower-case letter), which leaves out
# PC names, "EP" and "a school". Donation notes name a cause, not a recipient, so they are skipped.
_NOTE_WORD = r"[A-Z](?=[A-Za-z'\-]*[a-z])[A-Za-z'\-]+"
_NOTE_RECIPIENT = re.compile(rf"\b(?:for|to)\s+({_NOTE_WORD}(?:\s+{_NOTE_WORD}){{0,2}})(?![\w\-])")
_NOTE_SKIP = re.compile(r"donat|charit|school|non-?\s?profit", re.IGNORECASE)
_NOTE_NOT_NAMES = {"desktop", "laptop", "windows", "milliman", "jamf", "office", "teams", "onedrive", "intune", "personal"}


def recipient_from_note(resolution_note: str | None) -> str | None:
    """The name after "for" or "to" in a resolution note, or None. It may be a person, a first name or a charity."""
    note = " ".join((resolution_note or "").split())
    if not note or _NOTE_SKIP.search(note):
        return None
    for found in _NOTE_RECIPIENT.finditer(note):
        if found.group(1).split()[0].lower() not in _NOTE_NOT_NAMES:
            return found.group(1)
    return None


_SUBJECT_RECIPIENT = re.compile(r'^\s*Request for\s+(.+?)\s*:\s*"?De[\s\-]*mil+i?man', re.IGNORECASE)


def recipient_from_subject(subject: str | None) -> str | None:
    """The name in a form ticket's subject, 'Request for <Name> : "De-Millimanize" Device with Milliman Data'.

    Michael confirmed on 2026-11-25 that this name is the recipient. When a technician files the form without
    changing it, it is the technician's own name (the "technician-listed" case).
    """
    found = _SUBJECT_RECIPIENT.match(subject or "")
    return " ".join(found.group(1).split()) if found else None


def excerpt(text: str | None, width: int = 110) -> str | None:
    """A short piece of the text around the first De-Millimanize or keep-the-device wording, for a person to judge."""
    text = " ".join((text or "").split())
    if not text:
        return None
    found = DEMILL_PATTERN.search(text) or KEEP_PATTERN.search(text) or PERSONAL_USE_PATTERN.search(text)
    if not found:
        return text[:2 * width] + ("..." if len(text) > 2 * width else "")
    start, end = max(found.start() - width, 0), min(found.end() + width, len(text))
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")


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


# Lenovo machine types look like 21HLS1WQ00 (a model code, not a name).
_MACHINE_TYPE = re.compile(r"^\d\d[0-9A-Z]{2}[0-9A-Z]{2,7}$", re.I)
_MODEL_BRANDS = ("thinkpad", "thinkcentre", "dell", "hp", "apple", "microsoft")
_SERIAL_LIKE = re.compile(r"^(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,10}$", re.I)
_MACHINE_SUFFIX = re.compile(r"^S[0-9A-Z]{5}$", re.I)  # the tail of 21HLS1WQ00
_NOT_A_MODEL = {"test", "n/a", "na", "unknown", "none", "laptop", "desktop", "pc", "computer", "tbd", "?"}

# A PC name carries the model: 'MILWI-T15-JF' is a ThinkPad T15, 'CMH-P14S-JF' a ThinkPad P14s. Only these shapes
# count, and only as a whole segment of the name, so initials and practice codes don't match by accident.
_PC_MODEL_TOKENS = (
    (re.compile(r"^T(\d{2,3})([sp])?$", re.I), lambda m: f"ThinkPad T{m[1]}{(m[2] or '').lower()}"),
    (re.compile(r"^X1C(?:ARBON)?$", re.I), lambda m: "ThinkPad X1 Carbon"),
    (re.compile(r"^X1Y(?:OGA)?$", re.I), lambda m: "ThinkPad X1 Yoga"),
    (re.compile(r"^X1$", re.I), lambda m: "ThinkPad X1"),
    (re.compile(r"^X(\d{2,3})$", re.I), lambda m: f"ThinkPad X{m[1]}"),
    (re.compile(r"^P(\d{2})([sv])?$", re.I), lambda m: f"ThinkPad P{m[1]}{(m[2] or '').lower()}"),
    (re.compile(r"^E(\d{2,3})$", re.I), lambda m: f"ThinkPad E{m[1]}"),
    (re.compile(r"^L(\d{2})$", re.I), lambda m: f"ThinkPad L{m[1]}"),
    (re.compile(r"^M(\d{2,3})([a-z])?$", re.I), lambda m: f"ThinkCentre M{m[1]}{(m[2] or '').lower()}"),
    (re.compile(r"^SURFP(?:RO)?(\d)?$", re.I), lambda m: f"Surface Pro{' ' + m[1] if m[1] else ''}"),
    (re.compile(r"^(?:LAT)?([57]\d{3})$", re.I), lambda m: f"Dell Latitude {m[1]}"),
)
_CERT_PC_NAME = re.compile(
    r"^certificate-(?P<pc>.+?)-[A-Z0-9]{7,12}-[A-Z0-9]{3,8}-(?:success|fail\w*|error\w*)-\d{4}(?:-\d{2}){5}\.pdf$", re.I)


def machine_type(value: str | None) -> str | None:
    """First four characters of a Lenovo machine type ('LENOVO 21HLS1WQ00' or '21HLS1WQ00' -> '21HL')."""
    text = re.sub(r"^lenovo\s+", "", (value or "").strip(), flags=re.I).replace(" ", "")
    if _MACHINE_TYPE.match(text) or re.fullmatch(r"[0-9A-Z]{4}", text, re.I) and text[0].isdigit():
        return text[:4].upper()
    return None


def model_name(raw: str | None) -> str | None:
    """Tidy a typed make/model ('lenovo t14s', 'Lenovo M90Q Gen3') into one spelling ('ThinkPad T14s').

    Returns None for blanks and for bare machine-type codes, which don't name a model.
    """
    text = re.sub(r"[\s_]+", " ", raw or "").strip()
    compact = text.replace(" ", "")
    # Serial numbers ('MJ0E843G'), machine-type codes ('20NY', '20NY-S20V00', 'S09B00') and filler aren't model names.
    one_word = " " not in text
    if (not text or _MACHINE_TYPE.match(compact) or text.lower() in _NOT_A_MODEL
            or (one_word and (_SERIAL_LIKE.match(text) or _MACHINE_SUFFIX.match(text)
                              or re.fullmatch(r"\d\d[0-9A-Z]{2}(?:-[0-9A-Z]{3,8})?", text, re.I)))):
        return None
    low = text.lower().replace("think pad", "thinkpad").replace("think centre", "thinkcentre")
    low = re.sub(r"\blenovo\b", " ", low)
    low = re.sub(r"\bgen\s*(\d+)\s*i?\b", r"gen \1", low)  # 'gen3', 'gen 2i' -> 'gen 3', 'gen 2'
    tokens = low.split()
    if not tokens:
        return None
    special = {"thinkpad": "ThinkPad", "thinkcentre": "ThinkCentre", "hp": "HP"}
    words = []
    for t in tokens:
        if t in special:
            words.append(special[t])
        elif re.fullmatch(r"[a-z]\d+[a-z]?", t):
            words.append(t[0].upper() + t[1:])
        else:
            words.append(t.capitalize())
    first = tokens[0]
    if first == "latitude":
        words.insert(0, "Dell")
    elif first not in _MODEL_BRANDS:
        if re.fullmatch(r"[ptxel]\d+[a-z]?", first):
            words.insert(0, "ThinkPad")
        elif re.fullmatch(r"m\d+[a-z]?", first):
            words.insert(0, "ThinkCentre")
    return " ".join(words)


def model_from_pc_name(pc_name: str | None) -> str | None:
    """The model a PC name spells out ('MILWI-T15-JF' -> 'ThinkPad T15'), or None."""
    for segment in re.split(r"[-_\s.]+", pc_name or ""):
        for pattern, build in _PC_MODEL_TOKENS:
            found = pattern.match(segment)
            if found:
                return build(found)
    return None


def certificate_pc_name(file_name: str | None) -> str | None:
    """The old PC name inside 'Certificate-<PC name>-<serial>-<disk>-Success-<date>.pdf', or None."""
    found = _CERT_PC_NAME.match((file_name or "").strip())
    return found.group("pc") if found else None


def model_family(line: str | None) -> str:
    """A coarse family for model lines too rare to show on their own in the chart."""
    low = (line or "").lower()
    if low.startswith("thinkpad"):
        return "Other ThinkPad"
    if low.startswith("thinkcentre"):
        return "Other ThinkCentre"
    if "surface" in low:
        return "Surface"
    if low.startswith("hp") or "elitebook" in low:
        return "HP EliteBook"
    if low.startswith("dell"):
        return "Dell"
    return "Other models"


def model_line(name: str | None) -> str | None:
    """Model without its generation or number ('ThinkPad T14s Gen 2' -> 'ThinkPad T14s'), for charts."""
    if not name:
        return None
    return re.sub(r"^(Dell Latitude)\s+\d.*$", r"\1", re.sub(r"\s+Gen \d+$", "", name))


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
