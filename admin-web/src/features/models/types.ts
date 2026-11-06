export type Platform = 'android' | 'server'
export type ModelTarget = 'pc' | 'mobile'
export interface ModelArtifact { artifactId: string; platform: string; format: string; sizeBytes?: number; sha256?: string; exists?: boolean; hashValid?: boolean }
export interface ModelAsset {
  modelId: string; name: string; version: string; scenario?: string; status?: string
  active?: boolean; serverBindable?: boolean; serverReady?: boolean; androidBindable?: boolean; androidReady?: boolean
  serverValidated?: boolean; serverValidatedAt?: string; serverValidationSha256?: string
  sha256?: string
  androidConverted?: boolean; signatureStatus?: string; releaseEligible?: boolean; inputSize?: number
  labels?: string[]; artifacts?: ModelArtifact[]; availableVersions?: string[]; revokeReason?: string
  inputTypes?: ('image' | 'video')[]
  license?: Record<string, unknown>
  supportedTargets?: ModelTarget[]; supportedTargetsSource?: string
  targetReadiness?: Partial<Record<ModelTarget, {ready:boolean;supported?:boolean;reason?:string}>>
  targetReleaseEligible?: Partial<Record<ModelTarget, boolean>>
}
export interface CalibrationDataset {
  datasetId: string; name: string; version: string; scenario: string; imageCount: number; sizeBytes: number
  contentSha256: string; yamlPath: string; builtin: boolean; deletable?: boolean; status: string; createdAt?: string
}
export interface ConversionConfig {
  mode: 'local' | 'wsl' | 'remote'; distribution: string; python_path: string; input_size: 320 | 416 | 640
  calibration_data: string; default_calibration_dataset_id: string; timeout_seconds: number; auto_convert: boolean
  remote_endpoint: string; remote_token_env: string; remote_allow_insecure_http: boolean
  remote_poll_interval_seconds: number; remote_verifier_mode: 'local' | 'wsl'
}
export interface ConversionSettings { config: ConversionConfig; max_upload_bytes: number; max_calibration_upload_bytes: number; supported_modes: string[] }
export interface ConversionJob {
  id: string; action: 'check' | 'inspect' | 'mobile'; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted'
  attempt: number; created_at: number; started_at?: number; completed_at?: number; activity_at?: number
  queue_position?: number; stage_label?: string; progress?: number | null; progress_message?: string; error?: string
  metadata: { upload_id?: string; model_id?: string; name?: string; supported_targets?: ModelTarget[]; calibration_dataset?: CalibrationDataset }
  result?: { server_ready?: boolean; android_ready?: boolean; android_converted?: boolean; signature_status?: string; auto_conversion_error?: string; message?: string; mobile_available?: boolean; python?: string }
}
export interface AlertParameter {
  rawLabel: string; displayName: string; eventCode: string; operator: 'PRESENCE'; enabled: boolean; severity: 'MINOR' | 'MAJOR' | 'CRITICAL'
  image: { minimumConfidence: number; cooldownMs: number }
  camera: { minimumConfidence: number; minimumConsecutiveFrames: number; minimumDwellTimeMs: number; cooldownMs: number }
}
export interface ParameterProfile {
  sceneRevision?: number
  inventoryRevision?: number
  schemaVersion: number; modelId: string; modelVersion: string; platform: Platform; revision: number; source: string
  detection: { confidenceThreshold: number; iouThreshold: number; maxDetections: number }; alertRules: AlertParameter[]
  audit?: { action: string; revision: number; actor: string; at: string }[]
}
