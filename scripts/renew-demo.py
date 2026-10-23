"""为已过期的演示鞋款新建七天场次；只分配剩余未分配库存，不重置旧账本。"""
import json
import os
import time
import urllib.request
from data import connect


def call(path, body, token=None):
    """调用真实管理接口；不打印密码或会话令牌，失败交由调用方排查。"""
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(os.environ.get('MALL_ORDER_URL', 'http://127.0.0.1:8082') + path,
        data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    now = int(time.time() * 1000)
    # 仅选择项目原创演示鞋款；只读查询，库存划拨完全由管理API事务完成。
    with connect(os.environ.get('MALL_DB_NAME', 'seckill_mall')) as db:
        with db.cursor() as cursor:
            cursor.execute("""SELECT s.id,s.unallocated_stock,COALESCE(
                (SELECT ast.price_fen FROM activity_stock ast WHERE ast.sku_id=s.id
                 ORDER BY ast.activity_id DESC LIMIT 1),s.price_fen)
                FROM skus s JOIN goods g ON g.id=s.goods_id
                WHERE g.enabled=1 AND g.title IN
                ('AERO/01 · 轻量跑鞋','COURT/02 · 实战篮球鞋',
                 'STREET/03 · 城市休闲鞋','AERO/01 WOMEN · 跑步鞋')
                AND NOT EXISTS (SELECT 1 FROM activity_stock ast JOIN activities a
                  ON a.id=ast.activity_id WHERE ast.sku_id=s.id
                  AND a.status IN ('READY','ACTIVE') AND a.ends_at_ms>%s)
                ORDER BY s.id""", (now,))
            rows = cursor.fetchall()
    if not rows:
        print('No expired demo SKUs need renewal; existing sessions preserved')
        return
    token = call('/api/auth/login', {'username': os.environ['MALL_ADMIN_USERNAME'],
        'password': os.environ['MALL_ADMIN_PASSWORD']})['token']
    created = skipped = 0
    for sku, remaining, price in rows:
        if remaining <= 0:
            skipped += 1
            continue
        activity = call('/api/admin/activities', {'name': 'DROP · 新场限时发售',
            'skuId': str(sku), 'stock': str(min(10, remaining)), 'priceFen': str(price),
            'startsAtMs': str(now - 60000), 'endsAtMs': str(now + 7 * 86400000)}, token)
        # 若激活失败，保留READY记录供管理员重试activate，不自动重复划拨。
        call('/api/admin/activities/' + activity['activityId'] + '/activate',
             {'skuId': str(sku)}, token)
        created += 1
    print(f'Created {created} seven-day sessions; skipped {skipped} SKUs without unallocated stock')


if __name__ == '__main__':
    main()
