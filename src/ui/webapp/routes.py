"""API routes for CinemaCal webapp."""

import logging
from flask import Blueprint, request, jsonify, send_file
from datetime import date, datetime
import tempfile
import os

from ...models import ScraperConfig, Screening
from ...export.ics import export_to_ics
from ...export.google_calendar import (
    is_google_calendar_configured,
    export_to_google_calendar,
    get_setup_instructions,
    list_events,
    list_events_from_calendars,
    delete_event,
    add_screening_to_calendar,
    get_movie_screenings_calendar_id,
    get_calendar_list,
)
from ...export.ics import get_import_instructions
from .tasks import start_scrape_job, get_job_status, serialize_job_status, filter_regular_coolidge

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/status", methods=["GET"])
def status():
    """Check server status."""
    return jsonify({"status": "ok", "message": "CinemaCal API is running"})


@api_bp.route("/scrape", methods=["POST"])
def scrape():
    """Start a scraping job."""
    try:
        data = request.get_json() or {}
        
        # Build config from request
        config = ScraperConfig()
        config.days_ahead = int(data.get("days_ahead", 30))
        config.enable_screen_boston = data.get("enable_screen_boston", True)
        config.enable_coolidge = data.get("enable_coolidge", True)
        config.enable_hfa = data.get("enable_hfa", True)
        config.enable_brattle = data.get("enable_brattle", True)
        
        # Start job
        job_id = start_scrape_job(config)
        
        return jsonify({
            "job_id": job_id,
            "status": "pending",
            "message": "Scraping started"
        })
        
    except Exception as e:
        logger.error(f"Error starting scrape: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/scrape/<job_id>/status", methods=["GET"])
def scrape_status(job_id: str):
    """Get status of a scraping job."""
    job = get_job_status(job_id)
    
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    return jsonify(serialize_job_status(job))


@api_bp.route("/screenings", methods=["GET"])
def get_screenings():
    """Get screenings from a completed job."""
    job_id = request.args.get("job_id")
    
    if not job_id:
        return jsonify({"error": "job_id parameter required"}), 400
    
    job = get_job_status(job_id)
    
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.status != "complete":
        return jsonify({"error": f"Job not complete (status: {job.status})"}), 400
    
    # Apply filters if provided
    screenings = job.screenings
    venue_filter = request.args.get("venue")
    search_filter = request.args.get("search", "").lower()
    
    filtered = []
    for screening in screenings:
        if venue_filter and venue_filter != "All" and screening.venue != venue_filter:
            continue
        if search_filter and search_filter not in screening.title.lower():
            continue
        filtered.append(screening)
    
    exclude_regular = request.args.get("exclude_regular_coolidge", "").lower() in ("1", "true", "yes")
    if exclude_regular:
        filtered = filter_regular_coolidge(filtered)
    
    # Sort by earliest to latest (date, then time)
    filtered.sort(key=lambda s: (s.date, s.time))
    
    from .tasks import serialize_screening
    return jsonify({
        "screenings": [serialize_screening(s) for s in filtered],
        "count": len(filtered)
    })


@api_bp.route("/venues", methods=["GET"])
def get_venues():
    """Get list of unique venues from a completed job."""
    job_id = request.args.get("job_id")
    
    if not job_id:
        return jsonify({"error": "job_id parameter required"}), 400
    
    job = get_job_status(job_id)
    
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.status != "complete":
        return jsonify({"error": f"Job not complete (status: {job.status})"}), 400
    
    venues = sorted(set(s.venue for s in job.screenings))
    return jsonify({"venues": venues})


@api_bp.route("/export/ics", methods=["POST"])
def export_ics():
    """Export selected screenings to .ics file."""
    try:
        data = request.get_json()
        
        if not data or "screenings" not in data:
            return jsonify({"error": "screenings array required"}), 400
        
        # Reconstruct Screening objects from JSON
        screenings = []
        for s_data in data["screenings"]:
            screening = Screening(
                title=s_data["title"],
                venue=s_data["venue"],
                date=date.fromisoformat(s_data["date"]),
                time=datetime.strptime(s_data["time"], "%H:%M:%S").time(),
                source_url=s_data["source_url"],
                source_site=s_data["source_site"],
                runtime_minutes=s_data.get("runtime_minutes"),
                director=s_data.get("director"),
                year=s_data.get("year"),
                extra=s_data.get("extra"),
                special_attributes=s_data.get("special_attributes") or None,
            )
            screenings.append(screening)
        
        # Create temporary file
        fd, filepath = tempfile.mkstemp(suffix=".ics")
        os.close(fd)
        
        try:
            # Export to file
            export_to_ics(screenings, filepath)
            
            # Send file
            return send_file(
                filepath,
                mimetype="text/calendar",
                as_attachment=True,
                download_name="screenings.ics"
            )
        finally:
            # Clean up temp file after sending
            try:
                os.unlink(filepath)
            except:
                pass
        
    except Exception as e:
        logger.error(f"Error exporting ICS: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/export/google", methods=["POST"])
