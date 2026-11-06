<script setup lang="ts">
import type { ModelTarget } from './types'
defineProps<{ modelValue: ModelTarget[]; available: ModelTarget[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ModelTarget[]] }>()
const targets: ModelTarget[] = ['pc', 'mobile']
function toggle(value: ModelTarget[], target: ModelTarget, checked: unknown) {
  emit('update:modelValue', checked ? [...new Set([...value, target])] : value.filter(item => item !== target))
}
</script>
<template>
  <div class="target-selection" role="group" aria-label="启用目标端">
    <label v-for="target in targets" :key="target" class="target-choice" :class="{'is-selected':modelValue.includes(target),'is-unavailable':!available.includes(target)}">
      <UiInput type="checkbox" :aria-label="target==='pc'?'PC 端':'移动端'" :model-value="modelValue.includes(target)" :disabled="disabled||!available.includes(target)" @update:model-value="value=>toggle(modelValue,target,value)"/>
      <span><strong>{{target==='pc'?'PC 端':'移动端'}}</strong><small>{{available.includes(target)?'已发布，可独立启用':'未发布、产物未就绪或不支持'}}</small></span>
    </label>
  </div>
</template>
