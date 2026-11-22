#!/usr/bin/env python3
"""Publish official MLB box score and play-by-play links, with seasonal monitoring."""
import json, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ET=ZoneInfo("America/New_York")
OUT=Path("gamebooks.json")
API="https://statsapi.mlb.com/api/v1/schedule"
LOG=logging.getLogger("mlb-reports")
HEADERS={"User-Agent":"MLBGamebookDashboard/1.0","Accept":"application/json"}

def main():
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    now=datetime.now(ET)
    if now.month not in (2,3,4,5,6,7,8,9,10):
        OUT.write_text(json.dumps({"window_label":"Offseason","updated_at":datetime.now(timezone.utc).isoformat(),"offseason":True,"games":[]},indent=2)+"\n")
        LOG.info("Offseason: skipping MLB schedule checks")
        return
    today=(now-timedelta(hours=3)).date()
    days=[today-timedelta(days=1),today]
    session=requests.Session()
    session.headers.update(HEADERS)
    games=[];failures=[]
    for day in days:
        try:
            r=session.get(API,params={"sportId":1,"date":day.isoformat(),"hydrate":"team","gameTypes":"S,R,F,D,L,W"},timeout=25)
            r.raise_for_status()
            for block in r.json().get("dates",[]):
                for game in block.get("games",[]):
                    pk=game.get("gamePk")
                    if not isinstance(pk,int):continue
                    teams=game.get("teams",{})
                    away=teams.get("away",{}).get("team",{}).get("name","Away")
                    home=teams.get("home",{}).get("team",{}).get("name","Home")
                    state=game.get("status",{}).get("detailedState","Scheduled")
                    item={"id":str(pk),"date":day.isoformat(),"label":f"{away} @ {home}","status":state}
                    # MLB official game-specific pages. Do not claim they are PDF gamebooks.
                    if game.get("status",{}).get("abstractGameState") in ("Live","Final"):
                        base=f"https://www.mlb.com/gameday/{pk}"
                        item["box_url"]=base+"/box-score"
                        item["plays_url"]=base+"/play-by-play"
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
    games.sort(key=lambda g:(g["date"],g["label"],g["id"]))
    data={"window_label":f"{days[0]:%b %d, %Y} – {days[1]:%b %d, %Y} (ET; 3 AM rollover)","updated_at":datetime.now(timezone.utc).isoformat(),"games":games}
    if failures:data["warning"]="MLB schedule temporarily unavailable for "+", ".join(failures)
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n")
    LOG.info("Published %d MLB games",len(games))
    if len(failures)==2:raise RuntimeError("Both MLB schedule requests failed")

if __name__=="__main__":main()
