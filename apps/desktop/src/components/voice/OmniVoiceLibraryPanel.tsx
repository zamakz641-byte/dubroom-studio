import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleAlert,
  Cpu,
  LoaderCircle,
  Mic,
  Play,
  ShieldCheck,
  Square,
  Users,
  WandSparkles,
  Zap,
} from "lucide-react";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { VoiceLibraryBuildInput, VoiceLibraryCatalog } from "@/types";


export function OmniVoiceLibraryPanel({
  onProfilesRefresh,
  onCloneVoice,
}: {
  onProfilesRefresh: () => Promise<void>;
  onCloneVoice: () => void;
}) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<VoiceLibraryCatalog | null>(null);
  const [selected, setSelected] = useState<string[]>(["M01", "F01"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = Boolean(
    catalog && ["queued", "running"].includes(catalog.build.status),
  );

  const refresh = async (refreshProfiles = false) => {
    const next = await api.voiceLibrary();
    setCatalog(next);
    if (refreshProfiles) await onProfilesRefresh();
    return next;
  };

  useEffect(() => {
    void refresh().catch((reason) =>
      setError(reason instanceof Error ? reason.message : String(reason)),
    );
  }, []);

  useEffect(() => {
    if (!running) return;
    let alive = true;
    const timer = setInterval(() => {
      void api.voiceLibrary().then(async (next) => {
        if (!alive) return;
        const finished = !["queued", "running"].includes(next.build.status);
        setCatalog(next);
        if (finished && next.build.status === "ready") await onProfilesRefresh();
      }).catch((reason) => alive && setError(reason instanceof Error ? reason.message : String(reason)));
    }, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [running, onProfilesRefresh]);

  const groups = useMemo(() => {
    const templates = catalog?.templates || [];
    return [
      [t("voiceLibrary.male"), templates.filter((item) => item.id.startsWith("M"))],
      [t("voiceLibrary.female"), templates.filter((item) => item.id.startsWith("F"))],
      [t("voiceLibrary.special"), templates.filter((item) => !/^[MF]/.test(item.id))],
    ] as const;
  }, [catalog?.templates, t]);

  const start = async (input: VoiceLibraryBuildInput) => {
    setBusy(true);
    setError("");
    try {
      await api.buildOmniVoiceLibrary(input);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    try {
      await api.cancelOmniVoiceLibrary();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  if (!catalog) {
    return (
      <section className="ui-panel flex items-center gap-3 p-4 text-[11px] text-muted">
        <LoaderCircle className="size-4 animate-spin" />
        {t("voiceLibrary.loading")}
      </section>
    );
  }

  return (
    <section className="ui-panel overflow-hidden">
      <header className="flex items-start gap-4 border-b border-line p-4">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
          <Users className="size-5" />
        </span>
        <span className="min-w-0 flex-1">
          <small className="ui-kicker">{t("voiceLibrary.kicker")}</small>
          <strong className="mt-1 block text-[14px]">{t("voiceLibrary.title")}</strong>
          <p className="mt-1 text-[10px] leading-4 text-muted">
            {t("voiceLibrary.body")}
          </p>
          <span className="mt-2 flex flex-wrap gap-1.5">
            <i className="ui-chip">{t("profile.usage.both")}</i>
            <i className="ui-chip border-accent/30 text-accent">{t("voiceLibrary.reusableProfile")}</i>
            <i className="ui-chip border-success/30 text-success">
              {catalog.runtime.device === "cuda" ? `CUDA · ${catalog.runtime.cuda}` : "CPU"}
            </i>
            <i className="ui-chip border-success/30 text-success">
              <ShieldCheck className="size-3" /> {t("voiceLibrary.localOnly")}
            </i>
          </span>
        </span>
        <span className="grid shrink-0 justify-items-end gap-2 text-right">
          <strong className="block text-xl">{catalog.summary.generated}/{catalog.summary.configured}</strong>
          <small className="text-[9px] text-muted">{t("voiceLibrary.generated")}</small>
          <button className="ui-button ui-button-primary" onClick={onCloneVoice}>
            <Mic /> {t("voiceLibrary.cloneWithOmniVoice")}
          </button>
        </span>
      </header>

      {running && (
        <div className="border-b border-line bg-accent/5 p-4">
          <div className="flex items-center justify-between gap-3 text-[10px]">
            <span className="flex min-w-0 items-center gap-2 text-accent">
              <LoaderCircle className="size-3.5 shrink-0 animate-spin" />
              <strong className="truncate">{catalog.build.message}</strong>
            </span>
            <span className="font-mono">{catalog.build.progress}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-canvas">
            <i className="block h-full bg-accent transition-[width]" style={{ width: `${Math.max(2, catalog.build.progress)}%` }} />
          </div>
        </div>
      )}

      <div className="grid gap-4 p-4">
        <div className="grid gap-3">
          {groups.map(([label, templates]) => (
            <div key={label}>
              <small className="ui-label">{label}</small>
              <div className="mt-2 grid grid-cols-2 gap-2 xl:grid-cols-3">
                {templates.map((voice) => {
                  const active = selected.includes(voice.id);
                  return (
                    <button
                      key={voice.id}
                      type="button"
                      disabled={running}
                      title={`${voice.name} · ${voice.age} · ${voice.pitch}`}
                      className={`flex min-h-16 items-start gap-2 rounded-lg border p-3 text-left text-[9px] ${
                        active ? "border-accent bg-accent/10 text-accent" : "border-line bg-canvas text-muted"
                      }`}
                      onClick={() => setSelected((current) =>
                        current.includes(voice.id)
                          ? current.filter((id) => id !== voice.id)
                          : [...current, voice.id]
                      )}
                    >
                      {voice.status === "ready" ? <Check className="size-3 text-success" /> : voice.status === "failed" ? <CircleAlert className="size-3 text-danger" /> : null}
                      <span className="min-w-0 flex-1">
                        <strong className="block text-[10px]">{voice.id} · {voice.name}</strong>
                        <small className="mt-1 block truncate text-[9px] opacity-75">{t(`profile.gender.${voice.gender||"unspecified"}`)} · {voice.age} · {voice.roles?.[0]||voice.pitch}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {running ? (
            <button className="ui-button text-danger" disabled={busy} onClick={() => void cancel()}>
              <Square /> {t("voiceLibrary.cancel")}
            </button>
          ) : (
            <>
              <button className="ui-button ui-button-primary" disabled={busy || !selected.length || !catalog.runtime.ready} onClick={() => void start({ voices: selected })}>
                {busy ? <LoaderCircle className="animate-spin" /> : <Play />}
                {t("voiceLibrary.generateSelected")} ({selected.length})
              </button>
              <button className="ui-button" disabled={busy || !catalog.runtime.ready} onClick={() => void start({ voices: [] })}>
                <Zap /> {t("voiceLibrary.generateAll")}
              </button>
              <button className="ui-button" disabled={busy || !catalog.runtime.ready} onClick={() => void start({ voices: [], full_tests: true })}>
                <WandSparkles /> {t("voiceLibrary.fullTests")}
              </button>
            </>
          )}
          <span className="ml-auto flex items-center gap-2 text-[9px] text-muted">
            {catalog.runtime.device === "cuda" ? <Zap className="size-3 text-success" /> : <Cpu className="size-3" />}
            {catalog.build.status === "failed" ? catalog.build.error : t("voiceLibrary.noDownload")}
          </span>
        </div>
        {(error || catalog.build.error) && !running && (
          <p className="rounded-lg border border-danger/25 bg-danger/5 p-3 text-[10px] text-danger">
            {error || catalog.build.error}
          </p>
        )}
      </div>
    </section>
  );
}
