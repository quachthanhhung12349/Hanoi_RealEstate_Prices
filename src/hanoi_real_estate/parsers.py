"""Parsing and normalization helpers extracted from notebooks."""

from __future__ import annotations

import math
import re
from datetime import datetime
from hashlib import sha1


FULL_PRICE_UNITS = {"ty", "trieu", "nghin"}
SQM_PRICE_UNITS = {"ty_m2", "trieu_m2", "nghin_m2"}


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "null", "n/a"}


def clean_text(value: object) -> str | None:
    if is_missing(value):
        return None
    text = " ".join(str(value).replace("\xa0", " ").split())
    return text or None


def parse_price(value: object) -> tuple[float | None, str | None]:
    text = clean_text(value)
    if text is None:
        return None, None

    normalized = text.lower()
    if normalized in {"thoả thuận", "thỏa thuận"}:
        return None, None

    normalized = normalized.replace("~", "").replace(" ", "")
    normalized = normalized.replace("triệu/m²", "trieu/m2")
    normalized = normalized.replace("triệu/m2", "trieu/m2")
    normalized = normalized.replace("nghìn/m²", "nghin/m2")
    normalized = normalized.replace("nghìn/m2", "nghin/m2")
    normalized = normalized.replace("tỷ/m²", "ty/m2")
    normalized = normalized.replace("tỷ/m2", "ty/m2")
    normalized = normalized.replace("tỷđồng", "ty")
    normalized = normalized.replace("triệu", "trieu")
    normalized = normalized.replace("nghìn", "nghin")
    normalized = normalized.replace("tỷ", "ty")

    for pattern, unit in (
        (r"([\d.,]+)(?=ty/m2)", "ty_m2"),
        (r"([\d.,]+)(?=trieu/m2)", "trieu_m2"),
        (r"([\d.,]+)(?=nghin/m2)", "nghin_m2"),
        (r"([\d.,]+)(?=ty)", "ty"),
        (r"([\d.,]+)(?=trieu)", "trieu"),
        (r"([\d.,]+)(?=nghin)", "nghin"),
    ):
        match = re.search(pattern, normalized)
        if match:
            return _parse_number_token(match.group(1)), unit

    match = re.search(r"[\d.,]+", normalized)
    if match:
        return _parse_number_token(match.group(0)), None
    return None, None


def normalize_price(value: float | None, unit: str | None, target: str) -> float | None:
    if value is None:
        return None

    if target == "ty":
        if unit == "ty":
            return value
        if unit == "trieu":
            return value / 1000.0
        if unit == "nghin":
            return value / 1_000_000.0
        return value

    if target == "vnd":
        billion = normalize_price(value, unit, "ty")
        return None if billion is None else billion * 1_000_000_000.0

    if target == "trieu_m2":
        if unit == "ty_m2":
            return value * 1000.0
        if unit == "trieu_m2":
            return value
        if unit == "nghin_m2":
            return value / 1000.0
        return value

    return value


def normalize_price_pair(price_raw: object, price_per_m2_raw: object) -> tuple[float | None, float | None]:
    price_val, price_unit = parse_price(price_raw)
    unit_val, unit_unit = parse_price(price_per_m2_raw)

    if price_unit in SQM_PRICE_UNITS and unit_unit in FULL_PRICE_UNITS:
        price_val, unit_val = unit_val, price_val
        price_unit, unit_unit = unit_unit, price_unit

    total_price_vnd = normalize_price(price_val, price_unit, "vnd")
    price_per_m2_million = normalize_price(unit_val, unit_unit, "trieu_m2")
    return total_price_vnd, price_per_m2_million


def parse_float_metric(value: object) -> float | None:
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"[\d.,]+", text)
    if not match:
        return None
    return _parse_measurement_token(match.group(0))


def parse_int_metric(value: object) -> int | None:
    number = parse_float_metric(value)
    return None if number is None else int(round(number))


def parse_date_ddmmyyyy(value: object) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.strptime(text, "%d/%m/%Y")
    except ValueError:
        return None
    return parsed.date().isoformat()


def extract_listing_id(url: str, fallback: object = None) -> str | None:
    fallback_text = clean_text(fallback)
    if fallback_text:
        return fallback_text
    match = re.search(r"-pr(\d+)", url)
    if match:
        return match.group(1)
    return None


def infer_listing_type_from_url(url: str) -> str | None:
    text = clean_text(url)
    if text is None:
        return None
    path = text.lower()
    if "/ban-dat" in path:
        return "ban-dat"
    if "/ban-nha-rieng" in path:
        return "ban-nha-rieng"
    if "/ban-can-ho" in path:
        return "ban-can-ho"
    return None


