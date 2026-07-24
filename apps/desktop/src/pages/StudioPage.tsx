import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlignJustify,
  AudioLines,
  ChevronRight,
  Clapperboard,
  Download,
  Film,
  Flag as Marker,
  Gauge,
  Languages,
  Lock,
  Magnet,
  Maximize2,
  Menu,
  MessageSquareText,
  Mic2,
  MoreHorizontal,
  Music2,
  Pause,
  Play,
  Plus,
  Redo2,
  Scissors,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Subtitles,
  Trash2,
  Undo2,
  Unlock,
  Users,
  Volume2,
  VolumeX,
  WandSparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import type {
  AnalysisState,
  EngineRecord,
  ExportCapabilities,
  ExportDelivery,
  ExportOptions,
  ExportPlan,
  ExportRegion,
  JobRecord,
  MediaProbe,
  ProjectRecord,
  Segment,
  StudioStep,
  TimelineProjectState,
  TimelineEditClip,
  VoiceboxModel,
  VoiceboxProfile,
  VoiceboxStatus,
} from "@/types";

type Props = {
  project: ProjectRecord | null;
  step: StudioStep;
  onStep: (step: StudioStep) => void;
  analysis: AnalysisState | null;
  probe: MediaProbe | null;
  streamUrl: string;
  engines: EngineRecord[];
  jobs: JobRecord[];
  voiceboxStatus: VoiceboxStatus | null;
  voiceboxModels: VoiceboxModel[];
  voiceboxProfiles: VoiceboxProfile[];
  onRefreshVoicebox: () => Promise<void>;
  onImport: () => void;
  onAnalyze: () => void;
  onTranslate: () => void;
  onGenerate: () => void;
  onExport: (options: ExportOptions) => void;
  onOpenTools: () => void;
  onSaveAnalysis: (state: AnalysisState) => void;
};
type Mode = "media" | "script" | "cast" | "voice" | "mix" | "export";
type FitMode = "fit" | "actual" | "fill" | "blur";
type DragKind = "move" | "start" | "end";
const modeToStep: Record<Mode, StudioStep> = {
  media: "media",
  script: "transcript",
  cast: "characters",
  voice: "voices",
  mix: "mix",
  export: "export",
};
const stepToMode = (step: StudioStep): Mode =>
  step === "transcript" || step === "translation"
    ? "script"
    : step === "characters"
      ? "cast"
      : step === "voices" || step === "rvc"
        ? "voice"
        : step === "sync" || step === "mix"
          ? "mix"
          : step === "export"
            ? "export"
            : "media";
const modeMeta: [Mode, typeof Film, string][] = [
  ["media", Film, "studio.domain.media"],
  ["script", MessageSquareText, "studio.domain.script"],
  ["cast", Users, "studio.domain.cast"],
  ["voice", Mic2, "studio.domain.audio"],
  ["mix", SlidersHorizontal, "studio.mix"],
  ["export", Download, "studio.domain.delivery"],
];
const defaultExport: ExportOptions = {
  delivery: "full",
  container: "mp4",
  video_codec: "h264",
  audio_codec: "aac",
  quality: 19,
  preset: "medium",
  audio_bitrate: "320k",
  resolution: "source",
  aspect: "source",
  framing: "fit",
  upscale: "off",
  normalize_audio: true,
  original_volume: 0.32,
  voice_volume: 1,
  music_volume: 0.5,
  ducking: true,
  short_duration: 60,
  short_mode: "dialogue",
  segment_strategy: "count",
  segment_count: 20,
  segment_duration_seconds: 600,
  segment_ranges: [],
};

