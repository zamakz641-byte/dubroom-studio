import type {
  ActivityFeed,
  AnalysisState,
  AudioPreservationState,
  DiarizationState,
  AppConfig,
  EngineRecord,
  ExportCapabilities,
  ExportOptions,
  ExportPlan,
  InstallPreview,
  JobRecord,
  LibraryAsset,
  LibraryAssetKind,
  MediaPrepare,
  MediaProbe,
  ModelDownloadCheck,
  ProjectRecord,
  ProjectContentType,
  ProjectDubbingMode,
  RuntimeStatus,
  RvcJob,
  RvcModel,
  RvcStatus,
  SubCleanJob,
  SubCleanStatus,
  TimelineProjectState,
  TrashProjectRecord,
  TranscriptExportResult,
  TranscriptImportPreview,
  TranscriptImportResult,
  TtsGenerateInput,
  TtsGeneration,
  TtsModel,
  TtsPresetVoice,
  TtsProfile,
  TtsProfileInput,
  VoiceLibraryBuildInput,
  VoiceLibraryBuildState,
  VoiceLibraryCatalog,
  TtsStatus,
  YouTubeDownload,
  YouTubeInfo,
  YouTubeRuntime,
} from "@/types";

let baseUrlPromise: Promise<string> | null = null;

async function baseUrl() {
  if (!baseUrlPromise) {
    baseUrlPromise = (async () => {
      if (window.dubStudio?.getRuntimeConfig) {
        return (await window.dubStudio.getRuntimeConfig()).apiBaseUrl;
      }
      const configured = import.meta.env.VITE_API_BASE_URL as
        string | undefined;
      if (configured) return configured;
      // Browser preview used by visual regression tests has no Electron bridge.
      return "http://127.0.0.1:8766";
    })();
  }
  return baseUrlPromise;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${await baseUrl()}${path}`, {
    ...options,
    headers: {
      ...(options?.body ? { "Content-Type": "application/json" } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || `Erreur ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  activities: (limit = 100) => request<ActivityFeed>(`/activities?limit=${limit}`),
  cancelActivity: (id: string) =>
    request<{ status: string; activity_id: string }>(
      `/activities/${encodeURIComponent(id)}/cancel`,
      { method: "POST" },
    ),
  retryActivity: (id: string) =>
    request<{ status: string; source_id: string }>(
      `/activities/${encodeURIComponent(id)}/retry`,
      { method: "POST" },
    ),
  simulateActivities: () =>
    request<{ run_id: string }>("/activities/simulate", { method: "POST" }),
  clearSimulations: () =>
    request<{ deleted: number }>("/activities/simulations", { method: "DELETE" }),
  config: () => request<AppConfig>("/config"),
  runtime: () => request<RuntimeStatus>("/runtime/status"),
  libraryAssets: (kind?: LibraryAssetKind) =>
    request<{ assets: LibraryAsset[] }>(
      `/library/assets${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`,
    ).then((result) => result.assets),
  createLibraryAsset: (input: {
    kind: LibraryAssetKind;
    name: string;
    path?: string | null;
    content?: string;
    metadata?: Record<string, unknown>;
  }) =>
    request<LibraryAsset>("/library/assets", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  deleteLibraryAsset: (id: string) =>
    request<{ deleted: boolean }>(`/library/assets/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  terminologyTerms: (params?: {
    project_id?: string;
    source_language?: string;
    target_language?: string;
    status?: string;
  }) => {
    const query = new URLSearchParams(
      Object.entries(params || {}).filter((entry): entry is [string, string] => Boolean(entry[1])),
    );
    return request<{ terms: import("@/types").TerminologyTerm[] }>(
      `/terminology/terms${query.size ? `?${query}` : ""}`,
    ).then((result) => result.terms);
  },
  approveTerminologyTerm: (id: number, preferred_translation: string, apply_globally = false) =>
    request<import("@/types").TerminologyTerm>(`/terminology/terms/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ preferred_translation, apply_globally }),
    }),
  researchTerminologyTerm: (id: number) =>
    request<{ sources: { title?: string; url?: string; snippet?: string }[] }>(
      `/terminology/terms/${id}/research`,
      { method: "POST" },
    ),
  projects: () =>
    request<{ projects: ProjectRecord[] }>("/projects").then((x) => x.projects),
  trashProjects: () =>
    request<{ projects: TrashProjectRecord[] }>("/projects/trash").then(
      (x) => x.projects,
    ),
  createProject: (name: string) =>
    request<ProjectRecord>("/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  deleteProject: (id: string) =>
    request<{ trash_id: string; deleted_at: string; project: ProjectRecord }>(
      `/projects/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
  restoreProject: (trashId: string) =>
    request<ProjectRecord>(
      `/projects/trash/${encodeURIComponent(trashId)}/restore`,
      { method: "POST" },
    ),
  permanentlyDeleteProject: (trashId: string) =>
    request<{ deleted: boolean }>(
      `/projects/trash/${encodeURIComponent(trashId)}`,
      { method: "DELETE" },
    ),
  analysis: (id: string) =>
    request<AnalysisState>(
      `/projects/${encodeURIComponent(id)}/analysis/state`,
    ),
  saveAnalysis: (id: string, state: AnalysisState) =>
    request<AnalysisState>(
      `/projects/${encodeURIComponent(id)}/analysis/state`,
      { method: "PUT", body: JSON.stringify(state) },
    ),
  audioPreservation: (id: string) =>
    request<AudioPreservationState>(
      `/projects/${encodeURIComponent(id)}/audio/separation`,
    ),
  diarization: (id: string) =>
    request<DiarizationState>(
      `/projects/${encodeURIComponent(id)}/diarization`,
    ),
  separateAudio: (id: string) =>
    request<JobRecord>(
      `/projects/${encodeURIComponent(id)}/audio/separate`,
      { method: "POST" },
    ),
  audioPreservationUrl: async (
    projectId: string,
    track: "original" | "vocals" | "bed",
  ) =>
    `${await baseUrl()}/projects/${encodeURIComponent(projectId)}/audio/preservation/${track}`,
  exportTranscript: (
    id: string,
    format: "manifest" | "chat" | "json" | "srt" | "vtt" = "manifest",
    chunkSize = 60,
  ) =>
    request<TranscriptExportResult>(
      `/projects/${encodeURIComponent(id)}/transcript/export`,
      {
        method: "POST",
        body: JSON.stringify({ format, chunk_size: chunkSize }),
      },
    ),
  previewTranscriptImport: (id: string, path: string) =>
    request<TranscriptImportPreview>(
      `/projects/${encodeURIComponent(id)}/transcript/import/preview`,
      {
        method: "POST",
        body: JSON.stringify({ path }),
      },
    ),
  importTranscript: (
    id: string,
    path: string,
    revision: number,
  ) =>
    request<TranscriptImportResult>(
      `/projects/${encodeURIComponent(id)}/transcript/import`,
      {
        method: "POST",
        body: JSON.stringify({ path, revision }),
      },
    ),
  projectVoiceAudioUrl: async (projectId: string, segmentId: string) =>
    `${await baseUrl()}/projects/${encodeURIComponent(projectId)}/audio/${encodeURIComponent(segmentId)}`,
  timelineState: (id: string) =>
    request<TimelineProjectState>(
      `/projects/${encodeURIComponent(id)}/timeline/state`,
    ),
  saveTimelineState: (id: string, state: TimelineProjectState) =>
    request<TimelineProjectState>(
      `/projects/${encodeURIComponent(id)}/timeline/state`,
      { method: "PUT", body: JSON.stringify(state) },
    ),
  jobs: (id: string) =>
    request<{ jobs: JobRecord[] }>(
      `/projects/${encodeURIComponent(id)}/jobs`,
    ).then((x) => x.jobs),
  createJob: (
    id: string,
    type: string,
    options: Record<string, unknown> | ExportOptions = {},
  ) =>
    request<JobRecord>(`/projects/${encodeURIComponent(id)}/jobs`, {
      method: "POST",
      body: JSON.stringify({ type, options }),
    }),
  cancelJob: (projectId: string, jobId: string) =>
    request<JobRecord>(
      `/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: "POST" },
    ),
  exportCapabilities: () =>
    request<ExportCapabilities>("/exports/capabilities"),
  exportPlan: (id: string, options: ExportOptions, durationSeconds?: number) =>
    request<ExportPlan>(`/projects/${encodeURIComponent(id)}/exports/plan`, {
      method: "POST",
      body: JSON.stringify({ options, duration_seconds: durationSeconds }),
    }),
  engines: () =>
    request<{ engines: EngineRecord[] }>("/engines").then((x) => x.engines),
  installPreview: (id: string) =>
    request<InstallPreview>(
      `/engines/${encodeURIComponent(id)}/install-preview`,
    ),
  downloadCheck: (id: string) =>
    request<ModelDownloadCheck>(
      `/engines/${encodeURIComponent(id)}/download-check`,
    ),
  installEngine: (
    id: string,
    repair = false,
    credentials: Record<string, string> = {},
  ) =>
    request<{ status: string }>(`/engines/${encodeURIComponent(id)}/install`, {
      method: "POST",
      body: JSON.stringify({ repair, dry_run: false, credentials }),
    }),
  ttsStatus: () => request<TtsStatus>("/tts/status"),
  ttsModels: () =>
    request<{ models: TtsModel[] }>("/tts/models").then(
      (result) => result.models,
    ),
  ttsProfiles: () =>
    request<{ profiles: TtsProfile[] }>("/tts/profiles").then(
      (result) => result.profiles,
    ),
  voiceLibrary: () => request<VoiceLibraryCatalog>("/tts/voice-library"),
  buildOmniVoiceLibrary: (input: VoiceLibraryBuildInput) =>
    request<VoiceLibraryBuildState>("/tts/voice-library/omnivoice/build", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  cancelOmniVoiceLibrary: () =>
    request<VoiceLibraryBuildState>("/tts/voice-library/omnivoice/cancel", {
      method: "POST",
    }),
  createTtsProfile: (input: TtsProfileInput) =>
    request<TtsProfile>("/tts/profiles", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  addTtsSample: (profileId: string, path: string, referenceText: string) =>
    request<Record<string, unknown>>(
      `/tts/profiles/${encodeURIComponent(profileId)}/samples`,
      {
        method: "POST",
        body: JSON.stringify({ path, reference_text: referenceText }),
      },
    ),
  addTtsRecordingSample: (
    profileId: string,
    dataUrl: string,
    referenceText: string,
    fileName = "voice-sample.webm",
  ) =>
    request<Record<string, unknown>>(
      `/tts/profiles/${encodeURIComponent(profileId)}/samples/recording`,
      {
        method: "POST",
        body: JSON.stringify({
          data_url: dataUrl,
          reference_text: referenceText,
          file_name: fileName,
        }),
      },
    ),
  ttsPresets: (engine: string) =>
    request<{ engine: string; voices: TtsPresetVoice[] }>(
      `/tts/profiles/presets/${encodeURIComponent(engine)}`,
    ).then((result) => result.voices),
  generateTts: (input: TtsGenerateInput) =>
    request<TtsGeneration>("/tts/generate", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  ttsGeneration: (id: string) =>
    request<TtsGeneration>(
      `/tts/generations/${encodeURIComponent(id)}`,
    ),
  ttsGenerations: (profileId?: string, limit = 50) =>
    request<{ generations: TtsGeneration[] }>(
      `/tts/generations?limit=${limit}${profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ""}`,
    ).then((result) => result.generations),
  ttsGenerationAudioUrl: async (id: string) =>
    `${await baseUrl()}/tts/generations/${encodeURIComponent(id)}/audio`,
  probe: (path: string) =>
    request<MediaProbe>("/media/probe", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  prepare: (
    path: string,
    name: string,
    sourceLanguage?: string | null,
    targetLanguage?: string | null,
    outputAspect?: string | null,
    contentType: ProjectContentType = "other",
    dubbingMode: ProjectDubbingMode = "single",
  ) =>
    request<MediaPrepare>("/media/prepare", {
      method: "POST",
      body: JSON.stringify({
        path,
        project_name: name,
        source_language: sourceLanguage === "auto" ? null : sourceLanguage,
        target_language: targetLanguage || null,
        output_aspect: outputAspect || "source",
        content_type: contentType,
        dubbing_mode: dubbingMode,
      }),
    }),
  youtubeRuntime: () => request<YouTubeRuntime>("/media/youtube/runtime"),
  inspectYouTube: (url: string) =>
    request<YouTubeInfo>("/media/youtube/inspect", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  startYouTubeDownload: (
    url: string,
    title?: string,
    options?: {
      mediaType?: "video" | "audio";
      startSeconds?: number | null;
      endSeconds?: number | null;
    },
  ) =>
    request<YouTubeDownload>("/media/youtube/downloads", {
      method: "POST",
      body: JSON.stringify({
        url,
        title,
        media_type: options?.mediaType || "video",
        start_seconds: options?.startSeconds ?? null,
        end_seconds: options?.endSeconds ?? null,
      }),
    }),
  youtubeDownload: (id: string) =>
    request<YouTubeDownload>(
      `/media/youtube/downloads/${encodeURIComponent(id)}`,
    ),
  cancelYouTubeDownload: (id: string) =>
    request<YouTubeDownload>(
      `/media/youtube/downloads/${encodeURIComponent(id)}/cancel`,
      { method: "POST" },
    ),
  rvcStatus: () => request<RvcStatus>("/rvc/status"),
  rvcModels: () =>
    request<{ models: RvcModel[] }>("/rvc/models").then(
      (result) => result.models,
    ),
  importRvcModel: (input: {
    model_path: string;
    index_path?: string | null;
    name: string;
    author?: string | null;
    license?: string | null;
    authorized: boolean;
  }) =>
    request<RvcModel>("/rvc/models/import", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  startRvc: (input: {
    source_path: string;
    model_id: string;
    pitch: number;
    f0_method: string;
    index_rate: number;
    protect: number;
  }) =>
    request<RvcJob>("/rvc/jobs", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  rvcJob: (id: string) =>
    request<RvcJob>(`/rvc/jobs/${encodeURIComponent(id)}`),
  cancelRvc: (id: string) =>
    request<RvcJob>(`/rvc/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  rvcAudioUrl: async (id: string) =>
    `${await baseUrl()}/rvc/jobs/${encodeURIComponent(id)}/audio`,
  subcleanStatus: () => request<SubCleanStatus>("/subclean/status"),
  startSubClean: (input: {
    source_path: string;
    mode: string;
    areas: number[][];
  }) =>
    request<SubCleanJob>("/subclean/jobs", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  subcleanJob: (id: string) =>
    request<SubCleanJob>(`/subclean/jobs/${encodeURIComponent(id)}`),
  cancelSubClean: (id: string) =>
    request<SubCleanJob>(`/subclean/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  applyDerivedSource: (projectId: string, path: string, kind = "subclean") =>
    request<ProjectRecord>(
      `/projects/${encodeURIComponent(projectId)}/derived-source`,
      { method: "POST", body: JSON.stringify({ path, kind }) },
    ),
  restoreOriginalSource: (projectId: string) =>
    request<ProjectRecord>(
      `/projects/${encodeURIComponent(projectId)}/restore-source`,
      { method: "POST" },
    ),
  streamUrl: async (path: string) =>
    `${await baseUrl()}/media/stream?path=${encodeURIComponent(path)}`,
};
