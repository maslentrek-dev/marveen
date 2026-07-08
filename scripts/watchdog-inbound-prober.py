#!/usr/bin/env python3
"""Telethon inbound-probe prober for the channel-deafness watchdog.

Sends __wd_ping <ISO> as a DM TO THE MAIN BOT every PROBE_INTERVAL_MS
milliseconds. The watchdog reads the main session transcript to verify the
ping was ingested; if not, it triggers a respawn.

Target resolution (2026-07-08 fix): the ping target is the BOT itself, whose
@username is resolved once at startup via Bot API getMe (TELEGRAM_BOT_TOKEN
from .env), overridable with WATCHDOG_PROBE_TARGET (e.g. "@my_bot"). The
previous code sent to ALLOWED_CHAT_ID -- but that is the OPERATOR's private
chat id: a userbot->operator DM never reaches the bot, so the plugin would
never ingest the marker and every probe cycle would end in a false deafness
respawn (and the operator would get pinged every 3 minutes).

SAFE without the prober account being allowlisted (/telegram:access):
if the session file is missing or auth fails, logs a warning and exits 0.

MANUAL GATE REQUIRED before first activation:
  the operator must run `/telegram:access` in the main channels session to allowlist
  prober account <prober-account-id> (<prober-phone>). Until then this script is a
  no-op (it detects the missing/unauthorised state and exits cleanly).

NEVER logs the session string. NEVER passes it via argv.
"""

import asyncio
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root (scripts/ is one level below repo root)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

SESSION_FILE = PROJECT_ROOT / "store" / ".watchdog-userbot.session"
CREDS_FILE = PROJECT_ROOT / "store" / ".watchdog-userbot.json"
ENV_FILE = PROJECT_ROOT / ".env"
PROBE_LAST_SENT_FILE = PROJECT_ROOT / "store" / ".watchdog-probe-last-sent"

# ---------------------------------------------------------------------------
# .env parser (same approach as other scripts in this repo)
# ---------------------------------------------------------------------------
def resolve_probe_target(env: dict) -> str | None:
    """The bot @username the ping is DM'd to.

    WATCHDOG_PROBE_TARGET wins (explicit operator override, "@name" or "name");
    otherwise resolve the bot's username once via Bot API getMe. Never returns
    a bare numeric id: a fresh StringSession has no access_hash cached for raw
    ids, while a username resolves through ResolveUsername reliably.
    """
    explicit = env.get("WATCHDOG_PROBE_TARGET", "").strip()
    if explicit:
        return explicit if explicit.startswith("@") else "@" + explicit
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        # The channel plugin owns the bot token since the channels migration;
        # marveen/.env no longer carries it (verified 2026-07-08).
        channel_env = Path.home() / ".claude" / "channels" / "telegram" / ".env"
        token = read_env(channel_env).get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getMe", timeout=15
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        username = (data.get("result") or {}).get("username")
        return "@" + username if username else None
    except Exception as exc:
        # W6: log only the exception type -- the URL carries the bot token.
        print(f"inbound-prober: getMe failed: {type(exc).__name__}", file=sys.stderr)
        return None


