from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from .config import FIRECRAWL_API_KEY, FIRECRAWL_BASE_URL
from .parsers import clean_text


class FirecrawlError(RuntimeError):
    pass


@dataclass(slots=True)
class FirecrawlScrapeResult:
    url: str
    links: list[str]
    markdown: str | None
    raw_html: str | None
    metadata: dict[str, Any]


class FirecrawlClient:
    def __init__(
        self,
        api_key: str = FIRECRAWL_API_KEY,
        base_url: str = FIRECRAWL_BASE_URL,
        timeout_seconds: int = 120,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise FirecrawlError("FIRECRAWL_API_KEY is not configured.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def scrape_page(self, url: str) -> FirecrawlScrapeResult:
        payload = {
            "url": url,
            "formats": ["rawHtml", "markdown", "links"],
            "onlyMainContent": False,
        }
        response = self._post_json("/v2/scrape", payload)
        data = response.get("data", {})
        return FirecrawlScrapeResult(
            url=url,
            links=[link for link in data.get("links", []) if isinstance(link, str)],
            markdown=data.get("markdown"),
            raw_html=data.get("rawHtml"),
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    raise FirecrawlError(f"Firecrawl transient HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                body = response.json()
                if body.get("success") is False:
                    raise FirecrawlError(f"Firecrawl error: {body}")
                return body
            except (requests.RequestException, ValueError, FirecrawlError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(2 ** attempt, 10))
        raise FirecrawlError(str(last_error) if last_error else "Unknown Firecrawl error")


def extract_candidate_listing_urls(links: list[str], allowed_domain: str = "batdongsan.com.vn") -> list[str]:
    seen: dict[str, None] = {}
    for link in links:
        if allowed_domain not in link:
            continue
        if "-pr" not in link:
            continue
        seen[link] = None
    return list(seen.keys())


def parse_listing_detail_from_firecrawl(result: FirecrawlScrapeResult) -> dict[str, object]:
    html = result.raw_html
    if not html:
        raise FirecrawlError(f"Firecrawl result for {result.url} did not include raw HTML.")

    soup = BeautifulSoup(html, "html.parser")
    info: dict[str, object] = {
        "Link": result.url,
        "Tiêu đề": _select_text(soup, ".re__pr-title"),
        "Địa chỉ": None,
        "Địa chỉ 1": None,
        "Địa chỉ 2": None,
        "Mức giá": None,
        "Giá/m²": None,
        "Số phòng ngủ": None,
        "Huyện": None,
        "Diện tích": None,
        "Mặt tiền": None,
        "Đường vào": None,
        "Hướng nhà": None,
        "Hướng ban công": None,
        "Số tầng": None,
        "Số toilet": None,
        "Pháp lý": None,
        "Ngày đăng": None,
        "Ngày hết hạn": None,
        "Loại tin": None,
        "Mã tin": None,
        "Latitude": None,
        "Longitude": None,
    }

    address_el = soup.select_one("span.re__address")
    if address_el:
        line1 = _select_text(address_el, ".re__address-line-1")
        line2 = _select_text(address_el, ".re__address-line-2")
        info["Địa chỉ 1"] = line1
        info["Địa chỉ 2"] = line2
        parts = [part for part in (line1, line2) if part]
        info["Địa chỉ"] = " | ".join(parts) if parts else clean_text(address_el.get_text(" ", strip=True))

    short_items = soup.select(".re__pr-short-info-item.js__pr-config-item")
    if not short_items:
        short_items = soup.select(".re__pr-short-info-item")
    short_map: dict[str, str | None] = {}
    for item in short_items:
        title = _select_text(item, ".title")
        value = _select_text(item, ".value")
        if title:
            short_map[title] = value
    if not info["Mức giá"]:
        info["Mức giá"] = _select_text(soup, ".re__pr-short-info-item .value")
    if not info["Giá/m²"]:
        info["Giá/m²"] = _select_text(soup, ".re__pr-short-info-item .ext")

    for key in ("Ngày đăng", "Ngày hết hạn", "Loại tin", "Mã tin"):
        if key in short_map:
            info[key] = short_map[key]

    rooms_label = soup.find(string=re.compile(r"Phòng ngủ", re.IGNORECASE))
    if rooms_label:
        parent = rooms_label.find_parent(class_="re__pr-short-info-item")
        if parent:
            info["Số phòng ngủ"] = _select_text(parent, ".value")

    breadcrumbs = soup.select(".re__breadcrumb .re__link-se")
    for crumb in breadcrumbs:
        if crumb.get("level") == "3":
            info["Huyện"] = clean_text(crumb.get_text(" ", strip=True))
            break

    iframe = soup.select_one("iframe.lazyload")
    if iframe and iframe.get("data-src"):
        data_src = iframe.get("data-src", "")
        match = re.search(r"q=([-0-9.]+),([-0-9.]+)", data_src)
        if match:
            info["Latitude"] = match.group(1)
            info["Longitude"] = match.group(2)

    for spec in soup.select(".re__pr-specs-content-item"):
        title = _select_text(spec, ".re__pr-specs-content-item-title")
        value = _select_text(spec, ".re__pr-specs-content-item-value")
        if title in info:
            info[title] = value

    if not info["Ngày đăng"]:
        info["Ngày đăng"] = _extract_labelled_markdown_value(result.markdown, "Ngày đăng")
    if not info["Ngày hết hạn"]:
        info["Ngày hết hạn"] = _extract_labelled_markdown_value(result.markdown, "Ngày hết hạn")
    if not info["Loại tin"]:
        info["Loại tin"] = _extract_labelled_markdown_value(result.markdown, "Loại tin")
    if not info["Mã tin"]:
        info["Mã tin"] = _extract_labelled_markdown_value(result.markdown, "Mã tin")

    return info


def _select_text(node: BeautifulSoup | Any, selector: str) -> str | None:
    selected = node.select_one(selector)
    if not selected:
        return None
    return clean_text(selected.get_text(" ", strip=True))


def _extract_labelled_markdown_value(markdown: str | None, label: str) -> str | None:
    if not markdown:
        return None
    pattern = rf"{re.escape(label)}\s*:?\s*(.+)"
    for line in markdown.splitlines():
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return None
