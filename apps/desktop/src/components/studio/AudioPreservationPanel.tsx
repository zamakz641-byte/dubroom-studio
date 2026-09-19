import { useEffect, useMemo, useState } from "react";
import {
  AudioLines,
  Check,
  CircleAlert,
  Database,
  LoaderCircle,
  Music2,
  RefreshCw,
  ShieldCheck,
  Volume2,
} from "lucide-react";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { AudioPreservationState, JobRecord } from "@/types";


type TrackName = "original" | "vocals" | "bed";

export function AudioPreservationPanel({
  projectId,
  state,
  job,
  onSeparate,
}: {
  projectId: string;
  state: AudioPreservationState | null;
  job?: JobRecord;
  onSeparate: (options?: { force?: boolean; profile?: "cinema" | "fast" }) => void;
}) {
  const { t } = useI18n();
  const [urls, setUrls] = useState<Partial<Record<TrackName, string>>>({});
  const [profile, setProfile] = useState<"cinema" | "fast">(
    state?.backend === "demucs-separation" ? "fast" : "cinema",
  );
  const running = Boolean(job && ["queued", "running"].includes(job.status));
  const status = running ? "running" : state?.status || "not_processed";
  const progress = running ? job?.progress || 0 : state?.progress || 0;
  const usable = state?.runtime.usable !== false;
  const usesCuda = state?.runtime.device === "cuda";
  const sharedProviders = useMemo(
    () => Object.entries(state?.runtime.shared_dependencies.providers || {}),
    [state?.runtime.shared_dependencies.providers],
  );

  useEffect(() => {
    let active = true;
    if (state?.status !== "ready") {
      setUrls({});
      return () => {
        active = false;
      };
    }
    void Promise.all(
      (["original", "vocals", "bed"] as TrackName[]).map(async (track) => [
        track,
        await api.audioPreservationUrl(projectId, track),
      ] as const),
    ).then((entries) => active && setUrls(Object.fromEntries(entries)));
    return () => {
      active = false;
    };
  }, [projectId, state?.status, state?.fingerprint]);

  const statusMetaByKey: Record<
    string,
    [string, string, typeof AudioLines]
  > = {
    not_processed: [t("studio.audioPreservation.notProcessed"), "text-muted", AudioLines],
    running: [t("studio.audioPreservation.processing"), "text-accent", LoaderCircle],
    ready: [t("studio.audioPreservation.ready"), "text-success", Check],
    failed: [t("studio.audioPreservation.failed"), "text-danger", CircleAlert],
    cancelled: [t("studio.audioPreservation.cancelled"), "text-warning", CircleAlert],
  };
  const statusMeta = statusMetaByKey[status] || [status, "text-muted", AudioLines];
  const StatusIcon = statusMeta[2];

  return (
    <div className="grid gap-3" data-testid="audio-preservation-panel">
      <section className="ui-panel p-4">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
            <ShieldCheck className="size-5" />
          </span>
          <span className="min-w-0 flex-1">
            <small className="ui-kicker">{t("studio.audioPreservation.kicker")}</small>
            <strong className="mt-1 block text-[13px]">
              {t("studio.audioPreservation.title")}
            </strong>
            <p className="mt-1 text-[10px] leading-4 text-muted">
              {t("studio.audioPreservation.body")}
            </p>
          </span>
        </div>

        <div className="mt-4 flex items-center justify-between rounded-lg border border-line bg-canvas p-3">
          <span className={`flex items-center gap-2 text-[10px] font-semibold ${statusMeta[1]}`}>
            <StatusIcon className={`size-3.5 ${running ? "animate-spin" : ""}`} />
            {statusMeta[0]}
          </span>
          <span className="font-mono text-[10px] text-muted">{progress}%</span>
        </div>
        {running && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas">
            <i className="block h-full bg-accent transition-[width]" style={{ width: `${Math.max(2, progress)}%` }} />
          </div>
        )}
        {(job?.message || state?.message) && (
          <p className="mt-2 text-[10px] leading-4 text-copy">{job?.message || state?.message}</p>
        )}
        {state?.error && !running && (
          <p className="mt-2 rounded-lg border border-danger/30 bg-danger/5 p-2 text-[10px] leading-4 text-danger">
            {state.error}
          </p>
        )}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button
            type="button"
            className={`rounded-lg border p-3 text-left transition ${profile === "cinema" ? "border-accent bg-accent/10" : "border-line bg-canvas"}`}
            onClick={() => setProfile("cinema")}
          >
            <strong className="block text-[10px]">{t("studio.audioPreservation.cinema")}</strong>
            <small className="mt-1 block text-[9px] leading-3 text-muted">{t("studio.audioPreservation.cinemaBody")}</small>
          </button>
          <button
            type="button"
            className={`rounded-lg border p-3 text-left transition ${profile === "fast" ? "border-accent bg-accent/10" : "border-line bg-canvas"}`}
            onClick={() => setProfile("fast")}
          >
            <strong className="block text-[10px]">{t("studio.audioPreservation.fast")}</strong>
            <small className="mt-1 block text-[9px] leading-3 text-muted">{t("studio.audioPreservation.fastBody")}</small>
          </button>
        </div>
        <button
          className="ui-button ui-button-primary mt-4 w-full"
          disabled={running || !usable}
          onClick={() => onSeparate({ force: state?.status === "ready", profile })}
        >
          {running ? <LoaderCircle className="animate-spin" /> : state?.status === "ready" ? <RefreshCw /> : <AudioLines />}
          {state?.status === "ready"
            ? t("studio.audioPreservation.reprocess")
            : t("studio.audioPreservation.separate")}
        </button>
      </section>

      {state?.status === "ready" && (
        <section className="grid gap-2">
          <TrackPreview icon={Volume2} label={t("studio.audioPreservation.original")} url={urls.original} />
          <TrackPreview icon={AudioLines} label={t("studio.audioPreservation.voices")} url={urls.vocals} />
          <TrackPreview icon={Music2} label={t("studio.audioPreservation.bed")} url={urls.bed} />
          {state.cache_hit && (
            <p className="flex items-center gap-2 text-[10px] text-success">
              <Database className="size-3.5" />
              {t("studio.audioPreservation.cacheReused")}
            </p>
          )}
        </section>
      )}

      <section className="rounded-lg border border-line bg-canvas/60 p-3 text-[10px]">
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted">{t("studio.audioPreservation.runtime")}</span>
          <strong className={usable ? (usesCuda ? "text-success" : "text-warning") : "text-danger"}>
            {usable
              ? usesCuda
                ? `CUDA · ${state?.runtime.device_name || "GPU"}`
                : t("studio.audioPreservation.cpuRuntime")
              : t("studio.audioPreservation.repairRuntime")}
          </strong>
        </div>
        {sharedProviders.map(([module, provider]) => (
          <div key={module} className="mt-2 flex items-center justify-between gap-2 font-mono text-[9px]">
            <span>{module}</span>
            <span className="truncate text-muted">{provider}</span>
          </div>
        ))}
        <p className="mt-3 border-t border-line pt-2 leading-4 text-muted">
          {t("studio.audioPreservation.noSilentDownload")}
        </p>
      </section>
    </div>
  );
}

function TrackPreview({
  icon: Icon,
  label,
  url,
}: {
  icon: typeof AudioLines;
  label: string;
  url?: string;
}) {
  return (
    <article className="rounded-lg border border-line bg-raised p-3">
      <strong className="mb-2 flex items-center gap-2 text-[10px]">
        <Icon className="size-3.5 text-accent" />
        {label}
      </strong>
      <audio className="h-8 w-full" controls preload="metadata" src={url} />
    </article>
  );
}
