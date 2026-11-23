"""Official MLB game categories and game-specific statistics validation.

Only verified API response data can earn a verified_api classification.
An MLB.com Gameday URL pattern by itself is not proof that statistics exist.
"""
import requests

GAME_TYPES = "S,R,F,D,L,W,A,E"
CATEGORY = {
    "S": "spring_training",
    "R": "regular_season",
    "F": "wild_card",
    "D": "division_series",
    "L": "league_championship",
    "W": "world_series",
    "A": "all_star",
    "E": "exhibition",
}


def game_category(kind):
    return CATEGORY.get(str(kind or "").upper(), "unclassified_needs_review")


def official_links(game_id):
    token = str(game_id)
    if not token.isdigit():
        raise ValueError(f"Invalid MLB game ID: {token}")
    base = f"https://www.mlb.com/gameday/{token}"
    return {"box_url": base + "/box-score", "plays_url": base + "/play-by-play"}


def validate_game_data(session, game_id, timeout=12):
    """Verify real official MLB box-score and play-by-play data for this game."""
    game_id = str(game_id)
    if not game_id.isdigit():
        return False, "invalid_game_id"

    # MLB's canonical GUMBO game feed is /api/v1.1/, not /api/v1/.
    # Some older games do not expose a full game feed; use both official
    # smaller data endpoints as an alternative without inventing availability.
    try:
        response = session.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live",
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        actual = str((payload.get("gameData") or {}).get("game", {}).get("pk")
                     or payload.get("gamePk") or "")
        if actual != game_id:
            return False, "mismatched_game_id"
        live = payload.get("liveData") or {}
        teams = (live.get("boxscore") or {}).get("teams")
        plays = (live.get("plays") or {}).get("allPlays")
        if (isinstance(teams, dict) and
                all(team in teams for team in ("home", "away")) and
                isinstance(plays, list) and plays):
            return True, "verified_api"
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass

    # Fallback for game IDs without a complete GUMBO feed.
    try:
        base=f"https://statsapi.mlb.com/api/v1/game/{game_id}"
        box=session.get(base+"/boxscore",timeout=timeout)
        box.raise_for_status()
        box_data=box.json()
        teams=box_data.get("teams")
        if not isinstance(teams,dict) or not all(side in teams for side in ("away","home")):
            return False, "box_score_not_available"
        pbp=session.get(base+"/playByPlay",timeout=timeout)
        pbp.raise_for_status()
        plays=pbp.json().get("allPlays")
        if not isinstance(plays,list) or not plays:
            return False, "play_by_play_not_available"
        return True, "verified_api"
    except requests.HTTPError as exc:
        status=getattr(getattr(exc,"response",None),"status_code",None)
        return False, f"official_api_http_{status or 'error'}"
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return False, "official_api_unavailable"
