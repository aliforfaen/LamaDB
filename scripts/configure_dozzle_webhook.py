#!/usr/bin/env python3
"""
Configure Dozzle webhook notifications via its REST API.

This script:
  1. Creates a webhook dispatcher pointing to LamaDB's public webhook endpoint
  2. Creates notification rules for ERROR and WARN level events
  3. Tests the webhook to verify connectivity

Usage:
    python scripts/configure_dozzle_webhook.py

Requirements:
    - Dozzle server must be reachable (DOZZLE_HOST env var, default: http://probook:7080)
    - Dozzle must have no authentication enabled (as per current setup)

Environment variables:
    DOZZLE_HOST         Dozzle base URL (default: http://probook:7080)
    LAMADB_HOST         LamaDB base URL for webhook target (default: http://100.124.57.27:8000)
    DOZZLE_VERIFY_SSL   Whether to verify SSL (default: true, set to false for self-signed)
"""

import json
import sys
import os
import argparse

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_DOZZLE_HOST = "http://probook:7080"
DEFAULT_LAMADB_HOST = "http://100.124.57.27:8000"
DEFAULT_VERIFY_SSL = True


def get_settings():
    return {
        "dozzle_host": os.environ.get("DOZZLE_HOST", DEFAULT_DOZZLE_HOST).rstrip("/"),
        "lamadb_host": os.environ.get("LAMADB_HOST", DEFAULT_LAMADB_HOST).rstrip("/"),
        "verify_ssl": os.environ.get("DOZZLE_VERIFY_SSL", "true").lower() not in ("false", "0", "no"),
    }


# ---------------------------------------------------------------------------
# Dozzle API helpers
# ---------------------------------------------------------------------------

