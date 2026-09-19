from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unicodedata
from functools import lru_cache
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
    {"id": "compatible", "label": "Compatibilité maximale", "container": "mp4", "video_codec": "h264", "audio_codec": "aac", "quality": 19, "resolution": "1080p", "audio_bitrate": "192k", "compatibility_mode": True, "max_fps": 30},
    {"id": "balanced", "label": "YouTube haute qualité", "container": "mp4", "video_codec": "h264", "audio_codec": "aac", "quality": 18, "resolution": "source", "audio_bitrate": "256k", "hardware_acceleration": "auto"},
    {"id": "fast-copy", "label": "Copie rapide", "container": "mp4", "video_codec": "copy", "audio_codec": "aac", "quality": 19, "resolution": "source", "audio_bitrate": "256k"},
    {"id": "efficient", "label": "Haute efficacité", "container": "mp4", "video_codec": "h265", "audio_codec": "aac", "quality": 22, "resolution": "source", "audio_bitrate": "192k"},
    {"id": "archive", "label": "Archive", "container": "mkv", "video_codec": "copy", "audio_codec": "flac", "quality": 18, "resolution": "source", "keep_intermediate_audio": True},
    {"id": "master", "label": "Master ProRes (très volumineux)", "container": "mov", "video_codec": "prores", "audio_codec": "pcm", "quality": 12, "resolution": "source", "master_export": True, "keep_intermediate_audio": True},
    {"id": "web", "label": "Web", "container": "webm", "video_codec": "vp9", "audio_codec": "opus", "quality": 30, "resolution": "1080p", "audio_bitrate": "192k"},
]

VIDEO_ENCODERS = {
    "h264": "libx264",
    "h265": "libx265",
    "av1": "libaom-av1",
    "vp9": "libvpx-vp9",
    "prores": "prores_ks",
}

AUDIO_ENCODERS = {"aac": "aac", "opus": "libopus", "flac": "flac", "pcm": "pcm_s24le"}
AUDIO_MASTER_SAMPLE_RATE = 48000
DEFAULT_DELIVERY_SIZE_LIMIT_BYTES = 4_000_000_000
SIZE_LIMIT_SAFETY_RATIO = 0.92
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
MANAGED_FFMPEG_BIN = WORKSPACE_ROOT / "data" / "tools" / "ffmpeg" / "bin"
NVENC_ENCODERS = {
    "h264": "h264_nvenc",
    "h265": "hevc_nvenc",
    "av1": "av1_nvenc",
}


QUALITY_LIMITS = {
    "h264": (16, 35),
    "h265": (18, 38),
    "av1": (18, 45),
    "vp9": (18, 50),
}


def _normalise_quality(codec: str, value: Any, *, allow_lossless: bool) -> int:
    try:
        quality = int(value)
    except (TypeError, ValueError):
        quality = 19 if codec == "h264" else 22
    quality = max(0, min(51, quality))
    if allow_lossless or codec not in QUALITY_LIMITS:
        return quality
    minimum, maximum = QUALITY_LIMITS[codec]
    return max(minimum, min(maximum, quality))


def _normalise_audio_bitrate(value: Any, *, fallback: str) -> str:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", str(value or ""))
    if not match:
        return fallback
    amount = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        amount *= 1000.0
    elif not unit and amount > 2000:
        amount /= 1000.0
    kbps = max(64, min(512, round(amount)))
    return f"{kbps}k"


def _audio_bitrate_kbps(value: str) -> int:
    match = re.fullmatch(r"(\d+)k", str(value or ""))
    return int(match.group(1)) if match else 192


def _estimate_output_size(
    duration_seconds: float,
    opts: dict[str, Any],
    *,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
) -> dict[str, Any]:
    """Return a conservative delivery-size estimate, not a fake precise promise."""
    duration = max(0.0, float(duration_seconds or 0.0))
    codec = str(opts.get("video_codec") or "h264")
    if duration <= 0:
        return {"estimated": False, "reason": "duration_missing"}
    if codec == "copy":
        return {"estimated": False, "reason": "stream_copy_depends_on_source"}

    pixels_factor = max(0.20, (max(16, width) * max(16, height)) / (1920 * 1080))
    fps_factor = max(0.50, min(4.0, max(1.0, fps) / 30.0))
    quality = int(opts.get("quality") or 19)
    base_kbps = {
        "h264": 8000.0,
        "h265": 5000.0,
        "av1": 4000.0,
        "vp9": 6000.0,
        "prores": 180000.0,
    }.get(codec, 8000.0)
    if codec == "prores":
        video_kbps = base_kbps * pixels_factor * fps_factor
    else:
        reference = 19 if codec == "h264" else 22
        quality_factor = 2 ** ((reference - quality) / 6.0)
        video_kbps = base_kbps * pixels_factor * fps_factor * quality_factor
        video_kbps = max(700.0, min(80000.0, video_kbps))
    audio_kbps = (
        2304
        if str(opts.get("audio_codec")) == "pcm"
        else _audio_bitrate_kbps(str(opts.get("audio_bitrate") or "192k"))
    )
    middle = duration * (video_kbps + audio_kbps) * 1000 / 8
    return {
        "estimated": True,
        "minimum_bytes": round(middle * 0.65),
        "likely_bytes": round(middle),
        "maximum_bytes": round(middle * 1.45),
        "assumed_video_kbps": round(video_kbps),
        "assumed_audio_kbps": audio_kbps,
    }


