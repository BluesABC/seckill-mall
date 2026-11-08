"""普通商城只读账本核对，不自动修复库存，也不代表真实支付/物流对账。"""
import os,json
from data import connect

def inspect():
    with connect(os.environ.get('MALL_DB_NAME','seckill_mall')) as db:
        with db.cursor() as c:
            c.execute('SET TRANSACTION READ ONLY')
            c.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            checks={
                'ORDER_AMOUNT': "SELECT COUNT(*) FROM shop_orders o LEFT JOIN (SELECT order_id,SUM(quantity*price_fen) AS amount FROM shop_items GROUP BY order_id) i ON i.order_id=o.id WHERE i.amount IS NULL OR o.amount_fen<>i.amount",
                'PAYMENT_STATE': "SELECT COUNT(*) FROM shop_orders WHERE (status IN ('PAID','SHIPPED','DELIVERED','REFUNDED') AND (payment_id IS NULL OR paid_at_ms IS NULL)) OR (status IN ('PENDING_PAYMENT','CLOSED') AND payment_id IS NOT NULL)",
                'REFUND_STATE': "SELECT COUNT(*) FROM shop_orders WHERE (status='REFUNDED' AND (refund_id IS NULL OR refunded_at_ms IS NULL)) OR (status<>'REFUNDED' AND refund_id IS NOT NULL)",
                'SHIPMENT_STATE': "SELECT COUNT(*) FROM shop_orders WHERE status IN ('SHIPPED','DELIVERED') AND (carrier IS NULL OR tracking IS NULL OR shipped_at_ms IS NULL)",
                'DELIVERY_STATE': "SELECT COUNT(*) FROM shop_orders WHERE status='DELIVERED' AND delivered_at_ms IS NULL"
            }
            counts={}
            for name,query in checks.items():
                c.execute(query);counts[name]=c.fetchone()[0]
    return {'scope':'ordinary order snapshots and MOCK state; no external settlement','checks':counts,'result':'CLEAN' if not any(counts.values()) else 'DRIFT'}
if __name__=='__main__':
    report=inspect();print(json.dumps(report));raise SystemExit(0 if report['result']=='CLEAN' else 1)
