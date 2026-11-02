import hashlib
import unittest
from app.services.polymarket import JsonResponseCache


class ResponseCacheLimitsTests(unittest.TestCase):
    def test_byte_budget_and_recent_entries_survive_churn(self):
        cache=JsonResponseCache(max_bytes=1024,max_entries=256)
        for i in range(100):
            payload={'id':i,'values':[hashlib.sha256(f'{i}:{j}'.encode()).hexdigest() for j in range(8)]}
            cache.put(str(i),payload,now=100+i)
        status=cache.status(now=200)
        self.assertLessEqual(status['stored_bytes'],1024)
        self.assertLess(status['entries'],100)
        self.assertGreater(status['evictions'],0)
        self.assertEqual(cache.get('99',300,now=200)['id'],99)

    def test_lru_touch_and_oversized_response_bypass(self):
        cache=JsonResponseCache(max_entries=2)
        cache.put('a',{'value':1},now=100)
        cache.put('b',{'value':2},now=101)
        cache.get('a',100,now=102)
        cache.put('c',{'value':3},now=103)
        self.assertIsNone(cache.get('b',100,now=104))
        self.assertEqual(cache.get('a',100,now=104),{'value':1})
        cache.max_entry_bytes=64
        cache.put('large',{'payload':'x'*1000},now=105)
        self.assertIsNone(cache.get('large',100,now=106))
        self.assertEqual(cache.status(now=106)['skipped'],1)

    def test_expired_entries_removed_without_reading_their_keys(self):
        cache=JsonResponseCache()
        cache.put('old',{'value':1},now=10,retention_seconds=20)
        cache.put('new',{'value':2},now=25,retention_seconds=20)
        cache.prune(now=31)
        self.assertEqual(cache.status(now=31)['entries'],1)
        self.assertEqual(cache.status(now=31)['expired'],1)
        cache.prune(now=46)
        self.assertEqual(cache.status(now=46)['stored_bytes'],0)

    def test_cached_payload_cannot_be_mutated_by_consumers(self):
        cache=JsonResponseCache()
        original={'nested':[{'value':1}]}
        cache.put('entry',original,now=100)
        original['nested'][0]['value']=2
        first=cache.get('entry',10,now=101)
        first['nested'][0]['value']=3
        self.assertEqual(cache.get('entry',10,now=102),{'nested':[{'value':1}]})

    def test_decoded_budget_bounds_highly_compressible_payloads(self):
        cache=JsonResponseCache(max_bytes=1024**2)
        cache.max_decoded_bytes=4000
        for i in range(20):cache.put(str(i),{'value':'x'*1000},now=i)
        status=cache.status(now=20)
        self.assertLessEqual(status['decoded_json_bytes'],4000)
        self.assertLess(status['entries'],20)
