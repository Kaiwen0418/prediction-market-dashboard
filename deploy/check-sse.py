"""Check actual live SSE snapshots without logging the full market payload."""
import argparse
import json
import time
import urllib.parse
import urllib.request


def check(base, slug, count):
    url=base.rstrip('/')+'/api/live/stream?'+urllib.parse.urlencode({'slug':slug})
    started=time.monotonic()
    snapshots=[]
    with urllib.request.urlopen(url,timeout=15) as response:
        content_type=response.headers.get('content-type','')
        if not content_type.startswith('text/event-stream'):
            raise RuntimeError('Expected SSE content type')
        for raw in response:
            line=raw.decode().strip()
            if line.startswith('data: '):
                body=json.loads(line[6:])
                status=body.get('status',{})
                snapshots.append(dict(seconds=round(time.monotonic()-started,3),state=status.get('state'),
                    market_slug=status.get('marketSlug'),has_summary=bool(body.get('orderbookSummary'))))
                if len(snapshots)==count:
                    break
    if len(snapshots)!=count or any(s['state']!='connected' or s['market_slug']!=slug or not s['has_summary'] for s in snapshots):
        raise RuntimeError('SSE snapshots missing or not live for the requested market')
    return dict(base=base,content_type=content_type,snapshots=snapshots)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:18000')
    parser.add_argument('--slug',default='california-governor-election-2026')
    parser.add_argument('--count',type=int,default=3)
    args=parser.parse_args()
    if args.count<1:parser.error('Positive snapshot count required')
    print(json.dumps(check(args.base,args.slug,args.count),indent=2))
