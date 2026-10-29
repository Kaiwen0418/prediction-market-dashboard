"""Sampled coverage, never exchange completeness. Separate knowledge and event clocks."""
from datetime import datetime,timedelta


def merge(intervals):
    result=[]
    for lo,hi in sorted(intervals):
        if hi<=lo:continue
        if result and lo<=result[-1][1]:result[-1]=(result[-1][0],max(hi,result[-1][1]))
        else:result.append((lo,hi))
    return result


def covered(intervals,start,end):
    return any(lo<=start and hi>=end for lo,hi in intervals)


async def intervals(store,venue,market_id,start,end,known_at):
    # The receipt array and integrity flag must still be available. Do not use
    # legacy walks whose upper boundary was receipt time rather than feed head.
    rows=await store.fetch('''SELECT id,lower_time,upper_time FROM surveillance_observations o
        WHERE venue=%s AND (market_id=%s OR market_id IS NULL) AND lower_time<%s AND upper_time>%s
        AND known_at<=%s AND refs_complete
        ORDER BY lower_time LIMIT 20001''',(venue,market_id,end,start,known_at))
    if len(rows)>20000:raise ValueError('Observation interval budget exceeded; no partial coverage produced')
    return merge([(r['lower_time'],r['upper_time']) for r in rows]),[r['id'] for r in rows]


async def latest_cutoff(store,venue,knowledge_cutoff,market_id=None):
    rows=await store.fetch('''SELECT max(upper_time) AS head FROM surveillance_observations
        WHERE venue=%s AND (market_id IS NULL OR market_id=%s) AND known_at<=%s AND refs_complete''',(venue,market_id,knowledge_cutoff))
    head=rows[0]['head']
    return min(knowledge_cutoff,head).replace(second=0,microsecond=0) if head else knowledge_cutoff.replace(second=0,microsecond=0)
