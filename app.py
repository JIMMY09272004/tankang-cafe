from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# Private settings belong in environment variables or an ignored .env file.


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "shop.sqlite3"
SITE_CONTENT_PATH = DATA_DIR / "site_content.json"
TEXT_OVERRIDES_PATH = DATA_DIR / "text_overrides.json"
UPLOAD_DIR = BASE_DIR / "static" / "images" / "uploads"
ENV_PATH = BASE_DIR / ".env"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv_file()

APP_ENV = os.environ.get("APP_ENV", "development").lower()
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ENABLE_DEMO_ACCOUNT = (
    APP_ENV == "development"
    and os.environ.get("ENABLE_DEMO_ACCOUNT", "false").lower() == "true"
)
DELETED_MEMBER_USERNAME = "__deleted_member__"
if bool(ADMIN_USERNAME) != bool(ADMIN_PASSWORD):
    raise RuntimeError("Set both ADMIN_USERNAME and ADMIN_PASSWORD, or leave both empty.")
if APP_ENV == "production" and (
    not ADMIN_USERNAME
    or len(ADMIN_PASSWORD) < 12
    or not re.search(r"[a-z]", ADMIN_PASSWORD)
    or not re.search(r"[A-Z]", ADMIN_PASSWORD)
    or not re.search(r"\d", ADMIN_PASSWORD)
):
    raise RuntimeError("Production requires a configured admin and a strong password of at least 12 characters.")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if APP_ENV == "production":
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
    SECRET_KEY = secrets.token_hex(32)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    DATABASE=str(DB_PATH),
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower()
    in {"1", "true", "yes"}
    or APP_ENV == "production",
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOGIN_MAX_FAILED = 5
LOGIN_LOCK_SECONDS = 5 * 60
IP_MAX_FAILED = 15
IP_BLOCK_SECONDS = 30 * 60
RESET_EXPIRES_SECONDS = 30 * 60
EMAIL_VERIFY_EXPIRES_SECONDS = 24 * 60 * 60
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
EMAIL_RULE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RULE = re.compile(r"^[0-9+\-\s()]{8,20}$")
IP_RULE = re.compile(r"^[0-9a-fA-F:.]{3,45}$")
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_ALLOWED_HOSTNAMES = {
    item.strip().lower()
    for item in os.environ.get("TURNSTILE_ALLOWED_HOSTNAMES", "example.com").split(",")
    if item.strip()
}
SECURITY_ALERT_EMAIL = os.environ.get("SECURITY_ALERT_EMAIL", "").strip()
SECURITY_ALERT_THROTTLE_SECONDS = 30 * 60
SECURITY_EVENT_SUMMARY_WINDOW = 24 * 60 * 60
SECURITY_404_ALERT_THRESHOLD = 20
SECURITY_LOGIN_ALERT_THRESHOLD = 10
SECURITY_FORM_ALERT_THRESHOLD = 3
SECURITY_ADMIN_ALERT_THRESHOLD = 8
SECURITY_SENSITIVE_ALERT_THRESHOLD = 3
SENSITIVE_CACHE_PATHS = (
    "/admin",
    "/api/",
    "/login",
    "/register",
    "/cart",
    "/checkout",
    "/profile",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/verify-email-sent",
    "/resend-verification",
)
SENSITIVE_SCAN_PREFIXES = (
    "/.env",
    "/.git",
    "/wp-login.php",
    "/wp-admin",
    "/phpmyadmin",
    "/vendor/phpunit",
    "/config",
)
SENSITIVE_SCAN_PATHS = {
    "/.env.bak",
    "/.env.backup",
    "/.env.development",
    "/.env.local",
    "/.env.production",
    "/account.json",
    "/api/config",
    "/api/env",
    "/appsettings.json",
    "/credentials.json",
    "/firebase-adminsdk.json",
    "/google-credentials.json",
    "/key.json",
    "/keyfile.json",
    "/secrets.json",
    "/service-account.json",
    "/actuator/env",
}


CAFE_SITE_CONTENT = {'brand': {'name': '淡江咖啡館', 'english_name': 'TANKANG CAFE',
                             'logo': 'tankang-cafe-logo.png', 'tagline': '想喝咖啡、吃點甜的，歡迎來坐坐。'},
 'hero': {'eyebrow': 'TANKANG CAFE',
          'title': '坐下來，好好喝杯咖啡',
          'copy': '淡江咖啡館有深焙咖啡、手作甜點，也有安靜的座位。一個人來歇歇腳，或約朋友聊聊，都歡迎。',
          'image': 'buna-night-hero.webp'},
 'quality_points': [{'title': '深焙咖啡', 'copy': '喜歡堅果、可可或焦糖香氣，可以從深焙咖啡開始。想加點奶香，就選招牌拿鐵。'},
                    {'title': '手作甜點', 'copy': '布丁、可頌與季節蛋糕，每天小批量製作。點一份配咖啡，也可以和朋友分著吃。'},
                    {'title': '坐下歇一會', 'copy': '木質桌椅配上暖色燈光，適合一個人安靜坐著，也適合和朋友聊聊近況。'}],
 'recommendations': [{'label': 'Coffee', 'copy': '拿鐵、手沖或冷萃，選一杯今天想喝的。'},
                     {'label': 'Drinks', 'copy': '今天不喝咖啡？也有茶飲與季節飲品。'},
                     {'label': 'Delicacies', 'copy': '搭一份甜點或輕食，慢慢吃、慢慢聊。'}]}
CAFE_PRODUCTS = [{'slug': 'signature-latte',
  'name': '淡江招牌拿鐵',
  'category': '咖啡',
  'description': '雙份義式濃縮加上鮮奶與細緻奶泡，喝得到焦糖和堅果香。',
  'price': 150,
  'image': 'buna-coffee-gold.webp',
  'gallery': ['buna-coffee-gold.webp'],
  'benefits': ['濃縮層次', '細緻奶泡', '焦糖尾韻'],
  'ingredients': ['義式濃縮', '鮮奶', '微糖比例'],
  'tags': ['featured', 'coffee', 'latte'],
  'stock': 60,
  'featured': True},
 {'slug': 'single-origin-pour-over',
  'name': '單品手沖咖啡',
  'category': '咖啡',
  'description': '依當日豆單調整研磨與水溫，帶出果酸與咖啡豆的香氣。想知道今天用哪支豆子，歡迎問問店員。',
  'price': 180,
  'image': 'buna-pour-beans.webp',
  'gallery': ['buna-pour-beans.webp'],
  'benefits': ['手沖層次', '單品豆單', '乾淨餘韻'],
  'ingredients': ['單品咖啡豆', '濾泡水'],
  'tags': ['featured', 'coffee', 'pour-over'],
  'stock': 45,
  'featured': True},
 {'slug': 'cold-brew',
  'name': '黑金冷萃咖啡',
  'category': '冷飲',
  'description': '低溫慢萃，帶著巧克力與黑糖香氣，冰涼入口，尾韻柔順。',
  'price': 160,
  'image': 'buna-coffee-gold.webp',
  'gallery': ['buna-coffee-gold.webp'],
  'benefits': ['低溫慢萃', '清爽入口', '黑糖尾韻'],
  'ingredients': ['冷萃咖啡', '冰塊'],
  'tags': ['featured', 'iced', 'coffee'],
  'stock': 50,
  'featured': True},
 {'slug': 'matcha-croissant',
  'name': '抹茶可頌',
  'category': '甜點',
  'description': '酥脆可頌包著抹茶內餡，茶香中帶著奶油香。',
  'price': 135,
  'image': 'buna-delicacies.webp',
  'gallery': ['buna-delicacies.webp'],
  'benefits': ['酥脆層次', '抹茶香氣', '每日現烤'],
  'ingredients': ['麵粉', '奶油', '抹茶餡'],
  'tags': ['featured', 'dessert', 'matcha'],
  'stock': 32,
  'featured': True},
 {'slug': 'caramel-pudding',
  'name': '焦糖布丁',
  'category': '甜點',
  'description': '雞蛋與牛奶慢蒸成滑順布丁，淋上微苦的焦糖。',
  'price': 120,
  'image': 'buna-delicacies.webp',
  'gallery': ['buna-delicacies.webp'],
  'benefits': ['滑順口感', '焦糖苦甜', '小批製作'],
  'ingredients': ['雞蛋', '鮮奶', '糖', '香草'],
  'tags': ['dessert', 'pudding'],
  'stock': 28,
  'featured': False}]
DEFAULT_SITE_CONTENT = CAFE_SITE_CONTENT
DEFAULT_PRODUCTS = CAFE_PRODUCTS
LEGACY_PRODUCT_SLUGS = ("vitamin-c", "om" + "ega" + "-3", "probiotics", "multivitamin")
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


TAIPEI_TZ = timezone(timedelta(hours=8))


