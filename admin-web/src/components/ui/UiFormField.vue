<script setup lang="ts">
defineProps<{ id: string; label: string; hint?: string; error?: string; required?: boolean }>()
</script>

<template>
  <div class="form-field" :class="{ 'has-error': error }">
    <label :for="id">{{ label }}<span v-if="required" aria-hidden="true"> *</span></label>
    <slot :id="id" :describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined" />
    <p v-if="error" :id="`${id}-error`" class="field-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="`${id}-hint`" class="field-hint">{{ hint }}</p>
  </div>
</template>
