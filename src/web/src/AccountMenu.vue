<script setup lang="ts">
import {onMounted,ref} from 'vue';
import {api,date,message,type Session} from './api';
const props=defineProps<{session:Session;busy:boolean}>();
defineEmits<{logout:[]}>();
const profile=ref<{username:string;role:string;createdAtMs:string}|null>(null);
const shown=ref(false),error=ref('');
const trigger=ref<HTMLButtonElement|null>(null);
onMounted(async()=>{
 try{profile.value=await api('/api/auth/profile',props.session);}
 catch(e){error.value=message(e);}
});
function dismiss(){shown.value=false;trigger.value?.focus();}
function leave(event:FocusEvent){
 if(!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node|null))shown.value=false;
}
</script>
<template>
 <div class="account-menu" @pointerenter="shown=true" @pointerleave="shown=false" @focusout="leave" @keydown.esc.stop="dismiss">
  <button ref="trigger" class="avatar" aria-label="个人信息" aria-controls="account-profile" :aria-expanded="shown" @click="shown=true">
   {{profile?.username?.slice(0,1).toUpperCase() || '人'}}
  </button>
  <div v-if="shown" id="account-profile" class="profile">
   <strong>个人信息</strong>
   <dl v-if="profile"><dt>用户名</dt><dd>{{profile.username}}</dd><dt>账号类型</dt><dd>{{profile.role==='ADMIN'?'管理员':'会员'}}</dd><dt>注册时间</dt><dd>{{date(profile.createdAtMs)}}</dd></dl>
   <p v-else role="status">{{error || '正在加载…'}}</p>
   <button class="secondary" :disabled="busy" @click="$emit('logout')">退出登录</button>
  </div>
 </div>
</template>
<style scoped>
.account-menu{position:relative}
.avatar{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:50%;background:#171717;color:white;font-weight:700}
.profile{position:absolute;z-index:50;right:0;top:100%;width:min(240px,75vw);padding:16px;background:white;color:#111;border:1px solid #ddd;box-shadow:0 6px 20px #0002;overflow-wrap:anywhere}
dl{margin:12px 0}dt{color:#555;font-size:.85em}dd{margin:0 0 8px}
</style>
