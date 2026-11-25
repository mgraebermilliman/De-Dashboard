import os
from pathlib import Path

API_KEY_ENV = "FRESHSERVICE_API_KEY"
# API host confirmed from SPARK's source. hd.milliman.com is the portal and returns 404 for the API.
BASE_URL = os.environ.get("FRESHSERVICE_BASE_URL", "https://milliman-helpdesk.freshservice.com").rstrip("/")
# Agent ticket page; to be confirmed whether people prefer the hd.milliman.com portal address.
TICKET_URL_BASE = os.environ.get("DEDASH_TICKET_URL_BASE", f"{BASE_URL}/a/tickets")
# How far back a full run lists tickets.
FULL_RUN_SINCE = os.environ.get("DEDASH_FULL_RUN_SINCE", "2015-01-01")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Temporary location; to be moved to the secure drive / SharePoint in a later stage.
DATA_DIR = Path(os.environ.get("DEDASH_DATA_DIR", PROJECT_ROOT / "data"))
WORKBOOK_PATH = DATA_DIR / "DeMillimanize Requests.xlsx"
STATE_DIR = DATA_DIR / "state"
OVERRIDES_PATH = DATA_DIR / "outcome_overrides.csv"
# A person's yes/no on tickets the wording rules weren't sure about. Each ticket only needs confirming once.
CONFIRMATIONS_PATH = DATA_DIR / "match_confirmations.csv"
# Archived list pages take about 12 seconds each; a few at a time stays far below the 140-a-minute limit.
ARCHIVE_WORKERS = max(1, min(int(os.environ.get("DEDASH_ARCHIVE_WORKERS", "4")), 6))
# Tickets created before this date aren't relevant and are left out of the workbook (Michael, 2026-11-25).
DATA_START = os.environ.get("DEDASH_DATA_START", "2023-07-01").strip() or None
# A new archive scan starts at tickets created on or after this date. Blank = scan everything.
ARCHIVE_SINCE = os.environ.get("DEDASH_ARCHIVE_SINCE", DATA_START or "").strip() or None


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip() or _registry_user_env(API_KEY_ENV)
    if not key:
        raise SystemExit(
            f"{API_KEY_ENV} is not set for this Windows account "
            f"({os.environ.get('USERNAME', 'unknown')}). Run this as the ADM account."
        )
    return key


def _registry_user_env(name: str) -> str:
    # Scheduled tasks don't always receive user variables in the process environment.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""
