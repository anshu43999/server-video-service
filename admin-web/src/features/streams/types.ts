export interface StreamModel {
  modelId: string
  name?: string
  version?: string
  scenario?: string
  serverBindable?: boolean
  load_error?: string | null
  loaded?: boolean
}

export interface StreamItem {
  alert_error?: string | null
  stream_id: string
  display_name?: string
  source_type?: string
  model_id?: string | null
  scene_id?: string | null
  plan_id?: string | null
  scene_revision?: number | null
  yolo_enabled?: boolean
  confidence?: number
  max_fps?: number
  overlay_enabled?: boolean
  enabled?: boolean
  runtime_state?: string
  publish_state?: string
  runtime_available?: boolean
  configuration_state?: string
  frames_received?: number
  frames_processed?: number
  frames_dropped?: number
  received_fps?: number
  processed_fps?: number
  output_fps?: number
  last_latency_ms?: number | null
  p95_latency_ms?: number | null
  active_subscribers?: number
  detections_last?: number
  last_error?: string | null
  model_error?: string | null
  model?: StreamModel | null
}

