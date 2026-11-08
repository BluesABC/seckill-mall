/** 支付/退款页面夹具回归；真实交易正确性由S4集成测试验证。 */
import {chromium,expect} from '../../build/wsl/browser/node_modules/@playwright/test/index.mjs';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
const dist=path.resolve('build/wsl/web/dist');
const server=createServer(async(req,res)=>{
 try {const name=req.url==='/'?'index.html':req.url.split('?')[0].slice(1);
 const file=path.resolve(dist,name);if(!file.startsWith(dist+path.sep))throw Error();
 res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'image/webp');
 res.end(await readFile(file));}catch{res.writeHead(404);res.end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try {
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 let refunded=false;
 await page.addInitScript(()=>sessionStorage.setItem('shijian.session',JSON.stringify({token:'a'.repeat(64),userId:'1',role:'USER',expiresAtMs:String(Date.now()+3600000)})));
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url());let data={items:[]};
  if(url.pathname==='/api/payments/config')data={provider:'MOCK',wechatConfigured:false};
  if(url.pathname==='/api/auth/me')data={userId:'1',role:'USER'};
  if(url.pathname==='/api/order/status')data={orderId:'11111111-1111-4111-8111-111111111111',orderState:'PAID',amountFen:'1990'};
  if(url.pathname==='/api/order/refund')refunded=true;
  if(url.pathname==='/api/order/payment')data={paymentState:refunded?'REFUNDED':'SUCCEEDED',paymentId:'mock-payment',paidAmountFen:'1990',...(refunded?{refundId:'mock-refund',refundedAmountFen:'1990'}:{})};
  await route.fulfill({json:data});
 });
 await page.goto(`http://127.0.0.1:${server.address().port}/#/order/11111111-1111-4111-8111-111111111111`);
 await expect(page.getByText('支付状态：模拟支付成功')).toBeVisible();
 page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'模拟全额退款',exact:true}).click();
 if(refunded)throw Error('Cancel must not refund');
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'模拟全额退款',exact:true}).click();
 await expect(page.getByText('支付状态：已模拟全额退款')).toBeVisible();
 await page.reload();await expect(page.getByText('支付状态：已模拟全额退款')).toBeVisible();
 await expect(page.getByRole('button',{name:'模拟全额退款',exact:true})).toHaveCount(0);
 await mkdir('tests/reports/wsl/mock-payment',{recursive:true});
 for(const width of [390,1280]){await page.setViewportSize({width,height:900});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow');
 await page.screenshot({path:`tests/reports/wsl/mock-payment/refunded-${width}.png`,fullPage:true});}
 await writeFile('tests/reports/wsl/mock-payment-ui.json',JSON.stringify({passed:true,scope:'UI fixtures only',checks:['receipt','cancel','refund','reload','390/1280 no overflow']},null,2));
 console.log('PASS mock payment UI');
}finally{await browser.close();await new Promise(r=>server.close(r));}
