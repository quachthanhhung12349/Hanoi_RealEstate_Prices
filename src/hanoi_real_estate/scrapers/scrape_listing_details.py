from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium.webdriver.common.by import By

from ..parsers import clean_text, normalize_detail_payload
from ..repository import fetch_pending_listing_urls, mark_listing_failed, save_listing_detail
from .common import create_driver, is_rate_limited_error, sleep_jitter, wait_for_listing_details


def get_text_or_none(parent, selector: str) -> str | None:
    try:
        return clean_text(parent.find_element(By.CSS_SELECTOR, selector).text)
    except Exception:
        return None


def extract_address(driver) -> str | None:
    try:
        address_el = driver.find_element(By.CSS_SELECTOR, "span.re__address")
        line1 = get_text_or_none(address_el, ".re__address-line-1")
        line2 = get_text_or_none(address_el, ".re__address-line-2")
        parts = [part for part in (line1, line2) if part]
        return " | ".join(parts) if parts else clean_text(address_el.text)
    except Exception:
        return None


def extract_short_info_map(driver) -> dict[str, str | None]:
    data: dict[str, str | None] = {}
    items = driver.find_elements(By.CSS_SELECTOR, ".re__pr-short-info-item.js__pr-config-item")
    if not items:
        items = driver.find_elements(By.CSS_SELECTOR, ".re__pr-short-info-item")
    for item in items:
        try:
            title = get_text_or_none(item, ".title")
            value = get_text_or_none(item, ".value")
            if title:
                data[title] = value
        except Exception:
            continue
    return data


def extract_property_info(driver, url: str) -> dict[str, object]:
    driver.get(url)
    wait_for_listing_details(driver, timeout=90)
    info: dict[str, object] = {
        "Link": url,
        "Tiêu đề": None,
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

    try:
        info["Tiêu đề"] = clean_text(driver.find_element(By.CLASS_NAME, "re__pr-title").text)
    except Exception:
        pass

    try:
        address_el = driver.find_element(By.CSS_SELECTOR, "span.re__address")
        info["Địa chỉ 1"] = get_text_or_none(address_el, ".re__address-line-1")
        info["Địa chỉ 2"] = get_text_or_none(address_el, ".re__address-line-2")
        info["Địa chỉ"] = extract_address(driver)
    except Exception:
        pass

    try:
        info["Mức giá"] = clean_text(driver.find_element(By.CSS_SELECTOR, ".re__pr-short-info-item .value").text)
        info["Giá/m²"] = clean_text(driver.find_element(By.CSS_SELECTOR, ".re__pr-short-info-item .ext").text)
    except Exception:
        pass

    try:
        rooms_element = driver.find_element(
            By.XPATH,
            "//div[contains(@class, 're__pr-short-info-item') and .//span[contains(text(), 'Phòng ngủ')]]//span[@class='value']",
        )
        info["Số phòng ngủ"] = clean_text(rooms_element.text)
    except Exception:
        pass

    try:
        breadcrumbs = driver.find_elements(By.CSS_SELECTOR, ".re__breadcrumb .re__link-se")
        info["Huyện"] = next(
            (clean_text(b.text) for b in breadcrumbs if b.get_attribute("level") == "3"),
            None,
        )
    except Exception:
        pass

    try:
        iframe_element = driver.find_element(By.CSS_SELECTOR, "iframe.lazyload")
        data_src = iframe_element.get_attribute("data-src")
        coords = data_src.split("q=")[1].split(",")
        info["Latitude"] = clean_text(coords[0])
        info["Longitude"] = clean_text(coords[1].split("&")[0])
    except Exception:
        pass

    short_info = extract_short_info_map(driver)
    for key in ("Ngày đăng", "Ngày hết hạn", "Loại tin", "Mã tin"):
        if key in short_info:
            info[key] = short_info[key]

    for spec in driver.find_elements(By.CLASS_NAME, "re__pr-specs-content-item"):
        try:
            title = clean_text(spec.find_element(By.CLASS_NAME, "re__pr-specs-content-item-title").text)
            value = clean_text(spec.find_element(By.CLASS_NAME, "re__pr-specs-content-item-value").text)
            if title in info:
                info[title] = value
        except Exception:
            continue

    return info


def scrape_one(
    url: str,
    worker_id: int = 0,
    max_retries: int = 3,
    headless: bool = False,
) -> dict[str, object]:
    driver = create_driver(headless=headless)
    try:
        for attempt in range(1, max_retries + 1):
            try:
                sleep_jitter(2.0, 5.0)
                return extract_property_info(driver, url)
            except Exception as exc:
                if attempt >= max_retries or not is_rate_limited_error(exc):
                    raise
                backoff = (2 ** attempt) + worker_id
                print(f"Worker {worker_id}: rate limit on {url}, retrying in {backoff}s")
                time.sleep(backoff)
        raise RuntimeError(f"Failed to scrape listing after {max_retries} attempts: {url}")
    finally:
        driver.quit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape listing details into SQLite")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument("--batch-limit", type=int, default=1, help="How many fetch/process batches to run before exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = time.time()
    done = 0
    for batch_number in range(1, max(1, args.batch_limit) + 1):
        rows = fetch_pending_listing_urls(limit=args.limit)
        if not rows:
            if done == 0:
                print("No pending listings to scrape.")
            break

        print(f"Starting detail batch {batch_number} with {len(rows)} listings")
        with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
            future_to_row = {
                executor.submit(
                    scrape_one,
                    row["url"],
                    worker_id=index,
                    max_retries=args.max_retries,
                    headless=args.headless,
                ): row
                for index, row in enumerate(rows)
            }
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                listing_id = row["listing_id"]
                url = row["url"]
                try:
                    raw = future.result()
                    payload = normalize_detail_payload(raw)
                    save_listing_detail(payload)
                    print(f"OK {listing_id} {url}")
                except Exception as exc:
                    mark_listing_failed(listing_id, type(exc).__name__, str(exc))
                    print(f"FAIL {listing_id} {url}: {exc}")
                finally:
                    done += 1

    print(f"Processed {done} listings in {time.time() - started_at:.1f}s")


if __name__ == "__main__":
    main()
