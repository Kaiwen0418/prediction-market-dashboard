import unittest
from pathlib import Path
from surveillance.config import Settings
from surveillance.admission import slots


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.settings=Settings('unused',Path('/unused'))
        self.measured=dict(database_bytes=1024**3,database_used_bytes=1024**3,raw_bytes=0)

    def test_completed_market_count_does_not_limit_admission(self):
        self.assertEqual(slots(self.settings,self.measured,0,0)['slots'],2)
        self.assertEqual(slots(self.settings,self.measured,0,1)['slots'],1)
        self.assertEqual(slots(self.settings,self.measured,0,2)['slots'],0)

    def test_any_resource_can_stop_new_admission(self):
        self.assertEqual(slots(self.settings,dict(self.measured,raw_bytes=self.settings.raw_max_bytes),0,0)['slots'],0)
        self.assertEqual(slots(self.settings,dict(self.measured,database_bytes=self.settings.database_max_bytes),0,0)['slots'],0)
        self.assertEqual(slots(self.settings,self.measured,self.settings.research_tape_max_bytes,0)['slots'],0)