def _output_size_budget(duration_seconds: float, opts: dict[str, Any]) -> dict[str, Any]:
    """Calculate a conservative video bitrate that stays below the delivery cap."""
    duration = max(0.0, float(duration_seconds or 0.0))
    limit_bytes = max(0, int(opts.get("max_output_size_bytes") or 0))
    if duration <= 0 or limit_bytes <= 0 or opts.get("master_export"):
        return {"enabled": False}
    estimate = _estimate_output_size(
        duration,
        opts,
        width=int(opts.get("_source_width") or 1920),
        height=int(opts.get("_source_height") or 1080),
        fps=float(opts.get("_target_fps") or opts.get("_source_fps") or 30.0),
    )
    if estimate.get("estimated") and int(estimate.get("maximum_bytes") or 0) <= int(
        limit_bytes * 0.95
    ):
        return {
            "enabled": False,
            "within_limit_without_bitrate_cap": True,
            "limit_bytes": limit_bytes,
            "estimated_maximum_bytes": int(estimate["maximum_bytes"]),
        }
    audio_kbps = (
        2304
        if str(opts.get("audio_codec")) == "pcm"
        else _audio_bitrate_kbps(str(opts.get("audio_bitrate") or "192k"))
    )
    total_kbps = limit_bytes * 8 / duration / 1000
    # Reserve room for muxing overhead, metadata, subtitle packets and encoder
    # variance. A retry guard after encoding enforces the absolute limit.
    video_kbps = max(350, int(total_kbps * SIZE_LIMIT_SAFETY_RATIO - audio_kbps))
    return {
        "enabled": True,
        "limit_bytes": limit_bytes,
        "duration_seconds": round(duration, 3),
        "audio_kbps": audio_kbps,
        "video_kbps": video_kbps,
        "maxrate_kbps": max(video_kbps, round(video_kbps * 1.06)),
        "bufsize_kbps": max(video_kbps * 2, 1000),
        "safety_ratio": SIZE_LIMIT_SAFETY_RATIO,
    }


def _options_with_output_size_budget(
    opts: dict[str, Any],
    duration_seconds: float,
) -> dict[str, Any]:
    rendered = {**opts}
    budget = _output_size_budget(duration_seconds, rendered)
    rendered["_output_size_budget"] = budget
    if budget.get("enabled"):
        rendered["_target_video_bitrate_kbps"] = int(budget["video_kbps"])
        rendered["_target_video_maxrate_kbps"] = int(budget["maxrate_kbps"])
        rendered["_target_video_bufsize_kbps"] = int(budget["bufsize_kbps"])
    return rendered


def _delivery_size_estimate(
    duration_seconds: float,
    opts: dict[str, Any],
    *,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
) -> dict[str, Any]:
    estimate = _estimate_output_size(
        duration_seconds,
        opts,
        width=width,
        height=height,
        fps=fps,
    )
    budget_opts = {
        **opts,
        "_source_width": width,
        "_source_height": height,
        "_source_fps": fps,
    }
    budget = _output_size_budget(duration_seconds, budget_opts)
    if budget.get("enabled"):
        limit = int(budget["limit_bytes"])
        estimate.update(
            {
                "size_capped": True,
                "size_limit_bytes": limit,
                "likely_bytes": min(
                    int(estimate.get("likely_bytes") or limit),
                    round(limit * SIZE_LIMIT_SAFETY_RATIO),
                ),
                "maximum_bytes": limit,
                "assumed_video_kbps": int(budget["video_kbps"]),
                "assumed_audio_kbps": int(budget["audio_kbps"]),
            }
        )
    elif budget.get("limit_bytes"):
        estimate.update(
            {
                "size_capped": False,
                "size_limit_bytes": int(budget["limit_bytes"]),
            }
        )
    return estimate


def _media_tool(name: str) -> str:
    executable = f"{name}.exe" if os.name == "nt" else name
    managed = MANAGED_FFMPEG_BIN / executable
    if managed.is_file():
        return str(managed)
    resolved = shutil.which(executable) or shutil.which(name)
    return resolved or name

def _nvenc_ffmpeg() -> str:
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    managed = MANAGED_FFMPEG_BIN / executable
    return str(managed) if managed.is_file() else _media_tool("ffmpeg")


def _video_ffmpeg(opts: dict[str, Any]) -> str:
    codec = str(opts.get("video_codec") or "")
    requested = str(opts.get("hardware_acceleration") or "auto")
    if requested != "cpu" and codec in NVENC_ENCODERS and _nvenc_available(codec):
        return _nvenc_ffmpeg()
    return _media_tool("ffmpeg")


def capabilities() -> dict[str, Any]:
    encoders = _ffmpeg_listing("-encoders")
    filters = _ffmpeg_listing("-filters")
    return {
        "ready": Path(_media_tool("ffmpeg")).is_file() and Path(_media_tool("ffprobe")).is_file(),
        "containers": CONTAINERS,
        "presets": PRESETS,
        "video_encoders": {
            "copy": True,
            **{codec: encoder in encoders for codec, encoder in VIDEO_ENCODERS.items()},
        },
        "audio_encoders": {codec: encoder in encoders for codec, encoder in AUDIO_ENCODERS.items()},
        "hardware": {
            "nvenc": _nvenc_available("h264"),
            "amf": "h264_amf" in encoders,
            "qsv": "h264_qsv" in encoders,
        },
        "filters": {
            name: name in filters
            for name in [
                "zscale",
                "scale",
                "crop",
                "pad",
                "loudnorm",
                "acompressor",
                "alimiter",
                "aresample",
                "highpass",
            ]
        },
        "ai_upscale": {"installed": False, "engines": ["realesrgan-anime", "realesrgan-general"]},
    }


