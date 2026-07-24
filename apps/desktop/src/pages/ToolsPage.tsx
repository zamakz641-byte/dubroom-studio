import {
  Activity,
  AudioLines,
  Check,
  CloudDownload,
  FileAudio,
  FolderInput,
  Gauge,
  Layers3,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  ScanText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  Video,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type {
  EngineRecord,
  ProjectRecord,
  RvcJob,
  RvcModel,
  RvcStatus,
  SubCleanJob,
  SubCleanStatus,
} from "@/types";
type ToolTab = "rvc" | "subclean";
type Props = {
  engines: EngineRecord[];
  project: ProjectRecord | null;
  onInstall: (
    id: string,
    repair: boolean,
    credentials: Record<string, string>,
  ) => Promise<void>;
  onProjectUpdate: (project: ProjectRecord) => void;
};
export function ToolsPage({
  engines,
  project,
  onInstall,
  onProjectUpdate,
}: Props) {
  const { t } = useI18n();
  const [tab, setTab] = useState<ToolTab>("rvc");
  const [rvcStatus, setRvcStatus] = useState<RvcStatus | null>(null);
  const [subStatus, setSubStatus] = useState<SubCleanStatus | null>(null);
  const [models, setModels] = useState<RvcModel[]>([]);
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    const [rvc, sub, library] = await Promise.all([
      api.rvcStatus(),
      api.subcleanStatus(),
      api.rvcModels(),
    ]);
    setRvcStatus(rvc);
    setSubStatus(sub);
    setModels(library);
  };
  useEffect(() => {
    void refresh().catch(() => null);
  }, []);
  const install = async (id: string) => {
    const engine = engines.find((item) => item.id === id);
    setBusy(true);
    try {
      await onInstall(id, engine?.installation.status === "failed", {});
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    if (!project?.original_source_path) return;
    setBusy(true);
    try {
      const updated = await api.restoreOriginalSource(project.id);
      onProjectUpdate(updated);
      toast.success(t("subclean.restored"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };
  const toolItems = [
    {
      id: "rvc" as const,
      icon: AudioLines,
      kicker: "tools.rvcKind",
      label: "tools.rvc",
      ready: rvcStatus?.runtime_ready,
      description: "rvc.body",
    },
    {
      id: "subclean" as const,
      icon: ScanText,
      kicker: "tools.videoKind",
      label: "tools.subclean",
      ready: subStatus?.runtime_ready,
      description: "subclean.body",
    },
  ];
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHeader
        kicker={t("tools.kicker")}
        title={t("tools.title")}
        description={t("tools.description")}
        actions={
          <>
            {project?.original_source_path &&
              project.source_path !== project.original_source_path && (
                <button
                  className="ui-button"
                  disabled={busy}
                  onClick={() => void restore()}
                >
                  <RotateCcw />
                  {t("subclean.restore")}
                </button>
              )}
            <button className="ui-button" onClick={() => void refresh()}>
              <RefreshCw />
              {t("common.refresh")}
            </button>
          </>
        }
      />
      <div className="grid min-h-0 flex-1 grid-cols-[256px_minmax(0,1fr)] overflow-hidden max-[980px]:grid-cols-[184px_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-r border-line bg-surface/60 p-3">
          <div className="px-2 pb-3 pt-1">
            <span className="ui-kicker">{t("tools.kicker")}</span>
            <p className="mt-2 text-[11px] leading-5 text-muted max-[980px]:hidden">
              {t("tools.description")}
            </p>
          </div>
          <nav data-testid="tools-tabs" className="grid gap-2" aria-label={t("common.tools")}>
            {toolItems.map((item) => {
              const Icon = item.icon;
              const active = tab === item.id;
              return (
                <button
                  key={item.id}
                  className={`group relative flex min-h-20 w-full items-start gap-3 overflow-hidden rounded-xl border p-3 text-left transition-colors ${active ? "border-accent/70 bg-accent/[0.08] shadow-[inset_3px_0_0_var(--accent)]" : "border-line bg-raised/55 hover:border-copy/40 hover:bg-raised"}`}
                  onClick={() => setTab(item.id)}
                >
                  <span
                    className={`grid size-9 shrink-0 place-items-center rounded-lg ${active ? "bg-accent text-accent-contrast" : "bg-canvas text-muted group-hover:text-copy"}`}
                  >
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1 pt-0.5">
                    <small className="ui-kicker block whitespace-normal text-[10px] leading-3 max-[980px]:hidden">
                      {t(item.kicker)}
                    </small>
                    <strong className="mt-1 block text-[12px] leading-4">
                      {t(item.label)}
                    </strong>
                  </span>
                  <span
                    className={`mt-1 size-2 shrink-0 rounded-full ${item.ready ? "bg-success" : "bg-warning"}`}
                    title={t(item.ready ? "tools.ready" : "tools.missing")}
                  />
                </button>
              );
            })}
          </nav>
          <div className="mt-auto rounded-xl border border-line bg-canvas/70 p-3 max-[980px]:hidden">
            <div className="flex items-center gap-2 text-success">
              <ShieldCheck className="size-4" />
              <strong className="text-[11px]">{t("subclean.safe")}</strong>
            </div>
            <p className="mt-2 text-[10px] leading-4 text-muted">
              {t("subclean.safeBody")}
            </p>
          </div>
        </aside>
        <main className="min-h-0 min-w-0 overflow-auto bg-canvas p-5 lg:p-6">
          {tab === "rvc" ? (
            <RvcWorkbench
              status={rvcStatus}
              models={models}
              busy={busy}
              onInstall={() => install("rvc-runtime")}
              onRefresh={refresh}
            />
          ) : (
            <SubCleanWorkbench
              status={subStatus}
              project={project}
              busy={busy}
              onInstall={() => install("subclean-runtime")}
              onProjectUpdate={onProjectUpdate}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function RvcWorkbench({
  status,
  models,
  busy,
  onInstall,
  onRefresh,
}: {
  status: RvcStatus | null;
  models: RvcModel[];
  busy: boolean;
  onInstall: () => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [modelPath, setModelPath] = useState("");
  const [indexPath, setIndexPath] = useState("");
  const [name, setName] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [source, setSource] = useState("");
  const [selected, setSelected] = useState("");
  const [pitch, setPitch] = useState(0);
  const [indexRate, setIndexRate] = useState(0.75);
  const [protect, setProtect] = useState(0.33);
  const [job, setJob] = useState<RvcJob | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(
      () =>
        api
          .rvcJob(job.id)
          .then((next) => {
            setJob(next);
            if (next.status === "completed")
              void api.rvcAudioUrl(next.id).then(setAudioUrl);
          })
          .catch(() => null),
      900,
    );
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  const chooseModel = async () => {
    const path = await window.dubStudio?.openRvcModel();
    if (path) {
      setModelPath(path);
      setName(
        path
          .split(/[\\/]/)
          .pop()
          ?.replace(/\.pth$/i, "") || "",
      );
    }
  };
  const importModel = async () => {
    if (!modelPath || !name.trim()) return;
    setWorking(true);
    try {
      await api.importRvcModel({
        model_path: modelPath,
        index_path: indexPath || null,
        name: name.trim(),
        authorized,
      });
      await onRefresh();
      setModelPath("");
      setIndexPath("");
      setName("");
      setAuthorized(false);
      toast.success(t("rvc.imported"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  const convert = async () => {
    if (!source || !selected) return;
    setWorking(true);
    setAudioUrl("");
    try {
      setJob(
        await api.startRvc({
          source_path: source,
          model_id: selected,
          pitch,
          f0_method: "rmvpe",
          index_rate: indexRate,
          protect,
        }),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  if (!status?.runtime_ready)
    return (
      <RuntimeGate
        icon={AudioLines}
        title={t("rvc.runtimeTitle")}
        body={t("rvc.runtimeBody")}
        steps={[
          { title: t("rvc.models"), body: t("rvc.modelsBody") },
          { title: t("rvc.chooseAudio"), body: t("rvc.audioFormats") },
          { title: t("rvc.convert"), body: t("rvc.convertBody") },
        ]}
        busy={busy}
        onInstall={onInstall}
      />
    );
  return (
    <div className="grid min-w-0 gap-4">
      <ToolHead
        icon={AudioLines}
        kicker={t("rvc.signalPath")}
        title={t("rvc.title")}
        body={t("rvc.body")}
      />
      <div className="grid min-w-0 grid-cols-1 gap-4 min-[1180px]:grid-cols-[minmax(280px,0.8fr)_minmax(420px,1.2fr)]">
        <section className="ui-panel p-4">
          <ModuleHead
            number="01"
            title={t("rvc.models")}
            body={t("rvc.modelsBody")}
            icon={FolderInput}
          />
          <div className="mt-4 grid max-h-64 gap-2 overflow-auto">
            {models.map((model) => (
              <button
                key={model.id}
                className={`flex items-center gap-3 rounded-lg border p-3 text-left ${selected === model.id ? "border-accent bg-accent/5" : "border-line bg-raised"}`}
                onClick={() => setSelected(model.id)}
              >
                <span className="grid size-9 place-items-center rounded-lg bg-canvas text-[10px] text-accent">
                  {model.name.slice(0, 2).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <strong className="block truncate text-[11px]">
                    {model.name}
                  </strong>
                  <small className="text-[11px] text-muted">
                    {formatBytes(model.size_bytes)} ·{" "}
                    {model.index_path ? t("rvc.indexReady") : t("rvc.noIndex")}
                  </small>
                </span>
                {selected === model.id && (
                  <Check className="size-4 text-accent" />
                )}
              </button>
            ))}
            {!models.length && (
              <Empty
                icon={Layers3}
                title={t("rvc.empty")}
                body={t("rvc.emptyBody")}
              />
            )}
          </div>
          <details className="mt-4 rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-[11px] font-medium">
              {t("rvc.import")}
            </summary>
            <div className="mt-3 grid gap-2">
              <button
                className="ui-button justify-start truncate"
                onClick={() => void chooseModel()}
              >
                <FolderInput />
                {modelPath || t("rvc.choosePth")}
              </button>
              <button
                className="ui-button justify-start truncate"
                onClick={async () => {
                  const path = await window.dubStudio?.openRvcIndex();
                  if (path) setIndexPath(path);
                }}
              >
                <FolderInput />
                {indexPath || t("rvc.chooseIndex")}
              </button>
              <input
                className="ui-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("rvc.name")}
              />
              <label className="flex items-center gap-2 text-[10px] text-copy">
                <input
                  type="checkbox"
                  checked={authorized}
                  onChange={(event) => setAuthorized(event.target.checked)}
                />
                <ShieldCheck className="size-4 text-success" />
                {t("rvc.authorization")}
              </label>
              <button
                className="ui-button ui-button-primary"
                disabled={working || !modelPath || !name.trim() || !authorized}
                onClick={() => void importModel()}
              >
                {working ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <FolderInput />
                )}
                {t("rvc.import")}
              </button>
            </div>
          </details>
        </section>
        <section className="ui-panel p-4">
          <ModuleHead
            number="02"
            title={t("rvc.convert")}
            body={t("rvc.convertBody")}
            icon={SlidersHorizontal}
          />
          <button
            className="mt-4 flex w-full items-center gap-3 rounded-lg border border-dashed border-line bg-canvas p-4 text-left"
            onClick={async () => {
              const path = await window.dubStudio?.openAudio();
              if (path) setSource(path);
            }}
          >
            <FileAudio className="text-accent" />
            <span className="min-w-0">
              <strong className="block truncate text-[11px]">
                {source.split(/[\\/]/).pop() || t("rvc.chooseAudio")}
              </strong>
              <small className="text-[11px] text-muted">
                {t("rvc.audioFormats")}
              </small>
            </span>
          </button>
          <Control
            label={t("rvc.pitch")}
            value={`${pitch > 0 ? "+" : ""}${pitch}`}
            min={-12}
            max={12}
            step={1}
            current={pitch}
            onChange={setPitch}
          />
          <Control
            label={t("rvc.indexRate")}
            value={`${Math.round(indexRate * 100)}%`}
            min={0}
            max={1}
            step={0.05}
            current={indexRate}
            onChange={setIndexRate}
          />
          <Control
            label={t("rvc.protect")}
            value={protect.toFixed(2)}
            min={0}
            max={0.5}
            step={0.01}
            current={protect}
            onChange={setProtect}
          />
          <button
            className="ui-button ui-button-primary mt-4 w-full"
            disabled={
              working ||
              !source ||
              !selected ||
              (!!job && ["queued", "running"].includes(job.status))
            }
            onClick={() => void convert()}
          >
            {job && ["queued", "running"].includes(job.status) ? (
              <LoaderCircle className="animate-spin" />
            ) : (
              <Sparkles />
            )}
            {t("rvc.convertAction")}
          </button>
          {job && (
            <JobSignal
              job={job}
              onCancel={() => api.cancelRvc(job.id).then(setJob)}
            />
          )}{" "}
          {audioUrl && (
            <audio className="mt-3 h-9 w-full" controls src={audioUrl} />
          )}
        </section>
      </div>
    </div>
  );
}

function SubCleanWorkbench({
  status,
  project,
  busy,
  onInstall,
  onProjectUpdate,
}: {
  status: SubCleanStatus | null;
  project: ProjectRecord | null;
  busy: boolean;
  onInstall: () => Promise<void>;
  onProjectUpdate: (project: ProjectRecord) => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState("sttn-auto");
  const [manual, setManual] = useState(false);
  const [coords, setCoords] = useState([700, 1080, 0, 1920]);
  const [job, setJob] = useState<SubCleanJob | null>(null);
  const [preview, setPreview] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(
      () =>
        api
          .subcleanJob(job.id)
          .then((next) => {
            setJob(next);
            if (next.status === "completed")
              void api.streamUrl(next.output_path).then(setPreview);
          })
          .catch(() => null),
      1000,
    );
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  const start = async () => {
    if (!project?.source_path) return;
    setWorking(true);
    setPreview("");
    try {
      setJob(
        await api.startSubClean({
          source_path: project.source_path,
          mode,
          areas: manual ? [coords] : [],
        }),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  const apply = async () => {
    if (!job?.output_path || !project) return;
    setWorking(true);
    try {
      const updated = await api.applyDerivedSource(project.id, job.output_path);
      onProjectUpdate(updated);
      toast.success(t("subclean.applied"));
    } finally {
      setWorking(false);
    }
  };
  if (!status?.runtime_ready)
    return (
      <RuntimeGate
        icon={ScanText}
        title={t("subclean.runtimeTitle")}
        body={t("subclean.runtimeBody")}
        steps={[
          { title: t("subclean.method"), body: t("subclean.methodBody") },
          { title: t("subclean.manual"), body: t("subclean.manualBody") },
          { title: t("subclean.compare"), body: t("subclean.compareBody") },
        ]}
        busy={busy}
        onInstall={onInstall}
      />
    );
  if (!project)
    return (
      <Empty
        icon={Video}
        title={t("subclean.noProject")}
        body={t("subclean.noProjectBody")}
      />
    );
  return (
    <div className="grid min-w-0 gap-4">
      <ToolHead
        icon={ScanText}
        kicker={t("subclean.preflight")}
        title={t("subclean.title")}
        body={t("subclean.body")}
      />
      <div className="grid min-w-0 grid-cols-1 gap-4 min-[1180px]:grid-cols-2">
        <section className="ui-panel p-4">
          <ModuleHead
            number="01"
            title={t("subclean.method")}
            body={t("subclean.methodBody")}
            icon={Gauge}
          />
          <div className="mt-4 grid grid-cols-2 gap-2">
            {[
              ["sttn-auto", "AUTO", "subclean.auto"],
              ["lama", "LAMA", "subclean.anime"],
              ["propainter", "PRO", "subclean.quality"],
              ["opencv", "FAST", "subclean.preview"],
            ].map(([id, badge, key]) => (
              <button
                key={id}
                className={`rounded-lg border p-3 text-left ${mode === id ? "border-accent bg-accent/5" : "border-line bg-raised"}`}
                onClick={() => setMode(id)}
              >
                <small className="ui-kicker">{badge}</small>
                <strong className="mt-1 block text-[11px]">{t(key)}</strong>
              </button>
            ))}
          </div>
          <label className="mt-4 flex items-center gap-2 text-[10px]">
            <input
              type="checkbox"
              checked={manual}
              onChange={(event) => setManual(event.target.checked)}
            />
            {t("subclean.manual")}
          </label>
          {manual && (
            <div className="mt-3 grid grid-cols-4 gap-2">
              {["Y min", "Y max", "X min", "X max"].map((label, index) => (
                <label key={label}>
                  <span className="ui-label">{label}</span>
                  <input
                    className="ui-input mt-1"
                    type="number"
                    min={0}
                    value={coords[index]}
                    onChange={(event) =>
                      setCoords((current) =>
                        current.map((value, i) =>
                          i === index ? Number(event.target.value) : value,
                        ),
                      )
                    }
                  />
                </label>
              ))}
            </div>
          )}
          <button
            className="ui-button ui-button-primary mt-4 w-full"
            disabled={
              working || (!!job && ["queued", "running"].includes(job.status))
            }
            onClick={() => void start()}
          >
            <ScanText />
            {t("subclean.start")}
          </button>
          {job && (
            <JobSignal
              job={job}
              onCancel={() => api.cancelSubClean(job.id).then(setJob)}
            />
          )}
        </section>
        <section className="ui-panel p-4">
          <ModuleHead
            number="02"
            title={t("subclean.compare")}
            body={t("subclean.compareBody")}
            icon={Video}
          />
          <div className="mt-4 grid aspect-video place-items-center overflow-hidden rounded-lg border border-line bg-black">
            {preview ? (
              <video
                className="size-full object-contain"
                src={preview}
                controls
              />
            ) : (
              <div className="text-center">
                <ScanText className="mx-auto text-muted" />
                <strong className="mt-3 block text-[11px]">
                  {t("subclean.waiting")}
                </strong>
              </div>
            )}
          </div>
          {job?.status === "completed" && (
            <button
              className="ui-button ui-button-primary mt-4 w-full"
              disabled={working}
              onClick={() => void apply()}
            >
              <Check />
              {t("subclean.useSource")}
            </button>
          )}
        </section>
      </div>
    </div>
  );
}

function RuntimeGate({
  icon: Icon,
  title,
  body,
  steps,
  busy,
  onInstall,
}: {
  icon: typeof AudioLines;
  title: string;
  body: string;
  steps: Array<{ title: string; body: string }>;
  busy: boolean;
  onInstall: () => Promise<void>;
}) {
  const { t } = useI18n();
  return (
    <div className="grid min-w-0 gap-4">
      <section className="ui-panel overflow-hidden">
        <header className="flex flex-wrap items-start gap-5 border-b border-line p-6">
          <span className="grid size-14 shrink-0 place-items-center rounded-2xl border border-warning/25 bg-warning/10 text-warning shadow-[0_10px_36px_color-mix(in_srgb,var(--warning)_12%,transparent)]">
            <Icon className="size-6" />
          </span>
          <div className="min-w-64 flex-1">
            <small className="ui-kicker">{t("tools.runtimeMissing")}</small>
            <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em]">
              {title}
            </h2>
            <p className="mt-2 max-w-3xl text-[12px] leading-5 text-copy">
              {body}
            </p>
          </div>
          <button
            className="ui-button ui-button-primary min-h-10 shrink-0 px-5"
            disabled={busy}
            onClick={() => void onInstall()}
          >
            {busy ? (
              <LoaderCircle className="animate-spin" />
            ) : (
              <CloudDownload />
            )}
            {t("tools.installRuntime")}
          </button>
        </header>

        <div className="grid gap-px bg-line lg:grid-cols-3">
          {[
            [ShieldCheck, "01", t("tools.isolated")],
            [Layers3, "02", t("tools.noModels")],
            [FolderInput, "03", t("tools.localDisk")],
          ].map(([FeatureIcon, number, label]) => (
            <div
              key={number as string}
              className="flex min-h-24 items-start gap-3 bg-surface p-5"
            >
              <FeatureIcon className="mt-0.5 size-4 shrink-0 text-success" />
              <span>
                <small className="font-mono text-[10px] text-muted">
                  {number as string}
                </small>
                <strong className="mt-1 block text-[11px] leading-5">
                  {label as string}
                </strong>
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="ui-panel p-5">
        <div className="mb-4 flex items-center gap-3">
          <Activity className="size-4 text-accent" />
          <span>
            <small className="ui-kicker">{t("rvc.signalPath")}</small>
            <h3 className="mt-1 text-[13px] font-semibold">{title}</h3>
          </span>
        </div>
        <div className="grid gap-3 lg:grid-cols-3">
          {steps.map((step, index) => (
            <article
              key={step.title}
              className="relative min-h-28 overflow-hidden rounded-xl border border-line bg-raised/70 p-4"
            >
              <span className="font-mono text-[10px] text-accent">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h4 className="mt-3 text-[12px] font-semibold">{step.title}</h4>
              <p className="mt-1 text-[10px] leading-4 text-muted">
                {step.body}
              </p>
              <span className="absolute -bottom-4 -right-2 font-mono text-6xl font-semibold text-foreground/[0.025]">
                {index + 1}
              </span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
function ToolHead({
  icon: Icon,
  kicker,
  title,
  body,
}: {
  icon: typeof AudioLines;
  kicker: string;
  title: string;
  body: string;
}) {
  return (
    <header className="ui-panel flex items-center gap-4 p-5">
      <span className="grid size-10 place-items-center rounded-lg bg-accent/10 text-accent">
        <Icon />
      </span>
      <span>
        <small className="ui-kicker">{kicker}</small>
        <h2 className="mt-1 text-[17px] font-semibold">{title}</h2>
        <p className="mt-1 text-[10px] text-copy">{body}</p>
      </span>
    </header>
  );
}
function ModuleHead({
  number,
  title,
  body,
  icon: Icon,
}: {
  number: string;
  title: string;
  body: string;
  icon: typeof Gauge;
}) {
  return (
    <header className="flex items-start gap-3">
      <span className="font-mono text-[10px] text-accent">{number}</span>
      <Icon className="size-4 text-muted" />
      <span>
        <h3 className="text-[13px] font-semibold">{title}</h3>
        <p className="mt-1 text-[11px] text-muted">{body}</p>
      </span>
    </header>
  );
}
function Control({
  label,
  value,
  min,
  max,
  step,
  current,
  onChange,
}: {
  label: string;
  value: string;
  min: number;
  max: number;
  step: number;
  current: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="mt-4 grid gap-2">
      <span className="flex justify-between text-[10px]">
        <strong>{label}</strong>
        <em className="font-mono not-italic text-accent">{value}</em>
      </span>
      <input
        className="accent-[var(--accent)]"
        type="range"
        min={min}
        max={max}
        step={step}
        value={current}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}
function JobSignal({
  job,
  onCancel,
}: {
  job: {
    status: string;
    progress: number;
    message: string;
    error?: string | null;
  };
  onCancel: () => Promise<unknown>;
}) {
  const { t } = useI18n();
  const active = ["queued", "running"].includes(job.status);
  return (
    <div className="mt-4 rounded-lg border border-line bg-canvas p-3">
      <div className="flex items-center gap-3">
        {active ? (
          <Activity className="size-4 animate-pulse text-accent" />
        ) : job.status === "completed" ? (
          <Check className="size-4 text-success" />
        ) : (
          <Square className="size-4 text-danger" />
        )}
        <span className="min-w-0 flex-1">
          <strong className="block truncate text-[10px]">{job.message}</strong>
          <small className="text-[11px] text-muted">
            {job.error || t(`activity.status.${job.status}`)}
          </small>
        </span>
        <em className="font-mono text-[11px] not-italic">{job.progress}%</em>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded bg-raised">
        <i
          className="block h-full bg-accent"
          style={{ width: `${Math.max(job.progress, active ? 4 : 0)}%` }}
        />
      </div>
      {active && (
        <button
          className="mt-2 text-[11px] text-danger"
          onClick={() => void onCancel()}
        >
          {t("common.cancel")}
        </button>
      )}
    </div>
  );
}
function Empty({
  icon: Icon,
  title,
  body,
}: {
  icon: typeof Video;
  title: string;
  body: string;
}) {
  return (
    <div className="ui-panel grid min-h-72 w-full place-items-center text-center">
      <div>
        <Icon className="mx-auto size-8 text-muted" />
        <h3 className="mt-4 text-[14px] font-semibold">{title}</h3>
        <p className="mt-1 text-[10px] text-muted">{body}</p>
      </div>
    </div>
  );
}
function formatBytes(value: number) {
  return value > 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(1)} GB`
    : `${Math.round(value / 1024 ** 2)} MB`;
}
