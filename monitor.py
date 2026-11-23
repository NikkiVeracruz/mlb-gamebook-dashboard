#!/usr/bin/env python3
"""Publish official MLB box score and play-by-play links, with seasonal monitoring."""
import json, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import archive as archive_module
from mlb_policy import game_category, official_links, validate_game_data
from three_day_window import three_days, archive_outgoing_games, scheduled_games_in_window

ET=ZoneInfo("America/New_York")
OUT=Path("gamebooks.json")
API="https://statsapi.mlb.com/api/v1/schedule"
LOG=logging.getLogger("mlb-reports")
HEADERS={"User-Agent":"MLBGamebookDashboard/1.0","Accept":"application/json"}

def write_if_changed(path, payload):
    """Publish only genuine feed changes; save successful checks separately."""
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = {}
    visible = lambda x: {k: v for k, v in x.items() if k != "updated_at"}
    if visible(prior) == visible(payload):
        LOG.info("Feed unchanged; skipped timestamp-only commit")
        return False
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return True


def main():
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    # Never remove an outgoing MLB game until its existing record is saved.
    days=three_days()
    archive_outgoing_games(OUT, archive_module.ARCHIVE, days, archive_module)
    now=datetime.now(ET)
    if (now.month not in (2,3,4,5,6,7,8,9,10)
            and not scheduled_games_in_window("league-calendar.json", days)
            and not __import__("adaptive_monitor").should_poll("MLB")):
        write_if_changed(OUT, {"window_label":f"{days[0]:%b %d, %Y} – {days[-1]:%b %d, %Y} (ET; 3 AM rollover)",
                              "window_dates":[d.isoformat() for d in days],
                              "updated_at":datetime.now(timezone.utc).isoformat(),"offseason":True,"games":[]})
        LOG.info("Offseason: no MLB games scheduled in rolling three-date window")
        return
    session=requests.Session()
    session.headers.update(HEADERS)
    games=[];failures=[]
    try:
        prior = json.loads(OUT.read_text(encoding="utf-8"))
        verified_cache = {str(g.get("id")):g.get("link_verification")
                          for g in prior.get("games",[]) if isinstance(g,dict)}
    except (OSError,ValueError):
        verified_cache = {}
    for day in days:
        try:
            r=session.get(API,params={"sportId":1,"date":day.isoformat(),"hydrate":"team","gameTypes":"S,R,F,D,L,W,A,E"},timeout=25)
            r.raise_for_status()
            for block in r.json().get("dates",[]):
                for game in block.get("games",[]):
                    pk=game.get("gamePk")
                    if not isinstance(pk,int):continue
                    teams=game.get("teams",{})
                    away=teams.get("away",{}).get("team",{}).get("name","Away")
                    home=teams.get("home",{}).get("team",{}).get("name","Home")
                    state=game.get("status",{}).get("detailedState","Scheduled")
                    item={"id":str(pk),"date":day.isoformat(),"label":f"{away} @ {home}",
                          "status":state,"game_type":game.get("gameType"),
                          "competition":game_category(game.get("gameType"))}
                    # MLB official game-specific pages. Do not claim they are PDF gamebooks.
                    if game.get("status",{}).get("abstractGameState") in ("Live","Final"):
                        # Do NOT expose Gameday links before their game-specific
                        # official statistics have actually been confirmed.
                        previous = verified_cache.get(str(pk))
                        if previous == "verified_api":
                            item.update(official_links(pk))
                            item["link_verification"] = "verified_api"
                        else:
                            valid,reason=validate_game_data(session,pk)
                            if valid:
                                item.update(official_links(pk))
                                item["link_verification"] = "verified_api"
                            else:
                                item["link_verification"] = "needs_review:"+reason
                    games.append(item)
            LOG.info("Loaded %s",day)
        except (requests.RequestException,ValueError,KeyError):
            LOG.exception("MLB schedule unavailable for %s",day)
            failures.append(day.isoformat())
    if failures:
        try:
            previous=json.loads(OUT.read_text())
            seen={g["id"] for g in games}
            for g in previous.get("games",[]):
                if g.get("date") in {d.isoformat() for d in days} and g.get("id") not in seen:
                    games.append(g)
        except (OSError,ValueError,KeyError):pass
    # Completeness guard: a successful but partial schedule response must not erase games.
    try:
        prior_data = json.loads(OUT.read_text(encoding="utf-8"))
        known = {str(g["id"]): g for g in prior_data.get("games", []) if g.get("date") in {d.isoformat() for d in days} and g.get("id")}
        seen = {str(g["id"]) for g in games}
        missing = [g for gid, g in known.items() if gid not in seen]
        if missing:
            LOG.warning("SCHEDULE COMPLETENESS ALERT: %d previously known MLB games missing from source; retaining them", len(missing))
            games.extend(missing)
            failures.append("partial schedule: " + ", ".join(g["date"] for g in missing))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Retain previously verified MLB-hosted links for a game if a partial
    # upstream response temporarily omits them; never carry links between IDs.
    try:
        old_data=json.loads(OUT.read_text(encoding="utf-8"))
        previous={str(g.get("id")):g for g in old_data.get("games",[])
                  if isinstance(g,dict) and g.get("id")}
        for game in games:
            old=previous.get(str(game.get("id")))
            if not old or old.get("date")!=game.get("date"):continue
            prefix="https://www.mlb.com/gameday/"+str(game["id"])
            if old.get("link_verification")=="verified_api" and game.get("link_verification")!="verified_api":
                game["link_verification"]="verified_api"
            for key,suffix in (("box_url","/box-score"),("plays_url","/play-by-play")):
                if (old.get("link_verification")=="verified_api"
                        and not game.get(key) and old.get(key)==prefix+suffix):
                    game[key]=old[key]
    except (OSError,ValueError,TypeError,KeyError):
        pass
    games.sort(key=lambda g:(g["date"],g["label"],g["id"]))
    data={"window_label":f"{days[0]:%b %d, %Y} – {days[-1]:%b %d, %Y} (ET; 3 AM rollover)",
          "window_dates":[d.isoformat() for d in days],
          "updated_at":datetime.now(timezone.utc).isoformat(),"games":games}
    if failures:data["warning"]="MLB schedule temporarily unavailable for "+", ".join(failures)
    write_if_changed(OUT, data)
    LOG.info("Published %d MLB games",len(games))
    if len(failures)==len(days):raise RuntimeError("All three MLB schedule requests failed")

if __name__=="__main__":main()
