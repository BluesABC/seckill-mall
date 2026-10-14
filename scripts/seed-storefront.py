"""Seed the original demo shoes with real per-size SKUs and independent activities.

This script only runs against an empty catalog. It never edits a populated catalog.
"""
import json, os, time, urllib.request
from data import connect

URL = os.environ.get('MALL_ORDER_URL', 'http://127.0.0.1:8082')

def call(path, body, token=None, method='POST'):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(),
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)

with connect(os.environ.get('MALL_DB_NAME', 'seckill_mall')) as db:
    with db.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM goods')
        count = cur.fetchone()[0]
if count:
    print('Catalog already contains data; no products or stock modified')
    raise SystemExit(0)

session = call('/api/auth/login', {
    'username': os.environ['MALL_ADMIN_USERNAME'],
    'password': os.environ['MALL_ADMIN_PASSWORD']})
token = session['token']
products = [
    ('AERO/01 · 轻量跑鞋', 'shoe-run-v1.webp', '109900', '89900', 39, 46,
     '跑步', '白 / 荧光黄'),
    ('COURT/02 · 实战篮球鞋', 'shoe-court-v1.webp', '99900', '79900', 39, 46,
     '篮球', '钴蓝 / 黑'),
    ('STREET/03 · 城市休闲鞋', 'shoe-street-v1.webp', '49900', '39900', 39, 46,
     '休闲', '米白 / 酒红'),
    ('AERO/01 WOMEN · 跑步鞋', 'shoe-run-v1.webp', '69900', '59900', 35, 42,
     '跑步', '白 / 荧光黄'),
]
sizes = lambda low, high: [f'{n // 2}{".5" if n % 2 else ""}' for n in range(low * 2, high * 2 + 1)]
now = int(time.time() * 1000)
sku_count = activity_count = 0
for title, image, price, deal, low, high, category, color in products:
    range_sizes = sizes(low, high)
    base_size = range_sizes[0]
    g = call('/api/admin/goods', {
        'title': title,
        'description': f'原创概念运动鞋，EU {low}–{high} 半码段，{color}。仅作项目演示，无实物性能承诺。',
        'imageUrl': '/assets/' + image, 'priceFen': price, 'stock': '30'}, token)
    call('/api/admin/skus/' + g['skuId'], {
        'sizeEu': base_size, 'category': category, 'colorway': color}, token, 'PATCH')
    sku_ids = [(g['skuId'], base_size)]
    for size in range_sizes[1:]:
        sku = call(f"/api/admin/goods/{g['goodsId']}/skus",
                   {'sizeEu': size, 'stock': '30'}, token)
        sku_ids.append((sku['skuId'], size))
    for sku_id, size in sku_ids:
        activity = call('/api/admin/activities', {
            'name': 'DROP 01 · 限时发售', 'skuId': sku_id, 'stock': '10',
            'priceFen': deal, 'startsAtMs': str(now - 60000),
            'endsAtMs': str(now + 86400000)}, token)
        call('/api/admin/activities/' + activity['activityId'] + '/activate',
             {'skuId': sku_id}, token)
        sku_count += 1
        activity_count += 1
print(f'Seeded {len(products)} sneaker styles, {sku_count} size SKUs and '
      f'{activity_count} independent real activities')
