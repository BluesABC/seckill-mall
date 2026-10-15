"""Private fixture helpers, restricted to the owned S7 Compose project."""
import hashlib,http.client,json,os,secrets,subprocess,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENV=Path(os.environ.get('MALL_STACK_ENV',ROOT/'deploy/.env.s7'))
settings=dict(line.split('=',1) for line in ENV.read_text().splitlines() if '=' in line and not line.startswith('#'))
PROJECT=os.environ.get('MALL_STACK_PROJECT','seckill-mall-s7')
if PROJECT!='seckill-mall-s7':raise RuntimeError('Private fixtures require owned seckill-mall-s7 project')
PORT=int(settings['MALL_WEB_PORT'])
CMD=['docker','compose','-p',PROJECT,'--env-file',str(ENV),'-f',str(ROOT/'deploy/compose.yml'),'-f',str(ROOT/'deploy/compose.s7.yml')]

def dc(*args,check=True):
    r=subprocess.run(CMD+list(args),capture_output=True,text=True,timeout=180)
    if check and r.returncode:raise RuntimeError('Compose '+args[0]+' failed: '+r.stderr[-600:])
    return r.stdout
def sql(q):return dc('exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" mysql -umall seckill_mall -N -B -e "$1"','sh',q).strip()
def start_service(service):
    cid=dc('ps','-a','-q',service).strip()
    if not cid:raise RuntimeError('Missing owned container')
    label=subprocess.check_output(['docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',cid],text=True).strip()
    if label!=PROJECT:raise RuntimeError('Refuse starting a foreign container')
    # Compose start can also start dependencies and invalidate an injected outage.
    subprocess.run(['docker','start',cid],check=True,capture_output=True,text=True,timeout=120)
def redis(*args):return dc('exec','-T','redis','redis-cli','--raw',*map(str,args)).strip()
def call(method,path,body=None,token=None):
    c=http.client.HTTPConnection('127.0.0.1',PORT,timeout=20);h={'Content-Type':'application/json'}
    if token:h['Authorization']='Bearer '+token
    try:
        c.request(method,path,json.dumps(body) if body is not None else None,h);r=c.getresponse();raw=r.read().decode()
        try:value=json.loads(raw)
        except ValueError:value={'code':'HTTP_'+str(r.status)}
        return r.status,value
    finally:c.close()
def wait(fn,seconds=180):
    end=time.monotonic()+seconds;last=None
    while time.monotonic()<end:
        try:
            last=fn()
            if last:return last
        except (OSError,RuntimeError,KeyError,ValueError):pass
        time.sleep(.5)
    raise AssertionError('Recovery deadline exceeded: '+str(last))
def login():
    code,value=call('POST','/api/auth/login',{'username':settings['MALL_ADMIN_USERNAME'],'password':settings['MALL_ADMIN_PASSWORD']})
    assert code==200,value;return value['token']
def fixture_users(count):
    start=int(sql('SELECT COALESCE(MAX(id),0)+1 FROM users'));now=int(time.time()*1000);users=[]
    # Keep SQL below both Windows CreateProcess limits and Linux ARG_MAX.
    for offset in range(0,count,100):
        values=','.join(f"({start+i},'s7_{start+i}','private-load-fixture-no-password','USER',{now})"
                        for i in range(offset,min(count,offset+100)))
        sql('INSERT INTO users(id,username,password_hash,role,created_at_ms) VALUES '+values)
    # A private pipeline writes sessions only to this owned test Redis.
    script='import os,json,hashlib,redis,sys; r=redis.Redis.from_url(os.environ["MALL_REDIS_URL"]); p=r.pipeline(); rows=json.load(sys.stdin); [(p.hset("seckill:session:"+hashlib.sha256(t.encode()).hexdigest(),mapping={"userId":str(u),"role":"USER","expiresAtMs":str(e)}),p.pexpireat("seckill:session:"+hashlib.sha256(t.encode()).hexdigest(),e)) for u,t,e in rows];p.execute()'
    for i in range(count):users.append((start+i,secrets.token_hex(32),now+7200000))
    r=subprocess.run(CMD+['run','--rm','--no-deps','-T','migrate','python','-c',script],input=json.dumps(users),capture_output=True,text=True,timeout=120)
    assert r.returncode==0,r.stderr[-300:]
    return users
def activity(admin,stock,name):
    code,g=call('POST','/api/admin/goods',{'title':'S7 '+name,'description':'Owned load fixture','imageUrl':'/assets/shoe-run-v1.webp','priceFen':'10000','stock':str(stock)},admin);assert code==201,g
    now=int(time.time()*1000)
    code,a=call('POST','/api/admin/activities',{'name':name,'skuId':g['skuId'],'stock':str(stock),'priceFen':'9000','startsAtMs':str(now-60000),'endsAtMs':str(now+7200000)},admin);assert code==201,a
    assert call('POST','/api/admin/activities/'+a['activityId']+'/activate',{'skuId':g['skuId']},admin)[0]==200
    return a['activityId'],g['skuId']
def prepare(user,a,sku):
    uid,token,_=user;request=str(uuid.uuid4())
    code,c=call('GET',f'/api/seckill/captcha?activityId={a}&skuId={sku}',token=token);assert code==200,c
    key=f'seckill:{{{a}:{sku}}}:challenge:{c["captchaId"]}'
    proof=json.loads(redis('GET',key));proof['answerDigest']=hashlib.sha256(b'123456').hexdigest();redis('SET',key,json.dumps(proof),'KEEPTTL')
    code,p=call('POST','/api/seckill/token',{'activityId':a,'skuId':sku,'requestId':request,'captchaId':c['captchaId'],'captchaAnswer':'123456'},token);assert code==200,p
    return {'user':uid,'token':token,'activity':a,'sku':sku,'requestId':request,'body':{'activityId':a,'skuId':sku,'requestId':request,'activityToken':p['activityToken'],'captchaToken':p['captchaToken']}}
def buy(p):return call('POST','/api/seckill/buy',p['body'],p['token'])
def order(p):
    code,o=call('GET',f'/api/order/status?activityId={p["activity"]}&skuId={p["sku"]}&requestId={p["requestId"]}',token=p['token'])
    return o if code==200 and o.get('orderId') else None
def reconcile(grace=1800,activity_id=None,limit=50000):
    args=['run','--rm','--no-deps','-T','migrate','python','scripts/reconcile.py','--grace-seconds',str(grace)]
    if activity_id is not None:args.extend(['--activity-id',str(activity_id)])
    args.extend(['--limit',str(limit)])
    out=dc(*args,check=False)
    return json.loads(out)
def clean(activity_id=None,limit=50000,timeout=180):return wait(lambda:(r if (r:=reconcile(activity_id=activity_id,limit=limit))['status']=='CLEAN' else None),seconds=timeout)
def record(name,data):
    target=ROOT/'tests/reports/wsl/s7';target.mkdir(parents=True,exist_ok=True)
    (target/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
