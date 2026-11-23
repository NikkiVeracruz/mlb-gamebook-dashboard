"""MLB game discovery must include every game on all three dates."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import monitor


class MLBThreeDayFeedTests(unittest.TestCase):
    def test_fetches_every_game_on_three_dates_with_unique_doubleheader_ids(self):
        days=[date(2026,7,1),date(2026,7,2),date(2026,7,3)]
        responses={
            d.isoformat():[
                {"gamePk":777000+i*10+j,
                 "teams":{"away":{"team":{"name":"Visitors"}},
                          "home":{"team":{"name":"Hosts"}}},
                 "status":{"detailedState":"Final" if i==0 else "Scheduled",
                           "abstractGameState":"Final" if i==0 else "Preview"}}
                for j in range(2 if i==1 else 1)]
            for i,d in enumerate(days)
        }
        class Response:
            def __init__(self,day):self.day=day
            def raise_for_status(self):pass
            def json(self):return {"dates":[{"games":responses[self.day]}]}
        class Session:
            def __init__(self):self.calls=[]
            def headers(self):return {}
            def get(self,url,params=None,timeout=None):
                self.calls.append(params["date"])
                return Response(params["date"])
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"feed.json"
            out.write_text(json.dumps({"games":[]}))
            session=Session()
            # The real session exposes a headers mapping.
            session.headers={}
            with patch.object(monitor,"OUT",out), \
                 patch.object(monitor,"three_days",return_value=days), \
                 patch.object(monitor,"archive_outgoing_games",return_value=0), \
                 patch.object(monitor,"scheduled_games_in_window",return_value=True), \
                 patch.object(monitor.requests,"Session",return_value=session):
                monitor.main()
            data=json.loads(out.read_text())
            self.assertEqual(data["window_dates"],[d.isoformat() for d in days])
            self.assertEqual(len(data["games"]),4)
            self.assertEqual(len({x["id"] for x in data["games"]}),4)
            self.assertEqual(session.calls,[d.isoformat() for d in days])
            self.assertEqual(sum(bool(x.get("box_url")) for x in data["games"]),1)


if __name__=="__main__":
    unittest.main()
