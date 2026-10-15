"""Real C++ HTTP/Redis tests on WSL. Private fixture sessions/challenge answers only.
RocketMQ publishing uses an explicitly test-only probe, never production acceptance.
"""
import base64
import concurrent.futures
import hashlib
import http.client
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import uuid
from pathlib import Path
import redis

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/"build/wsl/cpp/src/seckill/seckill_service"
RELAY=ROOT/"build/wsl/cpp/relay_probe"
LUA=ROOT/"src/seckill/lua"
REPORT=ROOT/"tests/reports/wsl"

def sha(value):return hashlib.sha256(value.encode()).hexdigest()
def uid():return str(uuid.uuid4())
def free_port():
    with socket.socket() as s:s.bind(("127.0.0.1",0));return s.getsockname()[1]

class RunningServer:
    def __init__(self,prefix,**options):
        self.port=free_port();self.prefix=prefix
        self.env=dict(os.environ,MALL_HTTP_HOST="127.0.0.1",MALL_HTTP_PORT=str(self.port),MALL_REDIS_PORT="16379",
            MALL_KEY_PREFIX=prefix,MALL_HTTP_WORKERS="16",MALL_HTTP_QUEUE="128",MALL_IP_LIMIT="10000",
            MALL_USER_LIMIT="10000",MALL_PROOF_LIMIT="10000",MALL_MAX_PENDING="1000")
        self.env.update({k:str(v) for k,v in options.items()})
        self.log=(ROOT/"build/wsl"/f"s2-server-{self.port}.log").open("w")
        self.process=subprocess.Popen([str(BINARY),"--serve"],env=self.env,stdout=self.log,stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.process.poll() is not None:raise RuntimeError("C++ service failed at startup")
            try:
                if self.call("GET","/health/live")[0]==200:return
            except OSError:pass
            time.sleep(.05)
        self.stop();raise RuntimeError("C++ startup timeout")

    def call(self,method,path,token=None,payload=None,headers=None,raw=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=8)
        values=dict(headers or {})
        if token:values["Authorization"]="Bearer "+token
        data=raw if raw is not None else (json.dumps(payload) if payload is not None else None)
        if data is not None:values.setdefault("Content-Type","application/json")
        try:
            connection.request(method,path,body=data,headers=values)
            reply=connection.getresponse();body=reply.read().decode()
            result=json.loads(body) if "application/json" in reply.getheader("Content-Type","") else body
            return reply.status,result,dict(reply.getheaders())
        finally:connection.close()

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait();raise RuntimeError("C++ failed graceful shutdown")
        self.log.close()

def resp(file):
    line=file.readline()
    if not line:raise EOFError()
    prefix=line[:1]
    if prefix==b"$":
        size=int(line[1:-2]);extra=file.read(size+2) if size>=0 else b"";return line+extra
    if prefix==b"*":return line+b"".join(resp(file) for _ in range(max(0,int(line[1:-2]))))
    return line

class DropAofProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address=True;daemon_threads=True
    def __init__(self):
        self.drop=True;self.lock=threading.Lock()
        super().__init__(("127.0.0.1",0),self.Handler)
        self.thread=threading.Thread(target=self.serve_forever,daemon=True);self.thread.start()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection(("127.0.0.1",16379),timeout=4) as backend:
                source=self.request.makefile("rb");target=backend.makefile("rb")
                try:
                    while True:
                        command=resp(source)
                        if b"\r\nWAITAOF\r\n" in command:
                            with self.server.lock:
                                if self.server.drop:self.server.drop=False;return
                        backend.sendall(command);self.request.sendall(resp(target))
                except (EOFError,OSError):pass
    def close(self):self.shutdown();self.server_close();self.thread.join(timeout=3)

class S2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix="s2_test_"+uuid.uuid4().hex
        cls.client=redis.Redis(port=16379,decode_responses=True,socket_timeout=5)
        cls.preload=cls.client.register_script((LUA/"preload.lua").read_text())
        cls.owned_prefixes=[cls.prefix]
        cls.server=RunningServer(cls.prefix)
        cls.sessions={}
        for user in range(1,201):cls.sessions[user]=cls.session(user,cls.prefix,"ADMIN" if user==1 else "USER")
    @classmethod
    def session(cls,user,prefix,role="USER",expires=None):
        token=secrets.token_hex(32);key=prefix+":session:"+sha(token)
        cls.client.hset(key,mapping={"userId":str(user),"role":role,"expiresAtMs":str(expires or int(time.time()*1000)+3600000)})
        cls.client.expire(key,3600);return token
    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        for prefix in cls.owned_prefixes:
            keys=list(cls.client.scan_iter(match=prefix+":*"))
            if keys:cls.client.unlink(*keys)
    def setUp(self):
        self.a=str(secrets.randbelow(900000)+100000);self.s="1"
        self.key=self.prefix+":{"+self.a+":"+self.s+"}:ledger"
        now=int(time.time()*1000)
        self.preload(keys=[self.key],args=[10,now-1000,now+3600000,"ACTIVE",1,1990,self.a,self.s])
        self.keys=[self.key]
    def tearDown(self):
        self.client.unlink(*self.keys)
        self.client.srem(self.prefix+":ledgers",self.key)
        self.client.delete(self.prefix+":blacklist:ip",self.prefix+":blacklist:user")
    def captcha(self,user=1,server=None):
        srv=server or self.server
        token=self.sessions[user] if srv is self.server else self.session(user,srv.prefix)
        code,value,_=srv.call("GET",f"/api/seckill/captcha?activityId={self.a}&skuId={self.s}",token)
        self.assertEqual(code,200)
        self.assertNotIn("answer",value)
        image=base64.b64decode(value["imageDataUrl"].split(",",1)[1]);self.assertEqual(image[:8],b"\x89PNG\r\n\x1a\n")
        (REPORT/"s2-captcha-sample.png").write_bytes(image)
        key=srv.prefix+":{"+self.a+":"+self.s+"}:challenge:"+value["captchaId"]
        self.keys.append(key)
        # Private test fixture solves a fixed answer, not a public bypass API.
        proof=json.loads(self.client.get(key));proof["answerDigest"]=sha("123456")
        self.client.set(key,json.dumps(proof),keepttl=True)
        return value,key,token
    def purchase(self,user=1,request=None,server=None):
        srv=server or self.server;request=request or uid()
        captcha,key,token=self.captcha(user,srv)
        code,proof,_=srv.call("POST","/api/seckill/token",token,{"activityId":self.a,"skuId":self.s,"requestId":request,"captchaId":captcha["captchaId"],"captchaAnswer":"123456"})
        self.assertEqual(code,200)
        payload={"activityId":self.a,"skuId":self.s,"requestId":request,"captchaToken":proof["captchaToken"],"activityToken":proof["activityToken"]}
        return payload,key,token
    def buy(self,payload,token=None,server=None):return (server or self.server).call("POST","/api/seckill/buy",token or self.sessions[1],payload)
    def stock(self):return int(self.client.hget(self.key,"stock"))

    def test_health_and_activity_info(self):
        self.assertEqual(self.server.call("GET","/health/live")[0],200)
        status,ready,_=self.server.call("GET","/health/ready");self.assertEqual(status,200);self.assertFalse(ready["mqIntegrated"])
        status,value,_=self.server.call("GET",f"/api/seckill/info?activityId={self.a}&skuId=1")
        self.assertEqual(status,200);self.assertEqual(value["priceFen"],"1990");self.assertEqual(value["state"],"ACTIVE")
    def test_auth_missing_invalid_expired_revoked(self):
        path=f"/api/seckill/captcha?activityId={self.a}&skuId=1"
        self.assertEqual(self.server.call("GET",path)[0],401)
        self.assertEqual(self.server.call("GET",path,"a"*64)[0],401)
        token=self.session(1,self.prefix,expires=int(time.time()*1000)-1000)
        self.assertEqual(self.server.call("GET",path,token)[0],401)
        token=self.session(1,self.prefix);self.client.delete(self.prefix+":session:"+sha(token))
        self.assertEqual(self.server.call("GET",path,token)[0],401)
        token=self.session(1,self.prefix,role="INVALID_ROLE")
        self.assertEqual(self.server.call("GET",path,token)[0],401)
    def test_valid_buy_has_pending_no_order(self):
        payload,_,token=self.purchase();status,value,headers=self.buy(payload,token)
        self.assertEqual(status,202);self.assertEqual(value["requestState"],"RESERVED");self.assertIsNone(value["orderId"])
        self.assertEqual(self.stock(),9);self.assertEqual(self.client.hget(self.key,"pendingCount"),"1")
        self.assertTrue(self.client.hget(self.key,"pending:"+value["reservationId"]))
        self.assertTrue(self.client.sismember(self.key+":relay_pending",value["reservationId"]))
        self.assertTrue(headers.get("X-Trace-Id"));self.assertEqual(headers["Cache-Control"],"no-store")
    def test_replay_after_proof_expiry(self):
        payload,key,token=self.purchase();status,first,_=self.buy(payload,token);self.assertEqual(status,202)
        self.client.delete(key)
        payload["captchaToken"]="";payload["activityToken"]=""
        status,again,_=self.buy(payload,token)
        self.assertEqual(status,200);self.assertEqual(again["reservationId"],first["reservationId"]);self.assertEqual(self.stock(),9)
    def test_captcha_wrong_answer_and_attempt_limit(self):
        captcha,key,token=self.captcha();request=uid()
        payload={"activityId":self.a,"skuId":"1","requestId":request,"captchaId":captcha["captchaId"],"captchaAnswer":"000000"}
        for _ in range(5):self.assertEqual(self.server.call("POST","/api/seckill/token",token,payload)[0],403)
        payload["captchaAnswer"]="123456"
        self.assertEqual(self.server.call("POST","/api/seckill/token",token,payload)[0],403)
        self.assertEqual(json.loads(self.client.get(key))["attempts"],5);self.assertEqual(self.stock(),10)
    def test_accessible_text_challenge_keeps_answer_server_side(self):
        token=self.sessions[1]
        status,value,_=self.server.call("GET",f"/api/seckill/captcha?activityId={self.a}&skuId=1&mode=accessible",token)
        self.assertEqual(status,200);self.assertEqual(value["mode"],"accessible")
        self.assertIn("challengeText",value);self.assertNotIn("imageDataUrl",value);self.assertNotIn("answer",value)
        import re
        numbers=re.search(r"请计算 (\d+) 加 (\d+)",value["challengeText"])
        self.assertIsNotNone(numbers,value["challengeText"])
        answer=str(int(numbers.group(1))+int(numbers.group(2)))
        request=uid()
        invalid=dict(activityId=self.a,skuId="1",requestId=request,captchaId=value["captchaId"],captchaAnswer="0")
        self.assertEqual(self.server.call("POST","/api/seckill/token",token,invalid)[0],403)
        invalid["captchaAnswer"]=answer
        status,proof,_=self.server.call("POST","/api/seckill/token",token,invalid)
        self.assertEqual(status,200,proof)
        self.assertEqual(self.server.call("GET",f"/api/seckill/captcha?activityId={self.a}&skuId=1&mode=audio",token)[0],400)
    def test_challenge_one_use(self):
        payload,key,token=self.purchase();proof=json.loads(self.client.get(key))
        captcha_id=payload["activityToken"].split(".")[0]
        self.assertTrue(proof["used"]);self.assertNotIn("answerDigest",proof)
        self.assertEqual(self.server.call("POST","/api/seckill/token",token,{"activityId":self.a,"skuId":"1","requestId":uid(),"captchaId":captcha_id,"captchaAnswer":"123456"})[0],403)
    def test_proof_bound_user_request_and_activity(self):
        payload,_,token=self.purchase()
        self.assertEqual(self.buy(payload,self.sessions[2])[0],403)
        changed=dict(payload,requestId=uid());self.assertEqual(self.buy(changed,token)[0],403)
        changed=dict(payload,skuId="2");self.assertEqual(self.buy(changed,token)[0],404)
        self.assertEqual(self.stock(),10)
    def test_proof_expired_and_tampered(self):
        payload,key,token=self.purchase();changed=dict(payload,captchaToken="0"*64)
        self.assertEqual(self.buy(changed,token)[0],403)
        proof=json.loads(self.client.get(key));proof["expiresAtMs"]=1;self.client.set(key,json.dumps(proof),keepttl=True)
        self.assertEqual(self.buy(payload,token)[0],403);self.assertEqual(self.stock(),10)
    def test_same_user_different_requests(self):
        first,_,token=self.purchase();self.assertEqual(self.buy(first,token)[0],202)
        second,_,token=self.purchase();status,value,_=self.buy(second,token)
        self.assertEqual(status,409);self.assertEqual(value["code"],"ALREADY_PURCHASED");self.assertEqual(self.stock(),9)
    def test_concurrent_inventory(self):
        self.client.hset(self.key,mapping={"stock":"20","initialStock":"20"})
        purchases=[self.purchase(user) for user in range(1,81)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            results=list(pool.map(lambda item:self.buy(item[0],item[2])[0],purchases))
        self.assertEqual(results.count(202),20);self.assertEqual(results.count(409),60);self.assertEqual(self.stock(),0)
    def test_concurrent_same_request(self):
        payload,_,token=self.purchase()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results=list(pool.map(lambda _:self.buy(payload,token),range(30)))
        self.assertEqual(sum(result[0]==202 for result in results),1)
        self.assertEqual(sum(result[0]==200 for result in results),29)
        self.assertEqual(len({result[1]["reservationId"] for result in results}),1);self.assertEqual(self.stock(),9)
    def test_request_lookup_ownership_and_no_fabricated_order(self):
        payload,_,token=self.purchase();self.buy(payload,token)
        path="/api/order/status?"+urllib.parse.urlencode({"activityId":self.a,"skuId":"1","requestId":payload["requestId"]})
        status,value,_=self.server.call("GET",path,token);self.assertEqual(status,200);self.assertIsNone(value["orderId"])
        self.assertEqual(self.server.call("GET",path,self.sessions[2])[0],404)
        self.assertEqual(self.server.call("GET","/api/order/status?orderId="+uid(),token)[0],503)
    def test_unknown_fields_ids_json_and_body_limit(self):
        payload,_,token=self.purchase()
        for changed in [dict(payload,userId="2"),dict(payload,quantity="2"),dict(payload,activityId="-1"),dict(payload,requestId="bad")]:
            self.assertEqual(self.buy(changed,token)[0],400)
        raw=json.dumps(payload)[:-1]+',"requestId":"'+payload["requestId"]+'"}'
        self.assertEqual(self.server.call("POST","/api/seckill/buy",token,raw=raw)[0],400)
        self.assertEqual(self.server.call("POST","/api/seckill/buy",token,raw="{" )[0],400)
        self.assertEqual(self.server.call("POST","/api/seckill/buy",token,raw="x"*17000)[0],413)
        self.assertEqual(self.stock(),10)
    def test_duplicate_query_rejected(self):
        for query in [f"activityId={self.a}&activityId={self.a}&skuId=1",f"activityId={self.a}&activityId=2&skuId=1",f"%61ctivityId={self.a}&skuId=1"]:
            self.assertEqual(self.server.call("GET","/api/seckill/info?"+query)[0],400)
    def test_blacklist_ip_and_user(self):
        self.client.sadd(self.prefix+":blacklist:user","1")
        self.assertEqual(self.server.call("GET",f"/api/seckill/captcha?activityId={self.a}&skuId=1",self.sessions[1])[0],403)
        self.client.delete(self.prefix+":blacklist:user")
        self.client.sadd(self.prefix+":blacklist:ip",sha("127.0.0.1"))
        self.assertEqual(self.server.call("GET",f"/api/seckill/info?activityId={self.a}&skuId=1")[0],403)
        self.assertEqual(self.server.call("GET","/health/live")[0],200)
    def test_metrics_admin_only(self):
        self.assertEqual(self.server.call("GET","/metrics",self.sessions[2])[0],403)
        status,text,_=self.server.call("GET","/metrics",self.sessions[1]);self.assertEqual(status,200)
        self.assertIn("seckill_reserved_total",text);self.assertNotIn(self.sessions[1],text)
    def test_relay_outcomes_preserve_or_confirm_pending(self):
        payload,_,token=self.purchase();_,value,_=self.buy(payload,token);reservation=value["reservationId"]
        env=dict(os.environ,MALL_REDIS_PORT="16379",MALL_KEY_PREFIX=self.prefix)
        for outcome in ["unknown","rejected"]:
            subprocess.run([str(RELAY),self.key,outcome],env=env,check=True,stdout=subprocess.DEVNULL)
            self.assertTrue(self.client.hget(self.key,"pending:"+reservation));self.assertEqual(self.client.hget(self.key,"pendingCount"),"1")
            self.assertTrue(self.client.sismember(self.key+":relay_pending",reservation))
        subprocess.run([str(RELAY),self.key,"confirmed"],env=env,check=True,stdout=subprocess.DEVNULL)
        self.assertEqual(self.client.hget(self.key,"pending:"+reservation),"");self.assertEqual(self.client.hget(self.key,"pendingCount"),"0")
        self.assertFalse(self.client.sismember(self.key+":relay_pending",reservation))
        self.assertFalse(self.client.sismember(self.prefix+":relay_ledgers",self.key))
        request=json.loads(self.client.hget(self.key,"req:1:"+payload["requestId"]));self.assertEqual(request["state"],"QUEUED")
        self.assertEqual(self.stock(),9)
    def test_pending_backpressure(self):
        server=RunningServer(self.prefix,MALL_MAX_PENDING=1)
        try:
            first,_,token=self.purchase(server=server);self.assertEqual(self.buy(first,token,server)[0],202)
            second,_,token=self.purchase(user=2,server=server);status,value,_=self.buy(second,token,server)
            self.assertEqual(status,503);self.assertEqual(value["code"],"BACKPRESSURE");self.assertEqual(self.stock(),9)
        finally:server.stop()
    def test_ip_limit_ignores_forwarded_spoof(self):
        prefix="s2_ip_"+uuid.uuid4().hex;self.owned_prefixes.append(prefix)
        server=RunningServer(prefix,MALL_IP_LIMIT=2)
        key=prefix+":{"+self.a+":1}:ledger";self.keys.append(key)
        self.client.hset(key,mapping=self.client.hgetall(self.key))
        try:
            results=[server.call("GET",f"/api/seckill/info?activityId={self.a}&skuId=1",headers={"X-Forwarded-For":f"203.0.113.{i}"})[0] for i in range(4)]
            self.assertEqual(results,[200,200,429,429])
        finally:server.stop()
    def test_user_rate_limit(self):
        prefix="s2_user_"+uuid.uuid4().hex;self.owned_prefixes.append(prefix)
        server=RunningServer(prefix,MALL_USER_LIMIT=2)
        token=self.session(1,prefix);key=prefix+":{"+self.a+":1}:ledger";self.keys.append(key)
        self.client.hset(key,mapping=self.client.hgetall(self.key))
        try:
            path=f"/api/seckill/captcha?activityId={self.a}&skuId=1"
            self.assertEqual([server.call("GET",path,token)[0] for _ in range(3)],[200,200,429])
        finally:server.stop()
    def test_dependency_outage(self):
        server=RunningServer(self.prefix,MALL_REDIS_PORT=free_port())
        try:
            self.assertEqual(server.call("GET","/health/live")[0],200)
            self.assertEqual(server.call("GET","/health/ready")[0],503)
            self.assertEqual(server.call("GET",f"/api/seckill/info?activityId={self.a}&skuId=1")[0],503)
        finally:server.stop()
    def test_aof_reply_lost_query_and_replay(self):
        proxy=DropAofProxy();server=RunningServer(self.prefix,MALL_REDIS_PORT=proxy.server_address[1])
        try:
            payload,_,token=self.purchase(server=server)
            status,value,_=self.buy(payload,token,server);self.assertEqual(status,503);self.assertEqual(value["code"],"ACCEPTANCE_UNKNOWN")
            self.assertEqual(self.stock(),9)
            status,value,_=self.buy(payload,token,server);self.assertEqual(status,200);self.assertEqual(value["requestState"],"RESERVED")
            self.assertEqual(self.stock(),9)
        finally:server.stop();proxy.close()
    def test_graceful_shutdown_releases_port(self):
        server=RunningServer(self.prefix);port=server.port;server.stop();self.assertEqual(server.process.returncode,0)
        with socket.socket() as sock:self.assertNotEqual(sock.connect_ex(("127.0.0.1",port)),0)

if __name__=="__main__":
    if sys.platform!="linux":raise SystemExit("S2 acceptance must execute inside WSL/Linux")
    REPORT.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(S2Tests))
    report={"stage":"S2","platform":sys.platform,"tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
            "skipped":len(result.skipped),"passed":result.wasSuccessful(),"scope":"C++ HTTP + real Redis; relay probe test-only; no RocketMQ/Java order"}
    (REPORT/"s2-http-integration.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report));sys.exit(0 if result.wasSuccessful() else 1)
