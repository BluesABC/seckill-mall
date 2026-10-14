"""Explicit demo seeding: refuse to change any nonempty catalog or live stock."""
import json,os,time,urllib.request
from data import connect
URL=os.environ.get('MALL_ORDER_URL','http://127.0.0.1:8082')
def call(path,body,token=None,method='POST'):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(URL+path,data=json.dumps(body).encode(),headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
with connect(os.environ.get('MALL_DB_NAME','seckill_mall')) as db:
    with db.cursor() as cur:cur.execute('SELECT COUNT(*) FROM goods');count=cur.fetchone()[0]
if count:print('Catalog already contains data; no products or stock modified');raise SystemExit(0)
session=call('/api/auth/login',{'username':os.environ['MALL_ADMIN_USERNAME'],'password':os.environ['MALL_ADMIN_PASSWORD']});token=session['token']
products=[('AERO/01 · 轻量跑鞋','shoe-run-v1.webp','109900','89900','42','跑步','白 / 荧光黄'),('COURT/02 · 实战篮球鞋','shoe-court-v1.webp','99900','79900','42','篮球','钴蓝 / 黑'),('STREET/03 · 城市休闲鞋','shoe-street-v1.webp','49900','39900','42','休闲','米白 / 酒红'),('AERO/01 WOMEN · 跑步鞋','shoe-run-v1.webp','69900','59900','38.5','跑步','白 / 荧光黄')]
now=int(time.time()*1000)
for title,image,price,deal,size,category,color in products:
    g=call('/api/admin/goods',{'title':title,'description':f'原创概念运动鞋，EU{size}，{color}。仅作项目演示，无实物性能承诺。','imageUrl':'/assets/'+image,'priceFen':price,'stock':'30'},token)
    call('/api/admin/skus/'+g['skuId'],{'sizeEu':size,'category':category,'colorway':color},token,'PATCH')
    a=call('/api/admin/activities',{'name':'DROP 01 · 限时发售','skuId':g['skuId'],'stock':'10','priceFen':deal,'startsAtMs':str(now-60000),'endsAtMs':str(now+86400000)},token)
    call('/api/admin/activities/'+a['activityId']+'/activate',{'skuId':g['skuId']},token)
print('Seeded 4 original sneaker SKUs and real activities')
