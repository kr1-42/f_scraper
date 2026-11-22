"""Cheap round trips for one outbound date + one return date, skipping excluded countries.

    python3 -m scraper.cheap 2026-12-10 2026-12-13                # all configured airports
    python3 -m scraper.cheap 2026-12-10 2026-12-13 --max 60 PSA   # only PSA, total <= 60 EUR
    python3 -m scraper.cheap 2026-12-10 2026-12-13 --stays --max-stay 150   # + cheapest Airbnbs for the trip

Unlike the round-trip fare search (capped at 20 results by the API) this takes every outbound fare
for the day and looks up a return flight for each destination, so it can find more options.
"""
from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .base import get_provider
from .http import HttpError
from .config import EXCLUDE_COUNTRIES, ORIGINS, PROVIDERS
from .airbnb import StaysError, search_stays
from .models import Offer, Query, RoundTrip


def _cheapest_return(provider: str, out: Offer, ret: date, currency: str) -> RoundTrip | None:
    backs = [b for b in get_provider(provider).search(Query(out.destination, out.origin, ret, ret, currency))
             if b.destination == out.origin]
    return RoundTrip(out, min(backs, key=lambda b: b.price)) if backs else None


def cheap_round_trips(day: date, ret: date, origins: list[str] | None = None, max_price: float | None = None,
                      currency: str = "EUR") -> list[RoundTrip]:
    """Round trips (cheapest outbound that day + cheapest return that day, per destination), cheapest first.
    Destinations without a return flight on `ret` are dropped."""
    origins = origins or [o.iata for o in ORIGINS]
    outs = []
    for name in PROVIDERS:
        for origin in origins:
            for o in get_provider(name).search(Query(origin, None, day, day, currency)):
                if o.destination_country in EXCLUDE_COUNTRIES:
                    continue
                if max_price is not None and o.price > max_price:  # return leg can only add cost
                    continue
                outs.append(o)
    with ThreadPoolExecutor(8) as ex:
        trips = ex.map(lambda o: _cheapest_return(o.provider, o, ret, currency), outs)
    return sorted((t for t in trips if t and (max_price is None or t.price <= max_price)), key=lambda t: t.price)


def add_stays(trips: list[RoundTrip], adults: int = 1, max_stay: float | None = None, top: int = 10,
              keep: int = 3) -> tuple[list[RoundTrip], list[str]]:
    """Whole-trip search: for the `top` cheapest flight combos, find the `keep` cheapest stays in the
    destination from arrival day to return-departure day. Returns trips re-sorted by flights + stay
    (trips with no stay found go last) and a list of error messages."""
    errors: list[str] = []

    def work(t: RoundTrip):
        place = re.sub(r"\s*\(.*?\)", "", t.out.destination_name or t.out.destination)  # drop "(… airport)"
        try:
            t.stays = search_stays(place, t.out.arrival.date(), t.back.departure.date(), adults, max_stay)[:keep]
        except (StaysError, HttpError) as e:
            errors.append(f"stays {place}: {e}")

    head = trips[:top]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(work, head))
    head.sort(key=lambda t: (t.total is None, t.total if t.total is not None else t.price))
    return head, errors


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("day", type=date.fromisoformat)
    p.add_argument("ret", type=date.fromisoformat)
    p.add_argument("origins", nargs="*", help="IATA codes (default: configured airports)")
    p.add_argument("--max", type=float, dest="max_price", help="only round trips up to this total price")
    p.add_argument("--stays", action="store_true", help="also search Airbnb in each destination")
    p.add_argument("--max-stay", type=float, help="max total price for the stay")
    a = p.parse_args()
    trips = cheap_round_trips(a.day, a.ret, [x.upper() for x in a.origins], a.max_price)
    if a.stays:
        trips, errs = add_stays(trips, max_stay=a.max_stay)
        for e in errs:
            print("!", e)
    for t in trips:
        print(f"{t.out.origin} -> {t.out.destination:<4} {t.out.destination_name or '':<45}"
              f" out {t.out.price:6.2f} {t.out.carrier_ref}  back {t.back.price:6.2f} {t.back.carrier_ref}  = {t.price:6.2f} {t.out.currency}")
        for st in t.stays[:1]:
            print(f"      stay: {st.price_total:.0f} ({st.per_night}/night) {st.title} {st.rating or ''}  TOTAL {t.total:.2f}\n      {st.url}")


if __name__ == "__main__":
    main()
