from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _ssl_context() -> ssl.SSLContext:
    # python.org builds on macOS ship without CA certs; fall back to the system bundle (verification stays on).
    for cafile in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if cafile and os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


class HttpError(RuntimeError):
    pass


class Http:
    """Tiny stdlib HTTP client: retries with backoff + a minimum delay between calls."""

    def __init__(self, min_interval: float = 0.5, retries: int = 3, timeout: float = 20):
        self.min_interval, self.retries, self.timeout = min_interval, retries, timeout
        self._last = 0.0
        self._ctx = _ssl_context()

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        return json.loads(self.get_text(url, params, {"Accept": "application/json", **(headers or {})}))

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as r:
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < self.retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise HttpError(f"{e.code} for {url}") from e
            except urllib.error.URLError as e:
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise HttpError(f"{e.reason} for {url}") from e
