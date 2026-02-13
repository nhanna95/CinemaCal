"""Flask application for CinemaCal webapp."""

import logging
from flask import Flask
from flask_cors import CORS

logger = logging.getLogger(__name__)


def create_app():
    """Create and configure Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static"
    )
    
    # Enable CORS for local development
    CORS(app)
    
    # Register blueprints
    from .routes import api_bp
    app.register_blueprint(api_bp)
    
    # Register root route
    @app.route("/")
    def index():
        """Serve the main page."""
        from flask import render_template
        return render_template("index.html")
    
    return app
