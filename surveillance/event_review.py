"""Post-disclosure review, independent of real-time anomaly scoring."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import ceil

from .aggregates import read_bins
from .investigations import ALTERNATIVES
from .normalization import digest, now, timestamp

WINDOWS = (3600, 21600, 86400, 259200, 604800)


def dt(value):
    return datetime.fromisoformat(timestamp(value))


async def enqueue_review(c, information_id, venue, as_of, contract_only=False):
    from psycopg.types.json import Jsonb
    payload = dict(information_id=information_id, as_of=timestamp(as_of),contract_only=contract_only)
    key = 'event_review:' + digest(payload)
    await c.execute("INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'event_review',%s,%s) ON CONFLICT DO NOTHING",
                    (key,venue,Jsonb(payload)))
    return key


async def family(store, venue, market_id, cutoff):
    source = await store.fetch('''SELECT document,raw_id FROM surveillance_markets WHERE venue=%s
        AND (id=%s OR condition_id=%s) AND observed_at<=%s LIMIT 1''', (venue,market_id,market_id,cutoff))
    event_ids = source[0]['document'].get('event_ids',[]) if source else []
    if len(event_ids)!=1:
        return 'contract:'+market_id, [market_id], [source[0]['raw_id']] if source else []
    siblings = await store.fetch('''SELECT document,raw_id FROM surveillance_markets WHERE venue=%s
        AND observed_at<=%s AND document->'event_ids' ? %s ORDER BY id LIMIT 21''', (venue,cutoff,event_ids[0]))
    if len(siblings)>20:
        raise ValueError('Event family exceeds 20 known contracts; narrow the review before scoring')
    return 'native-event:'+event_ids[0], sorted({r['document'].get('condition_id') or r['document']['id'] for r in siblings}), [r['raw_id'] for r in siblings]


async def build_review(store, information_id, as_of, contract_only=False):
    cutoff = dt(as_of)
    if cutoff > datetime.now(timezone.utc):
        raise ValueError('Review knowledge cutoff cannot be in the future')
    information = await store.fetch('SELECT * FROM surveillance_information WHERE id=%s AND first_seen_at<=%s', (information_id,cutoff))
    if not information:
        raise ValueError('Information unavailable at knowledge cutoff or expired')
    info = information[0]
    if not info['document'].get('publication_time_verified'):
        raise ValueError('Verified publication time is required for event review')
    anchor = dt(info['document']['published_at'])
    if anchor>cutoff:
        raise ValueError('Publication is later than knowledge cutoff')
    venue = info['venue']
    if contract_only:
        group,members,refs = 'contract:'+info['market_id'],[info['market_id']],[]
    else:
        group, members, refs = await family(store,venue,info['market_id'],cutoff)
    refs = set(refs + [info['raw_id']])
    results = []
    total_bins = 0
    for market_id in members:
        bins = await read_bins(store,venue,market_id,anchor-timedelta(days=7),anchor,cutoff)
        total_bins += len(bins)
        if total_bins>20000:
            raise ValueError('Event review exceeds 20000 aggregate bins; no partial report produced')
        walks = await store.fetch('''SELECT * FROM surveillance_walks WHERE venue=%s AND market_id=%s
            AND known_at<=%s AND upper_time>%s AND lower_time<%s ORDER BY known_at DESC LIMIT 257''',
            (venue,market_id,cutoff,anchor-timedelta(days=7),anchor))
        if len(walks)>256:
            # Seven days of minute polls can produce thousands of overlapping walks.
            # Merge intervals in SQL rather than silently truncating the observation history.
            ranges = await store.fetch('''SELECT range_agg(tstzrange(lower_time,upper_time,'[)')) AS ranges
                FROM surveillance_walks WHERE venue=%s AND market_id=%s AND known_at<=%s
                AND upper_time>%s AND lower_time<%s''', (venue,market_id,cutoff,anchor-timedelta(days=7),anchor))
            intervals = [(r.lower,r.upper) for r in (ranges[0]['ranges'] or [])]
        else:
            intervals = [(r['lower_time'],r['upper_time']) for r in walks]
        empty_ranges = await store.fetch('''SELECT range_agg(tstzrange(lower_time,upper_time,'[)')) AS ranges
            FROM surveillance_walks w WHERE venue=%s AND market_id=%s AND known_at<=%s
            AND upper_time>%s AND lower_time<%s AND observed_trades=0 AND refs_complete
            AND NOT EXISTS(SELECT 1 FROM unnest(w.raw_ids) rid WHERE NOT EXISTS(SELECT 1 FROM surveillance_raw r WHERE r.id=rid))''',
            (venue,market_id,cutoff,anchor-timedelta(days=7),anchor))
        empty_intervals = [(r.lower,r.upper) for r in (empty_ranges[0]['ranges'] or [])]
        # Coverage refers to completed API walks, not an exchange completeness guarantee.
        # Keep at most 64 proof receipts separately and flag any omitted references.
        walk_refs = await store.fetch('''SELECT DISTINCT unnest(raw_ids) AS id FROM surveillance_walks
            WHERE venue=%s AND market_id=%s AND known_at<=%s AND upper_time>%s AND lower_time<%s LIMIT 65''',
            (venue,market_id,cutoff,anchor-timedelta(days=7),anchor))
        refs.update(r['id'] for r in walk_refs[:64])
        dirty = await store.fetch('''SELECT DISTINCT bin_end FROM surveillance_dirty_bins WHERE venue=%s
            AND market_id=%s AND bin_end>%s AND bin_end<=%s LIMIT 2017''',
            (venue,market_id,anchor-timedelta(days=7),anchor))
        pending = {r['bin_end'] for r in dirty}
        # Only full bins enter totals. Fetch the two boundary fragments as-of cutoff.
        boundaries = []
        for seconds in WINDOWS:
            start = anchor-timedelta(seconds=seconds)
            first = datetime.fromtimestamp(ceil(start.timestamp()/300)*300, timezone.utc)
            last = datetime.fromtimestamp(int(anchor.timestamp())//300*300, timezone.utc)
            boundaries.append((seconds,start,first,last))
        # One indexed seven-day query for boundary fragments, bounded explicitly.
        fragments = await store.fetch('''SELECT document,raw_id,event_time FROM surveillance_trades
            WHERE venue=%s AND market_id=%s AND event_time>=%s AND event_time<%s AND received_at<=%s
            AND (event_time>=%s OR ''' + ' OR '.join('(event_time>=%s AND event_time<%s)' for _ in WINDOWS) + ''')
            ORDER BY event_time,id LIMIT 50001''',
            (venue,market_id,anchor-timedelta(days=7),anchor,cutoff,boundaries[0][3],
             *[v for _,start,first,_ in boundaries for v in (start,first)]))
        if len(fragments)>50000:
            raise ValueError('Review boundary exceeds 50000 trades; no partial report produced')
        source_times = await store.fetch('''SELECT min(event_time) AS first,max(event_time) AS last FROM surveillance_trades
            WHERE venue=%s AND market_id=%s AND event_time>=%s AND event_time<%s AND received_at<=%s''',
            (venue,market_id,anchor-timedelta(days=7),anchor,cutoff))
        outcomes = sorted({b['outcome'] for b in bins} | {r['document']['token_id'] or r['document']['outcome'] for r in fragments})
        window_results = []
        for seconds,start,first,last in boundaries:
            covered = sum(any(lo<=end-timedelta(minutes=5) and hi>=end for lo,hi in intervals)
                          for end in (first+timedelta(seconds=i*300) for i in range(1,max(0,int((last-first).total_seconds()/300))+1)))
            expected = max(0,int((last-first).total_seconds()/300))
            empty_bins = sum(any(lo<=end-timedelta(minutes=5) and hi>=end for lo,hi in empty_intervals)
                for end in (first+timedelta(seconds=i*300) for i in range(1,expected+1)))
            boundary_empty = (first==start or any(lo<=start and hi>=first for lo,hi in empty_intervals)) and (
                last==anchor or any(lo<=last and hi>=anchor for lo,hi in empty_intervals))
            stats = []
            for outcome in outcomes:
                selected = [b for b in bins if b['outcome']==outcome and first<b['bin_end']<=last]
                boundary = [r for r in fragments if (r['document']['token_id'] or r['document']['outcome'])==outcome
                            and start<=r['event_time']<anchor and (r['event_time']<first or r['event_time']>=last)]
                sums = {k:sum((Decimal(b['document'][k]) for b in selected),Decimal(0)) for k in ('cash','buy_cash','sell_cash')}
                for r in boundary:
                    t=r['document']; cash=Decimal(t['price'])*Decimal(t['quantity'])
                    sums['cash']+=cash
                    if not t.get('is_block_trade') and t.get('direction') in (1,-1):
                        sums['buy_cash' if t['direction']==1 else 'sell_cash']+=cash
                for b in selected:
                    refs.update(b['raw_ids'])
                refs.update(r['raw_id'] for r in boundary)
                stats.append(dict(outcome=outcome, fills=sum(b['document']['fills'] for b in selected)+len(boundary),
                    **{k:str(v) for k,v in sums.items()}, sampled_trade_bins=len(selected),
                    refs_complete=all(b['document']['refs_complete'] for b in selected)))
            has_fills = any(s['fills']>0 for s in stats)
            for statistic in stats:
                if not statistic['fills'] and (empty_bins<expected or not boundary_empty):
                    statistic.update(fills=None,cash=None,buy_cash=None,sell_cash=None)
            is_pending = any(first<end<=last for end in pending)
            if not has_fills and source_times[0]['last'] is not None and source_times[0]['last']>=start:
                is_pending = True
            window_results.append(dict(seconds=seconds,start=start.isoformat(),end=anchor.isoformat(),
                outcomes=stats, fully_sampled_api_bins=covered, empty_api_bins=empty_bins, expected_full_bins=expected,
                boundary_seconds=seconds-expected*300, boundary_empty_sample=boundary_empty, pending_aggregation=is_pending,
                observation='pending_aggregation' if is_pending else ('sampled_no_trades' if expected>0 and empty_bins==expected and boundary_empty and not has_fills else
                    ('observed_sample' if has_fills else 'unknown_or_expired'))))
        rules = await store.fetch('''SELECT document,hash,raw_id,observed_at FROM surveillance_rules
            WHERE venue=%s AND market_id=%s AND observed_at<=%s ORDER BY observed_at DESC LIMIT 1''', (venue,market_id,cutoff))
        if rules:
            refs.add(rules[0]['raw_id'])
        results.append(dict(market_id=market_id,windows=window_results,walk_refs_complete=len(walk_refs)<=64,
            rules=dict(document=rules[0]['document'],hash=rules[0]['hash'],raw_id=rules[0]['raw_id'],
                observed_at=rules[0]['observed_at'].isoformat()) if rules else None,
            rules_coverage='observed_snapshot' if rules else 'not_collected_or_expired'))
    if len(refs)>4096:
        raise ValueError('Review evidence exceeds 4096 receipts; no partial report produced')
    document = dict(id=digest(['event-review-v1',venue,group,anchor.isoformat()]),kind='event_review',
        venue=venue,market_id=info['market_id'],event_group=group,known_members=members,
        knowledge_cutoff=cutoff.isoformat(),publication_anchor=anchor.isoformat(),generated_at=now(),
        information=dict(info['document'],raw_id=info['raw_id']),contracts=results,
        anomaly_score=None,evidence_quality=None,investigation_priority=None,status='candidate',
        score_meaning='Descriptive post-disclosure review; uncalibrated scores unavailable; no insider probability',
        replay_raw_ids=sorted(r for r in refs if r),
        alternative_explanations=[dict(explanation=x,status='unverified') for x in ALTERNATIVES],
        limitations=['Only known native event membership; no cross-platform equivalence inferred',
            'Contract/outcome totals remain separate; family grouping is not a common exposure calculation',
            'Manual verified publication anchor is not proof of earliest public information',
            'Missing bins are unknown; completed REST walks are sampled observations',
            'Late historical intake is allowed only at its actual knowledge cutoff',
            'Walk evidence references bounded at 64 per contract; omissions explicitly flagged'])
    existing = await store.fetch('SELECT document FROM surveillance_cases WHERE id=%s', (document['id'],))
    notices = {n['id']:n for n in existing[0]['document'].get('information_sources',[]) if dt(n['received_at'])<=cutoff} if existing else {}
    notices[information_id] = dict(info['document'],id=information_id,raw_id=info['raw_id'],received_at=info['first_seen_at'].isoformat())
    document['information_sources'] = list(notices.values())
    if existing:
        document['replay_raw_ids'] = sorted(set(document['replay_raw_ids'] + [n['raw_id'] for n in notices.values()]))
    if len(notices)>50 or len(document['replay_raw_ids'])>4096:
        raise ValueError('Family dossier exceeds notice/evidence budget; narrow to a contract')
    # A family case has a stable primary contract even when a sibling triggers refresh.
    document['market_id']=members[0] if members else info['market_id']
    return await store.update_dossier(document)
