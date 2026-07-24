export type AppSection =
  | "dashboard"
  | "projects"
  | "studio"
  | "library"
  | "tools"
  | "engines"
  | "settings";
export type StudioStep =
  | "media"
  | "cleanup"
  | "transcript"
  | "translation"
  | "characters"
  | "voices"
  | "rvc"
  | "sync"
  | "mix"
  | "export";
export type LibraryAssetKind = "captures" | "glossaries" | "audio" | "presets";
export interface LibraryAsset {
  id: string;
  kind: LibraryAssetKind;
  name: string;
  path?: string | null;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProjectRecord {
  id: string;
  name: string;
  status: string;
  project_dir: string;
  source_path?: string | null;
  original_source_path?: string | null;
  derived_sources?: { kind: string; path: string; created_at: string }[];
  media_manifest_path?: string | null;
  source_language?: string | null;
  target_language?: string | null;
  performance_profile?: string | null;
  created_at: string;
  updated_at: string;
}
export interface TrashProjectRecord {
  trash_id: string;
  deleted_at: string;
  original_id: string;
  project: ProjectRecord;
}

export interface Speaker {
  name: string;
  role: string;
  duration: string;
  color: string;
  level: number;
  voice_profile_id?: string | null;
  voice_engine?: string | null;
  voice_model?: string | null;
  voice_instruct?: string | null;
  effects_chain?: VoiceboxEffect[];
}
export interface Segment {
  id: string;
  left: number;
  width: number;
  lane: number;
  speaker: string;
  label: string;
  color: string;
  start: string;
  end: string;
  sourceText: string;
  translatedText: string;
  adaptedText: string;
  emotion: string;
  intensity: number;
  pace: number;
  fit: number;
  locked: boolean;
}
export interface MixSettings {
  voice_volume: number;
  original_volume: number;
  music_volume: number;
  voice_muted: boolean;
  original_muted: boolean;
  music_muted: boolean;
  normalize: boolean;
  ducking: boolean;
  music_path?: string | null;
}
export interface AnalysisState {
  speakers: Speaker[];
  segments: Segment[];
  updated_at: string;
  source_language?: string | null;
  target_language?: string | null;
  mix?: MixSettings;
}

export interface JobRecord {
  id: string;
  project_id: string;
  type: string;
  status: string;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  artifacts: Record<string, string>;
  options?: Record<string, unknown>;
}

export type ActivityKind =
  "project" | "engine" | "youtube" | "rvc" | "subclean" | "simulation";
export interface ActivityRecord {
  id: string;
  source_id: string;
  kind: ActivityKind;
  type: string;
  title: string;
  status: string;
  raw_status: string;
  progress: number;
  message: string;
  error?: string | null;
  project_id?: string | null;
  artifact_path?: string | null;
  created_at: string;
  updated_at: string;
  can_cancel: boolean;
  can_retry: boolean;
  simulation: boolean;
  metadata: Record<string, unknown>;
}
export interface ActivityFeed {
  activities: ActivityRecord[];
  active_count: number;
  failed_count: number;
}

export type ExportDelivery = "full" | "shorts" | "both" | "audio";
export type ExportContainer = "mp4" | "mkv" | "mov" | "webm";
export type ExportVideoCodec =
  "copy" | "h264" | "h265" | "av1" | "vp9" | "prores";
export type ExportAudioCodec = "aac" | "opus" | "flac" | "pcm";
export interface ExportOptions {
  delivery: ExportDelivery;
  container: ExportContainer;
  video_codec: ExportVideoCodec;
  audio_codec: ExportAudioCodec;
  quality: number;
  preset: "ultrafast" | "veryfast" | "fast" | "medium" | "slow";
  audio_bitrate: string;
  resolution: "source" | "720p" | "1080p" | "1440p" | "2160p";
  aspect: "source" | "16:9" | "9:16" | "1:1" | "4:5";
  framing: "fit" | "crop" | "blur";
  upscale: "off" | "standard" | "ai-anime" | "ai-general";
  normalize_audio: boolean;
  original_volume: number;
  voice_volume: number;
  music_volume: number;
  ducking: boolean;
  music_path?: string | null;
  short_duration: number;
  short_mode: "fixed" | "dialogue";
  name?: string;
  segment_strategy?: "count" | "duration" | "dialogue" | "manual";
  segment_count?: number;
  segment_duration_seconds?: number;
  segment_ranges?: ExportRegion[];
  edit_ranges?: { source_start: number; source_end: number }[];
}
export interface ExportRegion {
  id: string;
  name: string;
  start: number;
  end: number;
  duration?: number;
  enabled: boolean;
  framing?: "fit" | "crop" | "blur";
  position_x?: number;
  position_y?: number;
  scale?: number;
}
export interface ExportPlan {
  version: 2;
  strategy: string;
  duration_seconds: number;
  output_count: number;
  regions: ExportRegion[];
  warnings: string[];
  options: ExportOptions;
}
export interface TimelineProjectState {
  version: number;
  markers: { id: string; time: number; label: string; color?: string }[];
  export_regions: ExportRegion[];
  edit_initialized: boolean;
  edit_clips: TimelineEditClip[];
  in_point: number | null;
  out_point: number | null;
  track_states: Record<
    string,
    { muted?: boolean; locked?: boolean; hidden?: boolean }
  >;
  preferences: Record<string, unknown>;
  updated_at?: string | null;
}
export interface TimelineEditClip {
  id: string;
  name: string;
  source_start: number;
  source_end: number;
  enabled: boolean;
}
export interface ExportPreset {
  id: string;
  label: string;
  container: ExportContainer;
  video_codec: ExportVideoCodec;
  audio_codec: ExportAudioCodec;
  quality: number;
  resolution: ExportOptions["resolution"];
}
export interface ExportCapabilities {
  ready: boolean;
  containers: Record<
    ExportContainer,
    { video: ExportVideoCodec[]; audio: ExportAudioCodec[]; extension: string }
  >;
  presets: ExportPreset[];
  video_encoders: Record<string, boolean>;
  audio_encoders: Record<string, boolean>;
  hardware: { nvenc: boolean; amf: boolean; qsv: boolean };
  filters: Record<string, boolean>;
  ai_upscale: { installed: boolean; engines: string[] };
}

export interface EngineInstallation {
  status: string;
  progress: number;
  message: string;
  updated_at?: string | null;
  log_path?: string | null;
}
export interface EngineVerification {
  status: "not-installed" | "adapter-missing" | "untested" | "usable";
  usable: boolean;
  installed: boolean;
  adapter?: string | null;
  adapter_ready: boolean;
  smoke_test: boolean;
  smoke_test_label: string;
  message: string;
}
export interface EngineRecord {
  id: string;
  display_name: string;
  category: string;
  tagline: string;
  description: string;
  installable: boolean;
  source: string;
  license: string;
  capabilities: string[];
  languages?: string[];
  requirements: {
    disk_space_gb: number;
    minimum_ram_gb: number;
    recommended_vram_gb?: number;
  };
  installer: { steps: string[]; script?: string };
  installation: EngineInstallation;
  verification: EngineVerification;
  credentials?: EngineCredential[];
  brand?: EngineBrand;
  model?: {
    repo_id?: string;
    original_repo_id?: string;
    file_name?: string;
    runtime?: string;
    quantization?: string;
    recommended?: boolean;
    family?: string;
    family_id?: string;
    format?: string;
    variant?: string;
    parameters_m?: number;
    parameters_b?: number;
  };
}
export interface EngineBrand {
  id: string;
  name: string;
  owner: string;
  official_url: string;
  license: string;
  asset: string;
  asset_type?: string;
  asset_source?: string;
  accent: string;
  checksum?: string | null;
}
export interface EngineCredential {
  id: string;
  label: string;
  secret: boolean;
  required: boolean;
  help_url?: string;
}

export interface RuntimeStatus {
  status: string;
  workspace_root: string;
  projects_root: string;
  tools: { ffmpeg: boolean; ffprobe: boolean; nvidia_smi: boolean };
  hardware: {
    os: string;
    python: string;
    cpu: string;
    cpu_threads: number | null;
    memory: {
      load_percent: number;
      total_bytes: number;
      available_bytes: number;
    } | null;
    cuda: { name?: string; memory_total?: string } | null;
  };
  pipeline: Record<string, string>;
}

export interface AppConfig {
  api: { host: string; port: number; base_url: string };
  paths: Record<string, string>;
  preferences: Record<string, unknown>;
  voicebox?: {
    host: string;
    port: number;
    base_url: string;
    source: string;
    data: string;
    models: string;
  };
}

export interface MediaProbe {
  path: string;
  file_name: string;
  duration_seconds: number | null;
  size_bytes: number | null;
  format_name: string | null;
  video: {
    codec: string | null;
    width: number | null;
    height: number | null;
    fps: number | null;
  } | null;
  audio: {
    codec: string | null;
    channels: number | null;
    sample_rate: number | null;
  } | null;
}

export interface MediaPrepare {
  project_id: string;
  project_dir: string;
  audio_path: string;
  manifest_path: string;
  waveform: number[];
  media: MediaProbe;
}
export interface YouTubeRuntime {
  ready: boolean;
  engine_id: string;
}
export interface YouTubeInfo {
  id: string;
  title: string;
  channel?: string | null;
  duration?: number | null;
  thumbnail?: string | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  live: boolean;
  webpage_url: string;
}
export interface YouTubeDownload {
  id: string;
  status:
    | "queued"
    | "downloading"
    | "processing"
    | "completed"
    | "failed"
    | "cancelled";
  progress: number;
  message: string;
  url: string;
  title: string;
  path?: string | null;
  eta?: string | null;
  speed?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}
export interface RvcStatus {
  runtime_ready: boolean;
  core_assets_ready: boolean;
  runtime_root: string;
  models_root: string;
  model_count: number;
  worker_ready: boolean;
}
export interface RvcModel {
  id: string;
  name: string;
  model_path: string;
  index_path?: string | null;
  size_bytes: number;
  author?: string | null;
  language?: string | null;
  license?: string | null;
  authorized: boolean;
  created_at?: string | null;
}
export interface RvcJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  message: string;
  source_path: string;
  model_id: string;
  output_path: string;
  pitch: number;
  f0_method: string;
  index_rate: number;
  protect: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
}
export interface SubCleanStatus {
  runtime_ready: boolean;
  profile?: string | null;
  runtime_root: string;
  output_root: string;
}
export interface SubCleanJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  message: string;
  source_path: string;
  output_path: string;
  mode: string;
  areas: number[][];
  error?: string | null;
  created_at: string;
  updated_at: string;
}
export interface InstallPreview {
  engine_id: string;
  display_name: string;
  disk_space_gb: number;
  steps: string[];
  script: string;
  environment_root: string;
  models_root: string;
  cache_root: string;
  credentials: EngineCredential[];
}
export interface ModelDownloadCheck {
  engine_id: string;
  has_model: boolean;
  reachable: boolean;
  repo_id?: string | null;
  file_name?: string | null;
  file_found?: boolean | null;
  revision?: string | null;
  gated?: boolean;
  private?: boolean;
  last_modified?: string | null;
  message: string;
}

