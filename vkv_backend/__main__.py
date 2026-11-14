# -*- coding: utf-8 -*-
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from vkv_backend.http import Server
from vkv_backend.hub import Hub
from vkv_backend.settings import data_dir, lan_ips, listen_host, listen_port


def serve(root, host, port):
    hub = Hub(root)
    httpd = Server((host, port), hub)
    ips = lan_ips()
    print("VKV Ağ backend açık.")
    print(f"Veri: {root}")
    print(f"Dinlenen adres: {host}:{port}")
    if ips:
        print("İstemcilerin yazacağı adres:")
        for ip in ips:
            print(f"  {ip}:{port}")
    print(f"Aynı makineden: 127.0.0.1:{port}")
    if hub.needs_setup():
        print(f"İlk yönetici anahtarı: {hub.setup_key}")
    else:
        print("Yönetici kurulu. İstemciler kullanıcı adı ve parola ile girer.")
    print("Kapatmak için Ctrl+C.")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu kapandı.")
    finally:
        httpd.server_close()
        hub.close()


def _self_check():
    import tempfile
    folder = tempfile.TemporaryDirectory()
    hub = Hub(Path(folder.name))
    httpd = Server(("127.0.0.1", 0), hub)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"

    def call(path, payload=None, token="", raw=None, headers=None):
        data = raw if raw is not None else (None if payload is None else json.dumps(payload).encode("utf-8"))
        request = urllib.request.Request(base + path, data=data, method="GET" if data is None else "POST")
        if payload is not None and raw is None:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
                kind = response.headers.get("Content-Type", "")
                return response.status, json.loads(body.decode("utf-8")) if "json" in kind else body
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return exc.code, body

    try:
        status, body = call("/v1/durum")
        assert status == 200 and body["kurulum"]
        status, body = call("/v1/kurulum", {"anahtar": "yanlis", "ad": "Furkan", "kullanici": "furkan", "parola": "parola1"})
        assert status == 400
        status, body = call("/v1/kurulum", {"anahtar": hub.setup_key, "ad": "Furkan Hamarat", "kullanici": "furkan", "parola": "parola1"})
        assert status == 200 and body["kullanici"]["rol"] == "Yönetici"
        status, admin = call("/v1/giris", {"kullanici": "furkan", "parola": "parola1"})
        token = admin["kullanici"]["token"]
        status, created = call("/v1/kullanici", {"ad": "Ali Veli", "kullanici": "ali", "parola": "parola2", "rol": "Kullanıcı"}, token)
        assert created["kullanici"]["kullanici"] == "ali"
        status, talep = call("/v1/talep", {"baslik": "Fatura kontrol", "not": "Mart", "kime": created["kullanici"]["id"]}, token)
        assert talep["talep"]["no"] == "AG-1"
        payload = b"%PDF-1.4 deneme"
        status, saved = call(
            "/v1/dosya", token=token, raw=payload,
            headers={"X-Dosya-Ad": urllib.parse.quote("Mart fatura.pdf"), "X-Dosya-Not": urllib.parse.quote("ortak")},
        )
        status, downloaded = call(f"/v1/dosya?id={saved['dosya']['id']}", token=token)
        assert downloaded == payload
    finally:
        httpd.shutdown()
        httpd.server_close()
        hub.close()
        folder.cleanup()
    print("ok")


def main():
    if "--check" in sys.argv:
        _self_check()
        return
    serve(data_dir(), listen_host(), listen_port())


if __name__ == "__main__":
    main()
