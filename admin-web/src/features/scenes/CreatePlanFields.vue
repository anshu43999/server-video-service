<script setup lang="ts">
import { computed } from 'vue'
import type { ScenePlan, SceneInputType } from './api'
import CameraPolicyFields from './CameraPolicyFields.vue'
import SceneExecutionHelp from './SceneExecutionHelp.vue'
import { defaultCameraPolicy } from './cameraPolicy'

const props = defineProps<{
  plan: ScenePlan
  inputs: SceneInputType[]
  members: { id: string; label: string; inputs: SceneInputType[] }[]
}>()
const emit = defineEmits<{ change: [patch: Partial<ScenePlan>] }>()
const kinds: SceneInputType[] = ['image', 'video']
const supported = (ids: string[]) => props.inputs.filter(kind =>
  ids.every(id => props.members.find(member => member.id === id)?.inputs.includes(kind)))
const options = computed(() => supported(props.plan.memberIds))
function toggleMember(id: string, checked: unknown) {
  const memberIds = checked ? [...props.plan.memberIds, id] : props.plan.memberIds.filter(value => value !== id)
  const allowed = supported(memberIds)
  const retained = props.plan.inputTypes.filter(kind => allowed.includes(kind))
  emit('change', {memberIds, inputTypes: retained.length ? retained : allowed.slice(0,1)})
}
</script>
<template>
  <div class="scene-plan-draft">
    <label>方案名称<UiInput :model-value="plan.name" maxlength="255" @update:model-value="v=>emit('change',{name:String(v)})"/></label>
    <div class="scene-plan-options"><span>方案输入</span><label v-for="kind in kinds" :key="kind" class="model-check"><UiInput type="checkbox" :model-value="plan.inputTypes.includes(kind)" :disabled="!options.includes(kind)&&!plan.inputTypes.includes(kind)" @update:model-value="v=>emit('change',{inputTypes:v?[...plan.inputTypes,kind]:plan.inputTypes.filter(k=>k!==kind)})"/>{{kind==='image'?'图片':'本机相机连续帧'}}</label></div>
    <div class="scene-plan-options"><span>方案成员</span><label v-for="member in members" :key="member.id" class="model-check"><UiInput type="checkbox" :model-value="plan.memberIds.includes(member.id)" @update:model-value="v=>toggleMember(member.id,v)"/>{{member.label}}</label></div>
    <label>执行方式<UiSelect :model-value="plan.execution" @update:model-value="v=>emit('change',{execution:v as ScenePlan['execution']})"><UiOption value="single">单模型</UiOption><UiOption value="sync">同步</UiOption><UiOption value="async">异步</UiOption></UiSelect></label>
    <SceneExecutionHelp/>
    <CameraPolicyFields v-if="plan.inputTypes.includes('video')" :model-value="plan.cameraPolicy??defaultCameraPolicy()" @update:model-value="v=>emit('change',{cameraPolicy:v})"/>
    <label>方案 ID<UiInput :model-value="plan.planId" maxlength="128" @update:model-value="v=>emit('change',{planId:String(v)})"/></label>
    <label class="model-check"><UiInput type="checkbox" :model-value="plan.enabled" @update:model-value="v=>emit('change',{enabled:v===true})"/>启用方案</label>
  </div>
</template>
