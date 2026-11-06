<script setup lang="ts">
import { computed } from 'vue'
import { ElTag } from 'element-plus'

const props = withDefaults(defineProps<{
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'info'
}>(), { tone: 'default' })

const type = computed(() => props.tone === 'default' ? 'info' : props.tone)
</script>

<template>
  <ElTag class="ui-tag" :type="type" effect="plain" size="small"><slot /></ElTag>
</template>
