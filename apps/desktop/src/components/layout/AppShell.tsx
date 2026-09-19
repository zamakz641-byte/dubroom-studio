import {
  Activity,
  Bell,
  Boxes,
  CheckCircle2,
  ChevronRight,
  CircleGauge,
  CloudDownload,
  FolderKanban,
  Gauge,
  LayoutDashboard,
  Library,
  LoaderCircle,
  Maximize2,
  RotateCcw,
  Settings2,
  Sparkles,
  Square,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { useNotifications } from "@/notifications";
import { cn } from "@/lib/utils";
import type { PerformanceProfile } from "@/lib/performance";
import type { ActivityRecord, AppSection, ProjectRecord } from "@/types";
import {
  DesktopTitleBar,
  type RailState,
  type ShellPanel,
} from "@/components/layout/DesktopTitleBar";

const navigation: [AppSection, string, typeof Gauge][] = [
  ["dashboard", "nav.dashboard", LayoutDashboard],
  ["projects", "nav.projects", FolderKanban],
  ["studio", "nav.studio", Gauge],
  ["library", "nav.library", Library],
  ["tools", "nav.tools", Sparkles],
  ["engines", "nav.engines", Boxes],
  ["settings", "nav.settings", Settings2],
];

export function AppShell({
  section,
  onSection,
  activeProject,
  backendOnline,
  activities,
  onRefreshActivities,
  performanceProfile,
  children,
}: {
  section: AppSection;
  onSection: (section: AppSection) => void;
  activeProject: ProjectRecord | null;
  backendOnline: boolean;
  activities: ActivityRecord[];
  onRefreshActivities: () => Promise<void>;
  performanceProfile: PerformanceProfile;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const { items, unread, markAllRead, clear } = useNotifications();
  const [rail, setRail] = useState<RailState>(
    () =>
      (localStorage.getItem("dubroom.railState") as RailState) || "expanded",
  );
  const [panel, setPanel] = useState<ShellPanel>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const activeActivities = useMemo(
    () =>
      activities.filter((activity) =>
        ["queued", "running"].includes(activity.status),
      ),
    [activities],
  );

  useEffect(() => {
    localStorage.setItem("dubroom.railState", rail);
  }, [rail]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setRail((current) => (current === "expanded" ? "compact" : "expanded"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!panel) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        panelRef.current?.contains(target) ||
        target?.closest("[data-shell-panel-trigger]")
      ) return;
      setPanel(null);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer, true);
    return () =>
      document.removeEventListener("pointerdown", closeOnOutsidePointer, true);
  }, [panel]);

  const expanded = rail === "expanded";
  const visible = rail !== "focus";
  const contentWidth = !visible
    ? "100%"
    : expanded
      ? "calc(100% - 14rem)"
      : "calc(100% - 4rem)";
  return (
    <div
      data-testid="app-shell"
      className="grid h-full w-full grid-rows-[36px_minmax(0,1fr)] overflow-hidden bg-canvas text-foreground"
    >
      <DesktopTitleBar
        section={section}
        onSection={onSection}
        activeProject={activeProject}
        backendOnline={backendOnline}
        activityCount={activeActivities.length}
        unread={unread}
        panel={panel}
        setPanel={setPanel}
        markAllRead={markAllRead}
        rail={rail}
        setRail={setRail}
      />
      <div className="flex min-h-0 min-w-0 w-full max-w-full overflow-hidden">
      {visible && (
        <aside
          className={cn(
            "relative z-30 flex shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200 ease-[var(--ease-studio)]",
            expanded ? "w-56" : "w-16",
          )}
        >
          <nav
            data-testid="primary-navigation"
            className="flex flex-1 flex-col gap-1 px-2 py-3"
            aria-label={t("brand.tagline")}
          >
            {navigation.map(([id, label, Icon]) => {
              const active = section === id;
              const working = activeActivities.some((activity) =>
                id === "engines"
                  ? activity.kind === "engine"
                  : id === "tools"
                    ? ["rvc", "subclean"].includes(activity.kind)
                    : id === "studio"
                      ? activity.kind === "project"
                      : false,
              );
              return (
                <button
                  key={id}
                  title={!expanded ? t(label) : undefined}
                  aria-label={t(label)}
                  onClick={() => onSection(id)}
                  className={cn(
                    "group relative flex h-11 items-center rounded-xl text-muted transition duration-150 hover:bg-raised hover:text-foreground",
                    expanded ? "gap-3 px-3" : "justify-center",
                    active && "bg-accent-soft text-accent",
                  )}
                >
                  <Icon
                    className={cn(
                      "size-[18px] shrink-0",
                      working && "animate-pulse",
                    )}
                  />
                  {expanded && (
                    <span className="truncate text-xs font-semibold">
                      {t(label)}
                    </span>
                  )}
                  {working && (
                    <span
                      className={cn(
                        "absolute grid size-5 place-items-center rounded-full bg-accent text-[10px] font-bold text-accent-ink",
                        expanded ? "right-3" : "right-1 top-1",
                      )}
                    >
                      {activeActivities.length}
                    </span>
                  )}
                  {active && (
                    <i className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" />
                  )}
                </button>
              );
            })}
          </nav>
          <div className="border-t border-line p-2">
            <button
              className={cn(
                "flex h-10 w-full items-center rounded-lg text-muted hover:bg-raised hover:text-foreground",
                expanded ? "gap-3 px-3" : "justify-center",
              )}
              onClick={() => setRail("focus")}
              title={t("shell.focus")}
            >
              <Maximize2 className="size-4" />
              {expanded && (
                <span className="text-[11px] font-semibold">
                  {t("shell.focus")}
                </span>
              )}
            </button>
          </div>
        </aside>
      )}

      <section
        className="relative min-w-0 shrink-0 overflow-hidden"
        style={{ width: contentWidth, maxWidth: contentWidth }}
      >
        <main data-testid="app-content" className="h-full min-h-0 min-w-0 overflow-hidden">{children}</main>
        {panel && (
          <div ref={panelRef} className="absolute right-3 top-3 z-50 w-[390px] overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-[var(--shadow-panel)]">
            <header className="flex h-14 items-center justify-between border-b border-line px-4">
              <div>
                <small className="ui-kicker">
                  {panel === "status"
                    ? t("shell.localStudio")
                    : panel === "activity"
                      ? t("notifications.activity")
                      : t("notifications.title")}
                </small>
                <strong className="mt-0.5 block text-sm">
                  {panel === "status"
                    ? t("settings.diagnosticsTitle")
                    : panel === "activity"
                      ? t("activity.title")
                      : t("notifications.title")}
                </strong>
              </div>
              <div className="flex items-center gap-1">
                {panel === "notifications" && (
                  <button className="ui-icon-button size-8" onClick={clear}>
                    <Trash2 className="size-4" />
                  </button>
                )}
                <button
                  className="ui-icon-button size-8"
                  onClick={() => setPanel(null)}
                >
                  <X className="size-4" />
                </button>
              </div>
            </header>
            {panel === "status" ? (
              <StatusPanel
                online={backendOnline}
                performance={performanceProfile}
                t={t}
              />
            ) : panel === "activity" ? (
              <ActivityPanel
                activities={activities}
                onRefresh={onRefreshActivities}
                t={t}
              />
            ) : (
              <NotificationPanel items={items} t={t} />
            )}
          </div>
        )}
      </section>
      </div>
    </div>
  );
}

