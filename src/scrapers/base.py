"""Base scraper with common utilities."""

import logging
import time
import json
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, date, time as dt_time, timedelta
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..models import Screening, ScraperConfig

logger = logging.getLogger(__name__)

# Common user agent to avoid being blocked
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_with_retry(
    url: str,
    config: ScraperConfig,
    headers: Optional[dict] = None,
) -> requests.Response:
    """Fetch a URL with retry logic and exponential backoff."""
    
    default_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    if headers:
        default_headers.update(headers)
    
    last_exception = None
    for attempt in range(config.max_retries):
        try:
            response = requests.get(
                url,
                headers=default_headers,
                timeout=config.timeout,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            last_exception = e
            if attempt < config.max_retries - 1:
                delay = config.retry_delay * (2 ** attempt)
                logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
                time.sleep(delay)
    
    raise last_exception


def get_soup(url: str, config: ScraperConfig) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    response = fetch_with_retry(url, config)
    return BeautifulSoup(response.content, "lxml")


def parse_time(time_str: str) -> Optional[dt_time]:
    """Parse a time string like '7:00 PM', '7:00pm', '19:00' into a time object."""
    time_str = time_str.strip().upper().replace(" ", "")
    
    # Try various formats
    formats = [
        "%I:%M%p",   # 7:00PM
        "%I:%M %p",  # 7:00 PM
        "%I%p",      # 7PM
        "%H:%M",     # 19:00
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.time()
        except ValueError:
            continue
    
    logger.warning(f"Could not parse time: {time_str}")
    return None


def parse_runtime(runtime_str: str) -> Optional[int]:
    """Parse a runtime string like '2h 30m', '150 min', '2hrs 15mins' into minutes."""
    runtime_str = runtime_str.lower().strip()
    
    total_minutes = 0
    
    # Handle "Xhr Ymin" format
    import re
    
    # Match hours
    hours_match = re.search(r"(\d+)\s*h", runtime_str)
    if hours_match:
        total_minutes += int(hours_match.group(1)) * 60
    
    # Match minutes
    mins_match = re.search(r"(\d+)\s*m", runtime_str)
    if mins_match:
        total_minutes += int(mins_match.group(1))
    
    # Handle plain minutes like "150 min" or "150"
    if total_minutes == 0:
        plain_match = re.search(r"^(\d+)", runtime_str)
        if plain_match:
            total_minutes = int(plain_match.group(1))
    
    return total_minutes if total_minutes > 0 else None


def extract_special_attributes(text: str) -> List[str]:
    """Extract normalized special attributes from page text (format, event type).
    
    Returns a list of canonical labels such as: 35mm, 70mm, Screening on film,
    Panel discussion, Q&A, Director in person, Live musical accompaniment,
    Double feature, Premiere, New Release, etc.
    """
    if not text:
        return []
    t = text.lower()
    attrs: List[str] = []
    # Format / screening on film
    if "35mm" in t:
        attrs.append("35mm")
    if "70mm" in t:
        attrs.append("70mm")
    if "16mm" in t:
        attrs.append("16mm")
    if "screening on film" in t:
        attrs.append("Screening on film")
    if "screening on 35mm" in t or "35mm / dcp" in t:
        if "35mm" not in attrs:
            attrs.append("35mm")
    if "screening on 16mm" in t or "16mm / dcp" in t:
        if "16mm" not in attrs:
            attrs.append("16mm")
    # Event types
    if "panel discussion" in t:
        attrs.append("Panel discussion")
    if "q&a" in t or "q and a" in t:
        attrs.append("Q&A")
    if "director in person" in t or "director in-person" in t or "in person" in t:
        attrs.append("Director in person")
    if "live musical accompaniment" in t:
        attrs.append("Live musical accompaniment")
    if "double feature" in t:
        attrs.append("Double feature")
    if "premiere" in t:
        attrs.append("Premiere")
    if "new release" in t:
        attrs.append("New Release")
    if "spotlight on women" in t:
        attrs.append("Spotlight on Women")
    if "sing-along" in t or "sing along" in t:
        attrs.append("Sing-along")
    if "discussion" in t and "Panel discussion" not in attrs:
        attrs.append("Discussion")
    if "seminar" in t:
        attrs.append("Seminar")
    # Deduplicate while preserving order
    seen = set()
    out = []
    for a in attrs:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def parse_date_header(date_str: str, year: Optional[int] = None) -> Optional[date]:
    """Parse a date header like 'Thursday, January 28' or 'Jan 28'."""
    date_str = date_str.strip()
    
    # Use current year if not provided
    if year is None:
        year = datetime.now().year
    
    # Try various formats
    formats = [
        "%A, %B %d",      # Thursday, January 28
        "%A, %b %d",      # Thursday, Jan 28
        "%B %d",          # January 28
        "%b %d",          # Jan 28
        "%m/%d",          # 1/28
        "%m/%d/%Y",       # 1/28/2026
        "%Y-%m-%d",       # 2026-01-28
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If year wasn't in format, use provided year
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=year)
            return parsed.date()
        except ValueError:
            continue
    
    logger.warning(f"Could not parse date: {date_str}")
    return None


class BaseScraper(ABC):
    """Base class for all scrapers."""
    
    name: str = "base"
    base_url: str = ""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self._cache_dir = Path(config.cache_dir) / self.name
    
    @abstractmethod
    def scrape(self) -> list[Screening]:
        """Scrape screenings from the source. Must be implemented by subclasses."""
        pass
    
    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        return self._cache_dir / f"{url_hash}.html"
    
    def _get_cached(self, url: str) -> Optional[str]:
        """Get cached content for a URL if available and fresh."""
        if not self.config.use_cache:
            return None
        
        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            # Check if cache is fresh (less than 1 hour old)
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
            if datetime.now() - mtime < timedelta(hours=1):
                logger.debug(f"Using cached content for {url}")
                return cache_path.read_text(encoding="utf-8")
        
        return None
    
    def _save_cache(self, url: str, content: str):
        """Save content to cache."""
        if not self.config.use_cache:
            return
        
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self._get_cache_path(url)
        cache_path.write_text(content, encoding="utf-8")
        logger.debug(f"Cached content for {url}")
    
    def get_soup(self, url: str) -> BeautifulSoup:
        """Fetch a URL and return BeautifulSoup, with optional caching."""
        # Check cache first
        cached = self._get_cached(url)
        if cached:
            return BeautifulSoup(cached, "lxml")
        
        # Fetch fresh
        response = fetch_with_retry(url, self.config)
        content = response.text
        
        # Save to cache
        self._save_cache(url, content)
        
        return BeautifulSoup(content, "lxml")
    
    def make_absolute_url(self, url: str) -> str:
        """Convert a relative URL to absolute."""
        return urljoin(self.base_url, url)
