/** 本机真实秒杀：无地址阻止提交→填写地址→订单快照→取消→删除；不需要管理员。 */
import {chromium,expect} from '../../build/wsl/browser/node_modules/@playwright/test/index.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.SHOP_BASE_URL||'http://localhost:18080';
async function api(path,body,token,method){const r=await fetch(base+path,{method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(path+' '+r.status+' '+JSON.stringify(data));return data;}
const name='shipping_'+Date.now(),password='Shipping-test-only-2026';
await api('/api/auth/register',{username:name,password});const session=await api('/api/auth/login',{username:name,password});
const goods=(await api('/api/goods')).items,activities=(await api('/api/activities')).items;
let activity,product;
for(const a of activities){const g=goods.find(g=>g.skuId===a.skuId);if(!g||a.status!=='ACTIVE')continue;const info=await api(`/api/seckill/info?activityId=${a.activityId}&skuId=${a.skuId}`);if(info.state==='ACTIVE'&&info.stockAvailable){activity=a;product=g;break;}}
if(!product)throw Error('No active stocked demo campaign; no inventory is reset by this test');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(s=>sessionStorage.setItem('shijian.session',JSON.stringify(s)),session);
 const url=base+`/#/product/${product.goodsId}/${product.skuId}`;
 await page.goto(url);await page.getByRole('button',{name:'尺码 '+product.sizeEu,exact:true}).click();await page.getByRole('button',{name:/^立即抢购/}).click();
 const dialog=page.getByRole('dialog');await expect(dialog.getByLabel('收货地址（必选）')).toBeVisible();
 await expect(dialog.getByRole('button',{name:'验证并抢购',exact:true})).toBeDisabled();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Shipping dialog horizontal overflow');
 await mkdir('tests/reports/wsl/shipping-delete',{recursive:true});
 await page.screenshot({path:'tests/reports/wsl/shipping-delete/address-required.png'});
 await dialog.getByRole('link',{name:'管理收货地址',exact:true}).click();
 await page.getByLabel('收货人',{exact:true}).fill('秒杀测试收货人');
 await page.getByLabel('联系电话',{exact:true}).fill('13800138000');
 await page.getByLabel('完整收货地址',{exact:true}).fill('秒杀测试收货路100号 不寄送实物');
 await page.getByRole('button',{name:'保存地址',exact:true}).click();
 await expect(page.getByText('收货地址已保存',{exact:true})).toBeVisible();
 await page.goto(url);await page.getByRole('button',{name:'尺码 '+product.sizeEu,exact:true}).click();await page.getByRole('button',{name:/^立即抢购/}).click();
 await expect(dialog.getByLabel('收货地址（必选）')).not.toHaveValue('');
 await dialog.getByRole('button',{name:'改用屏幕阅读器友好的文字题',exact:true}).click();
 const text=await dialog.locator('.captcha-prompt').innerText();const values=text.match(/\d+/g).map(Number);
 await dialog.getByLabel('验证码',{exact:true}).fill(String(values[0]+values[1]));
 await dialog.getByRole('button',{name:'验证并抢购',exact:true}).click();
 await expect(page.getByRole('heading',{name:'待支付',exact:true})).toBeVisible({timeout:90000});
 await page.goto(base+'/#/shop/seckill');
 const row=page.locator('.commerce-order').filter({hasText:'秒杀测试收货人'});await expect(row).toBeVisible();
 await expect(row).toContainText('秒杀测试收货路100号');await expect(row.getByRole('button',{name:'删除订单',exact:true})).toHaveCount(0);
 page.once('dialog',d=>d.accept());await row.getByRole('button',{name:'取消订单',exact:true}).click();
 await expect(row.getByRole('button',{name:'删除订单',exact:true})).toBeVisible();
 page.once('dialog',d=>d.dismiss());await row.getByRole('button',{name:'删除订单',exact:true}).click();await expect(row).toBeVisible();
 page.once('dialog',d=>d.accept());await row.getByRole('button',{name:'删除订单',exact:true}).click();
 await expect(page.getByText('订单已删除',{exact:true})).toBeVisible();await expect(page.locator('.commerce-order')).toHaveCount(0);
 await page.reload();await expect(page.getByText('暂无符合条件的订单。',{exact:false})).toBeVisible();
 await page.screenshot({path:'tests/reports/wsl/shipping-delete/deleted.png'});
 if(errors.length)throw Error(JSON.stringify(errors));
 await writeFile('tests/reports/wsl/t063-shipping-delete-live.json',JSON.stringify({passed:true,scope:'local real C++/MQ/Java/SQL HTTP + browser; independent test user',checks:['no address disables submit','address book creation','pre-order snapshot','real MQ pending order','no delete on pending','cancel closes owned order','dismiss does not delete','delete hides terminal order','reload stays hidden','no administrator modifications']},null,2));
 console.log('PASS real shipping + cancellation + deletion');
}finally{await browser.close();}
