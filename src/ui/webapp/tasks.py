"""Background task management for scraping."""

import logging
import threading
import uuid
from collections import defaultdict
from datetime import date
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict

from ...models import Screening, ScraperConfig, VENUE_ADDRESSES
from ...scrapers import (
    ScreenBostonScraper,
    CoolidgeScraper,
    HarvardFilmArchiveScraper,
    BrattleScraper,
)

logger = logging.getLogger(__name__)

# Coolidge "regular" vs "one-off" heuristic (keep in sync with frontend)
COOLIDGE_VENUE_NAME = "Coolidge Corner Theatre"
MIN_DAYS_REGULAR_COOLIDGE = 5
MIN_SHOWTIMES_REGULAR_COOLIDGE = 10


def filter_regular_coolidge(
    screenings: List[Screening],
    min_days: int = MIN_DAYS_REGULAR_COOLIDGE,
    min_showtimes: int = MIN_SHOWTIMES_REGULAR_COOLIDGE,
) -> List[Screening]:
    """Remove Coolidge screenings whose title is 'regular' (many days or many showtimes).

    A Coolidge title is regular if it has >= min_days distinct dates or
    >= min_showtimes total showtimes. Other venues are unchanged.
    """
    coolidge = [s for s in screenings if s.venue == COOLIDGE_VENUE_NAME]
    if not coolidge:
        return screenings
    by_title: Dict[str, List[Screening]] = defaultdict(list)
    for s in coolidge:
        by_title[s.title].append(s)
    regular_titles = set()
    for title, group in by_title.items():
        distinct_dates = len(set(s.date for s in group))
        total_showtimes = len(group)
        if distinct_dates >= min_days or total_showtimes >= min_showtimes:
            regular_titles.add(title)
    return [
        s for s in screenings
        if not (s.venue == COOLIDGE_VENUE_NAME and s.title in regular_titles)
    ]


@dataclass
class JobStatus:
    """Status of a scraping job."""
    job_id: str
    status: str  # "pending", "running", "complete", "error"
    progress: int = 0  # 0-100
    message: str = ""
    screenings: List[Screening] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.screenings is None:
            self.screenings = []


# In-memory job storage (for MVP)
_jobs: Dict[str, JobStatus] = {}


def start_scrape_job(config: ScraperConfig) -> str:
    """Start a scraping job in the background.
    
    Args:
        config: ScraperConfig with scraping parameters
        
    Returns:
        Job ID string
    """
    job_id = str(uuid.uuid4())
    
    # Create initial job status
    job = JobStatus(
        job_id=job_id,
        status="pending",
        progress=0,
        message="Starting scrape..."
    )
    _jobs[job_id] = job
    
    # Start background thread
    thread = threading.Thread(target=_do_scrape, args=(job_id, config), daemon=True)
    thread.start()
    
    return job_id


def _canonical_venue(venue: str) -> str:
    """Return a canonical venue name for grouping (e.g. 'Brattle' -> 'The Brattle')."""
    if not venue:
        return venue
    v_lower = venue.lower().strip()
    for name in VENUE_ADDRESSES:
        if name.lower() in v_lower or v_lower in name.lower():
            return name
    return venue


def _merge_two_screenings(first: Screening, second: Screening) -> Screening:
    """Combine two screenings into one (title + title, directors, sum runtime)."""
    titles = [first.title, second.title]
    combined_title = " + ".join(titles)
    directors = [d for d in (first.director, second.director) if d]
    if not directors:
        combined_director = None
    elif len(set(directors)) == 1:
        combined_director = directors[0]
    else:
        combined_director = " + ".join(directors)
    runtimes = [r for r in (first.runtime_minutes, second.runtime_minutes) if r is not None]
    combined_runtime = sum(runtimes) if runtimes else None
    extras = [e for e in (first.extra, second.extra) if e]
    combined_extra = ", ".join(extras) if extras else None
    all_special = []
    for s in (first, second):
        if s.special_attributes:
            all_special.extend(s.special_attributes)
    combined_special = list(dict.fromkeys(all_special)) if all_special else None
    return Screening(
        title=combined_title,
        venue=first.venue,
        date=first.date,
        time=first.time,
        source_url=first.source_url,
        source_site=first.source_site,
        runtime_minutes=combined_runtime,
        director=combined_director,
        year=first.year,
        extra=combined_extra,
        special_attributes=combined_special,
    )


