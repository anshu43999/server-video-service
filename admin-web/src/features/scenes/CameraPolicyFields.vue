<script setup lang="ts">
import type { CameraPolicy } from './api'
const policy=defineModel<CameraPolicy>({required:true})
function update(key:keyof CameraPolicy,value:unknown){policy.value={...policy.value,[key]:typeof value==='number'?value:NaN}}
</script>
<template>
  <section class="scene-camera-policy" aria-label="移动相机运行设置">
    <h4>移动相机运行设置</h4>
    <p class="model-muted">预览持续播放；整套同步模型识别同一选中帧。修改后需要重新批准场景，不改变图片识别或 PC 视频任务。</p>
    <div class="scene-camera-policy-grid">
      <label>识别抽帧间隔（帧）<UiInput :model-value="policy.frameInterval" type="number" :min="1" :max="120" :step="1" @update:model-value="value=>update('frameInterval',value)"/><small>每 N 个分析帧选 1 帧；1 为不主动跳帧，首帧参与识别。</small></label>
      <label>整批执行期限（毫秒）<UiInput :model-value="policy.batchTimeoutMs" type="number" :min="1000" :max="10000" :step="500" @update:model-value="value=>update('batchTimeoutMs',value)"/><small>到期保留已完成的有效成员；未开始成员标为未执行。</small></label>
      <label>结果最大年龄（毫秒）<UiInput :model-value="policy.resultMaxAgeMs" type="number" :min="policy.batchTimeoutMs" :max="15000" :step="500" @update:model-value="value=>update('resultMaxAgeMs',value)"/><small>从帧采集计时，超过后不作为有效识别结果。</small></label>
      <label>历史框保留时间（毫秒）<UiInput :model-value="policy.overlayHoldMs" type="number" :min="0" :max="3000" :step="100" @update:model-value="value=>update('overlayHoldMs',value)"/><small>从有效结果展示计时；标明历史结果，到期清除。0 为不保留。</small></label>
    </div>
    <p class="model-muted">默认每 5 帧识别一次、执行期限 5 秒。这是工程初始值，不代表设备性能保证。</p>
  </section>
</template>
<style scoped>
.scene-camera-policy{grid-column:1/-1;padding:16px;border-radius:12px;background:var(--surface-muted,#f5f7fa)}
.scene-camera-policy h4{margin:0 0 8px}.scene-camera-policy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.scene-camera-policy-grid label{display:grid;gap:8px}.scene-camera-policy-grid small{font-weight:normal;color:var(--text-secondary,#59677a);line-height:1.5}
@media(max-width:640px){.scene-camera-policy-grid{grid-template-columns:1fr}}
</style>
