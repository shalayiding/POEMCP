import time

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://poedb.tw/us"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
CACHE_TTL = 3600  # 1 hour


def fetch_page(url: str) -> BeautifulSoup:
    """Fetch a poedb.tw page and return parsed HTML."""
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    # Replace em-dash with hyphen for better terminal compatibility
    text = resp.text.replace("\u2014", "-")
    return BeautifulSoup(text, "html.parser")


class Cache:
    """Simple in-memory cache with TTL."""

    def __init__(self) -> None:
        self._data: dict | None = None
        self._timestamp: float = 0

    def get(self) -> dict | None:
        if self._data and (time.time() - self._timestamp) < CACHE_TTL:
            return self._data
        return None

    def set(self, data: dict) -> None:
        self._data = data
        self._timestamp = time.time()
