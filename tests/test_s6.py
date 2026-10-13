"""Docker-only clean-volume acceptance via Nginx, no host service substitute."""
import hashlib,http.client,json,os,subprocess,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENV=Path(os.environ.get('MALL_STACK_ENV',ROOT/'deploy/.env.stack'))
settings=dict(line.split('=',1) for line in ENV.read_text().splitlines() if '=' in line and not line.startswith('#'))
PROJECT=os.environ.get('MALL_STACK_PROJECT','seckill-mall-s6')
PORT=int(settings.get('MALL_WEB_PORT','18080'))
CMD=['docker','compose','-p',PROJECT,'--env-file',str(ENV),'-f',str(ROOT/'deploy/compose.yml')]
def dc(*args):return subprocess.run(CMD+list(args),check=True,text=True,capture_output=True).stdout
def call(method,path,body=None,token=None,headers=None):
    conn=http.client.HTTPConnection('127.0.0.1',PORT,timeout=25)
    h={'Content-Type':'application/json'};h.update(headers or {})
    if token:h['Authorization']='Bearer '+token
    conn.request(method,path,json.dumps(body) if body is not None else None,h)
    r=conn.getresponse();raw=r.read().decode();meta=dict(r.getheaders());status=r.status;conn.close()
    try:data=json.loads(raw)
    except ValueError:data=raw
    return status,data,meta
def wait(action,seconds=120):
    end=time.monotonic()+seconds;last=None
    while time.monotonic()<end:
        try:
            last=action()
            if last:return last
        except (OSError,ValueError):pass
        time.sleep(.5)
    raise AssertionError('Timeout waiting for container chain: '+str(last))
def sql(query):
    return dc('exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" mysql -umall seckill_mall -N -B -e "$1"','sh',query).strip()
checks=[]
def check(name,fn):fn();checks.append({'name':name,'status':'PASS'});print('PASS',name,flush=True)
started=time.monotonic()
def healthy():
    wait(lambda:call('GET','/health/live')[0]==200)
    wait(lambda:call('GET','/health/order')[0]==200)
    wait(lambda:call('GET','/health/seckill')[0]==200)
check('all real containers ready behind Nginx',healthy)
check('static storefront, CSP, missing asset 404',lambda:(
    (_ for _ in ()).throw(AssertionError()) if 'SNKR//DROP' not in call('GET','/')[1] else None,
    (_ for _ in ()).throw(AssertionError()) if call('GET','/assets/missing.png')[0]!=404 else None,
    (_ for _ in ()).throw(AssertionError()) if 'Content-Security-Policy' not in call('GET','/')[2] else None))
products=call('GET','/api/goods')[1]['items'];assert len(products)==4
activities=call('GET','/api/activities')[1]['items']
code,login,_=call('POST','/api/auth/login',{'username':settings['MALL_ADMIN_USERNAME'],'password':settings['MALL_ADMIN_PASSWORD']});assert code==200,login
admin=login['token'];username='s6_'+uuid.uuid4().hex[:16];pwd='S6-fixture-'+uuid.uuid4().hex
assert call('POST','/api/auth/register',{'username':username,'password':pwd})[0]==201
code,user,_=call('POST','/api/auth/login',{'username':username,'password':pwd});assert code==200
token=user['token']
def buy(index):
    g=products[index];a=next(a for a in activities if a['skuId']==g['skuId']);request=str(uuid.uuid4())
    code,c,_=call('GET',f'/api/seckill/captcha?activityId={a["activityId"]}&skuId={g["skuId"]}',token=token);assert code==200,c
    key=f'seckill:{{{a["activityId"]}:{g["skuId"]}}}:challenge:{c["captchaId"]}'
    proof=json.loads(dc('exec','-T','redis','redis-cli','--raw','GET',key));proof['answerDigest']=hashlib.sha256(b'123456').hexdigest()
    dc('exec','-T','redis','redis-cli','SET',key,json.dumps(proof),'KEEPTTL')
    code,p,_=call('POST','/api/seckill/token',{'activityId':a['activityId'],'skuId':g['skuId'],'requestId':request,'captchaId':c['captchaId'],'captchaAnswer':'123456'},token);assert code==200,p
    body={'activityId':a['activityId'],'skuId':g['skuId'],'requestId':request,'activityToken':p['activityToken'],'captchaToken':p['captchaToken']}
    code,accepted,_=call('POST','/api/seckill/buy',body,token);assert code==202,accepted
    assert call('POST','/api/seckill/buy',body,token)[0]==200
    path=f'/api/order/status?activityId={a["activityId"]}&skuId={g["skuId"]}&requestId={request}'
    order=wait(lambda:(x if (x:=call('GET',path,token=token)[1]).get('orderId') else None))
    assert order['orderState']=='PENDING_PAYMENT'
    return order,a,g
