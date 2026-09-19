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

export interface TerminologyTerm {
  id: number;
  source_term: string;
  source_language: string;
  target_language: string;
  category: string;
  definition: string;
  preferred_translation: string;
  alternatives: string[];
  forbidden: string[];
  scope: "global" | "project";
  project_id?: string | null;
  status: string;
  confidence: number;
  suspicion_score: number;
  occurrences: number;
  examples: string[];
  sources: { title?: string; url?: string; snippet?: string }[];
  locked: boolean;
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
  output_aspect?: "source" | "16:9" | "9:16" | "1:1" | "4:5" | null;
  performance_profile?: string | null;
  content_type?: ProjectContentType;
  dubbing_mode?: ProjectDubbingMode;
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
  effects_chain?: TtsEffect[];
  character_id?: string | null;
  character_name?: string | null;
  character_role?: string | null;
  sex?: "male" | "female" | "uncertain" | string | null;
  age_group?: "child" | "teen" | "young_adult" | "adult" | "elderly" | "unknown" | string | null;
  importance?: "primary" | "major" | "supporting" | "minor" | "crowd" | string | null;
  dedicated_voice?: boolean;
  voice_archetype?: string | null;
  render_voice_key?: string | null;
  casting_confidence?: number | null;
  casting_status?: "auto" | "needs_review" | "locked" | string | null;
  identity_locked?: boolean;
  voice_locked?: boolean;
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
  subtitleEvidence?: Array<{
    text: string;
    start: number;
    end: number;
    source: string;
    overlap_ratio: number;
    match_confidence: number;
    revision?: string;
  }>;
  translatedText: string;
  adaptedText: string;
  rawTranslation?: string;
  fidelityScore?: number | null;
  fidelityIssues?: Array<{ type?: string; detail?: string }>;
  voiceAudioReady?: boolean;
  voiceAudioDuration?: number | null;
  voiceAudioEngine?: string | null;
  voiceAudioStatus?: "ready" | "failed" | "merged" | null;
  voiceSkip?: boolean;
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
  revision: number;
  narrative_profile: NarrativeProfile;
  narrative_instructions?: string;
  subtitle_evidence_revision?: string | null;
  last_operation?: string | null;
  mix?: MixSettings;
}
export type ProjectContentType =
  | "anime"
  | "manga_recap"
  | "manhwa_recap"
  | "live_action"
  | "gameplay"
  | "podcast"
  | "other";
export type ProjectDubbingMode = "single" | "multi";

export interface TranscriptExportResult {
  format: "manifest" | "chat" | "json" | "srt" | "vtt";
  output_dir: string;
  segment_count: number;
  context_count: number;
  transcript_fingerprint: string;
  files: Array<{ name: string; path: string; size_bytes: number }>;
}

export interface TranscriptImportSample {
  id: string;
  start: string;
  end: string;
  source_text: string;
  previous_text: string;
  target_text: string;
}

export interface TranscriptImportPreview {
  format: string;
  path: string;
  revision: number;
  transcript_fingerprint: string;
  imported_fingerprint?: string | null;
  segment_count: number;
  parsed_count: number;
  matched_count: number;
  changed_count: number;
  untouched_count: number;
  duplicate_ids: string[];
  unknown_ids: string[];
  empty_ids: string[];
  source_mismatch_ids: string[];
  invalid_character_ids: string[];
  character_conflicts: string[];
  invalid_emotion_ids: string[];
  invalid_voice_unit_ids: string[];
  invalid_bridge_ids: string[];
  invalid_registry_ids: string[];
  invalid_casting_ids: string[];
  casting_review_ids: string[];
  invalid_speaker_section_ids: string[];
  missing_registry_ids: string[];
  incomplete_multispeaker: boolean;
  prompt_revision?: string | null;
  expected_prompt_revision?: string | null;
  prompt_revision_mismatch: boolean;
  casting_r4?: boolean;
  dedicated_voice_count?: number;
  narrator_rendered_character_count?: number;
  fingerprint_mismatch: boolean;
  timing_warning_count: number;
  timing_warnings: Array<{
    id: string;
    duration_seconds: number;
    word_count: number;
    words_per_second: number;
    kind: "likely_too_long" | "likely_too_short";
  }>;
  can_apply: boolean;
  samples: TranscriptImportSample[];
}

export interface TranscriptImportResult {
  state: AnalysisState;
  preview: TranscriptImportPreview;
  changed_ids: string[];
  audit_path: string;
  next_stage: "voice_generation";
}

export type NarrativeProfile =
  | "natural_recap"
  | "external_narrator"
  | "cinematic_omniscient"
  | "documentary"
  | "mc_first_person"
  | "dramatic"
  | "dark_suspense"
  | "comedic_ironic"
  | "short_condensed"
  | "multi_character";

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

