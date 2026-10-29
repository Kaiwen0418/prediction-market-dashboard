"""Read-only warm endpoint probe; run with the project's Python dependencies."""
import argparse
import asyncio
from collections import Counter
import json
import statistics
import time
import httpx


async def run(base, requests, concurrency):
    results=[]
    async with httpx.AsyncClient(timeout=30) as client:
        for path in ('/health','/api/polymarket/market-context'):
            warm=await client.get(base+path)
            warm.raise_for_status()
            semaphore=asyncio.Semaphore(concurrency)
            async def call():
                async with semaphore:
                    started=time.perf_counter()
                    response=await client.get(base+path)
                    return response.status_code,(time.perf_counter()-started)*1000
            started=time.perf_counter()
            observations=await asyncio.gather(*(call() for _ in range(requests)))
            times=sorted(t for _,t in observations)
            results.append(dict(path=path,requests=requests,concurrency=concurrency,
                seconds=round(time.perf_counter()-started,3),
                status_counts=dict(Counter(str(s) for s,_ in observations)),
                p50_ms=round(statistics.median(times),2),p95_ms=round(times[min(len(times)-1,int(len(times)*.95))],2)))
    return dict(base=base,workload='Warm read-only API probes alongside live collectors; not a sustained load test',results=results)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--base',default='http://127.0.0.1:8000')
    p.add_argument('--requests',type=int,default=50)
    p.add_argument('--concurrency',type=int,default=10)
    args=p.parse_args()
    if min(args.requests,args.concurrency)<1:p.error('Positive workload sizes required')
    print(json.dumps(asyncio.run(run(args.base.rstrip('/'),args.requests,args.concurrency)),indent=2))
