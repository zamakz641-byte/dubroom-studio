import {
  Check,
  CircleAlert,
  Cpu,
  Database,
  LoaderCircle,
  RefreshCw,
  Users,
} from "lucide-react";
import { useI18n } from "@/i18n";
import type { DiarizationState, JobRecord } from "@/types";


export function SpeakerDiarizationPanel({
  state,
  job,
  onDiarize,
}: {
  state: DiarizationState | null;
  job?: JobRecord;
  onDiarize: (force?: boolean) => void;
}) {
  const { t } = useI18n();
  const running = Boolean(job && ["queued", "running"].includes(job.status));
  const status = running ? "running" : state?.status || "not_processed";
  const progress = running ? job?.progress || 0 : state?.progress || 0;
  const runtime = state?.runtime;
  const usable = runtime?.usable === true;
  const StatusIcon = status === "ready" ? Check : status === "running" ? LoaderCircle : status === "failed" ? CircleAlert : Users;

  return (
    <div className="grid gap-3" data-testid="speaker-diarization-panel">
      <section className="ui-panel p-4">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
            <Users className="size-5" />
          </span>
          <span className="min-w-0 flex-1">
            <small className="ui-kicker">{t("studio.diarization.kicker")}</small>
            <strong className="mt-1 block text-[13px]">{t("studio.diarization.title")}</strong>
            <p className="mt-1 text-[10px] leading-4 text-muted">{t("studio.diarization.body")}</p>
          </span>
        </div>

        <div className="mt-4 flex items-center justify-between rounded-lg border border-line bg-canvas p-3">
          <span className={`flex items-center gap-2 text-[10px] font-semibold ${status === "ready" ? "text-success" : status === "failed" ? "text-danger" : status === "running" ? "text-accent" : "text-muted"}`}>
            <StatusIcon className={`size-3.5 ${running ? "animate-spin" : ""}`} />
            {status === "ready" ? t("studio.diarization.ready") : status === "running" ? t("studio.diarization.processing") : status === "failed" ? t("studio.diarization.failed") : t("studio.diarization.notProcessed")}
          </span>
          <span className="font-mono text-[10px] text-muted">{progress}%</span>
        </div>
        {running && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas">
            <i className="block h-full bg-accent transition-[width]" style={{ width: `${Math.max(2, progress)}%` }} />
          </div>
        )}
        {(job?.message || state?.message) && <p className="mt-2 text-[10px] leading-4 text-copy">{job?.message || state?.message}</p>}
        {state?.error && !running && <p className="mt-2 rounded-lg border border-danger/30 bg-danger/5 p-2 text-[10px] leading-4 text-danger">{state.error}</p>}

        <button
          className="ui-button ui-button-primary mt-4 w-full"
          disabled={running || !usable || !state?.source_path}
          onClick={() => onDiarize(state?.status === "ready")}
        >
          {running ? <LoaderCircle className="animate-spin" /> : state?.status === "ready" ? <RefreshCw /> : <Users />}
          {state?.status === "ready" ? t("studio.diarization.reprocess") : t("studio.diarization.detect")}
        </button>
        {!state?.source_path && <p className="mt-2 text-[10px] leading-4 text-warning">{t("studio.diarization.needsVocals")}</p>}
        {runtime?.runtime_ready && !runtime.model_ready && <p className="mt-2 text-[10px] leading-4 text-warning">{t("studio.diarization.needsModel")}</p>}
      </section>

      {state?.status === "ready" && (
        <section className="ui-panel p-3">
          <div className="flex items-center justify-between">
            <span className="ui-kicker">{t("studio.diarization.result")}</span>
            <strong className="text-[11px] text-success">{state.speaker_count} {t("studio.diarization.speakers")}</strong>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
            <span className="rounded-lg bg-canvas p-2"><b>{state.turn_count}</b><br /><small className="text-muted">{t("studio.diarization.turns")}</small></span>
            <span className="rounded-lg bg-canvas p-2"><b>{state.elapsed_seconds?.toFixed(1) || "—"}s</b><br /><small className="text-muted">{t("studio.diarization.elapsed")}</small></span>
          </div>
          {state.cache_hit && <p className="mt-3 flex items-center gap-2 text-[10px] text-success"><Database className="size-3.5" />{t("studio.diarization.cacheReused")}</p>}
        </section>
      )}

      <section className="rounded-lg border border-line bg-canvas/60 p-3 text-[10px]">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-muted"><Cpu className="size-3.5" />{t("studio.diarization.runtime")}</span>
          <strong className={usable ? "text-success" : "text-warning"}>{runtime?.execution_provider || "Pyannote"} · {(runtime?.device || "cpu").toUpperCase()}</strong>
        </div>
        <p className="mt-3 border-t border-line pt-2 leading-4 text-muted">{t("studio.diarization.noSilentDownload")}</p>
      </section>
    </div>
  );
}
