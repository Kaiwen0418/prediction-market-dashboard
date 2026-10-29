from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from surveillance.research.study import load_tape,run_case
from surveillance.normalization import trade
from surveillance.tests.test_core import poly


class ResearchTests(unittest.TestCase):
    def test_frozen_tape_rejects_modified_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);body=json.dumps({'data':[poly()]}).encode()
            (root/'page.json').write_bytes(body)
            (root/'manifest.json').write_text(json.dumps({'condition_id':'c1','walk_reached_lower_boundary_or_end':True,
                'pages':[{'path':'page.json','sha256':hashlib.sha256(body).hexdigest(),'received_at':'2026-10-29T00:00:00+00:00'}]}))
            self.assertEqual(len(load_tape(root)),1)
            (root/'page.json').write_bytes(body+b' ')
            with self.assertRaisesRegex(ValueError,'checksum'):load_tape(root)

    def test_study_never_uses_post_cutoff_trade_or_future_outcome(self):
        at=datetime(2026,10,28,12,tzinfo=timezone.utc)
        rows=[]
        for i in range(12):
            dt=at-timedelta(seconds=90+i*60)
            rows.append(dict(trade('polymarket',dict(poly(),timestamp=int(dt.timestamp())),at.isoformat()),id=str(i)))
        dt=at-timedelta(hours=13)
        rows.insert(0,dict(trade('polymarket',dict(poly(),timestamp=int(dt.timestamp())),at.isoformat()),id='oldest'))
        case={'name':'test','role':'unknown_not_clean_negative','start':at.isoformat(),'end':(at+timedelta(minutes=1)).isoformat()}
        before=run_case(case,rows)
        future=dict(rows[-1],id='future',event_time=(at+timedelta(hours=1)).isoformat(),price='1',quantity='100000000')
        self.assertEqual(before,run_case(case,rows+[future]))

    def test_study_rejects_missing_baseline_boundary(self):
        at=datetime(2026,10,28,12,tzinfo=timezone.utc)
        row=dict(trade('polymarket',dict(poly(),timestamp=int(at.timestamp())),at.isoformat()),id='now')
        with self.assertRaisesRegex(ValueError,'13-hour'):
            run_case({'start':at.isoformat(),'end':(at+timedelta(minutes=1)).isoformat()},[row])
