from __future__ import annotations

import random
import threading
import time

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from ..config import CHROME_BINARY

# undetected_chromedriver copies a single chromedriver.exe to a fixed path on
# Windows; concurrent calls race to rename that file and raise WinError 32/183.
_driver_creation_lock = threading.Lock()


def is_rate_limited_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in ("403", "forbidden", "access denied", "blocked"))


def create_driver(headless: bool = False):
    options = uc.ChromeOptions()
    options.binary_location = CHROME_BINARY
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1200")
    if headless:
        options.add_argument("--headless=new")
    options.page_load_strategy = "normal"
    with _driver_creation_lock:
        return uc.Chrome(options=options)


def sleep_jitter(min_seconds: float = 2.0, max_seconds: float = 5.0) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


def wait_for_listing_cards(driver, timeout: int = 10) -> None:
    selectors = [
        (By.CLASS_NAME, "js__product-link-for-product-id"),
        (By.CSS_SELECTOR, "a.js__product-link-for-product-id"),
        (By.CSS_SELECTOR, "a.re__link-se[href*='batdongsan.com.vn']"),
    ]
    end_time = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < end_time:
        for selector in selectors:
            if has_elements(driver, *selector):
                return
        if is_cloudflare_challenge(driver):
            print("Cloudflare challenge detected on listing page. Waiting for it to clear...")
            time.sleep(3)
            continue
        for selector in selectors:
            try:
                WebDriverWait(driver, 2).until(EC.presence_of_element_located(selector))
                return
            except TimeoutException as exc:
                last_error = exc
        time.sleep(1)
    raise TimeoutException(str(last_error) if last_error else "Timed out waiting for listing cards")


def wait_for_listing_details(driver, timeout: int = 10) -> None:
    end_time = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < end_time:
        if has_elements(driver, By.CLASS_NAME, "re__pr-specs-content-item-value"):
            return
        if is_cloudflare_challenge(driver):
            print("Cloudflare challenge detected on detail page. Waiting for it to clear...")
            time.sleep(3)
            continue
        try:
            WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.CLASS_NAME, "re__pr-specs-content-item-value"))
            )
            return
        except TimeoutException as exc:
            last_error = exc
            time.sleep(1)
    raise TimeoutException(str(last_error) if last_error else "Timed out waiting for listing details")


def is_cloudflare_challenge(driver) -> bool:
    if has_elements(driver, By.CLASS_NAME, "js__product-link-for-product-id"):
        return False
    if has_elements(driver, By.CLASS_NAME, "re__pr-specs-content-item-value"):
        return False

    try:
        title = (driver.title or "").strip().lower()
    except Exception:
        title = ""
    if "just a moment" in title:
        return True

    try:
        current_url = (driver.current_url or "").lower()
    except Exception:
        current_url = ""
    if "__cf_chl" in current_url:
        return True

    try:
        body_text = (driver.find_element(By.TAG_NAME, "body").text or "").strip().lower()
    except Exception:
        body_text = ""

    if not body_text:
        return False

    challenge_markers = (
        "enable javascript and cookies to continue",
        "verify you are human",
        "checking your browser before accessing",
        "just a moment",
    )
    return any(marker in body_text for marker in challenge_markers)


def has_elements(driver, by: str, value: str) -> bool:
    try:
        return len(driver.find_elements(by, value)) > 0
    except Exception:
        return False