export function StudioPage({
  project,
  step,
  onStep,
  analysis,
  probe,
  streamUrl,
  engines,
  jobs,
  onImport,
  onAnalyze,
  onTranslate,
  onGenerate,
  onExport,
  onOpenTools,
  onSaveAnalysis,
}: Props) {
  const { t } = useI18n();
  const mode = stepToMode(step);
  const duration = Math.max(0.1, probe?.duration_seconds || 90);
  const videoRef = useRef<HTMLVideoElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const timelineScrollTargetRef = useRef<number | null>(null);
  const timelineScrollTimerRef = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [fit, setFit] = useState<FitMode>("fit");
  const [sceneOpen, setSceneOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorWidth, setInspectorWidth] = useState(320);
  const [zoom, setZoom] = useState(48);
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: 30 });
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedEditClips, setSelectedEditClips] = useState<string[]>([]);
  const [dragPreview, setDragPreview] = useState<
    Record<string, { start: number; end: number }>
  >({});
  const [history, setHistory] = useState<AnalysisState[]>([]);
  const [future, setFuture] = useState<AnalysisState[]>([]);
  const [timelineHistory, setTimelineHistory] = useState<
    TimelineProjectState[]
  >([]);
  const [timelineFuture, setTimelineFuture] = useState<TimelineProjectState[]>(
    [],
  );
  const [timelineState, setTimelineState] = useState<TimelineProjectState>({
    version: 3,
    markers: [],
    export_regions: [],
    edit_initialized: false,
    edit_clips: [],
    in_point: null,
    out_point: null,
    track_states: {},
    preferences: {},
  });
  const [exportOptions, setExportOptions] =
    useState<ExportOptions>(defaultExport);
  const [plan, setPlan] = useState<ExportPlan | null>(null);
  const [capabilities, setCapabilities] = useState<ExportCapabilities | null>(
    null,
  );
  const [advanced, setAdvanced] = useState(false);
  const [planning, setPlanning] = useState(false);
  const timelineWidth = Math.max(900, duration * zoom);
  const segments = analysis?.segments || [];
  const visibleSegments = useMemo(
    () =>
      segments.filter(
        (segment) =>
          toSeconds(segment.end) >= visibleRange.start &&
          toSeconds(segment.start) <= visibleRange.end,
      ),
    [segments, visibleRange],
  );
  const selectedSegment =
    segments.find((segment) => selected.includes(segment.id)) || null;
  const activeJobs = jobs.filter((job) =>
    ["queued", "running"].includes(job.status),
  );
  const editClips = useMemo<TimelineEditClip[]>(
    () =>
      timelineState.edit_initialized
        ? timelineState.edit_clips
        : [
            {
              id: "source-full",
              name: project?.name || t("studio.track.video"),
              source_start: 0,
              source_end: duration,
              enabled: true,
            },
          ],
    [timelineState.edit_initialized, timelineState.edit_clips, project?.name, duration, t],
  );
  const editRanges = useMemo(
    () =>
      editClips
        .filter((clip) => clip.enabled)
        .map((clip) => ({
          source_start: clip.source_start,
          source_end: clip.source_end,
        })),
    [editClips],
  );
  const editedDuration = editRanges.reduce(
    (total, range) => total + range.source_end - range.source_start,
    0,
  );
  const snapping = timelineState.preferences.snapping !== false;

  useEffect(() => {
    if (!project) return;
    void api
      .timelineState(project.id)
      .then((state) =>
        setTimelineState({
          ...state,
          version: 3,
          edit_initialized: state.edit_initialized ?? false,
          edit_clips: state.edit_clips || [],
          in_point: state.in_point ?? null,
          out_point: state.out_point ?? null,
          track_states: state.track_states || {},
          preferences: state.preferences || {},
        }),
      )
      .catch(() => null);
  }, [project?.id]);
  useEffect(() => {
    void api
      .exportCapabilities()
      .then(setCapabilities)
      .catch(() => null);
  }, []);
  const manualRegionKey =
    exportOptions.segment_strategy === "manual"
      ? JSON.stringify(timelineState.export_regions)
      : "";
  const editRangeKey = JSON.stringify(editRanges);
  useEffect(() => {
    if (mode !== "export" || !project) return;
    const timer = setTimeout(async () => {
      setPlanning(true);
      try {
        const result = await api.exportPlan(
          project.id,
          {
            ...exportOptions,
            edit_ranges: editRanges,
            original_volume: timelineState.track_states.original?.muted
              ? 0
              : exportOptions.original_volume,
            voice_volume:
              timelineState.track_states.voices?.muted ||
              timelineState.track_states.rvc?.muted
                ? 0
                : exportOptions.voice_volume,
            music_volume: timelineState.track_states.music?.muted
              ? 0
              : exportOptions.music_volume,
            segment_ranges:
              exportOptions.segment_strategy === "manual"
                ? timelineState.export_regions
                : exportOptions.segment_ranges,
          },
          duration,
        );
        setPlan(result);
        if (exportOptions.segment_strategy !== "manual")
          setTimelineState((state) => ({
            ...state,
            export_regions: result.regions,
          }));
      } catch {
        setPlan(null);
      } finally {
        setPlanning(false);
      }
    }, 260);
    return () => clearTimeout(timer);
  }, [
    mode,
    project?.id,
    duration,
    exportOptions,
    manualRegionKey,
    editRangeKey,
    timelineState.track_states,
  ]);
  const saveTimeline = useCallback(
    (next: TimelineProjectState) => {
      setTimelineState(next);
      if (project)
        void api.saveTimelineState(project.id, next).catch(() => null);
    },
    [project?.id],
  );
  const commitTimeline = useCallback(
    (next: TimelineProjectState) => {
      setTimelineHistory((items) => [...items.slice(-39), timelineState]);
      setTimelineFuture([]);
      saveTimeline(next);
    },
    [timelineState, saveTimeline],
  );

  const updateAnalysis = useCallback(
    (next: AnalysisState) => {
      if (analysis) {
        setHistory((items) => [...items.slice(-39), analysis]);
        setFuture([]);
      }
      onSaveAnalysis(next);
    },
    [analysis, onSaveAnalysis],
  );
  const undo = useCallback(() => {
    if (timelineHistory.length > 0) {
      const previous = timelineHistory.at(-1)!;
      setTimelineHistory((items) => items.slice(0, -1));
      setTimelineFuture((items) => [timelineState, ...items]);
      saveTimeline(previous);
      return;
    }
    if (!analysis || history.length === 0) return;
    const previous = history.at(-1)!;
    setHistory((items) => items.slice(0, -1));
    setFuture((items) => [analysis, ...items]);
    onSaveAnalysis(previous);
  }, [timelineHistory, timelineState, saveTimeline, analysis, history, onSaveAnalysis]);
  const redo = useCallback(() => {
    if (timelineFuture.length > 0) {
      const nextTimeline = timelineFuture[0];
      setTimelineFuture((items) => items.slice(1));
      setTimelineHistory((items) => [...items, timelineState]);
      saveTimeline(nextTimeline);
      return;
    }
    if (!analysis || future.length === 0) return;
    const next = future[0];
    setFuture((items) => items.slice(1));
    setHistory((items) => [...items, analysis]);
    onSaveAnalysis(next);
  }, [timelineFuture, timelineState, saveTimeline, analysis, future, onSaveAnalysis]);
  useEffect(() => {
    const u = () => undo(),
      r = () => redo();
    window.addEventListener("dubroom:undo", u);
    window.addEventListener("dubroom:redo", r);
    return () => {
      window.removeEventListener("dubroom:undo", u);
      window.removeEventListener("dubroom:redo", r);
    };
  }, [undo, redo]);

  const paintPlayhead = useCallback(
    (time: number) => {
      if (playheadRef.current)
        playheadRef.current.style.transform = `translateX(${160 + time * zoom}px)`;
    },
    [zoom],
  );
  useEffect(() => {
    paintPlayhead(currentTime);
  }, [currentTime, paintPlayhead]);
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      return;
    }
    let frames = 0;
    const loop = () => {
      const time = videoRef.current?.currentTime || 0;
      paintPlayhead(time);
      if (++frames % 6 === 0) setCurrentTime(time);
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, paintPlayhead]);
  const seek = (time: number) => {
    const next = Math.max(0, Math.min(duration, time));
    if (videoRef.current) videoRef.current.currentTime = next;
    setCurrentTime(next);
    paintPlayhead(next);
  };
  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
      setPlaying(true);
    } else {
      video.pause();
      setPlaying(false);
    }
  };
  const selectClip = (id: string, multiple: boolean) =>
    setSelected((current) =>
      multiple
        ? current.includes(id)
          ? current.filter((item) => item !== id)
          : [...current, id]
        : [id],
    );
  const snap = (value: number, exclude: string) => {
    if (!snapping) return value;
    const points = [
      currentTime,
      ...timelineState.markers.map((item) => item.time),
      ...segments
        .filter((item) => item.id !== exclude)
        .flatMap((item) => [toSeconds(item.start), toSeconds(item.end)]),
    ];
    const closest = points.reduce(
      (best, item) =>
        Math.abs(item - value) < Math.abs(best - value) ? item : best,
      value,
    );
    return Math.abs(closest - value) <= 8 / zoom ? closest : value;
  };
  const startDrag = (
    event: React.PointerEvent,
    segment: Segment,
    kind: DragKind,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    selectClip(segment.id, event.ctrlKey || event.metaKey);
    const originX = event.clientX;
    const original = {
      start: toSeconds(segment.start),
      end: toSeconds(segment.end),
    };
    let last = original;
    const move = (pointer: PointerEvent) => {
      const delta = (pointer.clientX - originX) / zoom;
      let start = original.start,
        end = original.end;
      if (kind === "move") {
        start = snap(Math.max(0, original.start + delta), segment.id);
        end = start + (original.end - original.start);
        if (end > duration) {
          end = duration;
          start = end - (original.end - original.start);
        }
      } else if (kind === "start")
        start = snap(
          Math.max(0, Math.min(end - 0.08, original.start + delta)),
          segment.id,
        );
      else
        end = snap(
          Math.min(duration, Math.max(start + 0.08, original.end + delta)),
          segment.id,
        );
      last = { start, end };
      setDragPreview((current) => ({ ...current, [segment.id]: last }));
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      setDragPreview((current) => {
        const next = { ...current };
        delete next[segment.id];
        return next;
      });
      if (!analysis) return;
      const nextSegments = analysis.segments.map((item) =>
        item.id === segment.id
          ? {
              ...item,
              start: formatTime(last.start),
              end: formatTime(last.end),
              left: round((last.start / duration) * 100),
              width: round(((last.end - last.start) / duration) * 100),
            }
          : item,
      );
      updateAnalysis({
        ...analysis,
        segments: nextSegments,
        updated_at: new Date().toISOString(),
      });
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
  };
  const editSegment = (patch: Partial<Segment>) => {
    if (!analysis || !selectedSegment) return;
    updateAnalysis({
      ...analysis,
      segments: analysis.segments.map((item) =>
        item.id === selectedSegment.id ? { ...item, ...patch } : item,
      ),
      updated_at: new Date().toISOString(),
    });
  };
  const splitAtPlayhead = () => {
    if (timelineState.track_states.video?.locked) return;
    const clip = editClips.find(
      (item) =>
        item.enabled &&
        currentTime > item.source_start + 0.04 &&
        currentTime < item.source_end - 0.04,
    );
    if (!clip) return;
    const left: TimelineEditClip = {
      ...clip,
      id: crypto.randomUUID(),
      name: `${clip.name} A`,
      source_end: round(currentTime),
    };
    const right: TimelineEditClip = {
      ...clip,
      id: crypto.randomUUID(),
      name: `${clip.name} B`,
      source_start: round(currentTime),
    };
    const nextClips = editClips.flatMap((item) =>
      item.id === clip.id ? [left, right] : [item],
    );
    setSelectedEditClips([right.id]);
    commitTimeline({
      ...timelineState,
      version: 3,
      edit_initialized: true,
      edit_clips: nextClips,
    });
  };
  const deleteSelectedEditClips = () => {
    if (
      timelineState.track_states.video?.locked ||
      selectedEditClips.length === 0 ||
      editClips.length <= selectedEditClips.length
    )
      return;
    commitTimeline({
      ...timelineState,
      version: 3,
      edit_initialized: true,
      edit_clips: editClips.filter(
        (clip) => !selectedEditClips.includes(clip.id),
      ),
    });
    setSelectedEditClips([]);
  };
  const setInPoint = () =>
    saveTimeline({
      ...timelineState,
      in_point: round(Math.min(currentTime, timelineState.out_point ?? duration)),
    });
  const setOutPoint = () =>
    saveTimeline({
      ...timelineState,
      out_point: round(Math.max(currentTime, timelineState.in_point ?? 0)),
    });
  const clearInOut = () =>
    saveTimeline({ ...timelineState, in_point: null, out_point: null });
  const cutMarkedRange = () => {
    if (timelineState.track_states.video?.locked) return;
    const rangeStart = timelineState.in_point;
    const rangeEnd = timelineState.out_point;
    if (
      rangeStart === null ||
      rangeEnd === null ||
      rangeEnd - rangeStart <= 0.04
    )
      return;
    const nextClips = editClips.flatMap((clip) => {
      if (clip.source_end <= rangeStart || clip.source_start >= rangeEnd)
        return [clip];
      const pieces: TimelineEditClip[] = [];
      if (clip.source_start < rangeStart)
        pieces.push({
          ...clip,
          id: crypto.randomUUID(),
          name: `${clip.name} A`,
          source_end: round(rangeStart),
        });
      if (clip.source_end > rangeEnd)
        pieces.push({
          ...clip,
          id: crypto.randomUUID(),
          name: `${clip.name} B`,
          source_start: round(rangeEnd),
        });
      return pieces;
    });
    if (nextClips.length === 0) return;
    setSelectedEditClips([]);
    commitTimeline({
      ...timelineState,
      version: 3,
      edit_initialized: true,
      edit_clips: nextClips,
      in_point: null,
      out_point: null,
    });
  };
  const updateTrackState = (
    track: string,
    patch: { muted?: boolean; locked?: boolean },
  ) =>
    saveTimeline({
      ...timelineState,
      track_states: {
        ...timelineState.track_states,
        [track]: { ...timelineState.track_states[track], ...patch },
      },
    });
  const addMarker = () => {
    const next = {
      ...timelineState,
      markers: [
        ...timelineState.markers,
        {
          id: crypto.randomUUID(),
          time: currentTime,
          label: `M${timelineState.markers.length + 1}`,
          color: "#d28a57",
        },
      ],
    };
    saveTimeline(next);
  };
  const timelineWheel = useCallback(
    (event: WheelEvent) => {
      const node = event.currentTarget;
      if (!(node instanceof HTMLDivElement)) return;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const rect = node.getBoundingClientRect();
        const cursor = event.clientX - rect.left + node.scrollLeft - 160;
        const time = Math.max(0, cursor / zoom);
        const next = Math.max(
          12,
          Math.min(240, zoom * (event.deltaY > 0 ? 0.88 : 1.14)),
        );
        setZoom(next);
        requestAnimationFrame(() => {
          node.scrollLeft = Math.max(
            0,
            160 + time * next - (event.clientX - rect.left),
          );
        });
        return;
      }
      if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        event.preventDefault();
        const delta = event.deltaX || event.deltaY;
        const base = timelineScrollTargetRef.current ?? node.scrollLeft;
        const target = Math.max(
          0,
          Math.min(node.scrollWidth - node.clientWidth, base + delta),
        );
        timelineScrollTargetRef.current = target;
        node.scrollLeft = target;
        if (timelineScrollTimerRef.current !== null)
          window.clearTimeout(timelineScrollTimerRef.current);
        timelineScrollTimerRef.current = window.setTimeout(() => {
          node.scrollLeft = timelineScrollTargetRef.current ?? target;
          timelineScrollTargetRef.current = null;
          timelineScrollTimerRef.current = null;
        }, 40);
      }
    },
    [zoom],
  );
  useEffect(() => {
    const node = timelineRef.current;
    if (!node) return;
    node.addEventListener("wheel", timelineWheel, { passive: false });
    return () => node.removeEventListener("wheel", timelineWheel);
  }, [timelineWheel]);
  useEffect(() => {
    const node = timelineRef.current;
    if (!node) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const start = Math.max(0, (node.scrollLeft - 160) / zoom - 2);
        const end = Math.min(
          duration,
          (node.scrollLeft + node.clientWidth - 160) / zoom + 2,
        );
        setVisibleRange((current) =>
          Math.abs(current.start - start) < 0.05 &&
          Math.abs(current.end - end) < 0.05
            ? current
            : { start, end },
        );
      });
    };
    node.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return () => {
      cancelAnimationFrame(frame);
      node.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, [zoom, duration]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement)?.matches("input,textarea,select"))
        return;
      if (event.code === "Space") {
        event.preventDefault();
        togglePlay();
      } else if (event.key === "ArrowLeft")
        seek(currentTime - (event.shiftKey ? 5 : 0.1));
      else if (event.key === "ArrowRight")
        seek(currentTime + (event.shiftKey ? 5 : 0.1));
      else if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "z"
      ) {
        event.preventDefault();
        event.shiftKey ? redo() : undo();
      } else if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "y"
      )
        redo();
      else if (event.key.toLowerCase() === "m") addMarker();
      else if (event.key.toLowerCase() === "i") setInPoint();
      else if (event.key.toLowerCase() === "o") setOutPoint();
      else if (event.key.toLowerCase() === "s") splitAtPlayhead();
      else if (event.key.toLowerCase() === "n")
        saveTimeline({
          ...timelineState,
          preferences: {
            ...timelineState.preferences,
            snapping: !snapping,
          },
        });
      else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelectedEditClips();
      } else if (event.key === "Escape") {
        setSelected([]);
        setSelectedEditClips([]);
      }
      else if (event.key === "+" || event.key === "=")
        setZoom((value) => Math.min(240, value * 1.2));
      else if (event.key === "-") setZoom((value) => Math.max(12, value / 1.2));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [
    currentTime,
    playing,
    undo,
    redo,
    timelineState,
    selectedEditClips,
    editClips,
    snapping,
  ]);
  if (!project)
    return (
      <div className="grid h-full place-items-center p-8">
        <div className="ui-panel max-w-lg p-8 text-center">
          <Clapperboard className="mx-auto size-8 text-muted" />
          <h2 className="mt-4 text-lg font-semibold">{t("studio.empty")}</h2>
          <p className="mt-2 text-[12px] text-copy">{t("studio.emptyBody")}</p>
          <button
            className="ui-button ui-button-primary mt-5"
            onClick={onImport}
          >
            <Plus />
            {t("dashboard.import")}
          </button>
        </div>
      </div>
    );

  return (
    <div
      data-testid="studio-workbench"
      className="flex h-full min-h-0 min-w-0 w-full max-w-full flex-col overflow-hidden bg-canvas"
    >
      <header className="flex h-[42px] shrink-0 min-w-0 items-center border-b border-line bg-surface px-2">
        <button
          className="ui-icon-button mr-1 size-8 shrink-0"
          title={t("studio.storyboard")}
          onClick={() => setSceneOpen((value) => !value)}
        >
          <Menu />
        </button>
        <nav
          data-testid="studio-modes"
          className="mx-auto flex h-9 min-w-0 items-center justify-center gap-0.5 overflow-x-auto rounded-lg border border-line bg-canvas/70 p-0.5"
        >
          {modeMeta.map(([id, Icon, key]) => (
            <button
              key={id}
              className={`relative flex h-7 min-w-[86px] items-center justify-center gap-1.5 rounded-md px-3 text-[10px] font-semibold transition-colors ${mode === id ? "bg-raised text-foreground shadow-sm" : "text-muted hover:bg-raised/50 hover:text-copy"}`}
              onClick={() => onStep(modeToStep[id])}
            >
              <Icon className="size-3.5" />
              {t(key)}
              {mode === id && (
                <i className="absolute inset-x-3 -bottom-1 h-0.5 rounded-full bg-accent" />
              )}
            </button>
          ))}
        </nav>
        <div className="flex shrink-0 items-center gap-1">
          <button
            className="ui-icon-button size-8"
            title={t("common.undo")}
            disabled={!history.length}
            onClick={undo}
          >
            <Undo2 />
          </button>
          <button
            className="ui-icon-button size-8"
            title={t("common.redo")}
            disabled={!future.length}
            onClick={redo}
          >
            <Redo2 />
          </button>
          <button
            className="ui-icon-button size-8"
            title={t("studio.inspector")}
            onClick={() => setInspectorOpen((value) => !value)}
          >
            <Settings2 />
          </button>
        </div>
      </header>

      <Group id="studio-vertical-layout" orientation="vertical" className="min-h-0 flex-1">
      <Panel id="studio-stage-panel" minSize={260} className="h-full min-h-0 overflow-hidden">
      <main
        className={`relative grid min-h-0 min-w-0 grid-cols-1 overflow-hidden ${
          sceneOpen && inspectorOpen
            ? "xl:grid-cols-[220px_minmax(360px,1fr)_var(--inspector-width)]"
            : sceneOpen
              ? "xl:grid-cols-[220px_minmax(360px,1fr)]"
              : inspectorOpen
                ? "xl:grid-cols-[minmax(360px,1fr)_var(--inspector-width)]"
                : "xl:grid-cols-[minmax(360px,1fr)]"
        }`}
        style={
          {
            "--inspector-width": `${inspectorWidth}px`,
          } as React.CSSProperties
        }
      >
        {sceneOpen && (
          <aside className="hidden min-h-0 border-r border-line bg-surface xl:flex xl:flex-col">
            <div className="flex h-11 items-center justify-between border-b border-line px-3">
              <span className="ui-kicker">
                {mode === "export"
                  ? t("export.outputs")
                  : t("studio.storyboard")}
              </span>
              <span className="ui-chip">
                {mode === "export" ? plan?.output_count || 0 : segments.length}
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-2">
              {mode === "export" ? (
                <RegionList
                  plan={plan}
                  onChange={(regions) => {
                    setPlan((current) =>
                      current
                        ? {
                            ...current,
                            regions,
                            output_count: regions.filter((item) => item.enabled)
                              .length,
                          }
                        : null,
                    );
                    saveTimeline({ ...timelineState, export_regions: regions });
                  }}
                />
              ) : segments.length > 0 ? (
                segments.map((segment, index) => (
                  <button
                    key={segment.id}
                    className={`mb-1 flex w-full gap-3 rounded-lg border p-2 text-left ${selected.includes(segment.id) ? "border-accent bg-accent/5" : "border-transparent hover:bg-raised"}`}
                    onClick={() => {
                      selectClip(segment.id, false);
                      seek(toSeconds(segment.start));
                    }}
                  >
                    <span className="grid size-7 shrink-0 place-items-center rounded bg-raised font-mono text-[10px] text-muted">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0">
                      <strong className="block truncate text-[11px]">
                        {segment.speaker || t("common.undefined")}
                      </strong>
                      <small className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted">
                        {segment.translatedText ||
                          segment.sourceText ||
                          segment.label}
                      </small>
                      <em className="mt-1 block font-mono text-[11px] not-italic text-muted">
                        {segment.start} — {segment.end}
                      </em>
                    </span>
                  </button>
                ))
              ) : (
                <div className="grid h-full min-h-52 place-items-center p-3 text-center">
                  <div>
                    <span className="mx-auto grid size-10 place-items-center rounded-xl border border-line bg-raised text-muted">
                      <Clapperboard className="size-4" />
                    </span>
                    <strong className="mt-3 block text-[11px]">
                      {t("studio.scenePending")}
                    </strong>
                    <p className="mt-1 text-[10px] leading-4 text-muted">
                      {t("studio.scenePendingBody")}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </aside>
        )}

        <section className="relative flex min-h-0 min-w-0 flex-col bg-[#070809]">
          <div className="relative min-h-0 flex-1 overflow-hidden p-2">
            <div
              data-testid="program-monitor"
              className="group relative mx-auto flex h-full max-w-[1100px] items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black shadow-2xl"
            >
              {streamUrl ? (
                <>
                  {fit === "blur" && (
                    <video
                      className="absolute inset-[-5%] size-[110%] object-cover opacity-45 blur-2xl"
                      src={streamUrl}
                      muted
                    />
                  )}
                  <video
                    ref={videoRef}
                    className={`relative z-10 max-h-full max-w-full ${fit === "fill" ? "size-full object-cover" : fit === "actual" ? "h-auto w-auto max-w-none object-contain" : "size-full object-contain"}`}
                    src={streamUrl}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                    onEnded={() => setPlaying(false)}
                    onLoadedMetadata={() =>
                      setCurrentTime(videoRef.current?.currentTime || 0)
                    }
                  />
                </>
              ) : (
                <div className="text-center">
                  <Film className="mx-auto size-8 text-white/20" />
                  <p className="mt-3 text-[11px] text-white/40">
                    {t("studio.sourceUnavailable")}
                  </p>
                </div>
              )}

              <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-3 bg-gradient-to-b from-black/85 via-black/45 to-transparent px-3 pb-8 pt-3">
                <span className="flex min-w-0 items-center gap-2 rounded-md border border-white/10 bg-black/45 px-2 py-1 text-[10px] text-white/80 backdrop-blur">
                  <i className="size-1.5 shrink-0 rounded-full bg-success" />
                  <strong className="max-w-52 truncate font-medium">
                    {project.name}
                  </strong>
                  <span className="font-mono text-white/45">
                    {probe?.video?.width || "—"}×{probe?.video?.height || "—"}
                  </span>
                </span>
                <div className="pointer-events-auto flex items-center gap-0.5 rounded-lg border border-white/10 bg-black/55 p-0.5 backdrop-blur">
                  <ViewButton
                    active={fit === "fit"}
                    label={t("studio.fit")}
                    onClick={() => setFit("fit")}
                  />
                  <ViewButton
                    active={fit === "actual"}
                    label="100%"
                    onClick={() => setFit("actual")}
                  />
                  <ViewButton
                    active={fit === "fill"}
                    label={t("studio.fill")}
                    onClick={() => setFit("fill")}
                  />
                  <ViewButton
                    active={fit === "blur"}
                    label={t("studio.blurBackground")}
                    onClick={() => setFit("blur")}
                  />
                  <button
                    className="grid size-7 place-items-center rounded text-white/65 transition hover:bg-white/10 hover:text-white"
                    title={t("studio.fullscreen")}
                    onClick={() => void videoRef.current?.requestFullscreen()}
                  >
                    <Maximize2 className="size-3.5" />
                  </button>
                </div>
              </div>

              <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex items-end gap-2 bg-gradient-to-t from-black/90 via-black/55 to-transparent px-3 pb-3 pt-10">
                <button
                  className="pointer-events-auto grid size-8 shrink-0 place-items-center rounded-full bg-white text-black transition hover:scale-105"
                  title={playing ? t("studio.pause") : t("studio.play")}
                  onClick={togglePlay}
                >
                  {playing ? (
                    <Pause className="size-3.5" />
                  ) : (
                    <Play className="ml-0.5 size-3.5" />
                  )}
                </button>
                <span className="w-28 shrink-0 font-mono text-[10px] text-white/80">
                  {formatClock(currentTime)} / {formatClock(duration)}
                </span>
                <input
                  className="pointer-events-auto mb-3 h-1 min-w-20 flex-1 accent-[var(--ui-accent)]"
                  aria-label={t("studio.videoPosition")}
                  type="range"
                  min={0}
                  max={duration}
                  step={0.01}
                  value={currentTime}
                  onChange={(event) => seek(Number(event.target.value))}
                />
                <Volume2 className="mb-2 size-3.5 shrink-0 text-white/60" />
                <button
                  className="ui-button ui-button-primary pointer-events-auto h-8 shrink-0"
                  onClick={() =>
                    mode === "media"
                      ? onAnalyze()
                      : mode === "script"
                        ? onTranslate()
                        : mode === "voice"
                          ? onGenerate()
                          : mode === "export"
                            ? onExport({
                                ...exportOptions,
                                edit_ranges: editRanges,
                                original_volume: timelineState.track_states
                                  .original?.muted
                                  ? 0
                                  : exportOptions.original_volume,
                                voice_volume:
                                  timelineState.track_states.voices?.muted ||
                                  timelineState.track_states.rvc?.muted
                                    ? 0
                                    : exportOptions.voice_volume,
                                music_volume: timelineState.track_states.music
                                  ?.muted
                                  ? 0
                                  : exportOptions.music_volume,
                                segment_ranges: timelineState.export_regions,
                              })
                            : onOpenTools()
                  }
                >
                  {mode === "export" ? <Download /> : <Sparkles />}
                  {mode === "media"
                    ? t("studio.analyze")
                    : mode === "script"
                      ? t("studio.translate")
                      : mode === "voice"
                        ? t("studio.generateVoices")
                        : mode === "export"
                          ? t("export.launch")
                          : t("common.tools")}
                </button>
              </div>
            </div>
          </div>
        </section>

        {inspectorOpen && (
          <aside className="absolute inset-y-0 right-0 z-30 flex min-h-0 w-[320px] flex-col border-l border-line bg-surface shadow-2xl xl:static xl:w-auto xl:shadow-none">
            <div
              className="absolute -left-1 top-0 z-40 hidden h-full w-2 cursor-col-resize transition hover:bg-accent/40 xl:block"
              onPointerDown={(event) => {
                event.preventDefault();
                const origin = event.clientX;
                const start = inspectorWidth;
                const move = (nextEvent: PointerEvent) =>
                  setInspectorWidth(
                    Math.max(
                      280,
                      Math.min(440, start + origin - nextEvent.clientX),
                    ),
                  );
                const up = () => {
                  document.removeEventListener("pointermove", move);
                  document.removeEventListener("pointerup", up);
                };
                document.addEventListener("pointermove", move);
                document.addEventListener("pointerup", up, { once: true });
              }}
            />
            <div className="flex h-11 items-center justify-between border-b border-line px-3">
              <span className="ui-kicker">
                {mode === "export" ? t("export.recipe") : t("studio.inspector")}
              </span>
              <button
                className="ui-icon-button xl:hidden"
                onClick={() => setInspectorOpen(false)}
              >
                <X />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-3">
              {mode === "export" ? (
                <ExportInspector
                  options={exportOptions}
                  onChange={setExportOptions}
                  plan={plan}
                  capabilities={capabilities}
                  advanced={advanced}
                  setAdvanced={setAdvanced}
                  planning={planning}
                />
              ) : (
                <ContextInspector
                  segment={selectedSegment}
                  probe={probe}
                  analysis={analysis}
                  engines={engines}
                  onEdit={editSegment}
                />
              )}
            </div>
          </aside>
        )}
      </main>
      </Panel>
      <Separator
        id="studio-timeline-separator"
        className="group relative z-40 h-1.5 bg-line outline-none transition-colors hover:bg-accent/70 focus-visible:bg-accent"
      >
        <i className="pointer-events-none absolute left-1/2 top-1/2 h-0.5 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full bg-line-strong transition group-hover:bg-accent-ink" />
      </Separator>
      <Panel
        id="studio-timeline-panel"
        defaultSize={300}
        minSize={220}
        maxSize={440}
        groupResizeBehavior="preserve-pixel-size"
        className="h-full min-h-0 overflow-hidden"
      >
      <section
        data-testid="studio-timeline"
        className="relative h-full min-w-0 max-w-full overflow-hidden bg-surface"
      >
        <div className="flex h-9 min-w-0 items-center gap-1 border-b border-line bg-surface px-2">
          <button
            className="ui-icon-button size-8"
            title={t("studio.zoomOut")}
            onClick={() => setZoom((value) => Math.max(12, value / 1.2))}
          >
            <ZoomOut />
          </button>
          <input
            className="w-24 accent-[var(--ui-accent)]"
            type="range"
            min={12}
            max={240}
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          />
          <button
            className="ui-icon-button size-8"
            title={t("studio.zoomIn")}
            onClick={() => setZoom((value) => Math.min(240, value * 1.2))}
          >
            <ZoomIn />
          </button>
          <span className="ml-1 font-mono text-[11px] text-muted">
            {zoom.toFixed(0)} px/s
          </span>
          <span className="mx-2 h-4 w-px bg-line" />
          <strong className="font-mono text-[10px] font-medium text-copy">
            {formatClock(currentTime)}
          </strong>
          <span className="mx-2 h-4 w-px bg-line" />
          <div
            data-testid="edit-toolbar"
            className="flex shrink-0 items-center gap-0.5"
          >
            <button
              className="ui-icon-button size-8 font-mono text-[10px]"
              title={t("studio.edit.setIn")}
              onClick={setInPoint}
            >
              I
            </button>
            <button
              className="ui-icon-button size-8 font-mono text-[10px]"
              title={t("studio.edit.setOut")}
              onClick={setOutPoint}
            >
              O
            </button>
            <button
              className="ui-icon-button size-8"
              title={t("studio.edit.split")}
              disabled={timelineState.track_states.video?.locked}
              onClick={splitAtPlayhead}
            >
              <Scissors />
            </button>
            <button
              className="ui-icon-button size-8"
              title={t("studio.edit.deleteClip")}
              disabled={
                timelineState.track_states.video?.locked ||
                selectedEditClips.length === 0 ||
                editClips.length <= selectedEditClips.length
              }
              onClick={deleteSelectedEditClips}
            >
              <Trash2 />
            </button>
            <button
              className="ui-icon-button size-8"
              title={t("studio.edit.cutRange")}
              disabled={
                timelineState.track_states.video?.locked ||
                timelineState.in_point === null ||
                timelineState.out_point === null
              }
              onClick={cutMarkedRange}
            >
              <X />
            </button>
            <button
              className={cn(
                "ui-icon-button size-8",
                snapping && "border-accent/30 bg-accent-soft text-accent",
              )}
              title={t("studio.edit.snapping")}
              onClick={() =>
                saveTimeline({
                  ...timelineState,
                  preferences: {
                    ...timelineState.preferences,
                    snapping: !snapping,
                  },
                })
              }
            >
              <Magnet />
            </button>
            {(timelineState.in_point !== null ||
              timelineState.out_point !== null) && (
              <button
                className="ui-button h-7 px-2 font-mono text-[11px]"
                title={t("studio.edit.clearInOut")}
                onClick={clearInOut}
              >
                {timelineState.in_point === null
                  ? "—"
                  : formatClock(timelineState.in_point)}
                →
                {timelineState.out_point === null
                  ? "—"
                  : formatClock(timelineState.out_point)}
              </button>
            )}
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <button className="ui-button h-8" onClick={addMarker}>
              <Marker />
              {t("studio.marker")}
            </button>
            <button
              className="ui-icon-button size-8"
              onClick={() =>
                timelineRef.current?.scrollTo({
                  left: Math.max(
                    0,
                    160 +
                      currentTime * zoom -
                      timelineRef.current.clientWidth / 2,
                  ),
                  behavior: "smooth",
                })
              }
            >
              <AlignJustify />
            </button>
          </div>
        </div>
        <div
          ref={timelineRef}
          data-testid="timeline-scroll"
          className="timeline-scroll relative h-[calc(100%-36px)] min-w-0 max-w-full overflow-auto overscroll-contain"
          onPointerDown={(event) => {
            if (event.target !== event.currentTarget) return;
            const rect = event.currentTarget.getBoundingClientRect();
            seek(
              (event.clientX -
                rect.left +
                event.currentTarget.scrollLeft -
                160) /
                zoom,
            );
          }}
        >
          <div
            className="relative"
            style={{ width: timelineWidth + 160, minHeight: 380 }}
          >
            <Ruler duration={duration} zoom={zoom} />
            <Track
              label={t("studio.track.video")}
              icon={Film}
              width={timelineWidth}
              controls={{
                locked: Boolean(timelineState.track_states.video?.locked),
                onLock: () =>
                  updateTrackState("video", {
                    locked: !timelineState.track_states.video?.locked,
                  }),
              }}
            >
              {editClips.map((clip, index) => (
                <button
                  key={clip.id}
                  data-testid="edit-clip"
                  data-selected={selectedEditClips.includes(clip.id)}
                  className={cn(
                    "absolute inset-y-1 overflow-hidden rounded-md border border-accent/30 bg-accent/10 px-2 text-left transition hover:border-accent/70",
                    selectedEditClips.includes(clip.id) &&
                      "border-accent bg-accent/20 ring-1 ring-accent",
                  )}
                  style={{
                    left: clip.source_start * zoom,
                    width: Math.max(
                      6,
                      (clip.source_end - clip.source_start) * zoom,
                    ),
                  }}
                  onClick={(event) => {
                    setSelected([]);
                    setSelectedEditClips((current) =>
                      event.ctrlKey || event.metaKey
                        ? current.includes(clip.id)
                          ? current.filter((id) => id !== clip.id)
                          : [...current, clip.id]
                        : [clip.id],
                    );
                  }}
                  onDoubleClick={() => seek(clip.source_start)}
                >
                  <span className="flex items-center gap-1.5 truncate text-[11px] font-medium text-accent">
                    <Film className="size-3 shrink-0" />
                    {String(index + 1).padStart(2, "0")} · {clip.name}
                  </span>
                </button>
              ))}
            </Track>
            <Track
              label={t("studio.track.original")}
              icon={AudioLines}
              width={timelineWidth}
              controls={{
                muted: Boolean(timelineState.track_states.original?.muted),
                locked: Boolean(timelineState.track_states.original?.locked),
                onMute: () =>
                  updateTrackState("original", {
                    muted: !timelineState.track_states.original?.muted,
                  }),
                onLock: () =>
                  updateTrackState("original", {
                    locked: !timelineState.track_states.original?.locked,
                  }),
              }}
            >
              <Wave width={timelineWidth} />
            </Track>
            <Track
              label={t("studio.track.dialogue")}
              icon={MessageSquareText}
              width={timelineWidth}
            >
              {visibleSegments.map((segment) => (
                <Clip
                  key={segment.id}
                  segment={segment}
                  duration={duration}
                  zoom={zoom}
                  preview={dragPreview[segment.id]}
                  selected={selected.includes(segment.id)}
                  text={segment.sourceText || segment.label}
                  onSelect={(event) =>
                    selectClip(segment.id, event.ctrlKey || event.metaKey)
                  }
                  onDrag={startDrag}
                />
              ))}
            </Track>
            <Track
              label={t("studio.track.translation")}
              icon={Languages}
              width={timelineWidth}
            >
              {visibleSegments
                .filter((item) => item.translatedText)
                .map((segment) => (
                  <Clip
                    key={segment.id}
                    segment={segment}
                    duration={duration}
                    zoom={zoom}
                    preview={dragPreview[segment.id]}
                    selected={selected.includes(segment.id)}
                    text={segment.translatedText}
                    onSelect={(event) =>
                      selectClip(segment.id, event.ctrlKey || event.metaKey)
                    }
                    onDrag={startDrag}
                    tone="translation"
                  />
                ))}
            </Track>
            <Track
              label={t("studio.track.voices")}
              icon={Mic2}
              width={timelineWidth}
              controls={{
                muted: Boolean(timelineState.track_states.voices?.muted),
                locked: Boolean(timelineState.track_states.voices?.locked),
                onMute: () =>
                  updateTrackState("voices", {
                    muted: !timelineState.track_states.voices?.muted,
                  }),
                onLock: () =>
                  updateTrackState("voices", {
                    locked: !timelineState.track_states.voices?.locked,
                  }),
              }}
            >
              {visibleSegments
                .filter((item) => item.translatedText || item.adaptedText)
                .map((segment) => (
                  <Clip
                    key={segment.id}
                    segment={segment}
                    duration={duration}
                    zoom={zoom}
                    selected={selected.includes(segment.id)}
                    text={segment.speaker}
                    onSelect={(event) =>
                      selectClip(segment.id, event.ctrlKey || event.metaKey)
                    }
                    onDrag={startDrag}
                    tone="voice"
                  />
                ))}
            </Track>
            <Track
              label="RVC"
              icon={WandSparkles}
              width={timelineWidth}
              controls={{
                muted: Boolean(timelineState.track_states.rvc?.muted),
                locked: Boolean(timelineState.track_states.rvc?.locked),
                onMute: () =>
                  updateTrackState("rvc", {
                    muted: !timelineState.track_states.rvc?.muted,
                  }),
                onLock: () =>
                  updateTrackState("rvc", {
                    locked: !timelineState.track_states.rvc?.locked,
                  }),
              }}
            />
            <Track
              label={t("studio.track.music")}
              icon={Music2}
              width={timelineWidth}
              controls={{
                muted: Boolean(timelineState.track_states.music?.muted),
                locked: Boolean(timelineState.track_states.music?.locked),
                onMute: () =>
                  updateTrackState("music", {
                    muted: !timelineState.track_states.music?.muted,
                  }),
                onLock: () =>
                  updateTrackState("music", {
                    locked: !timelineState.track_states.music?.locked,
                  }),
              }}
            />
            <Track
              label={t("studio.track.subtitles")}
              icon={Subtitles}
              width={timelineWidth}
            >
              {visibleSegments
                .filter((item) => item.translatedText)
                .map((segment) => (
                  <Clip
                    key={segment.id}
                    segment={segment}
                    duration={duration}
                    zoom={zoom}
                    selected={false}
                    text={segment.translatedText}
                    onSelect={() => null}
                    onDrag={startDrag}
                    tone="subtitle"
                  />
                ))}
            </Track>
            <Track
              label={t("studio.track.markers")}
              icon={Marker}
              width={timelineWidth}
            >
              {timelineState.markers.map((item) => (
                <button
                  key={item.id}
                  className="absolute top-1 h-6 w-1 rounded bg-warning"
                  style={{ left: item.time * zoom }}
                  title={`${item.label} · ${formatClock(item.time)}`}
                  onClick={() => seek(item.time)}
                />
              ))}
            </Track>
            <Track
              label={t("studio.track.exportRegions")}
              icon={Scissors}
              width={timelineWidth}
            >
              {timelineState.export_regions.map((region, index) => (
                <div
                  key={region.id}
                  className={`absolute inset-y-1 rounded border ${region.enabled ? "border-accent/50 bg-accent/10" : "border-line bg-raised/30 opacity-50"}`}
                  style={{
                    left: region.start * zoom,
                    width: Math.max(4, (region.end - region.start) * zoom),
                  }}
                >
                  <span className="absolute left-1 top-0 truncate text-[11px] text-accent">
                    {index + 1}
                  </span>
                </div>
              ))}
            </Track>
            {timelineState.in_point !== null && (
              <div
                className="pointer-events-none absolute bottom-0 top-6 z-20 w-px bg-success"
                style={{ left: 160 + timelineState.in_point * zoom }}
              >
                <span className="absolute left-1 top-1 rounded bg-success px-1 font-mono text-[10px] text-black">
                  I
                </span>
              </div>
            )}
            {timelineState.out_point !== null && (
              <div
                className="pointer-events-none absolute bottom-0 top-6 z-20 w-px bg-danger"
                style={{ left: 160 + timelineState.out_point * zoom }}
              >
                <span className="absolute right-1 top-1 rounded bg-danger px-1 font-mono text-[10px] text-white">
                  O
                </span>
              </div>
            )}
            {timelineState.in_point !== null &&
              timelineState.out_point !== null && (
                <div
                  className="pointer-events-none absolute bottom-0 top-6 z-10 border-x border-accent/30 bg-accent/5"
                  style={{
                    left: 160 + timelineState.in_point * zoom,
                    width: Math.max(
                      1,
                      (timelineState.out_point - timelineState.in_point) *
                        zoom,
                    ),
                  }}
                />
              )}
            <div
              ref={playheadRef}
              className="timeline-playhead pointer-events-none absolute bottom-0 top-0 z-30 w-px bg-accent"
              style={{ transform: `translateX(${160 + currentTime * zoom}px)` }}
            >
              <i className="absolute -left-1.5 top-0 h-2.5 w-3 rounded-b bg-accent" />
            </div>
          </div>
        </div>
      </section>
      </Panel>
      </Group>
      {activeJobs.length > 0 && (
        <div className="pointer-events-none fixed bottom-4 right-4 z-50 grid gap-2">
          {activeJobs.slice(0, 3).map((job) => (
            <div
              key={job.id}
              className="ui-panel flex w-72 items-center gap-3 p-3 shadow-2xl"
            >
              <Gauge className="size-4 animate-pulse text-accent" />
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-[11px]">
                  {job.message}
                </strong>
                <i className="mt-2 block h-1 overflow-hidden rounded-full bg-canvas">
                  <b
                    className="block h-full bg-accent transition-[width]"
                    style={{ width: `${job.progress}%` }}
                  />
                </i>
              </span>
              <em className="font-mono text-[10px] not-italic text-muted">
                {job.progress}%
              </em>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ViewButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`h-7 rounded-md px-2 text-[10px] font-medium transition ${active ? "bg-white/15 text-white" : "text-white/55 hover:bg-white/10 hover:text-white"}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
function Ruler({ duration, zoom }: { duration: number; zoom: number }) {
  const interval = zoom >= 100 ? 1 : zoom >= 40 ? 5 : zoom >= 20 ? 10 : 30;
  const points = Array.from(
    { length: Math.floor(duration / interval) + 1 },
    (_, index) => index * interval,
  );
  return (
    <div className="sticky top-0 z-20 h-6 border-b border-line bg-canvas/95 backdrop-blur">
      <span className="sticky left-0 z-20 inline-flex h-full w-40 items-center border-r border-line bg-canvas px-3 font-mono text-[10px] text-muted">
        TIMECODE
      </span>
      {points.map((point) => (
        <i
          key={point}
          className="absolute bottom-0 h-2 border-l border-line text-[10px] not-italic text-muted"
          style={{ left: 160 + point * zoom }}
        >
          <span className="absolute -top-3 left-1 font-mono">
            {formatClock(point)}
          </span>
        </i>
      ))}
    </div>
  );
}
function Track({
  label,
  icon: Icon,
  width,
  children,
  controls,
}: {
  label: string;
  icon: typeof Film;
  width: number;
  children?: React.ReactNode;
  controls?: {
    muted?: boolean;
    locked?: boolean;
    onMute?: () => void;
    onLock?: () => void;
  };
}) {
  const { t } = useI18n();
  return (
    <div className="relative h-10 border-b border-line/70">
      <div className="sticky left-0 z-20 flex h-full w-40 items-center gap-2 border-r border-line bg-surface px-3">
        <Icon className="size-3.5 text-muted" />
        <span className="min-w-0 flex-1 truncate text-[10px] font-medium text-copy">
          {label}
        </span>
        {controls?.onMute && (
          <button
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded text-muted transition hover:bg-raised hover:text-foreground",
              controls.muted && "text-danger",
            )}
            title={t(controls.muted ? "studio.track.unmute" : "studio.track.mute")}
            onClick={controls.onMute}
          >
            {controls.muted ? (
              <VolumeX className="size-3" />
            ) : (
              <Volume2 className="size-3" />
            )}
          </button>
        )}
        {controls?.onLock && (
          <button
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded text-muted transition hover:bg-raised hover:text-foreground",
              controls.locked && "text-warning",
            )}
            title={t(controls.locked ? "studio.track.unlock" : "studio.track.lock")}
            onClick={controls.onLock}
          >
            {controls.locked ? (
              <Lock className="size-3" />
            ) : (
              <Unlock className="size-3" />
            )}
          </button>
        )}
      </div>
      <div className="absolute bottom-0 left-40 top-0" style={{ width }}>
        {children}
      </div>
    </div>
  );
}
function Wave({ width }: { width: number }) {
  return (
    <div
      className="absolute inset-y-2 overflow-hidden rounded bg-success/5"
      style={{ width }}
    >
      {Array.from({ length: Math.ceil(width / 8) }, (_, index) => (
        <i
          key={index}
          className="absolute top-1/2 w-px -translate-y-1/2 bg-success/40"
          style={{ left: index * 8, height: `${20 + ((index * 17) % 65)}%` }}
        />
      ))}
    </div>
  );
}
function Clip({
  segment,
  duration,
  zoom,
  preview,
  selected,
  text,
  onSelect,
  onDrag,
  tone = "dialogue",
}: {
  segment: Segment;
  duration: number;
  zoom: number;
  preview?: { start: number; end: number };
  selected: boolean;
  text: string;
  onSelect: (event: React.PointerEvent) => void;
  onDrag: (event: React.PointerEvent, segment: Segment, kind: DragKind) => void;
  tone?: string;
}) {
  const start = preview?.start ?? toSeconds(segment.start),
    end = preview?.end ?? toSeconds(segment.end);
  const colors = {
    dialogue: "border-[#6e8dab]/50 bg-[#6e8dab]/20",
    translation: "border-[#a780b8]/50 bg-[#a780b8]/20",
    voice: "border-[#c98756]/50 bg-[#c98756]/20",
    subtitle: "border-[#78a789]/50 bg-[#78a789]/20",
  } as const;
  return (
    <button
      className={`group absolute inset-y-1 overflow-hidden rounded border text-left ${colors[tone as keyof typeof colors] || colors.dialogue} ${selected ? "ring-1 ring-accent" : ""}`}
      style={{ left: start * zoom, width: Math.max(6, (end - start) * zoom) }}
      onPointerDown={(event) => {
        onSelect(event);
        onDrag(event, segment, "move");
      }}
    >
      <i
        className="absolute inset-y-0 left-0 z-10 w-1 cursor-ew-resize bg-white/20 opacity-0 group-hover:opacity-100"
        onPointerDown={(event) => onDrag(event, segment, "start")}
      />
      <span className="block truncate px-2 text-[11px] font-medium text-copy">
        {text}
      </span>
      <i
        className="absolute inset-y-0 right-0 z-10 w-1 cursor-ew-resize bg-white/20 opacity-0 group-hover:opacity-100"
        onPointerDown={(event) => onDrag(event, segment, "end")}
      />
    </button>
  );
}
function ContextInspector({
  segment,
  probe,
  analysis,
  engines,
  onEdit,
}: {
  segment: Segment | null;
  probe: MediaProbe | null;
  analysis: AnalysisState | null;
  engines: EngineRecord[];
  onEdit: (patch: Partial<Segment>) => void;
}) {
  const { t } = useI18n();
  if (segment)
    return (
      <div className="grid gap-4">
        <section>
          <span className="ui-kicker">{t("studio.selectedClip")}</span>
          <h3 className="mt-1 truncate text-[14px] font-semibold">
            {segment.speaker}
          </h3>
        </section>
        <Field label={t("studio.sourceText")}>
          <textarea
            className="ui-input min-h-24 resize-y"
            value={segment.sourceText}
            onChange={(event) => onEdit({ sourceText: event.target.value })}
          />
        </Field>
        <Field label={t("studio.translatedText")}>
          <textarea
            className="ui-input min-h-24 resize-y"
            value={segment.translatedText}
            onChange={(event) => onEdit({ translatedText: event.target.value })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t("studio.emotion")}>
            <input
              className="ui-input"
              value={segment.emotion}
              onChange={(event) => onEdit({ emotion: event.target.value })}
            />
          </Field>
          <Field label={t("studio.intensity")}>
            <input
              className="ui-input"
              type="number"
              value={segment.intensity}
              onChange={(event) =>
                onEdit({ intensity: Number(event.target.value) })
              }
            />
          </Field>
        </div>
        <div className="ui-panel grid grid-cols-2 gap-px overflow-hidden bg-line">
          <MetricSmall label="IN" value={segment.start} />
          <MetricSmall label="OUT" value={segment.end} />
        </div>
      </div>
    );
  return (
    <div className="grid gap-3">
      <section className="ui-panel p-4">
        <span className="ui-kicker">{t("studio.sourceInspector")}</span>
        <h3 className="mt-1 text-[14px] font-semibold">
          {probe?.file_name || "—"}
        </h3>
        <div className="mt-4 grid gap-3">
          <MetricLine
            label={t("studio.duration")}
            value={formatClock(probe?.duration_seconds || 0)}
          />
          <MetricLine
            label={t("studio.frame")}
            value={
              probe?.video
                ? `${probe.video.width} × ${probe.video.height}`
                : "—"
            }
          />
          <MetricLine
            label={t("studio.frameRate")}
            value={`${probe?.video?.fps || "—"} fps`}
          />
          <MetricLine
            label={t("studio.videoCodec")}
            value={probe?.video?.codec || "—"}
          />
        </div>
      </section>
      <section className="ui-panel p-4">
        <span className="ui-kicker">{t("studio.workflow")}</span>
        <div className="mt-3 grid gap-2">
          <MetricLine
            label={t("studio.scenes")}
            value={String(analysis?.segments.length || 0)}
          />
          <MetricLine
            label={t("dashboard.engines")}
            value={String(
              engines.filter((item) => item.verification.usable).length,
            )}
          />
          <div className="mt-1 flex items-center gap-2 rounded-lg border border-success/20 bg-success/5 px-3 py-2 text-[10px] text-success">
            <i className="size-1.5 rounded-full bg-success" />
            {t("common.ready")}
          </div>
        </div>
      </section>
    </div>
  );
}
function ExportInspector({
  options,
  onChange,
  plan,
  capabilities,
  advanced,
  setAdvanced,
  planning,
}: {
  options: ExportOptions;
  onChange: (value: ExportOptions) => void;
  plan: ExportPlan | null;
  capabilities: ExportCapabilities | null;
  advanced: boolean;
  setAdvanced: (value: boolean) => void;
  planning: boolean;
}) {
  const { t } = useI18n();
  const patch = (value: Partial<ExportOptions>) =>
    onChange({ ...options, ...value });
  return (
    <div data-testid="export-inspector" className="grid gap-4">
      <div
        data-testid="export-deliveries"
        className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-canvas p-1"
      >
        {(["full", "shorts", "both", "audio"] as ExportDelivery[]).map(
          (delivery) => (
            <button
              key={delivery}
              className={`rounded-md px-2 py-2 text-[10px] ${options.delivery === delivery ? "bg-raised text-foreground" : "text-muted"}`}
              onClick={() => patch({ delivery })}
            >
              {t(`export.delivery.${delivery}`)}
            </button>
          ),
        )}
      </div>
      {options.delivery !== "full" && options.delivery !== "audio" && (
        <>
          <Field label={t("export.segmentStrategy")}>
            <select
              className="ui-input"
              value={options.segment_strategy}
              onChange={(event) =>
                patch({
                  segment_strategy: event.target
                    .value as ExportOptions["segment_strategy"],
                })
              }
            >
              <option value="count">{t("export.strategy.count")}</option>
              <option value="duration">{t("export.strategy.duration")}</option>
              <option value="dialogue">{t("export.strategy.dialogue")}</option>
              <option value="manual">{t("export.strategy.manual")}</option>
            </select>
          </Field>
          {options.segment_strategy === "count" && (
            <Field label={t("export.segmentCount")}>
              <input
                className="ui-input"
                type="number"
                min={1}
                max={200}
                value={options.segment_count}
                onChange={(event) =>
                  patch({
                    segment_count: Math.max(
                      1,
                      Math.min(200, Number(event.target.value)),
                    ),
                  })
                }
              />
            </Field>
          )}
          {["duration", "dialogue"].includes(
            options.segment_strategy || "",
          ) && (
            <Field label={t("export.segmentDuration")}>
              <div className="flex items-center gap-2">
                <input
                  className="ui-input"
                  type="number"
                  min={1}
                  value={Math.round(
                    (options.segment_duration_seconds || 60) / 60,
                  )}
                  onChange={(event) =>
                    patch({
                      segment_duration_seconds:
                        Math.max(1, Number(event.target.value)) * 60,
                    })
                  }
                />
                <span className="text-[10px] text-muted">min</span>
              </div>
            </Field>
          )}
        </>
      )}
      <section className="ui-panel p-3">
        <div className="flex items-center justify-between">
          <span className="ui-kicker">{t("export.summary")}</span>
          {planning && (
            <i className="size-3 animate-spin rounded-full border border-accent border-t-transparent" />
          )}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <MetricSmall
            label={t("export.outputs")}
            value={String(plan?.output_count || 0)}
          />
          <MetricSmall
            label={t("studio.duration")}
            value={formatClock(plan?.duration_seconds || 0)}
          />
        </div>
        {plan?.warnings.map((warning) => (
          <p
            className="mt-2 rounded bg-warning/10 p-2 text-[10px] text-warning"
            key={warning}
          >
            {t(warning)}
          </p>
        ))}
      </section>
      <button
        className="ui-button w-full justify-between"
        onClick={() => setAdvanced(!advanced)}
      >
        <span className="flex items-center gap-2">
          <Settings2 />
          {t("export.advanced")}
        </span>
        <ChevronRight
          className={`transition-transform ${advanced ? "rotate-90" : ""}`}
        />
      </button>
      {advanced && (
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label={t("export.container")}>
              <select
                className="ui-input"
                value={options.container}
                onChange={(event) =>
                  patch({
                    container: event.target.value as ExportOptions["container"],
                  })
                }
              >
                {Object.keys(
                  capabilities?.containers || {
                    mp4: 1,
                    mkv: 1,
                    mov: 1,
                    webm: 1,
                  },
                ).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </Field>
            <Field label={t("export.videoCodec")}>
              <select
                className="ui-input"
                value={options.video_codec}
                onChange={(event) =>
                  patch({
                    video_codec: event.target
                      .value as ExportOptions["video_codec"],
                  })
                }
              >
                {["h264", "h265", "av1", "vp9", "prores", "copy"].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  ),
                )}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label={t("export.resolution")}>
              <select
                className="ui-input"
                value={options.resolution}
                onChange={(event) =>
                  patch({
                    resolution: event.target
                      .value as ExportOptions["resolution"],
                  })
                }
              >
                {["source", "720p", "1080p", "1440p", "2160p"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </Field>
            <Field label={t("export.aspect")}>
              <select
                className="ui-input"
                value={options.aspect}
                onChange={(event) =>
                  patch({
                    aspect: event.target.value as ExportOptions["aspect"],
                  })
                }
              >
                {["source", "16:9", "9:16", "1:1", "4:5"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="CRF">
            <input
              className="w-full accent-[var(--accent)]"
              type="range"
              min={0}
              max={51}
              value={options.quality}
              onChange={(event) =>
                patch({ quality: Number(event.target.value) })
              }
            />
            <span className="font-mono text-[10px] text-muted">
              {options.quality}
            </span>
          </Field>
          <Field label={t("export.upscale")}>
            <select
              className="ui-input"
              value={options.upscale}
              onChange={(event) =>
                patch({
                  upscale: event.target.value as ExportOptions["upscale"],
                })
              }
            >
              {["off", "standard", "ai-anime", "ai-general"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </Field>
        </div>
      )}
    </div>
  );
}
function RegionList({
  plan,
  onChange,
}: {
  plan: ExportPlan | null;
  onChange: (regions: ExportRegion[]) => void;
}) {
  const regions = plan?.regions || [];
  return (
    <div className="grid gap-1">
      {regions.map((region, index) => (
        <div
          key={region.id}
          className={`rounded-lg border p-2 ${region.enabled ? "border-line bg-raised" : "border-transparent opacity-50"}`}
        >
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={region.enabled}
              onChange={(event) =>
                onChange(
                  regions.map((item) =>
                    item.id === region.id
                      ? { ...item, enabled: event.target.checked }
                      : item,
                  ),
                )
              }
            />
            <input
              className="min-w-0 flex-1 bg-transparent text-[10px] font-medium outline-none"
              value={region.name}
              onChange={(event) =>
                onChange(
                  regions.map((item) =>
                    item.id === region.id
                      ? { ...item, name: event.target.value }
                      : item,
                  ),
                )
              }
            />
            <span className="font-mono text-[11px] text-muted">
              {formatClock(region.duration || region.end - region.start)}
            </span>
            <MoreHorizontal className="size-3 text-muted" />
          </div>
          <div className="mt-1 pl-5 font-mono text-[11px] text-muted">
            {index + 1}. {formatClock(region.start)} → {formatClock(region.end)}
          </div>
        </div>
      ))}
    </div>
  );
}
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="ui-label">{label}</span>
      {children}
    </label>
  );
}
function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line pb-2 text-[10px]">
      <span className="text-muted">{label}</span>
      <strong className="font-mono text-copy">{value}</strong>
    </div>
  );
}
function MetricSmall({ label, value }: { label: string; value: string }) {
  return (
    <span className="bg-surface p-2">
      <small className="ui-label block">{label}</small>
      <strong className="mt-1 block truncate font-mono text-[11px]">
        {value}
      </strong>
    </span>
  );
}
function toSeconds(value: string) {
  const parts = value.replace(",", ".").split(":").map(Number);
  if (parts.some(Number.isNaN)) return 0;
  return (
    (parts.at(-3) || 0) * 3600 + (parts.at(-2) || 0) * 60 + (parts.at(-1) || 0)
  );
}
function formatTime(seconds: number) {
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600),
    minutes = Math.floor((safe % 3600) / 60),
    secs = safe % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${secs.toFixed(3).padStart(6, "0")}`;
}
function formatClock(seconds: number) {
  const safe = Math.max(0, seconds || 0),
    hours = Math.floor(safe / 3600),
    minutes = Math.floor((safe % 3600) / 60),
    secs = Math.floor(safe % 60);
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}
function round(value: number) {
  return Math.round(value * 100) / 100;
}
