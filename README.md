# CinemaCal

A Python application that scrapes movie screenings from Boston-area independent theaters and exports them to your calendar.

## Features

- **Multi-source scraping**: Fetches screenings from four Boston-area theater websites:
  - Screen Boston (aggregates multiple theaters)
  - Coolidge Corner Theatre
  - Harvard Film Archive
  - The Brattle Theatre

- **Selection UI**: Browse and select screenings using a graphical interface

- **Calendar export**: Export selected screenings as:
  - `.ics` file (compatible with Google Calendar, Apple Calendar, Outlook, etc.)
  - Direct Google Calendar API integration (optional)

## Installation

### Requirements

- Python 3.9+
- Dependencies in `requirements.txt` (install with `pip install -r requirements.txt`)

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/nhanna95/CinemaCal.git
   cd CinemaCal
   ```

2. Create and use the virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # macOS/Linux
   pip install -r requirements.txt
   ```
   Or in Cursor: run the **Setup venv (install deps)** task first.

3. For Landmark Theatre support (optional), install Playwright browsers:
   ```bash
   ./venv/bin/playwright install chromium
   ```
   Or run the **Install Playwright browsers (for Landmark)** Cursor task.  
   If you see "Executable doesn't exist" when scraping Landmark, run this step.

## Usage

### Running the Application

**Option 1: Cursor / VS Code task**

1. Open the project in Cursor (or VS Code).
2. Run **Terminal → Run Task…** (or `Cmd+Shift+P` → "Tasks: Run Task").
3. Choose **Start CinemaCal**.
4. Open your browser and go to the URL shown in the terminal (e.g. `http://localhost:5000`). If you get "Access denied" (403) when using `127.0.0.1`, try `http://localhost:5000` instead.

**Option 2: Command line**

```bash
# From project root, with venv active:
source venv/bin/activate   # macOS/Linux
python main.py
```

Or run the venv Python directly:

```bash
./venv/bin/python main.py
```

The server will start on `http://127.0.0.1:5000` by default; the app will open `http://localhost:5000` in your browser (same server, often avoids 403 from security software). You can customize the host and port:

```bash
python main.py --host 0.0.0.0 --port 8080
```

### If you get "Access denied" (HTTP 403)

The app does not return 403 for normal requests. If you see "Access to localhost was denied" or "Access to 127.0.0.1 was denied", the block is usually from the browser, an extension, or system security.

1. **Try a different port** (in case something is blocking 5000):
   ```bash
   python main.py --port 5050
   ```
   Then open `http://localhost:5050` in your browser.

2. **Check whether the server is responding** (in a new terminal while the app is running):
   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/
   ```
   If you see `200`, the server is fine and the 403 is from the browser or an extension.

3. **Try a private/incognito window** (disables most extensions).

4. **Try another browser** (e.g. Safari if you use Chrome, or vice versa).

5. **Temporarily disable browser extensions** that might block localhost (e.g. ad blockers, privacy tools).

6. **Bind to all interfaces and use 127.0.0.1**:
   ```bash
   python main.py --host 0.0.0.0 --port 5000
   ```
   Then open `http://127.0.0.1:5000` in your browser.

### Using the Interface

1. **Select sources**: Check/uncheck which theater websites to scrape

2. **Set date range**: Enter the number of days ahead to search (default: 30)

3. **Click "Scrape"**: The app will fetch screenings from all selected sources

4. **Browse and select**: 
   - Click the checkbox column to select/deselect screenings
   - Use filters to narrow down by venue or search by title
   - Use "Select All" / "Deselect All" buttons for bulk selection

5. **Export**:
   - Click "Export to .ics" to save a calendar file
   - Click "Add to Google Calendar" for direct API integration (requires setup)

### Importing the .ics File

After exporting, import the `.ics` file to Google Calendar:

1. Open [Google Calendar](https://calendar.google.com) on desktop
2. Click Settings (gear icon) → Settings
3. Click "Import & Export" in the sidebar
4. Click "Select file from your computer"
5. Choose your exported `.ics` file
6. Click "Import"

## Google Calendar API Setup (Optional)

For direct Google Calendar integration:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the Google Calendar API
3. Create OAuth2 credentials (Desktop application)
4. Download the credentials JSON file
5. Save it as `config/credentials.json` in this project (create the `config` folder if needed)

On first use, you'll be prompted to authorize access in your browser.

For optional settings (e.g. custom calendar ID or token path), copy `.env.example` to `.env` and edit as needed.

The Calendar view can show events from multiple calendars (e.g. meetings, classes, movie screenings). Use the "Calendars to show" checkboxes in Calendar view to choose which calendars to display. New screenings are always added to your **Movie Screenings** calendar (or the calendar set in `GOOGLE_CALENDAR_ID` in `.env` if you use a different name).

## Project Structure

```
CinemaCal/
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── README.md
├── LICENSE                 # MIT License
├── .env.example            # Optional env vars (copy to .env)
├── config/                 # Create this for Google Calendar (credentials.json, token.json)
└── src/
    ├── models.py           # Data models (Screening, ScraperConfig)
    ├── scrapers/           # Theater website scrapers
    │   ├── base.py         # Base scraper with common utilities
    │   ├── screen_boston.py
    │   ├── coolidge.py
    │   ├── harvard_film_archive.py
    │   ├── brattle.py
    │   └── landmark.py     # Requires Playwright
    ├── export/             # Calendar export modules
    │   ├── ics.py          # .ics file export
    │   └── google_calendar.py
    └── ui/
        └── webapp/         # Webapp
            ├── app.py      # Flask application
            ├── routes.py   # API routes
            ├── tasks.py    # Background scraping tasks
            ├── templates/
            │   └── index.html
            └── static/
                ├── css/
                │   └── style.css
                └── js/
                    └── app.js
```

## Dependencies

- **requests** - HTTP requests for scraping
- **beautifulsoup4** - HTML parsing
- **lxml** - Fast HTML parser
- **playwright** - Browser automation for JavaScript-heavy sites (optional)
- **icalendar** - .ics file generation
- **pytz** - Timezone handling
- **flask** - Web framework
- **flask-cors** - CORS support
- **google-api-python-client** - Google Calendar API (optional)
- **google-auth-oauthlib** - Google OAuth (optional)

## Notes

- The Landmark scraper requires Playwright and is optional. If Playwright is not installed, the Landmark checkbox will be disabled.

- Screen Boston aggregates screenings from multiple theaters, so you may see some overlap with direct theater scrapers. Duplicates are filtered when displaying results.

- Scraping accuracy depends on the structure of each website. If a website changes its format, the corresponding scraper may need updates.

## License

[MIT License](LICENSE) — feel free to modify and distribute.
