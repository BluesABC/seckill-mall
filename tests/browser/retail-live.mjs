/** 真实本机HTTP商城验收：独立用户/鞋款，最终下架夹具，不清理业务卷或订单。 */
import {readyForScreenshot} from './screenshot-ready.mjs';
import {chromium,expect} from '../../build/wsl/browser/node_modules/@playwright/test/index.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.SHOP_BASE_URL||'http://localhost:18080';
if(!process.env.MALL_ADMIN_PASSWORD)throw Error('MALL_ADMIN_PASSWORD required');
async function api(path,body,token,method){const res=await fetch(base+path,{method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});const result=await res.json();if(!res.ok)throw Error(path+' '+res.status+' '+JSON.stringify(result));return result;}
async function demoPay(page,token,capture=false){
 await page.getByRole('button',{name:'去支付',exact:true}).click();
 const dialog=page.getByRole('dialog');await expect(dialog.getByRole('heading',{name:'选择支付方式',exact:true})).toBeVisible();
 await expect(dialog.getByRole('radio',{name:/微信扫码（模拟）/})).toBeChecked();
 await dialog.getByRole('button',{name:'下一步',exact:true}).click();
 await expect(dialog.getByRole('img',{name:'模拟微信支付演示二维码，无法真实付款',exact:true})).toBeVisible();
 const pending=(await api('/api/shop/orders',null,token)).items.find(o=>o.status==='PENDING_PAYMENT');if(!pending)throw Error('QR must leave order pending');
 if(capture){await writeFile('build/wsl/t062-demo-qr.txt',await dialog.getByRole('img').getAttribute('src'));await mkdir('tests/reports/wsl/mock-cashier',{recursive:true});for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});if(await dialog.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Dialog overflow');await page.screenshot({path:`tests/reports/wsl/mock-cashier/qr-${width}.png`});}}
 await dialog.getByRole('button',{name:'模拟已支付',exact:true}).click();
 await expect(dialog.getByRole('heading',{name:'模拟支付成功',exact:true})).toBeVisible();
 await dialog.getByRole('button',{name:'查看订单',exact:true}).click();
 await expect(dialog).not.toBeVisible();
}
const admin=(await api('/api/auth/login',{username:'admin',password:process.env.MALL_ADMIN_PASSWORD})).token;
const product={title:'AERO/01 · 商城验收专用',description:'独立验收鞋款，结束后自动下架，无实物寄送。',imageUrl:'/assets/shoe-run-v1.webp',priceFen:'69900',stock:'8'};
const g=await api('/api/admin/goods',product,admin);
await api('/api/admin/skus/'+g.skuId,{sizeEu:'42',category:'跑步',colorway:'白 / 荧光黄'},admin,'PATCH');
const username='shop_'+Date.now(),password='Retail-test-only-2026';
await api('/api/auth/register',{username,password});
const session=await api('/api/auth/login',{username,password});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(s=>sessionStorage.setItem('shijian.session',JSON.stringify(s)),session);
 await page.goto(base+`/#/product/${g.goodsId}/${g.skuId}`);
 await page.getByRole('button',{name:'尺码 42',exact:true}).click();
 await expect(page.getByRole('button',{name:'立即购买',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'加入购物车',exact:true}).click();
 await expect(page.getByRole('heading',{name:'购物车',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:product.title,exact:true})).toBeVisible();
 await page.getByLabel('数量',{exact:false}).selectOption('2');
 await expect(page.getByText('购物车已更新',{exact:true})).toBeVisible();
 await page.goto(base+'/#/shop/addresses');
 await page.getByLabel('收货人',{exact:true}).fill('测试收货人');
 await page.getByLabel('联系电话',{exact:true}).fill('13800138000');
 await page.getByLabel('完整收货地址',{exact:true}).fill('上海市运动路100号 演示地址');
 await page.getByRole('button',{name:'保存地址',exact:true}).click();
 await expect(page.getByText('收货地址已保存',{exact:true})).toBeVisible();
 await page.goto(base+'/#/shop/cart');
 await expect(page.getByRole('heading',{name:product.title,exact:true})).toBeVisible();
 await readyForScreenshot(page);
 await mkdir('tests/reports/wsl/retail',{recursive:true});
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:1000});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow at '+width);
  await page.screenshot({path:`tests/reports/wsl/retail/cart-${width}.png`,fullPage:true});
 }
 await page.getByRole('button',{name:'提交订单，前往模拟支付',exact:true}).click();
 await expect(page.getByRole('heading',{name:'普通商城订单',exact:true})).toBeVisible();
 await demoPay(page,session.token,true);
 await expect(page.getByRole('button',{name:'未发货全额退款',exact:true})).toBeVisible();
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'未发货全额退款',exact:true}).click();
 await expect(page.locator('.commerce-order strong').filter({hasText:/^已退款$/})).toBeVisible();
 let orders=(await api('/api/shop/orders',null,session.token)).items;
 if(orders[0].status!=='REFUNDED'||orders[0].amount_fen!=='139800')throw Error('Refund/amount mismatch');
 await page.goto(base+`/#/product/${g.goodsId}/${g.skuId}`);
 await page.getByRole('button',{name:'尺码 42',exact:true}).click();
 await page.getByRole('button',{name:'立即购买',exact:true}).click();
 await expect(page.getByRole('heading',{name:'确认购买',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'提交订单，前往模拟支付',exact:true}).click();
 await expect(page.getByRole('heading',{name:'普通商城订单',exact:true})).toBeVisible();
 await demoPay(page,session.token);
 await expect(page.getByRole('button',{name:'未发货全额退款',exact:true})).toBeVisible();
 const second=(await api('/api/shop/orders',null,session.token)).items.find(o=>o.status==='PAID');
 if(!second)throw Error('Direct purchase missing');
 await api(`/api/admin/shop/orders/${second.id}/ship`,{carrier:'演示快递',tracking:'DEMO'+Date.now()},admin);
 await page.reload();await page.getByRole('button',{name:'确认收货',exact:true}).click({trial:true});
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'确认收货',exact:true}).click();
 await expect(page.locator('.commerce-order strong').filter({hasText:/^已完成$/})).toBeVisible();
 await page.screenshot({path:'tests/reports/wsl/retail/orders-1440.png',fullPage:true});
 const remaining=(await api('/api/goods/'+g.goodsId)).items.find(x=>x.skuId===g.skuId).unallocatedStock;
 if(remaining!=='7')throw Error('Stock mismatch: '+remaining);
 if(errors.length)throw Error(JSON.stringify(errors));
 const report={passed:true,scope:'real local Java/MySQL commerce HTTP and browser, MOCK money/manual shipment',userId:session.userId,goodsId:g.goodsId,checks:['choose size','server cart quantity','address','390/768/1440 no overflow','checkout amount','payment method selection','demo QR leaves order pending','explicit simulated paid confirmation','full refund','manual shipment','receipt','inventory 8→6→8→7']};
 await writeFile('tests/reports/wsl/t059-retail-browser.json',JSON.stringify(report,null,2));console.log('PASS retail live browser');
}finally{
 await browser.close();await api('/api/admin/goods/'+g.goodsId,{title:product.title,description:product.description,imageUrl:product.imageUrl,enabled:false},admin,'PATCH');
}
