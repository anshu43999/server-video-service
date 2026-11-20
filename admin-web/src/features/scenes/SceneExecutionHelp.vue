<template>
  <aside class="scene-execution-help" role="note" aria-label="同步与异步的区别">
    <p><strong>同步：</strong>图片对同一张照片依次识别，视频对同一帧依次识别；整组完成后统一展示结果。</p>
    <p><strong>异步：</strong>图片完成一个模型就先展示该模型结果，最终标记整组状态；视频成员按各自间隔处理。</p>
    <p>两种方式目前都依次推理，不会同时运行多个模型。</p>
  </aside>
</template>

<style scoped>
.scene-execution-help{grid-column:1/-1;min-width:0;margin:8px 0;color:var(--color-ink-muted);font-size:12px;line-height:1.7;overflow-wrap:anywhere}
.scene-execution-help p{margin:0}.scene-execution-help p+p{margin-top:4px}.scene-execution-help strong{color:var(--color-ink);font-weight:600}
</style>
