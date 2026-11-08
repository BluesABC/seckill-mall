<script setup lang="ts">
/** Native收银区：只展示后端已验签响应生成的二维码，支付结果从服务端查单获取。 */
import {ref,watch,onUnmounted} from 'vue';
import {api,paymentConfig,money,date,message,type Session,type PaymentConfig} from './api';
const props=defineProps<{session:Session|null;orderId:string;orderKind:'SHOP'|'SECKILL';orderState:string}>();
const emit=defineEmits<{updated:[];config:[PaymentConfig];managed:[boolean]}>();
type State={state:string;qrImage?:string;amount_fen?:string;expires_at_ms?:string;transaction_id?:string;refund_id?:string;last_error?:string};
const config=ref<PaymentConfig|null>(null),state=ref<State|null>(null),busy=ref(false),error=ref('');
let timer:ReturnType<typeof setTimeout>|undefined,generation=0;
const labels:Record<string,string>={NOT_STARTED:'尚未发起微信支付',CREATING:'正在确认预下单结果',PREPAY:'请使用微信扫描二维码支付',SUCCESS:'微信支付已确认',CLOSED:'微信支付已关闭',REFUNDING:'原路退款处理中',REFUNDED:'微信退款已确认',REVIEW:'支付状态需管理员复核'};
function clear(){if(timer)clearTimeout(timer);timer=undefined;}
async function refresh(version=generation){
 if(!props.session||!config.value?.wechatConfigured)return;
 try{const next=await api<State>(`/api/payments/wechat/status?orderKind=${props.orderKind}&orderId=${props.orderId}`,props.session);
  if(version!==generation)return;
  const previous=state.value?.state;state.value=next;error.value='';emit('managed',next.state!=='NOT_STARTED');
  if(previous&&previous!==next.state&&['SUCCESS','CLOSED','REFUNDED'].includes(next.state))emit('updated');
  if(['CREATING','PREPAY','REFUNDING'].includes(next.state)){clear();timer=setTimeout(()=>void refresh(version),3000);}
 }catch(e){if(version===generation)error.value=message(e);}
}
async function action(action:'native'|'close'|'refund'){
 if(busy.value||!props.session||!config.value?.wechatConfigured)return;
 if(action==='close'&&!window.confirm('确认关闭这笔微信支付？渠道确认前不会释放库存。'))return;
 if(action==='refund'&&!window.confirm('确认申请真实全额微信退款？退款处理中不等于已退款。'))return;
 busy.value=true;error.value='';const version=generation;
 try{const result=await api<State>('/api/payments/wechat/'+action,props.session,{orderKind:props.orderKind,orderId:props.orderId});if(version!==generation)return;state.value=result;await refresh(version);emit('updated');}
 catch(e){if(version===generation){error.value=message(e);await refresh(version);}}
 finally{if(version===generation)busy.value=false;}
}
watch(()=>[props.orderId,props.session?.userId],async()=>{
 clear();const version=++generation;state.value=null;
 try{const c=await paymentConfig();if(version!==generation)return;config.value=c;emit('config',c);await refresh(version);}catch(e){if(version===generation)error.value=message(e);}
},{immediate:true});
onUnmounted(()=>{clear();generation++;});
</script>
<template>
 <section class="wechat-pay" aria-label="微信扫码支付">
  <p v-if="error" role="alert">{{error}} <button :disabled="busy" @click="refresh()">重新查单</button></p>
  <template v-if="config?.wechatConfigured">
   <h3>微信扫码支付</h3><p role="status" aria-live="polite">{{labels[state?.state||'NOT_STARTED']||'正在查询支付状态'}}</p>
   <p v-if="state?.amount_fen">支付金额 ¥{{money(state.amount_fen)}}</p>
   <p v-if="state?.expires_at_ms" class="small muted">微信支付截止：{{date(state.expires_at_ms)}}</p>
   <img v-if="state?.qrImage" :src="state.qrImage" width="280" height="280" alt="请用微信扫一扫此订单支付二维码。支付金额以微信收银页面为准。">
   <div class="wechat-actions">
    <button v-if="orderState==='PENDING_PAYMENT'&&(!state||['NOT_STARTED','CREATING','PREPAY'].includes(state.state))" class="button" :disabled="busy" @click="action('native')">{{busy?'正在请求微信…':state?.qrImage?'重新查询二维码':'获取微信支付二维码'}}</button>
    <button v-if="state&&['CREATING','PREPAY'].includes(state.state)" class="secondary" :disabled="busy" @click="action('close')">关闭微信支付并取消订单</button>
    <button v-if="state?.state==='SUCCESS'&&orderState==='PAID'" class="secondary" :disabled="busy" @click="action('refund')">申请微信全额退款</button>
    <button v-if="state&&state.state!=='NOT_STARTED'" class="underlink" :disabled="busy" @click="refresh()">查询微信结果</button>
   </div>
   <p v-if="state?.transaction_id" class="small">微信交易号：{{state.transaction_id}}</p><p v-if="state?.refund_id" class="small">微信退款号：{{state.refund_id}}</p>
   <p class="small muted">二维码不是付款凭证。仅在微信确认成功后更新订单；连接中断时请查单，不要重复付款。</p>
  </template>
  <p v-else class="small muted">微信 Native 扫码支付尚未配置商户信息，当前不可收款。</p>
 </section>
</template>
<style scoped>
.wechat-pay{margin:20px 0;padding:16px 0;border-top:1px solid #ddd;overflow-wrap:anywhere}.wechat-pay img{display:block;max-width:100%;height:auto;background:#fff}.wechat-actions{display:flex;flex-wrap:wrap;gap:12px}.wechat-pay h3{font-size:18px}.wechat-pay button{min-height:44px}.wechat-pay button:focus-visible{outline:3px solid #111;outline-offset:3px}
</style>