def read_env(path: Path) -> dict:
    result = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            eq = line.find("=")
            if eq == -1:
                continue
            key = line[:eq].strip()
            val = line[eq + 1:].strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            result[key] = val
    except OSError:
        pass
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    # --- Session file check ---
    if not SESSION_FILE.exists():
        print(
            "MANUAL GATE: store/.watchdog-userbot.session missing. "
            "Allowlist prober account <prober-account-id> via /telegram:access in the main channels session. "
            "Exiting as safe no-op.",
            file=sys.stderr,
        )
        sys.exit(0)

    # N4: defensively ensure credentials file is readable only by owner.
    if CREDS_FILE.exists():
        os.chmod(CREDS_FILE, 0o600)

    # --- Credentials ---
    try:
        creds = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        api_id = int(creds["api_id"])
        api_hash = str(creds["api_hash"])
    except Exception as exc:
        # W6: log only exception type, never str(exc) which may carry credential payload.
        print(f"inbound-prober: failed to load credentials from {CREDS_FILE}: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

    # --- Session string (NEVER log its value) ---
    try:
        session_data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        session_str = session_data["session"]
    except Exception as exc:
        # W6: log only exception type.
        print(f"inbound-prober: failed to load session string: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

    # --- .env config ---
    env = read_env(ENV_FILE)
    probe_target = resolve_probe_target(env)
    if not probe_target:
        print(
            "inbound-prober: cannot resolve probe target "
            "(set WATCHDOG_PROBE_TARGET or a valid TELEGRAM_BOT_TOKEN in .env) -- exiting as safe no-op",
            file=sys.stderr,
        )
        sys.exit(0)

    probe_interval_ms = 180_000
    raw_interval = env.get("PROBE_INTERVAL_MS", "")
    if raw_interval:
        try:
            probe_interval_ms = int(raw_interval)
        except ValueError:
            pass
    # W1: enforce a minimum floor of 30 000 ms to prevent inadvertent DoS.
    probe_interval_ms = max(probe_interval_ms, 30_000)
    probe_interval_s = probe_interval_ms / 1000.0

    # --- Import telethon (inside venv) ---
    # W5: pinned dependencies in scripts/watchdog-requirements.txt
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import (
            FloodWaitError,
            AuthKeyError,
            UserDeactivatedError,
            UserDeactivatedBanError,
        )
    except ImportError as exc:
        print(f"inbound-prober: telethon not available: {exc}", file=sys.stderr)
        sys.exit(0)

    # --- Connect ---
    # MANUAL GATE: prober account <prober-account-id> must be /telegram:access allowlisted
    # by the operator before messages will be delivered. Until then this prober runs but
    # messages are dropped by the allowlist.
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(
                "MANUAL GATE: allowlist prober account <prober-account-id> via /telegram:access in the main channels session. "
                "Session exists but user is not authorized. Exiting as safe no-op.",
                file=sys.stderr,
            )
            await client.disconnect()
            sys.exit(0)
    except (AuthKeyError, UserDeactivatedError, UserDeactivatedBanError) as exc:
        # W6: log only exception type to avoid forwarding any payload.
        print(
            f"MANUAL GATE: allowlist prober account <prober-account-id> via /telegram:access in the main channels session. "
            f"Auth error: {type(exc).__name__}. Exiting as safe no-op.",
            file=sys.stderr,
        )
        try:
            await client.disconnect()
        except Exception:
            pass
        sys.exit(0)
    except Exception as exc:
        # W6: log only exception type.
        print(f"inbound-prober: connection error: {type(exc).__name__}", file=sys.stderr)
        try:
            await client.disconnect()
        except Exception:
            pass
        sys.exit(0)

    print(f"inbound-prober: connected. Will ping every {probe_interval_s}s.", flush=True)

    # --- Main send loop ---
    try:
        while True:
            ts_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            msg = f"__wd_ping {ts_iso}"
            try:
                await client.send_message(probe_target, msg)
                # Write marker AFTER successful send so the TS watchdog has
                # a reliable last-sent timestamp.
                PROBE_LAST_SENT_FILE.write_text(ts_iso, encoding="utf-8")
                print(f"inbound-prober: sent ping at {ts_iso}", flush=True)
            except FloodWaitError as fwe:
                wait_secs = fwe.seconds if hasattr(fwe, "seconds") else 60
                print(f"inbound-prober: FloodWait {wait_secs}s -- sleeping", file=sys.stderr, flush=True)
                await asyncio.sleep(wait_secs)
                continue
            except Exception as exc:
                # W6: log only exception type to avoid forwarding message payload.
                print(f"inbound-prober: send_message error: {type(exc).__name__}", file=sys.stderr, flush=True)

            await asyncio.sleep(probe_interval_s)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
