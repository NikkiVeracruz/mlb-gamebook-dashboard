"""MLB historical link auditing never alters game records or claims unverified links."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_mlb_links


class MLBLinkAuditTests(unittest.TestCase):
    def test_separate_report_tracks_checked_ids_not_archive_changes(self):
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/"archive.json"
            review=Path(d)/"review.json"
            games=[
                {"id":str(i),"date":"2026-06-02","status":"Final",
                 "box_url":f"https://www.mlb.com/gameday/{i}/box-score",
                 "plays_url":f"https://www.mlb.com/gameday/{i}/play-by-play"}
                for i in range(101,104)]
            archive.write_text(json.dumps({"games":games}))
            original=archive.read_text()
            with patch.object(audit_mlb_links,"review_game",
                              side_effect=lambda gid: (gid,"verified_api" if gid!="102" else
                                                           "needs_review:official_api_unavailable")):
                first=audit_mlb_links.audit(archive,review,limit=2)
                self.assertEqual(first["checked"],2)
                second=audit_mlb_links.audit(archive,review,limit=2)
                self.assertEqual(second["checked"],3)
            self.assertEqual(archive.read_text(),original)
            self.assertEqual(second["archived_games_with_links"],3)
            self.assertEqual(second["verified"],2)
            self.assertEqual(second["needs_review"],1)


if __name__=="__main__":
    unittest.main()