export interface VoiceboxStatus {
  online: boolean;
  base_url: string;
  source: string;
  source_ready: boolean;
  runtime_ready: boolean;
  data: string;
  models: string;
  pid: number | null;
}
export interface VoiceboxModel {
  model_name: string;
  display_name: string;
  hf_repo_id?: string | null;
  downloaded: boolean;
  downloading: boolean;
  size_mb?: number | null;
  loaded: boolean;
  engine?: string;
  model_size?: string | null;
  recommended_vram_gb?: number;
  languages?: string[];
  tier?: "light" | "balanced" | "quality" | "studio";
  brand?: EngineBrand;
}
export interface VoiceboxEffect {
  type: string;
  enabled?: boolean;
  params?: Record<string, number | string | boolean>;
}
export interface VoiceboxProfile {
  id: string;
  name: string;
  description?: string | null;
  language?: string | null;
  effects_chain?: VoiceboxEffect[];
  voice_type?: string | null;
  preset_engine?: string | null;
  preset_voice_id?: string | null;
  design_prompt?: string | null;
  default_engine?: string | null;
  personality?: string | null;
  generation_count?: number;
  sample_count?: number;
  created_at?: string;
  updated_at?: string;
}
export interface VoiceboxProfileInput {
  name: string;
  description?: string | null;
  language: string;
  voice_type: "cloned" | "preset" | "designed";
  preset_engine?: string | null;
  preset_voice_id?: string | null;
  design_prompt?: string | null;
  default_engine?: string | null;
  personality?: string | null;
}
export interface VoiceboxPresetVoice {
  voice_id: string;
  name: string;
  gender?: string;
  language?: string;
}
export interface VoiceboxGeneration {
  id: string;
  profile_id: string;
  text: string;
  language: string;
  audio_path?: string | null;
  duration?: number | null;
  seed?: number | null;
  instruct?: string | null;
  engine?: string | null;
  model_size?: string | null;
  status: string;
  error?: string | null;
  created_at: string;
}
export interface VoiceboxGenerateInput {
  profile_id: string;
  text: string;
  language: string;
  engine?: string | null;
  model_size?: string | null;
  instruct?: string | null;
  personality?: boolean;
  max_chunk_chars?: number;
  crossfade_ms?: number;
  normalize?: boolean;
  effects_chain?: VoiceboxEffect[] | null;
}
