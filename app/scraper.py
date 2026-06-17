from bs4 import BeautifulSoup
import re
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

PINCODE = "560087"

OUT_OF_STOCK_KEYWORDS = [
    "sold out", "out of stock", "notify me", "currently unavailable",
    "not available", "soldout", "outofstock", "unavailable",
    "coming soon", "temporarily unavailable",
]

IN_STOCK_KEYWORDS = [
    "add to cart", "add to bag", "buy now", "in stock",
    "addtocart", "add_to_cart",
]


@dataclass
class ScrapeResult:
    in_stock: bool
    price: Optional[str]
    status_text: str
    error: Optional[str] = None


def detect_platform(url: str) -> str:
    if "blinkit.com" in url:
        return "blinkit"
    return "amul"


def scrape_product(url: str) -> ScrapeResult:
    platform = detect_platform(url)
    if platform == "blinkit":
        return _scrape_blinkit(url)
    return _scrape_amul(url)


def _scrape_amul(url: str) -> ScrapeResult:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Handle pincode popup if present
            try:
                pincode_input = page.locator(
                    "input[placeholder*='PINCODE'], input[placeholder*='pincode'], input[placeholder*='Pincode']"
                ).first
                pincode_input.wait_for(timeout=5000)
                pincode_input.fill(PINCODE)
                page.wait_for_timeout(1500)
                page.locator(f"text={PINCODE}").last.click()
                page.wait_for_timeout(3000)
                logger.info("Amul pincode popup dismissed with %s", PINCODE)
            except Exception:
                pass

            try:
                page.wait_for_selector("[title='Add to Cart'], .add-to-cart, .sold-out", timeout=8000)
            except Exception:
                page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_text = soup.get_text(separator=" ").lower()
        price = _extract_price(soup)

        found_in_stock = False
        found_out_of_stock = False
        out_text = ""

        for el in soup.find_all(["button", "a"]):
            el_text = el.get_text(strip=True).lower()
            if not el_text:
                continue
            disabled_val = el.get("disabled", None)
            disabled = disabled_val is not None and str(disabled_val) != "0"

            if any(kw in el_text for kw in IN_STOCK_KEYWORDS) and not disabled:
                found_in_stock = True
            elif any(kw in el_text for kw in OUT_OF_STOCK_KEYWORDS):
                found_out_of_stock = True
                out_text = el_text
            elif disabled and any(kw in el_text for kw in IN_STOCK_KEYWORDS):
                found_out_of_stock = True
                out_text = el_text

        logger.info("Amul scrape %s — in_stock=%s out_stock=%s price=%s", url, found_in_stock, found_out_of_stock, price)

        if found_in_stock:
            return ScrapeResult(in_stock=True, price=price, status_text="add to cart")
        if found_out_of_stock:
            return ScrapeResult(in_stock=False, price=price, status_text=out_text or "sold out")

        for kw in IN_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=True, price=price, status_text=kw)
        for kw in OUT_OF_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=False, price=price, status_text=kw)

        return ScrapeResult(in_stock=False, price=price, status_text="unknown")

    except Exception as e:
        logger.exception("Amul scrape failed for %s", url)
        return ScrapeResult(in_stock=False, price=None, status_text="error", error=str(e))


def _scrape_blinkit(url: str) -> ScrapeResult:
    """
    Blinkit serves full SSR HTML — no Playwright needed.
    Stock logic (position-based):
    - In stock     -> "add to cart" appears before any "out of stock" in page HTML
    - Out of stock -> "out of stock" appears before "add to cart"
    Product status is always near the top; recommendations/suggestions come later,
    so first-occurrence position reliably identifies the product's own status.
    """
    try:
        import requests as _requests
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        resp = _requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        soup = BeautifulSoup(html, "lxml")
        price = _extract_price(soup)

        # Work on raw HTML (lowercase) for position-based detection
        # Using raw HTML rather than soup.get_text() preserves relative positions
        html_lower = html.lower()

        pos_add = html_lower.find("add to cart")
        pos_out = min(
            (html_lower.find(kw) for kw in ["out of stock", "sold out", "currently unavailable"] if html_lower.find(kw) != -1),
            default=-1,
        )

        logger.info("Blinkit scrape %s — pos_add=%s pos_out=%s price=%s", url, pos_add, pos_out, price)

        if pos_add != -1 and (pos_out == -1 or pos_add < pos_out):
            return ScrapeResult(in_stock=True, price=price, status_text="add to cart")
        if pos_out != -1:
            return ScrapeResult(in_stock=False, price=price, status_text="out of stock")

        return ScrapeResult(in_stock=False, price=price, status_text="unknown")

    except Exception as e:
        logger.exception("Blinkit scrape failed for %s", url)
        return ScrapeResult(in_stock=False, price=None, status_text="error", error=str(e))


def _extract_price(soup: BeautifulSoup) -> Optional[str]:
    price_patterns = [
        r"(?:MRP\s*[₹$£€]?\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:INR\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:[₹$£€]\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:Rs\.?\s*)([\d,]+(?:\.\d{1,2})?)",
    ]
    text = soup.get_text(separator=" ")
    for pattern in price_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"₹{match.group(1)}"

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            import json
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    p = offers.get("price") or offers.get("lowPrice")
                    currency = offers.get("priceCurrency", "INR")
                    if p:
                        return f"{'₹' if currency == 'INR' else currency}{p}"
        except Exception:
            pass
    return None
