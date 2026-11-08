/** 微信收银区界面夹具：不连接微信；二维码来自本地状态机测试，非真实收款码。 */
import {chromium,expect} from '../../build/wsl/browser/node_modules/@playwright/test/index.mjs';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('build/wsl/web/dist'),qr=await readFile('build/wsl/t060-test-qr.txt','utf8');
const server=createServer(async(req,res)=>{try{let file=path.resolve(root,req.url==='/'?'index.html':req.url.split('?')[0].slice(1));if(!file.startsWith(root+path.sep))throw Error();res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/webp');res.end(await readFile(file));}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 let configured=false,state='NOT_STARTED',orderState='PENDING_PAYMENT',refundCalls=0;
 const id='11111111-1111-4111-8111-111111111111';
 await page.addInitScript(()=>sessionStorage.setItem('shijian.session',JSON.stringify({token:'a'.repeat(64),userId:'1',role:'USER',expiresAtMs:String(Date.now()+3600000)})));
 await page.route('**/api/**',async route=>{
  const p=new URL(route.request().url()).pathname;let data={items:[]};
  if(p==='/api/auth/me')data={userId:'1',role:'USER'};
  if(p==='/api/payments/config')data={provider:configured?'WECHAT':'MOCK',wechatConfigured:configured};
  if(p==='/api/shop/orders')data={items:[{id,status:orderState,amount_fen:'1990',provider:configured?'WECHAT':'MOCK',recipient:'测试收货人',phone:'13800138000',address:'本地界面夹具地址',created_at_ms:String(Date.now()),expires_at_ms:String(Date.now()+600000),items:[]}]};
  if(p==='/api/payments/wechat/native')state='PREPAY';
  if(p==='/api/payments/wechat/refund'){refundCalls++;state='REFUNDING';}
  if(p==='/api/payments/wechat/close'){state='CLOSED';orderState='CLOSED';}
  if(p.startsWith('/api/payments/wechat/'))data={state,amount_fen:'1990',expires_at_ms:String(Date.now()+600000),...(state==='PREPAY'?{qrImage:qr}:{}),...(['SUCCESS','REFUNDING','REFUNDED'].includes(state)?{transaction_id:'fixture-transaction'}:{}),...(state==='REFUNDED'?{refund_id:'fixture-refund'}:{})};
  await route.fulfill({json:data});
 });
 const url=`http://127.0.0.1:${server.address().port}/#/shop/orders`;
 await page.goto(url);await expect(page.getByRole('button',{name:'去支付',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'获取微信支付二维码',exact:true})).toHaveCount(0);
 configured=true;await page.reload();await expect(page.getByRole('button',{name:'获取微信支付二维码',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'去支付',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'获取微信支付二维码',exact:true}).click();
 const image=page.getByRole('img',{name:/请用微信扫一扫/});await expect(image).toBeVisible();
 await expect(page.getByText('请使用微信扫描二维码支付',{exact:true})).toBeVisible();
 if(orderState!=='PENDING_PAYMENT'||await image.evaluate(e=>e.naturalWidth)!==280)throw Error('QR is not a payment success');
 await mkdir('tests/reports/wsl/wechat-ui',{recursive:true});
 await page.evaluate(()=>{const note=document.createElement('p');note.textContent='界面测试夹具 · 非真实微信收款二维码';note.style.cssText='background:#111;color:white;padding:12px;text-align:center';document.body.prepend(note);});
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width);await page.screenshot({path:`tests/reports/wsl/wechat-ui/qr-fixture-${width}.png`,fullPage:true});}
 state='SUCCESS';orderState='PAID';await page.getByRole('button',{name:'查询微信结果',exact:true}).click();
 await expect(page.getByText('微信支付已确认',{exact:true})).toBeVisible();
 page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'申请微信全额退款',exact:true}).click();if(refundCalls)throw Error('Cancelled confirmation submitted refund');
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'申请微信全额退款',exact:true}).click();await expect(page.getByText('原路退款处理中',{exact:true})).toBeVisible();
 state='REFUNDED';orderState='REFUNDED';await page.getByRole('button',{name:'查询微信结果',exact:true}).click();await expect(page.getByText('微信退款已确认',{exact:true})).toBeVisible();
 state='PREPAY';orderState='PENDING_PAYMENT';await page.reload();page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'关闭微信支付并取消订单',exact:true}).click();await expect(page.getByText('微信支付已关闭',{exact:true})).toBeVisible();
 if(errors.length)throw Error(JSON.stringify(errors));
 await writeFile('tests/reports/wsl/t060-wechat-ui.json',JSON.stringify({passed:true,scope:'UI fixture, no merchant or WeChat network; QR is not a real payment code',checks:['MOCK offers demo cashier only','real mode hides MOCK','280px local QR','QR does not mark paid','390/768/1440 responsive','payment from query','refund confirmation','processing is not success','confirmed refund','confirmed close']},null,2));console.log('PASS WeChat UI fixture');
}finally{await browser.close();await new Promise(r=>server.close(r));}
