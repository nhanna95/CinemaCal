"""Scraper for Harvard Film Archive (harvardfilmarchive.org)."""

import logging
import re
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from bs4 import BeautifulSoup

from ..models import Screening, ScraperConfig
from .base import BaseScraper, parse_time, extract_special_attributes

logger = logging.getLogger(__name__)

# Day and month names for date parsing
DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
)
MONTHS = set(MONTH_NAMES)
MONTH_TO_NUM = {m: i + 1 for i, m in enumerate(MONTH_NAMES)}


class HarvardFilmArchiveScraper(BaseScraper):
    """Scraper for Harvard Film Archive."""

    name = "harvard_film_archive"
    base_url = "https://harvardfilmarchive.org/"
    calendar_url = "https://harvardfilmarchive.org/calendar"
    venue_name = "Harvard Film Archive"

    SKIP = {
        "menu", "public cinema", "calendar", "film series",
        "collections", "conversations", "online exhibits", "contact",
        "privacy policy", "digital accessibility", "newsletter", "copyright",
        "director in person", "live musical accompaniment", "screening on film",
        "families", "teens", "streaming", "new 35mm print",
        "screening on 16mm / dcp", "screening on 35mm / dcp",
        "date", "from", "to", "filters", "read more", "view more", "current programs",
        "harvard college", ".",
    }

    def scrape(self) -> list[Screening]:
        """Scrape all screenings from HFA using date range and pagination."""
        screenings = []
        self._runtime_cache: Dict[str, Optional[int]] = {}
        self._detail_attrs_cache: Dict[str, List[str]] = {}

        try:
            start_str = self.config.start_date.strftime("%Y-%m-%d")
            end_str = self.config.end_date.strftime("%Y-%m-%d")
            year = datetime.now().year

            page = 1
            while True:
                url = f"{self.calendar_url}?from={start_str}&to={end_str}"
                if page > 1:
                    url += f"&page={page}"

                soup = self.get_soup(url)
                page_events = self._parse_calendar_page(soup, year)

                if not page_events and page == 1:
                    break

                for ev in page_events:
                    if not (self.config.start_date <= ev["date"] <= self.config.end_date):
                        continue
                    detail_url = ev.get("detail_url")
                    runtime = None
                    special_attributes = list(ev.get("special_attributes") or [])
                    if detail_url:
                        runtime, detail_attrs = self._get_runtime_and_attrs_for_detail_url(detail_url)
                        if detail_attrs:
                            for a in detail_attrs:
                                if a not in special_attributes:
                                    special_attributes.append(a)
                            if any(x in special_attributes for x in ("35mm", "16mm", "70mm")):
                                special_attributes = [a for a in special_attributes if a != "Screening on film"]
                    screenings.append(Screening(
                        title=ev["title"],
                        venue=self.venue_name,
                        date=ev["date"],
                        time=ev["time"],
                        source_url=self.calendar_url,
                        source_site="Harvard Film Archive",
                        director=ev.get("director"),
                        year=ev.get("year"),
                        extra=ev.get("series"),
                        runtime_minutes=runtime,
                        special_attributes=special_attributes or None,
                    ))

                logger.debug(f"HFA page {page}: Found {len(page_events)} events")

                if not self._has_more_pages(soup):
                    break

                page += 1
                if page > 20:
                    logger.warning("HFA: Hit pagination safety limit")
                    break

            logger.info(f"Harvard Film Archive: Found {len(screenings)} total screenings")

        except Exception as e:
            logger.error(f"Harvard Film Archive scraping failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        return screenings

    def _has_more_pages(self, soup: BeautifulSoup) -> bool:
        view_more = soup.find("a", string=re.compile(r"view\s*more", re.I))
        if view_more:
            return True
        return bool(soup.find("a", href=re.compile(r"page=\d+")))

    def _parse_calendar_page(self, soup: BeautifulSoup, year: int) -> list[Dict[str, Any]]:
        """Parse HFA calendar via DOM. Returns list of dicts with date, time, title, director, year, series, detail_url."""
        events: List[Dict[str, Any]] = []
        spots = soup.find_all(class_=lambda c: c and "m-calendar__spot" in str(c))
        current_date: Optional[date] = None

        for s in spots:
            classes = s.get("class") or []
            cstr = " ".join(classes)

            if "m-calendar__spot--day" in cstr:
                text = (s.get_text() or "").strip()
                # "Friday30January" or "Saturday31January" – day/month letters only to avoid \w matching digits
                mobj = re.search(r"([a-zA-Z]+)\s*(\d{1,2})\s*([a-zA-Z]+)", text, re.I)
                if mobj:
                    day_name, num_str, month_str = mobj.group(1), mobj.group(2), mobj.group(3)
                    if day_name.lower() in DAYS and num_str.isdigit() and month_str.lower() in MONTH_TO_NUM:
                        try:
                            d, m = int(num_str), MONTH_TO_NUM[month_str.lower()]
                            current_date = date(year, m, d)
                            if current_date.month < date.today().month - 6:
                                current_date = current_date.replace(year=year + 1)
                        except (ValueError, KeyError):
                            pass
                continue

            if "m-calendar__spot--event" not in cstr or current_date is None:
                continue

            link = s.find("a", href=lambda h: h and "/calendar/" in str(h) and "programs" not in str(h) and "page=" not in str(h))
            detail_url = self.make_absolute_url(link["href"]) if link and link.get("href") else None

            time_el = s.find("time") or s.find(string=re.compile(r"\d{1,2}:\d{2}\s*(?:am|pm)", re.I))
            if time_el is None:
                time_str = ""
            elif hasattr(time_el, "get_text"):
                time_str = (time_el.get_text() or "").strip()
            else:
                time_str = str(time_el).strip()
            t_match = re.search(r"\d{1,2}:\d{2}\s*(?:am|pm)", time_str, re.I)
            t = parse_time(t_match.group(0)) if t_match else None
            if not t:
                continue

            title_el = s.find("h5") or s.find("h4") or s.find("h3")
            title = (title_el.get_text() or "").strip() if title_el else None
            if not title:
                continue

            director, release_year = None, None
            for div in s.find_all("div"):
                txt = (div.get_text() or "").strip()
                dm = re.match(r"Directed by\s+(.+?),\s*(\d{4})\s*$", txt)
                if dm:
                    director = dm.group(1).strip()
                    try:
                        release_year = int(dm.group(2))
                    except ValueError:
                        pass
                    break

            series = None
            for div in s.find_all("div"):
                txt = (div.get_text() or "").strip()
                if "From the" in txt or "..." in txt:
                    series = txt
                    break

            # Extract special attributes from this event's text (screening on film, panel discussion, etc.)
            spot_text = (s.get_text() or "").strip()
            special_attributes = extract_special_attributes(spot_text) or None

            events.append({
                "date": current_date,
                "time": t,
                "title": title,
                "director": director,
                "year": release_year,
                "series": series,
                "detail_url": detail_url,
                "special_attributes": special_attributes,
            })

        return events

    def _get_runtime_and_attrs_for_detail_url(self, detail_url: str) -> tuple[Optional[int], List[str]]:
        """Fetch detail page if needed; extract runtime and special attributes (e.g. 35mm from blurb). Cache by URL."""
        if detail_url in self._runtime_cache:
            runtime = self._runtime_cache[detail_url]
            attrs = self._detail_attrs_cache.get(detail_url, [])
            return (runtime, attrs)
        runtime = None
        attrs: List[str] = []
        try:
            soup = self.get_soup(detail_url)
            body = soup.find("body") or soup
            text = (body.get_text() or "").replace("\n", " ")
            runtime = self._extract_runtime_from_detail_page(soup)
            attrs = extract_special_attributes(text)
        except Exception as e:
            logger.debug("HFA: Could not fetch detail from %s: %s", detail_url, e)
        self._runtime_cache[detail_url] = runtime
        self._detail_attrs_cache[detail_url] = attrs
        return (runtime, attrs)

    def _extract_runtime_from_detail_page(self, soup: BeautifulSoup) -> Optional[int]:
        """Parse runtime from detail page blurb: '... country, year, format, color, 111 min.' or '111min.'."""
        body = soup.find("body") or soup
        text = (body.get_text() or "").replace("\n", " ")
        m = re.search(r"\b(\d{1,3})\s*min\.?\b", text, re.I)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 600:
                return val
        m = re.search(r"\b(\d+)\s*h\s*(\d+)?\s*m\.?\b", text, re.I)
        if m:
            h, mn = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
            if 0 <= h <= 24 and 0 <= mn < 60:
                return h * 60 + mn
        return None