first,a,g=buy(0)
check('Nginx auth/captcha/C++ official MQ/Java/MySQL order + replay',lambda:None)
body={'orderId':first['orderId'],'idempotencyKey':str(uuid.uuid4())}
payment=call('POST','/api/order/pay',body,token);assert payment[0]==200 and payment[1]['orderState']=='PAID'
assert call('POST','/api/order/pay',body,token)[1]==payment[1]
check('idempotent real MOCK payment behind proxy',lambda:None)
second,a2,g2=buy(1)
sql(f"UPDATE orders SET expires_at_ms=created_at_ms+1 WHERE id='{second['orderId']}'")
wait(lambda:call('GET','/api/order/status?orderId='+second['orderId'],token=token)[1].get('orderState')=='CLOSED')
wait(lambda:dc('exec','-T','redis','redis-cli','HGET',f'seckill:{{{a2["activityId"]}:{g2["skuId"]}}}:ledger','stock').strip()=='10')
check('automatic close and durable Redis/DB stock release',lambda:None)
before=sql('SELECT COUNT(*) FROM goods')
dc('run','--rm','seed');assert sql('SELECT COUNT(*) FROM goods')==before
assert sql('SELECT COUNT(*)=COUNT(DISTINCT reservation_id) FROM orders')=='1'
check('repeated seed preserves catalog and live stock',lambda:None)
# An internal probe from the configured gateway must use its supplied identity.
dc('exec','-T','gateway','wget','-qO-','--header','X-Real-IP: 203.0.113.44',f'http://seckill:8083/api/seckill/info?activityId={a["activityId"]}&skuId={g["skuId"]}')
assert dc('exec','-T','redis','redis-cli','EXISTS','seckill:limit:ip:'+hashlib.sha256(b'203.0.113.44').hexdigest()).strip()=='1'
for i in range(3):
    assert call('GET',f'/api/seckill/info?activityId={a["activityId"]}&skuId={g["skuId"]}',headers={'X-Real-IP':f'203.0.113.{i}','X-Forwarded-For':f'203.0.113.{i}'})[0]==200
    digest=hashlib.sha256(f'203.0.113.{i}'.encode()).hexdigest()
    assert dc('exec','-T','redis','redis-cli','EXISTS','seckill:limit:ip:'+digest).strip()=='0'
check('client forged forwarding headers cannot select rate-limit identity',lambda:None)
containers=json.loads(dc('ps','--format','json')) if dc('ps','--format','json').lstrip().startswith('[') else [json.loads(line) for line in dc('ps','--format','json').splitlines()]
for c in containers:
    published=[p for p in (c.get('Publishers') or []) if p.get('PublishedPort',0)>0]
    if c['Service']!='gateway':assert not published,c['Service']
    else:assert len(published)==1 and published[0]['URL']=='127.0.0.1' and published[0]['PublishedPort']==PORT
check('only loopback gateway is published; app services unprivileged',lambda:(
    (_ for _ in ()).throw(AssertionError()) if dc('exec','-T','seckill','id','-u').strip()!='10001' else None,
    (_ for _ in ()).throw(AssertionError()) if dc('exec','-T','order','id','-u').strip()!='10001' else None))
dc('up','-d','--force-recreate','--no-deps','order');healthy()
assert call('GET','/api/order/status?orderId='+first['orderId'],token=token)[1]['orderState']=='PAID'
check('recreated order IP handled by Nginx Docker DNS',lambda:None)
dc('restart','redis','mysql','broker','order','seckill','relay','gateway');healthy()
assert call('GET','/api/order/status?orderId='+first['orderId'],token=token)[1]['orderState']=='PAID'
assert call('GET','/api/order/status?orderId='+second['orderId'],token=token)[1]['orderState']=='CLOSED'
assert sql("SELECT COUNT(*) FROM payments WHERE provider='MOCK' AND status='SUCCEEDED'")=='1'
assert sql('SELECT MIN(available_stock)>=0 FROM activity_stock')=='1'
assert sql('SELECT COUNT(*) FROM orders')=='2'
assert sql("SELECT COUNT(*) FROM activity_stock a WHERE a.initial_stock <> a.available_stock+(SELECT COALESCE(SUM(o.quantity),0) FROM orders o WHERE o.activity_id=a.activity_id AND o.sku_id=a.sku_id AND o.status<>'CLOSED')")=='0'
assert dc('exec','-T','redis','redis-cli','HGET',f'seckill:{{{a["activityId"]}:{g["skuId"]}}}:ledger','stock').strip()=='9'
assert dc('exec','-T','redis','redis-cli','HGET',f'seckill:{{{a2["activityId"]}:{g2["skuId"]}}}:ledger','stock').strip()=='10'
check('whole stack restart preserves sessions/payment/orders/stock',lambda:None)
report={'date':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'runtime':os.uname().sysname,'elapsedSeconds':round(time.monotonic()-started,3),'project':PROJECT,'checks':checks,'orders':2,'paid':1,'closed':1,'mockPayments':1,'fixtures':'Owned clean stack; captcha answer and expiry injected privately in test Redis/SQL only'}
(ROOT/'tests/reports/wsl/s6-deploy.json').write_text(json.dumps(report,indent=2));print('PASS S6 Docker deployment acceptance',flush=True)
