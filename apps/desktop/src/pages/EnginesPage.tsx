import {
  Box,
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { publicAssetUrl } from "@/lib/assets";
import type {
  EngineInstallation,
  EngineRecord,
  InstallPreview,
  ModelDownloadCheck,
} from "@/types";

type Props = {
  engines: EngineRecord[];
  onPreview: (id: string) => Promise<InstallPreview>;
  onInstall: (
    id: string,
    repair: boolean,
    credentials: Record<string, string>,
  ) => Promise<void>;
  onRefresh: () => void;
};

const activeInstallStatuses = new Set(["queued", "installing", "repairing"]);

const categoryOrder = [
  "asr",
  "translation",
  "voice",
  "rvc",
  "media",
  "utility",
  "diarization",
];

export function EnginesPage({
  engines,
  onPreview,
  onInstall,
  onRefresh,
}: Props) {
  const { t } = useI18n();
  const [category, setCategory] = useState("installed");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [preview, setPreview] = useState<InstallPreview | null>(null);
  const [sourceCheck, setSourceCheck] = useState<ModelDownloadCheck | null>(
    null,
  );

  const categories = useMemo(
    () => categoryOrder.filter((item) =>
      engines.some((engine) => engine.category === item)),
    [engines],
  );
  const families = useMemo(() => {
    const filtered = engines.filter(
      (engine) =>
        (category === "all" ||
          (category === "installed" &&
            (engine.verification.installed ||
              isActiveInstall(engine.installation.status))) ||
          engine.category === category) &&
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
      await onInstall(
        engine.id,
        engine.installation.status === "failed" ||
          engine.installation.status === "needs_repair" ||
          engine.verification.installed,
        {},
      );
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
              className={`ui-button border-0 ${category === "installed" ? "bg-raised text-foreground" : "bg-transparent text-muted"}`}
              onClick={() => setCategory("installed")}
            >
              <Check />
              {t("engines.installed")}
              <span className="rounded bg-canvas px-1.5 font-mono text-[10px]">
                {engines.filter((engine) => engine.verification.installed).length}
              </span>
            </button>
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
            <div className="grid auto-rows-min grid-cols-1 gap-3 xl:grid-cols-2">
              {families.map((family) => {
                const primary =
                  family.variants.find((item) => item.model?.recommended) ||
                  family.variants[0];
                const ready = family.variants.filter(
                  (item) => item.verification.usable,
                ).length;
                const installedVariants = family.variants.filter(
                  (item) => item.verification.installed,
                );
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
                        {installedVariants.length > 0 && (
                          <span className="mt-2 flex flex-wrap gap-1">
                            {installedVariants.map((variant) => (
                              <i
                                key={variant.id}
                                className={`ui-chip max-w-full truncate not-italic ${
                                  variant.verification.usable
                                    ? "border-success/30 text-success"
                                    : "border-warning/30 text-warning"
                                }`}
                                title={variant.display_name}
                              >
                                {variant.verification.usable ? (
                                  <Check className="size-3" />
                                ) : (
                                  <RefreshCw className="size-3" />
                                )}
                                {variant.model?.variant || variant.display_name}
                              </i>
                            ))}
                          </span>
                        )}
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
                                  )}                                </span>
                                {isActiveInstall(engine.installation.status) && (
                                  <InstallProgress installation={engine.installation} />
                                )}
                                {engine.installation.status === "failed" && (
                                  <p className="mt-2 line-clamp-2 text-[10px] text-danger">
                                    {engine.installation.message}
                                  </p>
                                )}
                              </div>
                              <Meta
                                icon={HardDrive}                                value={`${engine.requirements.disk_space_gb} GB`}
                              />
                              <Meta
                                icon={MemoryStick}
                                value={`${engine.requirements.recommended_vram_gb || 0} GB`}
                              />
                              <span
                                className={`ui-chip col-span-2 justify-self-start ${engine.verification.usable ? "border-success/30 text-success" : isActiveInstall(engine.installation.status) ? "border-warning/30 text-warning" : ""}`}
                              >
                                {engine.verification.usable ? (
                                  <Check />
                                ) : isActiveInstall(engine.installation.status) ? (
                                  <LoaderCircle className="animate-spin" />
                                ) : (
                                  <Box />
                                )}
                                {engine.verification.usable
                                  ? t("common.ready")
                                  : isActiveInstall(engine.installation.status)
                                    ? installLabel(engine.installation.status, t("common.installing"))
                                    : engine.verification.installed
                                      ? t("engines.needsRepair")
                                    : engine.installation.status === "failed"
                                      ? t("projects.status.failed")
                                      : t("common.notInstalled")}
                              </span>
                              <button
                                className={`ui-button ${engine.verification.usable ? "" : "ui-button-primary"}`}
                                disabled={
                                  !engine.installable ||
                                  installing === engine.id ||
                                  isActiveInstall(engine.installation.status)
                                }
                                onClick={() => void install(engine)}
                              >
                                {installing === engine.id ? (
                                  <LoaderCircle className="animate-spin" />
                                ) : engine.verification.usable ? (
                                  <ShieldCheck />
                                ) : engine.verification.installed ? (
                                  <RefreshCw />
                                ) : (
                                  <Download />
                                )}
                                {engine.verification.usable
                                  ? t("engines.repair")
                                  : engine.verification.installed
                                    ? t("engines.repair")
                                  : t("engines.install")}
                              </button>
                            </div>
                          ))}
                        </div>
                        <div className="mt-3 flex items-center justify-between text-[10px] text-muted">
                          <span>
                            {primary.brand?.owner} -{" "}
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
        </div>

        {preview && (
          <div className="mt-3 flex items-center gap-3 rounded-lg border border-line bg-raised px-4 py-3 text-[11px]">
            <ShieldCheck className="size-4 text-success" />
            <strong>{preview.display_name}</strong>
            <span className="text-copy">{preview.steps.join(" - ")}</span>
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
              x
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


function isActiveInstall(status: string) {
  return activeInstallStatuses.has(status);
}

function installLabel(status: string, fallback: string) {
  if (status === "queued") return "En file";
  if (status === "repairing") return "Reparation";
  return fallback;
}

function formatBytes(value?: number | null) {
  if (!value || value <= 0) return "?";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${Math.round(size)} B` : `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatEta(seconds?: number | null) {
  if (!seconds || seconds < 0) return "?";
  const rounded = Math.round(seconds);
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
  return minutes ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${rest}s`;
}

function InstallProgress({ installation }: { installation: EngineInstallation }) {
  const progress = Math.max(0, Math.min(100, installation.progress || 0));
  const details = installation.total_bytes
    ? `${formatBytes(installation.downloaded_bytes)} / ${formatBytes(installation.total_bytes)} - ${formatBytes(installation.speed_bps)}/s - ETA ${formatEta(installation.eta_seconds)}`
    : installation.message;
  return (
    <div className="mt-2 min-w-0">
      <div className="h-1.5 overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${progress}%` }} />
      </div>
      <p className="mt-1 truncate text-[10px] text-copy" title={installation.message}>
        {Math.round(progress)}% - {details}
      </p>
    </div>
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
  if (!sizeMb) return "-";
  return sizeMb >= 1000
    ? `${(sizeMb / 1000).toFixed(sizeMb >= 10000 ? 0 : 1)} GB`
    : `${sizeMb} MB`;
}





