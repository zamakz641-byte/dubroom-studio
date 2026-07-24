import type {
  ActivityFeed,
  AnalysisState,
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
  RuntimeStatus,
  RvcJob,
  RvcModel,
  RvcStatus,
  SubCleanJob,
  SubCleanStatus,
  TimelineProjectState,
  TrashProjectRecord,
  VoiceboxGenerateInput,
  VoiceboxGeneration,
  VoiceboxModel,
  VoiceboxPresetVoice,
  VoiceboxProfile,
  VoiceboxProfileInput,
  VoiceboxStatus,
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
  voiceboxStatus: () => request<VoiceboxStatus>("/voicebox/status"),
  startVoicebox: () =>
    request<VoiceboxStatus>("/voicebox/start", { method: "POST" }),
  voiceboxModels: () =>
    request<{ models: VoiceboxModel[] }>("/voicebox/models").then(
      (result) => result.models,
    ),
  downloadVoiceboxModel: (modelName: string) =>
    request<Record<string, unknown>>("/voicebox/models/download", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName }),
    }),
  cancelVoiceboxModel: (modelName: string) =>
    request<Record<string, unknown>>("/voicebox/models/download/cancel", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName }),
    }),
  voiceboxProfiles: () =>
    request<{ profiles: VoiceboxProfile[] }>("/voicebox/profiles").then(
      (result) => result.profiles,
    ),
  createVoiceboxProfile: (input: VoiceboxProfileInput) =>
    request<VoiceboxProfile>("/voicebox/profiles", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  addVoiceboxSample: (profileId: string, path: string, referenceText: string) =>
    request<Record<string, unknown>>(
      `/voicebox/profiles/${encodeURIComponent(profileId)}/samples`,
      {
        method: "POST",
        body: JSON.stringify({ path, reference_text: referenceText }),
      },
    ),
  addVoiceboxRecordingSample: (
    profileId: string,
    dataUrl: string,
    referenceText: string,
    fileName = "voice-sample.webm",
  ) =>
    request<Record<string, unknown>>(
      `/voicebox/profiles/${encodeURIComponent(profileId)}/samples/recording`,
      {
        method: "POST",
        body: JSON.stringify({
          data_url: dataUrl,
          reference_text: referenceText,
          file_name: fileName,
        }),
      },
    ),
  voiceboxPresets: (engine: string) =>
    request<{ engine: string; voices: VoiceboxPresetVoice[] }>(
      `/voicebox/profiles/presets/${encodeURIComponent(engine)}`,
    ).then((result) => result.voices),
  generateVoicebox: (input: VoiceboxGenerateInput) =>
    request<VoiceboxGeneration>("/voicebox/generate", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  voiceboxGeneration: (id: string) =>
    request<VoiceboxGeneration>(
      `/voicebox/generations/${encodeURIComponent(id)}`,
    ),
  voiceboxGenerationAudioUrl: async (id: string) =>
    `${await baseUrl()}/voicebox/generations/${encodeURIComponent(id)}/audio`,
  probe: (path: string) =>
    request<MediaProbe>("/media/probe", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  prepare: (path: string, name: string) =>
    request<MediaPrepare>("/media/prepare", {
      method: "POST",
      body: JSON.stringify({ path, project_name: name }),
    }),
  youtubeRuntime: () => request<YouTubeRuntime>("/media/youtube/runtime"),
  inspectYouTube: (url: string) =>
    request<YouTubeInfo>("/media/youtube/inspect", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  startYouTubeDownload: (url: string, title?: string) =>
    request<YouTubeDownload>("/media/youtube/downloads", {
      method: "POST",
      body: JSON.stringify({ url, title }),
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
