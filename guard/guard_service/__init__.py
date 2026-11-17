from datetime import timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, send_from_directory
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

from .models import db, utcnow
from .security import ApiError


def create_app(settings=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("GUARD_SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("GUARD_DATABASE_URL", "sqlite:///guard.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        PUBLIC_URL=os.getenv("GUARD_PUBLIC_URL", "http://127.0.0.1:8088"),
        CP_URL=os.getenv("GUARD_CP_URL", "https://codingprojects.ru"),
        CP_JWT_SECRET=os.getenv("GUARD_CP_JWT_SECRET"),
        CP_JWT_AUDIENCE=os.getenv("GUARD_CP_JWT_AUDIENCE") or None,
        CP_SERVICE_SECRET=os.getenv("GUARD_CP_SERVICE_SECRET"),
        EXAM_SERVICE_SECRET=os.getenv("GUARD_EXAM_SERVICE_SECRET"),
        ROLE_TTL_SECONDS=900, PRESENCE_TTL_SECONDS=20, NOW=utcnow,
        SESSION_COOKIE_NAME="guard_session", SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=1024*1024,
        WEB_DIST=Path(__file__).resolve().parents[1] / "web/dist",
    )
    if settings:
        app.config.update(settings)
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Set GUARD_SECRET_KEY to a random value of at least 32 characters")
    public = urlsplit(app.config["PUBLIC_URL"])
    if public.scheme not in {"http", "https"} or not public.hostname or public.username or public.path not in {"", "/"} or public.query or public.fragment:
        raise RuntimeError("GUARD_PUBLIC_URL must be an HTTPS origin")
    local = public.hostname in {"127.0.0.1", "localhost", "::1"}
    if public.scheme != "https" and not local:
        raise RuntimeError("HTTPS is required outside localhost")
    if local and public.scheme == "http":
        app.config["SESSION_COOKIE_SECURE"] = False
    db.init_app(app)
    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            @event.listens_for(db.engine, "connect")
            def sqlite_foreign_keys(connection, _record):
                connection.execute("PRAGMA foreign_keys=ON")
    from .security import auth
    from .routes import api
    from .agents import agents
    app.register_blueprint(auth)
    app.register_blueprint(api)
    app.register_blueprint(agents)
    from .cli import register
    register(app)

    @app.errorhandler(ApiError)
    def api_error(error):
        db.session.rollback()
        return jsonify(error=error.code), error.status

    @app.errorhandler(IntegrityError)
    @app.errorhandler(StaleDataError)
    def conflict(_error):
        db.session.rollback()
        return jsonify(error="conflict_refresh_required"), 409

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.name.lower().replace(" ", "_")), error.code

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request_path_is_private():
            response.headers["Cache-Control"] = "no-store"
        return response

    def request_path_is_private():
        from flask import request
        return request.path.startswith(("/api/", "/auth/"))

    @app.get("/healthz")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok", service="guard")

    @app.get("/")
    @app.get("/<path:asset>")
    def frontend(asset="index.html"):
        if asset.startswith(("api/", "auth/")):
            raise ApiError("not_found", 404)
        dist = Path(app.config["WEB_DIST"])
        return send_from_directory(dist, asset if (dist/asset).is_file() else "index.html")

    @app.cli.command("init-db")
    def init_db():
        """Create the initial schema for a new Guard database."""
        db.create_all()
        print("Guard schema initialized")

    return app
