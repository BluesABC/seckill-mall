"""Real MySQL/Redis contract integration in an owned database/key namespace.

The SQL consumer helper is a test harness, not the Java order service.
"""
import concurrent.futures
import json
import os
import platform
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from data import cache, connect, migrate, seed_demo, preheat
import pymysql
from jsonschema import Draft202012Validator, FormatChecker

def uid(): return str(uuid.uuid4())

class S1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = uuid.uuid4().hex
        cls.database = "mall_s1_" + cls.run_id
        cls.redis = cache()
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4")
        cls.db = connect(cls.database)
        cls.migration_first = migrate(cls.db)
        with cls.db.cursor() as cur:
            cur.executemany("INSERT INTO users(id,username,password_hash,role,created_at_ms) VALUES (%s,%s,'test-fixture-not-a-login-hash','USER',%s)",
                [(i, f"fixture-{i}", int(time.time()*1000)) for i in range(1, 301)])
        cls.db.commit()
        cls.scripts = {name: cls.redis.register_script(
            (ROOT / f"src/seckill/lua/{name}.lua").read_text(encoding="utf-8"))
            for name in ["preload", "reserve", "mark_request", "mark_order", "release"]}
        cls.schema = Draft202012Validator(json.loads((ROOT / "docs/contracts/reserved-event.schema.json").read_text()),
                                          format_checker=FormatChecker())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as conn:
            with conn.cursor() as cur:
                # Only the randomly named DB created by this test invocation.
                cur.execute(f"DROP DATABASE `{cls.database}`")

    def setUp(self):
        self.keys = []
        self.key, self.activity, self.sku = self.ledger()

    def tearDown(self):
        self.db.rollback()
        if self.keys: self.redis.unlink(*self.keys)

    def ledger(self, stock=10, starts=None, ends=None, status="ACTIVE"):
        now = int(time.time()*1000)
        starts = now-1000 if starts is None else starts
        ends = now+3600000 if ends is None else ends
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO goods(title,description) VALUES('S1 test','isolated')")
            goods = cur.lastrowid
            cur.execute("INSERT INTO skus(goods_id,price_fen,unallocated_stock) VALUES(%s,1990,%s)", (goods,stock*2))
            sku = cur.lastrowid
            cur.execute("INSERT INTO activities(name,starts_at_ms,ends_at_ms,status) VALUES('S1 fixture',%s,%s,%s)", (starts,ends,status))
            activity = cur.lastrowid
            cur.execute("UPDATE skus SET unallocated_stock=unallocated_stock-%s WHERE id=%s AND unallocated_stock>=%s", (stock,sku,stock))
            self.assertEqual(cur.rowcount,1)
            cur.execute("INSERT INTO activity_stock VALUES(%s,%s,%s,%s,1990,1,0)", (activity,sku,stock,stock))
        self.db.commit()
        key = f"s1:{self.run_id}:seckill:{{{activity}:{sku}}}:ledger"
        self.keys.append(key)
        self.assertEqual(self.scripts["preload"](keys=[key],args=[stock,starts,ends,status,1,1990,activity,sku])[0], "INITIALIZED")
        return key, activity, sku

    def reserve(self, user=1, request=None, reservation=None, key=None, epoch=1):
        request, reservation = request or uid(), reservation or uid()
        result = self.scripts["reserve"](keys=[key or self.key], args=[user,request,reservation,epoch,"s1-test"])
        return result, request, reservation

    def mark(self, request, reservation, old, new, user=1, key=None):
        return self.scripts["mark_request"](keys=[key or self.key], args=[user,request,reservation,1,old,new])

    def release(self, request, reservation, event=None, reason="FAILED", user=1):
        return self.scripts["release"](keys=[self.key],args=[user,request,reservation,1,event or uid(),reason])

    def order(self, user, request, reservation, activity=None, sku=None):
        for attempt in range(6):
            try:
                return self.order_once(user,request,reservation,activity,sku)
            except pymysql.err.OperationalError as error:
                if error.args[0] not in (1213,1205) or attempt == 5:
                    raise
                time.sleep(0.01 * 2**attempt)

    def order_once(self, user, request, reservation, activity=None, sku=None):
        """Exercise the future consumer's DB transaction invariants, not its service."""
        activity, sku = activity or self.activity, sku or self.sku
        connection = connect(self.database)
        try:
            connection.begin()
            now = int(time.time()*1000)
            with connection.cursor() as cur:
                # Lock parent stock BEFORE child FK inserts to avoid shared-lock
                # upgrade cycles; all consumers must follow the same lock order.
                cur.execute("SELECT epoch,price_fen FROM activity_stock WHERE activity_id=%s AND sku_id=%s FOR UPDATE",(activity,sku))
                if cur.fetchone() != (1,1990):
                    raise RuntimeError("Activity version/price conflict")
                cur.execute("INSERT INTO seckill_requests VALUES(%s,%s,%s,%s,%s,1,1990,'QUEUED',%s,NULL)",
                    (reservation,request,activity,sku,user,now))
                cur.execute("UPDATE activity_stock SET available_stock=available_stock-1,version=version+1 WHERE activity_id=%s AND sku_id=%s AND available_stock>0", (activity,sku))
                if cur.rowcount != 1:
                    connection.rollback(); return "SOLD_OUT"
                order_id = uid()
                cur.execute("INSERT INTO orders VALUES(%s,%s,%s,%s,%s,1,1990,'PENDING_PAYMENT',%s,%s,0)",
                    (order_id,reservation,activity,sku,user,now,now+900000))
                cur.execute("INSERT INTO outbox_events(event_id,reservation_id,kind,payload,next_attempt_at_ms,created_at_ms) VALUES(%s,%s,'ORDER_CREATED',%s,%s,%s)",
                    (uid(),reservation,json.dumps({"orderId":order_id}),now,now))
                cur.execute("UPDATE seckill_requests SET status='ORDER_CREATED' WHERE reservation_id=%s", (reservation,))
            connection.commit(); return "CREATED"
        except pymysql.err.IntegrityError as error:
            connection.rollback(); return "DUPLICATE" if error.args[0] == 1062 else "INTEGRITY_ERROR"
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    def test_migration_replay(self):
        self.assertEqual(self.migration_first,"APPLIED")
        self.assertEqual(migrate(self.db),"ALREADY_APPLIED")
        with self.db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()")
            self.assertEqual(cur.fetchone()[0],12)

    def test_migration_drift_rejected(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT sha256 FROM schema_migrations WHERE version='001_schema'")
            original=cur.fetchone()[0]
            cur.execute("UPDATE schema_migrations SET sha256=REPEAT('0',64) WHERE version='001_schema'")
        self.db.commit()
        try:
            with self.assertRaises(RuntimeError): migrate(self.db)
        finally:
            with self.db.cursor() as cur: cur.execute("UPDATE schema_migrations SET sha256=%s WHERE version='001_schema'",(original,))
            self.db.commit()

    def test_seed_replay_does_not_reset_stock(self):
        self.assertEqual(seed_demo(self.db),"SEEDED")
        with self.db.cursor() as cur: cur.execute("UPDATE activity_stock SET available_stock=99 WHERE activity_id=900001")
        self.db.commit()
        self.assertEqual(seed_demo(self.db),"ALREADY_SEEDED")
        with self.db.cursor() as cur:
            cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=900001")
            self.assertEqual(cur.fetchone()[0],99)

    def test_preload_cannot_overwrite(self):
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.scripts["preload"](keys=[self.key],args=[100,1,9999999999999,"ACTIVE",2,10,1,1])[0],"ALREADY_INITIALIZED")
        self.assertEqual(self.redis.hgetall(self.key),before)
        self.assertEqual(self.redis.ttl(self.key),-1)

    def test_preheat_rejects_active_or_partial_stock(self):
        with self.assertRaises(RuntimeError): preheat(self.db,self.redis,self.activity,self.sku)
        with self.db.cursor() as cur:
            cur.execute("UPDATE activities SET status='READY' WHERE id=%s",(self.activity,))
            cur.execute("UPDATE activity_stock SET available_stock=9 WHERE activity_id=%s AND sku_id=%s",(self.activity,self.sku))
        self.db.commit()
        with self.assertRaises(RuntimeError): preheat(self.db,self.redis,self.activity,self.sku)

    def test_preload_invalid_no_side_effect(self):
        key=self.key+":bad"; self.keys.append(key)
        self.assertEqual(self.scripts["preload"](keys=[key],args=[-1,1,2,"ACTIVE",1,10,1,1])[0],"INVALID_ARGUMENT")
        self.assertFalse(self.redis.exists(key))

    def test_valid_reservation_and_event(self):
        result,request,reservation=self.reserve()
        self.assertEqual(result[0],"RESERVED")
        self.assertEqual(self.redis.hget(self.key,"stock"),"9")
        self.assertEqual(self.redis.hget(self.key,"user:1"),reservation)
        event=json.loads(self.redis.hget(self.key,"pending:"+reservation))
        self.schema.validate(event)
        self.assertEqual(event["reservationId"],event["eventId"])
        self.assertEqual(event["requestId"],request)
        self.assertEqual(event["priceFen"],"1990")

    def test_same_request_replay(self):
        _,request,reservation=self.reserve()
        before=self.redis.hgetall(self.key)
        result,_,_=self.reserve(request=request)
        self.assertEqual(result[0],"REPLAY")
        self.assertEqual(json.loads(result[1])["reservationId"],reservation)
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_same_user_different_request(self):
        self.reserve()
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.reserve()[0][0],"ALREADY_PURCHASED")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_wrong_epoch_no_side_effect(self):
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.reserve(epoch=2)[0][0],"STALE_EPOCH")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_invalid_argument_no_side_effect(self):
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.reserve(request="invalid:request")[0][0],"INVALID_ARGUMENT")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_wrong_type_no_side_effect(self):
        key=self.key+":wrongtype"; self.keys.append(key); self.redis.set(key,"unchanged")
        self.assertEqual(self.reserve(key=key)[0][0],"NOT_READY")
        self.assertEqual(self.redis.get(key),"unchanged")

    def test_invalid_user_and_uuid_no_side_effect(self):
        before=self.redis.hgetall(self.key)
        for user in [0,-1,"9223372036854775808"]:
            self.assertEqual(self.reserve(user=user)[0][0],"INVALID_ARGUMENT")
        self.assertEqual(self.reserve(request="not-a-uuid")[0][0],"INVALID_ARGUMENT")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_not_started_ended_and_not_ready(self):
        now=int(time.time()*1000)
        for key,expected in [(self.ledger(starts=now+3600000,ends=now+7200000)[0],"NOT_STARTED"),
                             (self.ledger(starts=now-10000,ends=now-1000)[0],"ENDED"),
                             (self.ledger(status="READY")[0],"NOT_READY")]:
            before=self.redis.hgetall(key)
            self.assertEqual(self.reserve(key=key)[0][0],expected)
            self.assertEqual(self.redis.hgetall(key),before)

    def test_concurrent_inventory_no_oversell(self):
        key,_,_=self.ledger(stock=30)
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            results=list(pool.map(lambda user:self.reserve(user=user,key=key)[0][0],range(1,201)))
        self.assertEqual(results.count("RESERVED"),30)
        self.assertEqual(results.count("SOLD_OUT"),170)
        self.assertEqual(self.redis.hget(key,"stock"),"0")

    def test_concurrent_one_user_one_reservation(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            results=list(pool.map(lambda _:self.reserve()[0][0],range(100)))
        self.assertEqual(results.count("RESERVED"),1)
        self.assertEqual(results.count("ALREADY_PURCHASED"),99)
        self.assertEqual(self.redis.hget(self.key,"stock"),"9")

    def test_release_requires_termination(self):
        _,request,reservation=self.reserve()
        self.assertEqual(self.release(request,reservation)[0],"STATE_CONFLICT")
        self.assertEqual(self.redis.hget(self.key,"stock"),"9")

    def test_concurrent_release_once_and_preserve_qualification(self):
        _,request,reservation=self.reserve()
        self.assertEqual(self.mark(request,reservation,"RESERVED","COMPENSATING")[0],"UPDATED")
        event=uid()
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            results=list(pool.map(lambda _:self.release(request,reservation,event)[0],range(100)))
        self.assertEqual(results.count("RELEASED"),1)
        self.assertEqual(results.count("REPLAY"),99)
        self.assertEqual(self.redis.hget(self.key,"stock"),"10")
        self.assertEqual(self.redis.hget(self.key,"pending:"+reservation),"")
        self.assertEqual(self.reserve()[0][0],"ALREADY_PURCHASED")
        self.assertEqual(self.release(request,reservation)[0],"ALREADY_RELEASED")

    def test_release_wrong_reservation_or_epoch(self):
        _,request,reservation=self.reserve()
        self.mark(request,reservation,"RESERVED","COMPENSATING")
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.release(request,uid())[0],"RESERVATION_CONFLICT")
        self.assertEqual(self.scripts["release"](keys=[self.key],args=[1,request,reservation,2,uid(),"FAILED"])[0],"STALE_EPOCH")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_release_event_collision_rejected(self):
        _,request,reservation=self.reserve()
        self.mark(request,reservation,"RESERVED","COMPENSATING")
        event=uid(); self.release(request,reservation,event)
        _,request2,reservation2=self.reserve(user=2)
        self.mark(request2,reservation2,"RESERVED","COMPENSATING",user=2)
        self.assertEqual(self.release(request2,reservation2,event,user=2)[0],"RELEASE_CONFLICT")
        self.assertEqual(self.redis.hget(self.key,"stock"),"9")

    def test_paid_order_never_released(self):
        _,request,reservation=self.reserve()
        self.mark(request,reservation,"RESERVED","QUEUED")
        self.mark(request,reservation,"QUEUED","ORDER_CREATED")
        self.assertEqual(self.scripts["mark_order"](keys=[self.key],args=[1,request,reservation,1,"PAID"])[0],"UPDATED")
        self.assertEqual(self.release(request,reservation,reason="CLOSED")[0],"STATE_CONFLICT")
        self.assertEqual(self.scripts["mark_order"](keys=[self.key],args=[1,request,reservation,1,"CLOSED"])[0],"STATE_CONFLICT")
        self.assertEqual(self.redis.hget(self.key,"stock"),"9")

    def test_closed_order_released_once(self):
        _,request,reservation=self.reserve()
        self.mark(request,reservation,"RESERVED","QUEUED")
        self.mark(request,reservation,"QUEUED","ORDER_CREATED")
        self.scripts["mark_order"](keys=[self.key],args=[1,request,reservation,1,"CLOSED"])
        event=uid()
        self.assertEqual(self.release(request,reservation,event,reason="CLOSED")[0],"RELEASED")
        self.assertEqual(self.release(request,reservation,event,reason="CLOSED")[0],"REPLAY")
        self.assertEqual(self.redis.hget(self.key,"stock"),"10")

    def test_terminal_request_cannot_regress(self):
        _,request,reservation=self.reserve()
        self.mark(request,reservation,"RESERVED","QUEUED")
        self.mark(request,reservation,"QUEUED","ORDER_CREATED")
        before=self.redis.hgetall(self.key)
        self.assertEqual(self.mark(request,reservation,"ORDER_CREATED","QUEUED")[0],"STATE_CONFLICT")
        self.assertEqual(self.redis.hgetall(self.key),before)

    def test_mysql_parallel_stock_guard(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results=list(pool.map(lambda user:self.order(user,uid(),uid()),range(1,51)))
        self.assertEqual(results.count("CREATED"),10)
        self.assertEqual(results.count("SOLD_OUT"),40)
        with self.db.cursor() as cur:
            cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s",(self.activity,self.sku))
            self.assertEqual(cur.fetchone()[0],0)
            cur.execute("SELECT COUNT(*) FROM orders WHERE activity_id=%s",(self.activity,))
            self.assertEqual(cur.fetchone()[0],10)

    def test_mysql_duplicate_messages_and_business_qualification(self):
        request,reservation=uid(),uid()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results=list(pool.map(lambda _:self.order(1,request,reservation),range(30)))
        self.assertEqual(results.count("CREATED"),1)
        self.assertEqual(results.count("DUPLICATE"),29)
        self.assertEqual(self.order(1,uid(),uid()),"DUPLICATE")
        with self.db.cursor() as cur:
            cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s",(self.activity,self.sku))
            self.assertEqual(cur.fetchone()[0],9)
            cur.execute("SELECT COUNT(*) FROM seckill_requests WHERE activity_id=%s",(self.activity,))
            self.assertEqual(cur.fetchone()[0],1)

    def test_mysql_constraints_and_transaction_rollback(self):
        with self.db.cursor() as cur:
            with self.assertRaises(pymysql.err.OperationalError):
                cur.execute("UPDATE activity_stock SET available_stock=initial_stock+1 WHERE activity_id=%s",(self.activity,))
        self.db.rollback()
        self.assertEqual(self.order(99999,uid(),uid()),"INTEGRITY_ERROR")
        with self.db.cursor() as cur:
            cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=%s",(self.activity,))
            self.assertEqual(cur.fetchone()[0],10)

    def test_mysql_expired_payment_blocked(self):
        reservation=uid(); self.assertEqual(self.order(1,uid(),reservation),"CREATED")
        with self.db.cursor() as cur:
            cur.execute("UPDATE orders SET created_at_ms=1, expires_at_ms=2 WHERE reservation_id=%s",(reservation,))
            cur.execute("UPDATE orders SET status='PAID' WHERE reservation_id=%s AND status='PENDING_PAYMENT' AND expires_at_ms>CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED)",(reservation,))
            self.assertEqual(cur.rowcount,0)
            cur.execute("UPDATE orders SET status='CLOSED' WHERE reservation_id=%s AND status='PENDING_PAYMENT' AND expires_at_ms<=CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED)",(reservation,))
            self.assertEqual(cur.rowcount,1)
        self.db.commit()

    def test_real_redis_aof_confirmation(self):
        result,_,_=self.reserve()
        self.assertEqual(result[0],"RESERVED")
        # WAITAOF covers writes on the SAME connection. Use a nontransactional pipeline.
        with self.redis.pipeline(transaction=False) as pipe:
            pipe.hset(self.key,"s1-durability-check","1")
            pipe.execute_command("WAITAOF",1,0,1000)
            response=pipe.execute()
        self.assertEqual(response[-1][0],1)
        self.assertEqual(self.redis.config_get("appendfsync")["appendfsync"],"always")

if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(S1Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            mysql_version=cur.fetchone()[0]
    report={"stage":"S1","platform":sys.platform,"system":platform.platform(),
        "mysql":mysql_version,"redis":cache().info("server")["redis_version"],
        "tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
        "skipped":len(result.skipped),"passed":result.wasSuccessful(),
        "scope":"real storage/Lua/SQL harness; not RocketMQ or Java order service"}
    target=ROOT/"tests/reports/wsl/s1-integration.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))
    sys.exit(0 if result.wasSuccessful() else 1)
