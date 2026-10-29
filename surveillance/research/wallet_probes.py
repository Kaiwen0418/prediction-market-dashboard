"""Inspect a tape-selected wallet's history only through the first alert cutoff.

The wallet is selected from the alert window, never by later winnings or identity.
External identity links, wallet creation time and lifetime coverage are not inferred.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from .study import load_tape, request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy',choices=('automatic_cash_floor','research_buy_gate'),default='automatic_cash_floor')
    args=parser.parse_args()
    results=[]
    for case in json.loads(args.study.read_text())['results']:
        # Reported examples and same-event peers; temporal controls share wallets
        # and are not counted as independent people.
        if 'earlier' in case['name']:
            continue
        signal=case[args.policy]['first']
        if not signal:
            continue
        cutoff=datetime.fromisoformat(signal['as_of'])
        start=datetime.fromisoformat(signal['window_start'])
        tape=load_tape(args.data_dir/case['dataset'])
        amounts=defaultdict(float)
        for t in tape:
            dt=datetime.fromisoformat(t['event_time'])
            if not start<dt<=cutoff or t['outcome'].lower()!='yes' or not t.get('wallet'):
                continue
            # Inspect the side responsible for dominant flow; mixed windows use gross.
            if signal['flow_direction']=='buy' and t['direction']!=1:
                continue
            if signal['flow_direction']=='sell' and t['direction']!=-1:
                continue
            amounts[t['wallet']]+=float(t['price'])*float(t['quantity'])
        if not amounts:
            continue
        wallet=max(amounts,key=amounts.get)
        folder=args.data_dir/'wallet-probes'/args.policy/case['name'];folder.mkdir(parents=True,exist_ok=True)
        cursor=None;rows=[];receipts=[];seen=set()
        for i in range(5):
            params={'user':wallet,'start':1,'end':int(cutoff.timestamp()),'taker_only':'false','limit':1000}
            if cursor:params['cursor']=cursor
            url='https://data-api.polymarket.com/v2/trades?'+urlencode(params)
            body=request(url);p=folder/f'page-{i:02d}.json';p.write_bytes(body)
            d=json.loads(body)
            for row in d['data']:
                if row['proxy_wallet'].lower()!=wallet.lower() or row['timestamp']>cutoff.timestamp():
                    raise ValueError('Wallet response violates historical cutoff/filter')
            rows+=d['data'];receipts.append({'path':p.name,'url':url,'sha256':hashlib.sha256(body).hexdigest(),
                                           'received_at':datetime.now(timezone.utc).isoformat()})
            cursor=d['pagination'].get('next_cursor')
            if not cursor:break
            if cursor in seen:raise ValueError('Wallet cursor cycle')
            seen.add(cursor);time.sleep(.65)
        totals=defaultdict(float);events=defaultdict(float)
        for row in rows:
            # Gross cash turnover, explicitly not inventory or realized PnL.
            cash=row['size']*row['price'];totals[row['condition_id']]+=cash;events[row.get('event_slug') or '<unknown>']+=cash
        gross=sum(totals.values())
        first=min((r['timestamp'] for r in rows),default=None)
        result={'case':case['name'],'at_cutoff':cutoff.isoformat(),'wallet':wallet,
                'selection':f'Largest observed taker cash flow on dominant side of first {args.policy} alert',
                'window_wallet_cash':amounts[wallet],'rows':len(rows),'api_walk_complete':not bool(cursor),
                'distinct_markets':len(totals),'distinct_events':len(events),
                'earliest_indexed_trade_in_retrieved_history':datetime.fromtimestamp(first,timezone.utc).isoformat() if first else None,
                'visible_history_span_hours':(cutoff.timestamp()-first)/3600 if first else None,
                'largest_event_share_of_observed_gross_cash':min(1,max(events.values())/gross) if gross else None,
                'events':dict(events),'receipts':receipts,
                'limitations':['Retrospective receipt time; historical delivery unknown',
                  'Five-page cap; concentration is conditional on retrieved history if incomplete',
                  'Indexed first trade is not account creation or identity proof',
                  'Cash turnover is not position, profit or coordinated-wallet attribution']}
        (folder/'manifest.json').write_text(json.dumps(result,indent=2));results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('receipts','limitations','events')}),flush=True)
    args.output.write_text(json.dumps({'method':'Event-time retrospective probes at first alert, not current wallet history',
                                    'results':results},indent=2))


if __name__=='__main__':main()
