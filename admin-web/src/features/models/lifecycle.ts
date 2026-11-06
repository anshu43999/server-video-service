export interface RemovalImpact {
  expectedRevision:number; safeToRemove:boolean; knownDevices:number; unknownDeviceCount:number
  dependentCounts:{assignments:number;scenes:number;plans:number;streams:number;activeSlots:number}
}
export interface ModelRemovalResult {
  uninstalled:boolean; deletedFiles:number; missingFiles:number; retainedSharedFiles:number
  cleanupFailures:string[]; operationId:string; revision:number
}
export function removalOutcome(result:ModelRemovalResult){
  if(result.uninstalled!==true||!Array.isArray(result.cleanupFailures)||
    ![result.deletedFiles,result.missingFiles,result.retainedSharedFiles].every(n=>Number.isSafeInteger(n)&&n>=0))
    throw new Error('卸载响应无效，结果待核实；请使用同一操作标识重试。')
  const pending=result.cleanupFailures.length>0
  return {pending,text:pending
    ? `模型版本已退役，但 ${result.cleanupFailures.length} 个文件清理失败；清理意图已保留，可由服务恢复后重试。并非全部文件已回收。`
    : `模型版本已卸载：回收 ${result.deletedFiles} 个文件，保留 ${result.retainedSharedFiles} 个共享文件，${result.missingFiles} 个文件原已缺失。`}
}
export function removalSummary(impact:RemovalImpact){
  const count=impact.dependentCounts
  return `项目分配 ${count.assignments} · 场景 ${count.scenes} · 方案 ${count.plans} · 视频流 ${count.streams} · 活动版本 ${count.activeSlots}。离线设备数量未知，无法确认所有设备的当前运行状态。`
}
export function removalHeaders(revision:number,key:string){
  if(!Number.isSafeInteger(revision)||revision<1||!key)throw new Error('删除操作缺少有效预期修订或幂等标识')
  return {'If-Match':`"${revision}"`,'Idempotency-Key':key}
}
