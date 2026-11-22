from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Query:
    """What the user asks for. Providers interpret origin/destination in their own way
    (IATA code for airlines, city name for buses). destination=None means 'anywhere'
    where the provider supports it."""

    origin: str
    destination: str | None
    date_from: date
    date_to: date  # inclusive
    currency: str = "EUR"
    adults: int = 1


@dataclass
class Offer:
    """One normalised trip, whatever the provider."""

    provider: str
    mode: str  # "flight" | "bus"
    origin: str
    destination: str
    departure: datetime
    arrival: datetime | None
    price: float
    currency: str
    carrier_ref: str | None = None  # flight number / ride id
    origin_name: str | None = None  # e.g. "Pisa, Italy"
    destination_name: str | None = None  # e.g. "Malaga, Spain"
    destination_country: str | None = None
    stops: int = 0
    scraped_at: datetime = field(default_factory=datetime.now)
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self, with_raw: bool = False) -> dict:
        d = asdict(self)
        if not with_raw:
            d.pop("raw")
        for k, v in d.items():
            if isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        return d


@dataclass
class Stay:
    """One accommodation option for a date range."""

    provider: str
    title: str
    url: str
    price_total: float  # for the whole stay
    currency: str
    nights: int
    rating: str | None = None  # e.g. "4.92 (324)"
    details: str | None = None  # e.g. "1 double bed · 1 bath"
    photo: str | None = None

    @property
    def per_night(self) -> float:
        return round(self.price_total / max(self.nights, 1), 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["per_night"] = self.per_night
        return d


@dataclass
class RoundTrip:
    out: Offer
    back: Offer
    stays: list[Stay] = field(default_factory=list)  # cheapest first; filled by the "whole trip" search

    @property
    def price(self) -> float:
        return round(self.out.price + self.back.price, 2)

    @property
    def total(self) -> float | None:
        """Flights + cheapest stay, or None if no stay was found."""
        return round(self.price + self.stays[0].price_total, 2) if self.stays else None

    def to_dict(self) -> dict:
        return {
            "stays": [s.to_dict() for s in self.stays],
            "trip_total": self.total,
            "provider": self.out.provider,
            "mode": self.out.mode,
            "origin": self.out.origin,
            "destination": self.out.destination,
            "price": self.price,
            "currency": self.out.currency,
            "out": self.out.to_dict(),
            "back": self.back.to_dict(),
        }
