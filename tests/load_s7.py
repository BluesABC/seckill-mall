"""WSL stdlib HTTP load driver, real authenticated buy/MQ/MySQL pipeline."""
import collections,concurrent.futures,json,math,platform,subprocess,threading,time,sys
from stack_client import *

def quantiles(values):
    ordered=sorted(values)
    return {str(p):round(ordered[min(len(ordered)-1,math.ceil(len(ordered)*p/100)-1)],3) if ordered else None for p in (50,95,99)}
def global_status():
    return sql("SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_row_lock_waits','Innodb_row_lock_time','Threads_connected','Threads_running')")
samples=[];stop=threading.Event()
def monitor():
    while not stop.is_set():
        result=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}']+[PROJECT+'-'+s+'-1' for s in ('gateway','seckill','relay','order','redis','mysql','broker')],text=True,capture_output=True,timeout=15)
        samples.append({'atMs':int(time.time()*1000),'containers':[json.loads(s) for s in result.stdout.splitlines()]})
        stop.wait(2)
admin=login();results=[];start_status=global_status();thread=threading.Thread(target=monitor,daemon=True);thread.start()
def campaign(name,n,concurrency,stocks,rate=0,pause_relay=False,cold_cpp=False):
    groups=[activity(admin,v,name+'-'+str(i)) for i,v in enumerate(stocks)]
    users=fixture_users(n)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        plans=list(pool.map(lambda item:prepare(item[1],*groups[item[0]%len(groups)]),enumerate(users)))
    if pause_relay:dc('stop','-t','2','relay')
    if cold_cpp:
        dc('restart','seckill');wait(lambda:call('GET','/health/seckill')[0]==200)
    db_before=global_status();begun=time.monotonic();wall=int(time.time()*1000)
    def send(item):
        i,p=item
        if rate:time.sleep(max(0,begun+i/rate-time.monotonic()))
        request_wall=int(time.time()*1000);start=time.monotonic()
        try:code,value=buy(p)
        except OSError:code,value=0,{'code':'TRANSPORT_UNKNOWN'}
        return {'requestId':p['requestId'],'user':p['user'],'activity':p['activity'],'sku':p['sku'],'status':code,'code':value.get('code','ACCEPTED' if code==202 else 'REPLAY' if code==200 else 'UNKNOWN'),'latencyMs':(time.monotonic()-start)*1000,'startedAtMs':request_wall}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:raw=list(pool.map(send,enumerate(plans)))
    ingress=time.monotonic()-begun;ids=','.join(a for a,s in groups)
    pending_before_resume=None
    if pause_relay:
        a,s=groups[0];pending_before_resume=int(redis('HGET',f'seckill:{{{a}:{s}}}:ledger','pendingCount'))
        start_service('relay')
        assert pending_before_resume==128
        assert sum(r['code']=='BACKPRESSURE' for r in raw)==n-128
    def settled():
        report=reconcile()
        return report if report['status']=='CLEAN' else None
    final=wait(settled,180)
    rows=sql(f'SELECT r.request_id,o.created_at_ms,o.status FROM orders o JOIN seckill_requests r ON r.reservation_id=o.reservation_id WHERE o.activity_id IN ({ids})').splitlines()
    persisted={p[0]:(int(p[1]),p[2]) for row in rows if len(p:=row.split('\t'))==3}
    ledger_maps={a:json.loads(dc('exec','-T','redis','redis-cli','--json','HGETALL',f'seckill:{{{a}:{s}}}:ledger')) for a,s in groups}
    # Redis CLI --json HGETALL may encode a flat array on RESP2 versions.
    for a,h in list(ledger_maps.items()):
        if isinstance(h,list):ledger_maps[a]=dict(zip(h[::2],h[1::2]))
    accepted=[]
    for r in raw:
        req=ledger_maps[r['activity']].get(f'req:{r["user"]}:{r["requestId"]}')
        r['reservationAccepted']=bool(req)
        if req:
            accepted.append(r)
            assert r['requestId'] in persisted,'Accepted reservation failed to become an order'
            r['orderLatencyMs']=max(0,persisted[r['requestId']][0]-r['startedAtMs'])
    assert len(persisted)==len(accepted)
    assert len(persisted)<=sum(stocks)
    assert all(v[1]=='PENDING_PAYMENT' for v in persisted.values())
    assert all(r['status'] in (202,409,429) or (r['status']==503 and r['code']=='BACKPRESSURE') for r in raw),collections.Counter((r['status'],r['code']) for r in raw)
    ended=max((v[0] for v in persisted.values()),default=wall)
    result={'name':name,'startedAtMs':wall,'lastPersistenceAtMs':ended,'pendingBeforeRelayResume':pending_before_resume,'users':n,'stock':stocks,'activities':len(groups),'concurrency':concurrency,'offeredRate':rate or 'closed-loop burst','ingressSeconds':round(ingress,3),'ingressQps':round(n/ingress,3),'accepted':len(accepted),'acceptedQps':round(len(accepted)/ingress,3),'persisted':len(persisted),'persistenceWindowSeconds':round(max(.001,(ended-wall)/1000),3),'persistenceTps':round(len(persisted)/max(.001,(ended-wall)/1000),3),'responseStatus':dict(collections.Counter(str(r['status']) for r in raw)),'businessCode':dict(collections.Counter(r['code'] for r in raw)),'httpLatencyMs':quantiles([r['latencyMs'] for r in raw]),'orderLatencyMs':quantiles([r['orderLatencyMs'] for r in accepted]),'finalReconciliation':final['status'],'raw':raw}
    result['coldCppProcess']=cold_cpp;result['storageAndMqCaches']='warm'
    result['mysqlStatusBefore']=db_before;result['mysqlStatusAfter']=global_status()
    results.append(result);record('load-progress',results)
    print('PASS load',name,'accepted',len(accepted),'persisted',len(persisted),'ingressQps',result['ingressQps'],'orderP95Ms',result['orderLatencyMs']['95'],flush=True)
