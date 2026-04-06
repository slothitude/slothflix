"""SlothFlix Flask web application."""

import hashlib
import json
import os
import subprocess
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
    _auth_skip = {"/login", "/api/auth/token", "/chat-login", "/mail-login"}

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

    # Favicon
    @app.route("/favicon.ico")
    def favicon():
        from flask import Response as _Resp
        logo = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sloth_logo.png")
        if os.path.exists(logo):
            with open(logo, "rb") as f:
                blob = f.read()
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(blob))
                img.thumbnail((32, 32), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="ICO", sizes=[(16, 16), (32, 32)])
                return _Resp(buf.getvalue(), mimetype="image/x-icon")
            except Exception:
                return _Resp(blob, mimetype="image/png")
        return "", 404

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

    # --- Chat & Mail auto-login helpers ---

    def _get_telegram_user():
        """Get telegram_user_id and telegram_username from cookie token."""
        token = request.cookies.get("slothflix_token")
        if not token:
            return None
        import cache
        row = cache.validate_token(token)
        if not row:
            return None
        return row.get("telegram_user_id"), row.get("telegram_username")

    def _user_password(user_id):
        """Deterministic password from telegram user ID."""
        return hashlib.sha256(f"slothflix-{user_id}".encode()).hexdigest()[:16]

    def _docker_ip(container_name):
        """Get the Docker bridge IP of a container."""
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        if not ip:
            return None
        return ip

    # --- Chat (Open WebUI) auto-login ---

    @app.route("/chat-login")
    def chat_login():
        user = _get_telegram_user()
        if not user:
            return redirect("/login")
        user_id, username = user
        email = f"{user_id}@slothflix"
        password = _user_password(user_id)
        name = username or f"User {user_id}"

        container_ip = _docker_ip("open-webui")
        if not container_ip:
            return redirect("/chat/")

        base = f"http://{container_ip}:8080"
        import urllib.request
        import urllib.error

        # Try sign-in first, fallback to sign-up
        jwt = None
        for endpoint, payload in [
            ("/api/v1/auths/signin", {"email": email, "password": password}),
            ("/api/v1/auths/signup", {"email": email, "password": password, "name": name}),
        ]:
            try:
                req = urllib.request.Request(
                    f"{base}{endpoint}",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read())
                jwt = data.get("token") or data.get("jwt")
                if jwt:
                    break
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue

        resp = redirect("/chat/")
        if jwt:
            resp.set_cookie("token", jwt, httponly=False, samesite="Lax", path="/chat/")
        return resp

    # --- Mail (Poste.io) auto-login ---

    @app.route("/mail-login")
    def mail_login():
        user = _get_telegram_user()
        if not user:
            return redirect("/login")
        user_id, username = user
        domain = "slothitude.giize.com"
        email = f"{username}@{domain}" if username else f"{user_id}@{domain}"
        password = _user_password(user_id)

        container_ip = _docker_ip("poste")
        if not container_ip:
            return redirect("/mail/")

        base = f"http://{container_ip}"
        import urllib.request
        import urllib.error

        # Try to provision the mailbox via Poste admin API (ignore errors if exists)
        try:
            admin_payload = {
                "email": email,
                "password": password,
                "name": username or f"User {user_id}",
            }
            req = urllib.request.Request(
                f"{base}/admin/api/mailboxes",
                data=json.dumps(admin_payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

        # Redirect to webmail — poste webmail has its own login form
        # Use auto-login via hash fragment if supported, otherwise just redirect
        resp = redirect(f"/mail/webmail/#/login?email={email}")
        return resp

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
