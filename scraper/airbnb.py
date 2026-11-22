"""Airbnb stay search. Airbnb server-renders the first page of search results as JSON inside the HTML
(<script id="data-deferred-state-0">), so plain HTTP is enough. This is an undocumented structure and
can change; failures raise StaysError.

Results are ~18 listings per query, in Airbnb's own ranking, so we filter by price_max and sort ourselves.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from urllib.parse import quote

from .http import Http
from .models import Stay

URL = "https://www.airbnb.com/s/{place}/homes"


class StaysError(RuntimeError):
    pass


def _slug(place: str) -> str:
    return quote("--".join(p.strip().replace(" ", "-") for p in place.split(",")))


def _money(line: dict) -> float | None:
    for key in ("discountedPrice", "price"):
        m = re.search(r"\d[\d,]*(?:\.\d+)?", line.get(key) or "")
        if m:
            return float(m.group().replace(",", ""))
    return None


def _walk_results(o):
    if isinstance(o, dict):
        if o.get("__typename") == "StaySearchResult":
            yield o
        else:
            for v in o.values():
                yield from _walk_results(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_results(v)


def search_stays(place: str, checkin: date, checkout: date, adults: int = 1, max_total: float | None = None,
                 currency: str = "EUR", http: Http | None = None) -> list[Stay]:
    """Cheapest-first stays in `place` (e.g. "Malaga, Spain") for the dates. Prices are for the whole stay."""
    nights = (checkout - checkin).days
    if nights < 1:
        raise StaysError("checkout must be after checkin")
    params = {"checkin": checkin.isoformat(), "checkout": checkout.isoformat(), "adults": adults,
              "currency": currency}
    if max_total:
        params["price_max"] = int(max_total)
    html = (http or Http()).get_text(URL.format(place=_slug(place)), params)
    m = re.search(r'<script id="data-deferred-state-0"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise StaysError("airbnb: results block not found (blocked or page changed)")
    stays = []
    for r in _walk_results(json.loads(m.group(1))):
        line = ((r.get("structuredDisplayPrice") or {}).get("primaryLine")) or {}
        price = _money(line)
        if price is None:
            continue
        if line.get("qualifier") and "night" in line["qualifier"]:  # per-night display -> total
            price *= nights
        try:
            lid = base64.b64decode(r["demandStayListing"]["id"]).decode().split(":")[-1]
        except Exception:
            lid = r.get("propertyId")
        if not lid:
            continue
        info = [x.get("body") for x in (r.get("structuredContent") or {}).get("primaryLine") or [] if x.get("body")]
        pics = r.get("contextualPictures") or []
        stays.append(Stay(
            provider="airbnb",
            title=f"{r.get('title') or 'Stay'} · {r.get('subtitle') or ''}".strip(" ·"),
            url=f"https://www.airbnb.com/rooms/{lid}?check_in={checkin}&check_out={checkout}&adults={adults}",
            price_total=price,
            currency=currency,
            nights=nights,
            rating=r.get("avgRatingLocalized"),
            details=" · ".join(info) or None,
            photo=pics[0]["picture"] if pics else None,
        ))
    unique = {s.url: s for s in stays}  # the same listing can appear in both list and map results
    return sorted((s for s in unique.values() if max_total is None or s.price_total <= max_total),
                  key=lambda s: s.price_total)
