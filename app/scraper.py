import requests
import cloudscraper
from bs4 import BeautifulSoup
import re
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Cache-Control": "max-age=0",
}

# Keywords that indicate OUT OF STOCK
OUT_OF_STOCK_KEYWORDS = [
    "sold out", "out of stock", "notify me", "currently unavailable",
    "not available", "soldout", "outofstock", "unavailable",
    "coming soon", "temporarily unavailable",
]

# Keywords that indicate IN STOCK
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


def scrape_product(url: str) -> ScrapeResult:
    try:
        # cloudscraper bypasses Cloudflare JS challenges
        session = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove script/style noise
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_text = soup.get_text(separator=" ").lower()
        price = _extract_price(soup, resp.text)

        # Scan ALL buttons and collect signals — don't stop at first match.
        # Related/recommended products on the same page can have "Sold Out" buttons
        # that appear before the main product's "Add to Cart", causing false negatives.
        found_in_stock = False
        found_out_of_stock = False
        out_text = ""

        for btn in soup.find_all("button"):
            btn_text = btn.get_text(strip=True).lower()
            disabled = btn.has_attr("disabled")
            if any(kw in btn_text for kw in IN_STOCK_KEYWORDS) and not disabled:
                found_in_stock = True
            elif any(kw in btn_text for kw in OUT_OF_STOCK_KEYWORDS) or disabled:
                found_out_of_stock = True
                out_text = btn_text

        # In-stock wins if ANY active "Add to Cart" button exists
        logger.info("Scrape %s — in_stock_btn=%s out_stock_btn=%s price=%s", url, found_in_stock, found_out_of_stock, price)
        if not found_in_stock and not found_out_of_stock:
            logger.warning("No stock buttons found. Page snippet: %s", page_text[:300])
        if found_in_stock:
            return ScrapeResult(in_stock=True, price=price, status_text="add to cart")
        if found_out_of_stock:
            return ScrapeResult(in_stock=False, price=price, status_text=out_text or "sold out")

        # Fallback: scan page text — in_stock check first
        for kw in IN_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=True, price=price, status_text=kw)

        for kw in OUT_OF_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=False, price=price, status_text=kw)

        # Check meta tags (some sites embed availability)
        availability_meta = soup.find("meta", {"property": "product:availability"}) or \
                            soup.find("meta", {"name": "availability"})
        if availability_meta:
            content = availability_meta.get("content", "").lower()
            if "in stock" in content:
                return ScrapeResult(in_stock=True, price=price, status_text=content)
            if "out" in content:
                return ScrapeResult(in_stock=False, price=price, status_text=content)

        return ScrapeResult(in_stock=False, price=price, status_text="unknown — could not determine")

    except requests.exceptions.Timeout:
        return ScrapeResult(in_stock=False, price=None, status_text="error", error="Request timed out")
    except requests.exceptions.HTTPError as e:
        return ScrapeResult(in_stock=False, price=None, status_text="error", error=f"HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("Scrape failed for %s", url)
        return ScrapeResult(in_stock=False, price=None, status_text="error", error=str(e))


def _extract_price(soup: BeautifulSoup, raw_html: str) -> Optional[str]:
    # StoreHippo / Amul pattern: "MRP₹900" or "INR900"
    price_patterns = [
        r"(?:MRP\s*[₹$£€]?\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:INR\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:[₹$£€]\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:Rs\.?\s*)([\d,]+(?:\.\d{1,2})?)",
        r"(?:Price[:\s]+)([\d,]+(?:\.\d{1,2})?)",
    ]
    text = soup.get_text(separator=" ")
    for pattern in price_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"₹{match.group(1)}"

    # JSON-LD structured data
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            import json
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                    currency = offers.get("priceCurrency", "INR")
                    if price:
                        symbol = "₹" if currency == "INR" else currency
                        return f"{symbol}{price}"
        except Exception:
            pass

    return None
