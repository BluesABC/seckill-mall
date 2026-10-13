"""MySQL migration/demo seed and first-time Redis preheat; no live stock overwrite."""
import argparse
import hashlib
import os
import re
import time
from pathlib import Path

import pymysql
import redis
from pymysql.constants import CLIENT

ROOT = Path(__file__).resolve().parents[1]

def connect(database=None):
    return pymysql.connect(host=os.environ.get("MALL_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("MALL_DB_PORT", "13306")),
        user=os.environ.get("MALL_DB_USER", "mall"),
        password=os.environ["MALL_DB_PASSWORD"], database=database,
        charset="utf8mb4", autocommit=False, client_flag=CLIENT.MULTI_STATEMENTS)

def cache():
    return redis.Redis.from_url(os.environ.get("MALL_REDIS_URL", "redis://127.0.0.1:16379/0"),
        decode_responses=True, socket_timeout=5)

def migrate(connection):
    text = (ROOT / "scripts/sql/001_schema.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    with connection.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) PRIMARY KEY, sha256 CHAR(64) NOT NULL)")
        cur.execute("SELECT sha256 FROM schema_migrations WHERE version='001_schema'")
        row = cur.fetchone()
        if row:
            if row[0] != digest:
                raise RuntimeError("Applied schema changed; add a new migration, do not overwrite history")
            first_applied = False
        else:
            first_applied = True
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name <> 'schema_migrations'")
        if first_applied and cur.fetchone()[0]:
            raise RuntimeError("Untracked/partial schema detected; migrate a clean database, do not overwrite tables")
        # MySQL DDL commits implicitly. Partial failure must be repaired explicitly.
        if first_applied:
            cur.execute(text)
            while cur.nextset(): pass
            cur.execute("INSERT INTO schema_migrations VALUES ('001_schema', %s)", (digest,))
        for path in sorted((ROOT / "scripts/sql").glob("[0-9][0-9][0-9]_*.sql")):
            if path.stem == "001_schema": continue
            migration = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(migration.encode()).hexdigest()
            cur.execute("SELECT sha256 FROM schema_migrations WHERE version=%s", (path.stem,))
            applied = cur.fetchone()
            if applied:
                if applied[0] != checksum: raise RuntimeError("Applied schema changed; add a new migration")
                continue
            cur.execute(migration)
            while cur.nextset(): pass
            cur.execute("INSERT INTO schema_migrations VALUES (%s,%s)", (path.stem,checksum))
            first_applied = True
    connection.commit()
    return "APPLIED" if first_applied else "ALREADY_APPLIED"

def seed_demo(connection):
    demo_id = 900001
    now = int(time.time() * 1000)
    connection.begin()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT initial_stock, price_fen FROM activity_stock WHERE activity_id=%s AND sku_id=%s FOR UPDATE", (demo_id, demo_id))
            row = cur.fetchone()
            if row:
                if row != (100, 1990):
                    raise RuntimeError("Demo ID already belongs to incompatible data")
                connection.rollback()
                return "ALREADY_SEEDED"
            cur.execute("INSERT INTO goods(id,title,description,enabled) VALUES (%s,%s,%s,1)", (demo_id, "秒杀演示商品", "S1开发种子商品，库存100"))
            cur.execute("INSERT INTO skus(id,goods_id,price_fen,unallocated_stock,version) VALUES (%s,%s,1990,200,0)", (demo_id, demo_id))
            cur.execute("INSERT INTO activities VALUES (%s,%s,%s,%s,'READY')", (demo_id, "开发秒杀演示", now - 1000, now + 3600000))
            cur.execute("UPDATE skus SET unallocated_stock=unallocated_stock-100, version=version+1 WHERE id=%s AND unallocated_stock>=100", (demo_id,))
            if cur.rowcount != 1:
                raise RuntimeError("Insufficient unallocated stock")
            cur.execute("INSERT INTO activity_stock VALUES (%s,%s,100,100,1990,1,0)", (demo_id, demo_id))
        connection.commit()
        return "SEEDED"
    except Exception:
        connection.rollback()
        raise

def preheat(connection, client, activity_id, sku_id):
    with connection.cursor() as cur:
        cur.execute("SELECT s.available_stock, a.starts_at_ms, a.ends_at_ms, a.status, s.epoch, s.price_fen, s.initial_stock FROM activity_stock s JOIN activities a ON a.id=s.activity_id WHERE s.activity_id=%s AND s.sku_id=%s FOR UPDATE", (activity_id, sku_id))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Activity/SKU not found")
        # Never reconstruct a running, missing ledger from just available_stock.
        cur.execute("SELECT COUNT(*) FROM seckill_requests WHERE activity_id=%s AND sku_id=%s", (activity_id, sku_id))
        if cur.fetchone()[0] != 0:
            raise RuntimeError("Existing requests require reconciliation, not initial preheat")
        if row[3] != "READY":
            raise RuntimeError("Initial preheat requires READY activity; ACTIVE recovery needs reconciliation")
        if row[0] != row[6]:
            raise RuntimeError("Initial stock is not intact; reconcile instead of rebuilding a partial ledger")
    key = f"seckill:{{{activity_id}:{sku_id}}}:ledger"
    script = client.register_script((ROOT / "src/seckill/lua/preload.lua").read_text(encoding="utf-8"))
    return script(keys=[key], args=[*map(str, row[:6]), str(activity_id), str(sku_id)])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "seed", "preheat"])
    parser.add_argument("--database", default="seckill_mall")
    parser.add_argument("--activity", type=int, default=900001)
    parser.add_argument("--sku", type=int, default=900001)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", args.database):
        parser.error("Invalid database identifier")
    with connect(args.database) as connection:
        if args.command == "migrate": print(migrate(connection))
        elif args.command == "seed": print(seed_demo(connection))
        else: print(preheat(connection, cache(), args.activity, args.sku))

if __name__ == "__main__":
    main()
