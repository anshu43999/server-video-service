<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElCollapse, ElCollapseItem } from 'element-plus'
const props = defineProps<{ open?: boolean }>()
const active = ref<string[]>(props.open ? ['content'] : [])
watch(() => props.open, value => { active.value = value ? ['content'] : [] })
</script>

<template>
  <ElCollapse v-model="active" class="ui-collapse"><ElCollapseItem name="content"><template #title><slot name="title" /></template><slot /></ElCollapseItem></ElCollapse>
</template>
