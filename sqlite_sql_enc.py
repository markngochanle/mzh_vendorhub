import argparse
import base64
import hashlib
import hmac
import os
import sqlite3
import zlib
from pathlib import Path

MAGIC = "SQLITE_DUMP_ENC_V1"
SALT_LEN = 16
NONCE_LEN = 16
PBKDF2_ITERS = 200_000
DK_LEN = 64  # 32 bytes enc key + 32 bytes mac key


# -------------------- Crypto (stdlib-only) --------------------
def _derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITERS, dklen=DK_LEN)
    return dk[:32], dk[32:]


def _keystream_block(enc_key: bytes, nonce: bytes, counter: int) -> bytes:
    # 32-byte block (SHA256)
    msg = nonce + counter.to_bytes(4, "big")
    return hmac.new(enc_key, msg, hashlib.sha256).digest()


def _xor_stream(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = _keystream_block(enc_key, nonce, counter)
        n = min(len(block), len(data) - offset)
        for i in range(n):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += n
        counter += 1
    return bytes(out)


def encrypt_bytes(passphrase: str, plaintext: bytes) -> str:
    """
    Returns a TEXT payload (multiple lines) that stores:
      MAGIC
      b64(salt)
      b64(nonce)
      b64(mac)
      b64(ciphertext... possibly long)
    """
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    enc_key, mac_key = _derive_keys(passphrase, salt)

    # Compress first (smaller file + hides patterns)
    compressed = zlib.compress(plaintext, level=9)

    ciphertext = _xor_stream(enc_key, nonce, compressed)
    mac = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()

    b64_ct = base64.b64encode(ciphertext).decode("ascii")
    # wrap ciphertext for readability
    wrapped_ct = "\n".join(b64_ct[i:i+76] for i in range(0, len(b64_ct), 76))

    return "\n".join([
        MAGIC,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
        base64.b64encode(mac).decode("ascii"),
        wrapped_ct,
        ""
    ])


def decrypt_text(passphrase: str, payload_text: str) -> bytes:
    lines = [ln.strip() for ln in payload_text.splitlines() if ln.strip() != ""]
    if len(lines) < 5 or lines[0] != MAGIC:
        raise ValueError("Invalid encrypted dump format (bad MAGIC/header).")

    salt = base64.b64decode(lines[1])
    nonce = base64.b64decode(lines[2])
    mac_expected = base64.b64decode(lines[3])
    ct_b64 = "".join(lines[4:])
    ciphertext = base64.b64decode(ct_b64)

    enc_key, mac_key = _derive_keys(passphrase, salt)

    mac_actual = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac_actual, mac_expected):
        raise ValueError("Bad key or corrupted file (HMAC mismatch).")

    compressed = _xor_stream(enc_key, nonce, ciphertext)
    plaintext = zlib.decompress(compressed)
    return plaintext


# -------------------- SQLite dump/restore --------------------
def sqlite_dump_sql_text(db_path: Path, schema_only: bool = False) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        parts = []
        for line in conn.iterdump():
            if schema_only and line.startswith("INSERT INTO"):
                continue
            parts.append(line)
        return "\n".join(parts) + "\n"
    finally:
        conn.close()


def sqlite_restore_from_sql(db_path: Path, sql_text: str, mode: str):
    """
    mode:
      - replace: delete db file then restore
      - append: keep existing db and executescript (may fail on duplicates)
    """
    if mode not in ("replace", "append"):
        raise ValueError("mode must be replace or append")

    if mode == "replace" and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.executescript(sql_text)
        conn.commit()
    finally:
        conn.close()


# -------------------- CLI --------------------
def cmd_dump(args):
    db_path = Path(args.db).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    print("[DB ]", db_path)
    print("[OUT]", out_path)
    if not args.key:
        raise SystemExit("Missing --key. Example: --key 'your-secret'")

    sql_text = sqlite_dump_sql_text(db_path, schema_only=args.schema_only)
    payload = encrypt_bytes(args.key, sql_text.encode("utf-8"))

    out_path.write_text(payload, encoding="utf-8")
    print("[OK ] Dump encrypted")


def cmd_restore(args):
    enc_path = Path(args.sql_enc).expanduser().resolve()
    out_db = Path(args.out_db).expanduser().resolve()

    if not enc_path.exists():
        raise SystemExit(f"Encrypted SQL file not found: {enc_path}")

    print("[IN ]", enc_path)
    print("[DB ]", out_db, f"(mode={args.mode})")
    if not args.key:
        raise SystemExit("Missing --key. Example: --key 'your-secret'")

    payload_text = enc_path.read_text(encoding="utf-8", errors="ignore")
    sql_bytes = decrypt_text(args.key, payload_text)
    sql_text = sql_bytes.decode("utf-8", errors="strict")

    sqlite_restore_from_sql(out_db, sql_text, mode=args.mode)
    print("[OK ] Restored into SQLite")


def main():
    p = argparse.ArgumentParser(description="SQLite <-> Encrypted SQL dump (stdlib only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="Dump SQLite db -> encrypted SQL file (.sql.enc)")
    p_dump.add_argument("db", help="Path to SQLite db file (e.g. db.sqlite3)")
    p_dump.add_argument("-o", "--out", default="dump.sql.enc", help="Output encrypted SQL file")
    p_dump.add_argument("--schema-only", action="store_true", help="Dump schema only (no data)")
    p_dump.add_argument("--key", required=True, help="Encryption key / passphrase")
    p_dump.set_defaults(func=cmd_dump)

    p_res = sub.add_parser("restore", help="Restore encrypted SQL file -> SQLite db")
    p_res.add_argument("sql_enc", help="Path to encrypted SQL file (.sql.enc)")
    p_res.add_argument("-o", "--out-db", default="db.sqlite3", help="Output SQLite DB file")
    p_res.add_argument("--mode", choices=["replace", "append"], default="replace",
                       help="replace = delete existing db then import; append = import into existing db")
    p_res.add_argument("--key", required=True, help="Encryption key / passphrase (must match dump)")
    p_res.set_defaults(func=cmd_restore)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()