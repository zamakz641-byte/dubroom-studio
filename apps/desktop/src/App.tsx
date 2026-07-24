import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { ImportHub } from "@/components/ImportHub";
import { api } from "@/lib/api";
import { useAdaptivePerformance } from "@/lib/performance";
import { useI18n } from "@/i18n";
import { notify } from "@/notifications";
import type {
  AnalysisState,
  ActivityRecord,
  AppConfig,
  AppSection,
  EngineRecord,
  ExportOptions,
  InstallPreview,
  JobRecord,
  MediaProbe,
  ProjectRecord,
  RuntimeStatus,
  StudioStep,
  VoiceboxModel,
  VoiceboxProfile,
  VoiceboxStatus,
} from "@/types";

const Onboarding=lazy(()=>import("@/components/Onboarding").then(module=>({default:module.Onboarding})));
const DashboardPage=lazy(()=>import("@/pages/DashboardPage").then(module=>({default:module.DashboardPage})));
const EnginesPage=lazy(()=>import("@/pages/EnginesPage").then(module=>({default:module.EnginesPage})));
const LibraryPage=lazy(()=>import("@/pages/LibraryPage").then(module=>({default:module.LibraryPage})));
const ProjectsPage=lazy(()=>import("@/pages/ProjectsPage").then(module=>({default:module.ProjectsPage})));
const SettingsPage=lazy(()=>import("@/pages/SettingsPage").then(module=>({default:module.SettingsPage})));
const StudioPage=lazy(()=>import("@/pages/StudioPage").then(module=>({default:module.StudioPage})));
const ToolsPage=lazy(()=>import("@/pages/ToolsPage").then(module=>({default:module.ToolsPage})));

function WorkspaceLoading() {
  return (
    <div className="grid h-full place-items-center bg-canvas text-foreground" aria-busy="true">
      <div className="text-center">
        <i className="mx-auto mb-4 block size-8 animate-pulse rounded-full border border-accent/60 bg-accent-soft" />
        <strong className="text-[11px] uppercase tracking-[.2em]">DubRoom Studio</strong>
        <small className="mt-2 block text-[10px] text-muted">Chargement de l’espace de travail…</small>
      </div>
    </div>
  );
}

type BoundaryState = { error: Error | null };
const ONBOARDING_RESET_VERSION = "tailwind-v2-release";
export class AppErrorBoundary extends Component<
  { children: ReactNode },
  BoundaryState
> {
  state: BoundaryState = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[Dubroom UI]", error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="grid min-h-screen place-items-center bg-canvas p-8">
        <div className="ui-panel max-w-xl p-8">
          <span className="ui-kicker">INTERFACE RECOVERY</span>
          <h1 className="mt-2 text-2xl font-semibold">
            La session est restée ouverte.
          </h1>
          <p className="mt-2 text-copy">
            Une vue a rencontré une erreur, mais aucune donnée de projet n’a été
            supprimée.
          </p>
          <pre className="mt-5 overflow-auto rounded-lg bg-canvas p-4 text-xs text-danger">
            {this.state.error.message}
          </pre>
          <button
            className="ui-button ui-button-primary mt-5"
            onClick={() => window.location.reload()}
          >
            Recharger l’interface
          </button>
        </div>
      </main>
    );
  }
}

