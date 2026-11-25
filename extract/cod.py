"""Read the device details printed on a Certificate of Destruction (an Active@ KillDisk erase certificate).

Only the text is read; the PDF itself is never stored. pypdf is optional: without it the extract still
runs and the COD columns stay blank. Warranty and purchase dates are not on the certificate.
"""

import io
import re
from datetime import datetime

SECTIONS = {"Attributes", "Disk Information", "Results", "System Information", "Hardware Information",
            "Erase Passes"}
# Some certificates letter-space their headings ("R e s ult s"), so headings are compared without spaces.
_SECTION_KEYS = {re.sub(r"\s+", "", s).lower(): s for s in SECTIONS}


class CodUnavailable(Exception):
    """The PDF reader isn't installed."""


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise CodUnavailable("pypdf is not installed") from None
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def _label_values(text: str) -> dict[tuple[str, str], str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        # KillDisk draws every line twice, so the extracted text repeats each line.
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    values: dict[tuple[str, str], str] = {}
    section, i = "General", 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        heading = _SECTION_KEYS.get(re.sub(r"\s+", "", line).lower())
        if heading:
            section = heading
        elif line.rstrip(":") == "Computer" and nxt:
            values[("General", "Computer")] = nxt
            i += 1
        elif line.endswith(":") and nxt and not nxt.endswith(":") and not _SECTION_KEYS.get(re.sub(r"\s+", "", nxt).lower()):
            values.setdefault((section, line[:-1]), nxt)
            i += 1
        i += 1
    return values


def _erase_date(value: str | None) -> str | None:
    try:
        return datetime.strptime(value, "%B %d, %Y").date().isoformat() if value else None
    except ValueError:
        return None


def parse_cod_text(text: str) -> dict:
    """Column name -> value for the details on one certificate. Empty if the layout isn't recognized."""
    v = _label_values(text)
    fields = {
        "COD Erase Date": _erase_date(v.get(("General", "Date"))),
        "COD Erase Method": v.get(("Attributes", "Erase Method")),
        "COD Erase Result": v.get(("Results", "Result")),
        "COD Erase Errors": v.get(("Results", "Errors")),
        "COD Motherboard": v.get(("Hardware Information", "Motherboard")),
        "COD Processor": v.get(("Hardware Information", "Processor")),
        "COD Memory": v.get(("Hardware Information", "Memory")),
        "COD Drive Size": v.get(("Disk Information", "Size")),
        "COD OS": v.get(("System Information", "OS")),
        "COD BIOS": v.get(("Hardware Information", "BIOS")),
        "COD Device Serial": v.get(("Hardware Information", "BIOS Serial")),
    }
    recognized = fields["COD Erase Result"] or fields["COD Motherboard"] or fields["COD Device Serial"]
    return fields if recognized else {}
