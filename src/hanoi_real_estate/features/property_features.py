from __future__ import annotations

import re
from typing import Any

import pandas as pd

from hanoi_real_estate.parsers import clean_text


PROPERTY_TYPE_LAND = "Đất"
PROPERTY_TYPE_HOUSE = "Nhà"
PROPERTY_TYPE_MINI_APARTMENT = "Căn hộ dịch vụ/Chung cư Mini"
PROPERTY_TYPE_UNKNOWN = "Khác/Chưa rõ"

PROPERTY_TYPE_CHOICES = [
    PROPERTY_TYPE_LAND,
    PROPERTY_TYPE_HOUSE,
    PROPERTY_TYPE_MINI_APARTMENT,
    PROPERTY_TYPE_UNKNOWN,
]

_LAND_PATTERN = re.compile(
    r"\b(đất|dat|lô đất|lo dat|thổ cư|tho cu|đất nền|dat nen|mảnh đất|manh dat|đất dịch vụ|dat dich vu)\b",
    flags=re.IGNORECASE,
)
_MINI_APARTMENT_PATTERN = re.compile(
    r"\b(căn hộ dịch vụ|can ho dich vu|chung cư mini|chung cu mini|cc mini|chdv|apartment service)\b",
    flags=re.IGNORECASE,
)
_HOUSE_PATTERN = re.compile(
    r"\b(nhà|nha|nhà riêng|nha rieng|biệt thự|biet thu|liền kề|lien ke|shophouse|villa)\b",
    flags=re.IGNORECASE,
)


def add_property_type_features(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working["Loại BĐS"] = working.apply(infer_property_type_from_row, axis=1)
    working["is_land_listing"] = working["Loại BĐS"].eq(PROPERTY_TYPE_LAND).astype(int)
    return working


def infer_property_type_from_row(row: pd.Series) -> str:
    candidates = [
        row.get("Loại BĐS"),
        row.get("listing_type"),
        row.get("title"),
        row.get("Tiêu đề"),
        row.get("full_address"),
        row.get("Địa chỉ"),
    ]
    return infer_property_type(*candidates)


def infer_property_type(*values: Any) -> str:
    normalized_text = " | ".join(text for text in (_normalize_property_hint(value) for value in values) if text)
    if not normalized_text:
        return PROPERTY_TYPE_UNKNOWN

    if _MINI_APARTMENT_PATTERN.search(normalized_text):
        return PROPERTY_TYPE_MINI_APARTMENT
    if _LAND_PATTERN.search(normalized_text):
        return PROPERTY_TYPE_LAND
    if _HOUSE_PATTERN.search(normalized_text):
        return PROPERTY_TYPE_HOUSE

    if "ban-dat" in normalized_text:
        return PROPERTY_TYPE_LAND
    if "ban-can-ho" in normalized_text:
        return PROPERTY_TYPE_MINI_APARTMENT
    if "ban-nha" in normalized_text:
        return PROPERTY_TYPE_HOUSE
    return PROPERTY_TYPE_UNKNOWN


def property_type_is_land(value: Any) -> bool:
    return clean_text(value) == PROPERTY_TYPE_LAND


def null_house_only_fields_for_land(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "Loại BĐS" not in working.columns:
        return working
    land_mask = working["Loại BĐS"].eq(PROPERTY_TYPE_LAND)
    for column in ["Số phòng ngủ", "Số tầng", "Số toilet"]:
        if column in working.columns:
            working.loc[land_mask, column] = pd.NA
    return working


def _normalize_property_hint(value: Any) -> str:
    text = clean_text(value)
    if text is None:
        return ""
    return text.casefold()