def normalise_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    safety_adjustments: list[str] = []
    size_profile = str(raw.get("size_profile") or "balanced").strip().lower()
    if size_profile not in {"balanced", "compact", "ultra_compact", "master"}:
        size_profile = "balanced"
    master_export = bool(raw.get("master_export", False))
    allow_lossless = bool(raw.get("allow_lossless", False))
    container = str(raw.get("container", "mp4")).lower()
    video_codec = str(raw.get("video_codec", "h264")).lower()
    audio_codec = str(raw.get("audio_codec", "aac")).lower()
    requested_resolution = str(raw.get("resolution", "source")).lower()
    if video_codec == "copy" and requested_resolution != "source":
        raise ValueError("Video stream copy cannot resize the source")
    # A numeric delivery ceiling is optional. The default is quality-first CRF
    # encoding, which normally makes H.265 deliveries smaller without forcing
    # a long or already-compressed source into an arbitrary file size.
    raw_size_limit = raw.get("max_output_size_gb", 0.0)
    try:
        max_output_size_gb = max(0.0, min(100.0, float(raw_size_limit or 0.0)))
    except (TypeError, ValueError):
        max_output_size_gb = 0.0
    max_output_size_bytes = (
        int(max_output_size_gb * 1_000_000_000)
        if max_output_size_gb > 0 and not master_export
        else 0
    )
    if video_codec == "copy" and max_output_size_bytes:
        video_codec = "h265"
        container = "mp4"
        audio_codec = "aac"
        safety_adjustments.append("stream_copy_replaced_to_enforce_size_limit")
    if size_profile in {"compact", "ultra_compact"} and not master_export:
        container = "mp4"
        video_codec = "h265"
        audio_codec = "aac"
        safety_adjustments.append(f"{size_profile}_youtube_hevc_preset")

    # ProRes and PCM are mastering formats. They are the usual reason a normal
    # delivery suddenly becomes tens of gigabytes. Require the explicit master
    # preset; otherwise recover to a safe YouTube-ready MP4 instead of silently
    # producing a storage disaster.
    if (video_codec == "prores" or audio_codec == "pcm") and not master_export:
        safety_adjustments.append("master_codecs_replaced_with_h264_aac")
        container = "mp4"
        video_codec = "h264"
        audio_codec = "aac"

    if container not in CONTAINERS:
        raise ValueError(f"Unsupported container: {container}")
    if video_codec not in CONTAINERS[container]["video"]:
        raise ValueError(f"{video_codec} is not compatible with {container}")
    if audio_codec not in CONTAINERS[container]["audio"]:
        raise ValueError(f"{audio_codec} is not compatible with {container}")

    compatibility_mode = bool(raw.get("compatibility_mode", False))
    hardware_acceleration = str(raw.get("hardware_acceleration", "auto")).lower()
    if hardware_acceleration not in {"auto", "nvenc", "cpu"}:
        hardware_acceleration = "auto"
    max_fps = max(0.0, min(120.0, float(raw.get("max_fps", 30 if compatibility_mode else 0) or 0)))
    if compatibility_mode:
        # A real compatibility preset must not merely wear a reassuring label.
        container = "mp4"
        video_codec = "h264"
        audio_codec = "aac"

    delivery = str(raw.get("delivery", "full")).lower()
    if delivery not in {"full", "shorts", "both", "audio"}:
        raise ValueError(f"Unsupported delivery type: {delivery}")
    resolution = str(raw.get("resolution", "source")).lower()
    if resolution not in {"source", "720p", "1080p", "1440p", "2160p"}:
        raise ValueError(f"Unsupported resolution: {resolution}")
    if compatibility_mode:
        resolution = "1080p"
    aspect = str(raw.get("aspect", "source")).lower()
    if aspect not in {"source", "16:9", "9:16", "1:1", "4:5"}:
        raise ValueError(f"Unsupported aspect ratio: {aspect}")
    framing = str(raw.get("framing", "fit")).lower()
    if framing not in {"fit", "crop", "blur"}:
        raise ValueError(f"Unsupported framing mode: {framing}")
    reframe_scale = max(1.0, min(3.0, float(raw.get("reframe_scale", 1.0) or 1.0)))
    reframe_x = max(-1.0, min(1.0, float(raw.get("reframe_x", 0.0) or 0.0)))
    reframe_default_y = (
        -1.0 if str(raw.get("subtitle_cleanup", "none")).lower() == "crop" else 0.0
    )
    reframe_y = max(
        -1.0,
        min(1.0, float(raw.get("reframe_y", reframe_default_y))),
    )
    upscale = str(raw.get("upscale", "off")).lower()
    if upscale not in {"off", "standard", "clarity", "ai-anime", "ai-general"}:
        raise ValueError(f"Unsupported upscale mode: {upscale}")
    if upscale.startswith("ai-"):
        raise ValueError("AI upscale runtime is not installed. Use Standard upscale or install the optional runtime later.")
    if video_codec == "copy" and (
        resolution != "source"
        or aspect != "source"
        or upscale != "off"
        or reframe_scale > 1.0001
        or abs(reframe_x) > 0.0001
        or abs(reframe_y) > 0.0001
    ):
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

    subtitle_style = str(raw.get("subtitle_style", "cinema")).lower()
    if subtitle_style not in {"cinema", "social", "minimal", "manga", "documentary"}:
        subtitle_style = "cinema"
    subtitle_position = str(raw.get("subtitle_position", "bottom")).lower()
    if subtitle_position not in {"bottom", "top"}:
        subtitle_position = "bottom"
    subtitle_cleanup = str(raw.get("subtitle_cleanup", "none")).lower()
    if subtitle_cleanup not in {"none", "auto", "blur", "crop", "subclean"}:
        subtitle_cleanup = "none"
    subtitle_subclean_mode = str(raw.get("subtitle_subclean_mode", "lama")).lower()
    if subtitle_subclean_mode not in {"sttn-auto", "sttn-det", "lama", "propainter", "opencv"}:
        subtitle_subclean_mode = "lama"
    subtitles_enabled = bool(raw.get("subtitles_enabled", False))
    subtitle_cleanup_band = max(
        0.06,
        min(0.28, float(raw.get("subtitle_cleanup_band", 0.14) or 0.14)),
    )
    if video_codec == "copy" and (
        subtitles_enabled or subtitle_cleanup in {"auto", "blur", "crop"}
    ):
        raise ValueError(
            "Video stream copy cannot add or clean subtitles. Select H.264, H.265 or another encoded video format."
        )

    profile_quality = 25 if size_profile == "compact" else 28 if size_profile == "ultra_compact" else None
    requested_quality = (
        raw.get("quality", 19 if video_codec == "h264" else 22)
        if profile_quality is None or bool(raw.get("custom_quality", False))
        else profile_quality
    )
    quality = _normalise_quality(
        video_codec,
        requested_quality,
        allow_lossless=allow_lossless and master_export,
    )
    try:
        if int(requested_quality) != quality:
            safety_adjustments.append(f"quality_clamped_to_{quality}")
    except (TypeError, ValueError):
        safety_adjustments.append(f"quality_reset_to_{quality}")
    default_audio_bitrate = (
        "160k"
        if size_profile == "ultra_compact"
        else "192k"
        if size_profile == "compact" or compatibility_mode
        else "256k"
    )
    audio_bitrate = _normalise_audio_bitrate(
        raw.get("audio_bitrate", default_audio_bitrate),
        fallback=default_audio_bitrate,
    )

    return {
        "version": 3,
        # Internal role marker supplied by the project pipeline after replacing
        # source dialogue with a dialogue-free music/SFX preservation bed.
        "_source_audio_is_bed": bool(raw.get("_source_audio_is_bed", False)),
        "size_profile": size_profile,
        "max_output_size_gb": max_output_size_gb,
        "max_output_size_bytes": max_output_size_bytes,
        "delivery": delivery,
        "container": container,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "quality": quality,
        "preset": str(raw.get("preset", "fast" if size_profile in {"compact", "ultra_compact"} else "medium")) if str(raw.get("preset", "fast" if size_profile in {"compact", "ultra_compact"} else "medium")) in {"ultrafast", "veryfast", "fast", "medium", "slow"} else "medium",
        "audio_bitrate": audio_bitrate,
        "master_export": master_export,
        "allow_lossless": allow_lossless and master_export,
        "keep_intermediate_audio": bool(raw.get("keep_intermediate_audio", False)),
        "safety_adjustments": safety_adjustments,
        "compatibility_mode": compatibility_mode,
        "hardware_acceleration": hardware_acceleration,
        "max_fps": max_fps,
        "resolution": resolution,
        "aspect": aspect,
        "framing": framing,
        "reframe_scale": reframe_scale,
        "reframe_x": reframe_x,
        "reframe_y": reframe_y,
        "upscale": upscale,
        "normalize_audio": bool(raw.get("normalize_audio", True)),
        "audio_mastering": bool(raw.get("audio_mastering", True)),
        # A dubbed export must not silently fall back to the source dialogue.
        # Users can deliberately raise this when the source is an ambience or
        # music stem, but the safe default is complete dialogue replacement.
        "original_volume": max(0.0, min(2.0, float(raw.get("original_volume", 0.0)))),
        "voice_volume": max(0.0, min(2.0, float(raw.get("voice_volume", 1.0)))),
        "music_volume": max(0.0, min(2.0, float(raw.get("music_volume", 0.85)))),
        "ducking": bool(raw.get("ducking", True)),
        "subtitles_enabled": subtitles_enabled,
        "subtitle_style": subtitle_style,
        "subtitle_position": subtitle_position,
        "subtitle_cleanup": subtitle_cleanup,
        "subtitle_cleanup_band": subtitle_cleanup_band,
        "subtitle_subclean_mode": subtitle_subclean_mode,
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
    if opts.get("master_export"):
        warnings.append("export.master_files_are_very_large")
    if opts.get("safety_adjustments"):
        warnings.append("export.options_safely_adjusted")
    estimate = _delivery_size_estimate(duration, opts)
    return {
        "version": 3,
        "strategy": strategy,
        "duration_seconds": duration,
        "output_count": sum(1 for region in regions if region["enabled"]),
        "regions": regions,
        "warnings": warnings,
        "estimated_output_size": estimate,
        "options": opts,
    }


def execute_export(
    *,
    project_id: str,
    project_name: str,
    source_path: Path,
    source_audio_path: Path | None = None,
    output_root: Path,
    options: dict[str, Any],
    takes: list[dict[str, Any]],
    segment_times: dict[str, tuple[float, float]],
    subtitle_segments: list[dict[str, Any]] | None,
    duration_seconds: float,
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> dict[str, str]:
    source_path = source_path.expanduser().resolve()
    source_audio_path = (
        source_audio_path.expanduser().resolve()
        if source_audio_path is not None
        else None
    )
    output_root = output_root.expanduser().resolve()
    takes = [
        {
            **take,
            "path": str(Path(str(take["path"])).expanduser().resolve()),
        }
        for take in takes
    ]
    opts = normalise_options(options)
    source_video = _probe_video_stream(source_path)
    source_fps = float(source_video.get("fps") or 0.0)
    opts["_source_fps"] = source_fps
    opts["_source_width"] = int(source_video.get("width") or 0)
    opts["_source_height"] = int(source_video.get("height") or 0)
    if opts.get("max_fps"):
        opts["_target_fps"] = min(source_fps, float(opts["max_fps"])) if source_fps > 0 else float(opts["max_fps"])
    else:
        opts["_target_fps"] = 0.0
    edit_ranges = _effective_edit_ranges(opts["edit_ranges"], duration_seconds)
    edited_duration = sum(end - start for start, end in edit_ranges)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    portable_project_name = (
        _portable_path_name(project_name)
        or _portable_path_name(project_id)
        or "DubRoom-Export"
    )
    session_name = f"{portable_project_name}-{stamp}"
    session_dir = output_root / session_name
    session_dir.mkdir(parents=True, exist_ok=False)
    mix_path = session_dir / "dub-mix.wav"
    on_progress(2, "Preparing audio mix")
    _render_mix(
        source_path,
        mix_path,
        takes,
        segment_times,
        duration_seconds,
        opts,
        on_progress,
        is_cancelled,
        source_audio_path=source_audio_path,
    )

    artifacts: dict[str, str] = {"folder": str(session_dir)}
    if opts.get("keep_intermediate_audio"):
        artifacts["audio_mix"] = str(mix_path)
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
            subtitle_path: Path | None = None
            if opts["subtitles_enabled"] and subtitle_segments:
                subtitle_path = session_dir / f"{target.stem}.ass"
                _write_ass_subtitles(
                    subtitle_path,
                    subtitle_segments,
                    source_ranges,
                    opts,
                )
                artifacts[f"subtitles_{key}"] = str(subtitle_path)
            _encode_video_ranges(
                source_path,
                mix_path,
                target,
                render_opts := _options_with_output_size_budget(
                    opts,
                    sum(end - start for start, end in source_ranges),
                ),
                source_ranges,
                edited_duration,
                floor,
                ceiling,
                label,
                on_progress,
                is_cancelled,
                subtitle_path,
            )
            _validate_rendered_media(target, opts)
            size_limit = int(render_opts.get("max_output_size_bytes") or 0)
            if size_limit and target.stat().st_size > size_limit:
                first_size = target.stat().st_size
                current_kbps = int(render_opts.get("_target_video_bitrate_kbps") or 0)
                if current_kbps <= 0:
                    raise RuntimeError(
                        f"Export exceeded the {size_limit} byte delivery limit"
                    )
                retry_kbps = max(
                    300,
                    int(current_kbps * (size_limit / first_size) * 0.90),
                )
                render_opts["_target_video_bitrate_kbps"] = retry_kbps
                render_opts["_target_video_maxrate_kbps"] = max(
                    retry_kbps,
                    round(retry_kbps * 1.04),
                )
                render_opts["_target_video_bufsize_kbps"] = max(
                    retry_kbps * 2,
                    1000,
                )
                on_progress(floor, "Output was too large; encoding a smaller final pass")
                _encode_video_ranges(
                    source_path,
                    mix_path,
                    target,
                    render_opts,
                    source_ranges,
                    edited_duration,
                    floor,
                    ceiling,
                    label,
                    on_progress,
                    is_cancelled,
                    subtitle_path,
                )
                _validate_rendered_media(target, render_opts)
                if target.stat().st_size > size_limit:
                    raise RuntimeError(
                        f"Export remains larger than the {size_limit} byte delivery limit"
                    )
            artifacts[key] = str(target)

    output_details = {
        key: {
            "path": value,
            "size_bytes": Path(value).stat().st_size,
        }
        for key, value in artifacts.items()
        if key not in {"folder", "audio_mix"} and Path(value).is_file()
    }
    estimated_size = _delivery_size_estimate(
        edited_duration,
        opts,
        width=int(source_video.get("width") or 1920),
        height=int(source_video.get("height") or 1080),
        fps=float(opts.get("_target_fps") or source_fps or 30.0),
    )
    if not opts.get("keep_intermediate_audio"):
        mix_path.unlink(missing_ok=True)
    manifest_path = session_dir / "export-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "created_at": datetime.now().isoformat(),
                "source_audio_path": str(source_audio_path) if source_audio_path else None,
                "options": opts,
                "estimated_output_size": estimated_size,
                "outputs": output_details,
                "artifacts": artifacts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
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
    subtitle_path: Path | None = None,
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
            subtitle_path,
        )
        return
    if opts["video_codec"] == "copy":
        raise ValueError("Video stream copy cannot be used with multiple timeline cuts")

    command = [_video_ffmpeg(opts), "-y", "-i", str(source), "-i", str(mix)]
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
    video_filter = _video_filter(opts, subtitle_path)
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
    video_backend = _video_codec_args(command, opts)
    _audio_codec_args(command, opts)
    if opts["container"] in {"mp4", "mov"}:
        command.extend(["-movflags", "+faststart"])
    command.append(str(target))
    try:
        _run_ffmpeg(
            command,
            max(expected, 1),
            floor,
            ceiling,
            label,
            on_progress,
            is_cancelled,
        )
    except RuntimeError:
        if video_backend != "nvenc" or is_cancelled():
            raise
        on_progress(floor, "NVENC unavailable; retrying edited video on CPU")
        fallback = {**opts, "hardware_acceleration": "cpu"}
        _encode_video_ranges(
            source,
            mix,
            target,
            fallback,
            ranges,
            edited_duration,
            floor,
            ceiling,
            label,
            on_progress,
            is_cancelled,
            subtitle_path,
        )


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
    command = [_media_tool("ffmpeg"), "-y", "-i", str(source)]
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


def _base_audio_chain() -> str:
    return (
        f"aresample={AUDIO_MASTER_SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:sample_rates={AUDIO_MASTER_SAMPLE_RATE}:"
        "channel_layouts=stereo"
    )


def _voice_master_chain(volume: float, *, enabled: bool) -> str:
    chain = [_base_audio_chain()]
    if enabled:
        chain.extend(
            [
                "highpass=f=65:poles=2",
                "acompressor=threshold=0.125:ratio=2:attack=5:"
                "release=120:makeup=1.15:knee=2.5:detection=rms",
            ]
        )
    chain.append(f"volume={volume}")
    return ",".join(chain)


def _final_master_chain(*, normalize: bool, enabled: bool) -> str:
    chain = ["highpass=f=25:poles=2"] if enabled else []
    if normalize:
        chain.append("loudnorm=I=-14:TP=-1.0:LRA=9")
    # Prevent inter-sample overloads even when loudness normalization is off.
    chain.append("alimiter=limit=0.95:attack=5:release=50:level=0")
    return ",".join(chain)


def _render_mix(source: Path, target: Path, takes: list[dict[str, Any]], segment_times: dict[str, tuple[float, float]], duration: float, opts: dict[str, Any], on_progress: ProgressCallback, is_cancelled: CancelCallback, *, source_audio_path: Path | None = None) -> None:
    command = [_media_tool("ffmpeg"), "-y", "-i", str(source)]
    separate_audio = source_audio_path if source_audio_path and source_audio_path.is_file() else None
    if separate_audio:
        command.extend(["-i", str(separate_audio)])
    original_audio_index = 1 if separate_audio else 0
    take_input_offset = 2 if separate_audio else 1
    has_original_audio = _has_audio(separate_audio or source)
    mastering = bool(opts.get("audio_mastering", True))
    source_audio_gain = (
        float(opts.get("music_volume", 0.85) or 0.0)
        if bool(opts.get("_source_audio_is_bed", False))
        else float(opts.get("original_volume", 0.0) or 0.0)
    )
    filters = (
        [
            f"[{original_audio_index}:a]{_base_audio_chain()},highpass=f=25:poles=2,"
            f"volume={source_audio_gain}[original]"
        ]
        if has_original_audio
        else []
    )
    voice_inputs: list[str] = []
    for index, take in enumerate(takes, start=1):
        command.extend(["-i", str(take["path"])])
        input_index = take_input_offset + index - 1
        start = float(
            take.get("timeline_start")
            if take.get("timeline_start") is not None
            else segment_times.get(str(take.get("segment_id")), (0.0, 0.0))[0]
        )
        delay = max(0, round(start * 1000))
        label = f"voice{index}"
        filters.append(
            f"[{input_index}:a]{_voice_master_chain(opts['voice_volume'], enabled=mastering)},"
            f"adelay={delay}|{delay}[{label}]"
        )
        voice_inputs.append(f"[{label}]")
    filters.append(
        f"{''.join(voice_inputs)}"
        f"amix=inputs={len(voice_inputs)}:duration=longest:normalize=0[voices_raw]"
    )
    mix_inputs: list[str] = []
    if has_original_audio:
        if opts["ducking"]:
            # The voice programme has two consumers: the sidechain detector and
            # the final mix. Split it explicitly; reusing a filter label twice
            # can consume the voice only as a sidechain and omit it from output.
            filters.append(
                "[voices_raw]asplit=2[voices_sidechain][voices_program]"
            )
            filters.append(
                "[original][voices_sidechain]"
                "sidechaincompress=threshold=.025:ratio=8:"
                "attack=20:release=320[ambience]"
            )
            mix_inputs.append("[ambience]")
            mix_inputs.append("[voices_program]")
        else:
            mix_inputs.append("[original]")
            mix_inputs.append("[voices_raw]")
    else:
        mix_inputs.append("[voices_raw]")
    music_path = opts.get("music_path")
    if music_path:
        music_index = take_input_offset + len(takes)
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        filters.append(
            f"[{music_index}:a]{_base_audio_chain()},"
            f"volume={opts['music_volume']}[music]"
        )
        mix_inputs.append("[music]")
    bounded_duration = max(duration, 0.1)
    filters.append(
        f"{''.join(mix_inputs)}"
        f"amix=inputs={len(mix_inputs)}:duration=longest:normalize=0,"
        f"apad,atrim=duration={bounded_duration},asetpts=N/SR/TB[premix]"
    )
    filters.append(
        f"[premix]{_final_master_chain(normalize=opts['normalize_audio'], enabled=mastering)}[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
            "-ar",
            str(AUDIO_MASTER_SAMPLE_RATE),
            "-c:a",
            "pcm_s24le",
            "-t",
            f"{bounded_duration:.3f}",
            str(target),
        ]
    )
    _run_ffmpeg(command, max(duration, 1), 3, 23, "Mixing audio", on_progress, is_cancelled)


