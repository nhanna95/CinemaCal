#!/usr/bin/env python3
"""Main entry point for CinemaCal app."""

import logging
import argparse
import webbrowser
import threading
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

def open_browser(url, delay=2):
    """Open the browser after a short delay."""
    time.sleep(delay)
    webbrowser.open(url)

def main():
    """Run the CinemaCal webapp."""
    parser = argparse.ArgumentParser(description="CinemaCal - Scrape movie screenings and export to calendar")
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for webapp server (default: 5000)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for webapp server (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't automatically open the browser"
    )
    
    args = parser.parse_args()
    
    from src.ui.webapp.app import create_app
    
    app = create_app()
    url = f"http://{args.host}:{args.port}"
    # Prefer localhost in browser to avoid 403 from software that blocks 127.0.0.1
    browser_url = f"http://localhost:{args.port}" if args.host == "127.0.0.1" else url
    
    print(f"\n{'='*60}")
    print("CinemaCal Webapp")
    print(f"{'='*60}")
    print(f"Server running at: {url}")
    print(f"Open this URL in your browser: {browser_url}")
    print(f"{'='*60}\n")
    
    # Open browser automatically unless --no-browser flag is set
    if not args.no_browser:
        browser_thread = threading.Thread(target=open_browser, args=(browser_url,), daemon=True)
        browser_thread.start()
    
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