export default function App() {
  const { t } = useI18n();
  const [onboardingComplete, setOnboardingComplete] = useState(() => {
    if (
      localStorage.getItem("dubroom.onboardingResetVersion") !==
      ONBOARDING_RESET_VERSION
    ) {
      localStorage.removeItem("dubroom.onboardingComplete");
      localStorage.setItem("dubroom.locale", "fr");
      localStorage.setItem(
        "dubroom.onboardingResetVersion",
        ONBOARDING_RESET_VERSION,
      );
      return false;
    }
    return localStorage.getItem("dubroom.onboardingComplete") === "true";
  });
  const [section, setSection] = useState<AppSection>("dashboard");
  const [studioStep, setStudioStep] = useState<StudioStep>("media");
  const [backendOnline, setBackendOnline] = useState(false);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectRecord | null>(
    null,
  );
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [engines, setEngines] = useState<EngineRecord[]>([]);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [voiceboxStatus, setVoiceboxStatus] = useState<VoiceboxStatus | null>(
    null,
  );
  const [voiceboxModels, setVoiceboxModels] = useState<VoiceboxModel[]>([]);
  const [voiceboxProfiles, setVoiceboxProfiles] = useState<VoiceboxProfile[]>(
    [],
  );
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [probe, setProbe] = useState<MediaProbe | null>(null);
  const [streamUrl, setStreamUrl] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const engineStates = useRef<Record<string, string>>({});
  const jobStates = useRef<Record<string, string>>({});
  const activityStates = useRef<Record<string, string>>({});
  const performanceProfile = useAdaptivePerformance(runtime);

  const refreshProjects = async () => {
    const list = await api.projects();
    setProjects(list);
    return list;
  };
  const refreshEngines = async () => {
    const list = await api.engines();
    for (const engine of list)
      engineStates.current[engine.id] = engine.installation.status;
    setEngines(list);
  };
  const refreshActivities = async () => {
    const feed = await api.activities(100);
    for (const activity of feed.activities) {
      const previous = activityStates.current[activity.id];
      if (
        previous &&
        previous !== activity.status &&
        ["completed", "failed", "interrupted", "cancelled"].includes(
          activity.status,
        )
      ) {
        const failed = ["failed", "interrupted"].includes(activity.status);
        notify(
          t(
            failed
              ? "activity.notification.failed"
              : activity.status === "cancelled"
                ? "activity.notification.cancelled"
                : "activity.notification.completed",
          ),
          t(`activity.type.${activity.type}`).startsWith("activity.")
            ? activity.title
            : t(`activity.type.${activity.type}`),
          failed
            ? "error"
            : activity.status === "cancelled"
              ? "warning"
              : "success",
        );
      }
      activityStates.current[activity.id] = activity.status;
    }
    setActivities(feed.activities);
  };
  const refreshVoicebox = async () => {
    const [status, models] = await Promise.all([
      api.voiceboxStatus(),
      api.voiceboxModels(),
    ]);
    setVoiceboxStatus(status);
    setVoiceboxModels(models);
    setVoiceboxProfiles(status.online ? await api.voiceboxProfiles() : []);
  };
  const refreshJobs = async () => {
    if (!activeProject) {
      setJobs([]);
      return;
    }
    const next = await api.jobs(activeProject.id);
    for (const job of next) {
      const previous = jobStates.current[job.id];
      if (
        previous &&
        previous !== job.status &&
        ["completed", "partial", "failed"].includes(job.status)
      ) {
        if (job.type === "translation" && job.status === "completed")
          setAnalysis(await api.analysis(activeProject.id));
      }
      jobStates.current[job.id] = job.status;
    }
    setJobs(next);
  };

  useEffect(() => {
    let alive = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const hydrate = async () => {
      try {
        const [
          healthResult,
          configuration,
          machine,
          projectList,
          engineList,
          vbStatus,
          vbModels,
          activityFeed,
        ] = await Promise.all([
          api.health(),
          api.config(),
          api.runtime(),
          api.projects(),
          api.engines(),
          api.voiceboxStatus(),
          api.voiceboxModels(),
          api.activities(100),
        ]);
        if (!alive) return;
        setBackendOnline(healthResult.status === "ok");
        setConfig(configuration);
        setRuntime(machine);
        setProjects(projectList);
        setEngines(engineList);
        engineStates.current = Object.fromEntries(
          engineList.map((engine) => [engine.id, engine.installation.status]),
        );
        setVoiceboxStatus(vbStatus);
        setVoiceboxModels(vbModels);
        setActivities(activityFeed.activities);
        activityStates.current = Object.fromEntries(
          activityFeed.activities.map((activity) => [
            activity.id,
            activity.status,
          ]),
        );
        if (vbStatus.online) setVoiceboxProfiles(await api.voiceboxProfiles());
        const lastId = localStorage.getItem("dubroom.activeProjectId");
        const last = projectList.find((p) => p.id === lastId);
        if (last) await openProject(last, false);
      } catch (error) {
        if (!alive) return;
        setBackendOnline(false);
        console.error(error);
        retryTimer = setTimeout(hydrate, 1200);
      }
    };

    void hydrate();
    const heartbeat = setInterval(
      () =>
        api
          .health()
          .then((result) => alive && setBackendOnline(result.status === "ok"))
          .catch(() => alive && setBackendOnline(false)),
      3000,
    );
    return () => {
      alive = false;
      if (retryTimer) clearTimeout(retryTimer);
      clearInterval(heartbeat);
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      refreshActivities().catch(() => null);
    }, 1400);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!activeProject) return;
    const timer = setInterval(() => {
      refreshJobs().catch(() => null);
      refreshEngines().catch(() => null);
    }, 3500);
    return () => clearInterval(timer);
  }, [activeProject?.id]);
  useEffect(() => {
    if (section !== "engines") return;
    const timer = setInterval(() => {
      refreshEngines().catch(() => null);
      refreshVoicebox().catch(() => null);
    }, 2200);
    return () => clearInterval(timer);
  }, [section]);

  const openProject = async (project: ProjectRecord, navigate = true) => {
    setActiveProject(project);
    localStorage.setItem("dubroom.activeProjectId", project.id);
    if (navigate) setSection("studio");
    setStudioStep("media");
    try {
      const [state, projectJobs] = await Promise.all([
        api.analysis(project.id),
        api.jobs(project.id),
      ]);
      setAnalysis(state);
      setJobs(projectJobs);
    } catch {
      setAnalysis(null);
      setJobs([]);
    }
    if (project.source_path) {
      try {
        setProbe(await api.probe(project.source_path));
        setStreamUrl(await api.streamUrl(project.source_path));
      } catch {
        setProbe(null);
        setStreamUrl("");
      }
    } else {
      setProbe(null);
      setStreamUrl("");
    }
  };

  const prepareVideoPath = async (path: string, name?: string) => {
    toast.loading("Inspection de la vidéo…", { id: "media" });
    const metadata = await api.probe(path);
    const projectName =
      name?.trim() || metadata.file_name.replace(/\.[^.]+$/, "");
    toast.loading("Préparation de la piste audio…", { id: "media" });
    const prepared = await api.prepare(path, projectName);
    const list = await refreshProjects();
    const project = list.find((p) => p.id === prepared.project_id);
    if (!project) throw new Error("Le projet préparé n’a pas été retrouvé");
    setProbe(metadata);
    setStreamUrl(await api.streamUrl(path));
    await openProject(project);
    setImportOpen(false);
    toast.success("Session créée", { id: "media" });
  };
  const importLocalVideo = async () => {
    const path = await window.dubStudio?.openVideo();
    if (!path) return;
    try {
      await prepareVideoPath(path);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error), {
        id: "media",
      });
    }
  };
  const importVideo = () => setImportOpen(true);

  const createJob = async (
    type: string,
    options: Record<string, unknown> | ExportOptions = {},
  ) => {
    if (!activeProject) {
      toast.error("Ouvrez d’abord un projet");
      return;
    }
    try {
      const job = await api.createJob(activeProject.id, type, options);
      setJobs((current) => [job, ...current]);
      notify("Opération lancée", type.replaceAll("_", " "), "info");
      toast.success("L’opération continue en arrière-plan");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  const updateAnalysis = (next: AnalysisState) => {
    setAnalysis(next);
    if (!activeProject) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(
      () =>
        api
          .saveAnalysis(activeProject.id, next)
          .catch((error) => toast.error(error.message)),
      450,
    );
  };

  const installPreview = (id: string): Promise<InstallPreview> =>
    api.installPreview(id);
  const installEngine = async (
    id: string,
    repair: boolean,
    credentials: Record<string, string>,
  ) => {
    await api.installEngine(id, repair, credentials);
    await refreshEngines();
    const name = engines.find((engine) => engine.id === id)?.display_name || id;
    notify(repair ? "Réparation lancée" : "Installation lancée", name, "info");
    toast.success(repair ? "Réparation démarrée" : "Installation démarrée");
  };

  if (!onboardingComplete)
    return (
      <Suspense fallback={<div className="grid h-full place-items-center bg-canvas text-foreground" aria-busy="true"><div className="text-center"><i className="mx-auto mb-4 block size-9 animate-pulse rounded-full border border-accent bg-accent-soft"/><strong className="text-xs uppercase tracking-[.2em]">DubRoom Studio</strong></div></div>}>
        <Onboarding
          config={config}
          runtime={runtime}
          onComplete={(destination) => {
            setOnboardingComplete(true);
            if (destination === "engines") setSection("engines");
            else if (destination === "import")
              setTimeout(() => void importVideo(), 120);
            else setSection("dashboard");
          }}
        />
      </Suspense>
    );

  let content: ReactNode;
  if (section === "tools")
    content = (
      <ToolsPage
        engines={engines}
        project={activeProject}
        onInstall={installEngine}
        onProjectUpdate={(project) => {
          setActiveProject(project);
          setProjects((current) =>
            current.map((item) => (item.id === project.id ? project : item)),
          );
          if (project.source_path)
            void api.streamUrl(project.source_path).then(setStreamUrl);
        }}
      />
    );
  else if (section === "dashboard")
    content = (
      <DashboardPage
        projects={projects}
        engines={engines}
        jobs={jobs}
        runtime={runtime}
        onImport={importVideo}
        onOpenProject={openProject}
        onNavigate={setSection}
      />
    );
  else if (section === "projects")
    content = (
      <ProjectsPage
        projects={projects}
        activeProjectId={activeProject?.id}
        onImport={importVideo}
        onOpen={openProject}
        onDeleted={async (id) => {
          await api.deleteProject(id);
          setProjects((current) =>
            current.filter((project) => project.id !== id),
          );
          if (activeProject?.id === id) {
            setActiveProject(null);
            setAnalysis(null);
            setJobs([]);
            setProbe(null);
            setStreamUrl("");
            localStorage.removeItem("dubroom.activeProjectId");
            setSection("projects");
          }
          notify(
            "Projet déplacé",
            "Le projet est disponible dans la corbeille.",
            "info",
          );
        }}
        onRestored={async () => {
          await refreshProjects();
        }}
      />
    );
  else if (section === "studio")
    content = (
      <StudioPage
        project={activeProject}
        step={studioStep}
        onStep={setStudioStep}
        analysis={analysis}
        probe={probe}
        streamUrl={streamUrl}
        engines={engines}
        jobs={jobs}
        voiceboxStatus={voiceboxStatus}
        voiceboxModels={voiceboxModels}
        voiceboxProfiles={voiceboxProfiles}
        onRefreshVoicebox={refreshVoicebox}
        onImport={importVideo}
        onAnalyze={() => createJob("asr")}
        onTranslate={() => createJob("translation")}
        onGenerate={() => createJob("voice_generation")}
        onExport={(options) => createJob("export", options)}
        onOpenTools={() => setSection("tools")}
        onSaveAnalysis={updateAnalysis}
      />
    );
  else if (section === "library")
    content = (
      <LibraryPage
        status={voiceboxStatus}
        profiles={voiceboxProfiles}
        models={voiceboxModels}
        onRefresh={refreshVoicebox}
        onStart={async () => {
          await api.startVoicebox();
          await refreshVoicebox();
          notify(
            "Voicebox démarré",
            "La bibliothèque vocale est prête.",
            "success",
          );
        }}
        onOpenTools={() => setSection("tools")}
      />
    );
  else if (section === "engines")
    content = (
      <EnginesPage
        engines={engines}
        voiceboxStatus={voiceboxStatus}
        voiceboxModels={voiceboxModels}
        onInstallVoicebox={async () => {
          const runtimeEngine = engines.find(
            (engine) => engine.id === "voicebox-runtime",
          );
          await installEngine(
            "voicebox-runtime",
            runtimeEngine?.installation.status === "failed",
            {},
          );
        }}
        onStartVoicebox={async () => {
          await api.startVoicebox();
          await refreshVoicebox();
          notify(
            "Voicebox démarré",
            "Le runtime vocal local est connecté.",
            "success",
          );
        }}
        onDownloadVoicebox={async (modelName) => {
          await api.downloadVoiceboxModel(modelName);
          await refreshVoicebox();
          notify(
            "Téléchargement TTS lancé",
            voiceboxModels.find((model) => model.model_name === modelName)
              ?.display_name || modelName,
            "info",
          );
        }}
        onPreview={installPreview}
        onInstall={installEngine}
        onRefresh={() =>
          Promise.all([refreshEngines(), refreshVoicebox()]).catch((error) =>
            toast.error(error.message),
          )
        }
      />
    );
  else content = <SettingsPage config={config} runtime={runtime} />;

  const youtubeEngine =
    engines.find((engine) => engine.id === "yt-dlp") || null;
  return (
    <>
      <AppShell
        section={section}
        onSection={setSection}
        activeProject={activeProject}
        backendOnline={backendOnline}
        activities={activities}
        onRefreshActivities={refreshActivities}
        performanceProfile={performanceProfile}
      >
        <Suspense fallback={<WorkspaceLoading />}>
          {content}
        </Suspense>
      </AppShell>
      {importOpen && (
        <ImportHub
          engine={youtubeEngine}
          onClose={() => setImportOpen(false)}
          onLocal={importLocalVideo}
          onInstall={async () =>
            installEngine(
              "yt-dlp",
              youtubeEngine?.installation.status === "failed",
              {},
            )
          }
          onReady={prepareVideoPath}
        />
      )}
    </>
  );
}
