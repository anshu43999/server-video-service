// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import EvidenceImage from '../src/features/alerts/EvidenceImage.vue'
import { containImage, evidenceBoxes } from '../src/features/alerts/evidenceOverlay'
import type { AlertEvent } from '../src/features/alerts/types'

const snapshot = (bakedIn = false) => ({ version: 1, capturedAtUs: 123, bakedIn,
  detections: [{ label: '安全帽', confidence: .91, box: { left: .1, top: .2, right: .6, bottom: .8 } }] })
const event = (overlay: unknown = snapshot()): AlertEvent => ({ eventId: 'new', projectId: 'a', evidence: { displayOverlay: overlay },
  detectionResults: [{ label: 'later-frame', confidence: 1, box: { x: 0, y: 0, w: 1, h: 1 } }] })

afterEach(() => vi.unstubAllGlobals())
describe('capture-time evidence display', () => {
  it('uses immutable evidence metadata and supports both normalized coordinate contracts', () => {
    expect(evidenceBoxes(event())[0]?.label).toBe('安全帽')
    expect(evidenceBoxes(event({ ...snapshot(), detections: [{ label: '安全帽', confidence: .91,
      box: { x: .1, y: .2, w: .5, h: .6 } }] }))).toEqual(evidenceBoxes(event()))
    expect(evidenceBoxes(event(snapshot(true)))).toEqual([])
    expect(evidenceBoxes({ eventId: 'missing', detectionResults: event().detectionResults })).toEqual([])
  })

  it('rejects malformed data instead of coercing or fabricating boxes', () => {
    const invalid = { label: '<script>invalid</script>', confidence: .9, box: { left: -1, top: 0, right: 1, bottom: 1 } }
    expect(evidenceBoxes(event({ ...snapshot(), detections: [invalid, { ...invalid, confidence: '0.9' }] }))).toEqual([])
    expect(evidenceBoxes(event({ ...snapshot(), version: 2 }))).toEqual([])
    expect(evidenceBoxes(event({ ...snapshot(), bakedIn: 'false' }))).toEqual([])
  })

  it('maps portrait and landscape evidence into actual contain bounds including letterboxing', () => {
    expect(containImage(400, 400, 800, 400)).toEqual({ x: 0, y: 100, width: 400, height: 200 })
    expect(containImage(400, 400, 400, 800)).toEqual({ x: 100, y: 0, width: 200, height: 400 })
    expect(containImage(0, 400, 800, 400)).toBeUndefined()
  })

  it('renders on image load, measures resize, skips baked overlays and clears stale frames on reuse/error', async () => {
    let resize: (() => void) | undefined
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe() {} disconnect = disconnect
    })
    const wrapper = mount(EvidenceImage, { props: { src: 'blob:first', alt: '证据', event: event() } })
    const img = wrapper.get('img').element
    for (const [key, value] of Object.entries({ clientWidth: 400, clientHeight: 400, naturalWidth: 800, naturalHeight: 400 })) {
      Object.defineProperty(img, key, { value, configurable: true })
    }
    expect(wrapper.find('.evidence-box').exists()).toBe(false)
    await wrapper.get('img').trigger('load')
    expect(wrapper.get('.evidence-annotations').attributes('style')).toContain('top: 100px')
    expect(wrapper.get('.evidence-box-label').text()).toBe('安全帽 91%')
    await wrapper.setProps({ event: { ...event(), disposition: { status: 'ACKNOWLEDGED' } } })
    expect(wrapper.get('.evidence-box-label').text()).toBe('安全帽 91%')
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true })
    resize!(); await wrapper.vm.$nextTick()
    expect(wrapper.get('.evidence-annotations').attributes('style')).toContain('top: 0px')
    await wrapper.setProps({ event: event(snapshot(true)) })
    expect(wrapper.find('.evidence-box').exists()).toBe(false)
    await wrapper.setProps({ src: 'blob:second', event: { ...event(), projectId: 'b' } })
    expect(wrapper.find('.evidence-box').exists()).toBe(false)
    await wrapper.get('img').trigger('load')
    expect(wrapper.find('.evidence-box').exists()).toBe(true)
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('.evidence-box').exists()).toBe(false)
    expect(wrapper.emitted('error')).toHaveLength(1)
    wrapper.unmount(); expect(disconnect).toHaveBeenCalledOnce()
  })
})
