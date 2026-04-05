"""SlothFlix Flask web application."""

import os
import threading
from flask import Flask
from .api import api_bp
from .stream import stream_bp


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    )

    # Config
    app.config["DOWNLOAD_DIR"] = os.getenv("DOWNLOAD_DIR", "/downloads")
    app.config["CACHE_DB_PATH"] = os.getenv("CACHE_DB_PATH", "cache.db")

    # Init cache DB
    import cache
    cache.DB_PATH = app.config["CACHE_DB_PATH"]
    cache.init_db()

    # Register blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(stream_bp)

    # Serve static files
    @app.route("/static/<path:filename>")
    def static_files(filename):
        from flask import send_from_directory
        return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), filename)

    # Serve frontend
    @app.route("/")
    def index():
        from flask import render_template
        return render_template("index.html")

    # Trailer pre-roll: refresh on startup, then daily
    _schedule_trailer_refresh()

    return app


def _schedule_trailer_refresh():
    import trailers
    threading.Thread(target=trailers.refresh_trailers_if_stale, daemon=True).start()

    def _daily():
        while True:
            import time
            time.sleep(86400)
            trailers.refresh_trailers_if_stale()

    threading.Thread(target=_daily, daemon=True).start()
