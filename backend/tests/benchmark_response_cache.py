"""Synthetic response churn probe; no upstream requests and no running-app mutation."""
import hashlib,json,resource,sys,time
from app.services.polymarket import JsonResponseCache


def deep_bytes(value):
    seen=set();todo=[value];total=0
    while todo:
        obj=todo.pop()
        if id(obj) in seen:continue
        seen.add(id(obj));total+=sys.getsizeof(obj)
        if isinstance(obj,dict):todo.extend(obj.keys());todo.extend(obj.values())
        elif isinstance(obj,(list,tuple)):todo.extend(obj)
    return total


def main():
    payload=[dict(id=i,question='Example market '+str(i),description=hashlib.sha256(str(i).encode()).hexdigest()*2,
        prices=[.2,.8],outcomes=['Yes','No']) for i in range(1000)]
    raw=json.dumps(payload).encode();fixture_bytes=deep_bytes(json.loads(raw));cache=JsonResponseCache()
    before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;start=time.monotonic()
    for i in range(1200):cache.put('synthetic/'+str(i),json.loads(raw),now=i/10)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps(dict(fixture_json_bytes=len(raw),fixture_python_bytes=fixture_bytes,
        old_2048_independent_payload_projection_bytes=fixture_bytes*2048,
        requests=1200,seconds=time.monotonic()-start,rss_before_kib=before,rss_peak_kib=peak,
        cache=cache.status(now=120),caveat='Synthetic churn, not a live-process heap profile; compressed bytes exclude interpreter/request working memory'),indent=2))


if __name__=='__main__':main()
