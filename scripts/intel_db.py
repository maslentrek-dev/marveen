"""
intel_db.py -- Helper functions for the Proactive Intelligence Cycle (v4).
Database: /Users/gruzmanarnold/marveen/store/intel.db
"""

import sqlite3
import hashlib
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "store" / "intel.db"


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def get_active_registry(days: int = 14) -> list[dict]:
    """Return known_facts_registry rows updated within `days` days, excluding closed."""
    cutoff = int(time.time()) - days * 86400
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM known_facts_registry
            WHERE status != 'closed'
              AND updated_at >= ?
            ORDER BY priority_score DESC, updated_at DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_watchlist() -> list[dict]:
    """Return all watchlist entries ordered by creation date desc."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM watchlist ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_focus() -> list[dict]:
    """Return active_focus rows with status='active' and not yet expired."""
    now = int(time.time())
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM active_focus
            WHERE status = 'active'
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY started_at DESC
            """,
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_registry_fact(
    id: str,
    title: str,
    domain: str,
    source: str,
    source_tier: int,
    content: str,
    status: str = "new",
    priority_score: float = 0.5,
) -> str:
    """Insert or update a fact in known_facts_registry. Returns the id."""
    now = int(time.time())
    fact_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM known_facts_registry WHERE id = ?", (id,)
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE known_facts_registry
                SET title=?, domain=?, source=?, source_tier=?, status=?,
                    priority_score=?, content=?, fact_hash=?, updated_at=?
                WHERE id=?
                """,
                (title, domain, source, source_tier, status,
                 priority_score, content, fact_hash, now, id),
            )
        else:
            con.execute(
                """
                INSERT INTO known_facts_registry
                  (id, title, domain, source, source_tier, status,
                   priority_score, content, fact_hash, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (id, title, domain, source, source_tier, status,
                 priority_score, content, fact_hash, now, now),
            )
    return id


def add_watchlist(
    title: str,
    domain: str,
    direction: str,
    notes: str = "",
) -> str:
    """Add a new entry to the watchlist. Returns the generated id."""
    now = int(time.time())
    wid = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """
            INSERT INTO watchlist (id, title, domain, direction, days_tracked, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (wid, title, domain, direction, notes, now, now),
        )
    return wid


def log_decision(
    recommendation: str,
    reasoning: str,
    assumption: str,
    evidence: str,
    what_would_falsify: str,
    arnold_reaction: str = "",
    outcome: str = "",
) -> str:
    """Append a record to decision_log. Returns the generated id."""
    now = int(time.time())
    did = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """
            INSERT INTO decision_log
              (id, date, recommendation, reasoning, assumption, evidence,
               what_would_falsify, arnold_reaction, outcome, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (did, now, recommendation, reasoning, assumption, evidence,
             what_would_falsify, arnold_reaction, outcome, now),
        )
    return did


def make_fact_id(domain: str, content: str, date_str: str | None = None) -> str:
    """Deterministic fact id: <domain>-<YYYYMMDD>-<sha256(content)[:8]>.

    The same finding collected twice on the same day maps to the same id, so
    the collector's repeated hourly runs hit the UPDATE path of
    upsert_registry_fact instead of piling up duplicates.
    """
    day = date_str or time.strftime("%Y%m%d")
    return f"{domain}-{day}-{hashlib.sha256(content.encode()).hexdigest()[:8]}"


def dump_active(days: int = 14) -> dict:
    """Everything the daily brief reads, as one JSON-serializable dict."""
    return {
        "registry": get_active_registry(days),
        "watchlist": get_watchlist(),
        "active_focus": get_active_focus(),
    }


def _cli() -> int:
    """argparse CLI so agent prompts can write the registry without inline Python.

    Subcommands:
      add-fact   upsert into known_facts_registry (deterministic id if omitted)
      add-watch  insert into watchlist
      dump       print dump_active() as JSON (also reachable as --dump)
    No args: the original health counter (kept for backwards compatibility).
    """
    import argparse
    import json
    import sys

    # The daily-brief task calls `intel_db.py --dump`; accept the flag form as
    # an alias for the subcommand so that contract keeps working.
    argv = sys.argv[1:]
    if argv and argv[0] == "--dump":
        argv = ["dump"] + argv[1:]

    parser = argparse.ArgumentParser(description="Proactive Intelligence registry CLI (v4)")
    sub = parser.add_subparsers(dest="cmd")

    p_fact = sub.add_parser("add-fact", help="Upsert a fact into known_facts_registry")
    p_fact.add_argument("--id", help="Fact id; omitted -> deterministic <domain>-<YYYYMMDD>-<hash8>")
    p_fact.add_argument("--title", required=True)
    p_fact.add_argument("--domain", required=True, help="e.g. maslen / makro / jog / utazas")
    p_fact.add_argument("--source", required=True, help="URL or source name")
    p_fact.add_argument("--tier", required=True, type=int, choices=(1, 2, 3), help="source tier (1=primary)")
    p_fact.add_argument("--content", required=True)
    p_fact.add_argument("--status", default="new", choices=("new", "evolving", "stable", "closed"))
    p_fact.add_argument("--priority", default=0.5, type=float, help="priority_score 0..1")

    p_watch = sub.add_parser("add-watch", help="Add a watchlist entry")
    p_watch.add_argument("--title", required=True)
    p_watch.add_argument("--domain", required=True)
    p_watch.add_argument("--direction", required=True, help="what movement/direction is being tracked")
    p_watch.add_argument("--notes", default="")

    p_dump = sub.add_parser("dump", help="Print registry + watchlist + active_focus as JSON")
    p_dump.add_argument("--days", default=14, type=int)

    args = parser.parse_args(argv)

    if args.cmd == "add-fact":
        fact_id = args.id or make_fact_id(args.domain, args.content)
        try:
            upsert_registry_fact(
                id=fact_id, title=args.title, domain=args.domain, source=args.source,
                source_tier=args.tier, content=args.content, status=args.status,
                priority_score=max(0.0, min(1.0, args.priority)),
            )
        except sqlite3.IntegrityError:
            # fact_hash is UNIQUE: same content under a DIFFERENT id means the
            # fact is already known -- a repeat sighting, not an error.
            print(f"DUPLICATE content already in registry (id={fact_id} skipped)")
            return 0
        print(fact_id)
        return 0

    if args.cmd == "add-watch":
        print(add_watchlist(args.title, args.domain, args.direction, args.notes))
        return 0

    if args.cmd == "dump":
        print(json.dumps(dump_active(args.days), ensure_ascii=False, indent=2))
        return 0

    # No subcommand: original health counter, kept as-is.
    print(f"DB: {DB_PATH}")
    print(f"Active registry (14d): {len(get_active_registry())} rows")
    print(f"Watchlist: {len(get_watchlist())} rows")
    print(f"Active focus: {len(get_active_focus())} rows")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
