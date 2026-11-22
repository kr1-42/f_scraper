from __future__ import annotations

from ..base import Provider
from ..models import Query


class WizzAir(Provider):
    """TODO. Plain HTTP is blocked (be.wizzair.com returns 429 and the API path embeds a
    rotating build version). Plan: drive a real browser (Playwright), let the site make its own
    /Api/search/search XHR and capture the JSON response, then map it to Offer."""

    name = "wizzair"
    mode = "flight"

    def search(self, q: Query):
        raise NotImplementedError("wizzair provider not implemented yet (needs browser session)")
        yield  # pragma: no cover
