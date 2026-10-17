"""SKrapkin web interface: a small JSON API plus a static single-page UI.

Security model: meant for localhost or a trusted team. Every request must have an allowed Host header
(defeats DNS rebinding), every change must carry a custom header (a web page on another site cannot send
one without a CORS preflight, which is never granted), and an optional password protects shared use.
"""

import csv
import hmac
import io
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory
from pymongo import errors as mongo_errors
from pymongo.uri_parser import parse_uri
from werkzeug.exceptions import HTTPException

from .. import __version__, config, jobs
from .. import regions as geo
from ..csvsafe import safe_row
from ..hunter import HunterClient, HunterError, InvalidKey
from ..verifier import build_plan
from .tasks import Busy, TaskManager

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{10,200}$")
STATUSES = {"unchecked", "filtered", "webmail", "valid", "invalid", "accept_all", "unknown", "claimed"}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def describe_error(error):
    """Plain-language message for an exception. Never echoes connection strings or keys."""
    if isinstance(error, InvalidKey):
        return "Hunter rejected the API key. Re-enter it on the Verify tab."
    if isinstance(error, HunterError):
        return str(error)
    if isinstance(error, mongo_errors.ServerSelectionTimeoutError):
        return "Couldn't reach the database. Check that MongoDB is running and the address is right."
    if isinstance(error, mongo_errors.OperationFailure) and getattr(error, "code", None) in (13, 18):
        return "The database rejected the username or password."
    if isinstance(error, (mongo_errors.InvalidURI, mongo_errors.ConfigurationError)):
        return "That database address isn't valid."
    if isinstance(error, mongo_errors.PyMongoError):
        return "The database returned an error. Check that it is running."
    if isinstance(error, (PermissionError, NotADirectoryError, FileNotFoundError, OSError)):
        return ("SKrapkin can't write to its output folder. Check that the folder exists and that the "
                "program is allowed to write there.")
    if isinstance(error, RuntimeError) and "Overpass" in str(error):
        return ("Couldn't reach the business database (OpenStreetMap). Check your internet connection "
                "and try again in a minute.")
    return f"Something went wrong ({type(error).__name__})."


def hostname(host_header):
    host = host_header.strip().lower()
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]


def iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def lead_out(lead):
    return {
        "key": lead["key"], "business": lead.get("business", ""), "website": lead.get("website", ""),
        "category": lead.get("category", ""), "country": lead.get("country", ""),
        "region": lead.get("region", ""), "city": lead.get("city", ""),
        "confidence": lead.get("confidence", ""), "phones": lead.get("phones", []),
        "emails": [{k: e.get(k) for k in ("address", "status", "source", "note", "likelihood")}
                   for e in lead.get("emails", [])],
        "updated_at": iso(lead.get("updated_at")),
    }


def verified_out(doc):
    return {"email": doc["email"], "business": doc.get("business", ""), "website": doc.get("website", ""),
            "country": doc.get("country", ""), "region": doc.get("region", ""), "city": doc.get("city", ""),
            "category": doc.get("category", ""),
            "phones": doc.get("phones", []), "score": doc.get("score"), "verified_at": iso(doc.get("verified_at"))}


class Services:
    """Shared config and database connection."""

    def __init__(self, cfg=None):
        self.cfg = cfg or config.Config.load()
        self.db = None
        self.error = ""
        self.connected = False
        self._lock = threading.Lock()
        self._last_attempt = 0.0

    def connect(self):
        with self._lock:
            self._last_attempt = time.monotonic()
            if self.db is not None:
                self.db.close()
                self.db = None
            try:
                self.db = jobs.connect_db(self.cfg)
                self.connected, self.error = True, ""
            except Exception as e:
                self.connected, self.error = False, describe_error(e)

    def refresh(self):
        """Cheap health check used by /api/status; reconnects at most every 5 seconds."""
        if self.db is not None:
            try:
                self.db.client.admin.command("ping")
                self.connected, self.error = True, ""
            except Exception as e:
                self.connected, self.error = False, describe_error(e)
        elif time.monotonic() - self._last_attempt > 5:
            self.connect()

    def host_label(self):
        try:
            nodes = parse_uri(self.cfg.mongo_uri)["nodelist"]
            return ", ".join(f"{h}:{p}" for h, p in nodes) + f" / {self.cfg.db_name}"
        except Exception:
            return self.cfg.db_name


