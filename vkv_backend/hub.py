# -*- coding: utf-8 -*-
import secrets
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from vkv_backend.settings import (
    MAX_FILE, ONLINE_SECONDS, ROLES, STATUSES,
    check_password, clean_username, hash_password, safe_filename,
)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class Hub:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "dosyalar").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.root / "ag.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              username TEXT NOT NULL UNIQUE,
              password TEXT NOT NULL,
              role TEXT NOT NULL,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS clients (
              istemci_id TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              cihaz TEXT,
              sistem TEXT,
              ip TEXT,
              last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS requests (
              id INTEGER PRIMARY KEY,
              number TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              note TEXT,
              author_id INTEGER NOT NULL,
              assignee_id INTEGER NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS files (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              stored TEXT NOT NULL,
              size INTEGER NOT NULL,
              note TEXT,
              owner_id INTEGER NOT NULL,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL,
              text TEXT NOT NULL,
              created_at TEXT
            );
            """
        )
        self.conn.commit()
        self._ensure_key()

    def close(self):
        self.conn.close()

    def _ensure_key(self):
        path = self.root / "kurulum.anahtar"
        if self.user_count():
            try:
                path.unlink()
            except OSError:
                pass
            self.setup_key = ""
            return
        if path.is_file():
            self.setup_key = path.read_text(encoding="utf-8").strip()
        else:
            self.setup_key = secrets.token_hex(4)
            path.write_text(self.setup_key + "\n", encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass

    def user_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def needs_setup(self):
        return self.user_count() == 0

    def setup(self, key, name, username, password):
        with self.lock:
            if not self.needs_setup():
                raise ValueError("Kurulum tamamlanmış.")
            given = str(key or "").strip()
            expected = self.setup_key or ""
            if len(given) != len(expected) or not secrets.compare_digest(given, expected):
                raise ValueError("Kurulum anahtarı uyuşmuyor.")
            user_id = self._add_user(name, username, password, "Yönetici")
            self._ensure_key()
            return self._public_user(self._user(user_id))

    def _add_user(self, name, username, password, role):
        name = " ".join(str(name or "").split())
        username = clean_username(username)
        if len(name) < 2 or len(username) < 3 or len(str(password or "")) < 6:
            raise ValueError("Ad, en az 3 karakterlik kullanıcı adı ve 6 karakterlik parola gerekli.")
        if role not in ROLES:
            raise ValueError("Rol seç.")
        try:
            cursor = self.conn.execute(
                "INSERT INTO users (name, username, password, role, created_at) VALUES (?,?,?,?,?)",
                (name[:80], username, hash_password(password), role, now_text()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Bu kullanıcı adı kayıtlı.") from exc
        self.conn.commit()
        return cursor.lastrowid

    def add_user(self, actor, name, username, password, role):
        if actor["rol"] != "Yönetici":
            raise ValueError("Kullanıcıyı yönetici ekler.")
        with self.lock:
            return self._public_user(self._user(self._add_user(name, username, password, role)))

    def login(self, username, password):
        username = clean_username(username)
        row = self.conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None or not check_password(password, row["password"]):
            raise ValueError("Kullanıcı adı veya parola hatalı.")
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                (token, row["id"], now_text()),
            )
            self.conn.commit()
        user = self._public_user(row)
        user["token"] = token
        return user

    def logout(self, token):
        with self.lock:
            self.conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self.conn.commit()

    def user_by_token(self, token):
        if not token:
            return None
        row = self.conn.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token=?
            """,
            (token,),
        ).fetchone()
        return self._public_user(row) if row else None

    def _user(self, user_id):
        return self.conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()

    def _public_user(self, row):
        if row is None:
            return None
        return {"id": row["id"], "ad": row["name"], "kullanici": row["username"], "rol": row["role"]}

    def users(self):
        rows = self.conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [self._public_user(row) for row in rows]

    def beat(self, user, istemci_id, cihaz, sistem, ip):
        istemci_id = "".join(ch for ch in str(istemci_id or "") if ch.isalnum() or ch in "-")[:40]
        if len(istemci_id) < 8:
            raise ValueError("İstemci kimliği yok.")
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO clients (istemci_id, user_id, cihaz, sistem, ip, last_seen)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(istemci_id) DO UPDATE SET
                  user_id=excluded.user_id, cihaz=excluded.cihaz, sistem=excluded.sistem,
                  ip=excluded.ip, last_seen=excluded.last_seen
                """,
                (istemci_id, user["id"], str(cihaz or "")[:80], str(sistem or "")[:80], str(ip or "")[:64], now_text()),
            )
            self.conn.commit()
        return {"ok": True}

    def computers(self):
        rows = self.conn.execute(
            """
            SELECT c.*, u.name AS user_name, u.username, u.role
            FROM clients c JOIN users u ON u.id = c.user_id
            ORDER BY c.last_seen DESC
            """
        ).fetchall()
        moment = datetime.now()
        listed = []
        for row in rows:
            seen = parse_time(row["last_seen"])
            online = seen is not None and (moment - seen).total_seconds() <= ONLINE_SECONDS
            listed.append({
                "istemci": row["istemci_id"],
                "kullanici_id": row["user_id"],
                "ad": row["user_name"],
                "kullanici": row["username"],
                "rol": row["role"],
                "cihaz": row["cihaz"],
                "sistem": row["sistem"],
                "ip": row["ip"],
                "gorulme": row["last_seen"],
                "cevrimici": online,
            })
        return listed

    def create_request(self, actor, title, note, assignee_id):
        title = " ".join(str(title or "").split())
        note = " ".join(str(note or "").split())
        if len(title) < 2:
            raise ValueError("Başlık gerekli.")
        try:
            assignee_id = int(assignee_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Talep verilecek kişiyi seç.") from exc
        assignee = self._user(assignee_id)
        if assignee is None:
            raise ValueError("Talep verilecek kişiyi seç.")
        with self.lock:
            count = self.conn.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"]
            number = f"AG-{int(count) + 1}"
            while self.conn.execute("SELECT id FROM requests WHERE number=?", (number,)).fetchone():
                count += 1
                number = f"AG-{int(count) + 1}"
            cursor = self.conn.execute(
                """
                INSERT INTO requests (number, title, note, author_id, assignee_id, status, created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (number, title[:180], note[:2000], actor["id"], assignee["id"], "Açık", now_text()),
            )
            self.conn.commit()
            request_id = cursor.lastrowid
        return self._request(request_id)

    def set_status(self, actor, request_id, status):
        if status not in STATUSES:
            raise ValueError("Durum yok.")
        try:
            request_id = int(request_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Talep yok.") from exc
        row = self.conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError("Talep yok.")
        if actor["rol"] != "Yönetici" and actor["id"] not in {row["author_id"], row["assignee_id"]}:
            raise ValueError("Bu talebin durumunu açan veya alan kişi değiştirir.")
        with self.lock:
            self.conn.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            self.conn.commit()
        return self._request(request_id)

    def requests_for(self, actor):
        if actor["rol"] == "Yönetici":
            rows = self.conn.execute(self._request_sql() + " ORDER BY r.id DESC").fetchall()
        else:
            rows = self.conn.execute(
                self._request_sql() + " WHERE r.author_id=? OR r.assignee_id=? ORDER BY r.id DESC",
                (actor["id"], actor["id"]),
            ).fetchall()
        return [self._request_dict(row) for row in rows]

    def distribution(self):
        people = []
        for user in self.users():
            open_count = self.conn.execute(
                "SELECT COUNT(*) AS n FROM requests WHERE assignee_id=? AND status!='Tamamlandı'",
                (user["id"],),
            ).fetchone()["n"]
            people.append({**user, "acik": open_count})
        return people

    def _request(self, request_id):
        row = self.conn.execute(self._request_sql() + " WHERE r.id=?", (int(request_id),)).fetchone()
        return self._request_dict(row)

    def _request_sql(self):
        return """
            SELECT r.*, a.name AS author_name, b.name AS assignee_name
            FROM requests r
            JOIN users a ON a.id = r.author_id
            JOIN users b ON b.id = r.assignee_id
        """

    def _request_dict(self, row):
        return {
            "id": row["id"],
            "no": row["number"],
            "baslik": row["title"],
            "not": row["note"] or "",
            "acan": row["author_name"],
            "acan_id": row["author_id"],
            "alan": row["assignee_name"],
            "alan_id": row["assignee_id"],
            "durum": row["status"],
            "zaman": row["created_at"],
        }

    def save_file(self, actor, name, note, payload):
        if not payload:
            raise ValueError("Dosya boş.")
        if len(payload) > MAX_FILE:
            raise ValueError("Dosya 20 MB sınırını aşıyor.")
        clean = safe_filename(name)
        with self.lock:
            cursor = self.conn.execute(
                "INSERT INTO files (name, stored, size, note, owner_id, created_at) VALUES (?,?,?,?,?,?)",
                (clean, "", len(payload), " ".join(str(note or "").split())[:200], actor["id"], now_text()),
            )
            file_id = cursor.lastrowid
            stored = f"{file_id}-{clean}"
            path = self.root / "dosyalar" / stored
            path.write_bytes(payload)
            self.conn.execute("UPDATE files SET stored=? WHERE id=?", (stored, file_id))
            self.conn.commit()
        return self._file_dict(file_id)

    def files(self):
        rows = self.conn.execute(
            """
            SELECT f.*, u.name AS owner_name
            FROM files f JOIN users u ON u.id = f.owner_id
            ORDER BY f.id DESC
            """
        ).fetchall()
        return [self._file_row(row) for row in rows]

    def file_bytes(self, file_id):
        try:
            file_id = int(file_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Dosya yok.") from exc
        row = self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            raise ValueError("Dosya yok.")
        path = (self.root / "dosyalar" / row["stored"]).resolve()
        folder = (self.root / "dosyalar").resolve()
        if folder not in path.parents or not path.is_file():
            raise ValueError("Dosya bulunamadı.")
        return row["name"], path.read_bytes()

    def _file_dict(self, file_id):
        row = self.conn.execute(
            """
            SELECT f.*, u.name AS owner_name FROM files f
            JOIN users u ON u.id = f.owner_id WHERE f.id=?
            """,
            (int(file_id),),
        ).fetchone()
        return self._file_row(row)

    def _file_row(self, row):
        return {
            "id": row["id"],
            "ad": row["name"],
            "boy": row["size"],
            "not": row["note"] or "",
            "sahip": row["owner_name"],
            "sahip_id": row["owner_id"],
            "zaman": row["created_at"],
        }

    def add_message(self, actor, text):
        text = " ".join(str(text or "").split())
        if not text:
            raise ValueError("Mesaj yaz.")
        with self.lock:
            cursor = self.conn.execute(
                "INSERT INTO messages (user_id, text, created_at) VALUES (?,?,?)",
                (actor["id"], text[:500], now_text()),
            )
            self.conn.commit()
            message_id = cursor.lastrowid
        return self._message(message_id)

    def messages(self):
        rows = self.conn.execute(
            """
            SELECT m.*, u.name AS user_name FROM messages m
            JOIN users u ON u.id = m.user_id
            ORDER BY m.id DESC LIMIT 80
            """
        ).fetchall()
        return [self._message_row(row) for row in reversed(rows)]

    def _message(self, message_id):
        row = self.conn.execute(
            """
            SELECT m.*, u.name AS user_name FROM messages m
            JOIN users u ON u.id = m.user_id WHERE m.id=?
            """,
            (int(message_id),),
        ).fetchone()
        return self._message_row(row)

    def _message_row(self, row):
        return {"id": row["id"], "ad": row["user_name"], "metin": row["text"], "zaman": row["created_at"]}
