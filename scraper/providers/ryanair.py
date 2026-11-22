from __future__ import annotations

import json
from datetime import date, datetime

from ..base import Provider
from ..models import Offer, Query, RoundTrip

URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"
ROUTES_URL = "https://www.ryanair.com/api/views/locate/searchWidget/routes/en/airport/{}"
AIRPORTS_URL = "https://www.ryanair.com/api/views/locate/5/airports/en/active"
CPD_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares/{}/{}/cheapestPerDay"
RT_URL = "https://services-api.ryanair.com/farfnd/v4/roundTripFares"


class Ryanair(Provider):
    """Uses Ryanair's public 'fare finder' endpoint: cheapest fare per route/day.
    One call covers a whole date range and supports destination=None ('anywhere')."""

    name = "ryanair"
    mode = "flight"

    def search(self, q: Query):
        params = {
            "departureAirportIataCode": q.origin.upper(),
            "outboundDepartureDateFrom": q.date_from.isoformat(),
            "outboundDepartureDateTo": q.date_to.isoformat(),
            "currency": q.currency,
            "limit": 100,
        }
        if q.destination:
            params["arrivalAirportIataCode"] = q.destination.upper()
        data = self.http.get_json(URL, params)
        for f in data.get("fares", []):
            yield self._offer(f["outbound"], f)

    @staticmethod
    def _fmt_place(city: str, country: str, airport: str) -> str:
        return f"{city}, {country}" + (f" ({airport} airport)" if airport != city else "")

    @classmethod
    def _place(cls, a: dict) -> str:  # airport dict in the farfnd format
        return cls._fmt_place(a.get("city", {}).get("name") or a["name"], a["countryName"], a["name"])

    # ---- route / calendar helpers (used by the "find best dates" search) ----
    def destinations(self, origin: str) -> list[dict]:
        """Airports Ryanair flies to from `origin` (routes-API format: code, name, city, country, region)."""
        return [r["arrivalAirport"] for r in self.http.get_json(ROUTES_URL.format(origin.upper()))]

    def airport(self, code: str) -> dict:
        if not hasattr(self, "_airports"):
            self._airports = {a["code"]: a for a in self.http.get_json(AIRPORTS_URL)}
        return self._airports[code.upper()]

    @classmethod
    def _routes_place(cls, a: dict) -> str:
        return cls._fmt_place(a["city"]["name"], a["country"]["name"], a["name"])

    def cheapest_per_day(self, origin: dict, dest: dict, month: date, currency: str = "EUR") -> dict[date, Offer]:
        """Cheapest fare for every day of `month` on origin->dest (airport dicts from destinations()/airport())."""
        data = self.http.get_json(CPD_URL.format(origin["code"], dest["code"]),
                                  {"outboundMonthOfDate": month.replace(day=1).isoformat(), "currency": currency})
        out = {}
        for f in data["outbound"]["fares"]:
            if f.get("price") and not f["unavailable"] and not f["soldOut"]:
                out[date.fromisoformat(f["day"])] = Offer(
                    provider=self.name, mode=self.mode, origin=origin["code"], destination=dest["code"],
                    departure=datetime.fromisoformat(f["departureDate"]), arrival=datetime.fromisoformat(f["arrivalDate"]),
                    price=f["price"]["value"], currency=f["price"]["currencyCode"],
                    origin_name=self._routes_place(origin), destination_name=self._routes_place(dest),
                    destination_country=dest["country"]["name"], raw=f)
        return out

    def _offer(self, o: dict, raw: dict) -> Offer:
        return Offer(
            provider=self.name,
            mode=self.mode,
            origin=o["departureAirport"]["iataCode"],
            destination=o["arrivalAirport"]["iataCode"],
            departure=datetime.fromisoformat(o["departureDate"]),
            arrival=datetime.fromisoformat(o["arrivalDate"]),
            price=o["price"]["value"],
            currency=o["price"]["currencyCode"],
            carrier_ref=o.get("flightNumber"),
            origin_name=self._place(o["departureAirport"]),
            destination_name=self._place(o["arrivalAirport"]),
            destination_country=o["arrivalAirport"]["countryName"],
            raw=raw,
        )

    def search_round_trip(self, origin, destination, depart, ret, currency="EUR"):
        params = {
            "departureAirportIataCode": origin.upper(),
            "outboundDepartureDateFrom": depart.isoformat(),
            "outboundDepartureDateTo": depart.isoformat(),
            "inboundDepartureDateFrom": ret.isoformat(),
            "inboundDepartureDateTo": ret.isoformat(),
            "currency": currency,
            "limit": 20,  # API rejects >20 for round trips
        }
        name = None
        if destination and len(destination) == 3:
            params["arrivalAirportIataCode"] = destination.upper()
        elif destination:
            name = destination.lower()  # free text: search anywhere, filter by city/airport name
        data = self.http.get_json(RT_URL, params)
        trips = [RoundTrip(self._offer(f["outbound"], f), self._offer(f["inbound"], f)) for f in data.get("fares", [])]
        if name:
            trips = [t for t in trips if name in json.dumps(t.out.raw["outbound"]["arrivalAirport"]).lower()]
        return sorted(trips, key=lambda t: t.price)
