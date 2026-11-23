#!/usr/bin/env python3
"""Gradually verify 2026 MLB Gameday links against actual official Stats API data.

Existing links remain archived even when verification is inconclusive. The
separate review file says which game IDs truly passed independent validation.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import requests
import archive
from mlb_policy import validate_game_data

ARCHIVE=Path("archive.json")
REVIEW=Path("link-review.json")
BATCH=250


def review_game(game_id):
    session=requests.Session()
    valid, reason=validate_game_data(session, game_id)
    return str(game_id), "verified_api" if valid else "needs_review:"+reason


def audit(archive_path=ARCHIVE, review_path=REVIEW, limit=BATCH, executor_class=ThreadPoolExecutor):
    data=archive.load_payload(Path(archive_path), "MLB historical archive for link review")
    reviewed={}
    if Path(review_path).exists():
        reviewed=json.loads(Path(review_path).read_text(encoding="utf-8")).get("games",{})
    games={str(g["id"]):g for g in data["games"]
           if (g.get("id") and str(g.get("id")).isdigit()
               and "2026-01-01" <= g.get("date","") <= date.today().isoformat()
               and (g.get("box_url") or g.get("plays_url"))
               and str(g.get("status","")).lower() not in
               ("scheduled","postponed","suspended"))}
    # Every game is checked once, then unresolved cases are rotated for follow-up.
    unseen=[key for key in sorted(games) if key not in reviewed]
    retry=[key for key in sorted(games) if reviewed.get(key)!="verified_api"]
    chosen=(unseen or retry)[:limit]
    if chosen:
        with executor_class(max_workers=8) as executor:
            futures={executor.submit(review_game,gid):gid for gid in chosen}
            for future in as_completed(futures):
                game_id, status=future.result()
                reviewed[game_id]=status
    output={"scope":"2026","games":dict(sorted(reviewed.items())),
            "archived_games_with_links":len(games),
            "checked":len([key for key in reviewed if key in games]),
            "verified":sum(reviewed.get(key)=="verified_api" for key in games),
            "needs_review":sum(reviewed.get(key,"").startswith("needs_review")
                               for key in games)}
    if not Path(review_path).exists() or json.loads(Path(review_path).read_text())!=output:
        Path(review_path).write_text(
            json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("MLB 2026 link audit: "
          f"{output['checked']}/{output['archived_games_with_links']} checked, "
          f"{output['verified']} verified, {output['needs_review']} needs review, "
          f"batch={len(chosen)}")
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int,default=BATCH)
    args=parser.parse_args()
    audit(limit=max(1,min(args.limit,1000)))
