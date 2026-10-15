"""Owned WSL HTTP -> C++ -> RocketMQ -> Java -> MySQL/Redis business tests."""
import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import unittest
import uuid
from urllib.parse import urlencode
from pathlib import Path
import redis

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from data import connect,migrate
REPORT=ROOT/'tests/reports/wsl'
CPP=ROOT/'build/wsl/cpp-s3/src/seckill/seckill_service'
RELAY=ROOT/'build/wsl/cpp-s3/src/mq/mall_relay_worker'
JAR=ROOT/'build/wsl/order-target/order-service-0.1.0-SNAPSHOT.jar'
PASSWORD='S4-test-password-only-2026'
def uid():return str(uuid.uuid4())
def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
def call(at,method,path,token=None,body=None,raw=None):
    conn=http.client.HTTPConnection('127.0.0.1',at,timeout=20)
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    try:
        conn.request(method,path,body=raw if raw is not None else json.dumps(body) if body is not None else None,headers=headers)
        reply=conn.getresponse();text=reply.read().decode();return reply.status,json.loads(text) if text else None
    finally:conn.close()
def wait(action,seconds=45):
    deadline=time.monotonic()+seconds;last=None
    while time.monotonic()<deadline:
        try:
            last=action()
            if last:return last
        except (OSError,ValueError):pass
        time.sleep(.2)
    raise AssertionError(f'Timeout: {last}')

