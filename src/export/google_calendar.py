"""Export screenings to Google Calendar via API."""

import logging
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Any

from ..models import Screening

logger = logging.getLogger(__name__)

# Calendar name we add events to
MOVIE_SCREENINGS_CALENDAR_NAME = "Movie Screenings"

# Try to import Google API libraries
GOOGLE_API_AVAILABLE = False
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    logger.info("Google API libraries not installed - Google Calendar export will be disabled")

# OAuth2 scope: full calendar access (required to list calendars and add events)
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Default paths for credentials (project config directory)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CREDENTIALS_PATH = _PROJECT_ROOT / "config" / "credentials.json"
DEFAULT_TOKEN_PATH = _PROJECT_ROOT / "config" / "token.json"


def is_google_calendar_configured() -> bool:
    """Check if Google Calendar API is configured and available."""
    if not GOOGLE_API_AVAILABLE:
        return False
    
    # Check for credentials file
    credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_CREDENTIALS_PATH))
    if not Path(credentials_path).exists():
        return False
    
    return True


def get_credentials() -> Optional['Credentials']:
    """Get or refresh Google API credentials."""
    if not GOOGLE_API_AVAILABLE:
        return None
    
    credentials_path = Path(os.environ.get("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_CREDENTIALS_PATH)))
    token_path = Path(os.environ.get("GOOGLE_TOKEN_PATH", str(DEFAULT_TOKEN_PATH)))
    
    if not credentials_path.exists():
        logger.error(f"Google credentials not found at {credentials_path}")
        logger.info("To set up Google Calendar API:")
        logger.info("1. Go to https://console.cloud.google.com/")
        logger.info("2. Create a project and enable the Google Calendar API")
        logger.info("3. Create OAuth2 credentials (Desktop application)")
        logger.info("4. Download the credentials JSON file")
        logger.info(f"5. Save it to {credentials_path}")
        return None
    
    creds = None
    
    # Load existing token if available
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load saved credentials: {e}")
    
    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Failed to refresh credentials: {e}")
                creds = None
        
        if not creds:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                logger.error(f"Failed to get new credentials: {e}")
                return None
        
        # Save the credentials for next time
        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as token:
                token.write(creds.to_json())
        except Exception as e:
            logger.warning(f"Failed to save credentials: {e}")
    
    return creds


def _format_tags_for_title(special_attributes: Optional[List[str]]) -> str:
    """Extract format-style tags (35mm, 70mm, etc.) for appending to event title."""
    if not special_attributes:
        return ""
    # Format tags: *mm (35mm, 70mm, 16mm) or "Screening on film"
    format_tags = []
    for attr in special_attributes:
        a = attr.strip()
        if not a:
            continue
        if a.endswith("mm") and len(a) <= 5 and a[:-2].isdigit():
            format_tags.append(a)
        elif a == "Screening on film":
            format_tags.append(a)
    if not format_tags:
        return ""
    return " (" + ", ".join(format_tags) + ")"


def create_google_event(screening: Screening) -> dict:
    """Create a Google Calendar event from a Screening."""
    start_dt = datetime.combine(screening.date, screening.time)
    # Duration: runtime + 10 min per movie (e.g. +20 for double feature)
    extra_minutes = 20 if (screening.special_attributes and "Double feature" in screening.special_attributes) else 10
    end_dt = screening.datetime_end + timedelta(minutes=extra_minutes)

    summary = f"{screening.title} @ {screening.venue}"
    format_tags = _format_tags_for_title(screening.special_attributes)
    if format_tags:
        summary += format_tags

    event = {
        "summary": summary,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "America/New_York",
        },
    }

    # Tag so we can match events to screenings when listing
    event["extendedProperties"] = {
        "private": {"cinemacal_screening_id": screening.unique_id}
    }

    return event


def export_to_google_calendar(
    screenings: List[Screening],
    calendar_id: Optional[str] = None,
) -> tuple[int, int]:
    """Export screenings to Google Calendar.

    Args:
        screenings: List of Screening objects to export
        calendar_id: Google Calendar ID (default: resolve 'Movie Screenings' by name)

    Returns:
        Tuple of (success_count, failure_count)
    """
    if not GOOGLE_API_AVAILABLE:
        logger.error("Google API libraries not installed")
        return 0, len(screenings)

    if not screenings:
        logger.warning("No screenings to export")
        return 0, 0

    if calendar_id is None:
        calendar_id = get_movie_screenings_calendar_id()

    creds = get_credentials()
    if not creds:
        logger.error("Failed to get Google Calendar credentials")
        return 0, len(screenings)

    try:
        service = build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service: {e}")
        return 0, len(screenings)

    success_count = 0
    failure_count = 0

    for screening in screenings:
        try:
            event = create_google_event(screening)
            service.events().insert(calendarId=calendar_id, body=event).execute()
            success_count += 1
            logger.debug(f"Added event: {screening.title}")
        except HttpError as e:
            logger.error(f"Failed to add event '{screening.title}': {e}")
            failure_count += 1
        except Exception as e:
            logger.error(f"Unexpected error adding '{screening.title}': {e}")
            failure_count += 1
    
    logger.info(f"Google Calendar export complete: {success_count} added, {failure_count} failed")
    return success_count, failure_count


def _to_rfc3339(dt: Any, end_of_day: bool = False) -> str:
    """Convert datetime or date to RFC3339 string (America/New_York)."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        if end_of_day:
            dt = datetime.combine(dt, datetime.max.time().replace(microsecond=0))
        else:
            dt = datetime.combine(dt, datetime.min.time())
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"


def list_events(
    calendar_id: str = "primary",
    time_min: Optional[Any] = None,
    time_max: Optional[Any] = None,
) -> List[dict]:
    """List events in a calendar for a time range.

    Args:
        calendar_id: Google Calendar ID (default: primary)
        time_min: Start of range (date or datetime)
        time_max: End of range (date or datetime)

    Returns:
        List of dicts with id, summary, start, end, and cinemacal_screening_id if present
    """
    if not GOOGLE_API_AVAILABLE:
        return []

    creds = get_credentials()
    if not creds:
        return []

    try:
        service = build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service: {e}")
        return []

    if time_min is None:
        time_min = datetime.now()
    if time_max is None:
        time_max = datetime.now() + timedelta(days=30)

    time_min_str = _to_rfc3339(time_min)
    time_max_str = _to_rfc3339(time_max, end_of_day=True)

    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min_str,
                timeMax=time_max_str,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as e:
        logger.error(f"Failed to list events: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error listing events: {e}")
        return []

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        start_str = start.get("dateTime") or start.get("date", "")
        end_str = end.get("dateTime") or end.get("date", "")
        ext = item.get("extendedProperties", {}) or {}
        private = ext.get("private", {}) or {}
        cinemacal_screening_id = private.get("cinemacal_screening_id")
        events.append(
            {
                "id": item["id"],
                "summary": item.get("summary", ""),
                "start": start_str,
                "end": end_str,
                "cinemacal_screening_id": cinemacal_screening_id,
            }
        )
    return events


def list_events_from_calendars(
    calendar_ids: List[str],
    time_min: Optional[Any] = None,
    time_max: Optional[Any] = None,
) -> List[dict]:
    """List events from multiple calendars, merged and sorted by start time.

    Each event dict includes calendar_id and calendar_summary (from calendar list).
    """
    if not calendar_ids:
        return []
    calendars_by_id = {c["id"]: c for c in get_calendar_list()}
    all_events = []
    for cid in calendar_ids:
        events = list_events(calendar_id=cid, time_min=time_min, time_max=time_max)
        cal = calendars_by_id.get(cid, {})
        summary = cal.get("summaryOverride") or cal.get("summary") or cid
        for ev in events:
            ev = dict(ev)
            ev["calendar_id"] = cid
            ev["calendar_summary"] = summary
            all_events.append(ev)
    # Sort by start time (string comparison is ok for ISO-ish strings)
    all_events.sort(key=lambda e: e.get("start", "") or "")
    return all_events


def delete_event(calendar_id: str, event_id: str) -> bool:
    """Delete an event from a calendar.

    Args:
        calendar_id: Google Calendar ID (default: primary)
        event_id: Google Calendar event ID

    Returns:
        True if deleted, False on error
    """
    if not GOOGLE_API_AVAILABLE:
        return False

    creds = get_credentials()
    if not creds:
        return False

    try:
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True
    except HttpError as e:
        logger.error(f"Failed to delete event {event_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting event {event_id}: {e}")
        return False


def add_screening_to_calendar(
    screening: Screening,
    calendar_id: Optional[str] = None,
) -> Optional[str]:
    """Add a single screening to Google Calendar.

    Args:
        screening: Screening to add
        calendar_id: Google Calendar ID (default: resolve 'Movie Screenings' by name)

    Returns:
        Created event id, or None on failure
    """
    if not GOOGLE_API_AVAILABLE:
        return None

    if calendar_id is None:
        calendar_id = get_movie_screenings_calendar_id()

    creds = get_credentials()
    if not creds:
        return None

    try:
        service = build("calendar", "v3", credentials=creds)
        event = create_google_event(screening)
        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        return created.get("id")
    except HttpError as e:
        logger.error(f"Failed to add event '{screening.title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error adding '{screening.title}': {e}")
        return None


def get_calendar_list() -> List[dict]:
    """Get list of user's Google Calendars.

    Returns:
        List of calendar dictionaries with 'id', 'summary', and 'summaryOverride'
    """
    if not GOOGLE_API_AVAILABLE:
        return []

    creds = get_credentials()
    if not creds:
        return []

    try:
        service = build("calendar", "v3", credentials=creds)
        calendars = []
        page_token = None
        while True:
            calendars_result = service.calendarList().list(
                pageToken=page_token,
                maxResults=250,
            ).execute()
            items = calendars_result.get("items", [])
            for cal in items:
                calendars.append({
                    "id": cal["id"],
                    "summary": cal.get("summary", cal["id"]),
                    "summaryOverride": cal.get("summaryOverride"),
                })
            page_token = calendars_result.get("nextPageToken")
            if not page_token:
                break
        return calendars
    except Exception as e:
        logger.error(f"Failed to get calendar list: {e}")
        return []


def get_movie_screenings_calendar_id() -> str:
    """Return the calendar ID for 'Movie Screenings', or 'primary' if not found.

    Uses GOOGLE_CALENDAR_ID env var if set; otherwise finds a calendar whose
    name (summary or summaryOverride) matches 'Movie Screenings' case-insensitively.
    """
    if not GOOGLE_API_AVAILABLE:
        return "primary"
    override_id = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
    if override_id:
        logger.info("Using calendar id from GOOGLE_CALENDAR_ID: %s", override_id)
        return override_id
    target = MOVIE_SCREENINGS_CALENDAR_NAME.strip().lower()
    if not target:
        return "primary"
    calendars = get_calendar_list()
    for cal in calendars:
        summary = (cal.get("summary") or "").strip().lower()
        override = (cal.get("summaryOverride") or "").strip().lower()
        if summary == target or override == target:
            logger.info("Using calendar '%s' (id=%s)", MOVIE_SCREENINGS_CALENDAR_NAME, cal["id"])
            return cal["id"]
    logger.warning(
        "Calendar '%s' not found; using primary. Create a calendar named exactly '%s' to use it, or set GOOGLE_CALENDAR_ID to the calendar id.",
        MOVIE_SCREENINGS_CALENDAR_NAME,
        MOVIE_SCREENINGS_CALENDAR_NAME,
    )
    return "primary"


def get_setup_instructions() -> str:
    """Get instructions for setting up Google Calendar API."""
    return """
To set up Google Calendar API integration:

1. Go to the Google Cloud Console:
   https://console.cloud.google.com/

2. Create a new project (or select an existing one)

3. Enable the Google Calendar API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Calendar API"
   - Click "Enable"

4. Create OAuth2 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop application"
   - Give it a name and click "Create"

5. Download the credentials:
   - Click the download icon next to your new credentials
   - Save the file as "credentials.json"

6. Place the credentials file at config/credentials.json in this project.
   Or set the GOOGLE_CREDENTIALS_PATH environment variable.

7. On first use, you'll be prompted to authorize the app
   in your browser.

Note: The free tier of Google Cloud is sufficient for personal use.
"""
