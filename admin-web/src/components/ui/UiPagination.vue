<script setup lang="ts">
import { ElPagination } from 'element-plus'
defineProps<{ modelValue: number; total: number; pageSize: number }>()
defineEmits<{ 'update:modelValue': [value: number] }>()
</script>

<template>
  <ElPagination :current-page="modelValue" :total="total" :page-size="pageSize" layout="prev, pager, next" prev-text="上一页" next-text="下一页" @update:current-page="value => $emit('update:modelValue', value)" />
</template>
