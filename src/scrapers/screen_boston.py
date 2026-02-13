"""Scraper for Screen Boston (screenboston.com)."""

import logging
import re
from datetime import datetime, date
from typing import Optional, List

from bs4 import BeautifulSoup, Tag

from ..models import Screening, ScraperConfig
from .base import BaseScraper, parse_time, parse_runtime, parse_date_header, extract_special_attributes

logger = logging.getLogger(__name__)


class ScreenBostonScraper(BaseScraper):
    """Scraper for Screen Boston - aggregates screenings from multiple Boston theaters."""
    
    name = "screen_boston"
    base_url = "https://screenboston.com/"
    
    # Venue name mappings
    VENUES = {
        "The Brattle": ["brattle", "the brattle"],
        "Coolidge Corner Theatre": ["coolidge", "coolidge corner"],
        "Harvard Film Archive": ["harvard film archive", "hfa"],
        "Somerville Theatre": ["somerville theatre", "somerville theater"],
        "West Newton Cinema": ["west newton"],
        "Museum of Fine Arts": ["museum of fine arts", "mfa", "museum of fine art"],
        "Capitol Theatre": ["capitol theatre", "capitol theater"],
    }
    
    def scrape(self) -> list[Screening]:
        """Scrape all screenings from Screen Boston."""
        screenings = []
        
        try:
            soup = self.get_soup(self.base_url)
            screenings = self._parse_screenings(soup)
            logger.info(f"Screen Boston: Found {len(screenings)} screenings")
        except Exception as e:
            logger.error(f"Screen Boston scraping failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return screenings
    
    def _parse_screenings(self, soup: BeautifulSoup) -> list[Screening]:
        """Parse screenings from the Screen Boston page.
        
        The page structure is:
        - Date headers (e.g., "Wednesday, January 28")
        - Film cards with: title, director, year/genre/runtime, venue, times
        """
        screenings = []
        current_date = None
        current_year = datetime.now().year
        
        # Get all text content and split by date headers
        # Screen Boston uses a simple structure with date headers followed by film info
        body = soup.find("body") or soup
        full_text = body.get_text(separator="\n")
        
        # Split into lines and process
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check for date header
            if self._is_date_header(line):
                parsed_date = self._parse_screen_boston_date(line, current_year)
                if parsed_date:
                    current_date = parsed_date
                    # Handle year rollover
                    today = datetime.now().date()
                    if current_date.month < today.month - 6:
                        current_date = current_date.replace(year=current_year + 1)
                i += 1
                continue
            
            # Try to parse a film entry starting at this line
            if current_date:
                film_data, consumed = self._try_parse_film_block(lines, i, current_date)
                if film_data:
                    screenings.extend(film_data)
                    i += consumed
                    continue
            
            i += 1
        
        # Filter to configured date range
        screenings = [
            s for s in screenings 
            if self.config.start_date <= s.date <= self.config.end_date
        ]
        
        # Remove duplicates (same title, venue, date, time)
        seen = set()
        unique_screenings = []
        for s in screenings:
            key = (s.title, s.venue, s.date, s.time)
            if key not in seen:
                seen.add(key)
                unique_screenings.append(s)
        
        return unique_screenings
    
    def _is_date_header(self, text: str) -> bool:
        """Check if text looks like a date header."""
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        months = ["january", "february", "march", "april", "may", "june", 
                  "july", "august", "september", "october", "november", "december"]
        
        text_lower = text.lower()
        has_day = any(day in text_lower for day in days)
        has_month = any(month in text_lower for month in months)
        
        # Also check it's not too long (date headers are short)
        return has_day and has_month and len(text) < 50
    
    def _parse_screen_boston_date(self, text: str, year: int) -> Optional[date]:
        """Parse a Screen Boston date header."""
        text = text.strip()
        
        formats = [
            "%A, %B %d",      # Wednesday, January 28
            "%A, %b %d",      # Wednesday, Jan 28
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.replace(year=year).date()
            except ValueError:
                continue
        
        return parse_date_header(text, year)
    
    def _try_parse_film_block(self, lines: List[str], start_idx: int, screening_date: date) -> tuple[List[Screening], int]:
        """Try to parse a film block starting at the given index.
        
        Returns (list of screenings, number of lines consumed).
        Film blocks typically look like:
        
        SCREEN BOSTON CO-PRESENTS (optional)
        Film Title
        Optional subtitle (Double Feature with X)
        Director Name
        2025, Genre, 1h 59m
        Venue Name
        3:30 PM
        8:30 PM
        """
        screenings = []
        consumed = 0
        
        # Look ahead to gather the block
        title = None
        director = None
        year = None
        runtime = None
        venue = None
        times = []
        extra_info = []
        
        max_look_ahead = 15  # Don't look too far
        
        for offset in range(max_look_ahead):
            if start_idx + offset >= len(lines):
                break
            
            line = lines[start_idx + offset]
            
            # Stop if we hit another date header
            if self._is_date_header(line):
                break
            
            # Skip "Now Screening" and similar headers
            if line.lower() in ["now screening", "upcoming screenings", "schedule", "about"]:
                consumed = offset + 1
                continue
            
            # Skip "SCREEN BOSTON CO-PRESENTS" prefix
            if "SCREEN BOSTON" in line.upper():
                consumed = offset + 1
                continue
            
            # Check for time (indicates we're in a film block)
            time_match = re.match(r"^(\d{1,2}:\d{2}\s*(?:AM|PM))$", line, re.IGNORECASE)
            if time_match:
                time_obj = parse_time(time_match.group(1))
                if time_obj:
                    times.append(time_obj)
                consumed = offset + 1
                continue
            
            # Check for venue
            detected_venue = self._extract_venue(line)
            if detected_venue and venue is None:
                venue = detected_venue
                consumed = offset + 1
                continue
            
            # Check for year/genre/runtime line (e.g., "2025, Drama, 1h 59m")
            metadata_match = re.match(r"^(19\d{2}|20\d{2}),\s*\w+,\s*(\d+h\s*\d*m?)", line)
            if metadata_match:
                year = int(metadata_match.group(1))
                runtime = self._parse_runtime_str(metadata_match.group(2))
                consumed = offset + 1
                continue
            
            # Check for standalone year line
            year_match = re.match(r"^(19\d{2}|20\d{2})$", line)
            if year_match and year is None:
                year = int(year_match.group(1))
                consumed = offset + 1
                continue
            
            # Check for double feature / special info FIRST (so they're not mistaken for director)
            if "double feature" in line.lower() or "35mm" in line.lower() or "70mm" in line.lower():
                extra_info.append(line)
                consumed = offset + 1
                continue
            
            # Check for special event markers
            special_markers = ["in person", "q&a", "discussion", "seminar", "live score", "sing-along"]
            if any(marker in line.lower() for marker in special_markers):
                extra_info.append(line)
                consumed = offset + 1
                continue
            
            # Check for director line (name without numbers, not a venue, not too long, not double-feature text)
            if (title and not director and not venue and 
                len(line) < 40 and 
                not re.search(r"\d", line) and
                not self._extract_venue(line) and
                not self._is_date_header(line) and
                "double feature" not in line.lower()):
                # Likely a director name
                director = line
                consumed = offset + 1
                continue
            
            # If we don't have a title yet, this might be the title
            if title is None and len(line) > 1 and not self._is_date_header(line):
                title = line
                consumed = offset + 1
                continue
            
            # If we have times but hit a non-matching line, we're probably done with this block
            if times and not time_match:
                break
        
        # Create screenings if we have the required fields
        if title and venue and times:
            extra = ", ".join(extra_info) if extra_info else None
            special_attributes = extract_special_attributes(" ".join(extra_info)) if extra_info else None
            
            for time_obj in times:
                screening = Screening(
                    title=title,
                    venue=venue,
                    date=screening_date,
                    time=time_obj,
                    source_url=self.base_url,
                    source_site="Screen Boston",
                    runtime_minutes=runtime,
                    director=director,
                    year=year,
                    extra=extra,
                    special_attributes=special_attributes,
                )
                screenings.append(screening)
        
        return screenings, max(consumed, 1)
    
    def _extract_venue(self, text: str) -> Optional[str]:
        """Extract venue name from text."""
        text_lower = text.lower().strip()
        
        for venue_name, patterns in self.VENUES.items():
            for pattern in patterns:
                if pattern == text_lower or text_lower.startswith(pattern):
                    return venue_name
        
        return None
    
    def _parse_runtime_str(self, runtime_str: str) -> Optional[int]:
        """Parse a runtime string like '1h 59m' into minutes."""
        match = re.search(r"(\d+)h\s*(\d*)m?", runtime_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) if match.group(2) else 0
            return hours * 60 + minutes
        return None