def create_app(cfg=None, connect=True):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    svc = Services(cfg)
    app.extensions["skrapkin"] = svc
    tasks = TaskManager(describe_error)
    app.extensions["skrapkin_tasks"] = tasks

    extra_hosts = {h.strip().lower() for h in os.environ.get("SKRAPKIN_ALLOWED_HOSTS", "").split(",") if h.strip()}
    allowed_hosts = LOOPBACK_HOSTS | extra_hosts
    password = os.environ.get("SKRAPKIN_WEB_PASSWORD", "")
    username = os.environ.get("SKRAPKIN_WEB_USER", "skrapkin")

    if connect:
        threading.Thread(target=svc.connect, daemon=True).start()

    # ---- guards ---------------------------------------------------------------------------------

    @app.before_request
    def guard():
        if hostname(request.host) not in allowed_hosts:
            abort(421)
        if password and request.path != "/api/health":
            auth = request.authorization
            ok = (auth is not None and hmac.compare_digest((auth.username or "").encode(), username.encode())
                  and hmac.compare_digest((auth.password or "").encode(), password.encode()))
            if not ok:
                return Response("Sign in to use SKrapkin.", 401, {"WWW-Authenticate": 'Basic realm="SKrapkin"'})
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Skrapkin") != "1":
            abort(403)

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        messages = {403: "Request blocked.", 404: "Not found.", 405: "Method not allowed.",
                    413: "Request too large.", 421: "This address isn't allowed. See SKRAPKIN_ALLOWED_HOSTS."}
        return jsonify(error=messages.get(e.code, e.description)), e.code

    @app.errorhandler(Exception)
    def server_error(e):
        # Expected conditions get a clean response; only genuine bugs log a traceback.
        if isinstance(e, InvalidKey):
            status = 400
        elif isinstance(e, HunterError):
            status = 502
        elif isinstance(e, mongo_errors.PyMongoError):
            status = 503
            app.logger.warning("database error: %s", type(e).__name__)
        else:
            status = 500
            app.logger.exception("unhandled error")
        return jsonify(error=describe_error(e)), status

    # ---- helpers --------------------------------------------------------------------------------

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def fail(message, code=400):
        return jsonify(error=message), code

    def need_db():
        svc.refresh()
        if svc.db is None or not svc.connected:
            return None, fail("The database isn't connected. Open Settings to connect it.", 409)
        return svc.db, None

    def int_in(value, low, high, name):
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a whole number.")
        if not low <= number <= high:
            raise ValueError(f"{name} must be between {low} and {high}.")
        return number

    def csv_response(header, rows, filename):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(safe_row(r) for r in rows)
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    def hunter_source():
        if os.environ.get("HUNTER_API_KEY"):
            return "environment"
        return "saved" if config.get_hunter_key() else None

    def lead_filters():
        q = request.args
        category = q.get("category") if q.get("category") in jobs.CATEGORY_LABELS.values() else None
        country = q.get("country").upper() if geo.is_country(q.get("country")) else None
        region = q.get("region", "")[:80] or None
        status = q.get("status") if q.get("status") in STATUSES else None
        return q.get("q", "")[:200], category, country, region, status

    # ---- pages and status -----------------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify(ok=True)

    @app.get("/api/status")
    def status():
        svc.refresh()
        cfg_ = svc.cfg
        active = tasks.active()
        return jsonify(
            version=__version__,
            db={"connected": svc.connected, "error": svc.error, "target": svc.host_label(),
                "uri_from_environment": bool(os.environ.get("SKRAPKIN_MONGO_URI"))},
            hunter={"configured": hunter_source() is not None, "source": hunter_source()},
            active_task={"id": active.id, "kind": active.kind} if active else None,
            config={"min_likelihood": cfg_.min_likelihood, "max_credits_per_run": cfg_.max_credits_per_run,
                    "db_name": cfg_.db_name},
            output_dir=str(jobs.default_output_dir()),
            options={"categories": [{"label": k, "value": v} for k, v in jobs.CATEGORY_LABELS.items()],
                     "confidence": [{"label": k, "value": v} for k, v in jobs.CONFIDENCE_LABELS.items()],
                     "countries": geo.countries()},
        )

    @app.get("/api/regions/<code>")
    def region_list(code):
        if not geo.is_country(code):
            return fail("Unknown country.", 404)
        return jsonify(country=geo.country_name(code), regions=geo.regions(code))

    # ---- settings -------------------------------------------------------------------------------

    @app.post("/api/db")
    def set_db():
        data = body()
        name = str(data.get("db_name", "")).strip()
        uri = str(data.get("uri", "")).strip()
        if name:
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", name):
                return fail("The database name can only use letters, digits, - and _.")
            svc.cfg.db_name = name
        if uri:
            if os.environ.get("SKRAPKIN_MONGO_URI"):
                return fail("The database address is set by the SKRAPKIN_MONGO_URI environment variable. "
                            "Change it in your .env file and restart.")
            if not uri.startswith(("mongodb://", "mongodb+srv://")):
                return fail("The address must start with mongodb:// or mongodb+srv://")
            svc.cfg.mongo_uri = uri
        svc.cfg.save()
        svc.connect()
        return jsonify(connected=svc.connected, error=svc.error, target=svc.host_label())

    @app.post("/api/verify/settings")
    def verify_settings():
        data = body()
        try:
            svc.cfg.min_likelihood = int_in(data.get("min_likelihood", svc.cfg.min_likelihood), 0, 100, "The score")
            svc.cfg.max_credits_per_run = int_in(data.get("max_credits_per_run", svc.cfg.max_credits_per_run),
                                                 1, 10000, "The lookup limit")
        except ValueError as e:
            return fail(str(e))
        svc.cfg.save()
        return jsonify(min_likelihood=svc.cfg.min_likelihood, max_credits_per_run=svc.cfg.max_credits_per_run)

    # ---- hunter key -----------------------------------------------------------------------------

    @app.post("/api/hunter/key")
    def save_key():
        key = str(body().get("key", "")).strip()
        if not KEY_PATTERN.match(key):
            return fail("That doesn't look like a Hunter API key. Copy it again from hunter.io/api-keys.")
        account = HunterClient(key).account()  # free call; raises InvalidKey / HunterError
        config.set_hunter_key(key)
        return jsonify(account=account, source=hunter_source())

    @app.delete("/api/hunter/key")
    def remove_key():
        config.clear_hunter_key()
        note = ("The key from the HUNTER_API_KEY environment variable is still active; remove it from .env."
                if os.environ.get("HUNTER_API_KEY") else "")
        return jsonify(removed=True, note=note, source=hunter_source())

    @app.get("/api/hunter/account")
    def hunter_account():
        key = config.get_hunter_key()
        if not key:
            return fail("No Hunter API key is saved yet.", 409)
        return jsonify(account=HunterClient(key).account())

    # ---- find leads -----------------------------------------------------------------------------

    @app.post("/api/find")
    def find():
        data = body()
        category = data.get("category")
        country = str(data.get("country", "")).upper()
        region = str(data.get("region", "")).strip()
        place = str(data.get("place", "")).strip()
        if category not in jobs.CATEGORY_LABELS.values():
            return fail("Choose a type of business.")
        if not geo.is_country(country):
            return fail("Choose a country.")
        if region and geo.find_region(country, region) is None:
            return fail(f"'{region[:60]}' isn't a known region of {geo.country_name(country)}.")
        try:
            place = geo.clean_place(place)
        except ValueError as e:
            return fail(str(e))
        if data.get("min_confidence") not in ("low", "medium", "high"):
            return fail("Choose which leads to keep.")
        try:
            limit = int_in(data.get("max_businesses", 100), 1, 1000, "Max businesses")
        except ValueError as e:
            return fail(str(e))
        settings = jobs.Settings(category=category, country=country, region=region, place=place,
                                 output_dir=jobs.default_output_dir(),
                                 exclude_personal=bool(data.get("exclude_personal")),
                                 keep_chains=bool(data.get("keep_chains")),
                                 min_confidence=data["min_confidence"], max_businesses=limit)
        save_db, verify_after = bool(data.get("save_db", True)), bool(data.get("verify_after"))
        db = None
        if save_db:
            svc.refresh()
            db = svc.db if svc.connected else None
            if db is None:
                return fail("The database isn't connected. Connect it in Settings, or untick "
                            "'Save leads to the database'.", 409)
        if verify_after and not config.get_hunter_key():
            return fail("Add your Hunter API key on the Verify tab first, or untick the verification option.")

        def work(task):
            path, count = jobs.run_pipeline(settings, task.log, task.progress, task.stop.is_set,
                                            db=db, on_lead=task.add_lead)
            task.result = {"count": count, "file": path.name if path else None, "saved_to_database": db is not None}
            if verify_after and db is not None and count and not task.stop.is_set():
                task.log("Verifying new emails with Hunter...")
                _, _, stats = jobs.run_verification(db, svc.cfg, config.get_hunter_key(), task.log,
                                                    task.progress, task.stop.is_set)
                task.result["verification"] = stats

        try:
            task = tasks.start("find", work)
        except Busy:
            return fail("Another task is still running. Wait for it to finish or stop it.", 409)
        return jsonify(task=task.id), 202

    @app.get("/api/tasks/<task_id>")
    def task_status(task_id):
        task = tasks.get(task_id)
        if task is None:
            return fail("Unknown task.", 404)
        return jsonify(task.snapshot(lead_cursor=request.args.get("cursor", 0, type=int)))

    @app.post("/api/tasks/<task_id>/stop")
    def task_stop(task_id):
        task = tasks.get(task_id)
        if task is None:
            return fail("Unknown task.", 404)
        task.stop.set()
        return jsonify(stopping=True)

    @app.get("/api/download/<name>")
    def download(name):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+\.csv", name):
            abort(404)
        return send_from_directory(jobs.default_output_dir(), name, as_attachment=True)

    # ---- leads ----------------------------------------------------------------------------------

    @app.get("/api/leads")
    def leads():
        db, error = need_db()
        if error:
            return error
        text, category, country, region, status_filter = lead_filters()
        found = db.list_leads(text, category, country, region, limit=3000)
        if status_filter:
            found = [l for l in found if any(e["status"] == status_filter for e in l.get("emails", []))]
        stats = db.stats()
        return jsonify(leads=[lead_out(l) for l in found], totals={"leads": stats["leads"], "emails": stats["emails"],
                                                                    "verified": stats["verified"],
                                                                    "by_status": stats["by_status"]})

    @app.post("/api/leads/delete")
    def leads_delete():
        db, error = need_db()
        if error:
            return error
        keys = [k for k in body().get("keys", []) if isinstance(k, str)][:5000]
        return jsonify(deleted=db.delete_leads(keys))

    @app.get("/api/export/leads.csv")
    def export_leads():
        db, error = need_db()
        if error:
            return error
        text, category, country, region, status_filter = lead_filters()
        found = db.list_leads(text, category, country, region, limit=0)
        if status_filter:
            found = [l for l in found if any(e["status"] == status_filter for e in l.get("emails", []))]
        rows = [[l.get("business", ""), l.get("country", ""), l.get("region", ""), l.get("city", ""),
                 l.get("website", ""), "; ".join(f"{e['address']} ({e['status']})" for e in l.get("emails", [])),
                 "; ".join(l.get("phones", [])), l.get("confidence", "")] for l in found]
        return csv_response(["business", "country", "region", "city", "website", "emails", "phones", "confidence"],
                            rows, "skrapkin_leads.csv")

    # ---- verification ---------------------------------------------------------------------------

    @app.post("/api/verify/preview")
    def verify_preview():
        db, error = need_db()
        if error:
            return error
        plan = build_plan(db, svc.cfg)
        limit = svc.cfg.max_credits_per_run
        rows = []
        for i, c in enumerate(plan.to_check):
            within = i < limit
            rows.append({"decision": "check" if within else "skip", "email": c.address, "business": c.business,
                         "score": c.likelihood,
                         "reason": "" if within else f"over this run's limit of {limit} lookups"})
        rows += [{"decision": "skip", "email": c.address, "business": c.business, "score": c.likelihood,
                  "reason": why} for c, why in plan.filtered]
        rows += [{"decision": "skip", "email": c.address, "business": c.business, "score": c.likelihood,
                  "reason": "webmail addresses can't be confirmed"} for c in plan.webmail]
        rows += [{"decision": "skip", "email": c.address, "business": c.business, "score": c.likelihood,
                  "reason": f"already checked ({s['status']})"} for c, s in plan.cached]
        rows += [{"decision": "skip", "email": c.address, "business": c.business, "score": c.likelihood,
                  "reason": "this domain accepts any address"} for c in plan.inferred]
        return jsonify(rows=rows, will_use=min(len(plan.to_check), limit), skipped=plan.saved,
                       summary=plan.summary(), limit=limit, min_likelihood=svc.cfg.min_likelihood)

    @app.post("/api/verify/start")
    def verify_start():
        db, error = need_db()
        if error:
            return error
        key = config.get_hunter_key()
        if not key:
            return fail("Add and test your Hunter API key first.", 409)

        def work(task):
            account, plan, stats = jobs.run_verification(db, svc.cfg, key, task.log, task.progress, task.stop.is_set)
            task.result = {"stats": stats, "account": account}

        try:
            task = tasks.start("verify", work)
        except Busy:
            return fail("Another task is still running. Wait for it to finish or stop it.", 409)
        return jsonify(task=task.id), 202

    # ---- verified results -----------------------------------------------------------------------

    @app.get("/api/verified")
    def verified():
        db, error = need_db()
        if error:
            return error
        text, category, country, region, _ = lead_filters()
        return jsonify(verified=[verified_out(d) for d in db.list_verified(text, category, country, region, limit=5000)])

    @app.post("/api/verified/delete")
    def verified_delete():
        db, error = need_db()
        if error:
            return error
        emails = [e for e in body().get("emails", []) if isinstance(e, str)][:5000]
        return jsonify(deleted=db.delete_verified(emails))

    @app.get("/api/export/verified.csv")
    def export_verified():
        db, error = need_db()
        if error:
            return error
        text, category, country, region, _ = lead_filters()
        docs = db.list_verified(text, category, country, region, limit=0)
        rows = [[d["email"], d.get("business", ""), d.get("country", ""), d.get("region", ""), d.get("city", ""),
                 d.get("website", ""), "; ".join(d.get("phones", [])), d.get("score", ""), iso(d.get("verified_at"))]
                for d in docs]
        return csv_response(["email", "business", "country", "region", "city", "website", "phones", "score",
                             "verified_at"], rows, "skrapkin_verified_emails.csv")

    return app
