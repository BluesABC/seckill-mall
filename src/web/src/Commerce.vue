<script setup lang="ts">
/** 普通商城工作台：服务器购物车、地址、合并结算及物流；与秒杀订单分开显示。 */
import WechatPay from './WechatPay.vue';
import MockCashier from './MockCashier.vue';
import {computed,onMounted,onUnmounted,ref,watch} from 'vue';
import {api,money,date,message,paymentConfig,paymentRemaining,type Session,type Goods} from './api';
const props=defineProps<{session:Session|null; route:string}>();
const emit=defineEmits<{login:[]}>();
type Address={id:string;recipient:string;phone:string;address:string};
type Cart={skuId:string;title:string;sizeEu:string;priceFen:string;quantity:string;imageUrl:string;stock:string};
type Item={sku_id:string;title:string;size_eu:string;quantity:string;price_fen:string;image_url:string};
type ShopOrder={provider?:string;source?:string;id:string;status:string;amount_fen:string;recipient:string;phone:string;address:string;created_at_ms:string;expires_at_ms:string;payment_id?:string;refund_id?:string;carrier?:string;tracking?:string;items:Item[]};
const cart=ref<Cart[]>([]),addresses=ref<Address[]>([]),orders=ref<ShopOrder[]>([]),selected=ref(''),busy=ref(false),loading=ref(false),error=ref(''),notice=ref('');
const paymentProvider=ref('MOCK');
const wxManaged=ref<Record<string,boolean>>({});
const stockForm=ref({skuId:'',quantity:'1'});
const form=ref({recipient:'',phone:'',address:''});
const direct=ref<Cart|null>(null),filter=ref('ALL');
const tab=computed(()=>props.route.split('/')[2]||'cart');
const admin=computed(()=>tab.value==='admin' && props.session?.role==='ADMIN');
const checkoutItems=computed(()=>direct.value?[direct.value]:cart.value);
const total=computed(()=>checkoutItems.value.reduce((sum,i)=>sum+BigInt(i.priceFen)*BigInt(i.quantity),0n).toString());
const labels:Record<string,string>={PENDING_PAYMENT:'待支付',PAID:'待发货',SHIPPED:'待收货',DELIVERED:'已完成',CLOSED:'已取消',REFUNDED:'已退款'};
const visibleOrders=computed(()=>orders.value.filter(o=>(filter.value==='ALL'||o.status===filter.value)&&(!props.route.split('/')[3]||o.id===props.route.split('/')[3])));
const shipping=ref<Record<string,{carrier:string;tracking:string}>>({});
let generation=0;
async function load(){
 const version=++generation;error.value='';direct.value=null;
 if(!props.session){cart.value=[];addresses.value=[];orders.value=[];return;}
 loading.value=true;
 try{
  const config=await paymentConfig();if(version!==generation)return;paymentProvider.value=config.provider;
  const [c,a,o,seconds]=await Promise.all([
   api<{items:Cart[]}>('/api/shop/cart',props.session),api<{items:Address[]}>('/api/shop/addresses',props.session),
   api<{items:ShopOrder[]}>(admin.value?'/api/admin/shop/orders':'/api/shop/orders',props.session),api<{items:ShopOrder[]}>(admin.value?'/api/admin/shop/seckill/orders':'/api/shop/seckill/orders',props.session)]);
  if(version!==generation)return;
  cart.value=c.items;addresses.value=a.items;orders.value=tab.value==='seckill'?seconds.items:(admin.value||tab.value==='all')?[...o.items,...seconds.items].sort((a,b)=>Number(b.created_at_ms)-Number(a.created_at_ms)):o.items;
  if(!a.items.some(v=>v.id===selected.value))selected.value=a.items[0]?.id||'';
  if(tab.value==='buy'){
   const sid=props.route.split('/')[3],gid=props.route.split('/')[4];
   const variants=await api<{items:Goods[]}>(`/api/goods/${encodeURIComponent(gid||'')}`,props.session);
   if(version!==generation)return;
   const g=variants.items.find(g=>g.skuId===sid);if(!g)throw Error('商品已下架，请返回鞋款目录。');
   direct.value={skuId:g.skuId,title:g.title,sizeEu:g.sizeEu||'',priceFen:g.priceFen,quantity:'1',imageUrl:g.imageUrl,stock:g.unallocatedStock};
  }
 }catch(e){if(version===generation)error.value=message(e);}
 finally{if(version===generation)loading.value=false;}
}
/** 所有变更均禁用重复点击，未知结果保留结算键，允许查询/重试而不是重复下单。 */
async function run(action:()=>Promise<unknown>,success:string){
 if(busy.value)return;busy.value=true;error.value='';notice.value='';
 try{await action();notice.value=success;await load();}catch(e){error.value=message(e);}finally{busy.value=false;}
}
function quantity(item:Cart,event:Event){
 const q=(event.target as HTMLSelectElement).value;
 if(direct.value){direct.value={...direct.value,quantity:q};return;}
 void run(()=>api('/api/shop/cart',props.session,{skuId:item.skuId,quantity:q},'PUT'),'购物车已更新');
}
function remove(item:Cart){void run(()=>api(`/api/shop/cart/${item.skuId}`,props.session,undefined,'DELETE'),'已移除商品');}
function saveAddress(){void run(async()=>{const a=await api<{id:string}>('/api/shop/addresses',props.session,form.value);selected.value=a.id;form.value={recipient:'',phone:'',address:''};},'收货地址已保存');}
function deleteAddress(id:string){if(window.confirm('删除这个地址？已下单的收货信息不会改变。'))void run(()=>api(`/api/shop/addresses/${id}`,props.session,undefined,'DELETE'),'地址已删除');}
async function checkout(){
 if(!selected.value || !checkoutItems.value.length)return;
 const body={addressId:selected.value,items:checkoutItems.value.map(i=>({skuId:i.skuId,quantity:i.quantity}))};
 const key=`shop.checkout.${props.session?.userId}.${JSON.stringify(body)}`;
 let retry=sessionStorage.getItem(key);if(!retry){retry=crypto.randomUUID();sessionStorage.setItem(key,retry);}
 await run(async()=>{const created=await api<{id:string}>('/api/shop/checkout',props.session,{...body,idempotencyKey:retry});sessionStorage.removeItem(key);location.hash='/shop/orders/'+created.id;},'订单已创建，请模拟支付');
}
function action(o:ShopOrder,action:string){
 if(action==='cancel'&&o.source==='SECKILL'){
  if(window.confirm('确认取消这笔秒杀订单？未支付库存将通过原补偿流程恢复。'))void run(()=>api(`/api/shop/seckill/${o.id}/cancel`,props.session,{}),'秒杀订单已取消');return;
 }
 const question=action==='refund'?(o.source==='SECKILL'?'确认秒杀模拟退款？不恢复活动库存或购买资格，无真实资金变动。':'确认全额模拟退款并取消未发货订单？库存将恢复，无真实资金变动。'):action==='cancel'?'确认取消待支付订单？库存将恢复。':action==='receive'?'确认已收到商品？本项目仅演示物流登记。':'';
 if(question && !window.confirm(question))return;
 const url=o.source==='SECKILL'?(action==='receive'?`/api/shop/seckill/${o.id}/receive`:`/api/order/${action}`):`/api/shop/orders/${o.id}/${action}`;
 void run(()=>api(url,props.session,{...(o.source==='SECKILL'&&action!=='receive'?{orderId:o.id}:{}),idempotencyKey:crypto.randomUUID()}),action==='pay'?'模拟支付完成，无真实扣款':'订单已更新');
}
function deleteOrder(o:ShopOrder){
 if(!window.confirm('确认删除这笔订单？将从你的订单列表移除，交易凭证和库存记录仍保留。'))return;
 void run(async()=>{await api(o.source==='SECKILL'?`/api/shop/seckill/${o.id}`:`/api/shop/orders/${o.id}`,props.session,undefined,'DELETE');
  if(props.route.split('/')[3])location.hash=o.source==='SECKILL'?'/shop/seckill':'/shop/orders';
 },'订单已删除');
}
function restock(){
 const body={skuId:String(stockForm.value.skuId),quantity:String(stockForm.value.quantity)};const key=`shop.restock.${props.session?.userId}.${JSON.stringify(body)}`;
 let retry=sessionStorage.getItem(key);if(!retry){retry=crypto.randomUUID();sessionStorage.setItem(key,retry);}
 if(!window.confirm(`确认给SKU ${body.skuId} 补货 ${body.quantity} 双？`))return;
 void run(async()=>{await api('/api/admin/shop/restock',props.session,{...body,idempotencyKey:retry});sessionStorage.removeItem(key);stockForm.value={skuId:'',quantity:'1'};},'普通库存补货已登记');
}
function attachAddress(o:ShopOrder){if(!selected.value){error.value='请先选择地址';return;}void run(()=>api(`/api/shop/seckill/${o.id}/address`,props.session,{addressId:selected.value}),'秒杀订单收货地址已保存');}
function ship(o:ShopOrder){const b=shipping.value[o.id];if(!b?.carrier||!b.tracking){error.value='请填写承运商和物流单号';return;}void run(()=>api(o.source==='SECKILL'?`/api/admin/shop/seckill/${o.id}/ship`:`/api/admin/shop/orders/${o.id}/ship`,props.session,b),'发货信息已登记');}
const paymentClock=ref(Date.now());
let paymentTicker: ReturnType<typeof setInterval> | undefined;
let lastExpiryRefresh=0;
onMounted(()=>{
 paymentTicker=setInterval(()=>{
  paymentClock.value=Date.now();
  if(!props.session||loading.value||busy.value||paymentClock.value-lastExpiryRefresh<5000)return;
  if(!visibleOrders.value.some(o=>o.status==='PENDING_PAYMENT' && Number(o.expires_at_ms)>0
    && Number(o.expires_at_ms)<=paymentClock.value))return;
  lastExpiryRefresh=paymentClock.value;
  void load();
 },1000);
});
onUnmounted(()=>clearInterval(paymentTicker));
watch(()=>[props.route,props.session?.userId],()=>{filter.value='ALL';notice.value='';void load();},{immediate:true});
</script>
<template>
 <section class="container page-section commerce">
  <div class="commerce-title"><div><p class="commerce-context">普通购物 · SNKR//DROP</p><h1 tabindex="-1">{{admin?'订单发货管理':tab==='all'?'我的订单':tab==='orders'?'普通商城订单':tab==='seckill'?'秒杀订单履约':tab==='addresses'?'收货地址':tab==='buy'?'确认购买':'购物车'}}</h1></div><a href="#/catalog">继续选购 →</a></div>
  <nav class="commerce-tabs" aria-label="普通商城"><a href="#/orders">全部订单</a><a href="#/shop/cart">购物车</a><a href="#/shop/addresses">收货地址</a><a href="#/shop/orders">普通订单</a><a href="#/shop/seckill">秒杀收货</a><a href="#/requests">抢购请求查询</a><a v-if="session?.role==='ADMIN'" href="#/shop/admin">发货管理</a></nav>
  <p class="muted">普通购买按原价使用独立可售库存。{{paymentProvider==='WECHAT'?'微信支付会产生真实扣款；物流仍为手工登记。':'支付与物流为演示，不会扣款或寄送实物。'}}</p>
  <div v-if="!session" class="empty"><h2>登录后继续购买</h2><p>购物车与订单保存到你的账号。</p><button class="button" @click="emit('login')">登录 / 注册</button></div>
  <template v-else>
   <p v-if="error" role="alert" class="error">{{error}} <button :disabled="busy" @click="load">重新查询</button></p>
   <p v-if="notice" role="status">{{notice}}</p><p v-if="loading" role="status">正在加载…</p>
   <template v-if="tab==='cart'||tab==='buy'">
    <div class="commerce-grid"><div><div v-if="!checkoutItems.length&&!loading" class="empty"><h2>购物车还没有鞋款</h2><a class="button" href="#/catalog">探索全部鞋款</a></div>
     <article v-for="item in checkoutItems" :key="item.skuId" class="commerce-item">
      <img :src="item.imageUrl" :alt="item.title"><div><h2>{{item.title}}</h2><p>EU {{item.sizeEu||'未标注'}} · 原价 ¥{{money(item.priceFen)}}</p><p class="muted">当前可售 {{item.stock}} 双，以结算结果为准</p><label>数量 <select :value="item.quantity" :disabled="busy" @change="quantity(item,$event)"><option v-for="n in 10" :key="n" :value="String(n)">{{n}}</option></select></label><button v-if="!direct" class="underlink" :disabled="busy" @click="remove(item)">移除</button></div><strong>¥{{money((BigInt(item.priceFen)*BigInt(item.quantity)).toString())}}</strong>
     </article>
    </div><aside class="commerce-summary"><h2>订单摘要</h2><p class="commerce-total"><span>商品合计</span><strong>¥{{money(total)}}</strong></p><p class="small muted">演示商城免运费，金额由服务端重新核算。</p><label for="checkout-address">收货地址</label><select id="checkout-address" v-model="selected" :disabled="busy"><option value="">请选择收货地址</option><option v-for="a in addresses" :key="a.id" :value="a.id">{{a.recipient}} · {{a.address}}</option></select><a href="#/shop/addresses">管理收货地址</a><button class="button full" :disabled="busy||loading||!selected||!checkoutItems.length" @click="checkout">{{busy?'正在提交…':paymentProvider==='WECHAT'?'提交订单，前往微信支付':'提交订单，前往模拟支付'}}</button><p class="small muted">请在订单的支付截止时间前完成付款。超时或取消后释放普通库存。</p></aside></div>
   </template>
   <div v-else-if="tab==='addresses'" class="commerce-grid">
    <div><article v-for="a in addresses" :key="a.id" class="address-row"><h2>{{a.recipient}} · {{a.phone}}</h2><p>{{a.address}}</p><button class="underlink" :disabled="busy" @click="deleteAddress(a.id)">删除地址</button></article><p v-if="!addresses.length&&!loading">尚未添加地址。请填写右侧表单。</p></div>
    <form class="commerce-summary" @submit.prevent="saveAddress"><h2>新增收货地址</h2><label for="recipient">收货人</label><input id="recipient" v-model="form.recipient" autocomplete="name" maxlength="60" required><label for="phone">联系电话</label><input id="phone" v-model="form.phone" type="tel" autocomplete="tel" minlength="5" maxlength="30" required><label for="street">完整收货地址</label><textarea id="street" v-model="form.address" autocomplete="street-address" minlength="5" maxlength="400" required></textarea><button class="button" :disabled="busy">保存地址</button></form>
   </div>
   <template v-else>
    <form v-if="admin" class="ship-form" @submit.prevent="restock"><label>补货SKU ID<input v-model="stockForm.skuId" required pattern="[1-9][0-9]*" inputmode="numeric"></label><label>补货双数<input v-model="stockForm.quantity" type="number" min="1" max="1000000" required></label><button class="secondary" :disabled="busy">登记普通库存补货</button><a href="#/admin">商品、尺码与活动管理 →</a></form>
    <a v-if="tab==='orders' && props.route.split('/')[3]" href="#/shop/orders">← 查看全部订单</a>
    <div class="commerce-filters"><label>订单状态 <select v-model="filter"><option value="ALL">全部</option><option v-for="(label,state) in labels" :key="state" :value="state">{{label}}</option></select></label><button class="underlink" :disabled="busy" @click="load">刷新订单</button></div>
    <div v-if="!visibleOrders.length&&!loading" class="empty">暂无符合条件的订单。<a href="#/catalog">去选购</a></div>
    <article v-for="o in visibleOrders" :key="o.id" class="commerce-order">
     <header><div><strong>{{o.source==='SECKILL'?'秒杀 · ':''}}{{labels[o.status]||o.status}}</strong><p class="small muted">下单时间：{{date(o.created_at_ms)}}</p><p>订单号：{{o.id}}</p></div><strong>¥{{money(o.amount_fen)}}</strong><p v-if="o.status==='PENDING_PAYMENT'" class="order-payment-deadline">
       <strong>支付倒计时 · {{paymentRemaining(o.expires_at_ms,paymentClock)}}</strong>
       <span>支付截止：{{date(o.expires_at_ms)}}</span>
      </p></header>
     <div v-for="i in o.items" :key="i.sku_id" class="commerce-item"><img :src="i.image_url" :alt="i.title"><div><h2>{{i.title}}</h2><p>EU {{i.size_eu||'未标注'}} · {{i.quantity}} 双 · 单价 ¥{{money(i.price_fen)}}</p></div></div>
     <details open><summary>收货信息与支付凭证</summary><p>收货人：{{o.recipient||"尚未填写"}} · {{o.phone}}</p><p>收货地址：{{o.address||"尚未填写"}}</p><p v-if="o.payment_id">模拟支付凭证：{{o.payment_id}}</p><p v-if="o.refund_id">全额模拟退款凭证：{{o.refund_id}}</p><p v-if="o.carrier">物流：{{o.carrier}} · {{o.tracking}}（手工演示登记）</p></details>
     <p v-if="admin&&o.source==='SECKILL'&&o.status==='PAID'&&!o.address" class="muted">等待用户填写收货地址后才能发货。</p><form v-if="admin&&o.status==='PAID'&&(o.source!=='SECKILL'||o.address)" class="ship-form" @submit.prevent="ship(o)"><label>承运商<input :value="shipping[o.id]?.carrier||''" required maxlength="60" @input="shipping[o.id]={carrier:($event.target as HTMLInputElement).value,tracking:shipping[o.id]?.tracking||''}"></label><label>物流单号<input :value="shipping[o.id]?.tracking||''" required pattern="[A-Za-z0-9-]+" maxlength="100" @input="shipping[o.id]={tracking:($event.target as HTMLInputElement).value,carrier:shipping[o.id]?.carrier||''}"></label><button class="button" :disabled="busy">登记发货</button></form>
     <div v-if="!admin&&o.source==='SECKILL'&&o.status==='PAID'" class="ship-form"><label>秒杀收货地址<select v-model="selected"><option value="">请选择地址</option><option v-for="a in addresses" :key="a.id" :value="a.id">{{a.recipient}} · {{a.address}}</option></select></label><button class="secondary" :disabled="busy||!selected" @click="attachAddress(o)">保存本单收货信息</button></div>
     <MockCashier v-if="!admin&&paymentProvider==='MOCK'&&o.provider!=='WECHAT'" :session="session" :order-id="o.id" :order-kind="o.source==='SECKILL'?'SECKILL':'SHOP'" :order-state="o.status" :amount-fen="o.amount_fen" @updated="load" />
     <WechatPay v-if="!admin&&paymentProvider==='WECHAT'" :session="session" :order-id="o.id" :order-kind="o.source==='SECKILL'?'SECKILL':'SHOP'" :order-state="o.status" @updated="load" @config="paymentProvider=$event.provider" @managed="wxManaged[o.id]=$event" />
     <div v-if="!admin" class="commerce-actions"><template v-if="o.status==='PENDING_PAYMENT'"><button v-if="!wxManaged[o.id]&&o.provider!=='WECHAT'" class="secondary" :disabled="busy" @click="action(o,'cancel')">取消订单</button></template><button v-if="o.status==='PAID'&&o.provider!=='WECHAT'" class="secondary" :disabled="busy" @click="action(o,'refund')">未发货全额退款</button><button v-if="o.status==='SHIPPED'" class="button" :disabled="busy" @click="action(o,'receive')">确认收货</button><button v-if="['CLOSED','REFUNDED','DELIVERED'].includes(o.status)" class="secondary" :disabled="busy" @click="deleteOrder(o)">删除订单</button></div>
    </article>
   </template>
  </template>
 </section>
