#!/usr/bin/env python3
"""Refresh every Google MCP access token from its stored refresh_token.

Generalizes the calendar_briefing.py pattern to all Google connectors so a
dashboard/session restart never lands on an expired token. Designed to run as
a `type: command` scheduled task (no LLM, no tmux): exit 0 when every account
refreshed, exit 1 when any account failed -- the command-task failure-streak
alerting then notifies the operator. An `invalid_grant` failure means the
refresh token was revoked and a browser re-auth is needed (see the
google-mcp-reauth skill); that CANNOT be fixed unattended, only alerted.

Usage: google-token-refresh.py [--quiet]
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error

HOME = os.path.expanduser("~")

# (label, token file, oauth keys file). Token files use either the flat
# format or the {"normal": {...}} wrapper -- both handled below.
ACCOUNTS = [
    ("gmail (maslentrek)", f"{HOME}/.gmail-mcp/credentials.json", f"{HOME}/.gmail-mcp/gcp-oauth.keys.json"),
    ("gcal Trek",   f"{HOME}/gcalendar-mcp-server/credentials/.gcalendar-server-credentials.json",        f"{HOME}/gcalendar-mcp-server/credentials/gcp-oauth.keys.json"),
    ("gcal Arnold", f"{HOME}/gcalendar-mcp-server/credentials/.gcalendar-arnoldgruzman-credentials.json", f"{HOME}/gcalendar-mcp-server/credentials/gcp-oauth.keys.json"),
    ("gcal Uzem",   f"{HOME}/gcalendar-mcp-server/credentials/.gcalendar-maslenaptar-credentials.json",   f"{HOME}/gcalendar-mcp-server/credentials/gcp-oauth.keys.json"),
]

# Refresh when the access token has less than this much life left.
MIN_REMAINING_MS = 15 * 60 * 1000


def refresh(label, token_path, keys_path, quiet):
    if not os.path.exists(token_path):
        print(f"SKIP  {label}: no token file ({token_path})")
        return True  # not configured -> not a failure
    keys = json.load(open(keys_path))
    inst = keys.get("installed") or keys.get("web")
    d = json.load(open(token_path))
    node = d.get("normal", d)
    remaining = node.get("expiry_date", 0) - time.time() * 1000
    if remaining > MIN_REMAINING_MS:
        if not quiet:
            print(f"OK    {label}: token still valid ({int(remaining/60000)} min left)")
        return True
    body = urllib.parse.urlencode({
        "client_id": inst["client_id"], "client_secret": inst["client_secret"],
        "refresh_token": node["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    try:
        r = json.load(urllib.request.urlopen(
            urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=20))
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        print(f"FAIL  {label}: HTTP {e.code} {detail}")
        if "invalid_grant" in detail:
            print(f"      -> refresh token revoked; browser re-auth needed (google-mcp-reauth skill)")
        return False
    except Exception as e:
        print(f"FAIL  {label}: {e}")
        return False
    node["access_token"] = r["access_token"]
    node["expiry_date"] = int((time.time() + r.get("expires_in", 3600)) * 1000)
    if "normal" in d:
        d["normal"] = node
    tmp = token_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, token_path)
    print(f"OK    {label}: refreshed (+{r.get('expires_in', 3600)}s)")
    return True


def main():
    quiet = "--quiet" in sys.argv
    ok = all([refresh(*acc, quiet) for acc in ACCOUNTS])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