class DozzleClient:
    """Thin wrapper around httpx for Dozzle's notification API."""

    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.client = httpx.Client(timeout=30.0, verify=verify_ssl)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_dispatchers(self) -> list[dict]:
        """GET /api/notifications/dispatchers — list webhook dispatchers."""
        resp = self.client.get(self._url("/api/notifications/dispatchers"))
        resp.raise_for_status()
        return resp.json()

    def create_dispatcher(self, dispatcher: dict) -> dict:
        """POST /api/notifications/dispatchers — create a webhook dispatcher."""
        resp = self.client.post(
            self._url("/api/notifications/dispatchers"),
            json=dispatcher,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    def delete_dispatcher(self, dispatcher_id: str) -> None:
        """DELETE /api/notifications/dispatchers/{id}."""
        resp = self.client.delete(self._url(f"/api/notifications/dispatchers/{dispatcher_id}"))
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # 404 is acceptable (already gone)
            if e.response.status_code != 404:
                raise

    def get_rules(self) -> list[dict]:
        """GET /api/notifications/rules — list notification rules."""
        resp = self.client.get(self._url("/api/notifications/rules"))
        resp.raise_for_status()
        return resp.json()

    def create_rule(self, rule: dict) -> dict:
        """POST /api/notifications/rules — create a notification rule."""
        resp = self.client.post(
            self._url("/api/notifications/rules"),
            json=rule,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    def delete_rule(self, rule_id: str) -> None:
        """DELETE /api/notifications/rules/{id}."""
        resp = self.client.delete(self._url(f"/api/notifications/rules/{rule_id}"))
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

    def test_webhook(self, url: str) -> dict:
        """POST /api/notifications/test-webhook — test a webhook URL."""
        resp = self.client.post(
            self._url("/api/notifications/test-webhook"),
            json={"url": url, "type": "webhook"},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    def close(self):
        self.client.close()


# ---------------------------------------------------------------------------
# Dispatcher management
# ---------------------------------------------------------------------------

DISPATCHER_NAME = "LamaDB Events"


def find_existing_dispatcher(client: DozzleClient) -> str | None:
    """Return the ID of an existing LamaDB dispatcher, or None."""
    dispatchers = client.get_dispatchers()
    for d in dispatchers:
        if d.get("name") == DISPATCHER_NAME:
            return d.get("id")
    return None


def ensure_dispatcher(client: DozzleClient, webhook_url: str, replace: bool = False) -> dict:
    """
    Create or update the LamaDB webhook dispatcher.

    Args:
        client: DozzleClient instance.
        webhook_url: Full URL to LamaDB's public webhook endpoint.
        replace: If True, delete any existing dispatcher first.

    Returns:
        The created/updated dispatcher object.
    """
    existing_id = find_existing_dispatcher(client)

    if existing_id:
        if replace:
            print(f"  [*] Replacing existing dispatcher (id={existing_id})")
            client.delete_dispatcher(existing_id)
        else:
            print(f"  [+] LamaDB dispatcher already exists (id={existing_id})")
            return {"id": existing_id, "name": DISPATCHER_NAME}

    dispatcher = {
        "name": DISPATCHER_NAME,
        "url": webhook_url,
        "type": "webhook",
        "method": "POST",
    }
    result = client.create_dispatcher(dispatcher)
    print(f"  [+] Created dispatcher (id={result.get('id')})")
    return result


# ---------------------------------------------------------------------------
# Rule management
# ---------------------------------------------------------------------------

# Dozzle notification rule schema (based on typical Dozzle API shape):
# {
#   "name": str,
#   "channels": [dispatcher_id, ...],
#   "containers": ["*"] | [container_name, ...],
#   "levels": ["error", "warn"],
#   "regex": ""  (optional filter on log message)
# }


def build_rule(name: str, dispatcher_id: str, levels: list[str], containers: list[str] | None = None) -> dict:
    """Build a notification rule payload."""
    rule = {
        "name": name,
        "channels": [dispatcher_id],
        "levels": levels,
        "regex": "",
    }
    if containers:
        rule["containers"] = containers
    else:
        rule["containers"] = ["*"]  # all containers
    return rule


def find_existing_rule(client: DozzleClient, rule_name: str) -> str | None:
    """Return the ID of an existing rule by name, or None."""
    rules = client.get_rules()
    for r in rules:
        if r.get("name") == rule_name:
            return r.get("id")
    return None


def ensure_rule(
    client: DozzleClient,
    dispatcher_id: str,
    name: str,
    levels: list[str],
    containers: list[str] | None = None,
    replace: bool = False,
) -> dict:
    """
    Create or update a notification rule.

    Args:
        client: DozzleClient instance.
        dispatcher_id: ID of the dispatcher to attach.
        name: Human-readable rule name.
        levels: Log levels to trigger on (e.g. ["error", "warn"]).
        containers: Container name filter (None = all).
        replace: If True, delete existing rule first.

    Returns:
        The created/updated rule object.
    """
    existing_id = find_existing_rule(client, name)

    if existing_id:
        if replace:
            print(f"  [*] Replacing existing rule '{name}' (id={existing_id})")
            client.delete_rule(existing_id)
        else:
            print(f"  [+] Rule '{name}' already exists (id={existing_id})")
            return {"id": existing_id, "name": name}

    rule = build_rule(name, dispatcher_id, levels, containers)
    result = client.create_rule(rule)
    print(f"  [+] Created rule '{name}' (id={result.get('id')})")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

RULES = [
    {
        "name": "LamaDB: Error Alerts",
        "levels": ["error"],
        "containers": None,  # all containers
    },
    {
        "name": "LamaDB: Warn Alerts",
        "levels": ["warn"],
        "containers": None,
    },
]


def main():
    parser = argparse.ArgumentParser(description="Configure Dozzle webhook notifications for LamaDB")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing dispatchers and rules instead of skipping",
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Skip the webhook test step",
    )
    parser.add_argument(
        "--dozzle-url",
        dest="dozzle_url",
        default=None,
        help=f"Dozzle base URL (default: {DEFAULT_DOZZLE_HOST})",
    )
    parser.add_argument(
        "--lamadb-url",
        dest="lamadb_url",
        default=None,
        help=f"LamaDB base URL for webhook target (default: {DEFAULT_LAMADB_HOST})",
    )
    args = parser.parse_args()

    cfg = get_settings()
    dozzle_url = args.dozzle_url or cfg["dozzle_host"]
    lamadb_url = args.lamadb_url or cfg["lamadb_host"]
    verify_ssl = cfg["verify_ssl"]

    webhook_url = f"{lamadb_url}/api/dozzle/webhook"

    print(f"\n=== Dozzle Webhook Configuration ===")
    print(f"  Dozzle host : {dozzle_url}")
    print(f"  LamaDB host : {lamadb_url}")
    print(f"  Webhook URL : {webhook_url}")
    print(f"  Verify SSL  : {verify_ssl}")
    print()

    client = DozzleClient(dozzle_url, verify_ssl=verify_ssl)

    try:
        # 1. Show existing dispatchers
        print("[*] Fetching existing dispatchers...")
        dispatchers = client.get_dispatchers()
        print(f"    Found {len(dispatchers)} dispatcher(s)")
        for d in dispatchers:
            print(f"      - {d.get('name')} (id={d.get('id')})")

        # 2. Create/update dispatcher
        print("\n[*] Ensuring LamaDB dispatcher exists...")
        dispatcher = ensure_dispatcher(client, webhook_url, replace=args.replace)

        # 3. Show existing rules
        print("\n[*] Fetching existing notification rules...")
        rules = client.get_rules()
        print(f"    Found {len(rules)} rule(s)")
        for r in rules:
            print(f"      - {r.get('name')} (id={r.get('id')})")

        # 4. Create notification rules
        print("\n[*] Ensuring notification rules exist...")
        for rule_cfg in RULES:
            ensure_rule(
                client,
                dispatcher["id"],
                rule_cfg["name"],
                rule_cfg["levels"],
                rule_cfg.get("containers"),
                replace=args.replace,
            )

        # 5. Test webhook
        if not args.skip_test:
            print(f"\n[*] Testing webhook → {webhook_url}")
            try:
                result = client.test_webhook(webhook_url)
                print(f"  [+] Webhook test succeeded: {result}")
            except Exception as e:
                print(f"  [!] Webhook test failed: {e}")
                print("      This may be expected if LamaDB is not running yet.")
                print("      The dispatcher is still configured — it will work once LamaDB is up.")
        else:
            print("\n[*] Skipping webhook test (--skip-test)")

        print("\n=== Configuration complete ===")
        print(f"Webhook URL: {webhook_url}")
        print("In Dozzle UI, verify the dispatcher is active under Settings → Notifications")

    finally:
        client.close()


if __name__ == "__main__":
    main()