</template>
<style scoped>
.commerce{max-width:1200px;min-height:65vh}.commerce-title{display:flex;justify-content:space-between;gap:24px;align-items:center}.commerce-title h1{font-size:clamp(24px,3vw,32px);margin:8px 0 22px}.commerce-tabs{display:flex;gap:24px;flex-wrap:wrap;padding:14px 0;border-bottom:1px solid #ddd;margin-bottom:20px}.commerce-grid{display:grid;grid-template-columns:minmax(0,1fr) 350px;gap:48px;margin-top:32px}.commerce-item{display:flex;gap:20px;padding:24px 0;border-bottom:1px solid #ddd;align-items:center}.commerce-item img{width:110px;height:110px;object-fit:contain;background:#f5f5f5}.commerce-item h2{font-size:17px;margin:0}.commerce-item>div{flex:1;min-width:0}.commerce-item>strong{white-space:nowrap}.commerce select,.commerce input,.commerce textarea{max-width:100%;border:1px solid #aaa;border-radius:0;background:white;color:#111;padding:12px;font:inherit}.commerce-summary{align-self:start;padding:24px;background:#f6f6f4;display:flex;flex-direction:column;gap:16px}.commerce-summary h2{font-size:22px;margin:0}.commerce-total{display:flex;justify-content:space-between;gap:12px}.commerce-summary textarea{min-height:100px}.address-row{padding:24px 0;border-bottom:1px solid #ddd}.address-row h2{font-size:18px}.commerce-filters{display:flex;justify-content:space-between;gap:20px;margin:24px 0}.commerce-order{margin:0 0 24px;padding:clamp(14px,3vw,24px);border:1px solid #b7b7b2;border-radius:14px;background:#fff;box-shadow:0 2px 8px #0000000a}.commerce-order header{display:flex;justify-content:space-between;gap:12px 20px;padding:14px 16px;border-radius:8px;background:#f3f3ef}.commerce-order header>div{min-width:0}.commerce-order header>strong{white-space:nowrap}.commerce-order p,.commerce-order details{overflow-wrap:anywhere}.commerce-order summary{cursor:pointer;padding:16px 0}.commerce-actions,.ship-form{display:flex;gap:14px;flex-wrap:wrap;margin-top:20px}.ship-form label{display:flex;flex-direction:column;gap:8px}.commerce button:focus-visible,.commerce a:focus-visible,.commerce select:focus-visible,.commerce input:focus-visible,.commerce textarea:focus-visible{outline:3px solid #111;outline-offset:3px}.commerce button{min-height:44px}.commerce .underlink{margin-left:12px}@media(max-width:760px){.commerce-grid{grid-template-columns:1fr;gap:24px}.commerce-title{align-items:flex-start}.commerce-tabs{gap:16px}.commerce-item{gap:12px;flex-wrap:wrap}.commerce-item img{width:80px;height:80px}.commerce-item>strong{margin-left:auto;flex-basis:100%;text-align:right}.commerce-order header{flex-wrap:wrap}.commerce{padding-left:16px;padding-right:16px}.commerce-summary{padding:20px}.ship-form label{width:100%}}
.commerce-order header{flex-wrap:wrap}
.order-payment-deadline{flex:0 0 100%;display:flex;flex-wrap:wrap;gap:4px 16px;align-items:center;margin:0;padding-top:10px;border-top:1px solid #d4d4cf;color:#873411}
.order-payment-deadline strong{font-variant-numeric:tabular-nums}
.order-payment-deadline span{font-size:.85em;color:#4c4c49}
</style>
