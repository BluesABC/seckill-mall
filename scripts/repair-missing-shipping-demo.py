"""单笔旧MOCK无收货信息订单修复：默认只读预览，--apply才模拟退款并逻辑删除。

仅供有数据库维护权限的本地操作，不提供HTTP绕过入口。不物理删除订单，不回补
已付款秒杀库存/资格；库存/订单/退款凭证保留。与Orders.refund一致先锁活动、后订单。
"""
import argparse
import json
import uuid
from data import connect


def repair(db, order_id, apply=False):
    order_id = str(uuid.UUID(order_id))
    db.begin()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT activity_id,sku_id FROM orders WHERE id=%s", (order_id,))
            seed = cur.fetchone()
            if seed is None:
                raise ValueError('Order not found')
            cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s FOR UPDATE", seed)
            stock = cur.fetchone()[0]
            cur.execute("SELECT user_id,status FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            user, state = cur.fetchone()
            cur.execute("SELECT order_id FROM shop_seckill_delivery WHERE order_id=%s", (order_id,))
            if cur.fetchone() is not None:
                raise ValueError('Order has shipping information; refusing repair')
            cur.execute("SELECT id FROM wx_payments WHERE order_kind='SECKILL' AND order_id=%s", (order_id,))
            if cur.fetchone() is not None:
                raise ValueError('Real payment intent; refusing repair')
            cur.execute("SELECT id,amount_fen,provider,status FROM payments WHERE order_id=%s", (order_id,))
            paid = cur.fetchone()
            if state != 'PAID' or paid is None or paid[2:] != ('MOCK', 'SUCCEEDED'):
                raise ValueError('Only paid MOCK legacy orders are eligible')
            result = dict(orderId=order_id, eligible=True, applied=apply, retainedOrder=True,
                          retainedPayment=True, stockUnchanged=stock)
            if apply:
                cur.execute("SELECT id FROM mock_refunds WHERE payment_id=%s", (paid[0],))
                if cur.fetchone() is None:
                    retry = str(uuid.uuid5(uuid.NAMESPACE_URL, 'missing-shipping-demo:'+order_id))
                    cur.execute("INSERT INTO mock_refunds(id,payment_id,idempotency_key,amount_fen,created_at_ms) VALUES(%s,%s,%s,%s,CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED))",
                                (str(uuid.uuid4()), paid[0], retry, paid[1]))
                cur.execute("INSERT IGNORE INTO order_deletions(order_kind,order_id,user_id,deleted_at_ms) VALUES('SECKILL',%s,%s,CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED))", (order_id, user))
                cur.execute("SELECT available_stock FROM activity_stock WHERE activity_id=%s AND sku_id=%s", seed)
                assert cur.fetchone()[0] == stock
        if apply:
            db.commit()
        else:
            db.rollback()
        return result
    except BaseException:
        db.rollback()
        raise


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with connect(os.environ.get('MALL_DB_NAME','seckill_mall')) as db:
        print(json.dumps(repair(db, args.order_id, args.apply)))