finalize_only='--finalize-only' in sys.argv
if finalize_only:
    results=json.loads((ROOT/'tests/reports/wsl/s7/load-progress.json').read_text())
    before_db_restart=global_status()
    # Recover the database-outage evidence from the owned fixture activity.
    outage=sql("SELECT a.id,COUNT(o.id) FROM activities a JOIN activity_stock s ON s.activity_id=a.id LEFT JOIN orders o ON o.activity_id=a.id WHERE a.name='db-outage-burst' GROUP BY a.id ORDER BY a.id DESC LIMIT 1")
    parts=outage.split('\t')
    assert len(parts)==2 and int(parts[1])==48,('database outage fixture not reconciled',outage)
    results.append({'name':'db-outage-burst','activityId':int(parts[0]),'accepted':48,'persisted':int(parts[1]),'concurrency':32,'recoveredOrderCount':int(parts[1]),'finalReconciliation':clean()['status']})
    # Keep the production policy's exact limit_req directive and location, but
    # return locally during the isolated gate probe so the app backend cannot
    # become the limiting factor. Restore and reload the shipped config after.
    standard=(ROOT/'deploy/nginx/nginx.conf').read_text()
    shipped='location ^~ /api/seckill/ { limit_req zone=api_per_ip burst=80 nodelay; include /etc/nginx/proxy.conf; proxy_pass http://seckill_backend; }'
    probe=standard.replace(shipped, 'location ^~ /api/seckill/ { limit_req zone=api_per_ip burst=80 nodelay; try_files /index.html =404; }', 1)
    assert probe!=standard
    config=ROOT/'build/wsl/s7-nginx.conf';config.write_text(probe)
    try:
        dc('exec','-T','gateway','nginx','-s','reload');time.sleep(.5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=200) as pool:
            gates=list(pool.map(lambda _:call('GET','/api/seckill/rate-probe')[0],range(200)))
        gate_counts=collections.Counter(map(str,gates))
        assert 429 in gates and 200 in gates,gate_counts
        results.append({'name':'standard-nginx-40rps-gate','requests':200,'concurrency':200,'statuses':dict(gate_counts),'stockWrites':0,'method':'production limit_req directive/location with test-only static response'})
        print('PASS standard Nginx per-IP rejection gate',dict(gate_counts),flush=True)
    finally:
        config.write_text(standard)
        dc('exec','-T','gateway','nginx','-s','reload');time.sleep(.5)