def to_taipei_text(ts: int) -> str:
    """Format a unix timestamp as Taiwan local time (UTC+8)."""
    try:
        return datetime.fromtimestamp(int(ts), TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def table_columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def add_column_if_missing(
    db: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if column not in table_columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_user_schema(db: sqlite3.Connection) -> None:
    add_column_if_missing(db, "users", "full_name", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "users", "birthday", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "users", "phone", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "users", "email", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "users", "email_verified_at", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(db, "users", "updated_at", "TEXT NOT NULL DEFAULT ''")
    timestamp = now_iso()
    db.execute(
        """
        UPDATE users
        SET full_name = COALESCE(NULLIF(full_name, ''), display_name),
            updated_at = COALESCE(NULLIF(updated_at, ''), ?)
        WHERE full_name = '' OR updated_at = ''
        """,
        (timestamp,),
    )
    defaults = [
        ("admin", "admin@mellowday.local", "0900000000", "1985-01-01"),
        ("user", "user@mellowday.local", "0911111111", "1990-01-01"),
    ]
    for username, email, phone, birthday in defaults:
        db.execute(
            """
            UPDATE users
            SET email = COALESCE(NULLIF(email, ''), ?),
                phone = COALESCE(NULLIF(phone, ''), ?),
                birthday = COALESCE(NULLIF(birthday, ''), ?)
            WHERE username = ?
            """,
            (email, phone, birthday, username),
        )
    db.execute(
        """
        UPDATE users
        SET email_verified_at = COALESCE(NULLIF(email_verified_at, ''), ?)
        WHERE role = 'admin' OR username IN ('admin', 'user')
        """,
        (timestamp,),
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email != ''"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique ON users(phone) WHERE phone != ''"
    )


def ensure_admin_account(db: sqlite3.Connection) -> None:
    """Ensure the configured admin account exists and uses the current password."""
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return
    timestamp = now_iso()
    password_hash = generate_password_hash(ADMIN_PASSWORD)
    row = db.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if row:
        db.execute(
            """
            UPDATE users
            SET password_hash = ?, role = 'admin', is_active = 1,
                failed_attempts = 0, locked_until = 0,
                email_verified_at = COALESCE(NULLIF(email_verified_at, ''), ?),
                updated_at = ?
            WHERE id = ?
            """,
            (password_hash, timestamp, timestamp, row["id"]),
        )
    else:
        db.execute(
            """
            INSERT INTO users (
                username, password_hash, role, display_name, full_name,
                birthday, phone, email, email_verified_at, is_active, created_at, updated_at
            )
            VALUES (?, ?, 'admin', ?, ?, '1985-01-01', '', ?, ?, 1, ?, ?)
            """,
            (
                ADMIN_USERNAME,
                password_hash,
                "\u6c90\u5149\u7ba1\u7406\u54e1",
                "\u6c90\u5149\u7ba1\u7406\u54e1",
                f"{ADMIN_USERNAME}@mellowday.local",
                timestamp,
                timestamp,
                timestamp,
            ),
        )


def ensure_deleted_member_account(db: sqlite3.Connection) -> int:
    """Return a hidden inactive user used to preserve historical orders."""
    timestamp = now_iso()
    row = db.execute(
        "SELECT id FROM users WHERE username = ?", (DELETED_MEMBER_USERNAME,)
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = db.execute(
        """
        INSERT INTO users (
            username, password_hash, role, display_name, full_name,
            birthday, phone, email, email_verified_at, is_active, created_at, updated_at
        )
        VALUES (?, ?, 'user', ?, ?, '1970-01-01', '', '', ?, 0, ?, ?)
        """,
        (
            DELETED_MEMBER_USERNAME,
            generate_password_hash(secrets.token_urlsafe(32)),
            "已刪除會員",
            "已刪除會員",
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    return int(cursor.lastrowid)


def migrate_cafe_copy(db: sqlite3.Connection) -> None:
    """Update known starter copy without replacing later admin edits."""
    timestamp = now_iso()
    db.execute(
        "UPDATE products SET name = ?, updated_at = ? WHERE slug = ? AND name = ?",
        ("淡江招牌拿鐵", timestamp, "signature-latte", "沐光招牌拿鐵"),
    )
    old_descriptions = {
        "signature-latte": "雙份 espresso 與細緻奶泡融合，帶有焦糖與堅果香氣。",
        "single-origin-pour-over": "依當日豆單調整研磨與水溫，呈現明亮果酸與乾淨餘韻。",
        "cold-brew": "低溫慢萃帶出巧克力與黑糖調性，入口清爽、尾韻柔順。",
        "matcha-croissant": "酥脆外層搭配抹茶內餡，茶香與奶油香氣平衡。",
        "caramel-pudding": "雞蛋與牛奶慢蒸成滑順口感，搭配微苦焦糖。",
    }
    for product in CAFE_PRODUCTS:
        old_description = old_descriptions.get(product["slug"])
        if old_description:
            db.execute(
                "UPDATE products SET description = ?, updated_at = ? WHERE slug = ? AND description = ?",
                (product["description"], timestamp, product["slug"], old_description),
            )
    for old, new in (
        ("沐光咖啡正式開幕", "淡江咖啡館正式開幕"),
        ("沐光咖啡晚間座位開放", "淡江咖啡館晚間座位開放"),
        ("季節新品：抹茶奶霜可頌登場", "季節新品：抹茶奶霜可頌"),
    ):
        db.execute("UPDATE announcements SET title = ?, updated_at = ? WHERE title = ?", (new, timestamp, old))
    for old, new in (
        ("歡迎光臨沐光咖啡！即日起提供每日現磨咖啡、手作甜點與線上訂位服務，週末歡迎提早預約座位。",
         "淡江咖啡館開幕了，歡迎來喝杯現磨咖啡、吃份手作甜點。週末來訪建議提早訂位，線上送出申請後，請等候店家確認。"),
        ("晚間時段新增黑金吧台座位與手沖服務，歡迎先行訂位，讓我們替你保留一段安靜的咖啡時間。",
         "晚間新增吧台座位與手沖服務。想來坐坐，歡迎先訂位，座位以店家回覆確認為準。"),
        ("選用日本宇治抹茶製作的奶霜，搭配現烤可頌，茶香濃郁、甜度收斂，數量有限，售完為止。",
         "日本宇治抹茶做成奶霜，搭配現烤可頌，茶香濃郁、甜度不高。每日數量有限，售完為止。"),
    ):
        db.execute("UPDATE announcements SET body = ?, updated_at = ? WHERE body = ?", (new, timestamp, old))


def sync_cafe_catalog(db: sqlite3.Connection) -> None:
    migrate_cafe_copy(db)
    timestamp = now_iso()
    legacy_sql = ",".join("?" for _ in LEGACY_PRODUCT_SLUGS)
    db.execute(
        f"""
        UPDATE products
        SET name = ?,
            category = ?,
            description = ?,
            image = '',
            gallery_json = '[]',
            benefits_json = '[]',
            ingredients_json = '[]',
            tags_json = '[]',
            active = 0,
            featured = 0,
            updated_at = ?
        WHERE slug IN ({legacy_sql})
        """,
        ("\u5df2\u4e0b\u67b6\u820a\u54c1\u9805", "\u5df2\u4e0b\u67b6", "\u6b64\u820a\u54c1\u9805\u5df2\u5f9e\u524d\u53f0\u79fb\u9664\u3002", timestamp, *LEGACY_PRODUCT_SLUGS),
    )
    db.execute(
        f"""
        UPDATE order_items
        SET product_name = ?
        WHERE product_id IN (
            SELECT id FROM products WHERE slug IN ({legacy_sql})
        )
        """,
        ("\u5df2\u4e0b\u67b6\u820a\u54c1\u9805", *LEGACY_PRODUCT_SLUGS),
    )
    old_admin_email = "admin@" + "nour" + "isync.local"
    old_user_email = "user@" + "nour" + "isync.local"
    old_member_name = "Nour" + "isync " + "\u6703\u54e1"
    db.execute(
        """
        UPDATE users
        SET email = 'admin@mellowday.local', updated_at = ?
        WHERE username = 'admin' AND email = ?
        """,
        (timestamp, old_admin_email),
    )
    db.execute(
        """
        UPDATE users
        SET email = 'user@mellowday.local',
            display_name = ?,
            full_name = ?,
            updated_at = ?
        WHERE username = 'user'
          AND (email = ? OR display_name = ? OR full_name = ?)
        """,
        ("\u6c90\u5149\u6703\u54e1", "\u6c90\u5149\u6703\u54e1", timestamp, old_user_email, old_member_name, old_member_name),
    )
    for product in CAFE_PRODUCTS:
        row = db.execute(
            "SELECT id FROM products WHERE slug = ?", (product["slug"],)
        ).fetchone()
        payload = (
            product["slug"], product["name"], product["category"], product["description"],
            product["price"], product["image"], encode_json(product["gallery"]),
            encode_json(product["benefits"]), encode_json(product["ingredients"]),
            encode_json(product["tags"]), product["stock"], 1 if product["featured"] else 0,
            1, timestamp,
        )
        if not row:
            db.execute(
                """
                INSERT INTO products (
                    slug, name, category, description, price, image, gallery_json,
                    benefits_json, ingredients_json, tags_json, stock, featured,
                    active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*payload, timestamp),
            )


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
                display_name TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                birthday TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                email_verified_at TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                price INTEGER NOT NULL CHECK(price >= 0),
                image TEXT NOT NULL DEFAULT '',
                gallery_json TEXT NOT NULL DEFAULT '[]',
                benefits_json TEXT NOT NULL DEFAULT '[]',
                ingredients_json TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                featured INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cart_items (
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                qty INTEGER NOT NULL CHECK(qty > 0),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, product_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                total INTEGER NOT NULL CHECK(total >= 0),
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                qty INTEGER NOT NULL CHECK(qty > 0),
                unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
                subtotal INTEGER NOT NULL CHECK(subtotal >= 0),
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                code_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at TEXT,
                request_ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS email_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL,
                used_at TEXT,
                request_ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                party_size INTEGER NOT NULL CHECK(party_size > 0),
                reserved_date TEXT NOT NULL,
                reserved_time TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unread',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ip_guard (
                ip TEXT PRIMARY KEY,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                blocked_until INTEGER NOT NULL DEFAULT 0,
                manual_block INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket TEXT NOT NULL,
                ip TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rate_limits_bucket_ip_created
                ON rate_limits(bucket, ip, created_at);

            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                created_at_text TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_security_events_type_ip_created
                ON security_events(event_type, ip, created_at);

            CREATE INDEX IF NOT EXISTS idx_security_events_created
                ON security_events(created_at);

            CREATE TABLE IF NOT EXISTS security_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_key TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                last_sent_at INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        migrate_user_schema(db)

        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 0 and ENABLE_DEMO_ACCOUNT:
            created_at = now_iso()
            db.execute(
                """
                INSERT INTO users (
                    username, password_hash, role, display_name, full_name,
                    birthday, phone, email, email_verified_at, is_active, created_at, updated_at
                )
                VALUES (?, ?, 'user', ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "user",
                    generate_password_hash("LocalDemo123"),
                    "\u6c90\u5149\u6703\u54e1",
                    "\u6c90\u5149\u6703\u54e1",
                    "1990-01-01",
                    "0911111111",
                    "user@mellowday.local",
                    created_at,
                    created_at,
                    created_at,
                ),
            )


        ensure_admin_account(db)
        ensure_deleted_member_account(db)

        product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if product_count == 0:
            created_at = now_iso()
            db.executemany(
                """
                INSERT INTO products (
                    slug, name, category, description, price, image, gallery_json,
                    benefits_json, ingredients_json, tags_json, stock, featured,
                    active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                [
                    (
                        product["slug"],
                        product["name"],
                        product["category"],
                        product["description"],
                        product["price"],
                        product["image"],
                        encode_json(product["gallery"]),
                        encode_json(product["benefits"]),
                        encode_json(product["ingredients"]),
                        encode_json(product["tags"]),
                        product["stock"],
                        1 if product["featured"] else 0,
                        created_at,
                        created_at,
                    )
                    for product in DEFAULT_PRODUCTS
                ],
            )

        announcement_count = db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
        if announcement_count == 0:
            created_at = now_iso()
            db.executemany(
                """
                INSERT INTO announcements (title, body, pinned, published, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                [
                    (
                        "淡江咖啡館晚間座位開放",
                        "晚間新增吧台座位與手沖服務。想來坐坐，歡迎先訂位，座位以店家回覆確認為準。",
                        1,
                        created_at,
                        created_at,
                    ),
                    (
                        "單品手沖豆單更新",
                        "本週加入帶有莓果與可可尾韻的單品豆，適合喜歡乾淨酸質與細緻香氣的客人。",
                        0,
                        created_at,
                        created_at,
                    ),
                ],
            )


        sync_cafe_catalog(db)
        db.commit()

    if not SITE_CONTENT_PATH.exists():
        SITE_CONTENT_PATH.write_text(
            json.dumps(DEFAULT_SITE_CONTENT, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_site_content() -> dict:
    if not SITE_CONTENT_PATH.exists():
        return DEFAULT_SITE_CONTENT
    try:
        return json.loads(SITE_CONTENT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_SITE_CONTENT


TEXT_KEY_RULE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


def load_text_overrides() -> dict:
    if not TEXT_OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(TEXT_OVERRIDES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_text_overrides(data: dict) -> None:
    TEXT_OVERRIDES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clean_text(value, max_len: int, *, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise ValueError("\u8acb\u586b\u5beb\u5fc5\u586b\u6b04\u4f4d\u3002")
    if len(value) > max_len:
        raise ValueError(f"\u5167\u5bb9\u9577\u5ea6\u4e0d\u53ef\u8d85\u904e {max_len} \u5b57\u3002")
    return value


def normalize_email(value, *, required: bool = True) -> str:
    email = clean_text(value, 120, required=required).lower()
    if email and not EMAIL_RULE.match(email):
        raise ValueError("Email \u683c\u5f0f\u4e0d\u6b63\u78ba\u3002")
    return email


def normalize_phone(value, *, required: bool = True) -> str:
    phone = clean_text(value, 30, required=required)
    if phone and not PHONE_RULE.match(phone):
        raise ValueError("\u96fb\u8a71\u683c\u5f0f\u4e0d\u6b63\u78ba\u3002")
    return phone


def normalize_birthday(value) -> str:
    birthday = clean_text(value, 10)
    try:
        parsed = datetime.strptime(birthday, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("\u751f\u65e5\u683c\u5f0f\u61c9\u70ba YYYY-MM-DD\u3002") from exc
    if parsed > datetime.now().date():
        raise ValueError("\u751f\u65e5\u4e0d\u80fd\u665a\u65bc\u4eca\u5929\u3002")
    return birthday


def validate_password(password: str, confirm: str | None = None) -> None:
    if confirm is not None and password != confirm:
        raise ValueError("\u5169\u6b21\u8f38\u5165\u7684\u5bc6\u78bc\u4e0d\u4e00\u81f4\u3002")
    if not PASSWORD_RULE.match(password or ""):
        raise ValueError("\u5bc6\u78bc\u81f3\u5c11 8 \u78bc\uff0c\u4e14\u9700\u5305\u542b\u5927\u5beb\u82f1\u6587\u3001\u5c0f\u5beb\u82f1\u6587\u8207\u6578\u5b57\u3002")


def hash_reset_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_positive_int(value, label: str, *, allow_zero: bool = True) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} \u5fc5\u9808\u662f\u6578\u5b57\u3002") from exc
    if allow_zero and number < 0:
        raise ValueError(f"{label} \u4e0d\u80fd\u5c0f\u65bc 0\u3002")
    if not allow_zero and number <= 0:
        raise ValueError(f"{label} \u5fc5\u9808\u5927\u65bc 0\u3002")
    return number


def split_lines(value) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item, 80, required=False) for item in value if str(item).strip()]
    text = value or ""
    return [item.strip() for item in text.replace(",", "\n").splitlines() if item.strip()]


def slugify(value: str) -> str:
    slug = []
    previous_dash = False
    for char in value.lower():
        if char.isascii() and char.isalnum():
            slug.append(char)
            previous_dash = False
        elif not previous_dash:
            slug.append("-")
            previous_dash = True
    result = "".join(slug).strip("-")
    return result or f"product-{uuid.uuid4().hex[:8]}"


def ensure_unique_slug(base_slug: str, product_id: int | None = None) -> str:
    db = get_db()
    slug = base_slug
    counter = 2
    while True:
        if product_id:
            row = db.execute(
                "SELECT id FROM products WHERE slug = ? AND id != ?", (slug, product_id)
            ).fetchone()
        else:
            row = db.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    row = get_db().execute(
        """
        SELECT
            id, username, role, display_name, full_name, birthday,
            phone, email, email_verified_at, is_active
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row or not row["is_active"]:
        session.clear()
        return None
    return dict(row)


def wants_json_response() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def login_required(role: str | None = None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if wants_json_response():
                    return jsonify({"error": "login_required"}), 401
                return redirect(url_for("login", next=request.full_path))
            if role and user["role"] != role:
                if wants_json_response():
                    return jsonify({"error": "forbidden"}), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def protect_csrf():
    if request.method in SAFE_METHODS or request.endpoint == "static":
        return None
    expected = session.get("_csrf_token")
    submitted = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-CSRF-Token")
    )
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        record_security_event(
            "csrf_failed",
            detail={"endpoint": request.endpoint or "", "content_type": request.content_type or ""},
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=600,
        )
        if wants_json_response():
            return jsonify({"error": "csrf_failed"}), 400
        abort(400)
    return None


@app.before_request
def monitor_suspicious_request():
    if request.endpoint == "static":
        return None
    path = request.path.lower()
    ip = client_ip()
    if ip and ip_is_blocked(ip):
        return None
    if path in SENSITIVE_SCAN_PATHS or any(path == prefix or path.startswith(f"{prefix}/") for prefix in SENSITIVE_SCAN_PREFIXES):
        record_security_event(
            "sensitive_path",
            detail={"query": request.query_string.decode("utf-8", errors="ignore")[:300]},
            ip=ip,
            alert_threshold=SECURITY_SENSITIVE_ALERT_THRESHOLD,
            alert_window=600,
        )
    elif path.startswith("/admin"):
        user = current_user()
        if not user or user["role"] != "admin":
            record_security_event(
                "admin_probe",
                detail={"endpoint": request.endpoint or ""},
                ip=ip,
                alert_threshold=SECURITY_ADMIN_ALERT_THRESHOLD,
                alert_window=600,
            )
    return None


@app.before_request
def block_guarded_ip():
    if request.endpoint == "static":
        return None
    ip = client_ip()
    if not ip or not ip_is_blocked(ip):
        return None
    user = current_user()
    if user and user["role"] == "admin" and request.path.startswith("/admin/security"):
        return None
    if wants_json_response():
        return jsonify({"error": "ip_blocked"}), 403
    abort(403)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    if APP_ENV == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    request_path = request.path.lower() if has_request_context() else ""
    if request_path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif (
        wants_json_response()
        or any(request_path == path or request_path.startswith(f"{path}/") for path in SENSITIVE_CACHE_PATHS)
    ):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


USE_MIN_ASSETS = APP_ENV == "production"


def asset(filename: str) -> str:
    """Return minified static assets in production when available, with a cache-busting version."""
    rel = filename
    if USE_MIN_ASSETS and "." in filename:
        base, _, ext = filename.rpartition(".")
        min_rel = f"dist/{base.rsplit('/', 1)[-1]}.min.{ext}"
        if (BASE_DIR / "static" / min_rel).exists():
            rel = min_rel
    try:
        version = int((BASE_DIR / "static" / rel).stat().st_mtime)
    except OSError:
        version = 0
    return url_for("static", filename=rel, v=version)


@app.context_processor
def inject_template_globals():
    user = current_user()
    overrides = load_text_overrides()

    def ed(key: str, default: str = "") -> str:
        """Return editable text override, falling back to the template default."""
        return overrides.get(key, default)

    return {
        "brand": {**DEFAULT_SITE_CONTENT["brand"], **load_site_content().get("brand", {})},
        "current_user": user,
        "csrf_token": csrf_token,
        "editor_enabled": bool(user and user["role"] == "admin"),
        "ed": ed,
        "asset": asset,
        "turnstile_enabled": turnstile_should_render(),
        "turnstile_site_key": TURNSTILE_SITE_KEY,
    }


def log_audit(action: str, detail: dict | str, actor_id: int | None = None) -> None:
    if actor_id is None:
        user = current_user()
        actor_id = user["id"] if user else None
    if not isinstance(detail, str):
        detail = encode_json(detail)
    db = get_db()
    db.execute(
        """
        INSERT INTO audit_logs (actor_id, action, detail, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (actor_id, action, detail, now_iso()),
    )
    db.commit()


def find_user_by_contact(contact: str):
    value = clean_text(contact, 120, required=False)
    if not value:
        return None
    email = value.lower()
    return get_db().execute(
        "SELECT * FROM users WHERE email = ?",
        (email,),
    ).fetchone()


def find_duplicate_user(username: str, email: str, *, exclude_id: int | None = None):
    params = [username, email]
    query = """
        SELECT username, email, phone
        FROM users
        WHERE (username = ? OR email = ?)
    """
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    return get_db().execute(query, tuple(params)).fetchone()


def duplicate_message(row, username: str, email: str) -> str:
    if not row:
        return ""
    if row["username"] == username:
        return "此帳號已被註冊。"
    if row["email"] == email:
        return "此電子郵件已被註冊。"
    return "帳號或電子郵件已被使用。"


def user_by_id(user_id: int):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_email_verification(user_row, request_ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    get_db().execute(
        """
        INSERT INTO email_verifications (
            user_id, token_hash, expires_at, request_ip, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_row["id"],
            hash_reset_secret(token),
            int(time.time()) + EMAIL_VERIFY_EXPIRES_SECONDS,
            request_ip or "",
            now_iso(),
        ),
    )
    get_db().commit()
    return token


def create_password_reset(user_row, request_ip: str = "") -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = int(time.time()) + RESET_EXPIRES_SECONDS
    db = get_db()
    db.execute(
        """
        INSERT INTO password_resets (
            user_id, token_hash, code_hash, expires_at, request_ip, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_row["id"],
            hash_reset_secret(token),
            hash_reset_secret(code),
            expires_at,
            request_ip or "",
            now_iso(),
        ),
    )
    db.commit()
    return token, code


def send_email(to_email: str, subject: str, body: str) -> bool:
    server = os.environ.get("MAIL_SERVER", "").strip()
    from_email = os.environ.get("MAIL_FROM", "").strip() or os.environ.get(
        "MAIL_USERNAME", ""
    ).strip()
    if not server or not from_email:
        return False

    port = int(os.environ.get("MAIL_PORT", "587"))
    username = os.environ.get("MAIL_USERNAME", "")
    password = os.environ.get("MAIL_PASSWORD", "")
    use_tls = os.environ.get("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes"}

    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(server, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_email_verification(user_row, token: str) -> bool:
    brand_name = load_site_content().get("brand", DEFAULT_SITE_CONTENT["brand"]).get(
        "name", DEFAULT_SITE_CONTENT["brand"]["name"]
    )
    verify_link = url_for("verify_email", token=token, _external=True)
    recipient = user_row["full_name"] or user_row["display_name"] or user_row["username"]
    body = (
        f"\u60a8\u597d {recipient}\uff1a\n\n"
        f"\u8acb\u9ede\u64ca\u4ee5\u4e0b\u9023\u7d50\u5b8c\u6210 {brand_name} Email \u9a57\u8b49\uff1a\n"
        f"{verify_link}\n\n"
        "\u6b64\u9023\u7d50 24 \u5c0f\u6642\u5167\u6709\u6548\u3002\n"
        "\u82e5\u60a8\u6c92\u6709\u8a3b\u518a\uff0c\u8acb\u5ffd\u7565\u6b64\u4fe1\u3002"
    )
    return send_email(user_row["email"], f"{brand_name} Email \u9a57\u8b49", body)


def send_password_reset_email(user_row, token: str, code: str) -> bool:
    brand_name = load_site_content().get("brand", DEFAULT_SITE_CONTENT["brand"]).get(
        "name", DEFAULT_SITE_CONTENT["brand"]["name"]
    )
    reset_link = url_for("reset_password_token", token=token, _external=True)
    recipient = user_row["full_name"] or user_row["display_name"] or user_row["username"]
    body = (
        f"\u60a8\u597d {recipient}\uff1a\n\n"
        f"\u6211\u5011\u6536\u5230 {brand_name} \u5bc6\u78bc\u91cd\u8a2d\u8acb\u6c42\u3002\n"
        "\u60a8\u53ef\u4ee5\u9ede\u64ca\u4ee5\u4e0b 30 \u5206\u9418\u5167\u6709\u6548\u7684\u9023\u7d50\u91cd\u8a2d\u5bc6\u78bc\uff1a\n"
        f"{reset_link}\n\n"
        "\u4e5f\u53ef\u4ee5\u56de\u5230\u7db2\u7ad9\u8f38\u5165\u4ee5\u4e0b 6 \u4f4d\u6578\u9a57\u8b49\u78bc\uff1a\n"
        f"{code}\n\n"
        "\u82e5\u60a8\u6c92\u6709\u7533\u8acb\u91cd\u8a2d\u5bc6\u78bc\uff0c\u8acb\u5ffd\u7565\u6b64\u4fe1\u3002"
    )
    return send_email(user_row["email"], f"{brand_name} \u5bc6\u78bc\u91cd\u8a2d", body)


def send_member_notice_email(user_row, subject: str, body: str) -> bool:
    brand_name = load_site_content().get("brand", DEFAULT_SITE_CONTENT["brand"]).get(
        "name", DEFAULT_SITE_CONTENT["brand"]["name"]
    )
    recipient = user_row["full_name"] or user_row["display_name"] or user_row["username"]
    message = (
        f"您好 {recipient}：\n\n"
        f"{body}\n\n"
        f"{brand_name}"
    )
    return send_email(user_row["email"], f"{brand_name}｜{subject}", message)


def security_alert_recipient() -> str:
    return (
        SECURITY_ALERT_EMAIL
        or os.environ.get("MAIL_FROM", "").strip()
        or os.environ.get("MAIL_USERNAME", "").strip()
    )


def security_event_count(event_type: str, ip: str, window: int) -> int:
    cutoff = int(time.time()) - window
    row = get_db().execute(
        """
        SELECT COUNT(*) AS c
        FROM security_events
        WHERE event_type = ? AND ip = ? AND created_at >= ?
        """,
        (event_type, ip or "", cutoff),
    ).fetchone()
    return int(row["c"] if row else 0)


def maybe_send_security_alert(event_type: str, ip: str, total: int, window: int, detail: dict) -> None:
    recipient = security_alert_recipient()
    now_ts = int(time.time())
    alert_key = f"{event_type}:{ip or 'unknown'}"
    timestamp = now_iso()
    db = get_db()
    row = db.execute(
        "SELECT * FROM security_alerts WHERE alert_key = ?", (alert_key,)
    ).fetchone()
    if row and now_ts - int(row["last_sent_at"]) < SECURITY_ALERT_THROTTLE_SECONDS:
        return
    if row:
        cursor = db.execute(
            """
            UPDATE security_alerts
            SET event_type = ?, ip = ?, last_sent_at = ?, updated_at = ?
            WHERE alert_key = ? AND last_sent_at <= ?
            """,
            (
                event_type,
                ip or "",
                now_ts,
                timestamp,
                alert_key,
                now_ts - SECURITY_ALERT_THROTTLE_SECONDS,
            ),
        )
        if cursor.rowcount == 0:
            db.commit()
            return
    else:
        try:
            db.execute(
                """
                INSERT INTO security_alerts (
                    alert_key, event_type, ip, last_sent_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_key, event_type, ip or "", now_ts, timestamp, timestamp),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return
    db.commit()

    sent = False
    if recipient:
        path = request.path if has_request_context() else detail.get("path", "")
        brand_name = load_site_content().get("brand", {}).get("name", DEFAULT_SITE_CONTENT["brand"]["name"])
        subject = f"[{brand_name} Security] {event_type} from {ip or 'unknown'}"
        body = (
            f"Security alert from {brand_name}.\n\n"
            f"Event: {event_type}\n"
            f"IP: {ip or 'unknown'}\n"
            f"Path: {path}\n"
            f"Count: {total} events in {window // 60} minutes\n"
            f"Time: {now_iso()}\n\n"
            "Details:\n"
            f"{json.dumps(detail, ensure_ascii=False, indent=2)}"
        )
        try:
            sent = send_email(recipient, subject, body)
        except OSError:
            sent = False
    log_audit(
        "security_alert",
        {"event_type": event_type, "ip": ip, "count": total, "email_sent": sent},
        actor_id=None,
    )


def record_security_event(
    event_type: str,
    *,
    detail: dict | None = None,
    ip: str | None = None,
    path: str | None = None,
    method: str | None = None,
    alert_threshold: int | None = None,
    alert_window: int = 600,
) -> None:
    if not has_request_context() and not ip:
        ip = ""
    event_ip = (ip if ip is not None else client_ip())[:45]
    # 只記錄對外(公網)IP，略過本機/內網位址。
    if not is_public_ip(event_ip):
        return
    event_path = (path if path is not None else (request.path if has_request_context() else ""))[:500]
    event_method = (method if method is not None else (request.method if has_request_context() else ""))[:12]
    payload = detail or {}
    now_ts = int(time.time())
    db = get_db()
    db.execute(
        """
        INSERT INTO security_events (
            ip, event_type, path, method, detail, created_at, created_at_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event_ip, event_type, event_path, event_method, encode_json(payload), now_ts, now_iso()),
    )
    db.commit()
    if alert_threshold:
        total = security_event_count(event_type, event_ip, alert_window)
        if total >= alert_threshold:
            maybe_send_security_alert(event_type, event_ip, total, alert_window, payload)
            if event_type in {"not_found", "sensitive_path", "admin_probe"}:
                auto_block_security_ip(event_ip, event_type)


def security_event_rows(limit: int = 80) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT *
        FROM security_events
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["detail_data"] = decode_json(item.get("detail"), {})
        item["kind"] = ip_kind(item.get("ip") or "")
        item["created_at_local"] = to_taipei_text(item.get("created_at")) or item.get("created_at_text", "")
        result.append(item)
    return result


def security_event_summary(window: int = SECURITY_EVENT_SUMMARY_WINDOW) -> list[dict]:
    cutoff = int(time.time()) - window
    rows = get_db().execute(
        """
        SELECT event_type, COUNT(*) AS count, COUNT(DISTINCT ip) AS ip_count, MAX(created_at_text) AS last_seen
        FROM security_events
        WHERE created_at >= ?
        GROUP BY event_type
        ORDER BY count DESC, event_type ASC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(row) for row in rows]


def cloudflare_config_status() -> dict:
    hostname = os.environ.get("CLOUDFLARE_HOSTNAME", "example.com").strip() or "example.com"
    return {
        "hostname": hostname,
        "api_token_configured": bool(os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()),
        "zone_id_configured": bool(os.environ.get("CLOUDFLARE_ZONE_ID", "").strip()),
        "alert_email": security_alert_recipient(),
    }


def set_user_password(user_id: int, password: str) -> None:
    get_db().execute(
        """
        UPDATE users
        SET password_hash = ?, failed_attempts = 0, locked_until = 0, updated_at = ?
        WHERE id = ?
        """,
        (generate_password_hash(password), now_iso(), user_id),
    )


def product_from_row(row, *, public: bool = True) -> dict:
    product = {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"],
        "price": row["price"],
        "image": row["image"],
        "image_url": url_for("static", filename=f"images/{row['image']}")
        if row["image"]
        else "",
        "gallery": decode_json(row["gallery_json"], []),
        "benefits": decode_json(row["benefits_json"], []),
        "ingredients": decode_json(row["ingredients_json"], []),
        "tags": decode_json(row["tags_json"], []),
        "featured": bool(row["featured"]),
    }
    if public:
        product["availability"] = "in_stock" if row["stock"] > 0 else "sold_out"
    else:
        product.update(
            {
                "stock": row["stock"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return product


def get_products(*, include_inactive: bool = False) -> list[dict]:
    query = "SELECT * FROM products"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY featured DESC, id ASC"
    rows = get_db().execute(query).fetchall()
    return [product_from_row(row, public=not include_inactive) for row in rows]


def get_admin_menu_products() -> list[dict]:
    return [
        product
        for product in get_products(include_inactive=True)
        if product["category"] != "已下架"
    ]


def get_product_by_slug(slug: str):
    row = get_db().execute(
        "SELECT * FROM products WHERE slug = ? AND active = 1", (slug,)
    ).fetchone()
    return product_from_row(row, public=True) if row else None


def get_product_row(product_id: int):
    return get_db().execute(
        "SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)
    ).fetchone()


RESERVATION_STATUSES = ["new", "confirmed", "seated", "cancelled"]
MESSAGE_STATUSES = ["unread", "read", "archived"]


def normalize_reservation_time(value) -> str:
    text = clean_text(value, 5)
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("請輸入正確的時間格式（HH:MM）。") from exc
    return parsed.strftime("%H:%M")


def normalize_reservation_date(value) -> str:
    text = clean_text(value, 10)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("請輸入正確的日期格式（YYYY-MM-DD）。") from exc
    if parsed < datetime.now().date():
        raise ValueError("訂位日期不能早於今天。")
    return text


def create_reservation(payload) -> int:
    name = clean_text(payload.get("name"), 60)
    phone = normalize_phone(payload.get("phone"))
    email = normalize_email(payload.get("email"), required=False)
    party_size = parse_positive_int(payload.get("party_size"), "訂位人數", allow_zero=False)
    if party_size > 50:
        raise ValueError("訂位人數最多為 50 人，大型包場請使用聯絡表單洽詢。")
    reserved_date = normalize_reservation_date(payload.get("reserved_date"))
    reserved_time = normalize_reservation_time(payload.get("reserved_time"))
    note = clean_text(payload.get("note"), 240, required=False)
    timestamp = now_iso()
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO reservations (
            name, phone, email, party_size, reserved_date, reserved_time,
            note, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
        """,
        (name, phone, email, party_size, reserved_date, reserved_time, note, timestamp, timestamp),
    )
    db.commit()
    return cursor.lastrowid


def reservation_rows(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM reservations"
    params: tuple = ()
    if status and status in RESERVATION_STATUSES:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY reserved_date ASC, reserved_time ASC, created_at DESC"
    return [dict(row) for row in get_db().execute(query, params).fetchall()]


def create_message(payload) -> int:
    name = clean_text(payload.get("name"), 60)
    email = normalize_email(payload.get("email"), required=False)
    phone = normalize_phone(payload.get("phone"), required=False)
    subject = clean_text(payload.get("subject"), 120, required=False)
    body = clean_text(payload.get("body"), 1000)
    timestamp = now_iso()
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO messages (name, email, phone, subject, body, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'unread', ?, ?)
        """,
        (name, email, phone, subject, body, timestamp, timestamp),
    )
    db.commit()
    return cursor.lastrowid


def message_rows(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM messages"
    params: tuple = ()
    if status and status in MESSAGE_STATUSES:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    return [dict(row) for row in get_db().execute(query, params).fetchall()]


def announcement_rows(*, published_only: bool = False, limit: int | None = None) -> list[dict]:
    query = "SELECT * FROM announcements"
    if published_only:
        query += " WHERE published = 1"
    query += " ORDER BY pinned DESC, created_at DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    return [dict(row) for row in get_db().execute(query).fetchall()]


def get_announcement(announcement_id: int):
    return get_db().execute(
        "SELECT * FROM announcements WHERE id = ?", (announcement_id,)
    ).fetchone()


def announcement_form_payload() -> dict:
    return {
        "title": clean_text(request.form.get("title"), 100),
        "body": clean_text(request.form.get("body"), 2000),
        "pinned": 1 if str(request.form.get("pinned", "")).lower() in {"1", "true", "on", "yes"} else 0,
        "published": 1 if str(request.form.get("published", "")).lower() in {"1", "true", "on", "yes"} else 0,
    }


SUBMIT_MAX = 5
SUBMIT_WINDOW = 600


def submission_rate_limited(bucket: str, ip: str, max_count: int = SUBMIT_MAX, window: int = SUBMIT_WINDOW) -> bool:
    """Persistently rate-limit repeated public submissions by IP and bucket."""
    if not ip:
        return False
    now_ts = int(time.time())
    cutoff = now_ts - window
    db = get_db()
    db.execute(
        "DELETE FROM rate_limits WHERE bucket = ? AND ip = ? AND created_at < ?",
        (bucket, ip, cutoff),
    )
    row = db.execute(
        "SELECT COUNT(*) AS c FROM rate_limits WHERE bucket = ? AND ip = ? AND created_at >= ?",
        (bucket, ip, cutoff),
    ).fetchone()
    if int(row["c"]) >= max_count:
        db.commit()
        record_security_event(
            f"rate_limit_{bucket}",
            detail={"bucket": bucket, "max_count": max_count, "window": window},
            ip=ip,
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=window,
        )
        return True
    db.execute(
        "INSERT INTO rate_limits (bucket, ip, created_at) VALUES (?, ?, ?)",
        (bucket, ip, now_ts),
    )
    db.commit()
    return False


def is_local_request() -> bool:
    if not has_request_context():
        return True
    host = request.host.split(":", 1)[0].lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def turnstile_should_render() -> bool:
    return bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY) and not is_local_request()


def verify_turnstile(action: str) -> bool:
    if not turnstile_should_render():
        return True
    token = request.form.get("cf-turnstile-response", "").strip()
    if not token:
        record_security_event(
            "turnstile_failed",
            detail={"action": action, "reason": "missing_token"},
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=600,
        )
        return False
    payload = urllib.parse.urlencode(
        {
            "secret": TURNSTILE_SECRET_KEY,
            "response": token,
            "remoteip": client_ip(),
        }
    ).encode("utf-8")
    api_request = urllib.request.Request(
        TURNSTILE_VERIFY_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(api_request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        record_security_event(
            "turnstile_failed",
            detail={"action": action, "reason": "verify_error"},
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=600,
        )
        return False
    if not result.get("success"):
        record_security_event(
            "turnstile_failed",
            detail={"action": action, "reason": "not_success", "codes": result.get("error-codes", [])},
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=600,
        )
        return False
    response_action = str(result.get("action") or "")
    if response_action and response_action != action:
        record_security_event(
            "turnstile_failed",
            detail={"action": action, "reason": "action_mismatch", "response_action": response_action},
            alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
            alert_window=600,
        )
        return False
    response_hostname = str(result.get("hostname") or "").lower()
    if TURNSTILE_ALLOWED_HOSTNAMES and response_hostname:
        allowed = response_hostname in TURNSTILE_ALLOWED_HOSTNAMES
        if not allowed:
            record_security_event(
                "turnstile_failed",
                detail={"action": action, "reason": "hostname_mismatch", "hostname": response_hostname},
                alert_threshold=SECURITY_FORM_ALERT_THRESHOLD,
                alert_window=600,
            )
        return allowed
    return True


def client_ip() -> str:
    """Return the best client IP, preferring Cloudflare forwarding headers."""
    header_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if header_ip:
        return header_ip[:45]
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.remote_addr or "")[:45]


def ip_kind(value: str) -> str:
    """Classify an address string as 'ipv4', 'ipv6', or 'other'."""
    try:
        return "ipv6" if ipaddress.ip_address((value or "").strip()).version == 6 else "ipv4"
    except ValueError:
        return "other"


def is_public_ip(value: str) -> bool:
    """True only for globally routable (public / 對外) addresses.

    Loopback, private LAN, link-local and other internal ranges (127.0.0.1,
    192.168.*, 10.*, 172.16-31.*, ::1, fe80:: ...) all return False.
    """
    try:
        return ipaddress.ip_address((value or "").strip()).is_global
    except ValueError:
        return False


def ip_guard_get(ip: str):
    if not ip:
        return None
    return get_db().execute("SELECT * FROM ip_guard WHERE ip = ?", (ip,)).fetchone()


def ip_is_blocked(ip: str) -> bool:
    row = ip_guard_get(ip)
    if not row:
        return False
    return bool(row["manual_block"]) or row["blocked_until"] > int(time.time())


def record_ip_failure(ip: str) -> bool:
    """Record a failed login attempt and temporarily block noisy IPs."""
    if not ip or not is_public_ip(ip):
        return False
    record_security_event(
        "login_failed",
        detail={"source": "login"},
        ip=ip,
        alert_threshold=SECURITY_LOGIN_ALERT_THRESHOLD,
        alert_window=600,
    )
    db = get_db()
    now_ts = int(time.time())
    timestamp = now_iso()
    row = ip_guard_get(ip)
    if row is None:
        db.execute(
            """
            INSERT INTO ip_guard (ip, failed_attempts, blocked_until, manual_block, last_attempt_at, updated_at)
            VALUES (?, 1, 0, 0, ?, ?)
            """,
            (ip, timestamp, timestamp),
        )
        db.commit()
        return False
    failed = row["failed_attempts"] + 1
    blocked_until = row["blocked_until"]
    just_blocked = False
    if failed >= IP_MAX_FAILED:
        blocked_until = now_ts + IP_BLOCK_SECONDS
        failed = 0
        just_blocked = True
    db.execute(
        """
        UPDATE ip_guard
        SET failed_attempts = ?, blocked_until = ?, last_attempt_at = ?, updated_at = ?
        WHERE ip = ?
        """,
        (failed, blocked_until, timestamp, timestamp, ip),
    )
    db.commit()
    if just_blocked:
        log_audit("ip_auto_block", {"ip": ip}, actor_id=None)
        record_security_event(
            "ip_auto_block",
            detail={"blocked_minutes": IP_BLOCK_SECONDS // 60},
            ip=ip,
            alert_threshold=1,
            alert_window=600,
        )
    return just_blocked


def reset_ip_guard(ip: str) -> None:
    """Clear temporary login failures after a successful login."""
    if not ip:
        return
    db = get_db()
    db.execute(
        "UPDATE ip_guard SET failed_attempts = 0, blocked_until = 0, updated_at = ? WHERE ip = ? AND manual_block = 0",
        (now_iso(), ip),
    )
    db.commit()


def ip_guard_rows() -> list[dict]:
    rows = get_db().execute(
        "SELECT * FROM ip_guard ORDER BY manual_block DESC, blocked_until DESC, updated_at DESC"
    ).fetchall()
    now_ts = int(time.time())
    result = []
    for row in rows:
        item = dict(row)
        if item["manual_block"]:
            item["state"] = "manual"
        elif item["blocked_until"] > now_ts:
            item["state"] = "blocked"
        else:
            item["state"] = "normal"
        item["blocked_minutes_left"] = max(0, (item["blocked_until"] - now_ts + 59) // 60)
        item["kind"] = ip_kind(item["ip"])
        result.append(item)
    return result


def count_blocked_ips() -> int:
    now_ts = int(time.time())
    row = get_db().execute(
        "SELECT COUNT(*) AS c FROM ip_guard WHERE manual_block = 1 OR blocked_until > ?",
        (now_ts,),
    ).fetchone()
    return int(row["c"])


def auto_block_security_ip(ip: str, reason: str, seconds: int = IP_BLOCK_SECONDS) -> None:
    if not ip or not is_public_ip(ip):
        return
    db = get_db()
    now_ts = int(time.time())
    blocked_until = now_ts + seconds
    timestamp = now_iso()
    row = ip_guard_get(ip)
    if row and row["manual_block"]:
        return
    if row and row["blocked_until"] > now_ts:
        return
    if row:
        db.execute(
            """
            UPDATE ip_guard
            SET failed_attempts = 0, blocked_until = ?, last_attempt_at = ?, updated_at = ?
            WHERE ip = ?
            """,
            (blocked_until, timestamp, timestamp, ip),
        )
    else:
        db.execute(
            """
            INSERT INTO ip_guard (ip, failed_attempts, blocked_until, manual_block, last_attempt_at, updated_at)
            VALUES (?, 0, ?, 0, ?, ?)
            """,
            (ip, blocked_until, timestamp, timestamp),
        )
    db.commit()
    log_audit(
        "security_auto_block",
        {"ip": ip, "reason": reason, "blocked_minutes": seconds // 60},
        actor_id=None,
    )


def save_product_image(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("圖片格式只支援 PNG、JPG、JPEG 或 WEBP。")
    if file_storage.mimetype not in ALLOWED_MIMES:
        raise ValueError("圖片 MIME 類型不允許。")
    try:
        image = Image.open(file_storage.stream)
        image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("圖片內容無法解析。") from exc
    file_storage.stream.seek(0)
    filename = f"{uuid.uuid4().hex}.{extension}"
    path = UPLOAD_DIR / filename
    file_storage.save(path)
    return f"uploads/{filename}"


def product_form_payload(product_id: int | None = None) -> dict:
    data = request.get_json(silent=True) if request.is_json else request.form
    name = clean_text(data.get("name"), 80)
    slug_source = clean_text(data.get("slug") or name, 90, required=False)
    return {
        "slug": ensure_unique_slug(slugify(slug_source), product_id),
        "name": name,
        "category": clean_text(data.get("category"), 40),
        "description": clean_text(data.get("description"), 320),
        "price": parse_positive_int(data.get("price"), "價格"),
        "stock": parse_positive_int(data.get("stock"), "庫存"),
        "featured": 1 if str(data.get("featured", "")).lower() in {"1", "true", "on", "yes"} else 0,
        "benefits": split_lines(data.get("benefits")),
        "ingredients": split_lines(data.get("ingredients")),
        "tags": split_lines(data.get("tags")),
    }


def member_rows() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT
            id, username, role, display_name, full_name, birthday,
            phone, email, email_verified_at, is_active, created_at, updated_at
        FROM users
        WHERE username != ?
        ORDER BY role ASC, created_at DESC
        """,
        (DELETED_MEMBER_USERNAME,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.errorhandler(404)
def handle_not_found(error):
    if request.endpoint != "static":
        record_security_event(
            "not_found",
            detail={
                "query": request.query_string.decode("utf-8", errors="ignore")[:300],
                "endpoint": request.endpoint or "",
            },
            alert_threshold=SECURITY_404_ALERT_THRESHOLD,
            alert_window=600,
        )
    if wants_json_response():
        return jsonify({"error": "not_found"}), 404
    return render_template("404.html", active=""), 404


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "app": "WEB TEST"})


@app.route("/")
def home():
    content = load_site_content()
    products = get_products()
    featured = [product for product in products if product["featured"]][:4]
    return render_template(
        "home.html",
        active="home",
        site_content=content,
        featured_products=featured,
        latest_news=announcement_rows(published_only=True, limit=3),
    )


@app.route("/favicon.ico")
def favicon():
    logo = load_site_content().get("brand", {}).get("logo", DEFAULT_SITE_CONTENT["brand"]["logo"])
    return redirect(asset("images/" + logo))


@app.route("/shop")
def shop():
    products = get_products()
    categories = sorted({product["category"] for product in products})
    return render_template(
        "shop.html",
        active="shop",
        products=products,
        categories=categories,
    )


@app.route("/products/<slug>")
def product_detail(slug):
    product = get_product_by_slug(slug)
    if not product:
        abort(404)
    related = [
        item
        for item in get_products()
        if item["slug"] != product["slug"] and item["category"] == product["category"]
    ][:3]
    if len(related) < 3:
        related.extend(
            [
                item
                for item in get_products()
                if item["slug"] != product["slug"] and item not in related
            ][: 3 - len(related)]
        )
    return render_template(
        "product_detail.html",
        active="shop",
        product=product,
        related_products=related,
    )


@app.route("/reservation", methods=["GET", "POST"])
def reservation():
    if request.method == "POST":
        if not verify_turnstile("reservation"):
            flash("請完成安全驗證後再送出。", "error")
            return redirect(url_for("reservation"))
        if submission_rate_limited("reservation", client_ip()):
            flash("送出次數太多，請稍後再試。", "error")
            return redirect(url_for("reservation"))
        try:
            create_reservation(request.form)
            log_audit("reservation_create", {"name": request.form.get("name")}, actor_id=None)
            flash("訂位資料已送出，我們會盡快回覆確認。", "success")
            return redirect(url_for("reservation"))
        except ValueError as exc:
            flash(str(exc), "error")
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("reservation.html", active="reservation", today=today)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        if not verify_turnstile("contact"):
            flash("請完成安全驗證後再送出。", "error")
            return redirect(url_for("contact"))
        if submission_rate_limited("contact", client_ip()):
            flash("送出次數太多，請稍後再試。", "error")
            return redirect(url_for("contact"))
        try:
            create_message(request.form)
            flash("訊息已送出，我們會盡快回覆。", "success")
            return redirect(url_for("contact"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("contact.html", active="contact")


@app.route("/news")
def news():
    return render_template(
        "news.html",
        active="news",
        announcements=announcement_rows(published_only=True),
    )


@app.route("/news/<int:announcement_id>")
def news_detail(announcement_id):
    row = get_announcement(announcement_id)
    if not row or not row["published"]:
        abort(404)
    others = [
        item
        for item in announcement_rows(published_only=True)
        if item["id"] != announcement_id
    ][:5]
    return render_template(
        "news_detail.html",
        active="news",
        item=dict(row),
        others=others,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("shop"))
    if request.method == "POST":
        if not verify_turnstile("register"):
            flash("請完成安全驗證後再送出。", "error")
            return render_template("register.html", active="register")
        if submission_rate_limited("register", client_ip()):
            flash("送出次數太多，請稍後再試。", "error")
            return render_template("register.html", active="register"), 429
        try:
            full_name = clean_text(request.form.get("full_name"), 60)
            birthday = normalize_birthday(request.form.get("birthday"))
            email = normalize_email(request.form.get("email"))
            username = clean_text(request.form.get("username"), 60).lower()
            password = request.form.get("password") or ""
            validate_password(password, request.form.get("password_confirm") or "")
            duplicate = find_duplicate_user(username, email)
            if duplicate:
                raise ValueError(duplicate_message(duplicate, username, email))
            timestamp = now_iso()
            cursor = get_db().execute(
                """
                INSERT INTO users (
                    username, password_hash, role, display_name, full_name,
                    birthday, phone, email, email_verified_at, is_active, created_at, updated_at
                )
                VALUES (?, ?, 'user', ?, ?, ?, ?, ?, '', 1, ?, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    full_name,
                    full_name,
                    birthday,
                    "",
                    email,
                    timestamp,
                    timestamp,
                ),
            )
            get_db().commit()
            row = user_by_id(cursor.lastrowid)
            verify_token = create_email_verification(row, request.remote_addr or "")
            try:
                sent = send_email_verification(row, verify_token)
            except OSError:
                sent = False
            if sent:
                flash("\u8a3b\u518a\u6210\u529f\uff0c\u8acb\u5230\u4fe1\u7bb1\u6536\u53d6\u9a57\u8b49\u4fe1\u5b8c\u6210 Email \u8a8d\u8b49\u3002", "success")
            else:
                flash("\u8a3b\u518a\u6210\u529f\uff0c\u4f46\u9a57\u8b49\u4fe1\u76ee\u524d\u7121\u6cd5\u5bc4\u51fa\uff0c\u8acb\u6aa2\u67e5 SMTP \u8a2d\u5b9a\u5f8c\u518d\u7531\u5f8c\u53f0\u88dc\u767c\u3002", "warning")
            return redirect(url_for("verify_email_sent", email=email))
        except sqlite3.IntegrityError:
            flash("\u5e33\u865f\u6216\u96fb\u5b50\u90f5\u4ef6\u5df2\u88ab\u8a3b\u518a\u3002", "error")
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("register.html", active="register")


@app.route("/verify-email-sent")
def verify_email_sent():
    return render_template(
        "verify_email_sent.html",
        active="login",
        email=clean_text(request.args.get("email"), 120, required=False),
    )


def email_verification_row(token: str):
    return get_db().execute(
        """
        SELECT ev.*, u.email, u.full_name, u.display_name
        FROM email_verifications ev
        JOIN users u ON u.id = ev.user_id
        WHERE ev.token_hash = ? AND ev.used_at IS NULL AND ev.expires_at >= ?
        """,
        (hash_reset_secret(token), int(time.time())),
    ).fetchone()


@app.route("/verify-email/<token>")
def verify_email(token):
    row = email_verification_row(token)
    if not row:
        flash("驗證連結無效或已過期，請重新寄送驗證信。", "error")
        return redirect(url_for("resend_verification"))
    timestamp = now_iso()
    get_db().execute(
        "UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?",
        (timestamp, timestamp, row["user_id"]),
    )
    get_db().execute(
        "UPDATE email_verifications SET used_at = ? WHERE id = ?",
        (timestamp, row["id"]),
    )
    get_db().commit()
    flash("Email 驗證完成，現在可以登入。", "success")
    return redirect(url_for("login"))


@app.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    if request.method == "POST":
        email = normalize_email(request.form.get("email"), required=False)
        row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row and row["is_active"] and not row["email_verified_at"]:
            token = create_email_verification(row, request.remote_addr or "")
            try:
                send_email_verification(row, token)
            except OSError:
                log_audit("email_verification_send_failed", {"user": row["id"]}, actor_id=None)
        flash("如果此信箱需要驗證，我們已重新寄出驗證信。", "success")
        return redirect(url_for("resend_verification"))
    return render_template("resend_verification.html", active="login")


@app.route("/login", methods=["GET", "POST"])
def login():
    user = current_user()
    if request.method == "GET" and user:
        return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "shop"))
    if request.method == "POST":
        if not verify_turnstile("login"):
            flash("請完成安全驗證後再登入。", "error")
            return render_template("login.html", active="login"), 400
        ip = client_ip()
        if ip_is_blocked(ip):
            flash(f"此 IP 因多次登入失敗已暫時封鎖，請 {IP_BLOCK_SECONDS // 60} 分鐘後再試。", "error")
            return render_template("login.html", active="login"), 429
        username = clean_text(request.form.get("username"), 60, required=False).lower()
        password = request.form.get("password") or ""
        row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        now_ts = int(time.time())
        if row and row["locked_until"] > now_ts:
            flash("登入失敗次數過多，請稍後再試。", "error")
            return render_template("login.html", active="login"), 429
        if row and check_password_hash(row["password_hash"], password):
            if not row["is_active"]:
                flash("此帳號已停用，請聯絡客服。", "error")
                return render_template("login.html", active="login"), 403
            if row["role"] == "user" and not row["email_verified_at"]:
                flash("請先完成 Email 驗證後再登入。", "error")
                return render_template("login.html", active="login", unverified_email=row["email"]), 403
            get_db().execute(
                "UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?",
                (row["id"],),
            )
            get_db().commit()
            reset_ip_guard(ip)
            session.clear()
            session["user_id"] = row["id"]
            session["role"] = row["role"]
            csrf_token()
            if row["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            next_url = request.args.get("next")
            return redirect(next_url if next_url and next_url.startswith("/") else url_for("shop"))
        if row:
            failed = row["failed_attempts"] + 1
            locked_until = now_ts + LOGIN_LOCK_SECONDS if failed >= LOGIN_MAX_FAILED else 0
            get_db().execute(
                """
                UPDATE users
                SET failed_attempts = ?, locked_until = ?
                WHERE id = ?
                """,
                (failed, locked_until, row["id"]),
            )
            get_db().commit()
        if record_ip_failure(ip):
            flash(f"此 IP 登入失敗已達 {IP_MAX_FAILED} 次，已暫時封鎖 {IP_BLOCK_SECONDS // 60} 分鐘。", "error")
            return render_template("login.html", active="login"), 429
        flash("帳號或密碼錯誤，請再試一次。", "error")
    return render_template("login.html", active="login")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        if not verify_turnstile("forgot_password"):
            flash("請完成安全驗證後再送出。", "error")
            return redirect(url_for("forgot_password"))
        if submission_rate_limited("forgot_password", client_ip()):
            flash("送出次數太多，請稍後再試。", "error")
            return redirect(url_for("forgot_password"))
        email = normalize_email(request.form.get("email"), required=False)
        row = find_user_by_contact(email)
        if row and row["is_active"] and row["email"]:
            token, code = create_password_reset(row, request.remote_addr or "")
            try:
                send_password_reset_email(row, token, code)
            except OSError:
                log_audit("password_reset_email_failed", {"user": row["id"]}, actor_id=None)
        flash("若資料符合，我們已寄出密碼重設信。", "success")
        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html", active="login")


def reset_row_by_token(token: str):
    return get_db().execute(
        """
        SELECT pr.*, u.email, u.full_name, u.display_name
        FROM password_resets pr
        JOIN users u ON u.id = pr.user_id
        WHERE pr.token_hash = ? AND pr.used_at IS NULL AND pr.expires_at >= ?
        """,
        (hash_reset_secret(token), int(time.time())),
    ).fetchone()


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_token(token):
    row = reset_row_by_token(token)
    if not row:
        flash("重設連結無效或已過期。", "error")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        try:
            password = request.form.get("password") or ""
            validate_password(password, request.form.get("password_confirm") or "")
            set_user_password(row["user_id"], password)
            get_db().execute(
                "UPDATE password_resets SET used_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
            get_db().commit()
            flash("密碼已重設，請使用新密碼登入。", "success")
            return redirect(url_for("login"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("reset_password.html", active="login", token=token, mode="token")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password_code():
    if request.method == "POST":
        try:
            email = normalize_email(request.form.get("email"))
            code = clean_text(request.form.get("code"), 6)
            password = request.form.get("password") or ""
            validate_password(password, request.form.get("password_confirm") or "")
            user_row = find_user_by_contact(email)
            if not user_row:
                raise ValueError("驗證碼錯誤或已過期。")
            row = get_db().execute(
                """
                SELECT *
                FROM password_resets
                WHERE user_id = ? AND code_hash = ? AND used_at IS NULL AND expires_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_row["id"], hash_reset_secret(code), int(time.time())),
            ).fetchone()
            if not row:
                raise ValueError("驗證碼錯誤或已過期。")
            set_user_password(user_row["id"], password)
            get_db().execute(
                "UPDATE password_resets SET used_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
            get_db().commit()
            flash("密碼已重設，請使用新密碼登入。", "success")
            return redirect(url_for("login"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("reset_password.html", active="login", mode="code")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
@login_required("user")
def profile():
    user = user_by_id(current_user()["id"])
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "profile":
                full_name = clean_text(request.form.get("full_name"), 60)
                birthday = normalize_birthday(request.form.get("birthday"))
                email = normalize_email(request.form.get("email"))
                duplicate = find_duplicate_user(user["username"], email, exclude_id=user["id"])
                if duplicate:
                    raise ValueError(duplicate_message(duplicate, user["username"], email))
                email_changed = email != user["email"]
                verified_at = user["email_verified_at"] if not email_changed else ""
                get_db().execute(
                    """
                    UPDATE users
                    SET display_name = ?, full_name = ?, birthday = ?,
                        email = ?, email_verified_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (full_name, full_name, birthday, email, verified_at, now_iso(), user["id"]),
                )
                get_db().commit()
                if email_changed:
                    updated = user_by_id(user["id"])
                    token = create_email_verification(updated, request.remote_addr or "")
                    try:
                        send_email_verification(updated, token)
                    except OSError:
                        log_audit("email_verification_send_failed", {"user": user["id"]}, actor_id=None)
                    session.clear()
                    flash("個人資料已更新，請到新信箱完成 Email 驗證。", "success")
                    return redirect(url_for("verify_email_sent", email=email))
                flash("個人資料已更新。", "success")
            elif action == "password":
                current_password = request.form.get("current_password") or ""
                if not check_password_hash(user["password_hash"], current_password):
                    raise ValueError("目前密碼不正確。")
                password = request.form.get("password") or ""
                validate_password(password, request.form.get("password_confirm") or "")
                set_user_password(user["id"], password)
                get_db().commit()
                flash("密碼已更新。", "success")
            else:
                raise ValueError("操作不正確。")
            return redirect(url_for("profile"))
        except sqlite3.IntegrityError:
            flash("此電子郵件已被使用。", "error")
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("profile.html", active="profile", member=user)


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    products = get_products(include_inactive=True)
    reservations = reservation_rows()
    messages = message_rows()
    today = datetime.now().strftime("%Y-%m-%d")
    stats = {
        "products": len([product for product in products if product["active"]]),
        "reservations_pending": len(
            [r for r in reservations if r["status"] in {"new", "confirmed"}]
        ),
        "reservations_today": len(
            [r for r in reservations if r["reserved_date"] == today and r["status"] != "cancelled"]
        ),
        "messages_unread": len([m for m in messages if m["status"] == "unread"]),
        "low_stock": len(
            [product for product in products if product["active"] and product["stock"] <= 8]
        ),
        "members": len([member for member in member_rows() if member["role"] == "user"]),
        "blocked_ips": count_blocked_ips(),
        "announcements": len(announcement_rows()),
    }
    upcoming_reservations = [
        r for r in reservations if r["status"] in {"new", "confirmed"}
    ][:5]
    recent_messages = messages[:5]
    low_stock = [
        product for product in products if product["active"] and product["stock"] <= 8
    ][:6]
    return render_template(
        "admin.html",
        active="admin",
        stats=stats,
        upcoming_reservations=upcoming_reservations,
        recent_messages=recent_messages,
        low_stock=low_stock,
    )


@app.route("/admin/members")
@login_required("admin")
def admin_members():
    return render_template(
        "admin_members.html",
        active="admin-members",
        members=member_rows(),
    )


@app.route("/admin/members/<int:member_id>/update", methods=["POST"])
@login_required("admin")
def admin_member_update(member_id):
    row = user_by_id(member_id)
    if not row:
        abort(404)
    try:
        full_name = clean_text(request.form.get("full_name"), 60)
        birthday = normalize_birthday(request.form.get("birthday"))
        email = normalize_email(request.form.get("email"))
        is_active = 1 if request.form.get("is_active") == "1" else 0
        duplicate = find_duplicate_user(row["username"], email, exclude_id=member_id)
        if duplicate:
            raise ValueError(duplicate_message(duplicate, row["username"], email))
        email_changed = email != row["email"]
        verified_at = row["email_verified_at"] if not email_changed else ""
        if member_id == current_user()["id"] and not is_active:
            raise ValueError("不能停用自己的管理員帳號。")
        get_db().execute(
            """
            UPDATE users
            SET display_name = ?, full_name = ?, birthday = ?,
                email = ?, email_verified_at = ?, is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (full_name, full_name, birthday, email, verified_at, is_active, now_iso(), member_id),
        )
        get_db().commit()
        if email_changed and row["role"] == "user" and is_active:
            updated = user_by_id(member_id)
            token = create_email_verification(updated, request.remote_addr or "")
            try:
                send_email_verification(updated, token)
            except OSError:
                log_audit("email_verification_send_failed", {"user": member_id}, actor_id=None)
        log_audit(
            "member_update",
            {"id": member_id, "username": row["username"], "is_active": is_active},
        )
        flash("會員資料已更新。", "success")
    except sqlite3.IntegrityError:
        flash("此電子郵件已被使用。", "error")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:member_id>/send-reset", methods=["POST"])
@login_required("admin")
def admin_member_send_reset(member_id):
    row = user_by_id(member_id)
    if not row:
        abort(404)
    if not row["email"]:
        flash("這位會員沒有電子郵件，無法寄送重設密碼信。", "error")
        return redirect(url_for("admin_members"))
    token, code = create_password_reset(row, request.remote_addr or "")
    try:
        sent = send_password_reset_email(row, token, code)
    except OSError:
        sent = False
    log_audit("member_password_reset", {"id": member_id, "sent": sent})
    if sent:
        flash("已寄出密碼重設信。", "success")
    else:
        flash("SMTP 尚未成功寄出，請檢查郵件設定後再重試。", "warning")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:member_id>/send-mail", methods=["POST"])
@login_required("admin")
def admin_member_send_mail(member_id):
    row = user_by_id(member_id)
    if not row or row["username"] == DELETED_MEMBER_USERNAME:
        abort(404)
    if not row["email"]:
        flash("這位會員沒有電子郵件，無法寄信。", "error")
        return redirect(url_for("admin_members"))
    try:
        subject = clean_text(request.form.get("subject"), 120)
        body = clean_text(request.form.get("body"), 3000)
        try:
            sent = send_member_notice_email(row, subject, body)
        except OSError:
            sent = False
        log_audit(
            "member_notice_email",
            {"id": member_id, "subject": subject, "sent": sent},
        )
        if sent:
            flash("已寄出會員通知信。", "success")
        else:
            flash("SMTP 尚未成功寄出，請檢查郵件設定後再重試。", "warning")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/send-bulk-mail", methods=["POST"])
@login_required("admin")
def admin_members_send_bulk_mail():
    try:
        subject = clean_text(request.form.get("subject"), 120)
        body = clean_text(request.form.get("body"), 3000)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_members"))

    rows = get_db().execute(
        """
        SELECT *
        FROM users
        WHERE role = 'user'
          AND is_active = 1
          AND email != ''
          AND username != ?
        ORDER BY created_at DESC
        """,
        (DELETED_MEMBER_USERNAME,),
    ).fetchall()
    sent_count = 0
    failed_count = 0
    for row in rows:
        try:
            sent = send_member_notice_email(row, subject, body)
        except OSError:
            sent = False
        if sent:
            sent_count += 1
        else:
            failed_count += 1
    log_audit(
        "member_bulk_notice_email",
        {"subject": subject, "sent": sent_count, "failed": failed_count},
    )
    if failed_count:
        flash(f"已寄出 {sent_count} 封，{failed_count} 封寄送失敗，請檢查 SMTP 設定。", "warning")
    else:
        flash(f"已寄出 {sent_count} 封會員通知信。", "success")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:member_id>/delete", methods=["POST"])
@login_required("admin")
def admin_member_delete(member_id):
    row = user_by_id(member_id)
    if not row or row["username"] == DELETED_MEMBER_USERNAME:
        abort(404)
    if member_id == current_user()["id"]:
        flash("不能刪除自己的管理員帳號。", "error")
        return redirect(url_for("admin_members"))
    if row["role"] == "admin":
        flash("不能在會員管理刪除管理員帳號。", "error")
        return redirect(url_for("admin_members"))

    db = get_db()
    deleted_member_id = ensure_deleted_member_account(db)
    timestamp = now_iso()
    db.execute(
        """
        UPDATE orders
        SET user_id = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (deleted_member_id, timestamp, member_id),
    )
    db.execute("DELETE FROM cart_items WHERE user_id = ?", (member_id,))
    db.execute("DELETE FROM password_resets WHERE user_id = ?", (member_id,))
    db.execute("DELETE FROM email_verifications WHERE user_id = ?", (member_id,))
    db.execute("DELETE FROM users WHERE id = ?", (member_id,))
    db.commit()
    log_audit(
        "member_delete",
        {"id": member_id, "username": row["username"], "email": row["email"]},
    )
    flash("會員帳號已刪除，歷史訂單已保留。", "success")
    return redirect(url_for("admin_members"))


@app.route("/admin/products", methods=["GET", "POST"])
@login_required("admin")
def admin_products():
    if request.method == "POST":
        try:
            payload = product_form_payload()
            image = save_product_image(request.files.get("image"))
            created_at = now_iso()
            get_db().execute(
                """
                INSERT INTO products (
                    slug, name, category, description, price, image, gallery_json,
                    benefits_json, ingredients_json, tags_json, stock, featured,
                    active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    payload["slug"],
                    payload["name"],
                    payload["category"],
                    payload["description"],
                    payload["price"],
                    image or "",
                    encode_json([image] if image else []),
                    encode_json(payload["benefits"]),
                    encode_json(payload["ingredients"]),
                    encode_json(payload["tags"]),
                    payload["stock"],
                    payload["featured"],
                    created_at,
                    created_at,
                ),
            )
            get_db().commit()
            log_audit("product_create", {"name": payload["name"]})
            flash("菜單品項已新增。", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin_products"))
    products = get_admin_menu_products()
    categories = sorted({product["category"] for product in products})
    return render_template(
        "admin_products.html",
        active="admin-products",
        products=products,
        categories=categories,
    )


@app.route("/admin/products/<int:product_id>/update", methods=["POST"])
@login_required("admin")
def admin_product_update(product_id):
    row = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        abort(404)
    try:
        payload = product_form_payload(product_id)
        image = save_product_image(request.files.get("image")) or row["image"]
        get_db().execute(
            """
            UPDATE products
            SET slug = ?, name = ?, category = ?, description = ?, price = ?,
                image = ?, gallery_json = ?, benefits_json = ?, ingredients_json = ?,
                tags_json = ?, stock = ?, featured = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload["slug"], payload["name"], payload["category"], payload["description"],
                payload["price"], image, encode_json([image] if image else []),
                encode_json(payload["benefits"]), encode_json(payload["ingredients"]),
                encode_json(payload["tags"]), payload["stock"], payload["featured"],
                now_iso(), product_id,
            ),
        )
        get_db().commit()
        log_audit("product_update", {"id": product_id, "name": payload["name"]})
        flash("菜單品項已更新。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@login_required("admin")
def admin_product_delete(product_id):
    get_db().execute(
        "UPDATE products SET active = 0, updated_at = ? WHERE id = ?",
        (now_iso(), product_id),
    )
    get_db().commit()
    log_audit("product_delete", {"id": product_id})
    flash("菜單品項已下架。", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/restore", methods=["POST"])
@login_required("admin")
def admin_product_restore(product_id):
    row = get_db().execute("SELECT id, name FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        abort(404)
    get_db().execute(
        "UPDATE products SET active = 1, updated_at = ? WHERE id = ?",
        (now_iso(), product_id),
    )
    get_db().commit()
    log_audit("product_restore", {"id": product_id, "name": row["name"]})
    flash("菜單品項已重新上架。", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/reservations")
@login_required("admin")
def admin_reservations():
    status_filter = request.args.get("status", "")
    if status_filter not in RESERVATION_STATUSES:
        status_filter = ""
    return render_template(
        "admin_reservations.html",
        active="admin-reservations",
        reservations=reservation_rows(status_filter or None),
        statuses=RESERVATION_STATUSES,
        status_filter=status_filter,
    )


@app.route("/admin/reservations/<int:reservation_id>/status", methods=["POST"])
@login_required("admin")
def admin_reservation_status(reservation_id):
    status = request.form.get("status")
    if status not in RESERVATION_STATUSES:
        flash("訂位狀態不正確。", "error")
        return redirect(url_for("admin_reservations"))
    get_db().execute(
        "UPDATE reservations SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), reservation_id),
    )
    get_db().commit()
    log_audit("reservation_status_update", {"id": reservation_id, "status": status})
    flash("訂位狀態已更新。", "success")
    return redirect(url_for("admin_reservations"))


@app.route("/admin/reservations/<int:reservation_id>/delete", methods=["POST"])
@login_required("admin")
def admin_reservation_delete(reservation_id):
    get_db().execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
    get_db().commit()
    log_audit("reservation_delete", {"id": reservation_id})
    flash("訂位資料已刪除。", "success")
    return redirect(url_for("admin_reservations"))


@app.route("/admin/messages")
@login_required("admin")
def admin_messages():
    status_filter = request.args.get("status", "")
    if status_filter not in MESSAGE_STATUSES:
        status_filter = ""
    return render_template(
        "admin_messages.html",
        active="admin-messages",
        messages=message_rows(status_filter or None),
        statuses=MESSAGE_STATUSES,
        status_filter=status_filter,
    )


@app.route("/admin/messages/<int:message_id>/status", methods=["POST"])
@login_required("admin")
def admin_message_status(message_id):
    status = request.form.get("status")
    if status not in MESSAGE_STATUSES:
        flash("留言狀態不正確。", "error")
        return redirect(url_for("admin_messages"))
    get_db().execute(
        "UPDATE messages SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), message_id),
    )
    get_db().commit()
    log_audit("message_status_update", {"id": message_id, "status": status})
    flash("留言狀態已更新。", "success")
    return redirect(url_for("admin_messages"))


@app.route("/admin/messages/<int:message_id>/delete", methods=["POST"])
@login_required("admin")
def admin_message_delete(message_id):
    get_db().execute("DELETE FROM messages WHERE id = ?", (message_id,))
    get_db().commit()
    log_audit("message_delete", {"id": message_id})
    flash("留言已刪除。", "success")
    return redirect(url_for("admin_messages"))


@app.route("/admin/announcements", methods=["GET", "POST"])
@login_required("admin")
def admin_announcements():
    if request.method == "POST":
        try:
            payload = announcement_form_payload()
            timestamp = now_iso()
            get_db().execute(
                """
                INSERT INTO announcements (title, body, pinned, published, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (payload["title"], payload["body"], payload["pinned"], payload["published"], timestamp, timestamp),
            )
            get_db().commit()
            log_audit("announcement_create", {"title": payload["title"]})
            flash("公告已新增。", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin_announcements"))
    return render_template(
        "admin_announcements.html",
        active="admin-announcements",
        announcements=announcement_rows(),
    )


@app.route("/admin/announcements/<int:announcement_id>/update", methods=["POST"])
@login_required("admin")
def admin_announcement_update(announcement_id):
    if not get_announcement(announcement_id):
        abort(404)
    try:
        payload = announcement_form_payload()
        get_db().execute(
            """
            UPDATE announcements
            SET title = ?, body = ?, pinned = ?, published = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload["title"], payload["body"], payload["pinned"], payload["published"], now_iso(), announcement_id),
        )
        get_db().commit()
        log_audit("announcement_update", {"id": announcement_id})
        flash("公告已更新。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:announcement_id>/delete", methods=["POST"])
@login_required("admin")
def admin_announcement_delete(announcement_id):
    get_db().execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    get_db().commit()
    log_audit("announcement_delete", {"id": announcement_id})
    flash("公告已刪除。", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/security")
@login_required("admin")
def admin_security():
    return render_template(
        "admin_security.html",
        active="admin-security",
        ip_rows=ip_guard_rows(),
        security_events=security_event_rows(),
        security_summary=security_event_summary(),
        cloudflare_status=cloudflare_config_status(),
        max_failed=IP_MAX_FAILED,
        block_minutes=IP_BLOCK_SECONDS // 60,
        my_ip=client_ip(),
        my_ip_kind=ip_kind(client_ip()),
        my_ip_public=is_public_ip(client_ip()),
    )


@app.route("/admin/security/block", methods=["POST"])
@login_required("admin")
def admin_ip_block():
    ip = clean_text(request.form.get("ip"), 45, required=False)
    if not ip or not IP_RULE.match(ip):
        flash("IP 格式不正確。", "error")
        return redirect(url_for("admin_security"))
    db = get_db()
    timestamp = now_iso()
    if ip_guard_get(ip):
        db.execute(
            "UPDATE ip_guard SET manual_block = 1, updated_at = ? WHERE ip = ?",
            (timestamp, ip),
        )
    else:
        db.execute(
            """
            INSERT INTO ip_guard (ip, failed_attempts, blocked_until, manual_block, last_attempt_at, updated_at)
            VALUES (?, 0, 0, 1, ?, ?)
            """,
            (ip, timestamp, timestamp),
        )
    db.commit()
    log_audit("ip_manual_block", {"ip": ip})
    flash(f"已封鎖 IP {ip}。", "success")
    return redirect(url_for("admin_security"))


@app.route("/admin/security/unblock", methods=["POST"])
@login_required("admin")
def admin_ip_unblock():
    ip = clean_text(request.form.get("ip"), 45, required=False)
    get_db().execute(
        """
        UPDATE ip_guard
        SET manual_block = 0, blocked_until = 0, failed_attempts = 0, updated_at = ?
        WHERE ip = ?
        """,
        (now_iso(), ip),
    )
    get_db().commit()
    log_audit("ip_unblock", {"ip": ip})
    flash(f"已解除 IP {ip} 封鎖。", "success")
    return redirect(url_for("admin_security"))


@app.route("/admin/security/<path:ip>/delete", methods=["POST"])
@login_required("admin")
def admin_ip_delete(ip):
    get_db().execute("DELETE FROM ip_guard WHERE ip = ?", (ip,))
    get_db().commit()
    log_audit("ip_record_delete", {"ip": ip})
    flash(f"已刪除 IP {ip} 紀錄。", "success")
    return redirect(url_for("admin_security"))


@app.route("/api/products")
def api_products():
    return jsonify({"products": get_products()})


@app.route("/api/admin/content", methods=["POST"])
@login_required("admin")
def api_admin_content():
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip()
    value = payload.get("value", "")
    if not TEXT_KEY_RULE.match(key):
        return jsonify({"error": "key 格式不正確"}), 400
    if not isinstance(value, str) or len(value) > 5000:
        return jsonify({"error": "內容長度不正確"}), 400
    overrides = load_text_overrides()
    if key not in overrides and len(overrides) >= 1000:
        return jsonify({"error": "可編輯文字數量已達上限"}), 400
    value = value.strip()
    if value:
        overrides[key] = value
    else:
        overrides.pop(key, None)
    save_text_overrides(overrides)
    log_audit("content_edit", {"key": key})
    return jsonify({"ok": True})


@app.route("/api/admin/products", methods=["GET", "POST"])
@login_required("admin")
def api_admin_products():
    if request.method == "GET":
        return jsonify({"products": get_admin_menu_products()})
    try:
        payload = product_form_payload()
        image = None
        created_at = now_iso()
        cursor = get_db().execute(
            """
            INSERT INTO products (
                slug, name, category, description, price, image, gallery_json,
                benefits_json, ingredients_json, tags_json, stock, featured,
                active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                payload["slug"],
                payload["name"],
                payload["category"],
                payload["description"],
                payload["price"],
                image or "",
                encode_json(payload["benefits"]),
                encode_json(payload["ingredients"]),
                encode_json(payload["tags"]),
                payload["stock"],
                payload["featured"],
                created_at,
                created_at,
            ),
        )
        get_db().commit()
        log_audit("api_product_create", {"id": cursor.lastrowid})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "id": cursor.lastrowid}), 201


@app.route("/api/admin/products/<int:product_id>", methods=["PUT", "DELETE"])
@login_required("admin")
def api_admin_product_item(product_id):
    if request.method == "DELETE":
        get_db().execute(
            "UPDATE products SET active = 0, updated_at = ? WHERE id = ?",
            (now_iso(), product_id),
        )
        get_db().commit()
        log_audit("api_product_delete", {"id": product_id})
        return jsonify({"ok": True})
    row = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    try:
        payload = product_form_payload(product_id)
        get_db().execute(
            """
            UPDATE products
            SET slug = ?, name = ?, category = ?, description = ?, price = ?,
                benefits_json = ?, ingredients_json = ?, tags_json = ?, stock = ?,
                featured = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload["slug"],
                payload["name"],
                payload["category"],
                payload["description"],
                payload["price"],
                encode_json(payload["benefits"]),
                encode_json(payload["ingredients"]),
                encode_json(payload["tags"]),
                payload["stock"],
                payload["featured"],
                now_iso(),
                product_id,
            ),
        )
        get_db().commit()
        log_audit("api_product_update", {"id": product_id})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@app.route("/api/admin/reservations")
@login_required("admin")
def api_admin_reservations():
    return jsonify({"reservations": reservation_rows()})


@app.route("/api/admin/messages")
@login_required("admin")
def api_admin_messages():
    return jsonify({"messages": message_rows()})


init_db()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
        use_reloader=False,
    )
