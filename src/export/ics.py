"""Export screenings to .ics calendar format."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import webbrowser

from icalendar import Calendar, Event, vText
import pytz

from ..models import Screening, get_venue_address

logger = logging.getLogger(__name__)

# Boston timezone
BOSTON_TZ = pytz.timezone("America/New_York")


def create_calendar_event(screening: Screening) -> Event:
    """Create an iCalendar event from a Screening."""
    event = Event()
    
    # Summary: "Film Title @ Venue"
    summary = f"{screening.title} @ {screening.venue}"
    event.add("summary", summary)
    
    # Start time (with timezone)
    start_dt = datetime.combine(screening.date, screening.time)
    start_dt = BOSTON_TZ.localize(start_dt)
    event.add("dtstart", start_dt)
    
    # End time (start + runtime or default 2 hours)
    if screening.runtime_minutes:
        duration = timedelta(minutes=screening.runtime_minutes)
    else:
        duration = timedelta(hours=2)
    end_dt = start_dt + duration
    event.add("dtend", end_dt)
    
    # Location
    address = get_venue_address(screening.venue)
    if address:
        event.add("location", vText(f"{screening.venue}, {address}"))
    else:
        event.add("location", vText(screening.venue))
    
    # Description with details
    description_parts = []
    
    if screening.director:
        description_parts.append(f"Director: {screening.director}")
    
    if screening.year:
        description_parts.append(f"Year: {screening.year}")
    
    if screening.runtime_minutes:
        hours = screening.runtime_minutes // 60
        mins = screening.runtime_minutes % 60
        if hours and mins:
            description_parts.append(f"Runtime: {hours}h {mins}m")
        elif hours:
            description_parts.append(f"Runtime: {hours}h")
        else:
            description_parts.append(f"Runtime: {mins}m")
    
    if screening.special_attributes:
        description_parts.append(f"Special: {', '.join(screening.special_attributes)}")
    if screening.extra:
        description_parts.append(f"Notes: {screening.extra}")
    
    description_parts.append(f"Source: {screening.source_site}")
    description_parts.append(f"URL: {screening.source_url}")
    
    event.add("description", "\n".join(description_parts))
    
    # Unique ID based on screening details
    uid = f"{screening.unique_id}@cinemacal"
    event.add("uid", uid)
    
    # Creation timestamp
    event.add("dtstamp", datetime.now(pytz.UTC))
    
    return event


def export_to_ics(screenings: list[Screening], filepath: str) -> str:
    """Export screenings to an .ics file.
    
    Args:
        screenings: List of Screening objects to export
        filepath: Path to save the .ics file
        
    Returns:
        The filepath where the calendar was saved
    """
    if not screenings:
        logger.warning("No screenings to export")
        return filepath
    
    # Create calendar
    cal = Calendar()
    cal.add("prodid", "-//CinemaCal//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Movie Screenings")
    cal.add("x-wr-timezone", "America/New_York")
    
    # Add events
    for screening in screenings:
        try:
            event = create_calendar_event(screening)
            cal.add_component(event)
        except Exception as e:
            logger.warning(f"Failed to create event for {screening.title}: {e}")
            continue
    
    # Write to file
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "wb") as f:
        f.write(cal.to_ical())
    
    logger.info(f"Exported {len(screenings)} screenings to {filepath}")
    return str(path.absolute())


def open_google_calendar_import():
    """Open Google Calendar import page in the default browser."""
    url = "https://calendar.google.com/calendar/r/settings/export"
    webbrowser.open(url)
    logger.info("Opened Google Calendar import page in browser")


def get_import_instructions() -> str:
    """Get instructions for importing the .ics file to Google Calendar."""
    return """
To import the .ics file to Google Calendar:

1. Open Google Calendar (calendar.google.com) in your browser
2. Click the gear icon (Settings) in the top right
3. Select "Settings" from the dropdown
4. Click "Import & Export" in the left sidebar
5. Click "Select file from your computer"
6. Choose the exported .ics file
7. Select which calendar to add the events to
8. Click "Import"

Note: Google Calendar import only works on desktop, not mobile.
"""