class S4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform!='linux':raise RuntimeError('Use WSL/Linux')
        cls.prefix='s4_test_'+uuid.uuid4().hex;cls.database='mall_s4_'+uuid.uuid4().hex
        cls.topic='mall_s4_'+uuid.uuid4().hex;cls.group='mall_s4_probe_'+uuid.uuid4().hex
        cls.cache=redis.Redis(port=16379,decode_responses=True,socket_timeout=5)
        cls.processes=[];cls.java=None;cls.logs=[];cls.forced_stops=[]
        cls.addClassCleanup(cls.cleanup)
        with connect() as db:
            with db.cursor() as cur:cur.execute(f'CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4')
        with connect(cls.database) as db:migrate(db)
        subprocess.run(['docker','exec','seckill-mall-mq-broker-1','sh','mqadmin','updateTopic','-n','namesrv:9876','-b','127.0.0.1:10911','-t',cls.topic,'-r','4','-w','4','-a','+message.type=NORMAL'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','exec','seckill-mall-mq-broker-1','sh','mqadmin','updateSubGroup','-n','namesrv:9876','-b','127.0.0.1:10911','-g',cls.group,'-r','1','-p','{"type":"CUSTOMIZED","customizedRetryPolicy":{"next":[1000,1000]}}'],check=True,stdout=subprocess.DEVNULL)
        cls.java_port=port();cls.cpp_port=port()
        cls.env=dict(os.environ,MALL_KEY_PREFIX=cls.prefix,MALL_DB_NAME=cls.database,MALL_DB_USER='root',MALL_DB_PASSWORD='s1-local-root-only',MALL_DB_PORT='13306',MALL_REDIS_PORT='16379',MALL_BUSINESS_ENABLED='true',MALL_MQ_TOPIC=cls.topic,MALL_MQ_GROUP=cls.group,MALL_ADMIN_USERNAME='admin',MALL_ADMIN_PASSWORD=PASSWORD,ORDER_PORT=str(cls.java_port),ORDER_JOBS_ENABLED='false',ORDER_RECOVERY_AGE_MS='300000',MALL_LUA_DIRECTORY=str(ROOT/'src/seckill/lua'))
        cls.start_java()
        log=(ROOT/'build/wsl/s4-cpp.log').open('w');cls.logs.append(log)
        cppenv=dict(cls.env,MALL_HTTP_PORT=str(cls.cpp_port),MALL_IP_LIMIT='10000',MALL_USER_LIMIT='10000',MALL_PROOF_LIMIT='10000',MALL_HTTP_WORKERS='16',MALL_HTTP_QUEUE='128')
        cls.cpp=subprocess.Popen([str(CPP),'--serve'],env=cppenv,stdout=log,stderr=subprocess.STDOUT);cls.processes.append(cls.cpp)
        wait(lambda:call(cls.cpp_port,'GET','/health/live')[0]==200)
        code,data=call(cls.java_port,'POST','/api/auth/login',body={'username':'admin','password':PASSWORD});assert code==200,(code,data)
        cls.admin=data['token'];cls.users=[]
        for i in range(6):
            code,data=call(cls.java_port,'POST','/api/auth/register',body={'username':f'user{i}','password':PASSWORD});assert code==201,(code,data)
            code,login=call(cls.java_port,'POST','/api/auth/login',body={'username':f'user{i}','password':PASSWORD});assert code==200,(code,login)
            cls.users.append((data['userId'],login['token']))
    @classmethod
    def start_java(cls,jobs=False):
        if cls.java is not None:cls.stop_process(cls.java)
        log=(ROOT/'build/wsl'/f's4-java-{len(cls.logs)}.log').open('w');cls.logs.append(log)
        cls.java=subprocess.Popen(['java','-jar',str(JAR)],env=dict(cls.env,ORDER_JOBS_ENABLED=str(jobs).lower()),stdout=log,stderr=subprocess.STDOUT);cls.processes.append(cls.java)
        def ready():
            if cls.java.poll() is not None:raise RuntimeError('Java startup exited; inspect '+log.name)
            return call(cls.java_port,'GET','/health/ready')[0]==200
        wait(ready,100)
    @classmethod
    def stop_process(cls,process):
        if process.poll() is None:
            process.terminate()
            # Spring's configured RocketMQ consumer close grace is 20 seconds;
            # leave room for the remaining lifecycle hooks before declaring SIGKILL.
            try:process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                cls.forced_stops.append(process.pid);process.kill();process.wait()
    @classmethod
    def cleanup(cls):
        for process in cls.processes:cls.stop_process(process)
        for log in cls.logs:log.close()
        keys=list(cls.cache.scan_iter(match=cls.prefix+':*'))
        if keys:cls.cache.unlink(*keys)
        if hasattr(cls,'database'):
            with connect() as db:
                with db.cursor() as cur:cur.execute(f'DROP DATABASE IF EXISTS `{cls.database}`')
    def api(self,method,path,body=None,token=None,raw=None):return call(self.java_port,method,path,token or self.users[0][1],body,raw)
    def admin_api(self,method,path,body=None):return self.api(method,path,body,self.admin)
    def sql(self,query,args=(),write=False):
        with connect(self.database) as db:
            with db.cursor() as cur:cur.execute(query,args);result=cur.fetchall()
            if write:db.commit()
            return result
    def setUp(self):
        now=int(self.sql('SELECT CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED)')[0][0])
        code,product=self.admin_api('POST','/api/admin/goods',{'title':'精品测试商品','description':'S4 owned fixture','imageUrl':'/assets/fixture.webp','priceFen':'1990','stock':'30'});self.assertEqual(code,201,product)
        self.goods=product['goodsId'];self.sku=product['skuId']
        self.assertEqual(self.admin_api('PATCH',f'/api/admin/skus/{self.sku}',{'sizeEu':'42','category':'跑步','colorway':'黑 / 白'})[0],200)
        code,activity=self.admin_api('POST','/api/admin/activities',{'name':'真实秒杀测试','skuId':self.sku,'stock':'10','priceFen':'1990','startsAtMs':str(now-60000),'endsAtMs':str(now+3600000)});self.assertEqual(code,201,activity)
        self.activity=activity['activityId'];self.key=f'{self.prefix}:{{{self.activity}:{self.sku}}}:ledger'
        self.assertEqual(self.admin_api('POST',f'/api/admin/activities/{self.activity}/activate',{'skuId':self.sku})[0],200)
    def reserve(self,user=0,http=True):
        userid,token=self.users[user];request=uid()
        if http:
            code,challenge=call(self.cpp_port,'GET',f'/api/seckill/captcha?activityId={self.activity}&skuId={self.sku}',token);self.assertEqual(code,200,challenge)
            key=f'{self.prefix}:{{{self.activity}:{self.sku}}}:challenge:'+challenge['captchaId']
            # Private owned fixture only; no HTTP bypass endpoint exists.
            proof=json.loads(self.cache.get(key));proof['answerDigest']=hashlib.sha256(b'123456').hexdigest();self.cache.set(key,json.dumps(proof),keepttl=True)
            code,proof=call(self.cpp_port,'POST','/api/seckill/token',token,{'activityId':self.activity,'skuId':self.sku,'requestId':request,'captchaId':challenge['captchaId'],'captchaAnswer':'123456'});self.assertEqual(code,200,proof)
            body={'activityId':self.activity,'skuId':self.sku,'requestId':request,'captchaToken':proof['captchaToken'],'activityToken':proof['activityToken']}
            code,accepted=call(self.cpp_port,'POST','/api/seckill/buy',token,body);self.assertEqual(code,202,accepted)
            reservation=accepted['reservationId']
        else:
            reservation=uid();script=self.cache.register_script((ROOT/'src/seckill/lua/reserve.lua').read_text())
            result=script(keys=[self.key],args=[userid,request,reservation,'1','s4-fixture']);self.assertEqual(result[0],'RESERVED')
            self.cache.sadd(self.prefix+':ledgers',self.key)
            self.cache.execute_command('WAITAOF',1,0,2000)
        event=json.loads(self.cache.hget(self.key,'pending:'+reservation))
        return event,token
    def relay(self,allow_state_conflict=False):
        result=subprocess.run([str(RELAY),'--once'],env=self.env,text=True,capture_output=True,timeout=45)
        self.assertIn(result.returncode,(0,3) if allow_state_conflict else (0,),result.stdout+result.stderr)
    def status(self,event,token=None):return self.api('GET',f'/api/order/status?activityId={event["activityId"]}&skuId={event["skuId"]}&requestId={event["requestId"]}',token=token)
    def order(self,event,token=None):
        def found():
            code,data=self.status(event,token);return data if code==200 and data.get('orderId') else False
        return wait(found,90)
    def jobs(self):
        code,data=self.admin_api('POST','/api/admin/recovery/run');self.assertEqual(code,200,data)
    def redis_request(self,event):return json.loads(self.cache.hget(self.key,f'req:{event["userId"]}:{event["requestId"]}'))
    def replay_event(self,event):
        terminal=self.redis_request(event)['state'] in ('FAILED','COMPENSATING')
        before=self.admin_api('GET','/api/admin/recovery')[1]['metrics']['received']
        self.cache.hset(self.key,mapping={'pending:'+event['eventId']:json.dumps(event),'pendingCount':'1'})
        try:
            self.relay(terminal)
            started=time.monotonic()
            wait(lambda:self.admin_api('GET','/api/admin/recovery')[1]['metrics']['received']>before,120)
            print(f'replay observed after {time.monotonic()-started:.3f}s; terminal={terminal}',flush=True)
        finally:
            if terminal:
                # Restore injected state even if the timing assertion fails.
                self.cache.hset(self.key,mapping={'pending:'+event['eventId']:'','pendingCount':'0'})

    def test_01_auth_and_cpp_shared_session(self):
        self.assertEqual(self.api('GET','/api/auth/me')[0],200)
        self.assertEqual(self.api('GET','/api/admin/users')[0],403)
        self.assertEqual(self.api('POST','/api/auth/login',{'username':'user0','password':'wrong-password-long'})[0],401)
        self.assertEqual(self.api('POST','/api/auth/register',{'username':'user0','password':PASSWORD})[0],409)
        event,token=self.reserve();self.assertEqual(self.status(event,token)[1]['requestState'],'RESERVED')
    def test_02_real_http_to_mysql_order(self):
        event,token=self.reserve();self.relay();order=self.order(event,token)
        self.assertEqual(order['orderState'],'PENDING_PAYMENT');self.assertEqual(order['amountFen'],'1990');self.jobs()
        self.assertEqual(self.redis_request(event)['state'],'ORDER_CREATED')
        self.assertEqual(self.cache.hget(self.key,'stock'),'9')
        self.assertEqual(self.sql('SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku))[0][0],9)
    def test_03_duplicate_message_same_order(self):
        event,token=self.reserve();self.relay();first=self.order(event,token);self.jobs();self.replay_event(event);time.sleep(2)
        self.assertEqual(self.order(event,token)['orderId'],first['orderId']);self.assertEqual(self.sql('SELECT COUNT(*) FROM orders WHERE reservation_id=%s',(event['reservationId'],))[0][0],1)
        self.assertEqual(self.sql('SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku))[0][0],9)
    def test_04_order_owner_and_list(self):
        event,token=self.reserve();self.relay();order=self.order(event,token)
        self.assertEqual(self.api('GET','/api/order/status?orderId='+order['orderId'],token=self.users[1][1])[0],404)
        self.assertEqual(self.api('POST','/api/order/pay',{'orderId':order['orderId'],'idempotencyKey':uid()},self.users[1][1])[0],404)
        self.assertTrue(any(x['orderId']==order['orderId'] for x in self.api('GET','/api/orders',token=token)[1]['items']))
    def test_05_mock_payment_idempotent(self):
        event,token=self.reserve();self.relay();order=self.order(event,token);body={'orderId':order['orderId'],'idempotencyKey':uid()}
        first=self.api('POST','/api/order/pay',body,token);self.assertEqual(first[0],200,first)
        self.assertEqual(self.api('POST','/api/order/pay',body,token),first)
        again=self.api('POST','/api/order/pay',dict(body,idempotencyKey=uid()),token);self.assertEqual(again,first)
        self.jobs();self.assertEqual(self.redis_request(event)['orderState'],'PAID')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM payments WHERE order_id=%s',(order['orderId'],))[0][0],1)
    def test_06_timeout_close_and_release_once(self):
        event,token=self.reserve();self.relay();order=self.order(event,token)
        self.sql('UPDATE orders SET expires_at_ms=created_at_ms+1 WHERE id=%s',(order['orderId'],),True);self.jobs();self.jobs()
        self.assertEqual(self.status(event,token)[1]['orderState'],'CLOSED');self.assertEqual(self.cache.hget(self.key,'stock'),'10')
        self.assertTrue(self.redis_request(event)['released']);self.assertEqual(self.api('POST','/api/order/pay',{'orderId':order['orderId'],'idempotencyKey':uid()},token)[0],409)
        self.assertEqual(self.sql('SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku))[0][0],10)
        self.assertEqual(call(self.cpp_port,'POST','/api/seckill/buy',token,{'activityId':self.activity,'skuId':self.sku,'requestId':uid(),'captchaToken':'a'*64,'activityToken':'b'*64})[0],403)
    def test_07_paid_order_never_released(self):
        event,token=self.reserve();self.relay();order=self.order(event,token);self.assertEqual(self.api('POST','/api/order/pay',{'orderId':order['orderId'],'idempotencyKey':uid()},token)[0],200)
        self.sql('UPDATE orders SET expires_at_ms=created_at_ms+1 WHERE id=%s',(order['orderId'],),True);self.jobs()
        self.assertEqual(self.status(event,token)[1]['orderState'],'PAID');self.assertEqual(self.cache.hget(self.key,'stock'),'9')
    def test_08_compensate_without_mysql_double_release(self):
        event,token=self.reserve();self.sql('UPDATE activity_stock SET available_stock=0 WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku),True);self.relay()
        wait(lambda:self.sql('SELECT status FROM seckill_requests WHERE reservation_id=%s',(event['reservationId'],)))
        self.jobs();self.jobs();self.assertEqual(self.status(event,token)[1]['requestState'],'FAILED');self.assertEqual(self.cache.hget(self.key,'stock'),'10')
        self.assertEqual(self.sql('SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku))[0][0],0)
        self.replay_event(event);time.sleep(2);self.assertIsNone(self.status(event,token)[1]['orderId'])
    def test_09_outbox_survives_redis_failure_and_restart(self):
        event,token=self.reserve();self.relay();order=self.order(event,token);hidden=self.key+':hidden';self.cache.rename(self.key,hidden)
        try:
            self.jobs();self.assertEqual(self.sql("SELECT status FROM outbox_events WHERE reservation_id=%s AND kind='ORDER_CREATED'",(event['reservationId'],))[0][0],'PENDING')
            type(self).start_java()
        finally:self.cache.rename(hidden,self.key)
        time.sleep(2.1);self.jobs();self.assertEqual(self.redis_request(event)['state'],'ORDER_CREATED');self.assertEqual(self.status(event,token)[1]['orderId'],order['orderId'])
    def test_10_recover_stranded_queued_without_order(self):
        event,token=self.reserve();self.cache.hset(self.key,'pending:'+event['eventId'],'');self.cache.hset(self.key,'pendingCount','0')
        script=self.cache.register_script((ROOT/'src/seckill/lua/mark_request.lua').read_text());script(keys=[self.key],args=[event['userId'],event['requestId'],event['reservationId'],'1','RESERVED','QUEUED'])
        # Make the accepted snapshot old within the activity window, without changing its identity.
        created=int(time.time()*1000)-310000;event['createdAtMs']=str(created)
        req=self.redis_request(event);req['createdAtMs']=str(created);self.cache.hset(self.key,f'req:{event["userId"]}:{event["requestId"]}',json.dumps(req));self.sql('UPDATE activities SET starts_at_ms=%s WHERE id=%s',(created-1000,self.activity),True)
        self.jobs();self.assertEqual(self.status(event,token)[1]['requestState'],'FAILED');self.assertEqual(self.cache.hget(self.key,'stock'),'10')
        self.replay_event(event);time.sleep(2);self.assertIsNone(self.status(event,token)[1]['orderId'])
    def test_11_admin_permissions_catalog_and_allocation(self):
        self.assertTrue(self.api('GET','/api/goods')[1]['items']);self.assertEqual(self.api('GET','/api/goods/'+self.goods)[0],200)
        self.assertTrue(self.api('GET','/api/activities')[1]['items']);self.assertEqual(self.api('POST',f'/api/admin/activities/{self.activity}/activate',{'skuId':self.sku})[0],403)
        self.assertEqual(self.admin_api('POST','/api/admin/activities',{'name':'too much','skuId':self.sku,'stock':'100','priceFen':'1990','startsAtMs':str(int(time.time()*1000)),'endsAtMs':str(int(time.time()*1000)+5000)})[0],409)
        code,variant=self.admin_api('POST',f'/api/admin/goods/{self.goods}/skus',{'sizeEu':'42.5','stock':'12'})
        self.assertEqual(code,201,variant)
        self.assertEqual(variant['unallocatedStock'],'12')
        variants=self.api('GET',f'/api/goods/{self.goods}')[1]['items']
        self.assertEqual(len(variants),2)
        self.assertEqual({x['sizeEu'] for x in variants},{'42','42.5'})
        self.assertEqual(next(x for x in variants if x['skuId']==variant['skuId'])['category'],'跑步')
        self.assertEqual(self.admin_api('POST',f'/api/admin/goods/{self.goods}/skus',{'sizeEu':'42.5','stock':'5'})[0],409)
        self.assertEqual(self.admin_api('PATCH',f'/api/admin/skus/{variant["skuId"]}',{'sizeEu':'42','category':'跑步','colorway':'黑 / 白'})[0],409)
        self.assertEqual(self.admin_api('POST',f'/api/admin/goods/{self.goods}/skus',{'sizeEu':'51','stock':'5'})[0],400)
        self.assertEqual(self.api('POST',f'/api/admin/goods/{self.goods}/skus',{'sizeEu':'43','stock':'5'})[0],403)
    def test_12_activation_never_overwrites_live_stock(self):
        event,_=self.reserve();self.assertEqual(self.admin_api('POST',f'/api/admin/activities/{self.activity}/activate',{'skuId':self.sku})[0],200);self.assertEqual(self.cache.hget(self.key,'stock'),'9')
        self.assertEqual(self.admin_api('POST',f'/api/admin/activities/{self.activity}/end',{'skuId':self.sku})[0],200)
        self.assertEqual(self.admin_api('POST',f'/api/admin/activities/{self.activity}/activate',{'skuId':self.sku})[0],409)
        self.relay();self.assertTrue(self.order(event)) # Accept requests made before administrative end.
    def test_13_strict_http_validation(self):
        self.assertEqual(self.api('POST','/api/auth/login',raw='{"username":"user0","username":"admin","password":"'+PASSWORD+'"}')[0],400)
        self.assertEqual(self.api('GET','/api/order/status?orderId='+uid()+'&orderId='+uid())[0],400)
        self.assertEqual(self.api('POST','/api/order/pay',{'orderId':uid(),'idempotencyKey':uid(),'userId':'1'})[0],400)
        self.assertEqual(self.api('POST','/api/auth/login',raw='x'*17000)[0],413)
    def test_14_disable_revokes_cpp_and_java_session(self):
        user,token=self.users[5];self.assertEqual(self.admin_api('PATCH','/api/admin/users/'+user,{'enabled':False})[0],200)
        self.assertEqual(self.api('GET','/api/auth/me',token=token)[0],401)
        self.assertEqual(call(self.cpp_port,'GET',f'/api/seckill/captcha?activityId={self.activity}&skuId={self.sku}',token)[0],401)
        self.assertEqual(self.admin_api('PATCH','/api/admin/users/'+user,{'enabled':True})[0],200)
    def test_15_logout_revokes_session(self):
        code,login=self.api('POST','/api/auth/login',{'username':'user4','password':PASSWORD});self.assertEqual(code,200)
        self.assertEqual(self.api('POST','/api/auth/logout',token=login['token'])[0],200);self.assertEqual(self.api('GET','/api/auth/me',token=login['token'])[0],401)
    def test_16_paid_close_concurrency(self):
        event,token=self.reserve();self.relay();order=self.order(event,token)
        # One DB time boundary; either PAID or CLOSED is valid, never both resource outcomes.
        self.sql('UPDATE orders SET expires_at_ms=%s WHERE id=%s',(int(time.time()*1000)+100,order['orderId']),True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(self.api,'POST','/api/order/pay',{'orderId':order['orderId'],'idempotencyKey':uid()},token) for _ in range(4)]+[pool.submit(self.jobs) for _ in range(4)]
            for result in futures:result.result()
        time.sleep(.2);self.jobs();state=self.status(event,token)[1]['orderState'];self.assertIn(state,['PAID','CLOSED'])
        self.assertEqual(self.cache.hget(self.key,'stock'),'9' if state=='PAID' else '10');self.assertEqual(self.sql('SELECT COUNT(*) FROM payments WHERE order_id=%s',(order['orderId'],))[0][0],1 if state=='PAID' else 0)
    def test_17_schema_and_identity_conflict_quarantined(self):
        event,token=self.reserve();bad=dict(event,priceFen='1');self.replay_event(bad)
        wait(lambda:self.sql("SELECT message_hash FROM mq_failures WHERE status='QUARANTINED'"));self.assertFalse(self.sql('SELECT id FROM orders WHERE reservation_id=%s',(event['reservationId'],)))
        self.replay_event(event);self.assertTrue(self.order(event,token));self.assertEqual(self.cache.hget(self.key,'stock'),'9')
    def test_18_parallel_stock_never_oversold(self):
        # Direct Lua reservation fixtures isolate consumer concurrency; test_02 covers real HTTP.
        events=[]
        for i in range(6):events.append(self.reserve(i,False)[0])
        self.sql('UPDATE activity_stock SET available_stock=3 WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku),True)
        self.relay();wait(lambda:self.sql('SELECT COUNT(*) FROM seckill_requests WHERE activity_id=%s',(self.activity,))[0][0]==6)
        self.jobs();self.assertEqual(self.sql('SELECT COUNT(*) FROM orders WHERE activity_id=%s',(self.activity,))[0][0],3)
        self.assertEqual(self.sql('SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s',(self.activity,self.sku))[0][0],0)
        self.assertEqual(self.cache.hget(self.key,'stock'),'7')
    def test_19_background_jobs_and_restart(self):
        event,token=self.reserve();self.relay();self.order(event,token);type(self).start_java(jobs=True)
        wait(lambda:self.redis_request(event).get('state')=='ORDER_CREATED')
        order=self.status(event,token)[1];self.sql('UPDATE orders SET expires_at_ms=created_at_ms+1 WHERE id=%s',(order['orderId'],),True)
        wait(lambda:self.redis_request(event).get('released') is True);self.assertEqual(self.cache.hget(self.key,'stock'),'10')
        type(self).start_java(jobs=False)

    def dlq_offset(self):
        status=subprocess.run(['docker','exec','seckill-mall-mq-broker-1','sh','mqadmin','topicStatus','-n','namesrv:9876','-t','%DLQ%'+self.group],text=True,capture_output=True,timeout=20)
        return sum(int(line.split()[3]) for line in status.stdout.splitlines() if re.match(r'^mall-broker\s+\d+\s+\d+\s+\d+',line))

    def test_20_mysql_outage_dlq_then_safe_termination(self):
        # Let the prior malformed-message retry finish before measuring this group's DLQ.
        time.sleep(3);baseline=self.dlq_offset()
        event,token=self.reserve();created=int(time.time()*1000)-310000;event['createdAtMs']=str(created)
        req=self.redis_request(event);req['createdAtMs']=str(created)
        self.cache.hset(self.key,mapping={f'req:{event["userId"]}:{event["requestId"]}':json.dumps(req),'pending:'+event['eventId']:json.dumps(event)})
        self.sql('UPDATE activities SET starts_at_ms=%s WHERE id=%s',(created-1000,self.activity),True)
        compose=['docker','compose','-p','seckill-mall-s1','--env-file',str(ROOT/'deploy/.env.s1.example'),'-f',str(ROOT/'deploy/compose.infra.yml')]
        container=subprocess.check_output(compose+['ps','-q','mysql'],text=True).strip()
        labels=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]['Config']['Labels']
        self.assertEqual(labels.get('com.docker.compose.project'),'seckill-mall-s1');self.assertEqual(labels.get('com.docker.compose.service'),'mysql')
        subprocess.run(compose+['stop','-t','5','mysql'],check=True,stdout=subprocess.DEVNULL)
        try:
            self.relay();self.assertEqual(self.cache.hget(self.key,'stock'),'9')
            wait(lambda:self.dlq_offset()>baseline,90)
        finally:subprocess.run(compose+['up','-d','--wait','--wait-timeout','180','mysql'],check=True,stdout=subprocess.DEVNULL)
        wait(lambda:self.api('GET','/health/ready')[0]==200,60)
        self.assertFalse(self.sql('SELECT id FROM orders WHERE reservation_id=%s',(event['reservationId'],)))
        self.jobs();self.jobs();self.assertEqual(self.status(event,token)[1]['requestState'],'FAILED');self.assertEqual(self.cache.hget(self.key,'stock'),'10')
        self.replay_event(event);time.sleep(2);self.assertIsNone(self.status(event,token)[1]['orderId'])

    def test_21_login_rate_limit(self):
        name='missing_'+uuid.uuid4().hex
        replies=[self.api('POST','/api/auth/login',{'username':name,'password':PASSWORD})[0] for _ in range(31)]
        self.assertEqual(replies[:30],[401]*30);self.assertEqual(replies[-1],429)

    def test_22_public_catalog_filters_and_pages_beyond_100_products(self):
        fixture_name='S9_PAGE_'+uuid.uuid4().hex[:10]
        categories=('跑步','篮球','休闲','训练')
        with connect(self.database) as db:
            with db.cursor() as cur:
                cur.executemany(
                    'INSERT INTO goods(title,description,image_url) VALUES(%s,%s,%s)',
                    [(f'{fixture_name}_{i:03d}', 'catalog pagination fixture', '/assets/fixture.webp') for i in range(105)])
                cur.execute('SELECT id FROM goods WHERE title LIKE %s ORDER BY id DESC', (fixture_name+'_%',))
                goods_ids=[row[0] for row in cur.fetchall()]
                cur.executemany(
                    'INSERT INTO skus(goods_id,price_fen,unallocated_stock,size_eu,category,colorway) VALUES(%s,%s,1,%s,%s,%s)',
                    [(gid, 10000+(i%11)*1000, '42', categories[i%4], '黑 / 白') for i,gid in enumerate(goods_ids)])
            db.commit()

        pages=[]
        for page in range(5):
            query=urlencode({'q':fixture_name,'page':page,'size':24})
            code,result=self.api('GET','/api/goods/catalog?'+query)
            self.assertEqual(code,200,result)
            self.assertEqual(result['total'],105)
            self.assertEqual(result['page'],page)
            self.assertEqual(result['size'],24)
            self.assertEqual(result['hasMore'],page<4)
            pages.extend(result['items'])
        ids=[item['goodsId'] for item in pages]
        self.assertEqual(len(ids),105)
        self.assertEqual(len(set(ids)),105)
        code,filtered=self.api('GET','/api/goods/catalog?'+urlencode({'q':fixture_name,'category':'跑步','maxPriceFen':'50000','sort':'low','size':48}))
        self.assertEqual(code,200,filtered)
        self.assertTrue(filtered['total']>0)
        self.assertTrue(all(item['category']=='跑步' and int(item['priceFen'])<=50000 for item in filtered['items']))
        self.assertEqual([int(item['priceFen']) for item in filtered['items']],sorted(int(item['priceFen']) for item in filtered['items']))
        for query in ('page=-1','size=49','sort=arbitrary','maxPriceFen=0'):
            self.assertEqual(self.api('GET','/api/goods/catalog?'+query)[0],400,query)

    def test_23_bounded_sigterm_shutdown(self):
        type(self).stop_process(self.java)
        self.assertIsNotNone(self.java.poll());self.assertEqual(self.forced_stops,[],'Java shutdown required SIGKILL')

if __name__=='__main__':
    REPORT.mkdir(parents=True,exist_ok=True)
    names=[n for n in sys.argv[1:] if n.startswith('test_')]
    suite=unittest.TestSuite(S4Tests(n) for n in names) if names else unittest.defaultTestLoader.loadTestsFromTestCase(S4Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'stage':'S4','platform':sys.platform,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),'scope':'real HTTP/C++/RocketMQ/Java/MySQL/Redis; MOCK payment, not production capacity'}
    (REPORT/'s4-business.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));sys.exit(0 if result.wasSuccessful() else 1)
