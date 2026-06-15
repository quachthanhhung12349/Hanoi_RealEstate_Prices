from dataclasses import dataclass
from datetime import datetime


@dataclass
class ListingRecord:
    listing_id: str
    url: str
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    status: str = "new"


@dataclass
class AddressRecord:
    listing_id: str
    full_address: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    ward: str | None = None
    district: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None

