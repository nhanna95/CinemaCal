"""Data models for theater screenings."""

from dataclasses import dataclass, field
from datetime import date, time, datetime, timedelta
from typing import Optional, List
import hashlib


@dataclass
class Screening:
    """Represents a single movie screening."""
    
    title: str
    venue: str
    date: date
    time: time
    source_url: str
    source_site: str
    runtime_minutes: Optional[int] = None
    director: Optional[str] = None
    year: Optional[int] = None
    extra: Optional[str] = None  # e.g., free-form notes
    # Structured special attributes: format (35mm, screening on film), event type (panel discussion, Q&A, etc.)
    special_attributes: Optional[List[str]] = None
    
    @property
    def datetime_start(self) -> datetime:
        """Get the start datetime of the screening."""
        return datetime.combine(self.date, self.time)
    
    @property
    def datetime_end(self) -> datetime:
        """Get the end datetime (start + runtime, or +2h default for films)."""
        duration = timedelta(minutes=self.runtime_minutes) if self.runtime_minutes else timedelta(hours=2)
        return self.datetime_start + duration
    
    @property
    def unique_id(self) -> str:
        """Generate a unique ID for this screening based on key fields."""
        key = f"{self.title}|{self.venue}|{self.date}|{self.time}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def __str__(self) -> str:
        time_str = self.time.strftime("%I:%M %p")
        date_str = self.date.strftime("%a %b %d")
        extra_str = f" [{self.extra}]" if self.extra else ""
        special_str = ""
        if self.special_attributes:
            special_str = " [" + ", ".join(self.special_attributes) + "]"
        return f"{self.title} @ {self.venue} - {date_str} {time_str}{extra_str}{special_str}"
    
    def __hash__(self) -> int:
        return hash((self.title, self.venue, self.date, self.time))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, Screening):
            return False
        return (self.title == other.title and 
                self.venue == other.venue and 
                self.date == other.date and 
                self.time == other.time)


@dataclass
class ScraperConfig:
    """Configuration for scrapers."""
    
    start_date: date = field(default_factory=date.today)
    days_ahead: int = 60
    
    # Per-source enable/disable
    enable_screen_boston: bool = True
    enable_coolidge: bool = True
    enable_hfa: bool = True
    enable_brattle: bool = True
    
    # Request settings
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # Cache settings (for development)
    use_cache: bool = False
    cache_dir: str = ".cache"
    
    @property
    def end_date(self) -> date:
        """Get the end date based on start_date and days_ahead."""
        return self.start_date + timedelta(days=self.days_ahead)
    
    def date_range(self):
        """Yield dates from start_date to end_date."""
        current = self.start_date
        while current <= self.end_date:
            yield current
            current += timedelta(days=1)


# Venue addresses for calendar events
VENUE_ADDRESSES = {
    "The Brattle": "40 Brattle St, Cambridge, MA 02138",
    "Coolidge Corner Theatre": "290 Harvard St, Brookline, MA 02446",
    "Harvard Film Archive": "24 Quincy St, Cambridge, MA 02138",
    "Somerville Theatre": "55 Davis Square, Somerville, MA 02144",
    "West Newton Cinema": "1296 Washington St, West Newton, MA 02465",
    "Museum of Fine Arts": "465 Huntington Ave, Boston, MA 02115",
    "Capitol Theatre": "204 Massachusetts Ave, Arlington, MA 02474",
}


def get_venue_address(venue: str) -> Optional[str]:
    """Get the address for a venue, with fuzzy matching."""
    venue_lower = venue.lower()
    for name, address in VENUE_ADDRESSES.items():
        if name.lower() in venue_lower or venue_lower in name.lower():
            return address
    return None
