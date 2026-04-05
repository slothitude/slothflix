"""SlothFlix Flask web application."""

import hashlib
import os
import threading
from flask import Flask, request, Response, redirect, jsonify, render_template
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

    # Basic auth (set AUTH_USER and AUTH_PASS to enable)
    _auth_user = os.getenv("AUTH_USER", "")
    _auth_pass = os.getenv("AUTH_PASS", "")

    # Paths that skip auth
    _auth_skip = {"/login", "/api/auth/token"}

    def _is_authed():
        # 1. Cookie token
        token = request.cookies.get("slothflix_token")
        if token:
            import cache
            if cache.validate_token(token):
                return True
        # 2. HTTP Basic Auth
        auth = request.authorization
        if auth and _auth_user and _auth_pass:
            if auth.username == _auth_user and auth.password == _auth_pass:
                return True
        return False

    @app.before_request
    def _check_auth():
        # Auto-auth: ?token= in URL → validate, set cookie, redirect to bare path
        url_token = request.args.get("token")
        if url_token:
            import cache
            row = cache.validate_token(url_token)
            if row:
                resp = redirect(request.path)
                resp.set_cookie(
                    "slothflix_token", url_token,
                    max_age=60 * 60 * 24 * int(os.getenv("TOKEN_EXPIRY_DAYS", "7")),
                    httponly=True,
                    samesite="Lax",
                )
                return resp
            # Invalid token in URL → redirect to login
            return redirect("/login")

        if not (_auth_user and _auth_pass):
            return None
        if request.path in _auth_skip:
            return None
        if _is_authed():
            return None
        # Browser request → redirect to login
        if request.accept_mimetypes.accept_html and not request.is_json:
            return redirect("/login")
        return Response(
            "Login required", 401,
            {"WWW-Authenticate": 'Basic realm="SlothFlix"'},
        )

    # Login page
    @app.route("/login")
    def login_page():
        return render_template("login.html")

    # Token auth endpoint
    @app.route("/api/auth/token", methods=["POST"])
    def auth_token():
        data = request.get_json(silent=True) or {}
        token = data.get("token", "").strip()
        if not token:
            return jsonify({"ok": False, "error": "Token required"}), 400
        import cache
        row = cache.validate_token(token)
        if not row:
            return jsonify({"ok": False, "error": "Invalid or expired token"}), 401
        resp = jsonify({"ok": True})
        resp.set_cookie(
            "slothflix_token", token,
            max_age=60 * 60 * 24 * int(os.getenv("TOKEN_EXPIRY_DAYS", "7")),
            httponly=True,
            samesite="Lax",
        )
        return resp

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
        # Pass auth header so JS fetch calls can authenticate
        auth_header = ""
        auth = request.authorization
        if auth and _auth_user and _auth_pass:
            import hashlib
            auth_header = "Basic " + __import__("base64").b64encode(
                f"{auth.username}:{auth.password}".encode()
            ).decode()
        return render_template("index.html", auth_header=auth_header)

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
