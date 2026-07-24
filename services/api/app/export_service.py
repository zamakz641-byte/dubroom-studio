from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class ExportCancelled(RuntimeError):
    pass


ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


CONTAINERS: dict[str, dict[str, Any]] = {
    "mp4": {"video": ["copy", "h264", "h265", "av1"], "audio": ["aac"], "extension": "mp4"},
    "mkv": {"video": ["copy", "h264", "h265", "av1", "vp9", "prores"], "audio": ["aac", "opus", "flac", "pcm"], "extension": "mkv"},
    "mov": {"video": ["copy", "h264", "h265", "prores"], "audio": ["aac", "pcm"], "extension": "mov"},
    "webm": {"video": ["vp9", "av1"], "audio": ["opus"], "extension": "webm"},
}

PRESETS: list[dict[str, Any]] = [
    {"id": "compatible", "label": "Compatible", "container": "mp4", "video_codec": "h264", "audio_codec": "aac", "quality": 19, "resolution": "source"},
    {"id": "fast-copy", "label": "Copie rapide", "container": "mp4", "video_codec": "copy", "audio_codec": "aac", "quality": 19, "resolution": "source"},
    {"id": "efficient", "label": "Haute efficacité", "container": "mp4", "video_codec": "h265", "audio_codec": "aac", "quality": 22, "resolution": "source"},
    {"id": "archive", "label": "Archive", "container": "mkv", "video_codec": "copy", "audio_codec": "flac", "quality": 18, "resolution": "source"},
    {"id": "master", "label": "Master ProRes", "container": "mov", "video_codec": "prores", "audio_codec": "pcm", "quality": 12, "resolution": "source"},
    {"id": "web", "label": "Web", "container": "webm", "video_codec": "vp9", "audio_codec": "opus", "quality": 30, "resolution": "1080p"},
]

VIDEO_ENCODERS = {
    "h264": "libx264",
    "h265": "libx265",
    "av1": "libaom-av1",
    "vp9": "libvpx-vp9",
    "prores": "prores_ks",
}

AUDIO_ENCODERS = {"aac": "aac", "opus": "libopus", "flac": "flac", "pcm": "pcm_s24le"}


def capabilities() -> dict[str, Any]:
    encoders = _ffmpeg_listing("-encoders")
    filters = _ffmpeg_listing("-filters")
    return {
        "ready": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "containers": CONTAINERS,
        "presets": PRESETS,
        "video_encoders": {
            "copy": True,
            **{codec: encoder in encoders for codec, encoder in VIDEO_ENCODERS.items()},
        },
        "audio_encoders": {codec: encoder in encoders for codec, encoder in AUDIO_ENCODERS.items()},
        "hardware": {
            "nvenc": "h264_nvenc" in encoders,
            "amf": "h264_amf" in encoders,
            "qsv": "h264_qsv" in encoders,
        },
        "filters": {name: name in filters for name in ["zscale", "scale", "crop", "pad", "loudnorm"]},
        "ai_upscale": {"installed": False, "engines": ["realesrgan-anime", "realesrgan-general"]},
    }


