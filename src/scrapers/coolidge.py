"""Scraper for Coolidge Corner Theatre (coolidge.org)."""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from typing import Optional, List

from bs4 import BeautifulSoup, Tag

from ..models import Screening, ScraperConfig
from .base import BaseScraper, parse_time, extract_special_attributes

logger = logging.getLogger(__name__)

# Max concurrent requests for date pages (avoids hammering the server)
MAX_DATE_WORKERS = 10


class CoolidgeScraper(BaseScraper):
    """Scraper for Coolidge Corner Theatre."""
    
    name = "coolidge"
    base_url = "https://coolidge.org/"
    showtimes_url = "https://coolidge.org/films-events/now-playing"
    venue_name = "Coolidge Corner Theatre"
    
    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        # Cache for detail page data (title -> (director, year))
        self._detail_cache: dict[str, tuple[Optional[str], Optional[int]]] = {}
        self._detail_cache_lock = threading.Lock()
    
    def scrape(self) -> list[Screening]:
        """Scrape all screenings from Coolidge by iterating through dates (in parallel)."""
        screenings = []
        dates = list(self.config.date_range())
        workers = min(MAX_DATE_WORKERS, len(dates)) or 1

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_date = {executor.submit(self._scrape_date, d): d for d in dates}
            for future in as_completed(future_to_date):
                screening_date = future_to_date[future]
                try:
                    day_screenings = future.result()
                    screenings.extend(day_screenings)
                    logger.debug(f"Coolidge {screening_date}: Found {len(day_screenings)} screenings")
                except Exception as e:
                    logger.warning(f"Coolidge scraping failed for {screening_date}: {e}")

        logger.info(f"Coolidge: Found {len(screenings)} total screenings")
        return screenings
    
    def _scrape_date(self, screening_date: date) -> list[Screening]:
        """Scrape screenings for a specific date."""
        url = f"{self.showtimes_url}?date={screening_date.strftime('%Y-%m-%d')}"
        soup = self.get_soup(url)
        return self._parse_screenings(soup, screening_date)
    
    def _parse_screenings(self, soup: BeautifulSoup, screening_date: date) -> list[Screening]:
        """Parse screenings from the Coolidge showtimes page."""
        screenings = []
        
        # Find all film entries on the page
        # Coolidge uses a card-based layout for films
        # Each film has a title, runtime, description, and showtimes
        
        # Look for film containers - they typically have film titles as links
        # and showtime buttons/links
        
        # Try to find film blocks by looking for common patterns
        # The page structure has films with titles, runtimes, and time slots
        
        # Method 1: Look for elements with showtime links
        film_sections = soup.find_all("div", class_=re.compile(r"film|movie|showtime|event", re.I))
        
        if not film_sections:
            # Method 2: Parse text-based structure
            return self._parse_text_based(soup, screening_date)
        
        for section in film_sections:
            film_screenings = self._parse_film_section(section, screening_date)
            screenings.extend(film_screenings)
        
        # If no screenings found with div method, try text-based parsing
        if not screenings:
            screenings = self._parse_text_based(soup, screening_date)
        
        return screenings
    
    def _parse_film_section(self, section: Tag, screening_date: date) -> list[Screening]:
        """Parse a single film section into screenings."""
        screenings = []
        
        # Extract title - prefer links over headings, and filter out loglines
        title = None
        detail_url = None
        
        # First, try to find links (titles are often in links)
        link_elem = section.find("a", href=True)
        if link_elem:
            link_text = link_elem.get_text(strip=True)
            if link_text and len(link_text) >= 2 and not self._is_logline(link_text):
                title = link_text
                # Extract detail page URL
                href = link_elem.get("href", "")
                if href:
                    detail_url = self.make_absolute_url(href)
        
        # If no good link found, try headings
        if not title:
            for tag_name in ["h2", "h3", "h4"]:
                heading_elem = section.find(tag_name)
                if heading_elem:
                    heading_text = heading_elem.get_text(strip=True)
                    if heading_text and len(heading_text) >= 2 and not self._is_logline(heading_text):
                        title = heading_text
                        # Try to find a link near the heading
                        parent = heading_elem.parent
                        if parent:
                            nearby_link = parent.find("a", href=True)
                            if nearby_link:
                                href = nearby_link.get("href", "")
                                if href:
                                    detail_url = self.make_absolute_url(href)
                        break
        
        # If still no title, try any link without href check
        if not title:
            any_link = section.find("a")
            if any_link:
                link_text = any_link.get_text(strip=True)
                if link_text and len(link_text) >= 2 and not self._is_logline(link_text):
                    title = link_text
                    href = any_link.get("href", "")
                    if href:
                        detail_url = self.make_absolute_url(href)
        
        if not title:
            return screenings
        
        # Extract runtime
        runtime = self._extract_runtime(section.get_text())
        
        # Extract year and director from listing page first
        year = self._extract_year(section.get_text())
        director = self._extract_director(section.get_text())
        
        # Only fetch detail page if BOTH director and year are missing
        # This avoids unnecessary requests when we already have partial info
        if detail_url and not director and not year:
            detail_director, detail_year = self._get_detail_page_info(detail_url, title)
            director = detail_director
            year = detail_year
        
        # Extract showtimes - look for time patterns
        text = section.get_text()
        times = self._extract_times(text)
        
        # Extract extra info and special attributes (35mm, special screenings, etc.)
        extra = self._extract_extra(text)
        special_attributes = extract_special_attributes(text) or None
        
        # Create screening for each time
        now = datetime.now()
        for time_obj in times:
            screening = Screening(
                title=title,
                venue=self.venue_name,
                date=screening_date,
                time=time_obj,
                source_url=detail_url or f"{self.showtimes_url}?date={screening_date.strftime('%Y-%m-%d')}",
                source_site="Coolidge",
                runtime_minutes=runtime,
                year=year,
                director=director,
                extra=extra,
                special_attributes=special_attributes,
            )
            # Filter out screenings that have already passed
            if screening.datetime_start > now:
                screenings.append(screening)
        
        return screenings
    
    def _parse_text_based(self, soup: BeautifulSoup, screening_date: date) -> list[Screening]:
        """Parse screenings using text-based extraction."""
        screenings = []
        
        # Build a map of title -> detail URL by finding all links
        title_to_url = {}
        for link in soup.find_all("a", href=True):
            link_text = link.get_text(strip=True)
            if link_text and len(link_text) >= 2 and not self._is_logline(link_text):
                href = link.get("href", "")
                if href:
                    title_to_url[link_text] = self.make_absolute_url(href)
        
        # Get all text content
        body = soup.find("body") or soup
        full_text = body.get_text(separator="\n")
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        
        current_title = None
        current_runtime = None
        current_year = None
        current_director = None
        current_detail_url = None
        current_extra = []
        prev_line_was_runtime = False
        pending_runtime_mins = False  # "2hrs" seen; next "29mins" adds to runtime

        i = 0
        while i < len(lines):
            line = lines[i]
            runtime_match = hours_only = mins_only = None

            # Skip navigation/header items
            skip_patterns = [
                "now playing", "coming soon", "calendar", "skip to", "main navigation",
                "films & events", "education", "support us", "about us", "shop",
                "become a member", "donate", "search", "home", "film guide",
                "open captions", "membership", "gift cards",
                "learn more", "new release", "cinema in 70mm", "spotlight on women",
                "special screenings", "director in person", "speaker",
            ]
            # Room/theater codes often appear after times (e.g. MH1, MH2, ECEC)
            if re.match(r"^(MH\d|ECEC|MHB)$", line, re.I):
                prev_line_was_runtime = False
                pending_runtime_mins = False
                i += 1
                continue
            if any(pattern in line.lower() for pattern in skip_patterns):
                prev_line_was_runtime = False
                pending_runtime_mins = False
                i += 1
                continue

            # Runtime: "2hrs 29mins" on one line, or "2hrs" then "29mins" on consecutive lines
            runtime_match = re.search(r"(\d+)\s*h(?:rs?|ours?)?\s*(\d+)?\s*m(?:ins?)?", line, re.I)
            if runtime_match:
                hours = int(runtime_match.group(1))
                mins = int(runtime_match.group(2)) if runtime_match.group(2) else 0
                current_runtime = hours * 60 + mins
                prev_line_was_runtime = True
                pending_runtime_mins = False
                i += 1
                continue
            mins_only = re.match(r"^(\d+)\s*m(?:ins?)?$", line, re.I)
            if mins_only and pending_runtime_mins and current_runtime is not None:
                current_runtime += int(mins_only.group(1))
                pending_runtime_mins = False
                prev_line_was_runtime = True
                i += 1
                continue
            hours_only = re.match(r"^(\d+)\s*h(?:rs?|ours?)?$", line, re.I)
            if hours_only:
                current_runtime = int(hours_only.group(1)) * 60
                pending_runtime_mins = True
                prev_line_was_runtime = True
                i += 1
                continue
            
            # Check for time pattern (e.g., "3:00pm MH2", "7:00pm")
            time_match = re.match(r"^(\d{1,2}:\d{2}\s*(?:am|pm))(?:\s*\w+)?$", line, re.I)
            if time_match and current_title:
                time_obj = parse_time(time_match.group(1))
                if time_obj:
                    # Only fetch detail page if BOTH director and year are missing
                    director = current_director
                    year = current_year
                    if current_detail_url and not director and not year:
                        detail_director, detail_year = self._get_detail_page_info(current_detail_url, current_title)
                        director = detail_director
                        year = detail_year
                    
                    special_attrs = extract_special_attributes(" ".join(current_extra)) if current_extra else None
                    screening = Screening(
                        title=current_title,
                        venue=self.venue_name,
                        date=screening_date,
                        time=time_obj,
                        source_url=current_detail_url or f"{self.showtimes_url}?date={screening_date.strftime('%Y-%m-%d')}",
                        source_site="Coolidge",
                        runtime_minutes=current_runtime,
                        year=year,
                        director=director,
                        extra=", ".join(current_extra) if current_extra else None,
                        special_attributes=special_attrs,
                    )
                    # Filter out screenings that have already passed
                    now = datetime.now()
                    if screening.datetime_start > now:
                        screenings.append(screening)
                prev_line_was_runtime = False
                i += 1
                continue
            
            # Check for year in metadata line
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", line)
            if year_match and not current_year:
                current_year = int(year_match.group(1))
            
            # Check for director (often appears as "Directed by X" or just a name after title)
            director_match = re.search(r"Directed by\s+(.+?)(?:,|\s+\d{4}|$)", line, re.I)
            if director_match and not current_director:
                current_director = director_match.group(1).strip()
            # Also check for standalone director name (name without numbers, not too long, after title)
            elif (current_title and not current_director and 
                  len(line) > 2 and len(line) < 50 and
                  not re.search(r"\d", line) and
                  not time_match and
                  not self._is_logline(line) and
                  line[0].isupper()):
                # Likely a director name
                current_director = line
            
            # Check for special format markers
            if "35mm" in line.lower():
                current_extra.append("35mm")
            if "70mm" in line.lower():
                current_extra.append("70mm")
            
            # Check if this looks like a film title.
            # Don't treat description/tagline as title: it often follows runtime (e.g. "Dream Big.").
            if prev_line_was_runtime:
                prev_line_was_runtime = False
            elif (len(line) > 3 and len(line) < 100 and
                  not re.search(r"\d:\d{2}", line) and
                  line[0].isupper() and
                  not any(skip in line.lower() for skip in skip_patterns) and
                  not self._is_logline(line)):
                current_title = line
                current_runtime = None
                current_year = None
                current_director = None
                # Try to find detail URL for this title
                current_detail_url = title_to_url.get(line)
                current_extra = []
                pending_runtime_mins = False
            
            i += 1
        
        return screenings
    
    def _is_logline(self, text: str) -> bool:
        """Check if text looks like a logline/description rather than a title."""
        if not text:
            return True
        
        text_lower = text.lower()
        
        # Loglines often start with "A" or "An" followed by an adjective
        # Pattern matches: "A frisky, feminine, film noir about..." or "A film about..."
        if re.match(r"^a\s+[a-z]+(?:,\s+[a-z]+)*(?:\s+film\s+noir)?\s+(?:film|movie|story|tale|about)", text_lower):
            return True
        if re.match(r"^an\s+[a-z]+(?:\s+film\s+noir)?\s+(?:film|movie|story|tale|about)", text_lower):
            return True
        
        # Loglines often contain descriptive phrases
        logline_indicators = [
            "about",
            "frisky",
            "feminine",
            "film noir",
            "tells the story",
            "follows",
            "explores",
            "chronicles",
            "depicts",
            "portrays",
            "many other things",
        ]
        if any(indicator in text_lower for indicator in logline_indicators):
            return True
        
        # Loglines often end with ellipsis
        if text.strip().endswith("…") or text.strip().endswith("..."):
            return True
        
        # Loglines are typically longer than titles (more than 60 chars)
        if len(text) > 60:
            return True
        
        # Titles are usually shorter and don't contain multiple sentences
        if text.count(".") > 1 or text.count("…") > 0:
            return True
        
        return False
    
    def _extract_runtime(self, text: str) -> Optional[int]:
        """Extract runtime in minutes from text."""
        # Match patterns like "2hrs 28mins", "1hr 52mins", "2h 30m", "1h 45m"
        patterns = [
            r"(\d+)\s*h(?:rs?|ours?)?\s*(\d+)?\s*m(?:ins?)?",
            r"(\d+)\s*h(?:rs?|ours?)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                hours = int(match.group(1))
                mins = int(match.group(2)) if len(match.groups()) > 1 and match.group(2) else 0
                return hours * 60 + mins
        return None
    
    def _extract_year(self, text: str) -> Optional[int]:
        """Extract release year from text."""
        match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_director(self, text: str) -> Optional[str]:
        """Extract director name from text."""
        # Look for "Directed by X" pattern
        match = re.search(r"Directed by\s+(.+?)(?:,|\s+\d{4}|$)", text, re.I)
        if match:
            return match.group(1).strip()
        return None
    
    def _get_detail_page_info(self, detail_url: str, title: str) -> tuple[Optional[str], Optional[int]]:
        """Fetch director and year from a movie's detail page.
        
        Args:
            detail_url: URL of the movie detail page
            title: Movie title (for caching)
            
        Returns:
            Tuple of (director, year) or (None, None) if not found
        """
        cache_key = f"{title}|{detail_url}"
        with self._detail_cache_lock:
            if cache_key in self._detail_cache:
                return self._detail_cache[cache_key]

        director = None
        year = None

        try:
            # Use a shorter timeout for detail pages to avoid hanging
            # Create a config copy with shorter timeout
            from dataclasses import replace
            detail_config = replace(
                self.config,
                timeout=min(self.config.timeout, 10),  # Max 10 seconds for detail pages
                max_retries=1  # Only retry once for detail pages
            )
            
            # Fetch with shorter timeout
            from .base import fetch_with_retry
            response = fetch_with_retry(detail_url, detail_config)
            soup = BeautifulSoup(response.content, "lxml")
            page_text = soup.get_text()
            
            # Extract director
            director = self._extract_director(page_text)
            
            # Extract year
            year = self._extract_year(page_text)

            with self._detail_cache_lock:
                self._detail_cache[cache_key] = (director, year)

        except Exception as e:
            logger.debug(f"Coolidge: Could not fetch detail page {detail_url}: {e}")
            with self._detail_cache_lock:
                self._detail_cache[cache_key] = (None, None)

        return director, year
    
    def _extract_times(self, text: str) -> list:
        """Extract screening times from text."""
        times = []
        
        # Match times like "3:00pm", "7:00 PM"
        time_pattern = r"(\d{1,2}:\d{2}\s*(?:am|pm))"
        matches = re.findall(time_pattern, text, re.I)
        
        for match in matches:
            time_obj = parse_time(match)
            if time_obj:
                times.append(time_obj)
        
        return times
    
    def _extract_extra(self, text: str) -> Optional[str]:
        """Extract extra info like format or special events."""
        extras = []
        
        if "35mm" in text.lower():
            extras.append("35mm")
        if "70mm" in text.lower():
            extras.append("70mm")
        if "new release" in text.lower():
            extras.append("New Release")
        if "spotlight on women" in text.lower():
            extras.append("Spotlight on Women")
        
        return ", ".join(extras) if extras else None