def _encode_video(
    source: Path,
    mix: Path,
    target: Path,
    opts: dict[str, Any],
    start: float,
    length: float | None,
    source_duration: float,
    floor: int,
    ceiling: int,
    label: str,
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
    subtitle_path: Path | None = None,
) -> None:
    command = [_video_ffmpeg(opts), "-y"]
    if start > 0:
        command.extend(["-ss", f"{start:.3f}"])
    command.extend(["-i", str(source)])
    if start > 0:
        command.extend(["-ss", f"{start:.3f}"])
    command.extend(["-i", str(mix)])
    if length is not None:
        command.extend(["-t", f"{length:.3f}"])
    command.extend(["-map", "0:v:0", "-map", "1:a:0"])
    video_filter = _video_filter(opts, subtitle_path)
    if video_filter:
        command.extend(["-vf", video_filter])
    video_backend = _video_codec_args(command, opts)
    _audio_codec_args(command, opts)
    if opts["container"] in {"mp4", "mov"}:
        command.extend(["-movflags", "+faststart"])
    command.append(str(target))
    expected = length if length is not None else source_duration
    try:
        _run_ffmpeg(command, max(expected, 1), floor, ceiling, label, on_progress, is_cancelled)
    except RuntimeError:
        if video_backend != "nvenc" or is_cancelled():
            raise
        on_progress(floor, "NVENC unavailable; retrying video on CPU")
        fallback = {**opts, "hardware_acceleration": "cpu"}
        _encode_video(
            source, mix, target, fallback, start, length, source_duration,
            floor, ceiling, label, on_progress, is_cancelled, subtitle_path,
        )


