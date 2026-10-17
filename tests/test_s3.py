"""Real RocketMQ 5 C++ publisher -> Java consumer tests, WSL only."""
import json
import os
import select
import re
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

import redis
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "tests/reports/wsl"
CPP = ROOT / "build/wsl/cpp-s3/src/mq/mall_relay_worker"
JAVA_CLASSES = ROOT / "build/wsl/order-target/classes"
TOPIC = "seckill_reserved_v1"
COMPOSE = ["docker", "compose", "-p", "seckill-mall-mq", "-f", str(ROOT / "deploy/compose.mq.yml")]

def event_uuid(): return str(uuid.uuid4())

class S3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux": raise RuntimeError("S3 must execute inside WSL/Linux")
        cls.prefix = "s3_test_" + uuid.uuid4().hex
        cls.redis = redis.Redis(port=16379, decode_responses=True, socket_timeout=5)
        cls.preload = cls.redis.register_script((ROOT / "src/seckill/lua/preload.lua").read_text(encoding="utf-8"))
        cls.reserve = cls.redis.register_script((ROOT / "src/seckill/lua/reserve.lua").read_text(encoding="utf-8"))
        cls.schema = Draft202012Validator(json.loads((ROOT / "docs/contracts/reserved-event.schema.json").read_text(encoding="utf-8")),
                                           format_checker=FormatChecker())
        cls.java_classpath = str(JAVA_CLASSES) + ":" + (ROOT / "build/wsl/rocketmq-java.classpath").read_text().strip()
        cls.broker_id = subprocess.check_output(COMPOSE + ["ps", "-q", "broker"], text=True).strip()
        if not cls.broker_id: raise RuntimeError("Owned Broker not running")
        cls.check_broker_identity()
        cls.await_route()
        cls.test_keys = []

    @classmethod
    def check_broker_identity(cls):
        info = json.loads(subprocess.check_output(["docker", "inspect", cls.broker_id], text=True))[0]
        labels = info["Config"]["Labels"]
        if labels.get("com.docker.compose.project") != "seckill-mall-mq" or labels.get("com.docker.compose.service") != "broker":
            raise RuntimeError("Refusing to operate on an unrelated container")

    @classmethod
    def tearDownClass(cls):
        cls.start_broker()
        keys = list(cls.redis.scan_iter(match=cls.prefix + ":*"))
        if keys: cls.redis.unlink(*keys)

    @classmethod
    def stop_broker(cls):
        cls.check_broker_identity()
        subprocess.run(COMPOSE + ["stop", "-t", "5", "broker"], check=True, stdout=subprocess.DEVNULL)

    @classmethod
    def kill_broker(cls):
        cls.check_broker_identity()
        subprocess.run(["docker", "kill", "--signal", "KILL", cls.broker_id], check=True, stdout=subprocess.DEVNULL)

    @classmethod
    def start_broker(cls):
        subprocess.run(COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "120", "broker"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=145)
        cls.broker_id = subprocess.check_output(COMPOSE + ["ps", "-q", "broker"], text=True).strip()
        cls.check_broker_identity()
        cls.await_route()

    @classmethod
    def await_route(cls):
        # TCP health can precede async topic registration in NameServer.
        deadline=time.monotonic()+80
        while time.monotonic()<deadline:
            route=subprocess.run(["docker","exec",cls.broker_id,"sh","mqadmin","topicRoute",
                                  "-n","namesrv:9876","-t",TOPIC],text=True,capture_output=True,timeout=20)
            if route.returncode==0 and "brokerAddrs" in route.stdout and "queueDatas" in route.stdout:
                return
            time.sleep(1)
        raise RuntimeError("Broker TCP is up but topic route is not registered")

    def new_event(self, user):
        activity = str(int(uuid.uuid4().hex[:10], 16))
        sku = "1"; key = f"{self.prefix}:{{{activity}:{sku}}}:ledger"
        now = int(time.time() * 1000)
        response = self.preload(keys=[key], args=[10, now-1000, now+3600000, "ACTIVE", 1, 1990, activity, sku])
        self.assertEqual(response[0], "INITIALIZED")
        request, reservation = event_uuid(), event_uuid()
        with self.redis.pipeline(transaction=False) as pipe:
            pipe.eval((ROOT / "src/seckill/lua/reserve.lua").read_text(encoding="utf-8"), 1,
                      key, user, request, reservation, 1, "s3-transport-test")
            pipe.execute_command("WAITAOF", 1, 0, 1000)
            applied = pipe.execute()
        self.assertEqual(applied[0][0], "RESERVED")
        self.assertEqual(applied[1][0], 1)
        # The HTTP reserve path maintains these discovery indexes atomically.
        # This transport-only fixture uses internal Lua mode, so mirror those
        # index effects explicitly (including events created after relay start).
        with self.redis.pipeline(transaction=True) as pipe:
            pipe.sadd(self.prefix + ":ledgers", key)
            pipe.sadd(self.prefix + ":relay_ledgers", key)
            pipe.sadd(key + ":relay_pending", reservation)
            pipe.execute()
        self.test_keys.append(key)
        raw = self.redis.hget(key, "pending:" + reservation)
        self.schema.validate(json.loads(raw))
        return {"ledger":key,"user":str(user),"request":request,"eventId":reservation,"message":raw}

    def worker(self, crash=False, timeout=40):
        env = dict(os.environ, MALL_KEY_PREFIX=self.prefix, MALL_REDIS_PORT="16379",
                   MALL_MQ_ENDPOINT="127.0.0.1:8081", MALL_MQ_TOPIC=TOPIC)
        if crash: env["MALL_TEST_CRASH_AFTER_SEND"] = "1"
        return subprocess.run([str(CPP), "--once"], env=env, text=True, capture_output=True, timeout=timeout)

    def receive(self, event_id, count=1, group=None, mode="ack", timeout=75, push=False):
        group = group or "mall_s3_probe_" + uuid.uuid4().hex
        out = (ROOT / "build/wsl" / ("s3-java-" + group + ".log")).open("w", encoding="utf-8")
        command = ["java", "-cp", self.java_classpath,
                   "com.seckillmall.order.messaging.RocketPushFailureProbe" if push else
                   "com.seckillmall.order.messaging.RocketTransportProbe",
                   "127.0.0.1:8081", TOPIC, group, event_id]
        if not push: command += [str(count), mode]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=out, text=True, bufsize=1)
        deadline = time.monotonic() + 35
        try:
            while True:
                ready, _, _ = select.select([proc.stdout], [], [], max(0, deadline-time.monotonic()))
                if not ready:
                    raise RuntimeError("Java consumer did not become ready")
                line = proc.stdout.readline().strip()
                if line == "READY": break
                if proc.poll() is not None:
                    raise RuntimeError(f"Java consumer exited before ready: {line}")
            return proc, out, group
        except Exception:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            out.close()
            raise

    def finish_receiver(self, instance, timeout=75, push=False):
        proc, log, _ = instance
        try:
            output, _ = proc.communicate(timeout=timeout)
            self.assertEqual(proc.returncode, 0, log.name + " " + output)
            label="DELIVERY " if push else "EVENT "
            values = [json.loads(line[len(label):]) for line in output.splitlines() if line.startswith(label)]
            for item in values: self.schema.validate(item)
            return values
        finally:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            log.close()

    def request_state(self, event):
        return json.loads(self.redis.hget(event["ledger"], "req:"+event["user"]+":"+event["request"]))["state"]

    def test_01_cpp_to_java_and_ack(self):
        item=self.new_event(101)
        receiver=self.receive(item["eventId"])
        self.assertEqual(self.worker().returncode,0)
        messages=self.finish_receiver(receiver)
        self.assertEqual(len(messages),1)
        self.assertEqual(messages[0]["eventId"],item["eventId"])
        self.assertEqual(self.request_state(item),"QUEUED")
        self.assertEqual(self.redis.hget(item["ledger"],"pending:"+item["eventId"]),"")
        self.assertEqual(self.redis.hget(item["ledger"],"pendingCount"),"0")

    def test_02_broker_down_retains_reservation(self):
        item=self.new_event(102)
        self.stop_broker()
        try:
            failed=self.worker(timeout=45)
            self.assertNotEqual(failed.returncode,0)
            self.assertEqual(self.request_state(item),"RESERVED")
            self.assertTrue(self.redis.hget(item["ledger"],"pending:"+item["eventId"]))
            self.assertEqual(self.redis.hget(item["ledger"],"stock"),"9")
        finally:self.start_broker()
        receiver=self.receive(item["eventId"])
        self.assertEqual(self.worker().returncode,0)
        self.assertEqual(len(self.finish_receiver(receiver)),1)
        self.assertEqual(self.request_state(item),"QUEUED")

    def test_03_publish_ack_then_relay_crash_duplicate_safe_identity(self):
        item=self.new_event(103)
        receiver=self.receive(item["eventId"],count=2)
        crashed=self.worker(crash=True)
        self.assertEqual(crashed.returncode,93)
        self.assertEqual(self.request_state(item),"RESERVED")
        self.assertTrue(self.redis.hget(item["ledger"],"pending:"+item["eventId"]))
        self.assertEqual(self.worker().returncode,0)
        messages=self.finish_receiver(receiver)
        self.assertEqual(len(messages),2)
        self.assertEqual({m["eventId"] for m in messages},{item["eventId"]})
        self.assertEqual(self.redis.hget(item["ledger"],"stock"),"9")
        self.assertEqual(self.redis.hget(item["ledger"],"pendingCount"),"0")

    def test_04_broker_sigkill_retains_confirmed_message(self):
        item=self.new_event(104)
        group="mall_s3_probe_"+uuid.uuid4().hex
        receiver=self.receive(item["eventId"],group=group,mode="no-ack")
        self.assertEqual(self.worker().returncode,0)
        self.assertEqual(len(self.finish_receiver(receiver)),1)
        self.kill_broker()
        self.start_broker()
        receiver=self.receive(item["eventId"],group=group)
        self.assertEqual(len(self.finish_receiver(receiver)),1)
        self.assertEqual(self.request_state(item),"QUEUED")

    def test_05_push_consumer_retry_and_dead_letter(self):
        item=self.new_event(105)
        group="mall_s3_probe_"+uuid.uuid4().hex
        configured=subprocess.run(["docker","exec",self.broker_id,"sh","mqadmin","updateSubGroup",
            "-n","namesrv:9876","-b","127.0.0.1:10911","-g",group,"-r","1"],
            text=True,capture_output=True,timeout=25)
        self.assertEqual(configured.returncode,0,configured.stderr)
        receiver=self.receive(item["eventId"],count=2,group=group,push=True)
        self.assertEqual(self.worker().returncode,0)
        messages=self.finish_receiver(receiver,timeout=60,push=True)
        self.assertGreaterEqual(len(messages),2)
        self.assertEqual({message["eventId"] for message in messages},{item["eventId"]})
        dlq=["%DLQ%"+group, "%DLQ%"+group+"_"+TOPIC]
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            found=False
            for candidate in dlq:
                status=subprocess.run(["docker","exec",self.broker_id,"sh","mqadmin","topicStatus",
                                       "-n","namesrv:9876","-t",candidate],text=True,capture_output=True,timeout=20)
                offsets=[int(line.split()[3]) for line in status.stdout.splitlines()
                         if re.match(r"^mall-broker\s+\d+\s+\d+\s+\d+",line)]
                if status.returncode==0 and offsets and max(offsets)>=1:
                    found=True;break
            if found:break
            time.sleep(2)
        else:
            self.fail("Broker did not move failed message into this group's DLQ")
        self.assertEqual(self.request_state(item),"QUEUED")

    def test_07_legacy_pending_is_backfilled_at_startup(self):
        event = self.new_event(108)
        # Simulate a pre-index ledger, rather than silently dropping legacy
        # compatibility while updating the current producer's fixture.
        with self.redis.pipeline(transaction=True) as pipe:
            pipe.srem(self.prefix + ":relay_ledgers", event['ledger'])
            pipe.delete(event['ledger'] + ':relay_pending')
            pipe.execute()
        result = self.worker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.request_state(event), 'QUEUED')
        self.assertEqual(self.redis.hget(event['ledger'], 'pendingCount'), '0')
        self.assertEqual(self.redis.hget(event['ledger'], 'stock'), '9')
        self.assertFalse(self.redis.sismember(self.prefix + ':relay_ledgers', event['ledger']))
        self.assertEqual(self.redis.scard(event['ledger'] + ':relay_pending'), 0)

    def test_06_continuous_relay_recovers_without_manual_replay(self):
        env=dict(os.environ,MALL_KEY_PREFIX=self.prefix,MALL_REDIS_PORT="16379",
                 MALL_MQ_ENDPOINT="127.0.0.1:8081",MALL_MQ_TOPIC=TOPIC)
        log=(ROOT/"build/wsl/s3-relay-loop.log").open("w",encoding="utf-8")
        process=subprocess.Popen([str(CPP),"--loop"],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            first=self.new_event(106)
            deadline=time.monotonic()+35
            while time.monotonic()<deadline and self.request_state(first)!="QUEUED":
                self.assertIsNone(process.poll(),"Relay loop exited")
                time.sleep(.2)
            self.assertEqual(self.request_state(first),"QUEUED")
            self.stop_broker()
            second=self.new_event(107)
            time.sleep(2)
            self.assertEqual(self.request_state(second),"RESERVED")
            self.assertTrue(self.redis.hget(second["ledger"],"pending:"+second["eventId"]))
            self.start_broker()
            deadline=time.monotonic()+60
            while time.monotonic()<deadline and self.request_state(second)!="QUEUED":
                self.assertIsNone(process.poll(),"Relay loop exited after broker recovery")
                time.sleep(.5)
            self.assertEqual(self.request_state(second),"QUEUED")
            self.assertEqual(self.redis.hget(second["ledger"],"pendingCount"),"0")
            self.assertEqual(self.redis.hget(second["ledger"],"stock"),"9")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            log.close()
            self.start_broker()

if __name__ == "__main__":
    REPORT.mkdir(parents=True,exist_ok=True)
    selection = [name for name in sys.argv[1:] if name.startswith("test_")]
    suite = unittest.TestSuite(S3Tests(name) for name in selection) if selection else unittest.defaultTestLoader.loadTestsFromTestCase(S3Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={"stage":"S3","platform":sys.platform,"tests":result.testsRun,
            "failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),
            "passed":result.wasSuccessful(),"scope":"real RocketMQ C++ producer, Java simple ACK/retry and push failure/DLQ; no MySQL order transaction"}
    (REPORT/"s3-rocketmq.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report));sys.exit(0 if result.wasSuccessful() else 1)
