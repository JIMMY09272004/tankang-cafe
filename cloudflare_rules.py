"""Create or update Cloudflare WAF, hotlink and cache rules for this site.

Usage:
    python cloudflare_rules.py --dry-run
    python cloudflare_rules.py --apply

The script reads .env:
    CLOUDFLARE_API_TOKEN
    CLOUDFLARE_ZONE_ID
    CLOUDFLARE_HOSTNAME=example.com

It preserves rules not managed by this project and replaces rules with refs that
start with "mellowday_".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
API_BASE = "https://api.cloudflare.com/client/v4"
MANAGED_REFS = {
    "mellowday_block_scanners",
    "mellowday_challenge_admin",
    "mellowday_challenge_suspicious",
    "mellowday_hotlink_images",
    "mellowday_cache_static",
    "mellowday_cache_bypass_sensitive",
}


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cf_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = {"success": False, "errors": [{"message": body_text}]}
        body["status"] = exc.code
        return body
    return body


def require_config() -> tuple[str, str, str]:
    load_dotenv()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "").strip()
    hostname = os.environ.get("CLOUDFLARE_HOSTNAME", "example.com").strip() or "example.com"
    missing = [
        name
        for name, value in {
            "CLOUDFLARE_API_TOKEN": token,
            "CLOUDFLARE_ZONE_ID": zone_id,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(
            "[ERROR] Missing Cloudflare config in .env: "
            + ", ".join(missing)
            + "\nAdd these values first, then run: python cloudflare_rules.py --apply"
        )
    return token, zone_id, hostname


def image_extension_expression() -> str:
    extensions = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".avif")
    return "(" + " or ".join(
        f'ends_with(lower(http.request.uri.path), "{extension}")'
        for extension in extensions
    ) + ")"


def waf_rules(hostname: str) -> list[dict[str, Any]]:
    host = hostname.replace('"', "")
    image_ext = image_extension_expression()
    secret_paths = (
        'http.request.uri.path in {'
        '"/.env.bak" "/.env.backup" "/.env.development" "/.env.local" "/.env.production" '
        '"/account.json" "/api/config" "/api/env" "/appsettings.json" "/credentials.json" '
        '"/firebase-adminsdk.json" "/google-credentials.json" "/key.json" "/keyfile.json" '
        '"/secrets.json" "/service-account.json" "/actuator/env"'
        '}'
    )
    return [
        {
            "ref": "mellowday_block_scanners",
            "description": "Mellow Day - block common scanner paths",
            "expression": (
                f'(http.host eq "{host}" and ('
                'http.request.uri.path eq "/.env" or '
                f'{secret_paths} or '
                'starts_with(http.request.uri.path, "/.git") or '
                'starts_with(http.request.uri.path, "/wp-admin") or '
                'http.request.uri.path eq "/wp-login.php" or '
                'starts_with(http.request.uri.path, "/phpmyadmin") or '
                'starts_with(http.request.uri.path, "/vendor/phpunit")'
                "))"
            ),
            "action": "block",
            "enabled": True,
        },
        {
            "ref": "mellowday_challenge_admin",
            "description": "Mellow Day - challenge admin surfaces",
            "expression": (
                f'(http.host eq "{host}" and ('
                'starts_with(http.request.uri.path, "/admin") or '
                'starts_with(http.request.uri.path, "/api/admin")'
                "))"
            ),
            "action": "managed_challenge",
            "enabled": True,
        },
        {
            "ref": "mellowday_challenge_suspicious",
            "description": "Mellow Day - challenge suspicious clients and query strings",
            "expression": (
                f'(http.host eq "{host}" and ('
                'http.user_agent eq "" or '
                'lower(http.user_agent) contains "sqlmap" or '
                'lower(http.user_agent) contains "nikto" or '
                'lower(http.user_agent) contains "acunetix" or '
                'lower(http.user_agent) contains "masscan" or '
                'http.request.uri.query contains "../" or '
                'lower(http.request.uri.query) contains "<script"'
                "))"
            ),
            "action": "managed_challenge",
            "enabled": True,
        },
        {
            "ref": "mellowday_hotlink_images",
            "description": "Mellow Day - block image hotlinking with foreign referer",
            "expression": (
                f'(http.host eq "{host}" and http.referer ne "" and '
                f'not starts_with(http.referer, "https://{host}/") and '
                f'not starts_with(http.referer, "http://{host}/") and '
                f'http.referer ne "https://{host}" and '
                f'http.referer ne "http://{host}" and {image_ext})'
            ),
            "action": "block",
            "enabled": True,
        },
    ]


def cache_rules(hostname: str) -> list[dict[str, Any]]:
    host = hostname.replace('"', "")
    sensitive_paths = (
        'starts_with(http.request.uri.path, "/admin") or '
        'starts_with(http.request.uri.path, "/api/") or '
        'http.request.uri.path in {"/login" "/register" "/cart" "/checkout" '
        '"/profile" "/forgot-password" "/reset-password" "/verify-email-sent" '
        '"/resend-verification"} or '
        'starts_with(http.request.uri.path, "/reset-password/") or '
        'starts_with(http.request.uri.path, "/verify-email/")'
    )
    return [
        {
            "ref": "mellowday_cache_bypass_sensitive",
            "description": "Mellow Day - bypass cache for private and dynamic pages",
            "expression": f'(http.host eq "{host}" and ({sensitive_paths}))',
            "action": "set_cache_settings",
            "action_parameters": {"cache": False},
            "enabled": True,
        },
        {
            "ref": "mellowday_cache_static",
            "description": "Mellow Day - cache static assets",
            "expression": f'(http.host eq "{host}" and starts_with(http.request.uri.path, "/static/"))',
            "action": "set_cache_settings",
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 86400},
                "browser_ttl": {"mode": "override_origin", "default": 3600},
            },
            "enabled": True,
        },
    ]


def phase_payload(phase: str, rules: list[dict[str, Any]], existing: dict[str, Any] | None) -> dict[str, Any]:
    kept_rules = []
    if existing:
        for rule in existing.get("rules", []):
            if rule.get("ref") not in MANAGED_REFS:
                kept_rules.append(rule)
    return {
        "name": (existing.get("name") if existing else "") or f"Mellow Day {phase}",
        "description": (existing.get("description") if existing else "")
        or f"Managed by Mellow Day cloudflare_rules.py ({phase})",
        "rules": kept_rules + rules,
    }


def get_entrypoint(token: str, zone_id: str, phase: str) -> dict[str, Any] | None:
    response = cf_request(
        "GET",
        f"/zones/{zone_id}/rulesets/phases/{phase}/entrypoint",
        token,
    )
    if response.get("success"):
        return response.get("result") or {}
    if response.get("status") == 404:
        return None
    raise RuntimeError(json.dumps(response.get("errors", response), ensure_ascii=False))


def update_entrypoint(token: str, zone_id: str, phase: str, rules: list[dict[str, Any]], dry_run: bool) -> None:
    existing = get_entrypoint(token, zone_id, phase)
    payload = phase_payload(phase, rules, existing)
    print(f"\n[{phase}]")
    print(f"  Existing rules kept: {len(payload['rules']) - len(rules)}")
    print(f"  Managed rules upserted: {len(rules)}")
    for rule in rules:
        print(f"  - {rule['ref']}: {rule['action']}")
    if dry_run:
        return
    response = cf_request(
        "PUT",
        f"/zones/{zone_id}/rulesets/phases/{phase}/entrypoint",
        token,
        payload,
    )
    if not response.get("success"):
        raise RuntimeError(json.dumps(response.get("errors", response), ensure_ascii=False))
    print("  Applied.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Cloudflare rules for Mellow Day Cafe.")
    parser.add_argument("--apply", action="store_true", help="Apply changes to Cloudflare.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without applying.")
    args = parser.parse_args()
    dry_run = not args.apply or args.dry_run

    token, zone_id, hostname = require_config()
    print(f"Cloudflare hostname: {hostname}")
    print("Mode: " + ("dry-run" if dry_run else "apply"))
    update_entrypoint(token, zone_id, "http_request_firewall_custom", waf_rules(hostname), dry_run)
    update_entrypoint(token, zone_id, "http_request_cache_settings", cache_rules(hostname), dry_run)
    print("\n[OK] Cloudflare rule configuration finished.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] Cloudflare API failed: {exc}")
        raise SystemExit(1)
