"""Scraper for The Brattle Theatre (brattlefilm.org)."""

import logging
import re
from datetime import datetime, date
from typing import Optional, List, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import Screening, ScraperConfig
from .base import BaseScraper, parse_time, extract_special_attributes

logger = logging.getLogger(__name__)


class BrattleScraper(BaseScraper):
    """Scraper for The Brattle Theatre."""
    
    name = "brattle"
    base_url = "https://brattlefilm.org/"
    coming_soon_url = "https://brattlefilm.org/coming-soon/"
    venue_name = "The Brattle"
    
    def scrape(self) -> list[Screening]:
        """Scrape all screenings from The Brattle."""
        screenings = []
        
        try:
            soup = self.get_soup(self.coming_soon_url)
            screenings = self._parse_coming_soon(soup)
            logger.info(f"Brattle: Found {len(screenings)} screenings")
        except Exception as e:
            logger.error(f"Brattle scraping failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return screenings
    
    def _parse_coming_soon(self, soup: BeautifulSoup) -> list[Screening]:
        """Parse screenings from the coming-soon page."""
        screenings = []
        current_year = datetime.now().year
        
        # The Brattle page structure shows films with:
        # - Title (in h2 or link)
        # - Dates with showtimes (e.g., "Today, Jan 28" with times like "3:30 pm")
        # - Director, Runtime, Format, Release Year
        # - Some films show "Opens on February X" without specific times
        
        # Parse text-based structure
        body = soup.find("body") or soup
        full_text = body.get_text(separator="\n")
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        
        # Track current film context
        current_title = None
        current_director = None
        current_runtime = None
        current_year = None
        current_format = None
        current_dates_times: List[Tuple[date, list]] = []  # List of (date, [times])
        current_extra = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip navigation and footer items
            skip_patterns = [
                "skip to content", "upcoming films", "watch trailer", "see full details",
                "the brattle film foundation", "location", "contact", "policies",
                "subscribe", "instagram", "facebook", "letterboxd", "bluesky",
                "copyright", "powered by", "40 brattle st", "starring", "dates with showtimes"
            ]
            if any(pattern in line.lower() for pattern in skip_patterns):
                i += 1
                continue
            
            # Brattle uses label-value on separate lines: "Director:" then "Name", "Run Time:" then "113 min."
            if line.strip() == "Director:" and i + 1 < len(lines):
                current_director = lines[i + 1].strip()
                i += 2
                continue
            if line.strip() == "Run Time:" and i + 1 < len(lines):
                runtime_val = self._parse_runtime_value(lines[i + 1].strip())
                if runtime_val is not None:
                    current_runtime = runtime_val
                i += 2
                continue
            if line.strip() == "Format:" and i + 1 < len(lines):
                current_format = lines[i + 1].strip()
                i += 2
                continue
            if line.strip() == "Release Year:" and i + 1 < len(lines):
                try:
                    current_year = int(lines[i + 1].strip())
                except ValueError:
                    pass
                i += 2
                continue
            # Fallback: combined "Director: X Run Time: Y" on one line (legacy)
            if "Director:" in line or "Run Time:" in line:
                parsed = self._parse_metadata_line(line)
                if parsed.get("director") is not None:
                    current_director = parsed["director"]
                if parsed.get("runtime") is not None:
                    current_runtime = parsed["runtime"]
                if parsed.get("year") is not None:
                    current_year = parsed["year"]
                if parsed.get("format") is not None:
                    current_format = parsed["format"]
                i += 1
                continue
            
            # Check for date line (e.g., "Today, Jan 28", "Wed, Jan 29", "Fri, Jan 30")
            date_parsed = self._parse_brattle_date(line, current_year or datetime.now().year)
            if date_parsed:
                # Start collecting times for this date
                current_dates_times.append((date_parsed, []))
                i += 1
                continue
            
            # Check for time line (e.g., "3:30 pm", "6:00 pm35mm")
            time_match = re.match(r"^(\d{1,2}:\d{2}\s*(?:am|pm))(.*)$", line, re.I)
            if time_match and current_dates_times:
                time_obj = parse_time(time_match.group(1))
                if time_obj:
                    # Add to most recent date
                    current_dates_times[-1][1].append(time_obj)
                    # Check for format suffix like "35mm"
                    suffix = time_match.group(2).strip()
                    if suffix and suffix not in current_extra:
                        current_extra.append(suffix)
                i += 1
                continue
            
            # Check for "Opens on" without times (need to visit detail page)
            opens_match = re.match(r"Opens on (\w+ \d+)", line, re.I)
            if opens_match:
                # This film doesn't have times on main page
                # We could visit detail page, but for now just skip
                i += 1
                continue
            
            # Check for format markers
            if "35mm" in line.lower() and "35mm" not in current_extra:
                current_extra.append("35mm")
            if "70mm" in line.lower() and "70mm" not in current_extra:
                current_extra.append("70mm")
            if "premiere" in line.lower() and "Premiere" not in current_extra:
                current_extra.append("Premiere")
            
            # Check if this looks like a film title
            # Titles are usually standalone lines, capitalized, not too short
            if (len(line) > 3 and len(line) < 150 and
                not re.match(r"^\d{1,2}:\d{2}", line) and
                not date_parsed and
                not any(skip in line.lower() for skip in skip_patterns) and
                not "Director:" in line and
                line[0].isupper()):
                
                # Before setting new title, save current film if we have data
                if current_title and current_dates_times:
                    film_screenings = self._create_screenings(
                        current_title, current_director, current_runtime,
                        current_year, current_format, current_dates_times, current_extra
                    )
                    screenings.extend(film_screenings)
                
                # Start new film
                current_title = line
                current_director = None
                current_runtime = None
                current_year = None
                current_format = None
                current_dates_times = []
                current_extra = []
            
            i += 1
        
        # Don't forget the last film
        if current_title and current_dates_times:
            film_screenings = self._create_screenings(
                current_title, current_director, current_runtime,
                current_year, current_format, current_dates_times, current_extra
            )
            screenings.extend(film_screenings)
        
        # Filter to configured date range
        screenings = [
            s for s in screenings 
            if self.config.start_date <= s.date <= self.config.end_date
        ]
        
        # Remove duplicates
        seen = set()
        unique = []
        for s in screenings:
            key = (s.title, s.date, s.time)
            if key not in seen:
                seen.add(key)
                unique.append(s)
        
        return unique
    
    def _parse_brattle_date(self, text: str, year: int) -> Optional[date]:
        """Parse a Brattle date string.
        
        Formats:
        - "Today, Jan 28"
        - "Wed, Jan 29"
        - "Sat, Jan 31"
        - "Sun, Feb 1"
        """
        text = text.strip()
        
        # Handle "Today"
        if text.lower().startswith("today"):
            return datetime.now().date()
        
        # Try various formats
        formats = [
            "%a, %b %d",      # Wed, Jan 29
            "%A, %b %d",      # Wednesday, Jan 29
            "%a, %B %d",      # Wed, January 29
            "%A, %B %d",      # Wednesday, January 29
            "%b %d",          # Jan 29
            "%B %d",          # January 29
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                result = parsed.replace(year=year).date()
                # Handle year rollover
                today = datetime.now().date()
                if result.month < today.month - 6:
                    result = result.replace(year=year + 1)
                return result
            except ValueError:
                continue
        
        return None
    
    def _parse_runtime_value(self, text: str) -> Optional[int]:
        """Parse runtime from value line, e.g. '113 min.', '2hr 30min'."""
        text = text.strip()
        m = re.search(r"^(\d+)\s*min\.?$", text, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"^(\d+)\s*h(?:r|our)?s?\s*(\d+)?\s*m(?:in\.?)?s?$", text, re.I)
        if m:
            h = int(m.group(1))
            mn = int(m.group(2)) if m.group(2) else 0
            return h * 60 + mn
        return None

    def _parse_metadata_line(self, line: str) -> dict:
        """Parse a metadata line with director, runtime, format, year. Returns dict with keys director, runtime, year, format (only set when present)."""
        out: dict = {}
        # Director
        dir_match = re.search(r"Director:\s*([^R]+?)(?:Run Time:|$)", line)
        if dir_match:
            out["director"] = dir_match.group(1).strip()
        # Runtime: "Run Time: 113 min." or "Run Time: 2hr 30min" etc.
        runtime_match = re.search(r"Run Time:\s*(\d+)\s*(?:hr?|hour)?s?\s*(\d+)?\s*(?:min\.?)?", line, re.I)
        if runtime_match:
            if "h" in line.lower() or "hour" in line.lower():
                hours = int(runtime_match.group(1))
                mins = int(runtime_match.group(2)) if runtime_match.group(2) else 0
                out["runtime"] = hours * 60 + mins
            else:
                out["runtime"] = int(runtime_match.group(1))
        else:
            runtime_match2 = re.search(r"(\d+)\s*h(?:r|our)?s?\s*(\d+)?\s*m(?:in\.?)?", line, re.I)
            if runtime_match2:
                hours = int(runtime_match2.group(1))
                mins = int(runtime_match2.group(2)) if runtime_match2.group(2) else 0
                out["runtime"] = hours * 60 + mins
        # Year
        year_match = re.search(r"Release Year:\s*(\d{4})", line)
        if year_match:
            out["year"] = int(year_match.group(1))
        # Format
        format_match = re.search(r"Format:\s*(\S+)", line)
        if format_match:
            out["format"] = format_match.group(1)
        return out
    
    def _create_screenings(self, title: str, director: Optional[str], 
                           runtime: Optional[int], year: Optional[int],
                           film_format: Optional[str],
                           dates_times: List[Tuple[date, list]],
                           extra: List[str]) -> list[Screening]:
        """Create Screening objects from collected data."""
        screenings = []
        
        # Build combined text for special-attribute extraction
        combined_parts = [film_format] if film_format else []
        combined_parts.extend(extra)
        combined_text = " ".join(combined_parts)
        special_attributes = extract_special_attributes(combined_text) if combined_text else None
        # Also add format explicitly if present (e.g. "35mm", "70mm") and not already in list.
        # Normalize "35mm Film" / "70mm Film" / "16mm Film" to just "35mm" / "70mm" / "16mm".
        if film_format and film_format.upper() not in ["DCP"]:
            fmt_norm = film_format.strip()
            if fmt_norm.lower().endswith(" film"):
                fmt_norm = fmt_norm[:-5].strip()  # "35mm Film" -> "35mm"
            if special_attributes is None:
                special_attributes = []
            if fmt_norm and fmt_norm not in special_attributes:
                special_attributes.append(fmt_norm)
        
        # Build extra string for free-form display
        extra_parts = []
        if film_format and film_format not in ["DCP"]:
            extra_parts.append(film_format)
        extra_parts.extend(extra)
        extra_str = ", ".join(extra_parts) if extra_parts else None
        
        for screening_date, times in dates_times:
            for time_obj in times:
                screening = Screening(
                    title=title,
                    venue=self.venue_name,
                    date=screening_date,
                    time=time_obj,
                    source_url=self.coming_soon_url,
                    source_site="Brattle",
                    runtime_minutes=runtime,
                    director=director,
                    year=year,
                    extra=extra_str,
                    special_attributes=special_attributes,
                )
                screenings.append(screening)
        
        return screenings