def split_address_fields(address_line_1: object, address_line_2: object, full_address: object) -> dict[str, str | None]:
    line_1 = clean_text(address_line_1)
    line_2 = clean_text(address_line_2)
    full = clean_text(full_address)
    base_text = line_1 or full

    ward = _extract_last_named_segment(base_text, ("Phường", "Xã", "Thị trấn"))
    district = _extract_last_named_segment(base_text, ("Quận", "Huyện", "Thị xã"))
    city = _extract_city(base_text)

    return {
        "full_address": full,
        "address_line_1": line_1,
        "address_line_2": line_2,
        "ward": ward,
        "district": district,
        "city": city,
    }


def build_content_hash(payload: dict[str, object]) -> str:
    ordered = [f"{key}={clean_text(value) or ''}" for key, value in sorted(payload.items())]
    return sha1("|".join(ordered).encode("utf-8")).hexdigest()


def normalize_detail_payload(raw: dict[str, object]) -> dict[str, object]:
    url = clean_text(raw.get("Link"))
    if url is None:
        raise ValueError("Missing listing URL in scraped payload")

    listing_id = extract_listing_id(url, raw.get("Mã tin"))
    if listing_id is None:
        raise ValueError(f"Could not infer listing_id from URL: {url}")

    price_vnd, price_per_m2_million = normalize_price_pair(raw.get("Mức giá"), raw.get("Giá/m²"))
    address_fields = split_address_fields(raw.get("Địa chỉ 1"), raw.get("Địa chỉ 2"), raw.get("Địa chỉ"))

    listing_current = {
        "listing_id": listing_id,
        "title": clean_text(raw.get("Tiêu đề")),
        "title_normalized": _normalize_title(raw.get("Tiêu đề")),
        "price_raw": clean_text(raw.get("Mức giá")),
        "price_value_vnd": price_vnd,
        "price_value_billion_vnd": None if price_vnd is None else price_vnd / 1_000_000_000.0,
        "price_per_m2_raw": clean_text(raw.get("Giá/m²")),
        "price_per_m2_value_million_vnd": price_per_m2_million,
        "bedrooms": clean_text(raw.get("Số phòng ngủ")),
        "area_raw": clean_text(raw.get("Diện tích")),
        "area_m2": parse_float_metric(raw.get("Diện tích")),
        "front_length_m": parse_float_metric(raw.get("Mặt tiền")),
        "road_size_m": parse_float_metric(raw.get("Đường vào")),
        "direction": clean_text(raw.get("Hướng nhà")),
        "balcony_direction": clean_text(raw.get("Hướng ban công")),
        "floors": parse_int_metric(raw.get("Số tầng")),
        "toilets": parse_int_metric(raw.get("Số toilet")),
        "legal_status": clean_text(raw.get("Pháp lý")),
        "published_at": parse_date_ddmmyyyy(raw.get("Ngày đăng")),
        "expired_at": parse_date_ddmmyyyy(raw.get("Ngày hết hạn")),
        "ad_type": clean_text(raw.get("Loại tin")),
        "raw_district": clean_text(raw.get("Huyện")),
    }
    listing_current["content_hash"] = build_content_hash(listing_current)

    address = {
        "listing_id": listing_id,
        **address_fields,
        "latitude": parse_float_metric(raw.get("Latitude")),
        "longitude": parse_float_metric(raw.get("Longitude")),
        "location_source": "listing_page",
        "last_geocoded_at": None,
    }

    listing = {
        "listing_id": listing_id,
        "url": url,
        "listing_type": infer_listing_type_from_url(url),
        "status": "done",
        "is_active": 1,
    }

    history = {
        "listing_id": listing_id,
        "price_raw": listing_current["price_raw"],
        "price_value_vnd": listing_current["price_value_vnd"],
        "price_per_m2_raw": listing_current["price_per_m2_raw"],
        "price_per_m2_value_million_vnd": listing_current["price_per_m2_value_million_vnd"],
        "expired_at": listing_current["expired_at"],
        "ad_type": listing_current["ad_type"],
        "is_active": 1,
        "content_hash": listing_current["content_hash"],
    }

    return {
        "listing": listing,
        "listing_current": listing_current,
        "address": address,
        "history": history,
    }


def _parse_number_token(token: str) -> float | None:
    try:
        return float(token.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_measurement_token(token: str) -> float | None:
    normalized = token.strip()
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _extract_last_named_segment(text: str | None, prefixes: tuple[str, ...]) -> str | None:
    if text is None:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    matches = [part for part in parts if part.startswith(prefixes)]
    return matches[-1] if matches else None


def _extract_city(text: str | None) -> str | None:
    if text is None:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    for part in reversed(parts):
        if "hà nội" in part.lower():
            return part
    return parts[-1] if parts else None


def _normalize_title(value: object) -> str | None:
    text = clean_text(value)
    return text.lower() if text else None
