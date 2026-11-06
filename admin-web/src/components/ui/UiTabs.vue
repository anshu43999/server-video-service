<script setup lang="ts">
import { ElTabs, ElTabPane } from 'element-plus'
defineProps<{ modelValue: string; items: { id: string; label: string }[]; disabled?: boolean }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <ElTabs class="ui-tabs" :model-value="modelValue" @update:model-value="value => $emit('update:modelValue', String(value))"><ElTabPane v-for="item in items" :key="item.id" :name="item.id" :label="item.label" :disabled="disabled" /></ElTabs>
</template>