def normalise_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    container = str(raw.get("container", "mp4")).lower()
    if container not in CONTAINERS:
        raise ValueError(f"Unsupported container: {container}")
    video_codec = str(raw.get("video_codec", "h264")).lower()
    audio_codec = str(raw.get("audio_codec", "aac")).lower()
    if video_codec not in CONTAINERS[container]["video"]:
        raise ValueError(f"{video_codec} is not compatible with {container}")
    if audio_codec not in CONTAINERS[container]["audio"]:
        raise ValueError(f"{audio_codec} is not compatible with {container}")

    delivery = str(raw.get("delivery", "full")).lower()
    if delivery not in {"full", "shorts", "both", "audio"}:
        raise ValueError(f"Unsupported delivery type: {delivery}")
    resolution = str(raw.get("resolution", "source")).lower()
    if resolution not in {"source", "720p", "1080p", "1440p", "2160p"}:
        raise ValueError(f"Unsupported resolution: {resolution}")
    aspect = str(raw.get("aspect", "source")).lower()
    if aspect not in {"source", "16:9", "9:16", "1:1", "4:5"}:
        raise ValueError(f"Unsupported aspect ratio: {aspect}")
    framing = str(raw.get("framing", "fit")).lower()
    if framing not in {"fit", "crop", "blur"}:
        raise ValueError(f"Unsupported framing mode: {framing}")
    upscale = str(raw.get("upscale", "off")).lower()
    if upscale not in {"off", "standard", "ai-anime", "ai-general"}:
        raise ValueError(f"Unsupported upscale mode: {upscale}")
    if upscale.startswith("ai-"):
        raise ValueError("AI upscale runtime is not installed. Use Standard upscale or install the optional runtime later.")
    if video_codec == "copy" and (resolution != "source" or aspect != "source" or upscale != "off"):
        raise ValueError("Video stream copy cannot be combined with resize, reframing or upscale")

    legacy_mode = str(raw.get("short_mode", "dialogue"))
    strategy = str(raw.get("segment_strategy") or ("dialogue" if legacy_mode == "dialogue" else "duration")).lower()
    if strategy not in {"count", "duration", "dialogue", "manual"}:
        raise ValueError(f"Unsupported segment strategy: {strategy}")
    segment_count = max(1, min(200, int(raw.get("segment_count", 20))))
    segment_duration = max(1, int(raw.get("segment_duration_seconds", raw.get("short_duration", 60))))
    raw_ranges = raw.get("segment_ranges") or []
    segment_ranges: list[dict[str, Any]] = []
    if not isinstance(raw_ranges, list):
        raise ValueError("segment_ranges must be a list")
    for index, item in enumerate(raw_ranges[:200], start=1):
        if not isinstance(item, dict):
            raise ValueError("Every manual segment must be an object")
        start = max(0.0, float(item.get("start", 0)))
        end = max(0.0, float(item.get("end", 0)))
        if end <= start:
            raise ValueError(f"Manual segment {index} must end after its start")
        segment_ranges.append({
            "id": str(item.get("id") or f"region-{index:03d}"),
            "name": _safe_name(str(item.get("name") or f"Segment {index}")),
            "start": round(start, 3),
            "end": round(end, 3),
            "enabled": bool(item.get("enabled", True)),
            "framing": str(item.get("framing", framing)) if str(item.get("framing", framing)) in {"fit", "crop", "blur"} else framing,
            "position_x": max(-1.0, min(1.0, float(item.get("position_x", 0)))),
            "position_y": max(-1.0, min(1.0, float(item.get("position_y", 0)))),
            "scale": max(0.25, min(4.0, float(item.get("scale", 1)))),
        })
    if strategy == "manual" and not segment_ranges:
        raise ValueError("Manual strategy requires at least one segment range")

    raw_edit_ranges = raw.get("edit_ranges") or []
    if not isinstance(raw_edit_ranges, list):
        raise ValueError("edit_ranges must be a list")
    edit_ranges: list[dict[str, float]] = []
    for index, item in enumerate(raw_edit_ranges[:500], start=1):
        if not isinstance(item, dict):
            raise ValueError("Every edit range must be an object")
        start = max(0.0, float(item.get("source_start", item.get("start", 0))))
        end = max(0.0, float(item.get("source_end", item.get("end", 0))))
        if end <= start:
            raise ValueError(f"Edit range {index} must end after its start")
        edit_ranges.append({
            "source_start": round(start, 3),
            "source_end": round(end, 3),
        })
    if video_codec == "copy" and len(edit_ranges) > 1:
        raise ValueError("Video stream copy cannot be used with multiple timeline cuts")

    return {
        "version": 2,
        "delivery": delivery,
        "container": container,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "quality": max(0, min(51, int(raw.get("quality", 19)))),
        "preset": str(raw.get("preset", "medium")) if str(raw.get("preset", "medium")) in {"ultrafast", "veryfast", "fast", "medium", "slow"} else "medium",
        "audio_bitrate": str(raw.get("audio_bitrate", "320k")),
        "resolution": resolution,
        "aspect": aspect,
        "framing": framing,
        "upscale": upscale,
        "normalize_audio": bool(raw.get("normalize_audio", True)),
        "original_volume": max(0.0, min(2.0, float(raw.get("original_volume", 0.32)))),
        "voice_volume": max(0.0, min(2.0, float(raw.get("voice_volume", 1.0)))),
        "music_volume": max(0.0, min(2.0, float(raw.get("music_volume", 0.5)))),
        "ducking": bool(raw.get("ducking", True)),
        "music_path": str(raw.get("music_path")) if raw.get("music_path") and Path(str(raw.get("music_path"))).exists() else None,
        # Kept for older clients and persisted V1 presets.
        "short_duration": max(1, segment_duration),
        "short_mode": "dialogue" if strategy == "dialogue" else "fixed",
        "segment_strategy": strategy,
        "segment_count": segment_count,
        "segment_duration_seconds": segment_duration,
        "segment_ranges": segment_ranges,
        "edit_ranges": edit_ranges,
        "name": _safe_name(str(raw.get("name", ""))),
    }


