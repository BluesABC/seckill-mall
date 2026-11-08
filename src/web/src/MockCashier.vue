<script setup lang="ts">
/** 演示收银台：待支付订单→支付方式→演示二维码→显式模拟确认→服务端支付状态。 */
import {ref,nextTick,onUnmounted} from 'vue';
import {api,paymentKey,paymentConfig,money,date,message,type Session} from './api';
const props=defineProps<{session:Session|null;orderId:string;orderKind:'SHOP'|'SECKILL';orderState:string;amountFen:string|null}>();
const emit=defineEmits<{updated:[]}>();
type Demo={orderId:string;amountFen:string;expiresAtMs:string;qrImage?:string;provider:'MOCK';state:string};
const dialog=ref<HTMLDialogElement|null>(null),stage=ref<'METHOD'|'QR'|'SUCCESS'>('METHOD'),method=ref<'WECHAT_DEMO'|'DIRECT_DEMO'>('WECHAT_DEMO'),data=ref<Demo|null>(null),busy=ref(false),error=ref(''),title=ref<HTMLElement|null>(null);
const labelId=`mock-cashier-${props.orderKind}-${props.orderId}`;
let invoker:HTMLElement|null=null,alive=true;
async function open(){
 if(busy.value||!props.session)return;
 invoker=document.activeElement as HTMLElement;stage.value='METHOD';data.value=null;error.value='';method.value='WECHAT_DEMO';
 await nextTick();dialog.value?.showModal();await nextTick();title.value?.focus();
}
function close(){if(!busy.value)dialog.value?.close();}
function closed(){if(!alive)return;if(stage.value==='SUCCESS')document.querySelector<HTMLElement>('main h1')?.focus();else if(invoker?.isConnected)invoker.focus();emit('updated');}
function cancel(event:Event){if(busy.value)event.preventDefault();}
async function next(){
 if(busy.value)return;busy.value=true;error.value='';
 try{const c=await paymentConfig();if(c.provider!=='MOCK')throw Error('当前不是模拟支付模式。');
  const result=await api<Demo>('/api/payments/mock/session',props.session,{orderKind:props.orderKind,orderId:props.orderId,method:method.value});
  if(!alive)return;data.value=result;stage.value='QR';await nextTick();title.value?.focus();
 }catch(e){if(alive)error.value=message(e);}finally{if(alive)busy.value=false;}
}
async function verify(){
 if(!props.session)return;
 const result=props.orderKind==='SHOP'?await api<{status:string}>(`/api/shop/orders/${props.orderId}`,props.session):await api<{orderState:string}>(`/api/order/status?orderId=${props.orderId}`,props.session);
 const state='status' in result?result.status:result.orderState;
 if(!alive)return;
 if(state==='PAID'||state==='SHIPPED'||state==='DELIVERED'){stage.value='SUCCESS';error.value='';await nextTick();title.value?.focus();}
 else error.value=state==='PENDING_PAYMENT'?'订单仍待支付，可使用原记录重试模拟确认。':'订单状态已变化，请关闭收银台后刷新订单。';
}
async function confirm(){
 if(busy.value||!props.session||stage.value!=='QR')return;busy.value=true;error.value='';
 const key=paymentKey(props.session.userId,props.orderId);
 try{
  await api(props.orderKind==='SHOP'?`/api/shop/orders/${props.orderId}/pay`:'/api/order/pay',props.session,{...(props.orderKind==='SECKILL'?{orderId:props.orderId}:{}),idempotencyKey:key});
  await verify();
 }catch(e){if(alive)error.value=message(e)+' 请查询原订单结果，不要重复创建订单。';}
 finally{if(alive)busy.value=false;}
}
async function query(){if(busy.value)return;busy.value=true;try{await verify();}catch(e){if(alive)error.value=message(e);}finally{if(alive)busy.value=false;}}
onUnmounted(()=>{alive=false;dialog.value?.close();});
</script>
<template>
 <button v-if="orderState==='PENDING_PAYMENT'" class="button" @click="open">去支付</button>
 <dialog ref="dialog" class="mock-cashier" style="position:fixed;inset:0;margin:auto" :aria-labelledby="labelId" @cancel="cancel" @close="closed">
  <header><span class="demo-badge">演示收银台 · 不产生真实扣款</span><button class="close-cashier" aria-label="关闭收银台" :disabled="busy" @click="close">×</button></header>
  <p class="cashier-step">{{stage==='METHOD'?'1 / 3 · 选择支付方式':stage==='QR'?'2 / 3 · 模拟付款':'3 / 3 · 支付结果'}}</p>
  <h2 :id="labelId" ref="title" tabindex="-1">{{stage==='METHOD'?'选择支付方式':stage==='SUCCESS'?'模拟支付成功':method==='WECHAT_DEMO'?'模拟微信扫码支付':'直接模拟付款'}}</h2>
  <p class="cashier-amount">¥{{money(data?.amountFen||amountFen)}}</p>
  <p class="cashier-id">订单 {{orderId}}</p>
  <p v-if="error" role="alert" class="error">{{error}}</p>
  <template v-if="stage==='METHOD'">
   <fieldset><legend>请选择演示支付方式</legend>
    <label><input v-model="method" type="radio" value="WECHAT_DEMO" :name="labelId+'-method'"><span><strong>微信扫码（模拟）</strong><small>展示演示二维码，再手动确认模拟已支付</small></span></label>
    <label><input v-model="method" type="radio" value="DIRECT_DEMO" :name="labelId+'-method'"><span><strong>直接模拟付款</strong><small>不扫码，用于快速验证订单流程</small></span></label>
   </fieldset>
   <button class="button full" :disabled="busy" @click="next">{{busy?'正在准备…':'下一步'}}</button>
  </template>
  <template v-else-if="stage==='QR'">
   <div v-if="data?.qrImage" class="demo-qr"><p>模拟微信支付二维码</p><img :src="data.qrImage" width="280" height="280" alt="模拟微信支付演示二维码，无法真实付款"><strong>仅演示，不是微信收款码</strong></div>
   <p class="muted">无需实际扫码或转账。点击下方按钮确认模拟付款。未确认就关闭时，订单仍待支付，可在原截止时间前继续。</p>
   <p v-if="data?.expiresAtMs" class="cashier-id">支付截止 {{date(data.expiresAtMs)}}</p>
   <button class="button full" :disabled="busy" @click="confirm">{{busy?'正在确认…':'模拟已支付'}}</button>
   <div class="cashier-actions"><button :disabled="busy" @click="stage='METHOD'">重新选择方式</button><button :disabled="busy" @click="query">查询支付结果</button></div>
  </template>
  <template v-else>
   <p role="status" aria-live="polite">已确认付款，订单已进入后续处理流程。没有发生真实扣款。</p>
   <button class="button full" @click="close">查看订单</button>
  </template>
 </dialog>
