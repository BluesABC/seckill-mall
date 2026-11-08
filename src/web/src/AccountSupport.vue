<script setup lang="ts">
import {nextTick,ref} from 'vue';
import {api,ApiError,money,message,type Goods,type Session} from './api';
const props=defineProps<{session:Session|null}>();
const pending=ref(false),error=ref('');
const support=ref<HTMLElement|null>(null);
const visible=ref(false);
const launcher=ref<HTMLButtonElement|null>(null);
const position=ref<{left:number;top:number}|null>(null);
let windowDrag:{id:number;x:number;y:number;left:number;top:number}|null=null;
function startWindow(event:PointerEvent){
 if(!event.isPrimary||event.button!==0||(event.target as HTMLElement).closest('button'))return;
 const box=support.value?.getBoundingClientRect();
 if(!box)return;
 windowDrag={id:event.pointerId,x:event.clientX,y:event.clientY,left:box.left,top:box.top};
 (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}
function moveWindow(event:PointerEvent){
 if(!windowDrag||windowDrag.id!==event.pointerId||!support.value)return;
 const box=support.value.getBoundingClientRect();
 position.value={
  left:Math.max(0,Math.min(innerWidth-box.width,windowDrag.left+event.clientX-windowDrag.x)),
  top:Math.max(0,Math.min(innerHeight-box.height,windowDrag.top+event.clientY-windowDrag.y)),
 };
}
function endWindow(event:PointerEvent){
 if(windowDrag?.id===event.pointerId)windowDrag=null;
}
async function hide(){
 visible.value=false;
 await nextTick();
 launcher.value?.focus();
}
const transcript=ref<HTMLElement|null>(null);
const question=ref('');
type CartChoice = Goods & { quantity: number; saved: boolean };
const messages=ref<{question:string;answer:string;choices?:CartChoice[]}[]>([]);
const savingSku=ref('');
const cartIntent=/加入购物车|加到购物车|放进购物车|放到购物车|加购/;

async function findCartChoices(query:string):Promise<CartChoice[]>{
 const size=query.match(/(\d{2}(?:\.5)?)\s*(?:码|号)/)?.[1];
 const category=['跑步','篮球','休闲','训练'].find(value=>query.includes(value)) || '';
 const name=query.replace(cartIntent,'').replace(/\d{2}(?:\.5)?\s*(?:码|号)/g,'')
   .replace(/(?:帮我|请|把|的那双|这双|一双|鞋子|购物车|[，。！？])/g,'').trim();
 const params=new URLSearchParams({size:'12'});
 if(name)params.set('q',name.slice(0,80));
 const search=()=>api<{items:Goods[]}>('/api/goods/catalog?'+params,props.session);
 let {items}=await search();
 if(!items.length&&category){
  params.delete('q');
  params.set('category',category);
  ({items}=await search());
 }
 if(!name&&!category)return [];
 const products=await Promise.all(items.slice(0,6).map(item=>
  api<{items:Goods[]}>('/api/goods/'+encodeURIComponent(item.goodsId),props.session)));
 return products.flatMap(product=>product.items)
  .filter(sku=>Number(sku.unallocatedStock)>0&&(!size||Number(sku.sizeEu)===Number(size)))
  .slice(0,12).map(sku=>({...sku,quantity:1,saved:false}));
}
async function addChoice(choice:CartChoice){
 if(!props.session||savingSku.value||choice.saved)return;
 savingSku.value=choice.skuId;
 error.value='';
 try{
  const {items}=await api<{items:{skuId:string;quantity:string}[]}>('/api/shop/cart',props.session);
  const existing=items.find(item=>item.skuId===choice.skuId);
  // 保留用户已有数量。用绝对数量写入，重复请求不会重复累加。
  const quantity=Math.max(Number(existing?.quantity||0),choice.quantity);
  if(quantity>Number(choice.unallocatedStock)){
   error.value='当前可售库存不足，请重新查询。';
   return;
  }
  await api('/api/shop/cart',props.session,{skuId:choice.skuId,quantity:String(quantity)},'PUT');
  choice.saved=true;
 }catch(e){error.value=message(e);}
 finally{savingSku.value='';}
}
const offset=ref({x:16,y:16});
let drag:{id:number;x:number;y:number;left:number;top:number}|null=null;
let moved=false;

function start(event:PointerEvent){
 if(!event.isPrimary||event.button!==0)return;
 const button=event.currentTarget as HTMLButtonElement;
 const box=button.getBoundingClientRect();
 drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:box.left,top:box.top};
 moved=false;
 button.setPointerCapture(event.pointerId);
}
function move(event:PointerEvent){
 if(!drag||event.pointerId!==drag.id)return;
 const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
 if(!moved&&Math.hypot(dx,dy)<6)return;
 moved=true;
 const button=event.currentTarget as HTMLButtonElement;
 offset.value={
  x:Math.max(8,Math.min(innerWidth-button.offsetWidth-8,innerWidth-button.offsetWidth-drag.left-dx)),
  y:Math.max(8,Math.min(innerHeight-button.offsetHeight-8,innerHeight-button.offsetHeight-drag.top-dy)),
 };
}
function finish(event:PointerEvent){
 if(drag?.id===event.pointerId)drag=null;
}
function open(event:MouseEvent){
 if(event.detail!==0&&moved){moved=false;return;}
 visible.value=true;
 void nextTick(()=>support.value?.focus());
}
function localAnswer(q:string){
 if(/地址|收货人/.test(q))return '请在收货地址页面填写收货信息，秒杀提交前选择地址。';
 if(/退款|删除|取消/.test(q))return '待支付订单可取消。已取消、已退款或已完成的订单可从个人列表删除。';
 if(/支付|扣款/.test(q))return '请打开订单并选择去支付，支付方式以收银台显示为准。';
 if(/秒杀|抢购|库存/.test(q))return '请选择活动尺码与收货地址，完成验证码后提交抢购。';
 return '可以问我抢购、收货、支付或订单操作。';
}
async function ask(){
 const q=question.value.trim();
 if(!q||pending.value)return;
 pending.value=true;
 error.value='';
 try{
  if(cartIntent.test(q)){
   const choices=props.session?await findCartChoices(q):[];
   const answer=!props.session?'请先登录，然后告诉我商品名称和尺码。':
    choices.length?'请选择要加入购物车的尺码和数量。':'没找到匹配的有货款式，请提供商品名称或换个尺码。';
   messages.value.push({question:q,answer,choices});
   question.value='';
   return;
  }
  const history=messages.value.slice(-4).flatMap(entry=>[
   {role:'user',content:entry.question},{role:'assistant',content:entry.answer}
  ]);
  const answer=props.session
   ? (await api<{answer:string}>('/api/support/chat',props.session,
      {messages:[...history,{role:'user',content:q}]})).answer
   : '商城知识库 · '+localAnswer(q);
  messages.value.push({question:q,answer});
  question.value='';
 }catch(e){
  if(e instanceof ApiError && (e.status===404 || e.status===429 || e.status===0 || e.status>=500)){
   messages.value.push({question:q,answer:'商城知识库 · '+localAnswer(q)});
   question.value='';
  }else{
   error.value='客服暂时无法回复，请稍后重试。';
  }
 }finally{
  pending.value=false;
  await nextTick();
  if(transcript.value)transcript.value.scrollTop=transcript.value.scrollHeight;
 }
}
</script>
<template>
 <button v-show="!visible" ref="launcher" class="support-launch" aria-label="商城客服" title="点击聊天，拖动可移动"
  :style="{right:`min(${offset.x}px, calc(100vw - 64px))`,bottom:`min(${offset.y}px, calc(100dvh - 64px))`}"
  @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="finish" @lostpointercapture="finish" @click="open">
  <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8m-8 3h5"/></svg>
 </button>
 <section v-show="visible" ref="support" role="dialog" tabindex="-1" class="support-window"
  aria-labelledby="support-title" @keydown.esc.stop="hide"
  :style="position ? {left:`min(${position.left}px, max(0px, calc(100vw - 320px)))`,top:`min(${position.top}px, max(0px, calc(100dvh - 300px)))`,right:'auto',bottom:'auto',maxWidth:`calc(100vw - min(${position.left}px, max(0px, calc(100vw - 320px))))`,maxHeight:`calc(100dvh - min(${position.top}px, max(0px, calc(100dvh - 300px))))`} : undefined">
  <header @pointerdown="startWindow" @pointermove="moveWindow" @pointerup="endWindow" @pointercancel="endWindow" @lostpointercapture="endWindow">
   <div><p class="chat-brand">SNKR//DROP</p><h2 id="support-title">商城客服</h2></div>
   <div class="window-actions">
    <button type="button" aria-label="最小化聊天" title="最小化" @click="hide">−</button>
    <button type="button" aria-label="关闭聊天" title="关闭" @click="hide">×</button>
   </div>
  </header>

  <div ref="transcript" role="log" aria-label="聊天记录" class="transcript">
   <div class="chat-row"><span class="chat-avatar" aria-label="客服">客</span><p class="reply">你好！想了解抢购、收货、支付，还是订单操作？也可以说「把 42 码跑步鞋加入购物车」。</p></div>
   <div v-for="(entry,index) in messages" :key="index">
    <div class="chat-row customer"><p class="question">{{entry.question}}</p><span class="chat-avatar" aria-label="你">你</span></div>
    <div class="chat-row"><span class="chat-avatar" aria-label="客服">客</span><p class="reply">{{entry.answer}}</p></div>
    <div v-for="choice in entry.choices" :key="choice.skuId" class="cart-choice">
     <strong>{{choice.title}}</strong>
     <p>{{choice.colorway}} · EU {{choice.sizeEu || '未标注'}} · ¥{{money(choice.priceFen)}}</p>
     <label>购物车数量 <select v-model.number="choice.quantity" :disabled="choice.saved || !!savingSku">
      <option v-for="n in Math.min(10,Number(choice.unallocatedStock))" :key="n" :value="n">{{n}}</option>
     </select></label>
     <button type="button" class="secondary" :disabled="choice.saved || !!savingSku" @click="addChoice(choice)">
      {{choice.saved?'已加入购物车':'确认加购'}}
     </button>
    </div>
   </div>
   <template v-if="pending">
    <div class="chat-row customer"><p class="question">{{question}}</p><span class="chat-avatar" aria-label="你">你</span></div>
    <div class="chat-row"><span class="chat-avatar" aria-label="客服">客</span><p class="reply">正在回复…</p></div>
   </template>
  </div>
  <footer class="chat-footer">
  <p v-if="error" role="alert">{{error}}</p>
  <form @submit.prevent="ask"><input aria-label="你的问题" placeholder="输入消息…" v-model="question" :disabled="pending" required maxlength="200"><button class="button" :disabled="pending">{{pending ? '正在回复…' : '发送'}}</button></form>
  <a href="#/orders" @click="hide()">查看我的订单</a> · <a href="#/shop/cart" @click="hide()">查看购物车</a>
  </footer>
 </section>