def plan_export(
    duration_seconds: float,
    options: dict[str, Any] | None,
    segment_times: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic list of output regions without starting FFmpeg."""
    opts = normalise_options(options)
    source_duration = max(0.0, float(duration_seconds or 0))
    edit_ranges = _effective_edit_ranges(opts["edit_ranges"], source_duration)
    duration = round(sum(end - start for start, end in edit_ranges), 3)
    strategy = opts["segment_strategy"]
    dialogue_times = _remap_segment_times(segment_times or {}, edit_ranges)
    raw_regions: list[dict[str, Any]]

    if opts["delivery"] in {"full", "audio"}:
        raw_regions = [{"start": 0.0, "end": duration, "name": "Full video"}]
    elif strategy == "count":
        count = opts["segment_count"]
        if duration <= 0:
            raw_regions = []
        else:
            raw_regions = []
            for index in range(count):
                start = duration * index / count
                end = duration * (index + 1) / count
                raw_regions.append({"start": start, "end": end, "name": f"Segment {index + 1}"})
    elif strategy == "manual":
        raw_regions = [dict(item) for item in opts["segment_ranges"]]
    else:
        mode = "dialogue" if strategy == "dialogue" else "fixed"
        ranges = _short_ranges(duration, opts["segment_duration_seconds"], mode, dialogue_times)
        raw_regions = [{"start": start, "end": end, "name": f"Segment {index}"} for index, (start, end) in enumerate(ranges, start=1)]

    regions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_regions[:200], start=1):
        start = max(0.0, min(duration, float(item.get("start", 0))))
        end = max(start, min(duration, float(item.get("end", duration))))
        if end - start <= 0.001:
            continue
        regions.append({
            "id": str(item.get("id") or f"region-{index:03d}"),
            "name": _safe_name(str(item.get("name") or f"Segment {index}")),
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "enabled": bool(item.get("enabled", True)),
            "framing": str(item.get("framing", opts["framing"])),
            "position_x": float(item.get("position_x", 0)),
            "position_y": float(item.get("position_y", 0)),
            "scale": float(item.get("scale", 1)),
        })

    warnings: list[str] = []
    if len(regions) > 50:
        warnings.append("export.many_files")
    if not regions and duration <= 0:
        warnings.append("export.duration_missing")
    return {
        "version": 2,
        "strategy": strategy,
        "duration_seconds": duration,
        "output_count": sum(1 for region in regions if region["enabled"]),
        "regions": regions,
        "warnings": warnings,
        "options": opts,
    }


def execute_export(
    *,
    project_id: str,
    project_name: str,
    source_path: Path,
    output_root: Path,
    options: dict[str, Any],
    takes: list[dict[str, Any]],
    segment_times: dict[str, tuple[float, float]],
    duration_seconds: float,
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> dict[str, str]:
    opts = normalise_options(options)
    edit_ranges = _effective_edit_ranges(opts["edit_ranges"], duration_seconds)
    edited_duration = sum(end - start for start, end in edit_ranges)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_name = f"{_safe_name(project_name) or project_id}-{stamp}"
    session_dir = output_root / session_name
    session_dir.mkdir(parents=True, exist_ok=False)
    mix_path = session_dir / "dub-mix.wav"
    on_progress(2, "Preparing audio mix")
    _render_mix(source_path, mix_path, takes, segment_times, duration_seconds, opts, on_progress, is_cancelled)

    artifacts: dict[str, str] = {"folder": str(session_dir), "audio_mix": str(mix_path)}
    delivery = opts["delivery"]
    work: list[tuple[str, float, float | None]] = []
    if delivery in {"full", "both"}:
        work.append(("video", 0.0, None))
    if delivery in {"shorts", "both"}:
        plan = plan_export(duration_seconds, opts, segment_times)
        for index, region in enumerate((item for item in plan["regions"] if item["enabled"]), start=1):
            work.append((f"short_{index:03d}", region["start"], region["duration"]))
    if delivery == "audio":
        target = session_dir / f"{session_name}.{_audio_extension(opts['audio_codec'])}"
        _encode_audio_ranges(mix_path, target, opts, edit_ranges, on_progress, is_cancelled)
        artifacts["audio"] = str(target)
    else:
        total = max(1, len(work))
        for index, (key, start, length) in enumerate(work):
            suffix = "" if key == "video" else f"-{key.replace('_', '-')}"
            extension = CONTAINERS[opts["container"]]["extension"]
            target = session_dir / f"{session_name}{suffix}.{extension}"
            floor = 24 + round(index / total * 72)
            ceiling = 24 + round((index + 1) / total * 72)
            label = "Rendering full video" if key == "video" else f"Rendering {key.replace('_', ' ')}"
            source_ranges = _edited_slice_to_source_ranges(edit_ranges, start, length)
            _encode_video_ranges(source_path, mix_path, target, opts, source_ranges, edited_duration, floor, ceiling, label, on_progress, is_cancelled)
            artifacts[key] = str(target)

    manifest_path = session_dir / "export-manifest.json"
    manifest_path.write_text(json.dumps({"project_id": project_id, "created_at": datetime.now().isoformat(), "options": opts, "artifacts": artifacts}, indent=2), encoding="utf-8")
    artifacts["manifest"] = str(manifest_path)
    on_progress(100, "Export complete")
    return artifacts


def _effective_edit_ranges(raw_ranges: list[dict[str, Any]], source_duration: float) -> list[tuple[float, float]]:
    duration = max(0.0, float(source_duration or 0))
    if not raw_ranges:
        return [(0.0, duration)] if duration > 0 else []
    ranges: list[tuple[float, float]] = []
    for item in raw_ranges:
        start = max(0.0, min(duration, float(item.get("source_start", 0))))
        end = max(start, min(duration, float(item.get("source_end", duration))))
        if end - start > 0.001:
            ranges.append((start, end))
    if not ranges:
        raise ValueError("The edit timeline does not contain any renderable range")
    return ranges


def _edited_slice_to_source_ranges(
    edit_ranges: list[tuple[float, float]],
    edited_start: float,
    edited_length: float | None,
) -> list[tuple[float, float]]:
    start = max(0.0, float(edited_start or 0))
    end = float("inf") if edited_length is None else start + max(0.0, edited_length)
    cursor = 0.0
    result: list[tuple[float, float]] = []
    for source_start, source_end in edit_ranges:
        clip_length = source_end - source_start
        overlap_start = max(start, cursor)
        overlap_end = min(end, cursor + clip_length)
        if overlap_end - overlap_start > 0.001:
            mapped_start = source_start + overlap_start - cursor
            mapped_end = source_start + overlap_end - cursor
            result.append((mapped_start, mapped_end))
        cursor += clip_length
        if cursor >= end:
            break
    return result


def _remap_segment_times(
    segment_times: dict[str, tuple[float, float]],
    edit_ranges: list[tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    remapped: dict[str, tuple[float, float]] = {}
    for segment_id, (segment_start, segment_end) in segment_times.items():
        cursor = 0.0
        pieces: list[tuple[float, float]] = []
        for source_start, source_end in edit_ranges:
            overlap_start = max(segment_start, source_start)
            overlap_end = min(segment_end, source_end)
            if overlap_end - overlap_start > 0.001:
                pieces.append((
                    cursor + overlap_start - source_start,
                    cursor + overlap_end - source_start,
                ))
            cursor += source_end - source_start
        if pieces:
            remapped[segment_id] = (pieces[0][0], pieces[-1][1])
    return remapped


def _encode_video_ranges(
    source: Path,
    mix: Path,
    target: Path,
    opts: dict[str, Any],
    ranges: list[tuple[float, float]],
    edited_duration: float,
    floor: int,
    ceiling: int,
    label: str,
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> None:
    if not ranges:
        raise ValueError("The requested output does not intersect the edit timeline")
    expected = sum(end - start for start, end in ranges)
    if len(ranges) == 1:
        start, end = ranges[0]
        _encode_video(
            source,
            mix,
            target,
            opts,
            start,
            end - start,
            edited_duration,
            floor,
            ceiling,
            label,
            on_progress,
            is_cancelled,
        )
        return
    if opts["video_codec"] == "copy":
        raise ValueError("Video stream copy cannot be used with multiple timeline cuts")

    command = ["ffmpeg", "-y", "-i", str(source), "-i", str(mix)]
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, (start, end) in enumerate(ranges):
        filters.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[1:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.extend([f"[v{index}]", f"[a{index}]"])
    filters.append(
        f"{''.join(concat_inputs)}concat=n={len(ranges)}:v=1:a=1[vcat][acat]"
    )
    video_filter = _video_filter(opts)
    filters.append(
        f"[vcat]{video_filter}[vout]" if video_filter else "[vcat]null[vout]"
    )
    command.extend([
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        "[acat]",
    ])
    _video_codec_args(command, opts)
    _audio_codec_args(command, opts)
    if opts["container"] in {"mp4", "mov"}:
        command.extend(["-movflags", "+faststart"])
    command.append(str(target))
    _run_ffmpeg(command, max(expected, 1), floor, ceiling, label, on_progress, is_cancelled)


def _encode_audio_ranges(
    source: Path,
    target: Path,
    opts: dict[str, Any],
    ranges: list[tuple[float, float]],
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> None:
    if not ranges:
        raise ValueError("The edit timeline does not contain audio")
    command = ["ffmpeg", "-y", "-i", str(source)]
    filters: list[str] = []
    labels: list[str] = []
    for index, (start, end) in enumerate(ranges):
        filters.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
        labels.append(f"[a{index}]")
    filters.append(f"{''.join(labels)}concat=n={len(ranges)}:v=0:a=1[aout]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[aout]"])
    _audio_codec_args(command, opts)
    command.append(str(target))
    expected = sum(end - start for start, end in ranges)
    _run_ffmpeg(command, max(expected, 1), 25, 96, "Encoding edited audio", on_progress, is_cancelled)


def _render_mix(source: Path, target: Path, takes: list[dict[str, Any]], segment_times: dict[str, tuple[float, float]], duration: float, opts: dict[str, Any], on_progress: ProgressCallback, is_cancelled: CancelCallback) -> None:
    command = ["ffmpeg", "-y", "-i", str(source)]
    has_original_audio = _has_audio(source)
    filters = [f"[0:a]volume={opts['original_volume']}[original]"] if has_original_audio else []
    voice_inputs: list[str] = []
    for index, take in enumerate(takes, start=1):
        command.extend(["-i", str(take["path"])])
        start = segment_times.get(str(take.get("segment_id")), (0.0, 0.0))[0]
        delay = max(0, round(start * 1000))
        label = f"voice{index}"
        filters.append(f"[{index}:a]volume={opts['voice_volume']},adelay={delay}|{delay}[{label}]")
        voice_inputs.append(f"[{label}]")
    filters.append(f"{''.join(voice_inputs)}amix=inputs={len(voice_inputs)}:duration=longest:normalize=0[voices]")
    mix_inputs: list[str] = []
    if has_original_audio:
        if opts["ducking"]:
            filters.append("[original][voices]sidechaincompress=threshold=.025:ratio=8:attack=20:release=320[ambience]")
            mix_inputs.append("[ambience]")
        else:
            mix_inputs.append("[original]")
    mix_inputs.append("[voices]")
    music_path = opts.get("music_path")
    if music_path:
        music_index = len(takes) + 1
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        filters.append(f"[{music_index}:a]volume={opts['music_volume']}[music]")
        mix_inputs.append("[music]")
    filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=longest:normalize=0,apad,atrim=0:{max(duration, 0.1)}[premix]")
    if opts["normalize_audio"]:
        filters.append("[premix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        audio_map = "[aout]"
    else:
        audio_map = "[premix]"
    command.extend(["-filter_complex", ";".join(filters), "-map", audio_map, "-c:a", "pcm_s24le", str(target)])
    _run_ffmpeg(command, max(duration, 1), 3, 23, "Mixing audio", on_progress, is_cancelled)


def _encode_video(source: Path, mix: Path, target: Path, opts: dict[str, Any], start: float, length: float | None, source_duration: float, floor: int, ceiling: int, label: str, on_progress: ProgressCallback, is_cancelled: CancelCallback) -> None:
    command = ["ffmpeg", "-y"]
    if start > 0:
        command.extend(["-ss", f"{start:.3f}"])
    command.extend(["-i", str(source)])
    if start > 0:
        command.extend(["-ss", f"{start:.3f}"])
    command.extend(["-i", str(mix)])
    if length is not None:
        command.extend(["-t", f"{length:.3f}"])
    command.extend(["-map", "0:v:0", "-map", "1:a:0"])
    video_filter = _video_filter(opts)
    if video_filter:
        command.extend(["-vf", video_filter])
    _video_codec_args(command, opts)
    _audio_codec_args(command, opts)
    if opts["container"] in {"mp4", "mov"}:
        command.extend(["-movflags", "+faststart"])
    command.append(str(target))
    expected = length if length is not None else source_duration
    _run_ffmpeg(command, max(expected, 1), floor, ceiling, label, on_progress, is_cancelled)


def _encode_audio(source: Path, target: Path, opts: dict[str, Any], on_progress: ProgressCallback, is_cancelled: CancelCallback) -> None:
    command = ["ffmpeg", "-y", "-i", str(source)]
    _audio_codec_args(command, opts)
    command.append(str(target))
    _run_ffmpeg(command, 1, 25, 96, "Encoding audio", on_progress, is_cancelled)


def _video_codec_args(command: list[str], opts: dict[str, Any]) -> None:
    codec = opts["video_codec"]
    if codec == "copy":
        command.extend(["-c:v", "copy"])
        return
    encoder = VIDEO_ENCODERS[codec]
    command.extend(["-c:v", encoder])
    if codec in {"h264", "h265"}:
        command.extend(["-preset", opts["preset"], "-crf", str(opts["quality"]), "-pix_fmt", "yuv420p"])
    elif codec == "av1":
        command.extend(["-crf", str(opts["quality"]), "-b:v", "0", "-cpu-used", "6", "-pix_fmt", "yuv420p"])
    elif codec == "vp9":
        command.extend(["-crf", str(opts["quality"]), "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p"])
    elif codec == "prores":
        command.extend(["-profile:v", "3", "-pix_fmt", "yuv422p10le"])


def _audio_codec_args(command: list[str], opts: dict[str, Any]) -> None:
    codec = opts["audio_codec"]
    command.extend(["-c:a", AUDIO_ENCODERS[codec]])
    if codec in {"aac", "opus"}:
        command.extend(["-b:a", opts["audio_bitrate"]])


def _video_filter(opts: dict[str, Any]) -> str | None:
    resolution = opts["resolution"]
    aspect = opts["aspect"]
    if resolution == "source" and aspect == "source" and opts["upscale"] == "off":
        return None
    if resolution == "source":
        resolution = "1080p"
    sizes = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "2160p": (3840, 2160)}
    width, height = sizes[resolution]
    if aspect == "source":
        return f"scale=-2:{height}:flags=lanczos"
    if aspect == "9:16":
        width, height = height, width
    elif aspect == "1:1":
        width = height
    elif aspect == "4:5":
        width, height = height, round(height * 1.25 / 2) * 2
    framing = opts["framing"]
    if framing == "crop":
        return f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}"
    if framing == "blur":
        return f"split[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},boxblur=28:14[bg];[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"


def _short_ranges(duration: float, target: int, mode: str, segment_times: dict[str, tuple[float, float]]) -> list[tuple[float, float]]:
    duration = max(0.0, duration)
    if duration <= target:
        return [(0.0, duration)] if duration > 0 else []
    endings = sorted(end for _start, end in segment_times.values() if 0 < end < duration)
    ranges: list[tuple[float, float]] = []
    start = 0.0
    while start < duration - 0.25:
        ideal = min(duration, start + target)
        end = ideal
        if mode == "dialogue":
            candidates = [value for value in endings if start + 10 <= value <= min(duration, ideal + 6)]
            if candidates:
                end = min(candidates, key=lambda value: abs(value - ideal))
        if end <= start + 0.25:
            end = min(duration, start + target)
        ranges.append((start, end))
        start = end
    return ranges


def _run_ffmpeg(command: list[str], expected_duration: float, floor: int, ceiling: int, label: str, on_progress: ProgressCallback, is_cancelled: CancelCallback) -> None:
    command = [*command[:-1], "-progress", "pipe:1", "-nostats", command[-1]]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(Path(command[-1]).parent))
    tail: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line:
            tail.append(line)
            tail = tail[-30:]
        if is_cancelled():
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
            raise ExportCancelled("Export cancelled")
        if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
            try:
                seconds = int(line.split("=", 1)[1]) / 1_000_000
                fraction = min(1.0, seconds / max(expected_duration, 0.1))
                on_progress(floor + round((ceiling - floor) * fraction), label)
            except ValueError:
                pass
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg failed ({return_code}): {' | '.join(tail)[-1800:]}")
    on_progress(ceiling, label)


def _ffmpeg_listing(flag: str) -> str:
    try:
        completed = subprocess.run(["ffmpeg", "-hide_banner", flag], capture_output=True, text=True, check=False, timeout=15)
        return f"{completed.stdout}\n{completed.stderr}"
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _has_audio(path: Path) -> bool:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        return completed.returncode == 0 and "audio" in completed.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _safe_name(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value).strip(" .-")
    return re.sub(r"\s+", " ", value)[:90]


def _audio_extension(codec: str) -> str:
    return {"aac": "m4a", "opus": "opus", "flac": "flac", "pcm": "wav"}[codec]