function StatusPanel({
  online,
  performance,
  t,
}: {
  online: boolean;
  performance: PerformanceProfile;
  t: (key: string) => string;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 p-3">
      <StatusCard
        icon={online ? CheckCircle2 : XCircle}
        label={t("settings.localData")}
        value={t(online ? "shell.backendReady" : "shell.backendOffline")}
        tone={online ? "success" : "danger"}
      />
      <StatusCard
        icon={CircleGauge}
        label={t("settings.performanceTitle")}
        value={t(`performance.${performance}`)}
        tone="accent"
      />
    </div>
  );
}
function StatusCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  tone: "success" | "danger" | "accent";
}) {
  const tones = {
    success: "text-success bg-success/10",
    danger: "text-danger bg-danger/10",
    accent: "text-accent bg-accent-soft",
  };
  return (
    <article className="ui-raised flex min-h-24 items-start gap-3 p-3">
      <span
        className={cn("grid size-9 place-items-center rounded-lg", tones[tone])}
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <small className="block text-[11px] text-muted">{label}</small>
        <strong className="mt-1 block break-words text-xs">{value}</strong>
      </div>
    </article>
  );
}
function ActivityPanel({
  activities,
  onRefresh,
  t,
}: {
  activities: ActivityRecord[];
  onRefresh: () => Promise<void>;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  const [filter, setFilter] = useState<"all" | "active" | "attention">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const visible = activities.filter((activity) =>
    filter === "active"
      ? ["queued", "running"].includes(activity.status)
      : filter === "attention"
        ? ["failed", "interrupted"].includes(activity.status)
        : true,
  );
  const act = async (id: string, action: "cancel" | "retry") => {
    setBusy(id);
    try {
      if (action === "cancel") await api.cancelActivity(id);
      else await api.retryActivity(id);
      await onRefresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };
  const simulate = async () => {
    setBusy("simulation");
    try {
      await api.simulateActivities();
      await onRefresh();
      toast.success(t("activity.simulationStarted"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };
  const activityMessage = (activity: ActivityRecord) => {
    if (activity.error === "activity.interrupted")
      return t("activity.interrupted");
    if (activity.simulation) {
      if (activity.status === "completed")
        return t("activity.simulationMessage.completed");
      if (activity.status === "queued")
        return t("activity.simulationMessage.waiting");
      if (activity.progress < 40)
        return t("activity.simulationMessage.preparing");
      if (activity.progress < 80)
        return t("activity.simulationMessage.processing");
      return t("activity.simulationMessage.validating");
    }
    if (activity.status === "completed" && activity.message)
      return t("activity.notification.completed");
    if (activity.status === "failed") return t("activity.notification.failed");
    if (activity.status === "cancelled")
      return t("activity.notification.cancelled");
    return activity.message;
  };
  return (
    <div className="max-h-[620px] overflow-y-auto">
      <div className="sticky top-0 z-10 border-b border-line bg-surface p-2.5">
        <div className="flex gap-1 rounded-lg border border-line bg-canvas p-1">
          {(["all", "active", "attention"] as const).map((value) => (
            <button
              key={value}
              className={cn(
                "h-7 flex-1 rounded-md text-[10px] font-semibold text-muted",
                filter === value && "bg-raised text-foreground",
              )}
              onClick={() => setFilter(value)}
            >
              {t(`activity.filter.${value}`)}
            </button>
          ))}
        </div>
        <button
          className="ui-button mt-2 h-8 w-full border-accent/25 bg-accent/[0.06] text-accent"
          disabled={busy === "simulation"}
          onClick={() => void simulate()}
        >
          {busy === "simulation" ? (
            <LoaderCircle className="animate-spin" />
          ) : (
            <Sparkles />
          )}
          {t("activity.simulate")}
        </button>
      </div>
      <div className="p-2">
        {visible.length === 0 ? (
          <Empty icon={Activity} label={t("activity.empty")} />
        ) : (
          visible.slice(0, 40).map((activity) => {
            const running = ["queued", "running"].includes(activity.status);
            const failed = ["failed", "interrupted"].includes(activity.status);
            return (
              <article
                key={activity.id}
                className={cn(
                  "mb-2 overflow-hidden rounded-xl border bg-raised",
                  failed ? "border-danger/30" : "border-line",
                  activity.simulation && "border-accent/30",
                )}
              >
                <div className="flex items-start gap-3 p-3">
                  <span
                    className={cn(
                      "grid size-8 place-items-center rounded-lg",
                      running
                        ? "bg-accent-soft text-accent"
                        : failed
                          ? "bg-danger/10 text-danger"
                          : "bg-success/10 text-success",
                    )}
                  >
                    {running ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : failed ? (
                      <XCircle className="size-4" />
                    ) : (
                      <CheckCircle2 className="size-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex justify-between gap-3">
                      <strong className="truncate text-xs">
                        {t(`activity.type.${activity.type}`).startsWith(
                          "activity.",
                        )
                          ? activity.title
                          : t(`activity.type.${activity.type}`)}
                      </strong>
                      <em className="text-[10px] not-italic text-muted">
                        {activity.progress}%
                      </em>
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      {!activity.simulation && (
                        <span className="rounded border border-line px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
                          {t(`activity.kind.${activity.kind}`)}
                        </span>
                      )}
                      {activity.simulation && (
                        <span className="text-[11px] font-semibold text-accent">
                          {t("activity.simulation")}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 line-clamp-2 text-[10px] leading-4 text-muted">
                      {activityMessage(activity)}
                    </p>
                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-canvas">
                      <i
                        className={cn(
                          "block h-full rounded-full transition-[width] duration-300",
                          failed ? "bg-danger" : "bg-accent",
                        )}
                        style={{
                          width: `${Math.max(running ? 3 : 0, activity.progress)}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
                {(activity.can_cancel ||
                  activity.can_retry ||
                  activity.artifact_path) && (
                  <footer className="flex items-center gap-1 border-t border-line px-2 py-1.5">
                    {activity.can_cancel && (
                      <button
                        className="ui-button h-7 px-2 text-[11px] text-danger"
                        disabled={busy === activity.id}
                        onClick={() => void act(activity.id, "cancel")}
                      >
                        {busy === activity.id ? (
                          <LoaderCircle className="animate-spin" />
                        ) : (
                          <Square />
                        )}
                        {t("common.cancel")}
                      </button>
                    )}
                    {activity.can_retry && (
                      <button
                        className="ui-button h-7 px-2 text-[11px]"
                        disabled={busy === activity.id}
                        onClick={() => void act(activity.id, "retry")}
                      >
                        <RotateCcw />
                        {t("activity.retry")}
                      </button>
                    )}
                    {activity.artifact_path &&
                      activity.status === "completed" && (
                        <button
                          className="ui-button ml-auto h-7 px-2 text-[11px]"
                          onClick={() =>
                            void window.dubStudio?.revealPath(
                              activity.artifact_path!,
                            )
                          }
                        >
                          <CloudDownload />
                          {t("activity.openResult")}
                        </button>
                      )}
                  </footer>
                )}
              </article>
            );
          })
        )}
      </div>
    </div>
  );
}
function NotificationPanel({
  items,
  t,
}: {
  items: {
    id: string;
    title: string;
    body: string;
    createdAt: string;
    tone: string;
  }[];
  t: (key: string) => string;
}) {
  return (
    <div className="max-h-[520px] overflow-y-auto p-2">
      {items.length === 0 ? (
        <Empty icon={Bell} label={t("notifications.empty")} />
      ) : (
        items.map((item) => (
          <article
            key={item.id}
            className={cn(
              "mb-1.5 flex gap-3 rounded-xl border bg-raised p-3",
              item.tone === "error"
                ? "border-danger/30"
                : item.tone === "success"
                  ? "border-success/25"
                  : item.tone === "warning"
                    ? "border-warning/25"
                    : "border-line",
            )}
          >
            <span
              className={cn(
                "grid size-8 shrink-0 place-items-center rounded-lg",
                item.tone === "error"
                  ? "bg-danger/10 text-danger"
                  : item.tone === "success"
                    ? "bg-success/10 text-success"
                    : item.tone === "warning"
                      ? "bg-warning/10 text-warning"
                      : "bg-accent-soft text-accent",
              )}
            >
              {item.tone === "error" ? (
                <XCircle className="size-4" />
              ) : item.tone === "success" ? (
                <CheckCircle2 className="size-4" />
              ) : (
                <Bell className="size-4" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <strong className="text-xs">{item.title}</strong>
              <p className="mt-1 text-[11px] leading-5 text-copy">
                {item.body}
              </p>
              <time className="mt-2 block text-[10px] text-muted">
                {new Date(item.createdAt).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
            </div>
          </article>
        ))
      )}
    </div>
  );
}
function Empty({ icon: Icon, label }: { icon: typeof Bell; label: string }) {
  return (
    <div className="grid min-h-40 place-items-center text-center text-muted">
      <div>
        <Icon className="mx-auto mb-3 size-6" />
        <p className="text-xs">{label}</p>
      </div>
    </div>
  );
}
