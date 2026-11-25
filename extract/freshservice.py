"""Read-only Freshservice API v2 client. Only GET requests are implemented on purpose."""

import base64
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

_NEXT_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


class FreshserviceError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Following a redirect would resend the API key to whatever host it points at.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FreshserviceError(
            f"Server redirected to {urllib.parse.urlsplit(newurl).netloc} (HTTP {code}). "
            "Set FRESHSERVICE_BASE_URL to the API host instead of following the redirect."
        )


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = _NEXT_LINK.search(link_header)
    return match.group(1) if match else None


def tls_context() -> ssl.SSLContext:
    """Full certificate and hostname verification, as in Python 3.12.

    Python 3.13's VERIFY_X509_STRICT is cleared because an older Zscaler root (expires 2042) in the
    Windows store lacks a critical Basic Constraints flag. Approved by Kevin, 2026-11-20 (OVERVIEW.md).
    """
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


class FreshserviceClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30, max_retries: int = 5):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme != "https":
            raise ValueError("Freshservice base URL must use https.")
        self._base = base_url.rstrip("/")
        self._host = parts.netloc.lower()
        token = base64.b64encode(f"{api_key}:X".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self._timeout = timeout
        self._max_retries = max_retries
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=tls_context()))
        self.last_headers: dict[str, str] = {}
        self.request_count = 0

    def _url(self, path: str, params: dict | None) -> str:
        url = f"{self._base}/api/v2/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _check_host(self, url: str) -> None:
        if urllib.parse.urlsplit(url).netloc.lower() != self._host:
            raise FreshserviceError("Refusing to send credentials to a different host.")

    def _request(self, url: str) -> tuple[dict, str | None]:
        self._check_host(url)
        for attempt in range(self._max_retries + 1):
            req = urllib.request.Request(url, headers=self._headers, method="GET")
            self.request_count += 1
            try:
                with self._opener.open(req, timeout=self._timeout) as resp:
                    self.last_headers = dict(resp.headers.items())
                    body = json.loads(resp.read().decode("utf-8") or "{}")
                    return body, parse_next_link(resp.headers.get("Link"))
            except urllib.error.HTTPError as err:
                self.last_headers = dict(err.headers.items()) if err.headers else {}
                if err.code == 429 and attempt < self._max_retries:
                    time.sleep(int(err.headers.get("Retry-After", "60")))
                    continue
                if err.code >= 500 and attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                path = urllib.parse.urlsplit(url).path
                raise FreshserviceError(f"HTTP {err.code} for GET {path}") from None
            except urllib.error.URLError as err:
                raise FreshserviceError(f"Could not reach {self._host}: {err.reason}") from None
        raise FreshserviceError("Retries exhausted.")

    def get(self, path: str, params: dict | None = None) -> dict:
        body, _ = self._request(self._url(path, params))
        return body

    def download(self, url: str, max_bytes: int = 5_000_000) -> bytes:
        """GET a ticket attachment's pre-signed link. The API key is deliberately not sent."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not (parts.hostname or "").lower().endswith(".freshservice.com"):
            raise FreshserviceError("Refusing to download from a host outside freshservice.com.")
        try:
            with self._opener.open(urllib.request.Request(url, method="GET"), timeout=self._timeout) as resp:
                data = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as err:
            raise FreshserviceError(f"HTTP {err.code} downloading an attachment") from None
        except urllib.error.URLError as err:
            raise FreshserviceError(f"Could not download an attachment: {err.reason}") from None
        if len(data) > max_bytes:
            raise FreshserviceError("Attachment is larger than expected.")
        return data

    def get_all(self, path: str, key: str, params: dict | None = None, page_delay: float = 0.5):
        """Yield every item across all pages of a list endpoint."""
        params = {"per_page": 100, **(params or {})}
        url: str | None = self._url(path, params)
        while url:
            body, url = self._request(url)
            yield from body.get(key, [])
            if url:
                time.sleep(page_delay)
