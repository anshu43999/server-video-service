import { onMounted, onUnmounted } from 'vue'
import { ManagedWebSocket, type ManagedSocketOptions } from './realtime'

type LifecycleHook = (callback: () => void) => void

export function bindSocketLifecycle(
  socket: Pick<ManagedWebSocket, 'start' | 'stop'>,
  mounted: LifecycleHook = onMounted,
  unmounted: LifecycleHook = onUnmounted,
) {
  mounted(() => socket.start())
  unmounted(() => socket.stop())
}

export function useManagedWebSocket<T>(options: ManagedSocketOptions<T>) {
  const socket = new ManagedWebSocket<T>(options)
  bindSocketLifecycle(socket)
  return socket
}
