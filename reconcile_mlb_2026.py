#!/usr/bin/env python3
"""Safely catch up 2026 MLB exhibition and All-Star games missed by old filters."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import archive
from mlb_policy import game_category, official_links, validate_game_data
from monitor import HEADERS, API


def special_schedule(session, start=date(2026, 1, 1), end=None):
    end = end or datetime.now(timezone.utc).date()
    day = start
    all_games = {}
    while day <= end:
        last = min(day + timedelta(days=30), end)
        response = session.get(API, params={
            "sportId": 1, "startDate": day.isoformat(),
            "endDate": last.isoformat(),
            "hydrate": "team", "gameTypes": "A,E",
        }, timeout=35)
        response.raise_for_status()
        data = response.json()
        blocks = data.get("dates")
        if not isinstance(blocks, list):
            raise ValueError(f"MLB source returned invalid schedule for {day}")
        for block in blocks:
            date_str = block["date"]
            for event in block.get("games", []):
                kind = event.get("gameType")
                if kind not in ("A", "E"):
                    continue
                pk = event.get("gamePk")
                if not isinstance(pk, int):
                    raise ValueError("MLB special event is missing a numeric ID")
                teams = event.get("teams") or {}
                away = ((teams.get("away") or {}).get("team") or {}).get("name", "Away")
                home = ((teams.get("home") or {}).get("team") or {}).get("name", "Home")
                status = event.get("status") or {}
                row = {
                    "id": str(pk), "date": date_str,
                    "label": f"{away} @ {home}",
                    "status": status.get("detailedState", "Scheduled"),
                    "game_type": kind, "competition": game_category(kind),
                }
                if status.get("abstractGameState") in ("Live", "Final"):
                    valid, reason = validate_game_data(session, pk)
                    row.update(official_links(pk))
                    row["link_verification"] = "verified_api" if valid else "needs_review:"+reason
                all_games[str(pk)] = row
        day = last + timedelta(days=1)
    return sorted(all_games.values(), key=lambda g: (g["date"], g["id"]), reverse=True)


def reconcile(archive_path=Path("archive.json"), report_path=Path("special-game-review.json"),
              session=None, dry_run=False, start=date(2026, 1, 1), end=None):
    session = session or requests.Session()
    session.headers.update(HEADERS)
    previous = archive.load_payload(Path(archive_path), "MLB cumulative archive")
    prior = archive.validate_games(previous, "Previous MLB archive")
    special = special_schedule(session, start=start, end=end)
    merged = archive.build_archive({"games": special}, previous)
    introduced = sorted(set(archive.validate_games(merged, "Merged MLB archive")) - set(prior))
    report = {
        "scope": "2026",
        "special_games_discovered": len(special),
        "new_archive_ids": introduced,
        "all_star_count": sum(g["game_type"] == "A" for g in special),
        "exhibition_count": sum(g["game_type"] == "E" for g in special),
    }
    print(f"MLB 2026: {len(special)} official All-Star/exhibition events, "
          f"{len(introduced)} new archival IDs; dry_run={dry_run}")
    if dry_run:
        return report
    if merged["games"] != previous["games"]:
        archive.atomic_write_json(Path(archive_path), merged)
    stable = {k:v for k,v in report.items() if k != "new_archive_ids"}
    if not Path(report_path).exists() or {
        k:v for k,v in json.loads(Path(report_path).read_text()).items()
        if k != "new_archive_ids"
    } != stable:
        Path(report_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    reconcile(dry_run=args.dry_run)
