import { useEffect, useRef, useState, type ReactNode } from "react";
import { Group, Panel, Separator, type PanelSize } from "react-resizable-panels";

const STORAGE_KEY = "dubroom.studio.timelineHeight";
const DEFAULT_TIMELINE_HEIGHT = 300;
const MIN_TIMELINE_HEIGHT = 220;
const MAX_TIMELINE_HEIGHT = 440;

function readTimelineHeight() {
  const stored = Number(localStorage.getItem(STORAGE_KEY));
  if (!Number.isFinite(stored)) return DEFAULT_TIMELINE_HEIGHT;
  return Math.max(
    MIN_TIMELINE_HEIGHT,
    Math.min(MAX_TIMELINE_HEIGHT, stored),
  );
}

export function StudioVerticalDock({
  stage,
  timeline,
}: {
  stage: ReactNode;
  timeline: ReactNode;
}) {
  const [initialTimelineHeight] = useState(readTimelineHeight);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    },
    [],
  );

  const rememberTimelineHeight = (size: PanelSize) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(
        STORAGE_KEY,
        String(Math.round(size.inPixels)),
      );
    }, 160);
  };

  return (
    <Group
      id="studio-vertical-layout"
      orientation="vertical"
      className="min-h-0 min-w-0 w-full max-w-full flex-1 overflow-hidden"
    >
      <Panel
        id="studio-stage-panel"
        minSize={260}
        className="h-full min-h-0 min-w-0 max-w-full overflow-hidden"
      >
        {stage}
      </Panel>
      <Separator
        id="studio-timeline-separator"
        className="group relative z-40 h-1.5 bg-line outline-none transition-colors hover:bg-accent/70 focus-visible:bg-accent"
      >
        <i className="pointer-events-none absolute left-1/2 top-1/2 h-0.5 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full bg-line-strong transition group-hover:bg-accent-ink" />
      </Separator>
      <Panel
        id="studio-timeline-panel"
        defaultSize={initialTimelineHeight}
        minSize={MIN_TIMELINE_HEIGHT}
        maxSize={MAX_TIMELINE_HEIGHT}
        groupResizeBehavior="preserve-pixel-size"
        className="h-full min-h-0 min-w-0 max-w-full overflow-hidden"
        onResize={rememberTimelineHeight}
      >
        {timeline}
      </Panel>
    </Group>
  );
}
