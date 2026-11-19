import os
from pathlib import Path

API_KEY_ENV = "FRESHSERVICE_API_KEY"
# API host confirmed from SPARK's source. hd.milliman.com is the portal and returns 404 for the API.
BASE_URL = os.environ.get("FRESHSERVICE_BASE_URL", "https://milliman-helpdesk.freshservice.com").rstrip("/")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Temporary location; to be moved to the secure drive in a later stage.
DATA_DIR = Path(os.environ.get("DEDASH_DATA_DIR", PROJECT_ROOT / "data"))


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SystemExit(
            f"{API_KEY_ENV} is not set for this Windows account "
            f"({os.environ.get('USERNAME', 'unknown')}). Run this as the ADM account."
        )
    return key