else:
  try:
    campaign('pending-send-cap-128',160,64,[200],pause_relay=True)
    campaign('cold-cpp-process-warm-storage',64,16,[80],cold_cpp=True)
    for repeat in range(2):
        for concurrency in (4,16,64):campaign(f'hot-ramp-{concurrency}-run{repeat+1}',64,concurrency,[80])
    campaign('hot-oversubscription',96,64,[24])
    campaign('multi-activity-burst',128,32,[40,40,40,40])
    campaign('sustained-20rps-10s',200,32,[240],rate=20)
    # Real DB outage under traffic, independently report recovery and stock safety.
    before_db_restart=global_status()
    padmin=admin;groups=[activity(padmin,48,'db-outage-burst')];users=fixture_users(48)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:plans=list(pool.map(lambda u:prepare(u,*groups[0]),users))
    dc('stop','-t','1','mysql');begun=time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:replies=list(pool.map(buy,plans))
        assert all(code==202 for code,value in replies)
        time.sleep(3)
    finally:start_service('mysql')
    wait(lambda:call('GET','/health/order')[0]==200)
    final=clean();a,s=groups[0]
    wait(lambda:int(sql(f'SELECT COUNT(*) FROM orders WHERE activity_id={a}'))==48)
    results.append({'name':'db-outage-burst','accepted':48,'persisted':48,'concurrency':32,'outageToConvergenceSeconds':round(time.monotonic()-begun,3),'finalReconciliation':final['status']})
    print('PASS load database outage: accepted/persisted 48, no overselling',flush=True)
    # Probe the production limit_req location with local static content so the
    # app backend cannot become the bottleneck for the gateway policy check.
    standard=(ROOT/'deploy/nginx/nginx.conf').read_text()
    shipped='location ^~ /api/seckill/ { limit_req zone=api_per_ip burst=80 nodelay; include /etc/nginx/proxy.conf; proxy_pass http://seckill_backend; }'
    probe=standard.replace(shipped, 'location ^~ /api/seckill/ { limit_req zone=api_per_ip burst=80 nodelay; try_files /index.html =404; }', 1)
    assert probe!=standard
    config=ROOT/'build/wsl/s7-nginx.conf';config.write_text(probe)
    try:
        dc('exec','-T','gateway','nginx','-t');dc('exec','-T','gateway','nginx','-s','reload');time.sleep(.5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=200) as pool:
            gates=list(pool.map(lambda _:call('GET','/api/seckill/rate-probe')[0],range(200)))
        gate_counts=collections.Counter(map(str,gates))
        assert 429 in gates and 200 in gates,gate_counts
        results.append({'name':'standard-nginx-40rps-gate','requests':200,'concurrency':200,'statuses':dict(gate_counts),'stockWrites':0,'method':'production limit_req directive/location with test-only static response'})
        print('PASS standard Nginx per-IP rejection gate',dict(gate_counts),flush=True)
    finally:
        config.write_text(standard)
        dc('exec','-T','gateway','nginx','-t');dc('exec','-T','gateway','nginx','-s','reload')
  finally:stop.set();thread.join(timeout=20)
mq=dc('exec','-T','broker','sh','mqadmin','consumerProgress','-n','namesrv:9876','-g','mall_order_v1',check=False)
manifest={p:hashlib.sha256((ROOT/p).read_text().replace('\r\n','\n').encode()).hexdigest() for p in ['tests/load_s7.py','tests/test_s7.py','tests/stack_client.py','scripts/reconcile.py','scripts/test-s7-wsl.sh','deploy/compose.s7.yml','deploy/nginx/nginx.conf','src/seckill/redis.cpp','src/seckill/service.cpp','src/seckill/include/mall/redis.hpp']}
images=subprocess.check_output(['docker','inspect','--format','{{.Name}} {{.Image}}']+[PROJECT+'-'+s+'-1' for s in ('gateway','seckill','relay','order','redis','mysql','broker')],text=True)
background=subprocess.check_output(['docker','ps','--format','{{.Names}} {{.Status}}'],text=True)
record('load',{'date':'2026-10-14','codeRevision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'workingTreeIncludesS7':True,'sourceSha256':manifest,'runtimeImages':images,'coLocatedContainers':background,'cpu':subprocess.check_output(['lscpu'],text=True),'platform':platform.platform(),'mount':'/mnt/e (DrvFs)','connectionModel':'WSL Python3 stdlib HTTP/1.1, new connection per request; client and services share host','hardware':subprocess.check_output(['docker','info','--format','{{.NCPU}} CPUs / {{.MemTotal}} bytes'],text=True).strip(),'limits':{'nginxRate':5000,'cppIp':10000,'user':100,'proof':10,'pendingSendPerLedger':128,'javaConsumers':4,'hikariPool':12,'cppWorkers':8,'brokerInstances':1},'fixtures':'Private SQL users/Redis bearer sessions and captcha answers; token issuing and buy remain real HTTP; authentication setup and human captcha excluded from timed window','campaigns':results,'resources':samples,'mysqlStatusBefore':start_status,'mysqlStatusBeforeDatabaseRestart':before_db_restart,'mysqlStatusAfterDatabaseRestart':global_status(),'redisInfo':redis('INFO','stats'),'redisCommandLatency':redis('INFO','latencystats'),'mqConsumerProgressRaw':mq,'finalReconciliation':clean()})
print('PASS S7 load and downstream recovery',flush=True)