def _encode_audio(source: Path, target: Path, opts: dict[str, Any], on_progress: ProgressCallback, is_cancelled: CancelCallback) -> None:
    command = [_media_tool("ffmpeg"), "-y", "-i", str(source)]
    _audio_codec_args(command, opts)
    command.append(str(target))
    _run_ffmpeg(command, 1, 25, 96, "Encoding audio", on_progress, is_cancelled)


def _video_codec_args(command: list[str], opts: dict[str, Any]) -> str:
    codec = opts["video_codec"]
    if codec == "copy":
        command.extend(["-c:v", "copy"])
        opts["_resolved_video_backend"] = "stream-copy"
        return "copy"
    requested_hardware = str(opts.get("hardware_acceleration") or "auto")
    use_nvenc = (
        requested_hardware != "cpu"
        and codec in NVENC_ENCODERS
        and _nvenc_available(codec)
    )
    if use_nvenc:
        opts["_resolved_video_backend"] = "NVIDIA NVENC"
        target_kbps = int(opts.get("_target_video_bitrate_kbps") or 0)
        maxrate_kbps = int(opts.get("_target_video_maxrate_kbps") or target_kbps)
        bufsize_kbps = int(opts.get("_target_video_bufsize_kbps") or target_kbps * 2)
        command.extend(
            [
                "-c:v",
                NVENC_ENCODERS[codec],
                "-preset",
                "p3",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                str(opts["quality"]),
                "-b:v",
                f"{target_kbps}k" if target_kbps else "0",
                "-pix_fmt",
                "yuv420p",
            ]
        )
        if target_kbps:
            command.extend(
                [
                    "-maxrate",
                    f"{maxrate_kbps}k",
                    "-bufsize",
                    f"{bufsize_kbps}k",
                ]
            )
        if codec == "h264" and opts.get("compatibility_mode"):
            command.extend(
                [
                    "-profile:v",
                    "high",
                    "-level:v",
                    "4.1",
                    "-tag:v",
                    "avc1",
                    "-fps_mode",
                    "cfr",
                ]
            )
        return "nvenc"
    opts["_resolved_video_backend"] = "CPU"
    encoder = VIDEO_ENCODERS[codec]
    command.extend(["-c:v", encoder])
    target_kbps = int(opts.get("_target_video_bitrate_kbps") or 0)
    maxrate_kbps = int(opts.get("_target_video_maxrate_kbps") or target_kbps)
    bufsize_kbps = int(opts.get("_target_video_bufsize_kbps") or target_kbps * 2)
    if codec in {"h264", "h265"}:
        command.extend(["-preset", opts["preset"]])
        if target_kbps:
            command.extend(
                [
                    "-b:v",
                    f"{target_kbps}k",
                    "-maxrate",
                    f"{maxrate_kbps}k",
                    "-bufsize",
                    f"{bufsize_kbps}k",
                ]
            )
        else:
            command.extend(["-crf", str(opts["quality"])])
        command.extend(["-pix_fmt", "yuv420p"])
        if codec == "h264" and opts.get("compatibility_mode"):
            command.extend([
                "-profile:v", "high",
                "-level:v", "4.1",
                "-tag:v", "avc1",
                "-fps_mode", "cfr",
            ])
    elif codec == "av1":
        command.extend(["-crf", str(opts["quality"]), "-b:v", f"{target_kbps}k" if target_kbps else "0", "-cpu-used", "6", "-pix_fmt", "yuv420p"])
    elif codec == "vp9":
        command.extend(["-crf", str(opts["quality"]), "-b:v", f"{target_kbps}k" if target_kbps else "0", "-row-mt", "1", "-pix_fmt", "yuv420p"])
    elif codec == "prores":
        command.extend(["-profile:v", "3", "-pix_fmt", "yuv422p10le"])
    return "cpu"


