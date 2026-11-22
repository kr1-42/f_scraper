from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterator

from .http import Http
from .models import Offer, Query, RoundTrip

REGISTRY: dict[str, type["Provider"]] = {}


class Provider(ABC):
    name: str
    mode: str

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if getattr(cls, "name", None):
            REGISTRY[cls.name] = cls

    def __init__(self, http: Http | None = None):
        self.http = http or Http()

    @abstractmethod
    def search(self, q: Query) -> Iterator[Offer]:
        """Yield normalised Offers for the query."""

    def search_round_trip(self, origin: str, destination: str | None, depart: date, ret: date,
                          currency: str = "EUR") -> list[RoundTrip]:
        """Default: cheapest outbound + cheapest return per destination, from two one-way searches.
        Providers with a native round-trip endpoint override this."""
        outs = list(self.search(Query(origin, destination, depart, depart, currency)))
        backs = {}
        for dest in {o.destination for o in outs}:
            for b in self.search(Query(dest, origin, ret, ret, currency)):
                backs[dest] = min(backs.get(dest, b), b, key=lambda x: x.price)
        best = {}
        for o in outs:
            if o.destination in backs and (o.destination not in best or o.price < best[o.destination].price):
                best[o.destination] = o
        return sorted((RoundTrip(o, backs[d]) for d, o in best.items()), key=lambda r: r.price)


def get_provider(name: str) -> Provider:
    from . import providers  # noqa: F401  (populates REGISTRY)

    try:
        return REGISTRY[name]()
    except KeyError:
        raise SystemExit(f"unknown provider {name!r}; available: {', '.join(sorted(REGISTRY))}")
