import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}


def fetch_price(url: str) -> float | None:
    domain = url.split("/")[2].lower()

    if "trendyol.com" in domain:
        return _trendyol_price(url)
    elif "hepsiburada.com" in domain:
        return _hepsiburada_price(url)
    elif "amazon." in domain:
        return _amazon_price(url)
    else:
        raise ValueError(
            f"{domain} için fiyat çıkarıcı tanımlı değil. scrapers.py dosyasına eklemelisin."
        )


def _trendyol_price(url: str) -> float | None:
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "lxml")

    price_span = soup.select_one("span.prc-dsc")
    if not price_span:
        return None
    return _parse_price_text(price_span.get_text())


def _hepsiburada_price(url: str) -> float | None:
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "lxml")

    price_span = soup.find("span", {"itemprop": "price"})
    if not price_span:
        return None
    return _parse_price_text(price_span.get_text())


def _amazon_price(url: str) -> float | None:
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "lxml")

    price_span = soup.select_one("span.a-price span.a-offscreen")
    if not price_span:
        return None
    return _parse_price_text(price_span.get_text())


def _parse_price_text(text: str) -> float | None:
    text = (text or "").strip()
    text = text.replace(".", "").replace(",", ".").replace("TL", "").replace("₺", "")
    try:
        return float(text)
    except ValueError:
        return None