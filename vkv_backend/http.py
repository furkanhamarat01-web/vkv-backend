# -*- coding: utf-8 -*-
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from vkv_backend.settings import MAX_FILE


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/v1/durum" and self.command == "GET":
                self._json(200, {"ok": True, "kurulum": self.server.hub.needs_setup(), "ad": "VKV Ağ"})
                return
            if path == "/v1/kurulum" and self.command == "POST":
                body = self._json_body()
                user = self.server.hub.setup(body.get("anahtar"), body.get("ad"), body.get("kullanici"), body.get("parola"))
                self._json(200, {"ok": True, "kullanici": user})
                return
            if path == "/v1/giris" and self.command == "POST":
                body = self._json_body()
                self._json(200, {"ok": True, "kullanici": self.server.hub.login(body.get("kullanici"), body.get("parola"))})
                return
            user = self._actor()
            if user is None:
                self._json(401, {"ok": False, "error": "Oturum kapandı. Yeniden gir."})
                return
            if path == "/v1/cikis" and self.command == "POST":
                self.server.hub.logout(self._token())
                self._json(200, {"ok": True})
                return
            if path == "/v1/nabiz" and self.command == "POST":
                body = self._json_body()
                peer = self.client_address[0]
                self.server.hub.beat(user, self.headers.get("X-Istemci"), body.get("cihaz"), body.get("sistem"), peer or body.get("ip"))
                self._json(200, {"ok": True})
                return
            if path == "/v1/kullanicilar" and self.command == "GET":
                self._json(200, {"ok": True, "kullanicilar": self.server.hub.users()})
                return
            if path == "/v1/kullanici" and self.command == "POST":
                body = self._json_body()
                created = self.server.hub.add_user(user, body.get("ad"), body.get("kullanici"), body.get("parola"), body.get("rol") or "Kullanıcı")
                self._json(200, {"ok": True, "kullanici": created})
                return
            if path == "/v1/bilgisayarlar" and self.command == "GET":
                self._json(200, {"ok": True, "bilgisayarlar": self.server.hub.computers()})
                return
            if path == "/v1/dagilim" and self.command == "GET":
                self._json(200, {"ok": True, "dagilim": self.server.hub.distribution()})
                return
            if path == "/v1/talepler" and self.command == "GET":
                self._json(200, {"ok": True, "talepler": self.server.hub.requests_for(user)})
                return
            if path == "/v1/talep" and self.command == "POST":
                body = self._json_body()
                created = self.server.hub.create_request(user, body.get("baslik"), body.get("not"), body.get("kime"))
                self._json(200, {"ok": True, "talep": created})
                return
            if path == "/v1/talep/durum" and self.command == "POST":
                body = self._json_body()
                updated = self.server.hub.set_status(user, body.get("id"), body.get("durum"))
                self._json(200, {"ok": True, "talep": updated})
                return
            if path == "/v1/dosyalar" and self.command == "GET":
                self._json(200, {"ok": True, "dosyalar": self.server.hub.files()})
                return
            if path == "/v1/dosya" and self.command == "POST":
                length = self._length(MAX_FILE)
                payload = self.rfile.read(length) if length else b""
                name = urllib.parse.unquote(self.headers.get("X-Dosya-Ad", ""))
                note = urllib.parse.unquote(self.headers.get("X-Dosya-Not", ""))
                saved = self.server.hub.save_file(user, name, note, payload)
                self._json(200, {"ok": True, "dosya": saved})
                return
            if path == "/v1/dosya" and self.command == "GET":
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                name, payload = self.server.hub.file_bytes((query.get("id") or ["0"])[0])
                quoted = urllib.parse.quote(name)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/v1/mesajlar" and self.command == "GET":
                self._json(200, {"ok": True, "mesajlar": self.server.hub.messages()})
                return
            if path == "/v1/mesaj" and self.command == "POST":
                body = self._json_body()
                self._json(200, {"ok": True, "mesaj": self.server.hub.add_message(user, body.get("metin"))})
                return
            self._json(404, {"ok": False, "error": "Yok."})
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception:
            self._json(500, {"ok": False, "error": "Sunucu isteği tamamlayamadı."})

    def _actor(self):
        return self.server.hub.user_by_token(self._token())

    def _token(self):
        header = self.headers.get("Authorization", "")
        return header[7:].strip() if header.startswith("Bearer ") else ""

    def _length(self, limit):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("İstek boyu okunamadı.") from exc
        if length < 0 or length > limit:
            raise ValueError("İstek boyu geçersiz.")
        return length

    def _json_body(self):
        length = self._length(64 * 1024)
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("İstek okunamadı.") from exc
        if not isinstance(data, dict):
            raise ValueError("İstek okunamadı.")
        return data

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, hub):
        self.hub = hub
        super().__init__(address, Handler)
