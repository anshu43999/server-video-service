<script setup lang="ts">
import { ElTable, ElTableColumn } from 'element-plus'
export interface TableColumn { key: string; label: string; align?: 'start' | 'center' | 'end'; width?: number; minWidth?: number; fixed?: 'left' | 'right' }
defineProps<{ columns: TableColumn[]; rows: Record<string, unknown>[]; caption: string; rowKey?: string }>()
</script>

<template>
  <div class="table-region" tabindex="0" role="region" :aria-label="caption">
    <ElTable :data="rows" :row-key="rowKey ?? 'id'" empty-text="暂无数据">
      <ElTableColumn v-for="column in columns" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :min-width="column.minWidth" :fixed="column.fixed" :align="column.align === 'start' ? 'left' : column.align === 'end' ? 'right' : 'center'">
        <template #default="scope"><slot :name="`cell-${column.key}`" :row="scope.row" :value="scope.row[column.key]">{{ scope.row[column.key] }}</slot></template>
      </ElTableColumn>
      <template #empty><slot name="empty">暂无数据</slot></template>
    </ElTable>
  </div>
</template>
