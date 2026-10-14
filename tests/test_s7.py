"""Owned-stack faults, real RocketMQ, read-only alarms and replay safety."""
import json,time,hashlib,concurrent.futures,sys,re
from stack_client import *

started=time.monotonic();checks=[];timings={}
def passed(name):
    checks.append(name);record('fault-progress',{'checks':checks,'timingsSeconds':timings});print('PASS',name,flush=True)
def ready():wait(lambda:call('GET','/health/order')[0]==200);wait(lambda:call('GET','/health/seckill')[0]==200)
def finish(p,label,start):
    o=wait(lambda:order(p));timings[label]=round(time.monotonic()-start,3);assert o['orderState']=='PENDING_PAYMENT';clean();return o
def replay_created(p,expected):
    code,value=buy(p)
    assert code==503 and value['code']=='ORDER_SERVICE_UNAVAILABLE',(code,value)
    assert order(p)['orderId']==expected['orderId']
def dlq():
    out=dc('exec','-T','broker','sh','mqadmin','topicStatus','-n','namesrv:9876','-t','%DLQ%mall_order_v1',check=False)
    return sum(int(parts[3]) for line in out.splitlines() if (parts:=line.split()) and parts[0]=='mall-stack-broker' and len(parts)>3 and parts[3].isdigit())
if '--dlq-only' not in sys.argv:
    ready();admin=login();users=fixture_users(20);a,s=activity(admin,20,'faults')
    assert reconcile()['status']=='CLEAN';passed('bounded read-only clean reconciliation')

    dc('stop','-t','2','relay');p=prepare(users[0],a,s);assert buy(p)[0]==202
    r=reconcile();assert r['status']=='IN_FLIGHT',r;record('in-flight',r)
    time.sleep(2);r=reconcile(1);assert r['status']=='ALERT' and any(x['code']=='AGED_RESERVATION' for x in r['alerts']);record('aged-alarm',r)
    stock=redis('HGET',f'seckill:{{{a}:{s}}}:ledger','stock');assert stock=='19'
    start=time.monotonic();start_service('relay');first=finish(p,'relayRestartSeconds',start);assert redis('HGET',f'seckill:{{{a}:{s}}}:ledger','stock')==stock
    passed('relay outage distinguishes in-flight/aged alarm and recovers without overselling')

    key=f'seckill:{{{a}:{s}}}:ledger';original=redis('HGET',key,'stock')
    redis('HSET',key,'stock',int(original)+1)
    try:
        r=reconcile();assert r['status']=='ALERT' and any(x['code']=='REDIS_STOCK_DRIFT' for x in r['alerts']);record('drift-alarm',r)
        assert redis('HGET',key,'stock')==str(int(original)+1),'Reconciliation must never repair stock'
    finally:redis('HSET',key,'stock',original)
    clean();passed('injected stock drift is reported; checker makes no writes')

    redis('RENAME',key,key+':owned-hold')
    try:
        r=reconcile();assert r['status']=='ALERT' and any(x['code']=='MISSING_LEDGER' for x in r['alerts']);record('missing-ledger',r)
        assert buy(p)[0]==404  # Existing public contract: absent activity ledger is NOT_FOUND.
    finally:redis('RENAME',key+':owned-hold',key)
    clean();passed('lost ledger refuses purchases and cannot reset durable inventory')

    p2=prepare(users[1],a,s);dc('stop','-t','1','order');assert buy(p2)[0]==202
    start=time.monotonic();start_service('order');second=finish(p2,'consumerRestartSeconds',start)
    replay_created(p2,second);passed('hard-bounded consumer stop restores queued order and replay is unique')

    p3=prepare(users[2],a,s);dc('stop','-t','1','broker');assert buy(p3)[0]==202
    assert reconcile()['status']=='IN_FLIGHT';start=time.monotonic();start_service('broker');finish(p3,'brokerRestartSeconds',start)
    passed('broker outage retains Redis reservation until official SDK recovery')

    p4=prepare(users[3],a,s);dc('stop','-t','1','mysql');assert buy(p4)[0]==202
    time.sleep(5);assert reconcile()['status']=='UNAVAILABLE'
    start=time.monotonic();start_service('mysql');finish(p4,'databaseRestartSeconds',start)
    passed('database outage is unavailable, not clean; durable order recovers')

    p5=prepare(users[4],a,s);dc('stop','-t','1','redis');assert buy(p5)[0]==503
    start_service('redis');wait(lambda:call('GET','/health/seckill')[0]==200);assert buy(p5)[0]==202;fifth=finish(p5,'redisRestartSeconds',time.monotonic())
    before=clean();dc('kill','-s','SIGKILL','redis');start_service('redis');ready();replay_created(p5,fifth)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        codes=list(pool.map(lambda _:call('GET',f'/api/seckill/info?activityId={a}&skuId={s}')[0],range(64)))
    assert codes==[200]*64,'Every worker must reconnect before any business write'
    after=clean();assert [(l['activityId'],l['redisAvailable']) for l in before['ledgers']]==[(l['activityId'],l['redisAvailable']) for l in after['ledgers']]
    passed('Redis unavailable returns unknown/503; AOF crash preserves reservation and replay')

    body={'orderId':first['orderId'],'idempotencyKey':str(uuid.uuid4())}
    assert call('POST','/api/order/pay',body,p['token'])[0]==200;assert call('POST','/api/order/pay',body,p['token'])[0]==200
    sql(f"UPDATE orders SET expires_at_ms=created_at_ms+1 WHERE id='{second['orderId']}'")
    wait(lambda:call('GET','/api/order/status?orderId='+second['orderId'],token=p2['token'])[1].get('orderState')=='CLOSED')
    clean();assert sql("SELECT COUNT(*) FROM payments WHERE status='SUCCEEDED'")=='1'
    passed('MOCK payment replay and autonomous close conserve stock after faults')
