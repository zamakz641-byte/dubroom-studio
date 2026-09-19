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
  Upload,
  Users,
  Volume2,
  VolumeX,
  WandSparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { StudioVerticalDock } from "@/components/studio/StudioVerticalDock";
import { AudioPreservationPanel } from "@/components/studio/AudioPreservationPanel";
import { SpeakerDiarizationPanel } from "@/components/studio/SpeakerDiarizationPanel";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import type {
  AnalysisState,
  AudioPreservationState,
  DiarizationState,
  EngineRecord,
  ExportCapabilities,
  ExportDelivery,
  ExportOptions,
  ExportPlan,
  ExportRegion,
  JobRecord,
  MediaProbe,
  NarrativeProfile,
  ProjectRecord,
  Segment,
  StudioStep,
  TimelineProjectState,
  TimelineEditClip,
  TtsProfile,
  TranscriptImportPreview,
} from "@/types";

type Props = {
  project: ProjectRecord | null;
  step: StudioStep;
  onStep: (step: StudioStep) => void;
  analysis: AnalysisState | null;
  probe: MediaProbe | null;
  streamUrl: string;
  engines: EngineRecord[];
  voiceProfiles: TtsProfile[];
  jobs: JobRecord[];
  audioPreservation: AudioPreservationState | null;
  diarization: DiarizationState | null;
  onImport: () => void;
  onAnalyze: () => void;
  onSeparateAudio: (options?: { force?: boolean; profile?: "cinema" | "fast" }) => void;
  onDiarize: (force?: boolean) => void;
  onTranslate: (
    mode: "express" | "studio" | "master" | "experimental",
    narrativeProfile: NarrativeProfile,
    narrativeInstructions: string,
  ) => void;
  onGenerate: () => void;
  onExport: (options: ExportOptions) => void;
  onOpenTools: () => void;
  onSaveAnalysis: (state: AnalysisState) => void;
  onAnalysisImported: (state: AnalysisState) => void;
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
const narrativeProfileMeta: [NarrativeProfile, string][] = [
  ["natural_recap", "studio.profile.naturalRecap"],
  ["external_narrator", "studio.profile.externalNarrator"],
  ["cinematic_omniscient", "studio.profile.cinematicOmniscient"],
  ["documentary", "studio.profile.documentary"],
  ["dramatic", "studio.profile.dramatic"],
  ["dark_suspense", "studio.profile.darkSuspense"],
  ["comedic_ironic", "studio.profile.comedicIronic"],
  ["short_condensed", "studio.profile.shortCondensed"],
  ["mc_first_person", "studio.profile.mcFirstPerson"],
  ["multi_character", "studio.profile.multiCharacter"],
];
const defaultExport: ExportOptions = {
  delivery: "full",
  container: "mp4",
  video_codec: "h265",
  audio_codec: "aac",
  quality: 22,
  preset: "medium",
  audio_bitrate: "192k",
  max_output_size_gb: 0,
  hardware_acceleration: "auto",
  resolution: "source",
  aspect: "source",
  framing: "fit",
  reframe_scale: 1,
  reframe_x: 0,
  reframe_y: 0,
  upscale: "off",
  normalize_audio: true,
  audio_mastering: true,
  original_volume: 0,
  voice_volume: 1,
  music_volume: 0.85,
  ducking: true,
  subtitles_enabled: true,
  subtitle_style: "cinema",
  subtitle_position: "bottom",
  subtitle_cleanup: "none",
  subtitle_cleanup_band: 0.14,
  subtitle_subclean_mode: "lama",
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
  voiceProfiles,
  jobs,
  audioPreservation,
  diarization,
  onImport,
  onAnalyze,
  onSeparateAudio,
  onDiarize,
  onTranslate,
  onGenerate,
  onExport,
  onOpenTools,
  onSaveAnalysis,
  onAnalysisImported,
}: Props) {
  const { t } = useI18n();
  const mode = stepToMode(step);
  const isMultiSpeaker = project?.dubbing_mode === "multi";
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
  const [translationMode, setTranslationMode] =
    useState<"express" | "studio" | "master" | "experimental">("studio");
  const [sceneOpen, setSceneOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
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
  const [exchangeBusy, setExchangeBusy] = useState(false);
  const [exchangeError, setExchangeError] = useState("");
  const [exchangeNotice, setExchangeNotice] = useState("");
  const [importPath, setImportPath] = useState("");
  const [importPreview, setImportPreview] =
    useState<TranscriptImportPreview | null>(null);
  const timelineWidth = Math.max(900, duration * zoom);
  const segments = analysis?.segments || [];
  const narrativeProfile = analysis?.narrative_profile || "natural_recap";
  const narrativeInstructions = analysis?.narrative_instructions || "";
  const translatedCount = segments.filter((segment) =>
    segment.translatedText.trim(),
  ).length;
  const activeScriptJob = jobs.find(
    (job) =>
      ["asr", "translation", "diarization"].includes(job.type) &&
      ["queued", "running"].includes(job.status),
  );
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
  const focusedTracks = useMemo(() => {
    const byMode: Record<Mode, string[]> = {
      media: ["video", "original", "dialogue"],
      script: ["original", "dialogue", "translation", "subtitles"],
      cast: ["dialogue", "translation", "voices"],
      voice: ["original", "translation", "voices", "rvc"],
      mix: ["original", "voices", "rvc", "music", "subtitles"],
      export: ["video", "voices", "music", "subtitles", "markers", "regions"],
    };
    return new Set(byMode[mode]);
  }, [mode]);
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
    setExportOptions((current) => ({
      ...current,
      aspect: project.output_aspect || "source",
    }));
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
  const selectClip = (id: string, multiple: boolean) => {
    setSelected((current) =>
      multiple
        ? current.includes(id)
          ? current.filter((item) => item !== id)
          : [...current, id]
        : [id],
    );
    if (!multiple) setInspectorOpen(true);
  };
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

  const runCurrentStage = () => {
    if (mode === "media") {
      onAnalyze();
    } else if (mode === "script") {
      onTranslate(translationMode, narrativeProfile, narrativeInstructions);
    } else if (mode === "cast") {
      if (isMultiSpeaker) onDiarize();
      else onStep("voices");
    } else if (mode === "voice") {
      onGenerate();
    } else if (mode === "export") {
      onExport({
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
        segment_ranges: timelineState.export_regions,
      });
    } else {
      onOpenTools();
    }
  };
  const exportTranscriptManifest = async () => {
    if (!project || !segments.length) return;
    if (isMultiSpeaker && diarization?.status !== "ready") {
      setExchangeError(t("studio.exchange.detectSpeakersFirst"));
      return;
    }
    setExchangeBusy(true);
    setExchangeError("");
    setExchangeNotice("");
    try {
      const result = await api.exportTranscript(project.id, "manifest", 60);
      setExchangeNotice(
        t("studio.exchange.exportReady")
          .replace("{{segments}}", String(result.segment_count))
          .replace("{{files}}", String(result.files.length)),
      );
      await window.dubStudio?.revealPath(result.output_dir);
    } catch (reason) {
      setExchangeError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExchangeBusy(false);
    }
  };
  const chooseTranslatedTranscript = async () => {
    if (!project) return;
    const path = await window.dubStudio?.openTranscript();
    if (!path) return;
    setExchangeBusy(true);
    setExchangeError("");
    setExchangeNotice("");
    try {
      const preview = await api.previewTranscriptImport(project.id, path);
      setImportPath(path);
      setImportPreview(preview);
    } catch (reason) {
      setExchangeError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExchangeBusy(false);
    }
  };
  const applyTranslatedTranscript = async () => {
    if (!project || !importPreview || !importPath) return;
    setExchangeBusy(true);
    setExchangeError("");
    try {
      const result = await api.importTranscript(
        project.id,
        importPath,
        importPreview.revision,
      );
      onAnalysisImported(result.state);
      setImportPreview(null);
      setImportPath("");
      setExchangeNotice(
        t("studio.exchange.importApplied")
          .replace("{{changed}}", String(result.changed_ids.length)),
      );
      onStep("voices");
    } catch (reason) {
      setExchangeError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExchangeBusy(false);
    }
  };
  const sourceAspect =
    probe?.video?.width && probe?.video?.height
      ? probe.video.width / probe.video.height
      : 16 / 9;
  const exportAspect =
    exportOptions.aspect === "16:9"
      ? 16 / 9
      : exportOptions.aspect === "9:16"
        ? 9 / 16
        : exportOptions.aspect === "1:1"
          ? 1
          : exportOptions.aspect === "4:5"
            ? 4 / 5
            : sourceAspect;
  const monitorAspect = mode === "export" ? exportAspect : sourceAspect;
  const monitorFit: FitMode =
    mode === "export"
      ? exportOptions.framing === "crop"
        ? "fill"
        : exportOptions.framing === "blur"
          ? "blur"
          : "fit"
      : fit;
  const subtitleCropScale =
    mode === "export" && exportOptions.subtitle_cleanup === "crop"
      ? 1 / (1 - exportOptions.subtitle_cleanup_band)
      : 1;
  const monitorReframeScale =
    mode === "export"
      ? subtitleCropScale * exportOptions.reframe_scale
      : 1;
  const reframeActive =
    mode === "export" &&
    (exportOptions.subtitle_cleanup === "crop" ||
      exportOptions.reframe_scale > 1.0001);
  const monitorTransform =
    reframeActive && monitorFit !== "blur"
      ? {
          transform: `scale(${monitorReframeScale})`,
          transformOrigin: `${(exportOptions.reframe_x + 1) * 50}% ${(exportOptions.reframe_y + 1) * 50}%`,
        }
      : undefined;
  const startReframeDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!reframeActive) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const originX = event.clientX;
    const originY = event.clientY;
    const startX = exportOptions.reframe_x;
    const startY = exportOptions.reframe_y;
    const move = (pointer: PointerEvent) => {
      const x = Math.max(
        -1,
        Math.min(1, startX - ((pointer.clientX - originX) / bounds.width) * 2),
      );
      const y = Math.max(
        -1,
        Math.min(1, startY - ((pointer.clientY - originY) / bounds.height) * 2),
      );
      setExportOptions((current) => ({
        ...current,
        reframe_x: Number(x.toFixed(3)),
        reframe_y: Number(y.toFixed(3)),
      }));
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
  };

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
              onClick={() => {
                onStep(modeToStep[id]);
                if (id === "export") setInspectorOpen(true);
              }}
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
          {mode === "script" && (
            <>
              <span
                className="ui-chip hidden max-w-32 truncate 2xl:inline-flex"
                title={`${translatedCount}/${segments.length} ${t("studio.translatedSegments")}`}
              >
                {translatedCount}/{segments.length} {t("studio.results")}
              </span>
              <select
                className="ui-input h-8 w-28 py-0 text-[10px]"
                value={translationMode}
                onChange={(event) =>
                  setTranslationMode(
                    event.target.value as
                      | "express"
                      | "studio"
                      | "master"
                      | "experimental",
                  )
                }
                aria-label={t("studio.translationMode")}
              >
                <option value="express">{t("studio.translationExpress")}</option>
                <option value="studio">{t("studio.translationStudio")}</option>
                <option value="master">{t("studio.translationMaster")}</option>
                <option value="experimental">
                  {t("studio.translationExperimental")}
                </option>
              </select>
              <select
                className="ui-input h-8 w-48 py-0 text-[10px]"
                value={narrativeProfile}
                onChange={(event) => {
                  if (!analysis) return;
                  onSaveAnalysis({
                    ...analysis,
                    narrative_profile: event.target.value as NarrativeProfile,
                  });
                }}
                aria-label={t("studio.narrativeProfile")}
              >
                {narrativeProfileMeta.map(([profile, label]) => (
                  <option key={profile} value={profile}>
                    {t(label)}
                  </option>
                ))}
              </select>
              <button
                className="ui-button h-8 shrink-0 px-2"
                title={t("studio.exchange.exportManifest")}
                disabled={exchangeBusy || !segments.length}
                onClick={() => void exportTranscriptManifest()}
              >
                <Download />
                <span className="hidden 2xl:inline">
                  {t("studio.exchange.exportShort")}
                </span>
              </button>
              <button
                className="ui-button h-8 shrink-0 px-2"
                title={t("studio.exchange.importTranslated")}
                disabled={exchangeBusy || !segments.length}
                onClick={() => void chooseTranslatedTranscript()}
              >
                <Upload />
                <span className="hidden 2xl:inline">
                  {t("studio.exchange.importShort")}
                </span>
              </button>
            </>
          )}
          <button
            className="ui-button ui-button-primary h-8 shrink-0"
            onClick={runCurrentStage}
            disabled={
              Boolean(activeScriptJob) ||
              (mode === "script" && segments.length === 0)
            }
          >
            {mode === "export" ? <Download /> : <Sparkles />}
            {mode === "media"
              ? t("studio.analyze")
                : mode === "script"
                  ? activeScriptJob
                    ? `${activeScriptJob.progress}%`
                    : t("studio.translate")
                : mode === "cast"
                  ? activeScriptJob
                    ? `${activeScriptJob.progress}%`
                    : isMultiSpeaker
                      ? t("studio.diarization.detect")
                      : t("studio.singleCasting.continue")
                : mode === "voice"
                  ? t("studio.generateVoices")
                  : mode === "export"
                    ? t("export.launch")
                    : t("common.tools")}
          </button>
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

      <StudioVerticalDock
      stage={
      <main
        data-testid="studio-stage-grid"
        className="relative grid min-h-0 min-w-0 grid-cols-1 overflow-hidden"
      >
        {sceneOpen && (
          <aside className="absolute inset-y-0 left-0 z-30 flex min-h-0 w-[220px] flex-col border-r border-line bg-surface shadow-2xl">
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
                    className={`mb-1 flex w-full gap-3 rounded-lg border p-2 text-left [content-visibility:auto] [contain-intrinsic-size:auto_72px] ${selected.includes(segment.id) ? "border-accent bg-accent/5" : "border-transparent hover:bg-raised"}`}
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
              className={cn(
                "group relative mx-auto flex max-h-full max-w-full items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black shadow-2xl",
                monitorAspect < 1
                  ? "h-full w-auto"
                  : "h-auto w-full max-w-[1100px]",
              )}
              style={{ aspectRatio: monitorAspect }}
            >
              {streamUrl ? (
                <>
                  {monitorFit === "blur" && (
                    <video
                      className="absolute inset-[-5%] size-[110%] object-cover opacity-45 blur-2xl"
                      src={streamUrl}
                      muted
                    />
                  )}
                  <video
                    ref={videoRef}
                    className={`relative z-10 max-h-full max-w-full ${monitorFit === "fill" ? "size-full object-cover" : monitorFit === "actual" ? "h-auto w-auto max-w-none object-contain" : "size-full object-contain"}`}
                    style={monitorTransform}
                    src={streamUrl}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                    onEnded={() => setPlaying(false)}
                    onLoadedMetadata={() =>
                      setCurrentTime(videoRef.current?.currentTime || 0)
                    }
                  />
                  {reframeActive && monitorFit !== "blur" && (
                    <div
                      data-testid="visual-reframe-surface"
                      className="absolute inset-0 z-[15] cursor-grab touch-none active:cursor-grabbing"
                      title={t("export.reframeDrag")}
                      onPointerDown={startReframeDrag}
                    >
                      <div className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3 opacity-35">
                        {Array.from({ length: 9 }).map((_, index) => (
                          <i
                            key={index}
                            className="border-[0.5px] border-white/35"
                          />
                        ))}
                      </div>
                      <span className="pointer-events-none absolute bottom-14 left-1/2 -translate-x-1/2 rounded-full border border-white/15 bg-black/65 px-3 py-1 text-[9px] font-semibold text-white/85 backdrop-blur">
                        {t("export.reframePreview")} ·{" "}
                        {Math.round(monitorReframeScale * 100)}%
                      </span>
                    </div>
                  )}
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
                  onClick={runCurrentStage}
                >
                  {mode === "export" ? <Download /> : <Sparkles />}
                  {mode === "media"
                    ? t("studio.analyze")
                    : mode === "script"
                      ? t("studio.translate")
                      : mode === "cast"
                        ? isMultiSpeaker
                          ? t("studio.diarization.detect")
                          : t("studio.singleCasting.continue")
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
          <aside
            data-testid="studio-inspector"
            className="absolute inset-y-0 right-0 z-30 flex min-h-0 flex-col border-l border-line bg-surface shadow-2xl"
            style={{ width: inspectorWidth }}
          >
            <div
              className="absolute -left-1 top-0 z-40 h-full w-2 cursor-col-resize transition hover:bg-accent/40"
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
                className="ui-icon-button"
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
                  probe={probe}
                  plan={plan}
                  capabilities={capabilities}
                  advanced={advanced}
                  setAdvanced={setAdvanced}
                  planning={planning}
                />
              ) : mode === "media" ? (
                <AudioPreservationPanel
                  projectId={project.id}
                  state={audioPreservation}
                  job={jobs.find(
                    (item) =>
                      item.type === "audio_separation" &&
                      ["queued", "running"].includes(item.status),
                  )}
                  onSeparate={onSeparateAudio}
                />
              ) : mode === "cast" && isMultiSpeaker ? (
                <SpeakerDiarizationPanel
                  state={diarization}
                  job={jobs.find(
                    (item) =>
                      item.type === "diarization" &&
                      ["queued", "running"].includes(item.status),
                  )}
                  onDiarize={onDiarize}
                />
              ) : mode === "cast" ? (
                <section className="ui-panel p-4">
                  <small className="ui-kicker">{t("import.dubbingMode.single")}</small>
                  <strong className="mt-2 block text-[13px]">{t("studio.singleCasting.title")}</strong>
                  <p className="mt-2 text-[10px] leading-4 text-muted">{t("studio.singleCasting.body")}</p>
                  <button className="ui-button ui-button-primary mt-4" onClick={()=>onStep("voices")}>{t("studio.singleCasting.continue")}</button>
                </section>
              ) : (
                <ContextInspector
                  segment={selectedSegment}
                  probe={probe}
                  analysis={analysis}
                  engines={engines}
                  voiceProfiles={voiceProfiles}
                  projectId={project?.id || null}
                  isMultiSpeaker={isMultiSpeaker}
                  onEdit={editSegment}
                  onAnalysisEdit={(patch) => {
                    if (!analysis) return;
                    onSaveAnalysis({ ...analysis, ...patch });
                  }}
                />
              )}
            </div>
          </aside>
        )}
      </main>
      }
      timeline={
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
          <span className="ui-chip hidden shrink-0 xl:inline-flex">
            <SlidersHorizontal />
            {t(modeMeta.find(([id]) => id === mode)?.[2] || "studio.timeline")} · {focusedTracks.size}
          </span>
          <span className="mx-2 hidden h-4 w-px bg-line xl:block" />
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
            style={{
              width: timelineWidth + 160,
              minHeight: Math.max(220, 28 + focusedTracks.size * 50),
            }}
          >
            <Ruler duration={duration} zoom={zoom} />
            {focusedTracks.has("video") && <Track
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
            </Track>}
            {focusedTracks.has("original") && <Track
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
            </Track>}
            {focusedTracks.has("dialogue") && <Track
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
            </Track>}
            {focusedTracks.has("translation") && <Track
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
            </Track>}
            {focusedTracks.has("voices") && <Track
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
            </Track>}
            {focusedTracks.has("rvc") && <Track
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
            />}
            {focusedTracks.has("music") && <Track
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
            />}
            {focusedTracks.has("subtitles") && <Track
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
            </Track>}
            {focusedTracks.has("markers") && <Track
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
            </Track>}
            {focusedTracks.has("regions") && <Track
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
            </Track>}
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
      }
      />
      {(importPreview || exchangeError) && (
        <div
          className="fixed inset-0 z-[120] grid place-items-center bg-black/65 p-6 backdrop-blur-sm"
          onMouseDown={() => {
            if (!exchangeBusy) {
              setImportPreview(null);
              setExchangeError("");
            }
          }}
        >
          <section
            className="ui-panel max-h-[82vh] w-full max-w-3xl overflow-auto p-5 shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <span>
                <small className="ui-kicker">
                  {t("studio.exchange.kicker")}
                </small>
                <h2 className="mt-1 text-[17px] font-semibold">
                  {exchangeError
                    ? t("studio.exchange.validationFailed")
                    : t("studio.exchange.previewTitle")}
                </h2>
                {importPath && (
                  <p className="mt-1 max-w-xl truncate text-[10px] text-muted">
                    {importPath}
                  </p>
                )}
              </span>
              <button
                className="ui-icon-button"
                disabled={exchangeBusy}
                onClick={() => {
                  setImportPreview(null);
                  setExchangeError("");
                }}
              >
                <X />
              </button>
            </div>
            {exchangeError ? (
              <p className="mt-5 rounded-lg border border-danger/30 bg-danger/10 p-4 text-[11px] text-danger">
                {exchangeError}
              </p>
            ) : importPreview ? (
              <>
                <div className="mt-5 grid grid-cols-4 gap-2">
                  <MetricSmall
                    label={t("studio.exchange.detected")}
                    value={String(importPreview.parsed_count)}
                  />
                  <MetricSmall
                    label={t("studio.exchange.matched")}
                    value={String(importPreview.matched_count)}
                  />
                  <MetricSmall
                    label={t("studio.exchange.changed")}
                    value={String(importPreview.changed_count)}
                  />
                  <MetricSmall
                    label={t("studio.exchange.timingWarnings")}
                    value={String(importPreview.timing_warning_count)}
                  />
                </div>
                {(importPreview.fingerprint_mismatch ||
                  importPreview.duplicate_ids.length > 0 ||
                  importPreview.source_mismatch_ids.length > 0) && (
                  <p className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-[11px] text-danger">
                    {t("studio.exchange.blocked")}
                  </p>
                )}
                {importPreview.incomplete_multispeaker && (
                  <p className="mt-3 rounded-lg border border-danger/30 bg-danger/10 p-3 text-[11px] text-danger">
                    {t("studio.exchange.incompleteV3")}
                  </p>
                )}
                {[
                  ...(importPreview.invalid_character_ids || []),
                  ...(importPreview.character_conflicts || []),
                  ...(importPreview.invalid_emotion_ids || []),
                  ...(importPreview.invalid_voice_unit_ids || []),
                  ...(importPreview.invalid_bridge_ids || []),
                  ...(importPreview.invalid_registry_ids || []),
                  ...(importPreview.invalid_casting_ids || []),
                  ...(importPreview.invalid_speaker_section_ids || []),
                  ...(importPreview.missing_registry_ids || []),
                ].length > 0 && (
                  <p className="mt-3 rounded-lg border border-danger/30 bg-danger/10 p-3 text-[11px] text-danger">
                    {t("studio.exchange.invalidV3").replace(
                      "{{count}}",
                      String(
                        [
                          ...(importPreview.invalid_character_ids || []),
                          ...(importPreview.character_conflicts || []),
                          ...(importPreview.invalid_emotion_ids || []),
                          ...(importPreview.invalid_voice_unit_ids || []),
                          ...(importPreview.invalid_bridge_ids || []),
                          ...(importPreview.invalid_registry_ids || []),
                          ...(importPreview.invalid_casting_ids || []),
                          ...(importPreview.invalid_speaker_section_ids || []),
                          ...(importPreview.missing_registry_ids || []),
                        ].length,
                      ),
                    )}
                  </p>
                )}
                {importPreview.prompt_revision_mismatch && (
                  <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[11px] text-warning">
                    {t("studio.exchange.promptOld")}
                  </p>
                )}
                {importPreview.unknown_ids.length > 0 && (
                  <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[11px] text-warning">
                    {t("studio.exchange.unknownIds").replace(
                      "{{count}}",
                      String(importPreview.unknown_ids.length),
                    )}
                  </p>
                )}
                <div className="mt-5 grid gap-2">
                  {importPreview.samples.map((sample) => (
                    <article
                      key={sample.id}
                      className="grid grid-cols-[110px_1fr_1fr] gap-3 rounded-lg border border-line bg-canvas/60 p-3"
                    >
                      <span>
                        <strong className="block font-mono text-[10px] text-accent">
                          {sample.id}
                        </strong>
                        <small className="mt-1 block font-mono text-[9px] text-muted">
                          {sample.start} → {sample.end}
                        </small>
                      </span>
                      <p className="line-clamp-4 text-[10px] leading-4 text-muted">
                        {sample.source_text}
                      </p>
                      <p className="line-clamp-4 text-[10px] leading-4 text-copy">
                        {sample.target_text}
                      </p>
                    </article>
                  ))}
                </div>
                <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
                  <p className="text-[10px] text-muted">
                    {t("studio.exchange.preserveTiming")}
                  </p>
                  <span className="flex gap-2">
                    <button
                      className="ui-button"
                      disabled={exchangeBusy}
                      onClick={() => setImportPreview(null)}
                    >
                      {t("profile.cancel")}
                    </button>
                    <button
                      className="ui-button ui-button-primary"
                      disabled={exchangeBusy || !importPreview.can_apply}
                      onClick={() => void applyTranslatedTranscript()}
                    >
                      <Upload />
                      {exchangeBusy
                        ? t("studio.exchange.importing")
                        : t("studio.exchange.apply")}
                    </button>
                  </span>
                </div>
              </>
            ) : null}
          </section>
        </div>
      )}
      {exchangeNotice && (
        <button
          className="ui-panel fixed right-4 top-14 z-[110] max-w-sm border-success/30 bg-success/10 p-3 text-left text-[11px] text-success shadow-2xl"
          onClick={() => setExchangeNotice("")}
        >
          {exchangeNotice}
        </button>
      )}
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
  voiceProfiles,
  projectId,
  isMultiSpeaker,
  onEdit,
  onAnalysisEdit,
}: {
  segment: Segment | null;
  probe: MediaProbe | null;
  analysis: AnalysisState | null;
  engines: EngineRecord[];
  voiceProfiles: TtsProfile[];
  projectId: string | null;
  isMultiSpeaker: boolean;
  onEdit: (patch: Partial<Segment>) => void;
  onAnalysisEdit: (patch: Partial<AnalysisState>) => void;
}) {
  const { t } = useI18n();
  const [voiceAudioUrl, setVoiceAudioUrl] = useState("");
  const [voiceoverAudioUrl, setVoiceoverAudioUrl] = useState("");
  const selectedSpeaker = analysis?.speakers.find(
    (speaker) => speaker.name === segment?.speaker,
  );
  const compatibleVoiceProfiles = useMemo(() => {
    const targetLanguage = String(analysis?.target_language || "")
      .toLowerCase()
      .split("-", 1)[0];
    const usedByOtherSpeakers = new Set(
      (analysis?.speakers || [])
        .filter((speaker) => speaker.name !== selectedSpeaker?.name)
        .map((speaker) => speaker.voice_profile_id)
        .filter(Boolean),
    );
    return voiceProfiles
      .filter((profile) => {
        const usage = String(profile.usage_scope || "both").toLowerCase();
        if (isMultiSpeaker && !["both", "multi"].includes(usage)) return false;
        if (isMultiSpeaker && profile.multi_speaker_compatible === false) return false;
        const profileLanguage = String(profile.language || "multi")
          .toLowerCase()
          .split("-", 1)[0];
        const engineId = String(profile.default_engine || profile.preset_engine || "");
        return (
          !targetLanguage ||
          ["", "multi", targetLanguage].includes(profileLanguage) ||
          engineId === "tts-omnivoice-hq"
        );
      })
      .sort((left, right) => {
        // CASTING_R4_FINAL_PROFILE_SCORE
        const score = (profile: TtsProfile) => {
          let value = 0;
          const desiredArchetype = String(selectedSpeaker?.voice_archetype || "").toUpperCase();
          const profileArchetype = String(profile.voice_archetype || "").toUpperCase();
          if (desiredArchetype && profileArchetype === desiredArchetype) value += 1000;
          const wantedSex = String(selectedSpeaker?.sex || "").toLowerCase();
          const profileSex = String(profile.gender || "").toLowerCase();
          if (["male", "female"].includes(wantedSex) && ["male", "female"].includes(profileSex)) {
            if (wantedSex !== profileSex) return -10000;
            value += 140;
          }
          const wantedAge = String(selectedSpeaker?.age_group || "").toLowerCase();
          const profileAge = String(profile.age_group || "").toLowerCase();
          if (wantedAge && wantedAge === profileAge) value += 70;
          const wantedRole = String(selectedSpeaker?.render_voice_key || "").toLowerCase();
          const profileRole = String(profile.primary_role || "").toLowerCase();
          if (wantedRole && wantedRole === profileRole) value += 100;
          if (usedByOtherSpeakers.has(profile.id)) value -= 35;
          return value;
        };
        return score(right) - score(left) || left.name.localeCompare(right.name);
      });
  }, [analysis?.speakers, analysis?.target_language, isMultiSpeaker, selectedSpeaker?.name, selectedSpeaker?.voice_archetype, selectedSpeaker?.sex, selectedSpeaker?.age_group, selectedSpeaker?.render_voice_key, voiceProfiles]);
  const hasVoiceover = Boolean(
    analysis?.segments.some((item) => item.voiceAudioReady),
  );
  useEffect(() => {
    let active = true;
    if (!projectId || !hasVoiceover) {
      setVoiceoverAudioUrl("");
      return () => {
        active = false;
      };
    }
    void api
      .projectVoiceAudioUrl(projectId, "voiceover")
      .then((url) => active && setVoiceoverAudioUrl(url))
      .catch(() => active && setVoiceoverAudioUrl(""));
    return () => {
      active = false;
    };
  }, [projectId, hasVoiceover]);
  useEffect(() => {
    let active = true;
    if (!projectId || !segment?.voiceAudioReady) {
      setVoiceAudioUrl("");
      return () => {
        active = false;
      };
    }
    void api
      .projectVoiceAudioUrl(projectId, segment.id)
      .then((url) => active && setVoiceAudioUrl(url))
      .catch(() => active && setVoiceAudioUrl(""));
    return () => {
      active = false;
    };
  }, [projectId, segment?.id, segment?.voiceAudioReady]);

  const assignVoiceProfile = (profileId: string) => {
    if (!analysis || !selectedSpeaker) return;
    const profile = voiceProfiles.find((item) => item.id === profileId);
    onAnalysisEdit({
      speakers: analysis.speakers.map((speaker) =>
        speaker.name === selectedSpeaker.name
          ? {
              ...speaker,
              voice_profile_id: profile?.id || null,
              voice_engine:
                profile?.default_engine || profile?.preset_engine || null,
              voice_model:
                (
                  profile as (TtsProfile & { preset_voice_id?: string }) | undefined
                )?.preset_voice_id || profile?.model_size || null,
              // CASTING_R4_FINAL_MANUAL_LOCK
              voice_locked: Boolean(profile?.id),
              casting_status: profile?.id ? "locked" : speaker.casting_status,
            }
          : speaker,
      ),
    });
  };
  if (segment)
    return (
      <div className="grid gap-4">
        <section>
          <span className="ui-kicker">{t("studio.selectedClip")}</span>
          <h3 className="mt-1 truncate text-[14px] font-semibold">
            {segment.speaker}
          </h3>
          {/* CASTING_R4_FINAL_CAST_BADGES */}
          {isMultiSpeaker && selectedSpeaker && (
            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
              {selectedSpeaker.importance && <span className="ui-chip">{selectedSpeaker.importance}</span>}
              {selectedSpeaker.render_voice_key && <span className="ui-chip">{selectedSpeaker.render_voice_key}</span>}
              {selectedSpeaker.voice_archetype && <span className="ui-chip">{selectedSpeaker.voice_archetype}</span>}
              {selectedSpeaker.voice_locked && <span className="ui-chip">🔒 voix</span>}
              {selectedSpeaker.casting_status === "needs_review" && <span className="ui-chip">revue requise</span>}
            </div>
          )}
        </section>
        <Field label={t("profile.voice")}>
          <select
            className="ui-input"
            value={selectedSpeaker?.voice_profile_id || ""}
            onChange={(event) => assignVoiceProfile(event.target.value)}
          >
            <option value="">—</option>
            {compatibleVoiceProfiles.map((profile) => {
              const engineId = profile.default_engine || profile.preset_engine || "";
              const engineLabel =
                engines.find((engine) => engine.id === engineId)?.display_name || engineId || "—";
              const gender = String(profile.gender || "—");
              const role = String(profile.primary_role || profile.roles?.[0] || "—");
              const alreadyUsed = (analysis?.speakers || []).some(
                (speaker) =>
                  speaker.name !== selectedSpeaker?.name &&
                  speaker.voice_profile_id === profile.id,
              );
              return (
                <option key={profile.id} value={profile.id}>
                  {profile.name} · {(profile.language || "—").toUpperCase()} · {gender} · {role} · {engineLabel}
                  {alreadyUsed ? " · déjà utilisée" : ""}
                </option>
              );
            })}
          </select>
        </Field>
        {voiceoverAudioUrl && (
          <section className="rounded-lg border border-accent/30 bg-accent/5 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="ui-label">{t("studio.track.voices")}</span>
              <span className="ui-chip">Master</span>
            </div>
            <audio
              className="h-9 w-full"
              controls
              preload="metadata"
              src={voiceoverAudioUrl}
            />
          </section>
        )}
        {voiceAudioUrl && (
          <section className="rounded-lg border border-success/30 bg-success/5 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="ui-label">{t("studio.domain.audio")}</span>
              <span className="ui-chip">
                {segment.voiceAudioEngine || "TTS"}
                {segment.voiceAudioDuration
                  ? ` · ${segment.voiceAudioDuration.toFixed(2)} s`
                  : ""}
              </span>
            </div>
            <audio className="h-9 w-full" controls preload="metadata" src={voiceAudioUrl} />
          </section>
        )}
        <Field label={t("studio.narrativeDirection")}>
          <textarea
            className="ui-input min-h-16 resize-y"
            value={analysis?.narrative_instructions || ""}
            onChange={(event) =>
              onAnalysisEdit({ narrative_instructions: event.target.value })
            }
            placeholder={t("studio.narrativeDirectionPlaceholder")}
          />
        </Field>
        <Field label={t("studio.sourceText")}>
          <textarea
            className="ui-input min-h-24 resize-y"
            value={segment.sourceText}
            onChange={(event) => onEdit({ sourceText: event.target.value })}
          />
        </Field>
        {segment.rawTranslation && (
          <Field label={t("studio.rawTranslation")}>
            <textarea
              className="ui-input min-h-20 resize-y text-muted"
              value={segment.rawTranslation}
              readOnly
            />
          </Field>
        )}
        <Field label={t("studio.translatedText")}>
          <textarea
            className="ui-input min-h-24 resize-y"
            value={segment.translatedText}
            onChange={(event) => onEdit({ translatedText: event.target.value })}
          />
        </Field>
        {segment.fidelityScore !== null &&
          segment.fidelityScore !== undefined && (
            <section
              className={`rounded-lg border p-3 ${
                segment.fidelityScore >= 90
                  ? "border-success/30 bg-success/5"
                  : "border-warning/30 bg-warning/5"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="ui-label">{t("studio.fidelityScore")}</span>
                <strong className="font-mono text-[12px]">
                  {segment.fidelityScore}/100
                </strong>
              </div>
              {!!segment.fidelityIssues?.length && (
                <ul className="mt-2 grid gap-1 text-[10px] text-warning">
                  {segment.fidelityIssues.map((issue, index) => (
                    <li key={`${issue.type}-${index}`}>
                      {issue.type}
                      {issue.detail ? ` · ${issue.detail}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
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
            label={t("studio.narrativeProfile")}
            value={t(
              narrativeProfileMeta.find(
                ([profile]) =>
                  profile ===
                  (analysis?.narrative_profile || "natural_recap"),
              )?.[1] || "studio.profile.naturalRecap",
            )}
          />
          <MetricLine
            label={t("studio.savedRevision")}
            value={`#${analysis?.revision || 0}`}
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
  probe,
  plan,
  capabilities,
  advanced,
  setAdvanced,
  planning,
}: {
  options: ExportOptions;
  onChange: (value: ExportOptions) => void;
  probe: MediaProbe | null;
  plan: ExportPlan | null;
  capabilities: ExportCapabilities | null;
  advanced: boolean;
  setAdvanced: (value: boolean) => void;
  planning: boolean;
}) {
  const { t } = useI18n();
  const patch = (value: Partial<ExportOptions>) =>
    onChange({ ...options, ...value });
  const sourceWidth = probe?.video?.width || 0;
  const sourceHeight = probe?.video?.height || 0;
  const resolutionHeight = {
    source: sourceHeight,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "2160p": 2160,
  }[options.resolution];
  const targetHeight =
    options.aspect === "9:16"
      ? Math.round(resolutionHeight * (16 / 9))
      : options.aspect === "4:5"
        ? Math.round(resolutionHeight * 1.25)
        : resolutionHeight;
  const targetWidth =
    options.aspect === "9:16"
      ? resolutionHeight
      : options.aspect === "1:1"
        ? resolutionHeight
        : options.aspect === "4:5"
          ? resolutionHeight
          : options.aspect === "16:9"
            ? Math.round(resolutionHeight * (16 / 9))
            : sourceWidth && sourceHeight
              ? Math.round(resolutionHeight * (sourceWidth / sourceHeight))
              : 0;
  const realUpscale =
    options.upscale !== "off" &&
    Boolean(
      sourceWidth &&
        sourceHeight &&
        (targetWidth > sourceWidth || targetHeight > sourceHeight),
    );
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
      {options.delivery !== "audio" && (
        <section className="ui-panel grid gap-3 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <span className="ui-kicker">{t("export.subtitleStage")}</span>
              <p className="mt-1 text-[10px] leading-4 text-muted">
                {t("export.subtitleStageBody")}
              </p>
            </div>
            <Subtitles className="mt-0.5 size-4 text-accent" />
          </div>

          <div>
            <span className="ui-label">{t("export.oldSubtitles")}</span>
            <div className="mt-2 grid grid-cols-2 gap-1">
              {(
                [
                  ["none", "export.cleanup.none"],
                  ["blur", "export.cleanup.blur"],
                  ["crop", "export.cleanup.crop"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-md border px-2 py-2 text-left text-[10px] ${
                    options.subtitle_cleanup === value
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-line bg-canvas text-muted"
                  }`}
                  onClick={() =>
                    patch({
                      subtitle_cleanup: value,
                      ...(value === "crop" &&
                      options.subtitle_cleanup !== "crop"
                        ? { reframe_y: -1 }
                        : {}),
                    })
                  }
                >
                  {t(label)}
                </button>
              ))}
            </div>
          </div>

          {["blur", "crop"].includes(options.subtitle_cleanup) && (
            <Field label={t("export.subtitleBand")}>
              <div className="flex items-center gap-2">
                <input
                  className="min-w-0 flex-1 accent-[var(--accent)]"
                  type="range"
                  min={0.06}
                  max={0.28}
                  step={0.01}
                  value={options.subtitle_cleanup_band}
                  onChange={(event) =>
                    patch({
                      subtitle_cleanup_band: Number(event.target.value),
                    })
                  }
                />
                <span className="w-10 text-right font-mono text-[10px] text-muted">
                  {Math.round(options.subtitle_cleanup_band * 100)}%
                </span>
              </div>
            </Field>
          )}

          <div
            data-testid="visual-reframe-controls"
            className="grid gap-3 rounded-lg border border-accent/25 bg-accent/5 p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <span>
                <strong className="block text-[11px]">
                  {t("export.reframeTitle")}
                </strong>
                <small className="mt-1 block text-[9px] leading-4 text-muted">
                  {t("export.reframeBody")}
                </small>
              </span>
              <button
                type="button"
                className="ui-button h-7 px-2 text-[9px]"
                onClick={() =>
                  patch({
                    reframe_scale: 1,
                    reframe_x: 0,
                    reframe_y:
                      options.subtitle_cleanup === "crop" ? -1 : 0,
                  })
                }
              >
                {t("export.reframeReset")}
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1">
              {(
                [
                  ["fit", "export.reframe.fit"],
                  ["crop", "export.reframe.fill"],
                  ["blur", "export.reframe.blur"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-md border px-2 py-1.5 text-[9px] ${
                    options.framing === value
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-line bg-canvas text-muted"
                  }`}
                  onClick={() => patch({ framing: value })}
                >
                  {t(label)}
                </button>
              ))}
            </div>
            <Field label={t("export.reframeZoom")}>
              <div className="flex items-center gap-2">
                <input
                  data-testid="reframe-zoom"
                  className="min-w-0 flex-1 accent-[var(--accent)]"
                  type="range"
                  min={1}
                  max={2}
                  step={0.01}
                  value={options.reframe_scale}
                  onChange={(event) =>
                    patch({ reframe_scale: Number(event.target.value) })
                  }
                />
                <span className="w-10 text-right font-mono text-[10px]">
                  {Math.round(options.reframe_scale * 100)}%
                </span>
              </div>
            </Field>
            <Field label={t("export.reframeHorizontal")}>
              <input
                data-testid="reframe-x"
                className="w-full accent-[var(--accent)]"
                type="range"
                min={-1}
                max={1}
                step={0.01}
                value={options.reframe_x}
                onChange={(event) =>
                  patch({ reframe_x: Number(event.target.value) })
                }
              />
            </Field>
            <Field label={t("export.reframeVertical")}>
              <input
                data-testid="reframe-y"
                className="w-full accent-[var(--accent)]"
                type="range"
                min={-1}
                max={1}
                step={0.01}
                value={options.reframe_y}
                onChange={(event) =>
                  patch({ reframe_y: Number(event.target.value) })
                }
              />
            </Field>
            <small className="text-[9px] leading-4 text-copy">
              {t("export.reframeDrag")}
            </small>
          </div>

          <div className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-canvas p-2 text-[9px]">
            <span className="text-muted">{t("export.cleanupMethod")}</span>
            <span className="text-muted">{t("export.cleanupSpeed")}</span>
            <span className="text-muted">{t("export.cleanupQuality")}</span>
            <strong>{t("export.cleanup.cropShort")}</strong>
            <span className="text-success">★★★★★</span>
            <span>★★★☆☆</span>
            <strong>{t("export.cleanup.blurShort")}</strong>
            <span className="text-success">★★★★☆</span>
            <span>★★★☆☆</span>
            <strong>SubClean</strong>
            <span className="text-warning">★☆☆☆☆</span>
            <span className="text-success">★★★★★</span>
          </div>

          <button
            type="button"
            aria-pressed={options.subtitles_enabled}
            className={`flex items-center justify-between rounded-lg border px-3 py-2 text-left text-[11px] ${
              options.subtitles_enabled
                ? "border-accent/50 bg-accent/10"
                : "border-line bg-canvas text-muted"
            }`}
            onClick={() =>
              patch({ subtitles_enabled: !options.subtitles_enabled })
            }
          >
            <span>{t("export.addOurSubtitles")}</span>
            <span
              className={`h-4 w-7 rounded-full p-0.5 ${
                options.subtitles_enabled ? "bg-accent" : "bg-line"
              }`}
            >
              <span
                className={`block size-3 rounded-full bg-white transition-transform ${
                  options.subtitles_enabled ? "translate-x-3" : ""
                }`}
              />
            </span>
          </button>

          {options.subtitles_enabled && (
            <>
              <div>
                <span className="ui-label">{t("export.subtitleStyle")}</span>
                <div className="mt-2 grid grid-cols-2 gap-1">
                  {(
                    [
                      ["cinema", "export.style.cinema"],
                      ["social", "export.style.social"],
                      ["minimal", "export.style.minimal"],
                      ["manga", "export.style.manga"],
                      ["documentary", "export.style.documentary"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={`rounded-md border px-2 py-2 text-left text-[10px] ${
                        options.subtitle_style === value
                          ? "border-accent bg-accent/10"
                          : "border-line bg-canvas text-muted"
                      }`}
                      onClick={() => patch({ subtitle_style: value })}
                    >
                      {t(label)}
                    </button>
                  ))}
                </div>
              </div>
              <Field label={t("export.subtitlePosition")}>
                <select
                  className="ui-input"
                  value={options.subtitle_position}
                  onChange={(event) =>
                    patch({
                      subtitle_position: event.target
                        .value as ExportOptions["subtitle_position"],
                    })
                  }
                >
                  <option value="bottom">{t("export.position.bottom")}</option>
                  <option value="top">{t("export.position.top")}</option>
                </select>
              </Field>
            </>
          )}
        </section>
      )}
      {options.delivery !== "audio" && (
        <section className="ui-panel grid gap-3 p-3">
          <div>
            <span className="ui-kicker">{t("export.videoEnhance")}</span>
            <p className="mt-1 text-[10px] leading-4 text-muted">
              {t("export.videoEnhanceBody")}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-1">
            {(
              [
                ["off", "export.enhance.off"],
                ["standard", "export.enhance.standard"],
                ["clarity", "export.enhance.clarity"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`rounded-md border px-2 py-2 text-[10px] ${
                  options.upscale === value
                    ? "border-accent bg-accent/10 text-foreground"
                    : "border-line bg-canvas text-muted"
                }`}
                onClick={() =>
                  patch({
                    upscale: value,
                    resolution:
                      value !== "off" && options.resolution === "source"
                        ? "1080p"
                        : options.resolution,
                  })
                }
              >
                {t(label)}
              </button>
            ))}
          </div>
          {options.upscale !== "off" && (
            <Field label={t("export.enhanceResolution")}>
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
                <option value="1080p">1080p</option>
                <option value="1440p">1440p</option>
                <option value="2160p">2160p</option>
              </select>
            </Field>
          )}
          {options.upscale !== "off" && sourceWidth > 0 && sourceHeight > 0 && (
            <div
              data-testid="upscale-status"
              className={`rounded-lg border px-3 py-2 text-[9px] leading-4 ${
                realUpscale
                  ? "border-success/25 bg-success/5 text-success"
                  : "border-warning/25 bg-warning/5 text-warning"
              }`}
            >
              <strong className="block">
                {realUpscale
                  ? t("export.upscaleActive")
                  : t("export.upscaleNotNeeded")}
              </strong>
              <span className="font-mono">
                {sourceWidth}×{sourceHeight} → {targetWidth}×{targetHeight}
              </span>
            </div>
          )}
          <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded-lg border border-line bg-canvas p-2 text-[9px]">
            <span>{t("export.enhance.standard")}</span>
            <strong className="text-success">≈ 7.9× temps réel</strong>
            <span>{t("export.enhance.clarity")}</span>
            <strong className="text-warning">≈ 5.8× temps réel</strong>
          </div>
        </section>
      )}
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
                onChange={(event) => {
                  const container = event.target
                    .value as ExportOptions["container"];
                  const compatible = capabilities?.containers?.[container];
                  patch({
                    container,
                    video_codec:
                      compatible?.video.includes(options.video_codec)
                        ? options.video_codec
                        : compatible?.video[0] || options.video_codec,
                    audio_codec:
                      compatible?.audio.includes(options.audio_codec)
                        ? options.audio_codec
                        : compatible?.audio[0] || options.audio_codec,
                  });
                }}
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
              {["off", "standard", "clarity"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label={t("export.audioCodec")}>
              <select
                className="ui-input"
                value={options.audio_codec}
                onChange={(event) =>
                  patch({
                    audio_codec: event.target
                      .value as ExportOptions["audio_codec"],
                  })
                }
              >
                {(
                  capabilities?.containers?.[options.container]?.audio || [
                    "aac",
                  ]
                ).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </Field>
            <Field label={t("export.audioBitrate")}>
              <select
                className="ui-input"
                value={options.audio_bitrate}
                disabled={["flac", "pcm"].includes(options.audio_codec)}
                onChange={(event) =>
                  patch({ audio_bitrate: event.target.value })
                }
              >
                {["192k", "256k", "320k"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label={t("export.maxOutputSize")}>
            <div className="flex items-center gap-2">
              <input
                className="ui-input"
                type="number"
                min={0}
                max={20}
                step={0.5}
                value={options.max_output_size_gb}
                onChange={(event) =>
                  patch({
                    max_output_size_gb: Math.max(
                      0,
                      Math.min(20, Number(event.target.value) || 0),
                    ),
                  })
                }
              />
              <span className="whitespace-nowrap text-xs text-muted">
                {options.max_output_size_gb > 0 ? "GB" : t("export.sizeAutomatic")}
              </span>
            </div>
          </Field>
          <Field label={t("export.hardwareAcceleration")}>
            <select
              className="ui-input"
              value={options.hardware_acceleration}
              onChange={(event) =>
                patch({
                  hardware_acceleration: event.target
                    .value as ExportOptions["hardware_acceleration"],
                })
              }
            >
              <option value="auto">
                {t("export.hardwareAuto")}
                {capabilities?.hardware.nvenc ? " · RTX/NVENC" : ""}
              </option>
              <option
                value="nvenc"
                disabled={!capabilities?.hardware.nvenc}
              >
                {t("export.hardwareNvenc")}
              </option>
              <option value="cpu">{t("export.hardwareCpu")}</option>
            </select>
          </Field>
          <div className="grid gap-3 rounded-lg border border-line bg-canvas p-3">
            {(
              [
                ["voice_volume", "export.voiceVolume"],
                ["original_volume", "export.originalVolume"],
                ["music_volume", "export.musicVolume"],
              ] as const
            ).map(([key, label]) => (
              <Field key={key} label={t(label)}>
                <div className="flex items-center gap-2">
                  <input
                    className="min-w-0 flex-1 accent-[var(--accent)]"
                    type="range"
                    min={0}
                    max={key === "voice_volume" ? 1.5 : 1}
                    step={0.05}
                    value={options[key]}
                    onChange={(event) =>
                      patch({ [key]: Number(event.target.value) })
                    }
                  />
                  <span className="w-9 text-right font-mono text-[10px] text-muted">
                    {Math.round(options[key] * 100)}%
                  </span>
                </div>
              </Field>
            ))}
          </div>
          <div className="grid gap-2">
            {(
              [
                ["audio_mastering", "export.audioMastering"],
                ["normalize_audio", "export.normalizeAudio"],
                ["ducking", "export.ducking"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={options[key]}
                className={`flex items-center justify-between rounded-lg border px-3 py-2 text-left text-[11px] transition-colors ${
                  options[key]
                    ? "border-accent/50 bg-accent/10 text-foreground"
                    : "border-line bg-canvas text-muted"
                }`}
                onClick={() => patch({ [key]: !options[key] })}
              >
                <span>{t(label)}</span>
                <span
                  className={`h-4 w-7 rounded-full p-0.5 transition-colors ${
                    options[key] ? "bg-accent" : "bg-line"
                  }`}
                >
                  <span
                    className={`block size-3 rounded-full bg-white transition-transform ${
                      options[key] ? "translate-x-3" : ""
                    }`}
                  />
                </span>
              </button>
            ))}
            <p className="text-[10px] leading-4 text-muted">
              {t("export.audioMasteringBody")}
            </p>
          </div>
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
