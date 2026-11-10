<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import { operationsApi, type DeliveryPolicy, type DeliveryStatus } from './api'
import { useManagement } from '../management/useManagement'
import { useProjectCapabilities } from '../projects/capabilities'
import { errorText } from '../models/api'
import { redactMessage } from '../../api/errors'
import { VisiblePoller } from '../../api/visiblePoller'
import '../models/models.css'
const {settings:canManage,active} = useProjectCapabilities()
const draft=ref<DeliveryPolicy|null>(null)
const {data,loading,error,busy,mutationError,needsReload,notice,refresh,run}=useManagement<DeliveryPolicy|null>(null, operationsApi.policy)
const status=ref<DeliveryStatus|null>(null),statusError=ref(''),target=ref(''),resetOpen=ref(false)
const channelNames:Record<string,string>={management:'管理后台',app:'移动端通知',email:'邮件适配器',sms:'短信适配器',enterprise_im:'企业 IM 适配器'}
let disposed=false, testDeadline=0
const pendingTests=ref<string[]>([])
const statusPoller=new VisiblePoller({
  read: operationsApi.delivery,
  enabled: () => canManage.value && active.value,
  delay: value => value.pending > 0 || (pendingTests.value.length > 0 && Date.now() < testDeadline) ? 5000 : 30000,
  accept: value => {
    status.value=value;statusError.value=''
    const completed=new Set(value.recent.filter(receipt=>['delivered','failed','cancelled'].includes(receipt.status)).map(receipt=>receipt.deliveryId||receipt.delivery_id))
    pendingTests.value=pendingTests.value.filter(id=>!completed.has(id))
  },
  error: e => {status.value=null;statusError.value=errorText(e)},
})
async function loadPolicy(){if(await refresh())draft.value=data.value?{...data.value,channels:[...data.value.channels]}:null}
function loadStatus(){return statusPoller.refresh()}
async function save(){
  if(!canManage.value||!draft.value)return
  const value={...draft.value,channels:[...draft.value.channels]}
  await run(()=>operationsApi.savePolicy(value),()=>{})
  if(!mutationError.value&&data.value)draft.value={...data.value,channels:[...data.value.channels]}
}
async function reset(){
  if(!canManage.value||!data.value)return
  await run(()=>operationsApi.resetPolicy(data.value!.revision),()=>{resetOpen.value=false})
  if(!mutationError.value&&data.value)draft.value={...data.value,channels:[...data.value.channels]}
}
function toggleChannel(id:string,checked:boolean){if(!draft.value||!canManage.value)return;draft.value.channels=checked?[...new Set([...draft.value.channels,id])]:draft.value.channels.filter(c=>c!==id)}
async function send(){
  if(!canManage.value||!active.value||!target.value||busy.value||needsReload.value)return
  statusPoller.pause()
  let result:Awaited<ReturnType<typeof operationsApi.testDelivery>>|undefined
  try {
    await run(async()=>{result=await operationsApi.testDelivery(target.value)},()=>{
      target.value=''
      pendingTests.value=result?.accepted ? [...new Set([...pendingTests.value,...result.deliveryIds])] : pendingTests.value
      testDeadline=Date.now()+60000
    },false)
  } finally {if(!disposed)await statusPoller.resume()}
}
watch(()=>canManage.value&&active.value,enabled=>{if(enabled)void statusPoller.resume();else{statusPoller.pause();status.value=null;pendingTests.value=[]}})
onMounted(()=>{void loadPolicy();statusPoller.start()})
onBeforeUnmount(()=>{disposed=true;statusPoller.stop();pendingTests.value=[]})
</script>
<template><section class="model-workspace">
<div class="model-actions page-actions"><UiButton class="secondary-button" :disabled="busy||loading" @click="loadPolicy();loadStatus()">重新读取推送配置</UiButton></div>
<p class="operation-feedback">通道凭据与收件目标由平台维护。邮件、短信和企业 IM 回执只代表适配器状态，不能证明真实收件人收到通知。</p>
<p v-if="notice" class="operation-feedback" role="status">{{notice}} 测试入队不代表投递成功，最终状态以回执为准。</p><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
<UiStatePanel v-if="loading" state="loading"/><UiStatePanel v-else-if="error" state="error" :message="error" @retry="loadPolicy"/>
<section v-else-if="draft" class="model-panel"><header><h3>项目推送策略</h3><span>修订 {{draft.revision}} · {{canManage?'可维护':'只读'}}</span></header>
<form class="model-form" @submit.prevent="save"><fieldset :disabled="busy||needsReload||!canManage"><div class="model-fields">
<label class="model-check"><UiInput :disabled="busy||needsReload||!canManage" v-model="draft.enabled" type="checkbox"/>启用项目推送</label>
<label>最低通知级别<UiSelect :disabled="busy||needsReload||!canManage" v-model="draft.minimumSeverity"><UiOption value="MINOR">一般及以上</UiOption><UiOption value="MAJOR">重要及以上</UiOption><UiOption value="CRITICAL">仅严重</UiOption></UiSelect></label>
<label v-for="(name,id) in channelNames" :key="id" class="model-check"><UiInput :disabled="busy||needsReload||!canManage" type="checkbox" :checked="draft.channels.includes(id)" @change="value=>toggleChannel(id,Boolean(value))"/>{{name}}</label>
</div></fieldset><div v-if="canManage" class="model-actions"><UiButton class="primary-button" :disabled="busy||needsReload">保存推送策略</UiButton><UiButton type="button" class="secondary-button" :disabled="busy||needsReload" @click="resetOpen=true">恢复默认策略</UiButton></div></form></section>
<p v-if="statusError" class="operation-feedback is-error" role="alert">{{statusError}}<UiButton class="secondary-button" @click="loadStatus">重读投递回执</UiButton></p>
<p v-if="pendingTests.length" class="operation-feedback" role="status">测试回执尚未确认，仍在核对；入队不代表投递成功，不会自动重发测试。</p>
<template v-if="canManage&&status"><section class="model-panel"><header><h3>通道运行状态</h3><span>待处理 {{status.pending}}</span></header><div v-for="(channel,id) in status.channels" :key="id" class="dataset-row"><div><strong>{{channelNames[id]||id}}</strong><p>{{channel.enabled?'适配器可用':'适配器停用'}} · {{channel.subscribers}} 个订阅者</p></div><UiButton v-if="active" class="secondary-button" :disabled="busy||needsReload||!channel.enabled" @click="target=String(id)">测试 {{channelNames[id]||id}}</UiButton></div></section>
<section class="model-panel"><header><h3>最近投递回执</h3><span>当前项目最近 50 条</span></header><p v-if="!status.recent.length" class="model-muted">暂无投递回执</p><div v-for="(receipt,index) in status.recent" :key="index" class="dataset-row"><div><strong>{{channelNames[receipt.channel]||receipt.channel}} · {{receipt.status}}</strong><code>{{receipt.deliveryId||receipt.delivery_id}}</code><p>尝试 {{receipt.attempts}} 次 · {{redactMessage(receipt.errorCode||receipt.error_code,'无错误')}}</p></div></div></section></template>
<UiConfirmDialog :open="!!target" title="发送显式投递测试" :description="`将向 ${channelNames[target]||target} 入队一条测试告警，可能触达当前项目订阅者。入队不代表投递成功。`" confirm-label="确认发送测试" :busy="busy" @update:open="open=>{if(!open)target=''}" @confirm="send"/>
<UiConfirmDialog v-model:open="resetOpen" title="恢复默认推送策略" description="恢复项目默认通道与通知级别；不会更改平台通道凭据。" confirm-label="确认恢复" :busy="busy" @confirm="reset"/>
</section></template>
