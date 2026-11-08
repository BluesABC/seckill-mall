#!/usr/bin/env python3
# 职责：独立复核三轮瞬时竞争。成功请求与全响应均检查P95，防止快速售罄拒绝掩盖成功请求长尾。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
"""Check S20 three-round evidence without trusting a passed declaration."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def evaluate(data):
    def integer(value):
        return type(value) is int and value >= 0
    def finite(value):
        return type(value) in (float,int) and math.isfinite(value) and value >= 0
    previous=data.get('previousConfiguration',{'MALL_HTTP_WORKERS':'8','MALL_HTTP_QUEUE':'128'})
    checks={
        'completeThreeRounds':data.get('complete') is True and len(data.get('rounds',[]))==3,
        'profile':data.get('profile')=='s20-burst-diagnostic' and data.get('workers') in (8,32) and data.get('queue')==128,
        'compiledBacklog':data.get('compiledListenBacklog')==128,
        'runtimeRestored':data.get('nginxConfigRestored') is True and isinstance(previous,dict)
            and isinstance(previous.get('MALL_HTTP_WORKERS'),str)
            and data.get('restoredWorkers')==previous.get('MALL_HTTP_WORKERS')
            and data.get('restoredQueue')==previous.get('MALL_HTTP_QUEUE') and data.get('restoreErrors')==[],
    }
    for index, item in enumerate(data.get('rounds',[])):
        name=f'round{index+1}'
        rows=item.get('rows',[]);stock=item.get('stock')
        expected=Counter({'202':stock,'409':64-stock}) if stock in (32,64) else Counter()
        expected=+expected
        actual=Counter(str(row.get('status')) for row in rows)
        checks[name+'Counts']=item.get('complete') is True and stock in (32,64) and len(rows)==64 and actual==expected and item.get('accepted')==stock
        checks[name+'Outcomes']=all(row.get('status')==202 or (row.get('status')==409 and row.get('code')=='SOLD_OUT') for row in rows)
        checks[name+'UniquePaidOrders']=all(item.get('outcomes',{}).get(key)==stock for key in
            ('orders','paid','distinctUsers','paymentRows','distinctReservations'))
        fields=('httpMs','clientConnectMs','upstreamConnectMs','upstreamResponseMs','gatewayMs','handlerMs')
        valid=len(rows)==64 and all(all(finite(row.get(key)) for key in fields) for row in rows)
        checks[name+'CorrelatedTimings']=valid
        accepted=[row['httpMs'] for row in rows if row.get('status')==202] if valid else []
        checks[name+'Latency']=valid and bool(accepted) and sorted(row['httpMs'] for row in rows)[math.ceil(64*.95)-1]<=500 \
            and sorted(accepted)[math.ceil(len(accepted)*.95)-1]<=500
        delta=item.get('tcpDelta',{})
        checks[name+'NoListenOverflow']=all(integer(delta.get(key)) and delta[key]==0 for key in ('ListenDrops','ListenOverflows'))
        result=item.get('reconciliation',{});ledgers=result.get('ledgers',[])
        checks[name+'CleanStock']=result.get('status')=='CLEAN' and result.get('readOnly') is True and result.get('orders')==stock and len(ledgers)==1 and all(
            all(integer(ledger.get(key)) for key in ('initial','dbAvailable','redisAvailable','held','activeOrders','inTransit','pendingSend'))
            and ledger['initial']==stock==ledger['held']==ledger['activeOrders']
            and ledger['dbAvailable']==ledger['redisAvailable']==ledger['inTransit']==ledger['pendingSend']==0 for ledger in ledgers)
    return {'passed':bool(checks) and all(checks.values()),'checks':checks}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=evaluate(json.loads(args.report.read_text(encoding='utf-8')))
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(text+'\n',encoding='utf-8')
    print(text)
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
