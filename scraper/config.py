from dataclasses import dataclass


@dataclass(frozen=True)
class Origin:
    label: str
    iata: str


ORIGINS = [
    Origin("Pisa Airport", "PSA"),
    Origin("Firenze Peretola", "FLR"),
]

# Providers queried by the UI
PROVIDERS = ["ryanair"]

# Destinations in these countries are ignored by the cheap-fares search
EXCLUDE_COUNTRIES = {"Italy"}
