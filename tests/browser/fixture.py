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
        with db.cursor() as cur:cur.execute("UPDATE orders SET expires_at_ms=%s WHERE id=%s AND status='PENDING_PAYMENT'",(int(time.time()*1000)-1000,sys.argv[2]));assert cur.rowcount==1
        db.commit()
elif mode=='stock':
    a,sku,stock=sys.argv[2:5];assert stock in ('0','10')
    cache.hset(f'{config["prefix"]}:{{{a}:{sku}}}:ledger','stock',stock)
