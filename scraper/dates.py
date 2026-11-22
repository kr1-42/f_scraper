"""Reverse search: you pick the destination (city, airport code, country or region) and a window of
dates; we find the cheapest round trips inside it.

    python3 -m scraper.dates Spain 2026-12-01 2026-12-31 --nights 2-5
    python3 -m scraper.dates Malaga 2026-12-01 2026-12-31 --nights 3 --stays --max-stay 150
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .cheap import add_stays
from .config import ORIGINS
from .models import RoundTrip
from .providers.ryanair import Ryanair


def _months(a: date, b: date) -> list[date]:
    out, d = [], a.replace(day=1)
    while d <= b:
        out.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _matches(text: str, a: dict) -> bool:
    t = text.strip().lower()
    fields = [a["code"], a["name"], a["city"]["name"], a["country"]["name"], a["country"]["code"],
              (a.get("region") or {}).get("name", "")] + list(a.get("aliases") or [])
    return any(t == f.lower() for f in fields) or (len(t) > 3 and any(t in f.lower() for f in fields))


def find_dates(destination: str, first: date, last: date, min_nights: int = 2, max_nights: int = 5,
               origins: list[str] | None = None, max_price: float | None = None, currency: str = "EUR",
               limit: int = 40) -> tuple[list[RoundTrip], list[str]]:
    """Cheapest round trips to `destination` where you leave and return inside [first, last].
    Returns (trips sorted by price, error/info messages)."""
    ryan = Ryanair()
    origins = origins or [o.iata for o in ORIGINS]
    errors: list[str] = []
    pairs = []
    for o in origins:
        try:
            origin = ryan.airport(o)
            pairs += [(origin, d) for d in ryan.destinations(o) if _matches(destination, d) and d["code"] != o]
        except KeyError:
            errors.append(f"Ryanair doesn't serve {o}")
        except Exception as e:
            errors.append(f"ryanair {o}: {e}")
    if not pairs:
        errors.append(f"no Ryanair route found from {', '.join(origins)} matching {destination!r}")
        return [], errors

    months = _months(first, last)

    def calendar(job):
        a, b, month = job
        return Ryanair().cheapest_per_day(a, b, month, currency)  # own client per thread

    jobs = [(a, b, m) for a, b in pairs for m in months] + [(b, a, m) for a, b in pairs for m in months]
    with ThreadPoolExecutor(8) as ex:
        cals = list(ex.map(lambda j: _safe(calendar, j, errors), jobs))
    n = len(pairs) * len(months)
    trips: list[RoundTrip] = []
    for i, (a, b) in enumerate(pairs):
        outs = {d: o for c in cals[i * len(months):(i + 1) * len(months)] for d, o in c.items()}
        backs = {d: o for c in cals[n + i * len(months):n + (i + 1) * len(months)] for d, o in c.items()}
        for d, o in outs.items():
            if not first <= d <= last:
                continue
            for nights in range(min_nights, max_nights + 1):
                b_ = backs.get(d + timedelta(days=nights))
                if b_ and b_.departure.date() <= last:
                    trips.append(RoundTrip(o, b_))
    trips = [t for t in trips if max_price is None or t.price <= max_price]
    return sorted(trips, key=lambda t: t.price)[:limit], errors


def _safe(fn, job, errors):
    try:
        return fn(job)
    except Exception as e:
        errors.append(f"calendar {job[0]['code']}->{job[1]['code']}: {e}")
        return {}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("destination")
    p.add_argument("first", type=date.fromisoformat)
    p.add_argument("last", type=date.fromisoformat)
    p.add_argument("--nights", default="2-5", help="N or MIN-MAX nights (default 2-5)")
    p.add_argument("--max", type=float, dest="max_price")
    p.add_argument("--stays", action="store_true")
    p.add_argument("--max-stay", type=float)
    a = p.parse_args()
    lo, _, hi = a.nights.partition("-")
    trips, errs = find_dates(a.destination, a.first, a.last, int(lo), int(hi or lo), max_price=a.max_price)
    if a.stays:
        trips, e2 = add_stays(trips, max_stay=a.max_stay)
        errs += e2
    for e in errs:
        print("!", e)
    for t in trips:
        print(f"{t.out.departure:%a %d %b} -> {t.back.departure:%a %d %b} ({(t.back.departure.date() - t.out.departure.date()).days}n)  "
              f"{t.out.origin} -> {t.out.destination} {t.out.destination_name:<42} {t.out.price:6.2f} + {t.back.price:6.2f} = {t.price:6.2f}"
              + (f"   +stay {t.stays[0].price_total:.0f} = {t.total:.2f}" if t.stays else ""))


if __name__ == "__main__":
    main()