def _merge_double_screenings(screenings: List[Screening]) -> List[Screening]:
    """Identify double (or triple, etc.) screenings and merge into one.
    
    1. Group by (canonical venue, date, time) and merge same-slot screenings.
    2. For any screening that still has "Double feature" in special_attributes,
       merge it with the next screening at the same venue/date (catches cases
       where the second film was parsed with a different time).
    
    Combined screening uses:
    - title: "{Title 1} + {Title 2}"
    - director: "{Director 1} + {Director 2}" or just director if same
    - runtime_minutes: sum of runtimes
    """
    # Pass 1: group by canonical venue + date + time
    key_to_list: Dict[tuple, List[Screening]] = defaultdict(list)
    for s in screenings:
        key = (_canonical_venue(s.venue), s.date, s.time)
        key_to_list[key].append(s)
    
    result: List[Screening] = []
    for key, group in key_to_list.items():
        if len(group) == 1:
            result.append(group[0])
            continue
        # Same slot, multiple screenings: only merge if they're different films.
        # Same title = duplicate showtimes of one film (e.g. Coolidge listing same time twice) → keep one.
        titles = [s.title for s in group]
        if len(set(titles)) == 1:
            result.append(group[0])
            continue
        first = group[0]
        combined_title = " + ".join(titles)
        directors = [s.director for s in group if s.director]
        if not directors:
            combined_director = None
        elif len(set(directors)) == 1:
            combined_director = directors[0]
        else:
            combined_director = " + ".join(directors)
        runtimes = [s.runtime_minutes for s in group if s.runtime_minutes is not None]
        combined_runtime = sum(runtimes) if runtimes else None
        extras = [s.extra for s in group if s.extra]
        combined_extra = ", ".join(extras) if extras else None
        all_special = []
        for s in group:
            if s.special_attributes:
                all_special.extend(s.special_attributes)
        combined_special = list(dict.fromkeys(all_special)) if all_special else None
        merged = Screening(
            title=combined_title,
            venue=first.venue,
            date=first.date,
            time=first.time,
            source_url=first.source_url,
            source_site=first.source_site,
            runtime_minutes=combined_runtime,
            director=combined_director,
            year=first.year,
            extra=combined_extra,
            special_attributes=combined_special,
        )
        result.append(merged)
    
    # Pass 2: screenings with "Double feature" that weren't merged (e.g. second
    # film had a different time) — merge with the next screening at same venue/date
    result.sort(key=lambda s: (_canonical_venue(s.venue), s.date, s.time))
    out: List[Screening] = []
    i = 0
    while i < len(result):
        s = result[i]
        has_double_feature = (
            s.special_attributes
            and "Double feature" in s.special_attributes
        )
        next_same_venue_date = (
            i + 1 < len(result)
            and _canonical_venue(result[i + 1].venue) == _canonical_venue(s.venue)
            and result[i + 1].date == s.date
        )
        if has_double_feature and next_same_venue_date:
            merged = _merge_two_screenings(s, result[i + 1])
            out.append(merged)
            i += 2
            continue
        out.append(s)
        i += 1
    
    return out