export interface SharedDependencyState {
  status: string;
  python?: string;
  python_version?: string;
  paths: string[];
  providers: Record<string, string>;
  missing: string[];
  error?: string;
}

export interface AudioPreservationState {
  version: number;
  status: "not_processed" | "running" | "ready" | "failed" | "cancelled" | string;
  progress: number;
  message: string;
  error?: string | null;
  backend: string;
  model: string;
  fingerprint?: string | null;
  duration?: number | null;
  cache_hit: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  tracks: {
    original?: string | null;
    vocals?: string | null;
    bed?: string | null;
  };
  runtime: {
    engine_id: string;
    runtime_root: string;
    python: string;
    execution_provider?: string;
    device?: "cpu" | "cuda" | string;
    device_name?: string | null;
    torch?: string | null;
    cuda?: string | null;
    torchaudio?: string | null;
    worker: string;
    ready_manifest: string;
    installed: boolean;
    adapter_ready: boolean;
    usable: boolean;
    shared_dependencies: SharedDependencyState;
    profiles?: Record<string, {
      engine_id: string;
      usable: boolean;
      device?: string;
      device_name?: string | null;
    }>;
  };
}

export interface DiarizationTurn {
  start: number;
  end: number;
  speaker: string;
}

export interface DiarizationState {
  version: number;
  status: "not_processed" | "running" | "ready" | "failed" | "cancelled" | string;
  progress: number;
  message: string;
  error?: string | null;
  speaker_count: number;
  turn_count: number;
  speakers: string[];
  turns: DiarizationTurn[];
  duration?: number | null;
  elapsed_seconds?: number | null;
  cache_hit: boolean;
  source_path?: string | null;
  manifest_path: string;
  runtime: {
    engine_id: string;
    model_repo: string;
    python: string;
    execution_provider: string;
    shared_runtime: boolean;
    device: "cpu" | "cuda" | string;
    runtime_ready: boolean;
    model_ready: boolean;
    model_path?: string | null;
    worker: string;
    adapter_ready: boolean;
    usable: boolean;
    requires_hf_token: boolean;
    message: string;
  };
  created_at?: string | null;
  updated_at?: string | null;
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
export type SubtitleStyle =
  | "cinema"
  | "social"
  | "minimal"
  | "manga"
  | "documentary";
export type SubtitleCleanup =
  | "none"
  | "auto"
  | "blur"
  | "crop"
  | "subclean";
export interface ExportOptions {
  delivery: ExportDelivery;
  container: ExportContainer;
  video_codec: ExportVideoCodec;
  audio_codec: ExportAudioCodec;
  quality: number;
  preset: "ultrafast" | "veryfast" | "fast" | "medium" | "slow";
  audio_bitrate: string;
  max_output_size_gb: number;
  hardware_acceleration: "auto" | "nvenc" | "cpu";
  resolution: "source" | "720p" | "1080p" | "1440p" | "2160p";
  aspect: "source" | "16:9" | "9:16" | "1:1" | "4:5";
  framing: "fit" | "crop" | "blur";
  reframe_scale: number;
  reframe_x: number;
  reframe_y: number;
  upscale: "off" | "standard" | "clarity" | "ai-anime" | "ai-general";
  normalize_audio: boolean;
  audio_mastering: boolean;
  original_volume: number;
  voice_volume: number;
  music_volume: number;
  ducking: boolean;
  subtitles_enabled: boolean;
  subtitle_style: SubtitleStyle;
  subtitle_position: "bottom" | "top";
  subtitle_cleanup: SubtitleCleanup;
  subtitle_cleanup_band: number;
  subtitle_subclean_mode:
    | "sttn-auto"
    | "sttn-det"
    | "lama"
    | "propainter"
    | "opencv";
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
  phase?: string | null;
  downloaded_bytes?: number | null;
  total_bytes?: number | null;
  speed_bps?: number | null;
  eta_seconds?: number | null;
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
    os_detail?: string;
    python: string;
    cpu: string;
    cpu_threads: number | null;
    ram_gb?: number | null;
    ram_available_gb?: number | null;
    ram_load_percent?: number | null;
    memory: {
      load_percent: number;
      total_bytes: number;
      available_bytes: number;
    } | null;
    cuda: {
      vendor?: string;
      name?: string;
      vram_total_mb?: number | null;
      vram_free_mb?: number | null;
      driver_version?: string;
      cuda_version?: string | null;
    } | null;
  };
  pipeline: Record<string, string>;
}

