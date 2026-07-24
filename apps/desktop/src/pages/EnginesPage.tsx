import {
  Box,
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  Gauge,
  HardDrive,
  Languages,
  LoaderCircle,
  MemoryStick,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Waves,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { publicAssetUrl } from "@/lib/assets";
import type {
  EngineRecord,
  InstallPreview,
  ModelDownloadCheck,
  VoiceboxModel,
  VoiceboxStatus,
} from "@/types";

type Props = {
  engines: EngineRecord[];
  voiceboxStatus: VoiceboxStatus | null;
  voiceboxModels: VoiceboxModel[];
  onInstallVoicebox: () => Promise<void>;
  onStartVoicebox: () => Promise<void>;
  onDownloadVoicebox: (name: string) => Promise<void>;
  onPreview: (id: string) => Promise<InstallPreview>;
  onInstall: (
    id: string,
    repair: boolean,
    credentials: Record<string, string>,
  ) => Promise<void>;
  onRefresh: () => void;
};

const categoryOrder = [
  "asr",
  "translation",
  "tts",
  "rvc",
  "media",
  "utility",
  "diarization",
];

export function EnginesPage({
  engines,
  voiceboxStatus,
  voiceboxModels,
  onInstallVoicebox,
  onStartVoicebox,
  onDownloadVoicebox,
  onPreview,
  onInstall,
  onRefresh,
}: Props) {
  const { t } = useI18n();
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [preview, setPreview] = useState<InstallPreview | null>(null);
  const [sourceCheck, setSourceCheck] = useState<ModelDownloadCheck | null>(
    null,
  );

  const categories = useMemo(
    () =>
      categoryOrder.filter((item) =>
        item === "tts"
          ? voiceboxModels.length > 0
          : engines.some((engine) => engine.category === item),
      ),
    [engines, voiceboxModels.length],
  );
  const families = useMemo(() => {
    const filtered = engines.filter(
      (engine) =>
        category !== "tts" &&
        (category === "all" || engine.category === category) &&
        `${engine.display_name} ${engine.description} ${engine.model?.family || ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
    const map = new Map<string, EngineRecord[]>();
    for (const engine of filtered) {
      const key = engine.model?.family_id || engine.model?.family || engine.id;
      map.set(key, [...(map.get(key) || []), engine]);
    }
    return [...map.entries()].map(([id, variants]) => ({
      id,
      variants: variants.sort((a, b) =>
        (a.model?.format || "").localeCompare(b.model?.format || ""),
      ),
    }));
  }, [engines, category, query]);
  const visibleVoiceboxModels = useMemo(
    () =>
      voiceboxModels.filter((model) =>
        `${model.display_name} ${model.engine || ""} ${model.hf_repo_id || ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [query, voiceboxModels],
  );
  const showVoicebox =
    (category === "all" || category === "tts") &&
    visibleVoiceboxModels.length > 0;

  const install = async (engine: EngineRecord) => {
    setInstalling(engine.id);
    setSourceCheck(null);
    try {
      const [nextPreview, check] = await Promise.all([
        onPreview(engine.id),
        api.downloadCheck(engine.id).catch(() => null),
      ]);
      setPreview(nextPreview);
      setSourceCheck(check);
      await onInstall(engine.id, engine.installation.status === "failed", {});
    } finally {
      setInstalling(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHeader
        kicker={t("engines.kicker")}
        title={t("engines.title")}
        description={t("engines.description")}
        actions={
          <button className="ui-button" onClick={onRefresh}>
            <RefreshCw />
            {t("common.refresh")}
          </button>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col p-6 pt-4 xl:p-8 xl:pt-5">
        <div className="flex items-center gap-2">
          <div data-testid="engine-tabs" className="flex flex-1 gap-1 overflow-x-auto rounded-lg border border-line bg-surface p-1">
            <button
              className={`ui-button border-0 ${category === "all" ? "bg-raised text-foreground" : "bg-transparent text-muted"}`}
              onClick={() => setCategory("all")}
            >
              {t("common.all")}
            </button>
            {categories.map((item) => (
              <button
                key={item}
                className={`ui-button border-0 ${category === item ? "bg-raised text-foreground" : "bg-transparent text-muted"}`}
                onClick={() => setCategory(item)}
              >
                {t(`engines.${item}`)}
              </button>
            ))}
          </div>
          <label className="flex h-9 w-72 items-center gap-2 rounded-lg border border-line bg-surface px-3">
            <Search className="size-4 text-muted" />
            <input
              className="min-w-0 flex-1 bg-transparent text-[12px] outline-none"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("common.search")}
            />
          </label>
        </div>

        <div className="mt-4 min-h-0 flex-1 overflow-auto pr-1">
          {showVoicebox && (
            <VoiceModelDeck
              models={visibleVoiceboxModels}
              status={voiceboxStatus}
              onInstallRuntime={onInstallVoicebox}
              onStartRuntime={onStartVoicebox}
              onDownload={onDownloadVoicebox}
            />
          )}

          {category !== "tts" && (
            <div className="grid auto-rows-min grid-cols-1 gap-3 xl:grid-cols-2">
              {families.map((family) => {
                const primary =
                  family.variants.find((item) => item.model?.recommended) ||
                  family.variants[0];
                const ready = family.variants.filter(
                  (item) => item.verification.usable,
                ).length;
                const open = expanded === family.id;
                return (
                  <article
                    key={family.id}
                    className="engine-family ui-panel overflow-hidden"
                  >
                    <button
                      className="flex w-full items-center gap-4 p-4 text-left"
                      onClick={() => setExpanded(open ? null : family.id)}
                    >
                      <Brand
                        asset={primary.brand?.asset}
                        label={primary.brand?.name || primary.display_name}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <strong className="truncate text-[14px] font-semibold">
                            {primary.model?.family || primary.display_name}
                          </strong>
                          {primary.model?.recommended && (
                            <i className="ui-chip border-accent/30 bg-accent/10 text-accent">
                              <Sparkles className="size-3" />
                              {t("common.recommended")}
                            </i>
                          )}
                        </span>
                        <p className="mt-1 line-clamp-1 text-[11px] text-copy">
                          {primary.model && primary.category === "translation"
                            ? t("engines.desc.translationModel")
                            : primary.model && primary.category === "asr"
                              ? t("engines.desc.asrModel")
                              : primary.description}
                        </p>
                        <span className="mt-2 flex items-center gap-3 text-[10px] text-muted">
                          <i className="not-italic">
                            {t("engines.variantCount", {
                              count: family.variants.length,
                            })}
                          </i>
                          <i className="not-italic">
                            {t("engines.readyCount", {
                              ready,
                              total: family.variants.length,
                            })}
                          </i>
                          <i className="not-italic">{primary.license}</i>
                        </span>
                      </span>
                      <ChevronDown
                        className={`size-4 text-muted transition-transform ${open ? "rotate-180" : ""}`}
                      />
                    </button>
                    {open && (
                      <div className="border-t border-line bg-canvas/30 p-3">
                        <div className="grid gap-2">
                          {family.variants.map((engine) => (
                            <div
                              key={engine.id}
                              className="grid grid-cols-[minmax(0,1fr)_78px_112px] items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2.5"
                            >
                              <div className="min-w-0">
                                <strong className="block truncate text-[12px]">
                                  {engine.model?.variant || engine.display_name}
                                </strong>
                                <span className="mt-1 flex gap-1.5">
                                  <FormatBadge
                                    value={
                                      engine.model?.format ||
                                      engine.model?.runtime ||
                                      "Runtime"
                                    }
                                  />
                                  {engine.model?.quantization && (
                                    <FormatBadge
                                      value={engine.model.quantization}
                                    />
                                  )}
                                </span>
                              </div>
                              <Meta
                                icon={HardDrive}
                                value={`${engine.requirements.disk_space_gb} GB`}
                              />
                              <Meta
                                icon={MemoryStick}
                                value={`${engine.requirements.recommended_vram_gb || 0} GB`}
                              />
                              <span
                                className={`ui-chip col-span-2 justify-self-start ${engine.verification.usable ? "border-success/30 text-success" : engine.installation.status === "installing" ? "border-warning/30 text-warning" : ""}`}
                              >
                                {engine.verification.usable ? (
                                  <Check />
                                ) : engine.installation.status ===
                                  "installing" ? (
                                  <LoaderCircle className="animate-spin" />
                                ) : (
                                  <Box />
                                )}
                                {engine.verification.usable
                                  ? t("common.ready")
                                  : engine.installation.status === "installing"
                                    ? t("common.installing")
                                    : engine.installation.status === "failed"
                                      ? t("projects.status.failed")
                                      : t("common.notInstalled")}
                              </span>
                              <button
                                className={`ui-button ${engine.verification.usable ? "" : "ui-button-primary"}`}
                                disabled={
                                  !engine.installable ||
                                  installing === engine.id ||
                                  engine.installation.status === "installing"
                                }
                                onClick={() => void install(engine)}
                              >
                                {installing === engine.id ? (
                                  <LoaderCircle className="animate-spin" />
                                ) : engine.verification.usable ? (
                                  <ShieldCheck />
                                ) : (
                                  <Download />
                                )}
                                {engine.verification.usable
                                  ? t("engines.repair")
                                  : t("engines.install")}
                              </button>
                            </div>
                          ))}
                        </div>
                        <div className="mt-3 flex items-center justify-between text-[10px] text-muted">
                          <span>
                            {primary.brand?.owner} ·{" "}
                            {primary.brand?.license || primary.license}
                          </span>
                          {primary.brand?.official_url && (
                            <button
                              className="flex items-center gap-1 hover:text-foreground"
                              onClick={() =>
                                void window.open(
                                  primary.brand?.official_url,
                                  "_blank",
                                )
                              }
                            >
                              <ExternalLink className="size-3" />
                              {t("engines.officialSource")}
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </div>

        {preview && (
          <div className="mt-3 flex items-center gap-3 rounded-lg border border-line bg-raised px-4 py-3 text-[11px]">
            <ShieldCheck className="size-4 text-success" />
            <strong>{preview.display_name}</strong>
            <span className="text-copy">{preview.steps.join(" · ")}</span>
            {sourceCheck?.reachable && (
              <span className="ui-chip border-success/30 text-success">
                <Check />
                {t("engines.sourceVerified")}
              </span>
            )}
            <span className="ml-auto font-mono text-muted">
              {preview.disk_space_gb} GB
            </span>
            <button className="ui-icon-button" onClick={() => setPreview(null)}>
              ×
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function VoiceModelDeck({
  models,
  status,
  onInstallRuntime,
  onStartRuntime,
  onDownload,
}: {
  models: VoiceboxModel[];
  status: VoiceboxStatus | null;
  onInstallRuntime: () => Promise<void>;
  onStartRuntime: () => Promise<void>;
  onDownload: (name: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const runtimeReady = Boolean(status?.runtime_ready);
  const online = Boolean(status?.online);
  const readyModels = models.filter((model) => model.downloaded).length;

  const run = async (id: string, action: () => Promise<void>) => {
    setBusy(id);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="mb-4 overflow-hidden rounded-xl border border-line bg-surface shadow-[0_18px_60px_rgba(0,0,0,.12)]">
      <div className="grid gap-4 border-b border-line bg-[radial-gradient(circle_at_12%_0%,color-mix(in_srgb,var(--accent)_13%,transparent),transparent_45%)] px-5 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div className="flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-xl border border-accent/30 bg-accent/10 text-accent">
            <Waves className="size-5" />
          </span>
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[.18em] text-accent">
              {t("voicebox.deck")}
            </span>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] font-semibold">
                {t("voicebox.title")}
              </h2>
              <span
                className={`ui-chip ${online ? "border-success/30 text-success" : "border-line text-muted"}`}
              >
                <i
                  className={`size-1.5 rounded-full ${online ? "bg-success" : "bg-muted"}`}
                />
                {online ? t("voicebox.connected") : t("voicebox.stopped")}
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-[11px] text-copy">
              {t("voicebox.steps")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-line bg-canvas/50 px-3 py-2">
          <Gauge className="size-4 text-accent" />
          <span className="text-[10px] text-muted">
            {t("voicebox.modelsReady", {
              ready: readyModels,
              total: models.length,
            })}
          </span>
          {!runtimeReady ? (
            <button
              className="ui-button ui-button-primary"
              disabled={busy !== null}
              onClick={() => void run("runtime", onInstallRuntime)}
            >
              {busy === "runtime" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Download />
              )}
              {t("voicebox.installRuntime")}
            </button>
          ) : !online ? (
            <button
              className="ui-button ui-button-primary"
              disabled={busy !== null}
              onClick={() => void run("runtime", onStartRuntime)}
            >
              {busy === "runtime" ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Play />
              )}
              {t("voicebox.start")}
            </button>
          ) : null}
        </div>
      </div>
      <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-5">
        {models.map((model) => (
          <article
            key={model.model_name}
            className="group flex min-h-48 flex-col bg-surface p-4 transition-colors hover:bg-raised"
          >
            <div className="flex items-start justify-between gap-3">
              <Brand
                asset={model.brand?.asset}
                label={model.brand?.name || model.display_name}
              />
              <span className="rounded border border-line px-1.5 py-0.5 text-[11px] uppercase tracking-wider text-muted">
                {model.tier || "local"}
              </span>
            </div>
            <strong className="mt-3 line-clamp-2 text-[12px] leading-5">
              {model.display_name}
            </strong>
            <span className="mt-1 truncate text-[11px] text-muted">
              {model.brand?.owner || model.hf_repo_id}
            </span>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-copy">
              <span className="flex items-center gap-1">
                <HardDrive className="size-3 text-muted" />
                {formatSize(model.size_mb)}
              </span>
              <span className="flex items-center gap-1">
                <MemoryStick className="size-3 text-muted" />
                {model.recommended_vram_gb || 0} GB
              </span>
              <span className="col-span-2 flex items-center gap-1">
                <Languages className="size-3 text-muted" />
                {(model.languages?.length || 0) === 1
                  ? t("voicebox.languageCountOne")
                  : t("voicebox.languageCount", {
                      count: model.languages?.length || 0,
                    })}
              </span>
            </div>
            <div className="mt-auto pt-4">
              {model.downloaded ? (
                <span className="ui-chip w-full justify-center border-success/30 text-success">
                  <Check />
                  {t("common.ready")}
                </span>
              ) : (
                <button
                  className="ui-button w-full justify-center"
                  disabled={!online || busy !== null || model.downloading}
                  onClick={() =>
                    void run(model.model_name, () =>
                      onDownload(model.model_name),
                    )
                  }
                >
                  {busy === model.model_name || model.downloading ? (
                    <LoaderCircle className="animate-spin" />
                  ) : (
                    <Download />
                  )}
                  {!runtimeReady
                    ? t("voicebox.runtimeFirst")
                    : !online
                      ? t("voicebox.startFirst")
                      : t("voicebox.installModel")}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Brand({ asset, label }: { asset?: string; label: string }) {
  const [fallback, setFallback] = useState(false);
  const source = publicAssetUrl(asset);

  useEffect(() => setFallback(false), [source]);

  return (
    <span className="grid size-12 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-raised shadow-sm">
      {source && !fallback ? (
        <img
          className="size-10 rounded-lg object-contain"
          src={source}
          alt={label}
          title={label}
          onError={() => setFallback(true)}
        />
      ) : (
        <span className="text-[12px] font-bold text-accent">
          {label.slice(0, 2).toUpperCase()}
        </span>
      )}
    </span>
  );
}

function FormatBadge({ value }: { value: string }) {
  return (
    <i className="max-w-32 truncate rounded border border-line bg-raised px-1.5 py-0.5 text-[11px] not-italic text-copy">
      {value}
    </i>
  );
}

function Meta({
  icon: Icon,
  value,
}: {
  icon: typeof HardDrive;
  value: string;
}) {
  return (
    <span className="flex items-center gap-1 text-[10px] text-copy">
      <Icon className="size-3 text-muted" />
      {value}
    </span>
  );
}

function formatSize(sizeMb?: number | null) {
  if (!sizeMb) return "—";
  return sizeMb >= 1000
    ? `${(sizeMb / 1000).toFixed(sizeMb >= 10000 ? 0 : 1)} GB`
    : `${sizeMb} MB`;
}