</template>
<style scoped>
.support-launch{position:fixed;z-index:45;display:grid;place-items:center;width:56px;height:56px;border:1px solid #fff;border-radius:50%;background:#171717;color:#fff;box-shadow:0 4px 16px #0003;touch-action:none;cursor:grab}
.support-launch:active{cursor:grabbing}
 .support-window{
 position:fixed;right:16px;bottom:16px;z-index:60;
 display:flex;flex-direction:column;
 width:min(660px,calc(100vw - 24px));height:min(680px,calc(100dvh - 24px));
 min-width:min(320px,100vw);min-height:min(300px,100dvh);
 max-width:100vw;max-height:100dvh;
 resize:both;overflow:hidden;background:white;color:#141414;
 border:1px solid #ddd;border-radius:18px;box-shadow:0 18px 70px #0004;
 }
 header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;background:#181818;color:white;cursor:move;touch-action:none;user-select:none}
 header h2{margin:0;font-size:21px}
 .chat-brand{margin:0;font-size:11px;letter-spacing:.12em;color:#ddd}
 .window-actions{display:flex;gap:4px}
 .window-actions button{width:44px;height:44px;border:0;border-radius:50%;background:#333;color:white;font-size:24px}
 @media(max-width:480px){.support-window{right:8px;bottom:8px;width:calc(100vw - 16px)}}
form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin-bottom:8px}
form .button{min-height:44px;padding:0 16px}
.chat-footer{padding:12px 16px;border-top:1px solid #ddd}
.chat-footer a{text-decoration:underline}
.transcript{flex:1;min-height:0;padding:8px 16px;background:#fafafa;overflow:auto;overflow-wrap:anywhere}
.question,.reply{padding:10px 12px;margin:8px 0;border-radius:12px;background:#f3f3f3}
.question{background:#222;color:#fff;margin-left:24px}.reply{margin-right:24px}
.chat-row{display:flex;align-items:flex-start;gap:8px;margin:12px 0}
.customer{justify-content:flex-end}
.chat-avatar{display:grid;place-items:center;width:32px;height:32px;flex:0 0 32px;border-radius:50%;background:#eee;color:#111}
.chat-row p{margin:0;max-width:calc(100% - 40px);white-space:pre-wrap}
.cart-choice{margin:8px 0 8px 40px;padding:12px;border:1px solid #ddd;border-radius:10px;background:white}
.cart-choice label{display:inline-flex;align-items:center;gap:6px;margin-right:8px}
.cart-choice select{width:auto}
.cart-choice button{min-height:44px}
</style>