</template>
<style scoped>
.mock-cashier{width:460px;max-width:calc(100vw - 24px);max-height:90dvh;overflow:auto;padding:28px;border:0;background:#fff;color:#111;font-family:inherit}.mock-cashier::backdrop{background:rgb(0 0 0 / .5)}.mock-cashier header{display:flex;justify-content:space-between;gap:12px;align-items:center}.demo-badge{font-size:12px;color:#555}.close-cashier{background:none;border:0;font-size:28px;min-width:44px;min-height:44px}.cashier-step,.cashier-id{font-size:12px;color:#555;overflow-wrap:anywhere}.mock-cashier h2{font-size:26px;margin:12px 0}.cashier-amount{font-size:36px;font-weight:750;margin:16px 0}.mock-cashier fieldset{padding:0;border:0;margin:24px 0}.mock-cashier legend{font-size:14px;margin-bottom:12px}.mock-cashier label{display:flex;align-items:center;gap:12px;border:1px solid #bbb;padding:16px;margin:10px 0;cursor:pointer}.mock-cashier input{width:18px;height:18px;flex-shrink:0;accent-color:#111}.mock-cashier small{display:block;font-size:12px;line-height:1.7;margin-top:5px}.demo-qr{text-align:center;margin:16px 0}.demo-qr img{display:block;width:240px;height:240px;max-width:100%;object-fit:contain;margin:0 auto}.demo-qr strong{font-size:13px}.cashier-actions{display:flex;gap:12px;justify-content:space-between;margin-top:14px}.cashier-actions button{background:none;border:0;min-height:44px;text-decoration:underline}.mock-cashier button:focus-visible,.mock-cashier input:focus-visible{outline:3px solid #111;outline-offset:3px}@media(max-width:480px){.mock-cashier{padding:20px}.mock-cashier h2{font-size:23px}.cashier-amount{font-size:30px}}
</style>
