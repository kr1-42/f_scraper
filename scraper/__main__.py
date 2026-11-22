from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from .base import REGISTRY, get_provider
from .models import Query


def main(argv=None):
    from . import providers  # noqa: F401

    p = argparse.ArgumentParser(prog="scraper", description="Search flights/buses across providers")
    p.add_argument("provider", choices=sorted(REGISTRY))
    p.add_argument("origin")
    p.add_argument("destination", nargs="?", help="omit for 'anywhere' (where supported)")
    p.add_argument("--from", dest="date_from", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    p.add_argument("--to", dest="date_to", type=date.fromisoformat)
    p.add_argument("--currency", default="EUR")
    p.add_argument("--out", help="append results to this JSONL file (default: print a table)")
    a = p.parse_args(argv)

    q = Query(a.origin, a.destination, a.date_from, a.date_to or a.date_from, a.currency)
    offers = sorted(get_provider(a.provider).search(q), key=lambda o: o.price)

    if a.out:
        with open(a.out, "a") as f:
            for o in offers:
                f.write(json.dumps(o.to_dict()) + "\n")
        print(f"wrote {len(offers)} offers to {a.out}", file=sys.stderr)
    else:
        for o in offers:
            print(f"{o.departure:%Y-%m-%d %H:%M}  {o.origin:>10} -> {o.destination:<12} {o.price:7.2f} {o.currency}  {o.provider}")


if __name__ == "__main__":
    main()
