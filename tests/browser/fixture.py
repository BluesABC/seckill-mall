"""Private owned S5 fixture controls. No application endpoint or test bypass."""
import hashlib,json,os,sys,time
from pathlib import Path
import redis
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from data import connect
config=json.loads((ROOT/'build/wsl/s5-runtime.json').read_text())
assert config['prefix'].startswith('s5_') and config['database'].startswith('mall_s5_')
cache=redis.Redis(port=16379,decode_responses=True)
mode=sys.argv[1]
if mode=='answer':
    a,sku,captcha=sys.argv[2:5]
    key=f'{config["prefix"]}:{{{a}:{sku}}}:challenge:{captcha}'
    proof=json.loads(cache.get(key));proof['answerDigest']=hashlib.sha256(b'123456').hexdigest();cache.set(key,json.dumps(proof),keepttl=True)
elif mode=='expire':
    with connect(config['database']) as db:
        expired_at=int(time.time()*1000)-1000
        with db.cursor() as cur:cur.execute("UPDATE orders SET created_at_ms=%s,expires_at_ms=%s WHERE id=%s AND status='PENDING_PAYMENT'",(expired_at-60000,expired_at,sys.argv[2]));assert cur.rowcount==1
        db.commit()
elif mode=='stock':
    a,sku,stock=sys.argv[2:5];assert stock in ('0','10')
    cache.hset(f'{config["prefix"]}:{{{a}:{sku}}}:ledger','stock',stock)
elif mode=='catalog':
    categories=('跑步','篮球','休闲','训练')
    with connect(config['database']) as db:
        with db.cursor() as cur:
            cur.executemany(
                'INSERT INTO goods(title,description,image_url) VALUES(%s,%s,%s)',
                [(f'PAGINATIONCHECK_{i:02d}', 'browser pagination fixture', '/assets/shoe-run-v1.webp') for i in range(25)])
            cur.execute("SELECT id FROM goods WHERE title LIKE 'PAGINATIONCHECK_%' ORDER BY id DESC")
            ids=[row[0] for row in cur.fetchall()]
            cur.executemany(
                'INSERT INTO skus(goods_id,price_fen,unallocated_stock,size_eu,category,colorway) VALUES(%s,%s,1,%s,%s,%s)',
                [(gid, 80000+i*100, '42', categories[i%4], '黑 / 白') for i,gid in enumerate(ids)])
        db.commit()
elif mode=='clear-catalog':
    with connect(config['database']) as db:
        with db.cursor() as cur:
            cur.execute("DELETE s FROM skus s JOIN goods g ON g.id=s.goods_id WHERE g.title LIKE 'PAGINATIONCHECK_%'")
            cur.execute("DELETE FROM goods WHERE title LIKE 'PAGINATIONCHECK_%'")
        db.commit()