export interface AppConfig {
  api: { host: string; port: number; base_url: string };
  paths: Record<string, string>;
  preferences: Record<string, unknown>;
  tts?: {
    runtime: string;
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
export type YouTubeMediaType = "video" | "audio";
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
  media_type?: YouTubeMediaType;
  start_seconds?: number | null;
  end_seconds?: number | null;
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

export interface TtsStatus {
  ready: boolean;
  runtime: "dubroom-native-tts";
  daemon_required: false;
  data: string;
  models: string;
  installed_count: number;
  model_count: number;
  active_generations: number;
}
export interface TtsModel {
  id: string;
  family: string;
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
  voice_modes?: Array<"preset" | "cloned" | "designed" | "voice-style-json">;
  sample_rate?: number;
  license?: string;
  source?: string;
  installation_status?: string;
  tier?: "light" | "balanced" | "quality" | "studio";
  brand?: EngineBrand;
  capabilities?: string[];
  speaker_mode?: "single-speaker" | "multi-speaker-native" | string;
  multi_speaker_compatible?: boolean;
  supports_preset?: boolean;
  supports_cloning?: boolean;
  supports_design?: boolean;
  supports_expression?: boolean;
  supports_streaming?: boolean;
  local_only?: boolean;
}
export interface TtsEffect {
  type: string;
  enabled?: boolean;
  params?: Record<string, number | string | boolean>;
}
export interface TtsProfile {
  id: string;
  name: string;
  description?: string | null;
  language?: string | null;
  effects_chain?: TtsEffect[];
  voice_type?: string | null;
  preset_engine?: string | null;
  preset_voice_id?: string | null;
  design_prompt?: string | null;
  default_engine?: string | null;
  personality?: string | null;
  generation_count?: number;
  sample_count?: number;
  prompt_ready?: boolean;
  prompt_count?: number;
  created_at?: string;
  updated_at?: string;
  origin?: string;
  voice_source?: string;
  provider_profile_id?: string | null;
  engine_family?: string | null;
  engine_display_name?: string | null;
  model_size?: string | null;
  speaker_mode?: "single-speaker" | "multi-speaker-native" | string;
  multi_speaker_compatible?: boolean;
  gender?: string | null;
  age_group?: string | null;
  primary_role?: string | null;
  voice_archetype?: string | null;
  casting_tags?: string[];
  usage_scope?: "both" | "single" | "multi" | string;
  age?: string | null;
  pitch?: string | null;
  traits?: string[];
  roles?: string[];
  supports_expression?: boolean;
}

export interface VoiceLibraryBuildState {
  status: "idle" | "queued" | "running" | "ready" | "failed" | "cancelled" | string;
  progress: number;
  message: string;
  error?: string | null;
  selected: string[];
  generated: string[];
  failed: Array<{ id: string; error: string }>;
  full_tests: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  log_path: string;
}

export interface VoiceLibraryTemplate {
  id: string;
  name: string;
  gender: string;
  age: string;
  pitch: string;
  traits: string[];
  roles: string[];
  voice_archetype?: string | null;
  casting_tags?: string[];
  status: "ready" | "failed" | "not_generated" | string;
  profile_id?: string | null;
  speaker_mode: string;
  multi_speaker_compatible: boolean;
}

export interface VoiceLibraryCatalog {
  runtime: {
    ready: boolean;
    python: string;
    model_path: string;
    device: "cpu" | "cuda" | string;
    torch?: string | null;
    cuda?: string | null;
    local_only: boolean;
  };
  build: VoiceLibraryBuildState;
  summary: {
    configured: number;
    generated: number;
    single_speaker: number;
    multi_speaker_assignable: number;
  };
  templates: VoiceLibraryTemplate[];
  engines: Array<{
    id: string;
    display_name: string;
    family: string;
    downloaded: boolean;
    languages: string[];
    speaker_mode: string;
    multi_speaker_compatible: boolean;
    voice_sources: string[];
    supports_preset: boolean;
    supports_cloning: boolean;
    supports_design: boolean;
    supports_expression: boolean;
    supports_streaming: boolean;
    local_only: boolean;
  }>;
  catalog_path: string;
}

export interface VoiceLibraryBuildInput {
  voices?: string[];
  full_tests?: boolean;
  regenerate?: boolean;
  tests_only?: boolean;
}
export interface TtsProfileInput {
  name: string;
  description?: string | null;
  language: string;
  voice_type: "cloned" | "preset" | "designed";
  preset_engine?: string | null;
  preset_voice_id?: string | null;
  design_prompt?: string | null;
  default_engine?: string | null;
  personality?: string | null;
  gender: "female" | "male" | "neutral" | "unspecified";
  age_group: "child" | "teen" | "young_adult" | "adult" | "senior" | "unspecified";
  primary_role: "mc" | "female_lead" | "narrator" | "antagonist" | "supporting" | "child" | "background" | "other";
  roles?: string[];
  usage_scope: "both" | "single" | "multi";
}
export interface TtsPresetVoice {
  voice_id: string;
  name: string;
  gender?: string;
  language?: string;
}
export interface TtsGeneration {
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
  updated_at?: string;
  sample_rate?: number | null;
  device?: string | null;
}
export interface TtsGenerateInput {
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
  effects_chain?: TtsEffect[] | null;
}
