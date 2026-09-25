import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


SITE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MARE_DB_PATH", str(SITE_DIR / "data" / "mare.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
HOST = os.environ.get("MARE_HOST", "127.0.0.1")
PORT = int(os.environ.get("MARE_PORT", "8000"))
ADMIN_USER = os.environ.get("MARE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("MARE_ADMIN_PASSWORD", "")
HTTPS_COOKIE = os.environ.get("MARE_COOKIE_SECURE", "0") == "1"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_SALT = secrets.token_bytes(16)
PASSWORD_HASH = hashlib.pbkdf2_hmac("sha256", ADMIN_PASSWORD.encode("utf-8"), PASSWORD_SALT, 310000) if len(ADMIN_PASSWORD) >= 12 else b""
SESSIONS = {}
LOGIN_ATTEMPTS = {}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
SERVICES = {"pranzo", "cena"}
STATUSES = {"ricevuta", "confermata", "annullata"}
ROME = ZoneInfo("Europe/Rome")


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_db():
    with connect_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS service_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                time TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS daily_limits (
                day TEXT PRIMARY KEY,
                capacity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS slot_limits (
                day TEXT NOT NULL,
                slot_id INTEGER NOT NULL,
                capacity INTEGER NOT NULL,
                PRIMARY KEY(day, slot_id)
            );
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL UNIQUE,
                day TEXT NOT NULL,
                service TEXT NOT NULL,
                time TEXT NOT NULL,
                guests INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ricevuta',
                utm_source TEXT NOT NULL DEFAULT '',
                utm_medium TEXT NOT NULL DEFAULT '',
                utm_campaign TEXT NOT NULL DEFAULT '',
                utm_term TEXT NOT NULL DEFAULT '',
                utm_content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reservations_day_service_time
                ON reservations(day, service, time, status);
            """
        )


def valid_date(value):
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        return False


def local_now():
    return datetime.now(ROME)


def slot_is_future(day, slot_time):
    if day < local_now().date().isoformat():
        return False
    if day > local_now().date().isoformat():
        return True
    slot_datetime = datetime.strptime(day + " " + slot_time, "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
    return slot_datetime > local_now()
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def booked_seats(connection, day, service=None, slot_time=None):
    query = "SELECT COALESCE(SUM(guests), 0) FROM reservations WHERE day = ? AND status != 'annullata'"
    values = [day]
    if service is not None:
        query += " AND service = ?"
        values.append(service)
    if slot_time is not None:
        query += " AND time = ?"
        values.append(slot_time)
    return int(connection.execute(query, values).fetchone()[0])


def slot_booked(connection, day, service, slot_time):
    row = connection.execute(
        "SELECT COALESCE(SUM(guests), 0) FROM reservations WHERE day = ? AND service = ? AND time = ? AND status != 'annullata'",
        (day, service, slot_time),
    ).fetchone()
    return int(row[0])


def day_limit(connection, day):
    row = connection.execute("SELECT capacity FROM daily_limits WHERE day = ?", (day,)).fetchone()
    return int(row[0]) if row else None


def effective_slot_capacity(connection, day, slot):
    row = connection.execute("SELECT capacity FROM slot_limits WHERE day = ? AND slot_id = ?", (day, slot["id"])).fetchone()
    return int(row[0]) if row else int(slot["capacity"])


def safe_text(value, max_length):
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


class MareHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def end_headers(self):
        is_menu_pdf = bool(re.fullmatch(r"/assets/menus/[A-Za-z0-9_-]+\.pdf", urlparse(self.path).path, flags=re.IGNORECASE))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if is_menu_pdf else "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        frame_rule = "frame-ancestors 'self'" if is_menu_pdf else "frame-ancestors 'none'"
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; " + frame_rule)
        super().end_headers()

    def send_json(self, payload, status=200, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, max_bytes=32768):
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            raise ValueError("La richiesta deve usare JSON.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Dimensione della richiesta non valida.")
        if size < 1 or size > max_bytes:
            raise ValueError("La richiesta è vuota o supera il limite consentito.")
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Il contenuto della richiesta non è valido.")
        if not isinstance(payload, dict):
            raise ValueError("Il contenuto della richiesta non è valido.")
        return payload

    def require_admin(self):
        if self.admin_session():
            return True
        self.send_json({"error": "Accedi per continuare."}, 401)
        return False

    def admin_session(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("mare_session")
        token = morsel.value if morsel else ""
        expiry = SESSIONS.get(token)
        if expiry and expiry > time.time():
            return True
        if token:
            SESSIONS.pop(token, None)
        return False

    def static_path_allowed(self, path):
        if path in {"/", "/index.html", "/admin.html", "/styles.css", "/app.js", "/admin.js"}:
            return True
        if re.fullmatch(r"/assets/[A-Za-z0-9_.-]+\.jpg", path, flags=re.IGNORECASE):
            return True
        return bool(re.fullmatch(r"/assets/menus/[A-Za-z0-9_-]+\.pdf", path, flags=re.IGNORECASE))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/availability":
            self.get_availability(parse_qs(parsed.query))
            return
        if parsed.path == "/api/admin/session":
            self.send_json({"authenticated": self.admin_session(), "configured": bool(PASSWORD_HASH)})
            return
        if parsed.path == "/api/admin/config":
            if self.require_admin():
                self.get_admin_config(parse_qs(parsed.query))
            return
        if parsed.path == "/api/admin/overview":
            if self.require_admin():
                self.get_admin_overview(parse_qs(parsed.query))
            return
        if parsed.path == "/admin":
            self.send_response(302)
            self.send_header("Location", "/admin.html")
            self.end_headers()
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "Risorsa non trovata."}, 404)
            return
        if self.static_path_allowed(parsed.path):
            super().do_GET()
        else:
            self.send_json({"error": "Risorsa non trovata."}, 404)

    def do_HEAD(self):
        path = urlparse(self.path).path
        if self.static_path_allowed(path):
            super().do_HEAD()
        else:
            self.send_response(404)
            self.end_headers()

    def get_availability(self, query):
        day = query.get("date", [""])[0]
        service = query.get("service", [""])[0]
        guests_text = query.get("guests", ["1"])[0]
        if not valid_date(day) or service not in SERVICES:
            self.send_json({"error": "Seleziona una data e un servizio validi."}, 400)
            return
        try:
            guests = int(guests_text)
        except ValueError:
            guests = 0
        if guests < 1 or guests > 500:
            self.send_json({"error": "Il numero di persone non è valido."}, 400)
            return
        with connect_db() as connection:
            slots = connection.execute("SELECT * FROM service_slots WHERE service = ? AND active = 1 ORDER BY time", (service,)).fetchall()
            total_booked = booked_seats(connection, day)
            total_limit = day_limit(connection, day)
            daily_remaining = max(0, total_limit - total_booked) if total_limit is not None else None
            result = []
            for slot in slots:
                if not slot_is_future(day, slot["time"]):
                    continue
                capacity = effective_slot_capacity(connection, day, slot)
                booked = slot_booked(connection, day, service, slot["time"])
                remaining = max(0, capacity - booked)
                if daily_remaining is not None:
                    remaining = min(remaining, daily_remaining)
                result.append({"time": slot["time"], "available": remaining >= guests, "remaining": remaining})
        if not slots:
            availability_state = "not_configured"
        elif not result:
            availability_state = "no_future_slots"
        elif not any(slot["available"] for slot in result):
            availability_state = "full"
        else:
            availability_state = "available"
        self.send_json({"slots": result, "state": availability_state})

    def get_admin_config(self, query):
        day = query.get("date", [""])[0]
        if not valid_date(day):
            self.send_json({"error": "La data selezionata non è valida."}, 400)
            return
        with connect_db() as connection:
            slots = connection.execute("SELECT * FROM service_slots ORDER BY service, time").fetchall()
            result = []
            for slot in slots:
                override = connection.execute("SELECT capacity FROM slot_limits WHERE day = ? AND slot_id = ?", (day, slot["id"])).fetchone()
                result.append({
                    "id": slot["id"],
                    "service": slot["service"],
                    "time": slot["time"],
                    "capacity": int(slot["capacity"]),
                    "active": bool(slot["active"]),
                    "dayCapacity": int(override[0]) if override else None,
                    "booked": slot_booked(connection, day, slot["service"], slot["time"]),
                })
            self.send_json({"date": day, "dailyCapacity": day_limit(connection, day), "slots": result})

    def get_admin_overview(self, query):
        day = query.get("date", [""])[0]
        if not valid_date(day):
            self.send_json({"error": "La data selezionata non è valida."}, 400)
            return
        with connect_db() as connection:
            reservations = connection.execute(
                "SELECT id, reference, day, service, time, guests, notes, status, utm_source, utm_medium, utm_campaign, created_at FROM reservations WHERE day = ? ORDER BY time, id",
                (day,),
            ).fetchall()
            total_limit = day_limit(connection, day)
            total_booked = booked_seats(connection, day)
            remaining = max(0, total_limit - total_booked) if total_limit is not None else None
            slots = connection.execute("SELECT * FROM service_slots WHERE active = 1 ORDER BY service, time").fetchall()
            slot_result = []
            for slot in slots:
                capacity = effective_slot_capacity(connection, day, slot)
                used = slot_booked(connection, day, slot["service"], slot["time"])
                slot_result.append({
                    "service": slot["service"],
                    "time": slot["time"],
                    "capacity": capacity,
                    "booked": used,
                    "remaining": max(0, capacity - used),
                })
            reservation_result = [dict(row) for row in reservations]
        self.send_json({
            "date": day,
            "totalBooked": total_booked,
            "dailyCapacity": total_limit,
            "dailyRemaining": remaining,
            "slots": slot_result,
            "reservations": reservation_result,
        })

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reservations":
            self.create_reservation()
            return
        if path == "/api/admin/login":
            self.admin_login()
            return
        if path == "/api/admin/logout":
            self.admin_logout()
            return
        if path.startswith("/api/"):
            self.send_json({"error": "Risorsa non trovata."}, 404)
            return
        self.send_json({"error": "Metodo non consentito."}, 405)

    def create_reservation(self):
        try:
            payload = self.read_json()
            day = payload.get("date")
            service = payload.get("service")
            slot_time = payload.get("time")
            guests = payload.get("guests")
            notes = safe_text(payload.get("notes", ""), 500)
            if not valid_date(day) or not isinstance(slot_time, str) or not TIME_PATTERN.fullmatch(slot_time) or not slot_is_future(day, slot_time):
                raise ValueError("Scegli una data valida, da oggi in poi.")
            if service not in SERVICES or not isinstance(slot_time, str) or not TIME_PATTERN.fullmatch(slot_time):
                raise ValueError("Scegli un servizio e un orario validi.")
            if isinstance(guests, bool) or not isinstance(guests, int) or guests < 1 or guests > 500:
                raise ValueError("Il numero di persone deve essere compreso tra 1 e 500.")
            utm = payload.get("utm", {})
            if not isinstance(utm, dict):
                utm = {}
            utm_values = [safe_text(utm.get(key, ""), 150) for key in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")]
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        reference = "MARE-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        try:
            with connect_db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                slot = connection.execute(
                    "SELECT * FROM service_slots WHERE service = ? AND time = ? AND active = 1",
                    (service, slot_time),
                ).fetchone()
                if not slot:
                    self.send_json({"error": "Questo orario non è più disponibile."}, 409)
                    return
                capacity = effective_slot_capacity(connection, day, slot)
                used = slot_booked(connection, day, service, slot_time)
                limit = day_limit(connection, day)
                day_used = booked_seats(connection, day)
                if used + guests > capacity:
                    self.send_json({"error": "I posti per questo orario sono terminati. Scegli un altro orario."}, 409)
                    return
                if limit is not None and day_used + guests > limit:
                    self.send_json({"error": "La capienza giornaliera è stata raggiunta."}, 409)
                    return
                connection.execute(
                    "INSERT INTO reservations (reference, day, service, time, guests, notes, status, utm_source, utm_medium, utm_campaign, utm_term, utm_content, created_at) VALUES (?, ?, ?, ?, ?, ?, 'ricevuta', ?, ?, ?, ?, ?, ?)",
                    (reference, day, service, slot_time, guests, notes, *utm_values, local_now().isoformat(timespec="seconds")),
                )
                connection.commit()
        except sqlite3.Error:
            self.send_json({"error": "Non è stato possibile salvare la prenotazione. Riprova."}, 500)
            return
        self.send_json({"reference": reference, "status": "ricevuta"}, 201)

    def client_ip(self):
        return self.client_address[0]

    def admin_login(self):
        if not PASSWORD_HASH:
            self.send_json({"error": "Accesso admin non configurato. Imposta le credenziali del responsabile sul server."}, 503)
            return
        ip = self.client_ip()
        now = time.time()
        attempts = [timestamp for timestamp in LOGIN_ATTEMPTS.get(ip, []) if now - timestamp < 900]
        if len(attempts) >= 8:
            self.send_json({"error": "Troppi tentativi. Riprova tra qualche minuto."}, 429)
            return
        try:
            payload = self.read_json(8192)
            username = safe_text(payload.get("username"), 120)
            password = payload.get("password", "")
            if not isinstance(password, str):
                password = ""
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), PASSWORD_SALT, 310000)
        if not hmac.compare_digest(username.encode("utf-8"), ADMIN_USER.encode("utf-8")) or not hmac.compare_digest(password_hash, PASSWORD_HASH):
            attempts.append(now)
            LOGIN_ATTEMPTS[ip] = attempts
            self.send_json({"error": "Nome utente o password non corretti."}, 401)
            return
        LOGIN_ATTEMPTS.pop(ip, None)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = now + SESSION_SECONDS
        cookie = "mare_session={}; Path=/; Max-Age={}; HttpOnly; SameSite=Strict".format(token, SESSION_SECONDS)
        if HTTPS_COOKIE:
            cookie += "; Secure"
        self.send_json({"authenticated": True}, extra_headers={"Set-Cookie": cookie})

    def admin_logout(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("mare_session")
        if morsel:
            SESSIONS.pop(morsel.value, None)
        expired_cookie = "mare_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
        if HTTPS_COOKIE:
            expired_cookie += "; Secure"
        self.send_json({"authenticated": False}, extra_headers={"Set-Cookie": expired_cookie})

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/admin/slots":
            if self.require_admin():
                self.update_slots()
            return
        if path == "/api/admin/capacity":
            if self.require_admin():
                self.update_capacity()
            return
        self.send_json({"error": "Risorsa non trovata."}, 404)

    def update_slots(self):
        try:
            payload = self.read_json()
            slots = payload.get("slots")
            if not isinstance(slots, list) or len(slots) > 100:
                raise ValueError("Elenco degli orari non valido.")
            prepared = []
            active_keys = set()
            for item in slots:
                if not isinstance(item, dict):
                    raise ValueError("Controlla i dati degli orari.")
                service = item.get("service")
                slot_time = item.get("time")
                capacity = item.get("capacity")
                active = item.get("active") is True
                slot_id = item.get("id")
                if service not in SERVICES or not isinstance(slot_time, str) or not TIME_PATTERN.fullmatch(slot_time):
                    raise ValueError("Inserisci un servizio e un orario validi.")
                if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1 or capacity > 500:
                    raise ValueError("La capienza per orario deve essere tra 1 e 500.")
                if active:
                    key = (service, slot_time)
                    if key in active_keys:
                        raise ValueError("Non ripetere lo stesso orario per lo stesso servizio.")
                    active_keys.add(key)
                if slot_id is not None and (isinstance(slot_id, bool) or not isinstance(slot_id, int) or slot_id < 1):
                    raise ValueError("Identificativo dell’orario non valido.")
                prepared.append((slot_id, service, slot_time, capacity, 1 if active else 0))
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        try:
            with connect_db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE service_slots SET active = 0")
                for slot_id, service, slot_time, capacity, active in prepared:
                    if slot_id is None:
                        existing = connection.execute("SELECT id FROM service_slots WHERE service = ? AND time = ? ORDER BY active DESC LIMIT 1", (service, slot_time)).fetchone()
                        if existing:
                            connection.execute("UPDATE service_slots SET capacity = ?, active = ? WHERE id = ?", (capacity, active, existing["id"]))
                        else:
                            connection.execute("INSERT INTO service_slots (service, time, capacity, active) VALUES (?, ?, ?, ?)", (service, slot_time, capacity, active))
                    else:
                        exists = connection.execute("SELECT id FROM service_slots WHERE id = ?", (slot_id,)).fetchone()
                        if not exists:
                            raise ValueError("Un orario è stato modificato da un’altra sessione. Aggiorna la pagina.")
                        connection.execute("UPDATE service_slots SET service = ?, time = ?, capacity = ?, active = ? WHERE id = ?", (service, slot_time, capacity, active, slot_id))
                connection.commit()
        except ValueError as error:
            self.send_json({"error": str(error)}, 409)
            return
        except sqlite3.Error:
            self.send_json({"error": "Non è stato possibile salvare gli orari."}, 500)
            return
        self.send_json({"saved": True})

    def update_capacity(self):
        try:
            payload = self.read_json()
            day = payload.get("date")
            daily_capacity = payload.get("dailyCapacity")
            slot_capacities = payload.get("slotCapacities")
            if not valid_date(day):
                raise ValueError("La data selezionata non è valida.")
            if daily_capacity is not None and (isinstance(daily_capacity, bool) or not isinstance(daily_capacity, int) or daily_capacity < 1 or daily_capacity > 500):
                raise ValueError("La capienza giornaliera deve essere tra 1 e 500 oppure vuota.")
            if not isinstance(slot_capacities, list) or len(slot_capacities) > 100:
                raise ValueError("Capienze per orario non valide.")
            prepared = []
            for item in slot_capacities:
                if not isinstance(item, dict):
                    raise ValueError("Controlla le capienze per orario.")
                slot_id = item.get("id")
                capacity = item.get("capacity")
                if isinstance(slot_id, bool) or not isinstance(slot_id, int) or slot_id < 1:
                    raise ValueError("Identificativo dell’orario non valido.")
                if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1 or capacity > 500):
                    raise ValueError("La capienza di un orario deve essere tra 1 e 500 oppure vuota.")
                prepared.append((slot_id, capacity))
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        try:
            with connect_db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current_day_booked = booked_seats(connection, day)
                if daily_capacity is not None and daily_capacity < current_day_booked:
                    raise ValueError("Il totale giornaliero non può essere inferiore ai coperti già prenotati.")
                if daily_capacity is None:
                    connection.execute("DELETE FROM daily_limits WHERE day = ?", (day,))
                else:
                    connection.execute("INSERT INTO daily_limits(day, capacity) VALUES(?, ?) ON CONFLICT(day) DO UPDATE SET capacity = excluded.capacity", (day, daily_capacity))
                for slot_id, capacity in prepared:
                    slot = connection.execute("SELECT service, time FROM service_slots WHERE id = ?", (slot_id,)).fetchone()
                    if not slot:
                        raise ValueError("Un orario è stato modificato da un’altra sessione. Aggiorna la pagina.")
                    used = slot_booked(connection, day, slot["service"], slot["time"])
                    if capacity is not None and capacity < used:
                        raise ValueError("Una capienza non può essere inferiore ai coperti già prenotati.")
                    if capacity is None:
                        connection.execute("DELETE FROM slot_limits WHERE day = ? AND slot_id = ?", (day, slot_id))
                    else:
                        connection.execute("INSERT INTO slot_limits(day, slot_id, capacity) VALUES(?, ?, ?) ON CONFLICT(day, slot_id) DO UPDATE SET capacity = excluded.capacity", (day, slot_id, capacity))
                connection.commit()
        except ValueError as error:
            self.send_json({"error": str(error)}, 409)
            return
        except sqlite3.Error:
            self.send_json({"error": "Non è stato possibile salvare le capienze."}, 500)
            return
        self.send_json({"saved": True})

    def do_PATCH(self):
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/admin/reservations/(\d+)", path)
        if not match:
            self.send_json({"error": "Risorsa non trovata."}, 404)
            return
        if not self.require_admin():
            return
        try:
            payload = self.read_json(8192)
            status = payload.get("status")
            if status not in STATUSES:
                raise ValueError("Stato della prenotazione non valido.")
            reservation_id = int(match.group(1))
            with connect_db() as connection:
                reservation = connection.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
                if not reservation:
                    self.send_json({"error": "Prenotazione non trovata."}, 404)
                    return
                if reservation["status"] == "annullata" and status != "annullata":
                    slot = connection.execute("SELECT * FROM service_slots WHERE service = ? AND time = ? ORDER BY active DESC LIMIT 1", (reservation["service"], reservation["time"])).fetchone()
                    if not slot:
                        self.send_json({"error": "Configura di nuovo questo orario prima di riattivare la prenotazione."}, 409)
                        return
                    capacity = effective_slot_capacity(connection, reservation["day"], slot)
                    used = slot_booked(connection, reservation["day"], reservation["service"], reservation["time"])
                    limit = day_limit(connection, reservation["day"])
                    day_used = booked_seats(connection, reservation["day"])
                    if used + reservation["guests"] > capacity or (limit is not None and day_used + reservation["guests"] > limit):
                        self.send_json({"error": "La capienza disponibile non basta per riattivare questa prenotazione."}, 409)
                        return
                connection.execute("UPDATE reservations SET status = ? WHERE id = ?", (status, reservation_id))
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        except sqlite3.Error:
            self.send_json({"error": "Non è stato possibile aggiornare la prenotazione."}, 500)
            return
        self.send_json({"saved": True})

    def log_message(self, format_string, *args):
        super().log_message(format_string, *args)


def main():
    initialize_db()
    server = ThreadingHTTPServer((HOST, PORT), MareHandler)
    print("Sito Marè disponibile su http://{}:{}".format(HOST, PORT))
    if not PASSWORD_HASH:
        print("Area admin non attiva: configura MARE_ADMIN_USER e MARE_ADMIN_PASSWORD.")
    if HOST not in {"127.0.0.1", "localhost", "::1"}:
        print("Rete attiva. In produzione usa un proxy HTTPS e imposta MARE_COOKIE_SECURE=1.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto del server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
