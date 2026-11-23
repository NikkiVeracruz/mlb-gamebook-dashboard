"""2026 MLB category coverage, confirmed official API data, and safe reconciliation."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import mlb_policy as p
import reconcile_mlb_2026 as repair


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.urls = []
    def get(self, url, params=None, timeout=None):
        self.urls.append((url, params))
        if url.endswith("/feed/live"):
            return FakeResponse(self.payload)
        return FakeResponse({"dates": [
            {"date": "2026-07-14", "games": [
                {"gamePk": 123456, "gameType": "A",
                 "teams": {"away": {"team": {"name": "AL"}},
                           "home": {"team": {"name": "NL"}}},
                 "status": {"detailedState": "Final", "abstractGameState": "Final"}},
                {"gamePk": 234567, "gameType": "E",
                 "teams": {"away": {"team": {"name": "Visitors"}},
                           "home": {"team": {"name": "Hosts"}}},
                 "status": {"detailedState": "Scheduled", "abstractGameState": "Preview"}},
            ]}
        ]})


class MlbIntegrityTests(unittest.TestCase):
    def test_categories_cover_all_star_and_exhibition(self):
        self.assertIn("A",p.GAME_TYPES)
        self.assertIn("E",p.GAME_TYPES)
        self.assertEqual(p.game_category("A"), "all_star")
        self.assertEqual(p.game_category("E"), "exhibition")
        self.assertEqual(p.game_category("R"), "regular_season")

    def test_real_official_game_id_and_stat_fields_required(self):
        data={"gameData":{"game":{"pk":123456}},
              "liveData":{"boxscore":{"teams":{"home":{},"away":{}}},
                          "plays":{"allPlays":[{"event":"start"}]}}}
        valid,status=p.validate_game_data(FakeSession(data), "123456")
        self.assertTrue(valid)
        self.assertEqual(status,"verified_api")
        valid,status=p.validate_game_data(FakeSession(data), "999999")
        self.assertFalse(valid)
        self.assertEqual(status,"mismatched_game_id")
        missing={"gameData":{"game":{"pk":123456}},"liveData":{}}
        self.assertFalse(p.validate_game_data(FakeSession(missing),"123456")[0])

    def test_no_unknown_or_cross_game_url(self):
        urls=p.official_links(123456)
        self.assertEqual(urls["box_url"],"https://www.mlb.com/gameday/123456/box-score")
        self.assertEqual(urls["plays_url"],"https://www.mlb.com/gameday/123456/play-by-play")
        with self.assertRaises(ValueError):
            p.official_links("../other")

    def test_special_schedule_finds_all_star_and_exhibition(self):
        obj=FakeSession({"gameData":{"game":{"pk":123456}},
                         "liveData":{"boxscore":{"teams":{"home":{},"away":{}}},
                                     "plays":{"allPlays":[{"event":"start"}]}}})
        rows=repair.special_schedule(obj,date(2026,7,14),date(2026,7,14))
        self.assertEqual({g["game_type"] for g in rows},{"A","E"})
        self.assertEqual(len(rows),2)
        self.assertTrue(next(g for g in rows if g["game_type"]=="A")["link_verification"]=="verified_api")
        self.assertNotIn("box_url",next(g for g in rows if g["game_type"]=="E"))

    def test_reconcile_preserves_prior_records_and_existing_links(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Path(root)/"archive.json"
            report=Path(root)/"review.json"
            archive.write_text(json.dumps({"games":[{"id":"old","date":"2026-06-01",
                "label":"Known","box_url":"https://www.mlb.com/gameday/111111/box-score"}]}))
            obj=FakeSession({"gameData":{"game":{"pk":123456}},
                             "liveData":{"boxscore":{"teams":{"home":{},"away":{}}},
                                         "plays":{"allPlays":[{"event":"start"}]}}})
            result=repair.reconcile(archive,report,obj,start=date(2026,7,14),end=date(2026,7,14))
            self.assertEqual(len(result["new_archive_ids"]),2)
            saved={g["id"]:g for g in json.loads(archive.read_text())["games"]}
            self.assertIn("old",saved)
            self.assertIn("123456",saved)
            self.assertIn("234567",saved)
            self.assertEqual(saved["old"]["box_url"],
                             "https://www.mlb.com/gameday/111111/box-score")
            initial=archive.read_text()
            repair.reconcile(archive,report,obj,start=date(2026,7,14),end=date(2026,7,14))
            self.assertEqual(initial,archive.read_text())


if __name__ == "__main__":
    unittest.main()