def _audio_codec_args(command: list[str], opts: dict[str, Any]) -> None:
    codec = opts["audio_codec"]
    command.extend(["-c:a", AUDIO_ENCODERS[codec]])
    if codec in {"aac", "opus"}:
        command.extend(["-b:a", opts["audio_bitrate"]])
    if opts.get("compatibility_mode"):
        command.extend(["-ar", "48000", "-ac", "2"])


def _escape_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


# SUBTITLE_TIMELINE_V9_20260802

def _ass_escape_line(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .strip()
    )


def _subtitle_line_limit(opts: dict[str, Any]) -> int:
    aspect = str(opts.get("aspect") or "source")
    if aspect == "9:16":
        return 24
    if aspect in {"1:1", "4:5"}:
        return 31
    return 40


def _split_long_word(word: str, limit: int) -> list[str]:
    if len(word) <= limit:
        return [word]
    return [
        word[index:index + limit]
        for index in range(0, len(word), limit)
    ]


def _subtitle_chunks(value: str, opts: dict[str, Any]) -> list[str]:
    cleaned = re.sub(
        r"\s+",
        " ",
        str(value or "").replace(r"\N", " "),
    ).strip()
    if not cleaned:
        return []

    limit = _subtitle_line_limit(opts)
    words: list[str] = []
    for word in cleaned.split(" "):
        words.extend(_split_long_word(word, limit))

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    return [
        r"\N".join(
            _ass_escape_line(line)
            for line in lines[index:index + 2]
        )
        for index in range(0, len(lines), 2)
    ]


