<script setup lang="ts">
import { RotateCcw, Search } from '@lucide/vue'
withDefaults(defineProps<{ searchLabel?: string; resetLabel?: string }>(), { searchLabel: '查询', resetLabel: '重置' })
defineEmits<{ submit: []; reset: [] }>()
</script>

<template>
  <form class="filter-bar" role="search" @submit.prevent="$emit('submit')" @reset.prevent="$emit('reset')">
    <div class="filter-fields"><slot /></div>
    <div class="filter-actions"><UiButton class="secondary-button" type="reset"><RotateCcw :size="16" aria-hidden="true" />{{ resetLabel }}</UiButton><UiButton class="primary-button" type="submit"><Search :size="16" aria-hidden="true" />{{ searchLabel }}</UiButton></div>
  </form>
</template>
