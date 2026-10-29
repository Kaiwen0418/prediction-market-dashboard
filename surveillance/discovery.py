"""Stratified, event-diverse deep sampling; the global feed is independent."""
from bisect import insort
from collections import Counter
from datetime import datetime, timezone
import math
import re

from .normalization import digest

INFO = re.compile(r'\b(appoint(?:ed|ment|ments)?|nominat(?:e|ed|es|ion|ions|ing)|resign(?:s|ed|ation)?|fda|regulator[sy]?|regulatory|announce(?:ment|ments|s|d)?|award(?:s)?|policy|interest rates?|rate (?:cut|hike)|merger|acquisition|nobel|oscar|emmy|grammy|bafta|fed chair|cabinet|ceo|cfo|supreme court)\b', re.I)
CIVIC = re.compile(r'\b(election|president(?:ial)?|vote|ceasefire|war|military|house race|senate)\b',re.I)
SPORT = re.compile(r'\b(sports?|esports?|match|lineup|roster|injur(?:y|ies|ed)|coach|tournament|championship|soccer|football|basketball|baseball|tennis|hockey|chess)\b|\bvs\.?\s',re.I)
SPORT_SERIES = re.compile(r'^KX(NBA|NFL|NHL|MLB|NCAA|ATP|WTA|SOCCER|FIFA|EPL|UCL|CHESS|SB)',re.I)


def theme(m):
    text = ' '.join(str(m.get(k) or '') for k in ('title','category','tags','series_category'))
    # Elections containing "win" and macro statistics containing "nominal" are not appointments.
    if m.get('sports_market_type') or SPORT_SERIES.search(m['id']) or SPORT.search(text):
        return 'sports'
    if INFO.search(text) or (re.search(r'\bapproval\b',text,re.I) and not re.search(r'approval rating',text,re.I)):
        return 'information'
    if CIVIC.search(text):return 'civic'
    return 'other'


def tier(m):
    return {'information':0,'sports':0,'civic':1,'other':2}[theme(m)]


def event_key(m):
    ids = sorted(set(m.get('event_ids') or []))
    return (m['venue'], 'event', tuple(ids)) if ids else (m['venue'],'unmapped',m['id'])


def low_activity(m):
    # Native reported volume units differ across venues; not a cross-venue dollar ranking.
    value = m.get('volume_24h')
    if value is None and m.get('volume_reported') is False:return False
    return float(value if value is not None else m.get('volume',0)) <= 1000


class Pool:
    def __init__(self,size,per_event=2):
        self.size,self.per_event=size,per_event
        self.items=[]
        self.groups={}

    def add(self,key,m):
        if not self.size or (len(self.items)>=self.size and key>=self.items[-1][0]):
            return
        group=event_key(m)
        existing=self.groups.get(group,[])
        if len(existing)>=self.per_event:
            worst=max(existing)
            if key>=worst:return
            self.remove(worst)
        insort(self.items,(key,m))
        self.groups.setdefault(group,[]).append(key)
        if len(self.items)>self.size:self.remove(self.items[-1][0])

    def remove(self,key):
        for i,(k,m) in enumerate(self.items):
            if k==key:
                self.items.pop(i);group=event_key(m);self.groups[group].remove(k)
                if not self.groups[group]:del self.groups[group]
                return


class Selector:
    def __init__(self,budget=100,exploration_fraction=.2,at=None,end_grace_hours=6,scouts=None,previous=None):
        self.at=at or datetime.now(timezone.utc)
        self.budget=budget
        self.exploration=min(max(1,round(budget*exploration_fraction)),budget)
        self.end_grace_hours=end_grace_hours
        self.epoch=str(int(self.at.timestamp())//21600)
        self.scouts=scouts or {};self.previous=previous or set()
        self.unmapped=Pool(budget)
        self.pools={k:Pool(budget) for k in ('information','sports','civic','other','low','promotion')}
        self.counts=Counter();self.selection={}

    def rank(self,m):
        urgency=0
        if m.get('end_time'):
            try:
                hours=(datetime.fromisoformat(m['end_time'].replace('Z','+00:00'))-self.at).total_seconds()/3600
                urgency=1/(1+hours) if hours>=0 else -.2
            except (ValueError,TypeError):urgency=-.2
        key=m.get('condition_id') or m['id']
        activity=self.scouts.get(key,{})
        cash=float(activity.get('recent_cash') or 0);prior=float(activity.get('prior_cash') or 0)
        # Only triage priority: never an insider score or a calibrated anomaly statistic.
        change=min(1,max(0,math.log1p(cash)-math.log1p(prior))/5) if prior else 0
        boost=min(1,math.log1p(cash)/15)+change
        volume=m.get('volume_24h') if m.get('volume_24h') is not None else m.get('volume',0)
        return urgency+min(math.log1p(float(volume or 0))/100,1)+boost+(.25 if key in self.previous else 0)

    def add(self,m):
        if m['closed'] or m.get('settled') or m.get('is_combo') or not m.get('tradable',True) or (m['venue']=='polymarket' and not m.get('condition_id')):
            self.counts['ineligible']+=1;return
        if len(set(m.get('event_ids') or []))!=1:
            self.counts['unmapped']+=1
            self.unmapped.add((digest([self.epoch,m['venue'],m['id']]),m['id']),m)
            return
        group=theme(m);self.counts[group]+=1
        self.pools[group].add((-self.rank(m),m['id']),m)
        key=m.get('condition_id') or m['id']
        if key not in self.previous and float(self.scouts.get(key,{}).get('recent_cash') or 0)>=1000:
            self.pools['promotion'].add((tier(m),-self.rank(m),m['id']),m)
        if low_activity(m):
            self.counts['low_activity']+=1
            self.pools['low'].add((digest([self.epoch,m['venue'],m['id']]),m['id']),m)

    def result(self):
        chosen=[];ids=set();events=Counter();self.selection={}
        def take(pool,n,reason):
            for _,m in pool:
                if n<=0 or len(chosen)>=self.budget:break
                if m['id'] in ids or events[event_key(m)]>=2:continue
                chosen.append(m);ids.add(m['id']);events[event_key(m)]+=1;n-=1
                self.selection[m['id']]=dict(classifier='stratified-v2',theme=theme(m),reason=reason,low_activity=low_activity(m),
                    event_key=list(event_key(m)),ranking=self.rank(m),metadata_mapped=bool(m.get('event_ids')))
        take(self.pools['low'].items,self.exploration,'low_activity_exploration')
        take(self.pools['promotion'].items,max(1,round(self.budget*.1)),'wide_activity_promotion')
        remaining=self.budget-len(chosen)
        for name,weight in (('information',.4375),('sports',.375),('civic',.1875)):
            take(self.pools[name].items,round(remaining*weight),'stratum:'+name)
        fallback=sorted((item for name,pool in self.pools.items() if name not in ('low','promotion') for item in pool.items),key=lambda x:(tier(x[1]),x[0]))
        take(fallback,self.budget-len(chosen),'available_strata_fallback')
        return chosen


def select(markets,budget=100,exploration_fraction=.2,at=None):
    selector=Selector(budget,exploration_fraction,at)
    for m in markets:selector.add(m)
    return selector.result()