def _ass_text(value: str) -> str:
    chunks = _subtitle_chunks(value, {})
    return chunks[0] if chunks else ""


def _subtitle_canvas(opts: dict[str, Any]) -> tuple[int, int]:
    aspect = str(opts.get("aspect") or "source")
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "1:1":
        return 1080, 1080
    if aspect == "4:5":
        return 1080, 1350
    return 1920, 1080


def _subtitle_style_line(opts: dict[str, Any]) -> str:
    style = str(opts.get("subtitle_style") or "cinema")
    alignment = 8 if opts.get("subtitle_position") == "top" else 2
    presets: dict[str, tuple[str, int, str, str, int, float, float, int]] = {
        # font, size, primary, outline, border style, outline, shadow, vertical margin
        "cinema": ("Arial", 55, "&H00FFFFFF", "&H00101010", 1, 4.0, 1.5, 72),
        "social": ("Impact", 68, "&H0000E8FF", "&H00120A08", 3, 13.0, 0.0, 88),
        "minimal": ("Segoe UI", 43, "&H00FFFFFF", "&H00202020", 1, 2.0, 0.0, 60),
        "manga": ("Arial", 61, "&H00FFFFFF", "&H00512974", 1, 5.0, 2.0, 78),
        "documentary": ("Trebuchet MS", 49, "&H00FFFFFF", "&H00101010", 3, 9.0, 0.0, 66),
    }
    font, size, primary, outline_colour, border, outline, shadow, margin = presets.get(
        style, presets["cinema"]
    )
    return (
        f"Style: Default,{font},{size},{primary},&H000000FF,{outline_colour},"
        f"&H78000000,-1,0,0,0,100,100,0,0,{border},{outline:.1f},{shadow:.1f},"
        f"{alignment},90,90,{margin},1"
    )


def _write_ass_subtitles(
    path: Path,
    subtitle_segments: list[dict[str, Any]],
    source_ranges: list[tuple[float, float]],
    opts: dict[str, Any],
) -> None:
    # DUBROOM_FAST_SUBS_V2
    width, height = _subtitle_canvas(opts)
    events: list[str] = []
    cursor = 0.0
    position = str(opts.get("subtitle_position") or "bottom").lower()
    override = r"{\\an8}" if position == "top" else r"{\\an2}"

    for range_start, range_end in source_ranges:
        for segment in subtitle_segments:
            text = _ass_text(str(segment.get("text") or ""))
            if not text:
                continue
            segment_start = float(segment.get("start") or 0.0)
            segment_end = float(segment.get("end") or 0.0)
            overlap_start = max(range_start, segment_start)
            overlap_end = min(range_end, segment_end)
            if overlap_end - overlap_start <= 0.02:
                continue
            output_start = cursor + overlap_start - range_start
            output_end = cursor + overlap_end - range_start
            events.append(
                "Dialogue: 0,"
                f"{_ass_timestamp(output_start)},{_ass_timestamp(output_end)},"
                f"Default,,0,0,0,,{override}{text}"
            )
        cursor += range_end - range_start

    content = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding"
            ),
            _subtitle_style_line(opts),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")

