#!/usr/bin/env python3
"""Independent S19 evidence checks; a smoke run cannot satisfy the full profile."""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from load_s19_journeys import LIMITS


def evaluate(d):
    checks = {}
    def finite(x):
        return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
    def count(x):
        return finite(x) and x>=0 and int(x)==x
    def latency(x):
        return isinstance(x,dict) and all(finite(x.get(p)) for p in ('p50','p95','p99')) and 0<=x['p50']<=x['p95']<=x['p99']
    def clean(r, expected):
        return (isinstance(r,dict) and r.get('status')=='CLEAN' and r.get('orders')==expected
                and r.get('readOnly') is True and r.get('alerts')==[]
                and r.get('outbox')==[] and r.get('mqFailures')==[]
                and isinstance(r.get('ledgers'),list) and len(r['ledgers'])==1)
    def ledger(r, initial, held):
        x=r['ledgers'][0]
        return (all(count(x.get(k)) for k in ('initial','held','activeOrders','dbAvailable','redisAvailable','inTransit','pendingSend'))
                and x['initial']==initial and x['held']==x['activeOrders']==held
                and x['dbAvailable']==x['redisAvailable']==initial-held
                and x['inTransit']==x['pendingSend']==0)
    p=d.get('profile',{})
    checks['completeFullProfile']=(d.get('complete') is True and d.get('smokeOnly') is False
        and p.get('durationSeconds')==1800 and p.get('backgroundReadQps')==15
        and p.get('journeys')==64 and p.get('naturalExpiryOrders')==16
        and p.get('paymentTtlMs')==900000 and p.get('realRegistrations')==8)
    elapsed=d.get('submissionSeconds')
    checks['measuredDurationAndReadRate']=(finite(elapsed) and elapsed+1/15+.02>=1800
        and d.get('submittedReadRequests')==27000 and 27000/elapsed>=15*.99)
    checks['all64JourneysObserved']=d.get('completedJourneys')==d.get('durableObservedCount')==64
    checks['noRequestOrJourneyErrors']=d.get('errors')==[] and 'failure' not in d
    api=d.get('mixedApi',{})
    required={'register':8,'login':64,'captcha_image':32,'captcha_accessible':32,'token':64,
              'buy':64,'buy_replay':8,'pay':48,'pay_replay':48}
    checks['allWriteRoutesAndCountsPresent']=all(api.get(k,{}).get('count')==v for k,v in required.items())
    checks['orderPollingPresent']=count(api.get('order_status',{}).get('count')) and api['order_status']['count']>=64
    reads=('catalog','catalog_filtered','detail','activity_info','orders','me')
    checks['allReadRoutesAndCountsPresent']=(all(count(api.get(k,{}).get('count')) and api[k]['count']>0 for k in reads)
        and sum(api[k]['count'] for k in reads)==27000)
    good=True
    for name,x in api.items():
        expected='201' if name=='register' else '202' if name=='buy' else '200'
        good=(good and name in LIMITS and count(x.get('count')) and x['count']>0
              and x.get('statuses')=={expected:x['count']} and latency(x) and x['p95']<=LIMITS[name])
    checks['perApiStatusAndLatencyTargets']=bool(api) and good
    x=d.get('durableOrderMs',{})
    checks['durableLatencyTargets']=latency(x) and x['p95']<=3000 and x['p99']<=8000
    checks['naturalExpiryObserved']=d.get('naturalClosedObserved')==16
    x=d.get('expiryToClosedObservedMs',{})
    checks['naturalExpiryObservationWithin60s']=latency(x) and x['p99']<=60000
    checks['paidClosedAndPaymentConservation']=(d.get('orderOutcomes')=={'CLOSED':16,'PAID':48}
        and d.get('paymentRows')==48
        and d.get('requestCounts')=={'rows':64,'distinctReservations':64,'distinctActivityUsers':64})
    reconciliations=d.get('reconciliations',[])
    checks['allMixedInventoryConservesStock']=(len(reconciliations)==3
        and sum(r.get('orders',0) for r in reconciliations)==64
        and len({r.get('activityId') for r in reconciliations})==3
        and all(clean(r,r.get('orders')) and ledger(r,64,16) for r in reconciliations))
    bursts=d.get('bursts',[])
    checks['bothBurstProfilesPresent']=isinstance(bursts,list) and len(bursts)==2 and [b.get('initialStock') for b in bursts]==[64,32]
    for stock in (64,32):
        found=[b for b in bursts if b.get('initialStock')==stock]
        passed=False
        if len(found)==1:
            b=found[0];r=b.get('reconciliation',{});api=b.get('buyApi',{})
            statuses={'202':stock, **({'409':64-stock} if stock<64 else {})}
            codes={'ACCEPTED':stock, **({'SOLD_OUT':64-stock} if stock<64 else {})}
            passed=(b.get('users')==64 and b.get('accepted')==stock and b.get('httpStatuses')==statuses
                and b.get('businessCodes')==codes and api.get('count')==64 and api.get('statuses')==statuses
                and latency(api) and clean(r,stock) and ledger(r,stock,stock))
        checks[f'burstStock{stock}ConservesStock']=passed
    return {'passed':all(checks.values()),'checks':checks,
            'failedChecks':[k for k,v in checks.items() if not v],
            'scope':'S19 specified local mixed API profile and 64-user burst correctness only; not production SLA.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        d=json.loads(args.report.read_text(encoding='utf-8-sig'))
        if not isinstance(d,dict):raise ValueError('Expected report object')
        result=evaluate(d)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,OSError,ZeroDivisionError) as e:
        result={'passed':False,'failedChecks':['invalidOrMissingEvidence'],'error':type(e).__name__}
    if args.output:args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
