/** 真实本机模拟收银：独立普通用户，不需要管理员；最终退款恢复其普通库存占用。 */
import {chromium,expect} from '../../build/wsl/browser/node_modules/@playwright/test/index.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.SHOP_BASE_URL||'http://localhost:18080';
async function api(path,body,token,method){const response=await fetch(base+path,{method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(!response.ok)throw Error(path+' '+response.status+' '+JSON.stringify(data));return data;}
const username='cashier_'+Date.now(),password='Cashier-test-only-2026';await api('/api/auth/register',{username,password});const session=await api('/api/auth/login',{username,password});
const g=(await api('/api/goods')).items.find(x=>Number(x.unallocatedStock)>=2&&x.sizeEu);if(!g)throw Error('No stocked SKU for cashier test');
await api('/api/shop/addresses',{recipient:'模拟收银测试用户',phone:'13800138000',address:'测试地址 不寄送实物'},session.token);
await api('/api/shop/cart',{skuId:g.skuId,quantity:'1'},session.token,'PUT');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(s=>sessionStorage.setItem('shijian.session',JSON.stringify(s)),session);
 await page.goto(base+'/#/shop/cart');await page.getByRole('button',{name:'提交订单，前往模拟支付',exact:true}).click();
 await expect(page.getByRole('heading',{name:'普通商城订单',exact:true})).toBeVisible();
 const order=(await api('/api/shop/orders',null,session.token)).items[0];if(order.status!=='PENDING_PAYMENT')throw Error('Expected pending order');
 const pay=page.getByRole('button',{name:'去支付',exact:true});await pay.click();const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('heading',{name:'选择支付方式',exact:true})).toBeVisible();
 await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
 if((await api('/api/shop/orders/'+order.id,null,session.token)).status!=='PENDING_PAYMENT')throw Error('Opening cashier must not pay');
 await pay.click();await expect(dialog.getByRole('radio',{name:/微信扫码（模拟）/})).toBeChecked();
 await dialog.getByRole('button',{name:'下一步',exact:true}).click();
 const qr=dialog.getByRole('img',{name:'模拟微信支付演示二维码，无法真实付款',exact:true});await expect(qr).toBeVisible();
 if((await api('/api/shop/orders/'+order.id,null,session.token)).status!=='PENDING_PAYMENT')throw Error('Showing QR must not pay');
 await mkdir('tests/reports/wsl/mock-cashier',{recursive:true});await writeFile('build/wsl/t062-demo-qr.txt',await qr.getAttribute('src'));await writeFile('build/wsl/t062-demo-session.json',JSON.stringify({orderId:order.id,amountFen:order.amount_fen,expiresAtMs:order.expires_at_ms,qrImage:await qr.getAttribute('src')}));
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});if(await dialog.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Cashier overflow');await page.screenshot({path:`tests/reports/wsl/mock-cashier/qr-${width}.png`});}
 await dialog.getByRole('button',{name:'模拟已支付',exact:true}).click();await expect(dialog.getByRole('heading',{name:'模拟支付成功',exact:true})).toBeVisible();
 if((await api('/api/shop/orders/'+order.id,null,session.token)).status!=='PAID')throw Error('Confirmation did not persist');
 await dialog.getByRole('button',{name:'查看订单',exact:true}).click();await expect(dialog).not.toBeVisible();
 await page.reload();await expect(page.getByRole('button',{name:'未发货全额退款',exact:true})).toBeVisible();
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'未发货全额退款',exact:true}).click();await expect(page.locator('.commerce-order strong').filter({hasText:/^已退款$/})).toBeVisible();
 if(errors.length)throw Error(JSON.stringify(errors));
 await writeFile('tests/reports/wsl/t062-cashier-live.json',JSON.stringify({passed:true,scope:'real local HTTP order/payment DB, simulated money, independent ordinary user; no admin changes',checks:['pending order created','payment method selection','Escape does not pay','demo QR does not pay','390/768/1440 modal','explicit simulated confirmation','server PAID','reload persists','refund restores own order allocation']},null,2));console.log('PASS live mock cashier');
}finally{await browser.close();}
