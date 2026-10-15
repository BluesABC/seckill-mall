"""Read-only, bounded reconciliation. Never reset a live ledger or repair stock."""
import argparse,json,os,time
from data import connect,cache

def inspect(grace=1800,limit=50000,activity_id=None):
    client=cache();prefix=os.environ.get('MALL_KEY_PREFIX','seckill')
    alerts=[];transit=[];unstable=[];ledgers=[]
    def issue(code,a=None):alerts.append({'code':code,'activityId':str(a) if a is not None else None})
    def snapshot(key):
        if client.hlen(key)>limit:raise ValueError('LEDGER_LIMIT_EXCEEDED')
        return client.hgetall(key)
    with connect(os.environ.get('MALL_DB_NAME','seckill_mall')) as db:
        with db.cursor() as c:
            c.execute('SET TRANSACTION READ ONLY')
            c.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            if activity_id is None:
                c.execute('SELECT s.activity_id,s.sku_id,s.initial_stock,s.available_stock,s.epoch,s.price_fen,s.version,a.status FROM activity_stock s JOIN activities a ON a.id=s.activity_id ORDER BY s.activity_id LIMIT 501')
            else:
                c.execute('SELECT s.activity_id,s.sku_id,s.initial_stock,s.available_stock,s.epoch,s.price_fen,s.version,a.status FROM activity_stock s JOIN activities a ON a.id=s.activity_id WHERE s.activity_id=%s ORDER BY s.activity_id LIMIT 501',(activity_id,))
            stocks=c.fetchall()
            if len(stocks)>500:raise ValueError('ACTIVITY_LIMIT_EXCEEDED')
            if activity_id is None:
                c.execute('SELECT reservation_id,version FROM orders ORDER BY reservation_id LIMIT %s',(limit+1,))
            else:
                c.execute('SELECT reservation_id,version FROM orders WHERE activity_id=%s ORDER BY reservation_id LIMIT %s',(activity_id,limit+1))
            versions=c.fetchall()
            if len(versions)>limit:raise ValueError('ORDER_LIMIT_EXCEEDED')
            before={}
            for a,s,*_ in stocks:before[(a,s)]=snapshot(f'{prefix}:{{{a}:{s}}}:ledger')
            now=int(time.time()*1000)
            for a,s,initial,available,epoch,price,version,status in stocks:
                key=f'{prefix}:{{{a}:{s}}}:ledger';h=before[(a,s)];local=[];queued=[]
                c.execute('SELECT reservation_id,status,quantity,version FROM orders WHERE activity_id=%s AND sku_id=%s LIMIT %s',(a,s,limit+1));orders=c.fetchall()
                c.execute('SELECT reservation_id,status FROM seckill_requests WHERE activity_id=%s AND sku_id=%s LIMIT %s',(a,s,limit+1));requests=c.fetchall()
                if max(len(orders),len(requests))>limit:raise ValueError('ROW_LIMIT_EXCEEDED')
                active={r[0] for r in orders if r[1]!='CLOSED'};durable=dict(requests)
                if initial!=available+sum(r[2] for r in orders if r[1]!='CLOSED'):local.append('DB_STOCK_DRIFT')
                if not h:
                    if status!='READY' or requests:local.append('MISSING_LEDGER')
                    for code in local:issue(code,a)
                    continue
                try:
                    held=set();seen=set();pending=sum(1 for k,v in h.items() if k.startswith('pending:') and v)
                    for field,raw in h.items():
                        if not field.startswith('req:'):continue
                        r=json.loads(raw);rid=r['reservationId'];seen.add(rid)
                        if h.get('user:'+field.split(':',2)[1])!=rid:local.append('QUALIFICATION_DRIFT')
                        if not r.get('released',False):
                            if rid in held:local.append('DUPLICATE_RESERVATION')
                            held.add(rid)
                        if rid not in durable and r['state'] in ('RESERVED','QUEUED'):
                            age=max(0,(now-int(r['createdAtMs']))/1000)
                            queued.append(age)
                            if age>grace:local.append('AGED_RESERVATION')
                    if int(h['stock'])<0 or int(h['initialStock'])!=initial or int(h['stock'])+len(held)!=initial:local.append('REDIS_STOCK_DRIFT')
                    if h['epoch']!=str(epoch) or h['priceFen']!=str(price):local.append('METADATA_DRIFT')
                    if int(h.get('pendingCount',0))!=pending:local.append('PENDING_COUNT_DRIFT')
                    if not active.issubset(held):local.append('ACTIVE_ORDER_NOT_HELD')
                    if set(durable)-seen:local.append('DURABLE_REQUEST_MISSING')
                    # DB availability includes reservations not yet made into active orders.
                    if available-int(h['stock'])!=len(held-active):local.append('CROSS_STORE_DRIFT')
                    ledgers.append({'activityId':str(a),'skuId':str(s),'initial':initial,'dbAvailable':available,'redisAvailable':int(h['stock']),'held':len(held),'activeOrders':len(active),'inTransit':len(queued),'pendingSend':pending,'oldestInTransitSeconds':round(max(queued,default=0),3)})
                except (ValueError,KeyError,TypeError):local.append('MALFORMED_LEDGER')
                # A changing ledger/DB version is a moving snapshot, not proof of drift.
                after=snapshot(key)
                if after!=h:unstable.append(str(a))
                else:
                    for code in sorted(set(local)):issue(code,a)
                    if queued:transit.append(str(a))
            if activity_id is None:
                c.execute("SELECT status,COUNT(*),MIN(created_at_ms) FROM outbox_events WHERE status<>'PUBLISHED' GROUP BY status")
                outbox=c.fetchall()
                c.execute("SELECT status,COUNT(*),MIN(updated_at_ms) FROM mq_failures WHERE status<>'RESOLVED' GROUP BY status")
                failures=c.fetchall()
                c.execute('SELECT COUNT(*),COUNT(DISTINCT reservation_id) FROM orders');counts=c.fetchone()
            else:
                c.execute("SELECT o.status,COUNT(*),MIN(o.created_at_ms) FROM outbox_events o JOIN seckill_requests r ON r.reservation_id=o.reservation_id WHERE r.activity_id=%s AND o.status<>'PUBLISHED' GROUP BY o.status",(activity_id,))
                outbox=c.fetchall()
                c.execute("SELECT m.status,COUNT(*),MIN(m.updated_at_ms) FROM mq_failures m JOIN seckill_requests r ON r.reservation_id=JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.reservationId')) WHERE r.activity_id=%s AND m.status<>'RESOLVED' GROUP BY m.status",(activity_id,))
                failures=c.fetchall()
                c.execute('SELECT COUNT(*),COUNT(DISTINCT o.reservation_id) FROM orders o WHERE o.activity_id=%s',(activity_id,));counts=c.fetchone()
            if counts[0]!=counts[1]:issue('DUPLICATE_ORDER')
        db.rollback()
        with db.cursor() as c:
            if activity_id is None:
                c.execute('SELECT activity_id,sku_id,version FROM activity_stock ORDER BY activity_id LIMIT 501')
            else:
                c.execute('SELECT activity_id,sku_id,version FROM activity_stock WHERE activity_id=%s ORDER BY activity_id LIMIT 501',(activity_id,))
            if [(r[0],r[1],r[6]) for r in stocks]!=list(c.fetchall()):unstable.append('DB_CHANGED')
            if activity_id is None:
                c.execute('SELECT reservation_id,version FROM orders ORDER BY reservation_id LIMIT %s',(limit+1,))
            else:
                c.execute('SELECT reservation_id,version FROM orders WHERE activity_id=%s ORDER BY reservation_id LIMIT %s',(activity_id,limit+1))
            if versions!=c.fetchall():unstable.append('ORDERS_CHANGED')
        db.rollback()
    for state,count,oldest in outbox:
        if state=='DEAD' or (now-oldest)/1000>grace:issue('OUTBOX_'+state)
        else:transit.append('OUTBOX')
    for state,count,oldest in failures:
        if state=='QUARANTINED' or (now-oldest)/1000>grace:issue('MQ_'+state)
        else:transit.append('MQ_RETRY')
    # Never emit a clean verdict if the two stores changed during the read window.
    verdict='INCONCLUSIVE' if unstable else 'ALERT' if alerts else 'IN_FLIGHT' if transit else 'CLEAN'
    return {'status':verdict,'readOnly':True,'graceSeconds':grace,'activityId':str(activity_id) if activity_id is not None else None,'orders':counts[0],'ledgers':ledgers,'alerts':alerts,'movingSnapshots':unstable,'outbox':[{'state':s,'count':n} for s,n,t in outbox],'mqFailures':[{'state':s,'count':n} for s,n,t in failures],'atMs':now}

def main():
    p=argparse.ArgumentParser();p.add_argument('--grace-seconds',type=int,default=1800);p.add_argument('--activity-id',type=int);p.add_argument('--limit',type=int,default=50000);p.add_argument('--strict',action='store_true');args=p.parse_args()
    if args.grace_seconds<1:p.error('grace must be positive')
    if args.limit<1 or args.limit>500000:p.error('limit must be 1..500000')
    try:result=inspect(args.grace_seconds,args.limit,activity_id=args.activity_id)
    except Exception as e:result={'status':'UNAVAILABLE','readOnly':True,'error':type(e).__name__}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='CLEAN' or (result['status']=='IN_FLIGHT' and not args.strict) else 2 if result['status']=='ALERT' else 3
if __name__=='__main__':raise SystemExit(main())
