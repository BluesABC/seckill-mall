# 测试职责：客户端/代理/handler关联计时及TCP队列溢出诊断。
# 具体断言及fixture边界在本文件；通过范围以对应阶段报告为准，不自动代表生产上线。
"""Owned S7 burst diagnosis: private sessions/proofs, real HTTP/MQ/SQL/stock.

No registration/login capacity claim. Does not reset volumes or inventory.
"""
import argparse
import concurrent.futures as cf
from collections import Counter
from datetime import datetime, timezone
import hashlib
import fcntl
import http.client
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

from stack_client import ROOT, ENV, PROJECT, PORT, activity, clean, dc, fixture_users, login, order, sql, wait, call
from load_s19_journeys import accessible_answer


def prepare(user, aid, sku):
    code, challenge=call('GET',f'/api/seckill/captcha?activityId={aid}&skuId={sku}&mode=accessible',token=user[1])
    assert code==200, challenge
    request=str(uuid.uuid4())
    from shipping_fixture import prepare_shipping
    prepare_shipping(call,user[1],aid,sku,request)
    code, proof=call('POST','/api/seckill/token',{'activityId':aid,'skuId':sku,'requestId':request,
        'captchaId':challenge['captchaId'],'captchaAnswer':accessible_answer(challenge['challengeText'])},user[1])
    assert code==200, proof
    return {'token':user[1],'activity':aid,'sku':sku,'requestId':request,
            'body':{'activityId':aid,'skuId':sku,'requestId':request,
                    'activityToken':proof['activityToken'],'captchaToken':proof['captchaToken']}}


def quantiles(values):
    values = sorted(values)
    assert values
    return {f'p{p}': round(values[max(0, math.ceil(len(values)*p/100)-1)], 3) for p in (50,95,99)}


def inspect(service):
    return json.loads(subprocess.check_output(['docker','inspect',f'{PROJECT}-{service}-1'], text=True))[0]


def counters():
    lines = dc('exec','-T','seckill','cat','/proc/net/netstat').splitlines()
    result = {}
    for i in range(0,len(lines),2):
        keys, values = lines[i].split(), lines[i+1].split()
        if keys[0] == 'TcpExt:':
            result = {k:int(v) for k,v in zip(keys[1:], values[1:]) if k in ('ListenOverflows','ListenDrops','TCPSynRetrans')}
    assert len(result) == 3
    return result


def logs(service, since):
    result = subprocess.run(['docker','logs','--since',since,f'{PROJECT}-{service}-1'], capture_output=True,text=True,check=True)
    return (result.stdout+'\n'+result.stderr).splitlines()


