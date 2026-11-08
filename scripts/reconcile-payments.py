"""只读核对MOCK支付/退款凭证与订单；不是外部渠道账单对账。"""
import json
import os
from data import connect


def inspect():
    with connect(os.environ.get('MALL_DB_NAME', 'seckill_mall')) as db:
        with db.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            checks = {
                'PAYMENT_ORDER_MISMATCH': "SELECT COUNT(*) FROM payments p JOIN orders o ON o.id=p.order_id WHERE p.provider='MOCK' AND (o.status<>'PAID' OR p.status<>'SUCCEEDED' OR p.amount_fen<>o.amount_fen)",
                'PAID_WITHOUT_PAYMENT': "SELECT COUNT(*) FROM orders o LEFT JOIN payments p ON p.order_id=o.id WHERE o.status='PAID' AND p.id IS NULL",
                'REFUND_MISMATCH': "SELECT COUNT(*) FROM mock_refunds r JOIN payments p ON p.id=r.payment_id WHERE p.provider<>'MOCK' OR p.status<>'SUCCEEDED' OR r.amount_fen<>p.amount_fen",
            }
            counts = {}
            for name, query in checks.items():
                cursor.execute(query)
                counts[name] = cursor.fetchone()[0]
    return {'scope': 'local MOCK ledger, no external settlement',
            'result': 'CLEAN' if not any(counts.values()) else 'DRIFT', 'checks': counts}


if __name__ == '__main__':
    report = inspect()
    print(json.dumps(report))
    raise SystemExit(0 if report['result'] == 'CLEAN' else 1)
