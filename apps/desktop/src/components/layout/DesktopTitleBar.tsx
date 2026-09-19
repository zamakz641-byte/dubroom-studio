import {
  Activity,
  ArrowLeft,
  ArrowRight,
  AudioWaveform,
  Bell,
  ChevronDown,
  CircleGauge,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import type { AppSection, ProjectRecord } from "@/types";

export type RailState = "expanded" | "compact" | "focus";
export type ShellPanel = "activity" | "notifications" | "status" | null;
type MenuId = "file" | "edit" | "view" | "help";
type MenuItem = {
  label: string;
  action: () => void;
  shortcut?: string;
  disabled?: boolean;
};
type TitlebarMenu = {
  id: MenuId;
  label: string;
  items: MenuItem[];
};

type Props = {
  section: AppSection;
  onSection: (section: AppSection) => void;
  activeProject: ProjectRecord | null;
  backendOnline: boolean;
  activityCount: number;
  unread: number;
  panel: ShellPanel;
  setPanel: Dispatch<SetStateAction<ShellPanel>>;
  markAllRead: () => void;
  rail: RailState;
  setRail: Dispatch<SetStateAction<RailState>>;
};

export function DesktopTitleBar({
  section,
  onSection,
  activeProject,
  backendOnline,
  activityCount,
  unread,
  panel,
  setPanel,
  markAllRead,
  rail,
  setRail,
}: Props) {
  const { t } = useI18n();
  const [openMenu, setOpenMenu] = useState<MenuId | null>(null);
  const [sectionHistory, setSectionHistory] = useState<{
    items: AppSection[];
    index: number;
  }>({ items: [section], index: 0 });
  const ignoreNextSection = useRef(false);
  const titlebar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ignoreNextSection.current) {
      ignoreNextSection.current = false;
      return;
    }
    setSectionHistory((current) => {
      if (current.items[current.index] === section) return current;
      const items = [...current.items.slice(0, current.index + 1), section];
      return { items, index: items.length - 1 };
    });
  }, [section]);

  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!titlebar.current?.contains(event.target as Node)) setOpenMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenu(null);
    };
    window.addEventListener("pointerdown", dismiss);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const syncOverlay = () => {
      const styles = getComputedStyle(root);
      void window.dubStudio?.setTitleBarTheme({
        color: styles.getPropertyValue("--ui-canvas").trim(),
        symbolColor: styles.getPropertyValue("--ui-foreground").trim(),
      });
    };
    syncOverlay();
    const observer = new MutationObserver(syncOverlay);
    observer.observe(root, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  const moveHistory = (direction: -1 | 1) => {
    const nextIndex = sectionHistory.index + direction;
    const target = sectionHistory.items[nextIndex];
    if (!target) return;
    ignoreNextSection.current = true;
    setSectionHistory((current) => ({ ...current, index: nextIndex }));
    setOpenMenu(null);
    onSection(target);
  };

  const navigate = (target: AppSection) => {
    setOpenMenu(null);
    if (target !== section) {
      ignoreNextSection.current = true;
      setSectionHistory((current) => {
        const items = [...current.items.slice(0, current.index + 1), target];
        return { items, index: items.length - 1 };
      });
    }
    onSection(target);
  };
  const dispatch = (name: "dubroom:undo" | "dubroom:redo") => {
    setOpenMenu(null);
    window.dispatchEvent(new Event(name));
  };

  const menus: TitlebarMenu[] = [
    {
      id: "file" as const,
      label: t("titlebar.file"),
      items: [
        { label: t("nav.dashboard"), action: () => navigate("dashboard"), shortcut: "Ctrl+1" },
        { label: t("nav.projects"), action: () => navigate("projects"), shortcut: "Ctrl+2" },
        {
          label: t("nav.studio"),
          action: () => navigate("studio"),
          shortcut: "Ctrl+3",
          disabled: !activeProject,
        },
      ],
    },
    {
      id: "edit" as const,
      label: t("titlebar.edit"),
      items: [
        { label: t("common.undo"), action: () => dispatch("dubroom:undo"), shortcut: "Ctrl+Z" },
        { label: t("common.redo"), action: () => dispatch("dubroom:redo"), shortcut: "Ctrl+Y" },
      ],
    },
    {
      id: "view" as const,
      label: t("titlebar.view"),
      items: [
        {
          label: t(rail === "expanded" ? "shell.collapse" : "shell.openNavigation"),
          action: () => {
            setOpenMenu(null);
            setRail((current) => (current === "expanded" ? "compact" : "expanded"));
          },
          shortcut: "Ctrl+B",
        },
        {
          label: t("shell.focus"),
          action: () => {
            setOpenMenu(null);
            setRail("focus");
          },
          shortcut: "F11",
        },
      ],
    },
    {
      id: "help" as const,
      label: t("titlebar.help"),
      items: [
        { label: t("nav.engines"), action: () => navigate("engines") },
        { label: t("titlebar.diagnostics"), action: () => navigate("settings") },
      ],
    },
  ];

  return (
    <div
      ref={titlebar}
      data-testid="desktop-titlebar"
      className={cn(
        "window-drag relative z-[80] flex h-9 items-center border-b border-line bg-canvas pl-2",
        window.dubStudio && "pr-[138px]",
      )}
    >
      <button
        className="window-no-drag flex h-7 items-center gap-2 rounded-md px-1.5 text-copy transition hover:bg-raised hover:text-foreground"
        title={t("titlebar.home")}
        aria-label={t("titlebar.home")}
        onClick={() => navigate("dashboard")}
      >
        <span className="grid size-5 place-items-center rounded-md border border-accent/30 bg-accent-soft text-accent">
          <AudioWaveform className="size-3" />
        </span>
        <strong className="text-[11px] font-semibold tracking-wide">
          {t("titlebar.appName")}
        </strong>
      </button>
      <span className="mx-2 h-4 w-px bg-line" />
      <div className="window-no-drag flex items-center gap-0.5">
        <button
          className="ui-icon-button size-7 rounded-md"
          title={t("titlebar.previous")}
          aria-label={t("titlebar.previous")}
          disabled={sectionHistory.index === 0}
          onClick={() => moveHistory(-1)}
        >
          <ArrowLeft className="size-3.5" />
        </button>
        <button
          className="ui-icon-button size-7 rounded-md"
          title={t("titlebar.next")}
          aria-label={t("titlebar.next")}
          disabled={sectionHistory.index >= sectionHistory.items.length - 1}
          onClick={() => moveHistory(1)}
        >
          <ArrowRight className="size-3.5" />
        </button>
        <button
          data-testid="sidebar-toggle"
          className={cn(
            "ui-icon-button size-7 rounded-md",
            rail === "focus" &&
              "border-accent/30 bg-accent-soft text-accent",
          )}
          title={`${t(
            rail === "expanded" ? "shell.collapse" : "shell.openNavigation",
          )} · Ctrl+B`}
          aria-label={t(
            rail === "expanded" ? "shell.collapse" : "shell.openNavigation",
          )}
          onClick={() =>
            setRail((current) =>
              current === "focus"
                ? "compact"
                : current === "expanded"
                  ? "compact"
                  : "expanded",
            )
          }
        >
          {rail === "expanded" ? (
            <PanelLeftClose className="size-3.5" />
          ) : (
            <PanelLeftOpen className="size-3.5" />
          )}
        </button>
      </div>
      <span className="mx-2 h-4 w-px bg-line" />
      <nav className="window-no-drag flex h-full items-center" aria-label={t("titlebar.appMenu")}>
        {menus.map((menu) => (
          <div key={menu.id} className="relative h-full" data-titlebar-menu>
            <button
              className={cn(
                "flex h-full items-center gap-1 rounded-none px-2.5 text-[11px] text-copy transition hover:bg-raised hover:text-foreground",
                openMenu === menu.id && "bg-raised text-foreground",
              )}
              aria-haspopup="menu"
              aria-expanded={openMenu === menu.id}
              onClick={() => setOpenMenu((current) => (current === menu.id ? null : menu.id))}
            >
              {menu.label}
              <ChevronDown className="size-3 opacity-50" />
            </button>
            {openMenu === menu.id && (
              <div
                role="menu"
                className="absolute left-0 top-full z-[90] min-w-56 rounded-b-xl border border-line-strong bg-surface p-1.5 shadow-[var(--shadow-panel)]"
              >
                {menu.items.map((item) => (
                  <button
                    key={item.label}
                    role="menuitem"
                    disabled={item.disabled}
                    className="flex h-9 w-full items-center justify-between gap-5 rounded-lg px-2.5 text-left text-[11px] text-copy transition hover:bg-raised hover:text-foreground disabled:opacity-40"
                    onClick={item.action}
                  >
                    <span>{item.label}</span>
                    {item.shortcut && (
                      <kbd className="font-mono text-[10px] text-muted">
                        {item.shortcut}
                      </kbd>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>
      <div className="window-no-drag ml-auto flex min-w-0 items-center gap-1 pr-2">
        <button
          className="flex h-7 min-w-0 max-w-60 items-center gap-2 rounded-md border border-line px-2 text-left transition hover:border-line-strong hover:bg-raised"
          title={activeProject?.name || t("shell.noProject")}
          onClick={() => navigate("projects")}
        >
          <span className="grid size-5 shrink-0 place-items-center rounded border border-line-strong bg-raised font-mono text-[10px] text-accent">
            {activeProject?.name.slice(0, 2).toUpperCase() || "--"}
          </span>
          <strong className="truncate text-[10px] font-semibold">
            {activeProject?.name || t("shell.noProject")}
          </strong>
          <ChevronDown className="size-3 shrink-0 text-muted" />
        </button>
        <button
          data-shell-panel-trigger
          className="flex h-7 items-center gap-1.5 rounded-md border border-line px-2 text-[10px] font-semibold transition hover:border-line-strong hover:bg-raised"
          title={t(backendOnline ? "shell.backendReady" : "shell.backendOffline")}
          onClick={() => setPanel(panel === "status" ? null : "status")}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              backendOnline ? "bg-success" : "bg-danger",
            )}
          />
          <span className="hidden min-[1180px]:inline">
            {t(backendOnline ? "shell.backendReady" : "shell.backendOffline")}
          </span>
          <CircleGauge className="size-3.5 text-muted" />
        </button>
        <button
          data-shell-panel-trigger
          className={cn(
            "ui-icon-button relative size-7 rounded-md",
            activityCount > 0 && "text-accent",
          )}
          title={t("activity.tooltip")}
          onClick={() => setPanel(panel === "activity" ? null : "activity")}
        >
          <Activity
            className={cn("size-3.5", activityCount > 0 && "animate-pulse")}
          />
          {activityCount > 0 && (
            <em className="absolute -right-0.5 -top-0.5 grid size-4 place-items-center rounded-full bg-accent text-[10px] not-italic text-accent-ink">
              {Math.min(activityCount, 9)}
            </em>
          )}
        </button>
        <button
          data-shell-panel-trigger
          className="ui-icon-button relative size-7 rounded-md"
          title={t("notifications.tooltip")}
          onClick={() => {
            markAllRead();
            setPanel(panel === "notifications" ? null : "notifications");
          }}
        >
          <Bell className="size-3.5" />
          {unread > 0 && (
            <em className="absolute -right-0.5 -top-0.5 grid size-4 place-items-center rounded-full bg-danger text-[10px] not-italic text-white">
              {Math.min(unread, 9)}
            </em>
          )}
        </button>
      </div>
    </div>
  );
}