def export_google():
    """Export selected screenings to Google Calendar."""
    try:
        if not is_google_calendar_configured():
            return jsonify({
                "error": "Google Calendar API not configured",
                "configured": False
            }), 400
        
        data = request.get_json()
        
        if not data or "screenings" not in data:
            return jsonify({"error": "screenings array required"}), 400
        
        # Reconstruct Screening objects from JSON
        screenings = []
        for s_data in data["screenings"]:
            screening = Screening(
                title=s_data["title"],
                venue=s_data["venue"],
                date=date.fromisoformat(s_data["date"]),
                time=datetime.strptime(s_data["time"], "%H:%M:%S").time(),
                source_url=s_data["source_url"],
                source_site=s_data["source_site"],
                runtime_minutes=s_data.get("runtime_minutes"),
                director=s_data.get("director"),
                year=s_data.get("year"),
                extra=s_data.get("extra"),
                special_attributes=s_data.get("special_attributes") or None,
            )
            screenings.append(screening)
        
        # Export to Google Calendar
        success, failed = export_to_google_calendar(screenings)
        
        return jsonify({
            "success": success,
            "failed": failed,
            "total": len(screenings)
        })
        
    except Exception as e:
        logger.error(f"Error exporting to Google Calendar: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/calendar/list", methods=["GET"])
def get_calendar_list_route():
    """Get list of user's Google Calendars."""
    if not is_google_calendar_configured():
        return jsonify({
            "error": "Google Calendar API not configured",
            "configured": False,
        }), 400
    try:
        calendars = get_calendar_list()
        return jsonify({"calendars": calendars})
    except Exception as e:
        logger.error(f"Error getting calendar list: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/calendar/target", methods=["GET"])
def get_calendar_target():
    """Get the calendar ID (and name) used for adding screenings (Movie Screenings)."""
    if not is_google_calendar_configured():
        return jsonify({
            "error": "Google Calendar API not configured",
            "configured": False,
        }), 400
    try:
        calendar_id = get_movie_screenings_calendar_id()
        calendars = get_calendar_list()
        summary = calendar_id
        for cal in calendars:
            if cal.get("id") == calendar_id:
                summary = cal.get("summaryOverride") or cal.get("summary") or calendar_id
                break
        return jsonify({"calendar_id": calendar_id, "summary": summary})
    except Exception as e:
        logger.error(f"Error getting target calendar: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/calendar/events", methods=["GET"])
def get_calendar_events():
    """Get user's Google Calendar events for a time range, from one or more calendars."""
    if not is_google_calendar_configured():
        return jsonify({
            "error": "Google Calendar API not configured",
            "configured": False,
        }), 400
    time_min_s = request.args.get("time_min")
    time_max_s = request.args.get("time_max")
    if not time_min_s or not time_max_s:
        return jsonify({"error": "time_min and time_max query parameters required"}), 400
    try:
        time_min = date.fromisoformat(time_min_s) if len(time_min_s) <= 10 else datetime.fromisoformat(time_min_s.replace("Z", "+00:00"))
        time_max = date.fromisoformat(time_max_s) if len(time_max_s) <= 10 else datetime.fromisoformat(time_max_s.replace("Z", "+00:00"))
    except ValueError:
        return jsonify({"error": "time_min and time_max must be ISO date or datetime strings"}), 400
    calendar_ids_param = request.args.get("calendar_ids")
    if calendar_ids_param:
        calendar_ids = [x.strip() for x in calendar_ids_param.split(",") if x.strip()]
    else:
        calendars = get_calendar_list()
        calendar_ids = [c["id"] for c in calendars] if calendars else ["primary"]
    try:
        events = list_events_from_calendars(calendar_ids, time_min=time_min, time_max=time_max)
        return jsonify({"events": events})
    except Exception as e:
        logger.error(f"Error listing calendar events: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/calendar/events", methods=["POST"])
def add_calendar_event():
    """Add a single screening to Google Calendar."""
    if not is_google_calendar_configured():
        return jsonify({
            "error": "Google Calendar API not configured",
            "configured": False,
        }), 400
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body with screening data required"}), 400
    try:
        screening = Screening(
            title=data["title"],
            venue=data["venue"],
            date=date.fromisoformat(data["date"]),
            time=datetime.strptime(data["time"], "%H:%M:%S").time(),
            source_url=data["source_url"],
            source_site=data["source_site"],
            runtime_minutes=data.get("runtime_minutes"),
            director=data.get("director"),
            year=data.get("year"),
            extra=data.get("extra"),
            special_attributes=data.get("special_attributes") or None,
        )
    except (KeyError, ValueError) as e:
        return jsonify({"error": f"Invalid screening data: {e}"}), 400
    try:
        event_id = add_screening_to_calendar(screening)
        if event_id is None:
            return jsonify({"error": "Failed to add event to Google Calendar"}), 500
        return jsonify({"event_id": event_id})
    except Exception as e:
        logger.error(f"Error adding calendar event: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/calendar/events/<event_id>", methods=["DELETE"])
def remove_calendar_event(event_id: str):
    """Remove an event from Google Calendar. Requires calendar_id query param."""
    if not is_google_calendar_configured():
        return jsonify({
            "error": "Google Calendar API not configured",
            "configured": False,
        }), 400
    if not event_id:
        return jsonify({"error": "event_id required"}), 400
    calendar_id = request.args.get("calendar_id")
    if not calendar_id:
        return jsonify({"error": "calendar_id query parameter required"}), 400
    try:
        if delete_event(calendar_id, event_id):
            return "", 204
        return jsonify({"error": "Failed to delete event"}), 500
    except Exception as e:
        logger.error(f"Error deleting calendar event: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/config", methods=["GET"])
def get_config():
    """Get current scraper configuration options."""
    return jsonify({
        "google_calendar_configured": is_google_calendar_configured(),
    })


@api_bp.route("/instructions/import", methods=["GET"])
def get_import_instructions():
    """Get instructions for importing .ics file."""
    return jsonify({"instructions": get_import_instructions()})


@api_bp.route("/instructions/google", methods=["GET"])
def get_google_setup_instructions():
    """Get instructions for setting up Google Calendar API."""
    return jsonify({"instructions": get_setup_instructions()})
