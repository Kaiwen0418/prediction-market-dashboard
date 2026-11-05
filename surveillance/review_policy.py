"""Transparent investigation budget exclusions; discovery still records markets."""
import re

VERSION = 'review-scope-v2'
ASSETS = re.compile(r'\b(bitcoin|btc|ethereum|eth|solana|sol|dogecoin|xrp|crypto|stock|share price|forex|exchange rate|s&p|nasdaq|dow jones|spx|tesla|tsla|nvidia|nvda|aapl|apple|gold|silver|crude oil|brent|eur/usd|usd/jpy)\b',re.I)
PRICE = re.compile(r'\b(above|below|between|over|under|reach|hit|close|closing|price|up or down|up/down|higher|lower|rise|fall|increase|decrease)\b',re.I)
PRICE_SERIES = re.compile(r'^KX(BTC|ETH|SOL|XRP|DOGE|INX|NASDAQ|SPX|FOREX|GOLD|SILVER|WTI|BRENT)(?:[A-Z0-9]*-)',re.I)
FINANCIAL_CATEGORIES = {'crypto','cryptocurrency','stocks','equities','forex','indices','commodities'}


def evaluate(market):
    from decimal import Decimal
    known_zero = market.get('volume_reported') is True and Decimal(str(market.get('volume') or '0')) == 0
    if known_zero:
        return dict(version=VERSION,eligible=False,reason='reported_zero_activity',basis='explicit_source_volume')
    title = market.get('title') or ''
    category = str(market.get('category') or '').lower()
    financial = bool(ASSETS.search(title)) or category in FINANCIAL_CATEGORIES
    price = bool(PRICE.search(title))
    excluded = bool(PRICE_SERIES.search(market.get('id',''))) or financial and price
    return dict(version=VERSION,eligible=not excluded,
        reason='continuous_asset_price' if excluded else 'discrete_event_or_unclassified',
        basis='native_series' if PRICE_SERIES.search(market.get('id','')) else 'title_and_category')


async def exclude(c, review_id, policy):
    from psycopg.types.json import Jsonb
    await c.execute("UPDATE surveillance_retrospectives SET status='excluded',document=document||%s WHERE id=%s",
                    (Jsonb(dict(review_policy=policy)),review_id))
    await c.execute("UPDATE surveillance_jobs SET enabled=false WHERE id=%s AND enabled",('retrospective:'+review_id,))


async def sweep(c, limit=100):
    rows = await (await c.execute("""SELECT id,document->'market' AS market FROM surveillance_retrospectives
        WHERE status IN ('pending','collecting','analyzing','complete_observed','complete_with_gaps') AND document->'review_policy'->>'version' IS DISTINCT FROM %s
        ORDER BY known_at,id LIMIT %s""",(VERSION,limit))).fetchall()
    from psycopg.types.json import Jsonb
    removed = 0
    for row in rows:
        policy = evaluate(row['market'])
        if not policy['eligible']:
            await exclude(c,row['id'],policy)
            removed += 1
        else:
            await c.execute('UPDATE surveillance_retrospectives SET document=document||%s WHERE id=%s',
                            (Jsonb(dict(review_policy=policy)),row['id']))
    return dict(checked=len(rows),excluded=removed,version=VERSION)
