import requests
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

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


def scrape_product(url: str) -> ScrapeResult:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_text = soup.get_text(separator=" ").lower()
        price = _extract_price(soup)

        found_in_stock = False
        found_out_of_stock = False
        out_text = ""

        # Check both <button> and <a> tags — Amul uses <a class="add-to-cart">
        for el in soup.find_all(["button", "a"]):
            el_text = el.get_text(strip=True).lower()
            if not el_text:
                continue
            # disabled="0" means NOT disabled — only treat as disabled if value is not "0"
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

        logger.info("Scrape %s — in_stock_btn=%s out_stock_btn=%s price=%s", url, found_in_stock, found_out_of_stock, price)

        if not found_in_stock and not found_out_of_stock:
            logger.warning("No stock buttons found. Page snippet: %s", page_text[:300])

        # in_stock wins if ANY active Add to Cart exists
        if found_in_stock:
            return ScrapeResult(in_stock=True, price=price, status_text="add to cart")
        if found_out_of_stock:
            return ScrapeResult(in_stock=False, price=price, status_text=out_text or "sold out")

        # Fallback: page text
        for kw in IN_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=True, price=price, status_text=kw)
        for kw in OUT_OF_STOCK_KEYWORDS:
            if kw in page_text:
                return ScrapeResult(in_stock=False, price=price, status_text=kw)

        return ScrapeResult(in_stock=False, price=price, status_text="unknown")

    except requests.exceptions.Timeout:
        return ScrapeResult(in_stock=False, price=None, status_text="error", error="Request timed out")
    except requests.exceptions.HTTPError as e:
        return ScrapeResult(in_stock=False, price=None, status_text="error", error=f"HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("Scrape failed for %s", url)
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