def _video_filter(
    opts: dict[str, Any],
    subtitle_path: Path | None = None,
) -> str | None:
    resolution = opts["resolution"]
    aspect = opts["aspect"]
    target_fps = float(opts.get("_target_fps") or 0.0)
    fps_filter = f"fps={target_fps:.6f}" if target_fps > 0 else ""

    visual_filter: str | None = None
    if not (resolution == "source" and aspect == "source" and opts["upscale"] == "off"):
        if resolution == "source":
            resolution = "1080p"
        sizes = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "2160p": (3840, 2160)}
        width, height = sizes[resolution]
        if aspect == "source":
            visual_filter = f"scale=-2:{height}:flags=lanczos"
        else:
            if aspect == "9:16":
                width, height = height, width
            elif aspect == "1:1":
                width = height
            elif aspect == "4:5":
                width, height = height, round(height * 1.25 / 2) * 2
            framing = opts["framing"]
            if framing == "crop":
                visual_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}"
            elif framing == "blur":
                visual_filter = f"split[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},boxblur=28:14[bg];[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"
            else:
                visual_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"

    filters: list[str] = []
    cleanup = str(opts.get("subtitle_cleanup") or "none")
    band = max(0.06, min(0.28, float(opts.get("subtitle_cleanup_band") or 0.14)))
    if cleanup == "auto":
        # The automatic fast path prefers a conservative lower-band repair.
        # It avoids an expensive AI pass unless SubClean is explicitly selected.
        cleanup = "crop" if band <= 0.12 else "blur"
    cleanup_zoom = 1.0 / (1.0 - band) if cleanup == "crop" else 1.0
    manual_zoom = max(1.0, min(3.0, float(opts.get("reframe_scale") or 1.0)))
    total_zoom = cleanup_zoom * manual_zoom
    position_x = max(-1.0, min(1.0, float(opts.get("reframe_x") or 0.0)))
    position_y = max(-1.0, min(1.0, float(opts.get("reframe_y") or 0.0)))
    if total_zoom > 1.0001:
        x_anchor = (position_x + 1.0) / 2.0
        y_anchor = (position_y + 1.0) / 2.0
        filters.append(
            f"crop=iw/{total_zoom:.6f}:ih/{total_zoom:.6f}:"
            f"(iw-ow)*{x_anchor:.6f}:(ih-oh)*{y_anchor:.6f},"
            f"scale=trunc(iw*{total_zoom:.6f}/2)*2:"
            f"trunc(ih*{total_zoom:.6f}/2)*2:flags=lanczos"
        )
    if cleanup == "blur":
        # `delogo` is a local interpolation filter. It is dramatically faster
        # than neural inpainting and visually behaves like a softened repair band.
        source_width = max(4, int(opts.get("_source_width") or 0))
        source_height = max(4, int(opts.get("_source_height") or 0))
        if source_width > 4 and source_height > 4:
            y = max(1, min(source_height - 3, round(source_height * (1.0 - band))))
            height = max(2, source_height - y - 1)
            filters.append(
                f"delogo=x=1:y={y}:w={source_width-2}:h={height}:show=0"
            )
    filters.extend(value for value in [visual_filter] if value)
    if opts.get("upscale") == "clarity":
        filters.append("unsharp=5:5:0.32:5:5:0.0")
    if fps_filter:
        filters.append(fps_filter)
    if subtitle_path and subtitle_path.is_file():
        filters.append(f"ass='{_escape_filter_path(subtitle_path)}'")
    return ",".join(filters) or None


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


def _ffmpeg_listing(flag: str, executable: str | None = None) -> str:
    try:
        completed = subprocess.run([executable or _media_tool("ffmpeg"), "-hide_banner", flag], capture_output=True, text=True, check=False, timeout=15)
        return f"{completed.stdout}\n{completed.stderr}"
    except (OSError, subprocess.TimeoutExpired):
        return ""


@lru_cache(maxsize=3)
def _nvenc_available(codec: str = "h264") -> bool:
    encoder = NVENC_ENCODERS.get(codec)
    nvenc_ffmpeg = _nvenc_ffmpeg()
    if not encoder or encoder not in _ffmpeg_listing("-encoders", nvenc_ffmpeg):
        return False
    null_output = "NUL" if os.name == "nt" else "/dev/null"
    try:
        completed = subprocess.run(
            [
                nvenc_ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:size=256x256:rate=1:duration=1",
                "-frames:v",
                "1",
                "-c:v",
                encoder,
                "-f",
                "null",
                null_output,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ratio_to_float(value: str | None) -> float:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _probe_video_stream(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                _media_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,avg_frame_rate,level",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, check=False, timeout=20,
        )
        payload = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
        streams = payload.get("streams") if isinstance(payload, dict) else None
        stream = streams[0] if isinstance(streams, list) and streams else {}
        fps = _ratio_to_float(stream.get("avg_frame_rate")) or _ratio_to_float(stream.get("r_frame_rate"))
        return {**stream, "fps": fps}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError, TypeError):
        return {}


def _probe_audio_codec(path: Path) -> str:
    try:
        completed = subprocess.run(
            [
                _media_tool("ffprobe"), "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True, text=True, check=False, timeout=15,
        )
        return completed.stdout.strip().lower() if completed.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _validate_rendered_media(path: Path, opts: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError("FFmpeg did not create a readable video file")
    video = _probe_video_stream(path)
    if not video:
        raise RuntimeError("The exported file contains no readable video stream")
    if not _has_audio(path):
        raise RuntimeError("The exported file contains no readable audio stream")

    if not opts.get("compatibility_mode"):
        return
    issues: list[str] = []
    codec = str(video.get("codec_name") or "").lower()
    pix_fmt = str(video.get("pix_fmt") or "").lower()
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    fps = float(video.get("fps") or 0.0)
    audio_codec = _probe_audio_codec(path)
    if codec != "h264":
        issues.append(f"video codec is {codec or 'unknown'}, expected H.264")
    if pix_fmt != "yuv420p":
        issues.append(f"pixel format is {pix_fmt or 'unknown'}, expected yuv420p")
    if max(width, height) > 1920 or min(width, height) > 1080:
        issues.append(f"resolution is {width}x{height}, expected at most 1080p")
    if fps > float(opts.get("max_fps") or 30) + 0.2:
        issues.append(f"frame rate is {fps:.2f} fps")
    if audio_codec != "aac":
        issues.append(f"audio codec is {audio_codec or 'unknown'}, expected AAC")
    if issues:
        raise RuntimeError("Maximum-compatibility export validation failed: " + "; ".join(issues))


def _has_audio(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [_media_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        return completed.returncode == 0 and "audio" in completed.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _safe_name(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value).strip(" .-")
    return re.sub(r"\s+", " ", value)[:90]


def _portable_path_name(value: str) -> str:
    """Return an ASCII-only Windows media name compatible with older players."""
    value = (
        str(value or "")
        .replace("…", "...")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("·", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:72].rstrip(" .-")


def _audio_extension(codec: str) -> str:
    return {"aac": "m4a", "opus": "opus", "flac": "flac", "pcm": "wav"}[codec]