def run_round(admin, users, stock, number, checkpoint):
    aid, sku = activity(admin,stock,f'S20-{time.time_ns()}')
    plans = []
    for user in users:
        plans.append(prepare(user,aid,sku))
        time.sleep(.1)  # Two preparation calls/user stay below the 40 r/s gateway rule.
    time.sleep(3)  # Drain preparation tokens; the actual 64-request burst fits burst=80.
    barrier = threading.Barrier(64)
    since = datetime.now(timezone.utc).isoformat()
    before = counters()
    def send(plan):
        client = http.client.HTTPConnection('127.0.0.1',PORT,timeout=20)
        barrier.wait(timeout=30)
        begin = time.monotonic()
        connected = None
        try:
            client.connect()
            connected = time.monotonic()
            client.request('POST','/api/seckill/buy',json.dumps(plan['body']),
                           {'Content-Type':'application/json','Authorization':'Bearer '+plan['token']})
            response = client.getresponse()
            raw=response.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = {'code':'NON_JSON_RESPONSE'}
            return {'requestId':plan['requestId'],'status':response.status,'code':body.get('code','ACCEPTED'),
                    'traceId':response.getheader('X-Trace-Id'),'clientConnectMs':(connected-begin)*1000,
                    'httpMs':(time.monotonic()-begin)*1000}
        except (OSError,http.client.HTTPException) as error:
            return {'requestId':plan['requestId'],'status':0,'code':'TRANSPORT_UNKNOWN',
                    'traceId':None,'clientConnectMs':None if connected is None else (connected-begin)*1000,
                    'httpMs':(time.monotonic()-begin)*1000,'transportError':type(error).__name__}
        finally:
            client.close()
    with cf.ThreadPoolExecutor(max_workers=64) as pool:
        rows = list(pool.map(send,plans))
    after = counters()
    checkpoint({'round':number,'activityId':aid,'stock':stock,'users':64,'rows':rows,
                'tcpDelta':{k:after[k]-before[k] for k in before},'complete':False})
    accepted = [p for p,r in zip(plans,rows) if r['status']==202]
    assert len(accepted)==stock
    assert all(r['status']==202 or (r['status']==409 and r['code']=='SOLD_OUT') for r in rows)
    wait(lambda:int(sql(f'SELECT COUNT(*) FROM orders WHERE activity_id={int(aid)}'))==stock)
    time.sleep(3)
    for plan in accepted:
        found = order(plan)
        assert found
        code, result = call('POST','/api/order/pay',{'orderId':found['orderId'],'idempotencyKey':plan['requestId']},plan['token'])
        assert code==200, (code,result)
        time.sleep(.1)
    reconciliation = clean(activity_id=aid,limit=100000)
    counts=sql(f'SELECT COUNT(*),SUM(status="PAID"),COUNT(DISTINCT user_id) FROM orders WHERE activity_id={int(aid)}').split('\t')
    outcomes=dict(zip(('orders','paid','distinctUsers'),map(int,counts)))
    outcomes['paymentRows']=int(sql(f'SELECT COUNT(*) FROM payments WHERE order_id IN (SELECT id FROM orders WHERE activity_id={int(aid)})'))
    outcomes['distinctReservations']=int(sql(f'SELECT COUNT(DISTINCT reservation_id) FROM seckill_requests WHERE activity_id={int(aid)}'))
    assert set(outcomes.values())=={stock}, outcomes
    handlers = {}
    for line in logs('seckill',since):
        try:
            value=json.loads(line)
        except ValueError:
            continue
        if value.get('path')=='/api/seckill/buy':handlers[value['traceId']]=value['rtUs']/1000
    upstream = {}
    for line in logs('gateway',since):
        try:
            value=json.loads(line)
        except ValueError:
            continue
        if value.get('uri')=='/api/seckill/buy':upstream[value['trace']]=value
    for row in rows:
        trace = row['traceId']
        assert trace in handlers and trace in upstream, 'Missing correlated timing evidence'
        row['handlerMs']=handlers[trace]
        row['upstreamConnectMs']=float(upstream[trace]['connect'])*1000
        row['upstreamResponseMs']=float(upstream[trace]['response'])*1000
        row['gatewayMs']=float(upstream[trace]['request'])*1000
    return {'round':number,'activityId':aid,'stock':stock,'users':64,
            'accepted':len(accepted),'soldOut':64-len(accepted),'rows':rows,'complete':True,
            'timings':{k:quantiles([r[k] for r in rows]) for k in
                       ('httpMs','clientConnectMs','upstreamConnectMs','upstreamResponseMs','gatewayMs','handlerMs')},
            'tcpDelta':{k:after[k]-before[k] for k in before},'reconciliation':reconciliation,'outcomes':outcomes}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    parser.add_argument('--stock',type=int,choices=(32,64),default=64)
    parser.add_argument('--workers',type=int,choices=(8,32),default=32)
    args=parser.parse_args()
    assert sys.platform=='linux' and re.fullmatch('[a-z0-9-]+',args.label)
    lock=(ROOT/'build/wsl/capacity.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(SystemExit(143)))
    target=ROOT/'tests/reports/wsl'/f's20-{args.label}.json'
    assert not target.exists(), 'Refuse overwriting evidence'
    assert PROJECT=='seckill-mall-s7' and ENV.resolve()==(ROOT/'deploy/.env.s7').resolve()
    gateway=inspect('gateway')
    assert int(gateway['NetworkSettings']['Ports']['80/tcp'][0]['HostPort'])==PORT
    initial=inspect('seckill')
    assert all(x['Config']['Labels']['com.docker.compose.project']==PROJECT for x in (initial,gateway))
    env=dict(x.split('=',1) for x in initial['Config']['Env'] if '=' in x)
    previous={k:env[k] for k in ('MALL_HTTP_WORKERS','MALL_HTTP_QUEUE')}
    config=ROOT/'build/wsl/s7-nginx.conf'
    original=config.read_bytes()
    old="log_format mall '$remote_addr $request_method $uri $status $request_time';"
    new='log_format mall escape=json \'{"uri":"$uri","status":"$status","trace":"$upstream_http_x_trace_id","request":"$request_time","connect":"$upstream_connect_time","response":"$upstream_response_time"}\';'
    assert original.decode().count(old)==1
    report={'profile':'s20-burst-diagnostic','gitBase':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'workers':args.workers,'queue':128,'rounds':[],'complete':False,
            'previousConfiguration':previous,
            'fixture':'64 private SQL users/Redis sessions; real accessible captcha/token exchange; real HTTP/MQ/SQL/mock payment',
            'sourceSha256':hashlib.sha256((ROOT/'src/seckill/service.cpp').read_bytes()).hexdigest()}
    def save():
        raw=ROOT/'build/wsl'/f's20-{args.label}-checkpoint.json'
        raw_temp=raw.with_suffix('.tmp')
        raw_temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        raw_temp.replace(raw)
        public=json.loads(json.dumps(report))
        for item in public['rounds']:
            item['httpStatuses']=dict(Counter(str(row['status']) for row in item['rows']))
            for row in item['rows']:
                row.pop('requestId',None)
                row.pop('traceId',None)
                for key,value in row.items():
                    if key.endswith('Ms') and isinstance(value,(int,float)):
                        row[key]=round(value,3)
        temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(target)
    try:
        config.write_bytes(original.replace(old.encode(),new.encode()))
        dc('exec','-T','gateway','nginx','-t')
        dc('exec','-T','gateway','nginx','-s','reload')
        os.environ.update(MALL_HTTP_WORKERS=str(args.workers),MALL_HTTP_QUEUE='128')
        dc('up','-d','--no-deps','--force-recreate','--wait','seckill')
        wait(lambda:call('GET','/health/seckill')[0]==200)
        time.sleep(2)  # Existing Nginx workers drain before timing begins.
        runtime=inspect('seckill')
        applied=dict(x.split('=',1) for x in runtime['Config']['Env'] if '=' in x)
        assert applied['MALL_HTTP_WORKERS']==str(args.workers) and applied['MALL_HTTP_QUEUE']=='128'
        order_env=dict(x.split('=',1) for x in inspect('order')['Config']['Env'] if '=' in x)
        assert order_env['ORDER_PAYMENT_TTL_MS']=='900000'
        report['imageId']=runtime['Image']
        startup='\n'.join(logs('seckill','1970-01-01T00:00:00Z'))
        match=re.search(r'listenBacklog=(\d+)',startup)
        report['compiledListenBacklog']=int(match.group(1)) if match else None
        report['kernelSomaxconn']=int(dc('exec','-T','seckill','cat','/proc/sys/net/core/somaxconn').strip())
        report['nginxConfigSha256']=hashlib.sha256(original).hexdigest()
        report['orderPaymentTtlMs']=900000
        report['dockerHost']=json.loads(subprocess.check_output(['docker','info','--format',
            '{"cpus":{{.NCPU}},"memoryBytes":{{.MemTotal}}}'],text=True))
        report['startedUtc']=datetime.now(timezone.utc).isoformat()
        report['sourceMount']=str(ROOT)
        report['kernel']=subprocess.check_output(['uname','-r'],text=True).strip()
        admin=login();users=fixture_users(64)
        for number in range(1,4):
            def checkpoint(value):
                report['rounds'].append(value)
                save()
            result=run_round(admin,users,args.stock,number,checkpoint)
            report['rounds'][-1]=result
            save()
            print(json.dumps({'round':number,'timings':report['rounds'][-1]['timings'],'tcp':report['rounds'][-1]['tcpDelta']}),flush=True)
        report['complete']=True
    except BaseException as error:
        report['failure']={'type':type(error).__name__,'message':str(error)[:300]}
        raise
    finally:
        restore_errors=[]
        try:
            config.write_bytes(original)
            dc('exec','-T','gateway','nginx','-t')
            dc('exec','-T','gateway','nginx','-s','reload')
        except Exception as error:
            restore_errors.append(type(error).__name__+': gateway restore failed')
        try:
            os.environ.update(previous)
            dc('up','-d','--no-deps','--force-recreate','--wait','seckill')
            wait(lambda:call('GET','/health/seckill')[0]==200)
            actual=dict(x.split('=',1) for x in inspect('seckill')['Config']['Env'] if '=' in x)
            assert all(actual[k]==v for k,v in previous.items())
            report['restoredWorkers']=actual['MALL_HTTP_WORKERS']
            report['restoredQueue']=actual['MALL_HTTP_QUEUE']
        except Exception as error:
            restore_errors.append(type(error).__name__+': service restore failed')
        report['nginxConfigRestored']=config.read_bytes()==original
        report['restoreErrors']=restore_errors
        save()
        if restore_errors:
            raise RuntimeError('; '.join(restore_errors))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
