"""Compare identical catalog fixtures in disposable SQL tables; never touches live rows."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from surveillance.normalization import market


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market-json',type=Path,required=True)
    parser.add_argument('--contracts',type=int,default=50000)
    parser.add_argument('--details',type=int,default=40)
    args=parser.parse_args()
    if args.contracts<1 or not 0<=args.details<=args.contracts:raise ValueError('Invalid sample size')
    body=args.market_json.read_bytes();source=json.loads(body)
    m=market('polymarket',source,datetime.now(timezone.utc).isoformat())
    index={k:v for k,v in m.items() if k not in ('rules','tokens')}
    detail={k:m[k] for k in ('venue','id','title','category','tags','rules','observed_at')}
    namespace='surveillance_bench_'+uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(os.environ['SURVEILLANCE_DATABASE_URL'],autocommit=True) as c:
        await c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(namespace)))
        try:
            for name,template in [('old_markets','surveillance_markets'),('new_markets','surveillance_markets'),
                                  ('old_rules','surveillance_rules'),('new_rules','surveillance_rules')]:
                await c.execute(sql.SQL('CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)').format(
                    sql.Identifier(namespace),sql.Identifier(name),sql.Identifier(template)))
            timings={}
            for mode,doc in [('old',m),('new',index)]:
                t=time.monotonic()
                await c.execute(sql.SQL("""INSERT INTO {}.{} SELECT 'polymarket',g::text,'c'||g::text,
                    %s::jsonb||jsonb_build_object('id',g::text,'condition_id','c'||g::text),now(),NULL
                    FROM generate_series(1,%s) g""").format(sql.Identifier(namespace),sql.Identifier(mode+'_markets')),
                    (Jsonb(doc),args.contracts))
                if mode=='old':
                    await c.execute(sql.SQL("""INSERT INTO {}.old_rules SELECT venue,condition_id,
                        document->>'rules_hash',document,observed_at,NULL FROM {}.old_markets""").format(
                        sql.Identifier(namespace),sql.Identifier(namespace)))
                else:
                    await c.execute(sql.SQL("""INSERT INTO {}.new_rules SELECT venue,condition_id,
                        document->>'rules_hash',%s::jsonb||jsonb_build_object('id',id),observed_at,NULL
                        FROM {}.new_markets ORDER BY id LIMIT %s""").format(sql.Identifier(namespace),sql.Identifier(namespace)),
                        (Jsonb(detail),args.details))
                timings[mode]=time.monotonic()-t
            sizes={}
            for name in ('old_markets','old_rules','new_markets','new_rules'):
                qualified=f'{namespace}.{name}'
                row=await (await c.execute('SELECT pg_total_relation_size(%s::regclass)',(qualified,))).fetchone()
                sizes[name]=row[0]
            old=sizes['old_markets']+sizes['old_rules'];new=sizes['new_markets']+sizes['new_rules']
            print(json.dumps({'contracts':args.contracts,'detailed_contracts_after':args.details,
                'fixture_sha256':hashlib.sha256(body).hexdigest(),'physical_bytes':sizes,
                'old_total_bytes':old,'new_total_bytes':new,'reduction_fraction':1-new/old,
                'sql_bulk_load_seconds':timings,
                'limits':'Repeated real rule fixture, equal SQL/index layout; not a production growth rate or worker throughput benchmark'},indent=2))
        finally:
            await c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(namespace)))

if __name__=='__main__':asyncio.run(main())
