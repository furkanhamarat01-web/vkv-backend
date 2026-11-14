# -*- coding: utf-8 -*-
import hashlib
import os
import secrets
import socket
from pathlib import Path

PORT = 8780
HOST = "0.0.0.0"
MAX_FILE = 20 * 1024 * 1024
FILE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".xls", ".xlsx", ".doc", ".docx"}
ROLES = ("Yönetici", "Kullanıcı")
STATUSES = ("Açık", "Üzerinde", "Tamamlandı")
ONLINE_SECONDS = 20


def data_dir():
    chosen = os.environ.get("VKV_AG_HOME", "").strip().strip('"')
    if chosen:
        root = Path(chosen)
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home()))) / "VKVAg" / "sunucu"
    elif os.name == "posix" and Path("/Library").exists() and "darwin" in os.uname().sysname.lower():
        root = Path.home() / "Library" / "Application Support" / "VKVAg" / "sunucu"
    else:
        root = Path.home() / ".vkv_ag" / "sunucu"
    root.mkdir(parents=True, exist_ok=True)
    (root / "dosyalar").mkdir(parents=True, exist_ok=True)
    return root


def listen_host():
    return os.environ.get("VKV_AG_HOST", HOST).strip() or HOST


def listen_port():
    raw = os.environ.get("VKV_AG_PORT", str(PORT)).strip()
    if not raw.isdigit():
        raise ValueError("VKV_AG_PORT sayı olmalı.")
    port = int(raw)
    if port < 1 or port > 65535:
        raise ValueError("VKV_AG_PORT 1 ile 65535 arasında olmalı.")
    return port


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return salt.hex() + ":" + digest.hex()


def check_password(password, stored):
    try:
        salt_hex, digest_hex = str(stored).split(":", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 120_000)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest.hex(), digest_hex)


def clean_username(value):
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum() or ch in "._-")[:32]


def safe_filename(name):
    base = Path(str(name or "")).name
    suffix = Path(base).suffix.lower()
    if suffix not in FILE_EXT:
        raise ValueError("PDF, görüntü, metin veya ofis dosyası paylaşılır.")
    stem = "".join(ch for ch in Path(base).stem if ch.isalnum() or ch in "._- ")[:80].strip() or "dosya"
    return stem + suffix


def lan_ips():
    found = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        address = info[4][0]
        if address.startswith("127.") or address in found:
            continue
        found.append(address)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.3)
            sock.connect(("1.1.1.1", 80))
            probe = sock.getsockname()[0]
    except OSError:
        probe = ""
    if probe and not probe.startswith("127.") and probe not in found:
        found.insert(0, probe)
    return found
