import type { CameraPolicy } from './api'
export const defaultCameraPolicy = (): CameraPolicy => ({frameInterval:5,batchTimeoutMs:5000,resultMaxAgeMs:6000,overlayHoldMs:1500})
export function cameraPolicyError(policy: CameraPolicy): string {
  if (!Object.values(policy).every(Number.isInteger)) return '相机运行设置必须填写整数。'
  if (policy.frameInterval < 1 || policy.frameInterval > 120) return '识别抽帧间隔为 1–120 帧；1 表示不主动跳帧。'
  if (policy.batchTimeoutMs < 1000 || policy.batchTimeoutMs > 10000) return '整批执行期限为 1000–10000 毫秒。'
  if (policy.resultMaxAgeMs < policy.batchTimeoutMs || policy.resultMaxAgeMs > 15000) return '结果最大年龄不能小于整批执行期限，且不能超过 15000 毫秒。'
  if (policy.overlayHoldMs < 0 || policy.overlayHoldMs > 3000) return '历史框保留时间为 0–3000 毫秒。'
  return ''
}