def _deduplicate_screenings(screenings: List[Screening]) -> List[Screening]:
    """Remove duplicate screenings.
    
    Removes:
    1. Duplicates from the same source site
    2. Cross-site duplicates, preferring theater's own site over Screen Boston
    
    Args:
        screenings: List of screenings to deduplicate
        
    Returns:
        Deduplicated list of screenings
    """
    # Map venue names to their preferred source sites
    venue_to_preferred_site = {
        "Coolidge Corner Theatre": "Coolidge",
        "The Brattle": "Brattle",
        "Harvard Film Archive": "Harvard Film Archive",
    }
    
    # Track unique screenings by (title, venue, date, time)
    seen: Dict[tuple, Screening] = {}
    
    for screening in screenings:
        key = (screening.title, screening.venue, screening.date, screening.time)
        
        if key not in seen:
            # First occurrence, keep it
            seen[key] = screening
        else:
            # Duplicate found
            existing = seen[key]
            
            # If same source site, skip (keep the first one)
            if existing.source_site == screening.source_site:
                continue
            
            # Cross-site duplicate - decide which to keep
            # Prefer theater's own site over Screen Boston
            preferred_site = venue_to_preferred_site.get(screening.venue)
            
            # If current screening is from preferred site, replace
            if screening.source_site == preferred_site:
                seen[key] = screening
            # If existing is from Screen Boston and current is from a theater site, replace
            elif existing.source_site == "Screen Boston" and screening.source_site != "Screen Boston":
                seen[key] = screening
            # Otherwise keep existing (it's already preferred or from a theater site)
            # No action needed
    
    return list(seen.values())


def _do_scrape(job_id: str, config: ScraperConfig):
    """Perform scraping in background thread."""
    job = _jobs.get(job_id)
    if not job:
        return
    
    try:
        job.status = "running"
        job.progress = 0
        job.message = "Initializing scrapers..."
        
        screenings: List[Screening] = []
        
        # Build list of scrapers to run
        scrapers = []
        if config.enable_screen_boston:
            scrapers.append(("Screen Boston", ScreenBostonScraper(config)))
        if config.enable_coolidge:
            scrapers.append(("Coolidge", CoolidgeScraper(config)))
        if config.enable_hfa:
            scrapers.append(("HFA", HarvardFilmArchiveScraper(config)))
        if config.enable_brattle:
            scrapers.append(("Brattle", BrattleScraper(config)))
        
        total_scrapers = len(scrapers)
        
        # Run each scraper
        for idx, (name, scraper) in enumerate(scrapers):
            try:
                job.message = f"Scraping {name}..."
                job.progress = int((idx / total_scrapers) * 90)
                
                logger.info(f"Scraping {name}...")
                results = scraper.scrape()
                screenings.extend(results)
                
                logger.info(f"Found {len(results)} screenings from {name}")
            except Exception as e:
                logger.error(f"Error scraping {name}: {e}")
                continue
        
        # Merge double screenings (same venue, date, time → one combined screening)
        screenings = _merge_double_screenings(screenings)
        
        # Deduplicate screenings
        original_count = len(screenings)
        screenings = _deduplicate_screenings(screenings)
        removed_count = original_count - len(screenings)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} duplicate screening(s)")
        
        # Sort by earliest to latest (date, then time)
        screenings.sort(key=lambda s: (s.date, s.time))
        
        # Complete
        job.status = "complete"
        job.progress = 100
        job.message = f"Found {len(screenings)} screenings"
        job.screenings = screenings
        
        logger.info(f"Scraping complete: {len(screenings)} screenings")
        
    except Exception as e:
        logger.error(f"Scraping job {job_id} failed: {e}")
        job.status = "error"
        job.error = str(e)
        job.message = f"Error: {e}"


def get_job_status(job_id: str) -> Optional[JobStatus]:
    """Get the status of a scraping job.
    
    Args:
        job_id: Job ID string
        
    Returns:
        JobStatus object or None if not found
    """
    return _jobs.get(job_id)


def serialize_screening(screening: Screening) -> dict:
    """Convert Screening to JSON-serializable dict."""
    return {
        "title": screening.title,
        "venue": screening.venue,
        "date": screening.date.isoformat(),
        "time": screening.time.strftime("%H:%M:%S"),
        "source_url": screening.source_url,
        "source_site": screening.source_site,
        "runtime_minutes": screening.runtime_minutes,
        "director": screening.director,
        "year": screening.year,
        "extra": screening.extra,
        "special_attributes": screening.special_attributes or [],
        "unique_id": screening.unique_id,
    }


def serialize_job_status(job: JobStatus) -> dict:
    """Convert JobStatus to JSON-serializable dict."""
    result = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
    }
    
    if job.error:
        result["error"] = job.error
    
    if job.status == "complete" and job.screenings:
        result["screenings"] = [serialize_screening(s) for s in job.screenings]
        result["count"] = len(job.screenings)
    
    return result