else:
    prior=json.loads((ROOT/'tests/reports/wsl/s7/fault-progress-before-resume.json').read_text())
    assert len(prior['checks'])==9
    checks.extend(prior['checks']);timings.update(prior['timingsSeconds'])
    ready();admin=login();users=fixture_users(20)

# Retain a request until real broker retries exhaust while DB is offline.
# Age only this owned fixture so the existing durable timeout fence can close it.
policy='{"type":"CUSTOMIZED","customizedRetryPolicy":{"next":[1000,2000,4000,8000,16000,30000,30000,30000]}}'
# Private two-retry policy; restore standard eight-retry policy before load.
dc('exec','-T','broker','sh','mqadmin','updateSubGroup','-n','namesrv:9876','-b','broker:10911','-g','mall_order_v1','-r','2','-p',policy)
dc('stop','-t','1','order');start_service('order');ready()
ad,sd=activity(admin,2,'dlq');pd=prepare(users[5],ad,sd);dc('stop','-t','2','relay')
assert buy(pd)[0]==202;kd=f'seckill:{{{ad}:{sd}}}:ledger'
reservation=json.loads(redis('HGET',kd,f'req:{pd["user"]}:{pd["requestId"]}'))
event=json.loads(redis('HGET',kd,'pending:'+reservation['reservationId']))
old=int(time.time()*1000)-1805000;reservation['createdAtMs']=str(old);event['createdAtMs']=str(old)
sql(f'UPDATE activities SET starts_at_ms={old-60000} WHERE id={ad}')
baseline=dlq();dc('stop','-t','1','mysql')
# Age after DB is stopped, otherwise the healthy recovery worker can legitimately
# terminate it before any message is sent and there will be nothing to enter DLQ.
redis('HSET',kd,'startsAtMs',old-60000,f'req:{pd["user"]}:{pd["requestId"]}',json.dumps(reservation),'pending:'+event['eventId'],json.dumps(event))
start_service('relay')
assert json.loads(dc('ps','-a','--format','json','mysql'))['State']=='exited','DB outage must stay injected while relay sends'
def target_in_dlq():
    if dlq()<=baseline:return False
    index=dc('exec','-T','broker','sh','mqadmin','queryMsgByKey','-n','namesrv:9876','-t','%DLQ%mall_order_v1','-k',event['eventId'],check=False)
    for line in index.splitlines():
        parts=line.split()
        if not parts or not re.fullmatch(r'[0-9A-Fa-f]{32,64}',parts[0]):continue
        body=dc('exec','-T','broker','sh','mqadmin','queryMsgById','-n','namesrv:9876','-t','%DLQ%mall_order_v1','-i',parts[0],'-f','UTF-8',check=False)
        if json.dumps(event) in body:return body
    return False
try:
    proof=wait(target_in_dlq,240)
    (ROOT/'tests/reports/wsl/s7/dlq-target.txt').write_text(proof)
finally:start_service('mysql')
ready();wait(lambda:call('GET',f'/api/order/status?activityId={ad}&skuId={sd}&requestId={pd["requestId"]}',token=pd['token'])[1].get('requestState')=='FAILED')
assert redis('HGET',kd,'stock')=='2'
assert sql(f'SELECT COUNT(*) FROM orders WHERE activity_id={ad}')=='0'
# A private quarantine marker proves this exact payload reached the handler;
# the recovery scheduler only replays RETRY, so it cannot resolve this marker.
raw=json.dumps(event);message_hash=hashlib.sha256(raw.encode()).hexdigest()
sql(f"INSERT INTO mq_failures(message_hash,payload,status,reason,updated_at_ms) VALUES('{message_hash}',CONVERT(X'{raw.encode().hex()}' USING utf8mb4),'QUARANTINED','LATE_TEST_MARKER',{int(time.time()*1000)}) ON DUPLICATE KEY UPDATE status='QUARANTINED',reason='LATE_TEST_MARKER'")
record('quarantine-alarm',reconcile())
# Replay the identical original event through the official producer; never change IDs.
dc('stop','-t','2','relay');redis('HSET',kd,'pending:'+event['eventId'],json.dumps(event))
confirmed=call('GET','/api/admin/recovery',token=admin)[1]['metrics']['confirmed']
dc('run','--rm','--no-deps','-T','relay','mall_relay_worker','--once',check=False)
redis('HSET',kd,'pending:'+event['eventId'],'');start_service('relay')
wait(lambda:call('GET','/api/admin/recovery',token=admin)[1]['metrics']['confirmed']>confirmed)
wait(lambda:sql(f"SELECT status FROM mq_failures WHERE message_hash='{message_hash}'")=='RESOLVED')
assert sql(f'SELECT COUNT(*) FROM orders WHERE activity_id={ad}')=='0';clean()
passed('real retry exhaustion/DLQ and durable termination fence reject late original event')
dc('exec','-T','broker','sh','mqadmin','updateSubGroup','-n','namesrv:9876','-b','broker:10911','-g','mall_order_v1','-r','8','-p',policy)

result={'date':'2026-10-14','checks':checks,'timingsSeconds':timings,'elapsedSecondsInThisInvocation':round(time.monotonic()-started,3),'resumedDlqOnly':'--dlq-only' in sys.argv,'dlqRetryLimit':2,'loadRetryLimit':8,'recoveryObservationDeadlineSeconds':180,'dlqObservationDeadlineSeconds':240,'final':clean(),'fixtures':'Owned S7 only: SQL users/Redis sessions/captcha digest/aged reservation/stock drift/quarantine marker proving late payload consumption; no public bypass routes'}
record('faults',result);print('PASS S7 faults',json.dumps(timings),flush=True)
