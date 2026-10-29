"""Sparse, versioned five-minute observations; missing bins are never zero-filled."""
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from .normalization import digest, now, timestamp
from .money import cash_sql


async def dirty(c, trades):
    bins = {(t['venue'], t['market_id'], t['token_id'] or t['outcome'],
             datetime.fromtimestamp((int(datetime.fromisoformat(t['event_time']).timestamp()) // 300 + 1) * 300,
                                    timezone.utc)) for t in trades}
    if bins:
        async with c.cursor() as cursor:
            await cursor.executemany('INSERT INTO surveillance_dirty_bins VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING', sorted(bins))


async def materialize(store, limit=2000):
    """Bound work per queue claim. Receipt time and materialization time are distinct."""
    count = 0
    async with store.connection() as c:
        # Only the single worker calls this; advisory lock also fences accidental callers.
        await c.execute('SELECT pg_advisory_xact_lock(81724005)')
        known_at = now()
        bins = await (await c.execute('''SELECT * FROM surveillance_dirty_bins WHERE bin_end<=%s
            ORDER BY bin_end LIMIT %s FOR UPDATE SKIP LOCKED''', (known_at, limit))).fetchall()
        for b in bins:
            key = (b['venue'], b['market_id'], b['outcome'], b['bin_end'])
            row = await (await c.execute(f'''SELECT count(*) AS fills,count(*) FILTER(WHERE {cash_sql()} IS NULL) AS unknown_cash_fills,
                COALESCE(sum((document->>'quantity')::numeric),0)::text AS shares,
                COALESCE(sum({cash_sql()}),0)::text AS cash,
                COALESCE(sum({cash_sql()})
                    FILTER(WHERE document->>'direction'='1' AND NOT COALESCE((document->>'is_block_trade')::boolean,false)),0)::text AS buy_cash,
                COALESCE(sum({cash_sql()})
                    FILTER(WHERE document->>'direction'='-1' AND NOT COALESCE((document->>'is_block_trade')::boolean,false)),0)::text AS sell_cash
                FROM surveillance_trades WHERE venue=%s AND market_id=%s
                AND COALESCE(NULLIF(document->>'token_id',''),outcome)=%s
                AND event_time>=%s-interval '5 minutes' AND event_time<%s AND received_at<=%s''',
                (*key, b['bin_end'], known_at))).fetchone()
            refs = await (await c.execute('''SELECT DISTINCT raw_id FROM surveillance_trades WHERE venue=%s AND market_id=%s
                AND COALESCE(NULLIF(document->>'token_id',''),outcome)=%s
                AND event_time>=%s-interval '5 minutes' AND event_time<%s AND received_at<=%s
                ORDER BY raw_id LIMIT 65''', (*key, b['bin_end'], known_at))).fetchall()
            # Expired source rows cannot overwrite a retained positive version with zero.
            if row['fills']:
                row.update(cash_complete=row['unknown_cash_fills']==0,aggregation_version='cash-v2',coverage='observed_trades; upstream completeness unknown', refs_complete=len(refs)<=64)
                raw_ids = [r['raw_id'] for r in refs[:64] if r['raw_id']]
                row['content_hash'] = digest([row, raw_ids])
                previous = await (await c.execute('''SELECT document FROM surveillance_aggregates WHERE
                    venue=%s AND market_id=%s AND outcome=%s AND bin_end=%s ORDER BY known_at DESC LIMIT 1''', key)).fetchone()
                if not previous or previous['document']['content_hash'] != row['content_hash']:
                    await c.execute('INSERT INTO surveillance_aggregates VALUES(%s,%s,%s,%s,%s,%s,%s)',
                                    (*key, known_at, Jsonb(row), raw_ids))
                    count += 1
            await c.execute('DELETE FROM surveillance_dirty_bins WHERE venue=%s AND market_id=%s AND outcome=%s AND bin_end=%s', key)
    return dict(processed_bins=len(bins), appended_versions=count, known_at=known_at)


async def read_bins(store, venue, market_id, start, end, as_of, limit=20000):
    rows = await store.fetch('''SELECT DISTINCT ON(outcome,bin_end) * FROM surveillance_aggregates
        WHERE venue=%s AND market_id=%s AND bin_end>%s AND bin_end<=%s AND known_at<=%s
        ORDER BY outcome,bin_end,known_at DESC LIMIT %s''', (venue,market_id,start,end,as_of,limit+1))
    if len(rows)>limit:
        raise ValueError('Aggregate query budget exceeded; shorten the interval')
    for row in rows:
        if venue=='kalshi' and row['document'].get('aggregation_version')!='cash-v2':
            row['document'].update(cash_complete=False,cash_basis='legacy_yes_quote; corrected version pending')
    return rows


async def record_walk(c, job, walk):
    if walk['upper_time'] < walk['lower_time']:
        return
    await c.execute('''INSERT INTO surveillance_walks VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING''', (digest([job['id'],walk]), job['venue'],job['payload']['market_id'],
        walk['lower_time'],walk['upper_time'],now(),walk['raw_ids'],walk['refs_complete'],walk.get('observed_trades',-1)))
