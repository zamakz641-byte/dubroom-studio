from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

try:
    from .config import PATHS
except ImportError:
    from config import PATHS


MIN_RATE = 1.0 / 1.10
MAX_RATE = 1.10
PREFERRED_AUDIO_MIN = 0.96
PREFERRED_AUDIO_MAX = 1.06
PREFERRED_VIDEO_MIN = 0.94
PREFERRED_VIDEO_MAX = 1.08
SPEECH_TAIL_TARGET_SECONDS = 0.10
SPEECH_TAIL_MIN_SECONDS = 0.08
PLAN_VERSION = 5
SYNC_SERVICE_BUILD = "CONTINUOUS_RETIME_V12_PCM_20260809"

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class SyncCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _media_tool(name: str) -> str:
    """Always prefer DubRoom's managed FFmpeg over the system PATH."""
    executable = f"{name}.exe" if os.name == "nt" else name
    managed = PATHS.data / "tools" / "ffmpeg" / "bin" / executable

    if managed.is_file():
        return str(managed)

    resolved = shutil.which(executable) or shutil.which(name)
    return resolved or name


def _has_audio(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [
                _media_tool("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return completed.returncode == 0 and "audio" in completed.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _nvenc_runtime_usable() -> tuple[bool, str]:
    """Test NVENC with a realistic H.264 encode using DubRoom's local FFmpeg.

    Very small probes such as 64x64 at 1 fps can be rejected by some NVENC
    driver/FFmpeg combinations even though normal video encoding works. This
    probe intentionally mirrors a real export: 640x360, 30 fps, H.264 NVENC,
    yuv420p and an MP4 output.
    """
    ffmpeg = _media_tool("ffmpeg")

    try:
        with tempfile.TemporaryDirectory(prefix="dubroom-nvenc-probe-") as folder:
            output_path = Path(folder) / "nvenc_probe.mp4"

            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=640x360:r=30:d=1",
                    "-frames:v",
                    "30",
                    "-an",
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p5",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            output_valid = (
                output_path.is_file()
                and output_path.stat().st_size > 0
            )

    except (OSError, subprocess.SubprocessError) as exc:
        return False, (
            f"NVENC compatibility test could not run with {ffmpeg}: {exc}"
        )

    details = f"{completed.stderr}\n{completed.stdout}".strip()

    if completed.returncode == 0 and output_valid:
        return True, (
            f"NVENC compatibility test passed with {ffmpeg} "
            "(640x360, 30 fps, H.264 NVENC)"
        )

    useful_lines = [
        line.strip()
        for line in details.splitlines()
        if line.strip()
    ]
    reason = " | ".join(useful_lines[-12:])[-1800:]

    return False, (
        f"NVENC compatibility test failed with {ffmpeg}: "
        f"{reason or 'the test output was not created'}"
    )


def _nvenc_available() -> bool:
    """Compatibility alias retained for older internal callers."""
    return _nvenc_runtime_usable()[0]


def solve_segment_rates(
    video_duration: float,
    audio_duration: float,
    *,
    minimum_rate: float = MIN_RATE,
    maximum_rate: float = MAX_RATE,
    audio_weight: float = 3.0,
    video_weight: float = 1.0,
) -> dict[str, Any]:
    """Pause-aware timing policy.

    The source video remains at normal speed whenever the complete voice can fit
    by changing only the speech tempo within the allowed range. A shorter voice
    leaves a real visual pause instead of forcing the video to accelerate.

    Only speech that is still too long at maximum audio tempo is allowed to
    stretch the video timeline. Any remaining extension is distributed as
    continuous slow motion by the renderer, never as a cloned final frame.
    """
    del audio_weight, video_weight

    video = max(0.05, float(video_duration or 0.0))
    audio = max(0.05, float(audio_duration or 0.0))
    minimum = max(0.05, float(minimum_rate))
    maximum = max(minimum, float(maximum_rate))

    audio_padding = 0.0
    video_hold = 0.0
    residual_mode = "none"

    # Normal case: protect the source pacing. The line may be naturally shorter
    # than its image window, which is not an error and should remain a pause.
    if audio <= video * maximum + 1e-9:
        output_duration = video
        video_rate = 1.0
        fill_rate = audio / output_duration
        if fill_rate < PREFERRED_AUDIO_MIN:
            audio_rate = 1.0
            residual_mode = "preserved_visual_pause"
        else:
            audio_rate = _clamp(fill_rate, minimum, maximum)

        played_audio = audio / max(0.05, audio_rate)
        audio_padding = max(0.0, output_duration - played_audio)
        if audio_padding > 0.035:
            residual_mode = "preserved_visual_pause"

    else:
        # The voice is genuinely longer. Accelerate speech first. Slow the
        # moving image only for the remaining amount.
        audio_rate = maximum
        output_duration = audio / audio_rate
        required_video_rate = video / output_duration

        if required_video_rate >= minimum - 1e-9:
            video_rate = _clamp(required_video_rate, minimum, 1.0)
            residual_mode = "continuous_video_slowdown"
        else:
            video_rate = minimum
            base_duration = video / video_rate
            video_hold = max(0.0, output_duration - base_duration)
            residual_mode = "distributed_video_extension"

    preferred = (
        PREFERRED_AUDIO_MIN <= audio_rate <= PREFERRED_AUDIO_MAX
        and PREFERRED_VIDEO_MIN <= video_rate <= PREFERRED_VIDEO_MAX
    )
    return {
        "video_duration": round(video, 6),
        "audio_duration": round(audio, 6),
        "output_duration": round(output_duration, 6),
        "audio_rate": round(audio_rate, 8),
        "video_rate": round(video_rate, 8),
        "audio_padding_seconds": round(audio_padding, 6),
        "video_hold_seconds": round(video_hold, 6),
        "residual_mode": residual_mode,
        "within_preferred_range": preferred,
        "within_absolute_limits": (
            minimum - 1e-6 <= audio_rate <= maximum + 1e-6
            and minimum - 1e-6 <= video_rate <= maximum + 1e-6
        ),
    }

def build_sync_plan(
    candidates: list[dict[str, Any]],
    *,
    source_duration: float | None = None,
    minimum_rate: float = MIN_RATE,
    maximum_rate: float = MAX_RATE,
) -> dict[str, Any]:
    ordered = sorted(
        (dict(item) for item in candidates),
        key=lambda item: _number(item.get("timeline_start")),
    )
    if source_duration is None:
        source_duration = max(
            [_number(item.get("timeline_end")) for item in ordered] or [0.0]
        )
    source_duration = max(0.0, float(source_duration or 0.0))

    output_cursor = 0.0
    source_cursor = 0.0
    intervals: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for item in ordered:
        segment_id = str(item.get("segment_id") or item.get("id") or "")
        raw_start = max(0.0, _number(item.get("timeline_start")))
        raw_end = max(raw_start + 0.05, _number(item.get("timeline_end"), raw_start + 0.05))
        source_start = max(source_cursor, raw_start)
        source_end = max(source_start + 0.05, raw_end)
        if source_duration > 0.0:
            source_start = min(source_start, source_duration)
            source_end = min(source_end, source_duration)
        if source_end <= source_start + 0.001:
            continue
        if source_start > source_cursor + 0.0005:
            gap_duration = source_start - source_cursor
            intervals.append(
                {
                    "kind": "gap",
                    "source_start": round(source_cursor, 6),
                    "source_end": round(source_start, 6),
                    "source_duration": round(gap_duration, 6),
                    "output_start": round(output_cursor, 6),
                    "output_end": round(output_cursor + gap_duration, 6),
                    "output_duration": round(gap_duration, 6),
                    "video_rate": 1.0,
                    "video_hold_seconds": 0.0,
                }
            )
            output_cursor += gap_duration

        video_duration = max(0.05, source_end - source_start)
        audio_duration = max(
            0.05,
            _number(item.get("source_duration") or item.get("audio_duration"), 0.05),
        )
        requested_tail = min(
            0.06,
            max(0.025, audio_duration * 0.010),
        )
        # Plan speech with a short tail so the last consonant finishes before
        # the segment boundary instead of being cut on the exact final sample.
        solved = solve_segment_rates(
            video_duration,
            audio_duration + requested_tail,
            minimum_rate=minimum_rate,
            maximum_rate=maximum_rate,
        )
        output_duration = float(solved["output_duration"])
        maximum_tail_at_limit = max(
            0.0,
            output_duration - (audio_duration / maximum_rate),
        )
        speech_tail = min(requested_tail, maximum_tail_at_limit)
        if maximum_tail_at_limit >= SPEECH_TAIL_MIN_SECONDS:
            speech_tail = max(SPEECH_TAIL_MIN_SECONDS, speech_tail)
        speech_window = max(0.05, output_duration - speech_tail)
        ideal_audio_rate = audio_duration / speech_window

        # Never drag a clearly short line merely to fill empty pictures. Keep
        # natural speech at 1.0x and preserve the visual pause.
        if ideal_audio_rate < PREFERRED_AUDIO_MIN:
            actual_audio_rate = 1.0
        else:
            actual_audio_rate = _clamp(
                ideal_audio_rate,
                minimum_rate,
                maximum_rate,
            )

        actual_speech_duration = audio_duration / actual_audio_rate
        speech_tail = max(0.0, output_duration - actual_speech_duration)
        solved["audio_duration"] = round(audio_duration, 6)
        solved["audio_rate"] = round(actual_audio_rate, 8)
        solved["audio_padding_seconds"] = round(speech_tail, 6)
        solved["speech_tail_padding_seconds"] = round(speech_tail, 6)
        solved["planned_audio_duration"] = round(audio_duration + requested_tail, 6)
        segment = {
            **item,
            **solved,
            "segment_id": segment_id,
            "source_start": round(source_start, 6),
            "source_end": round(source_end, 6),
            "output_start": round(output_cursor, 6),
            "output_end": round(output_cursor + output_duration, 6),
            "timeline_start": round(output_cursor, 6),
            "timeline_end": round(output_cursor + output_duration, 6),
            "scheduled_duration": round(output_duration, 6),
            "target_duration": round(video_duration, 6),
            "duration_fitted": (
                abs(float(solved["audio_rate"]) - 1.0) > 0.001
                or abs(float(solved["video_rate"]) - 1.0) > 0.001
                or float(solved["audio_padding_seconds"]) > 0.001
                or float(solved["video_hold_seconds"]) > 0.001
            ),
            "sync_policy": "pause-aware-continuous-video-v11",
            "strict_timeline": True,
        }
        segments.append(segment)
        intervals.append(
            {
                "kind": "segment",
                "segment_id": segment_id,
                "source_start": segment["source_start"],
                "source_end": segment["source_end"],
                "source_duration": round(video_duration, 6),
                "output_start": segment["output_start"],
                "output_end": segment["output_end"],
                "output_duration": segment["output_duration"],
                "video_rate": segment["video_rate"],
                "video_hold_seconds": segment["video_hold_seconds"],
            }
        )
        if not bool(solved["within_preferred_range"]) or str(solved["residual_mode"]) != "none":
            warnings.append(
                {
                    "segment_id": segment_id,
                    "kind": "sync_adjustment",
                    "audio_rate": solved["audio_rate"],
                    "video_rate": solved["video_rate"],
                    "audio_padding_seconds": solved["audio_padding_seconds"],
                    "video_hold_seconds": solved["video_hold_seconds"],
                    "message": "This segment requires a visible timing adjustment; ""V10 distributes it continuously instead of freezing a frame.",
                }
            )
        output_cursor += output_duration
        source_cursor = source_end

    if source_duration > source_cursor + 0.0005:
        tail_duration = source_duration - source_cursor
        intervals.append(
            {
                "kind": "gap",
                "source_start": round(source_cursor, 6),
                "source_end": round(source_duration, 6),
                "source_duration": round(tail_duration, 6),
                "output_start": round(output_cursor, 6),
                "output_end": round(output_cursor + tail_duration, 6),
                "output_duration": round(tail_duration, 6),
                "video_rate": 1.0,
                "video_hold_seconds": 0.0,
            }
        )
        output_cursor += tail_duration

    fingerprint_payload = {
        "version": PLAN_VERSION,
        "audio_start_guard": "041B",
        "source_duration": round(source_duration, 6),
        "segments": [
            {
                "segment_id": item["segment_id"],
                "source_start": item["source_start"],
                "source_end": item["source_end"],
                "audio_duration": item["audio_duration"],
                "audio_rate": item["audio_rate"],
                "speech_tail_padding_seconds": item.get("speech_tail_padding_seconds", 0.0),
                "video_rate": item["video_rate"],
                "output_duration": item["output_duration"],
            }
            for item in segments
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "version": PLAN_VERSION,
        "created_at": _now(),
        "fingerprint": fingerprint,
        "source_duration": round(source_duration, 6),
        "output_duration": round(output_cursor, 6),
        "minimum_rate": round(minimum_rate, 8),
        "maximum_rate": round(maximum_rate, 8),
        "segments": segments,
        "intervals": intervals,
        "warnings": warnings,
        "diagnostics": {
            "interval_count": len(intervals),
            "tiny_interval_count": sum(
                1
                for interval in intervals
                if float(interval.get("source_duration") or 0.0) < 0.10
            ),
            "video_extension_count": sum(
                1
                for segment in segments
                if float(segment.get("video_hold_seconds") or 0.0) > 0.0005
            ),
            "preserved_visual_pause_count": sum(
                1
                for segment in segments
                if str(segment.get("residual_mode") or "")
                == "preserved_visual_pause"
            ),
            "rate_switch_count": sum(
                1
                for first, second in zip(intervals, intervals[1:])
                if abs(
                    float(first.get("video_rate") or 1.0)
                    - float(second.get("video_rate") or 1.0)
                ) >= 0.035
            ),
        },
    }


def write_sync_plan(path: Path, plan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def synchronise_audio_takes(
    plan: dict[str, Any],
    *,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Tempo-fit complete takes without fading or trimming speech."""
    ffmpeg = _media_tool("ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    segments = [
        item for item in plan.get("segments", [])
        if isinstance(item, dict)
    ]
    total = max(1, len(segments))

    for index, item in enumerate(segments, start=1):
        if is_cancelled and is_cancelled():
            raise SyncCancelled("Voice synchronization cancelled")

        segment_id = str(item.get("segment_id") or "")
        raw_path = Path(str(item.get("raw_path") or item.get("path") or ""))
        output_path = output_dir / f"{segment_id}.wav"
        if not raw_path.is_file():
            failures.append(
                {"segment_id": segment_id, "reason": "Natural TTS take is missing"}
            )
            continue

        duration = max(0.05, float(item.get("output_duration") or 0.05))
        rate = _clamp(
            float(item.get("audio_rate") or 1.0),
            MIN_RATE,
            MAX_RATE,
        )
        filter_chain = (
            f"atempo={rate:.8f},"
            "aresample=24000,"
            "aformat=sample_fmts=s16:sample_rates=24000:"
            "channel_layouts=mono,"
            f"apad=whole_dur={duration:.8f},"
            f"atrim=duration={duration:.8f}"
        )

        temporary = output_path.with_suffix(".sync-v9.tmp.wav")
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw_path),
                "-filter:a",
                filter_chain,
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if (
            completed.returncode != 0
            or not temporary.is_file()
            or temporary.stat().st_size <= 44
        ):
            temporary.unlink(missing_ok=True)
            failures.append(
                {
                    "segment_id": segment_id,
                    "reason": (
                        "Audio synchronization failed: "
                        f"{(completed.stderr or completed.stdout)[-900:]}"
                    ),
                }
            )
            continue

        os.replace(temporary, output_path)
        generated.append(
            {
                **item,
                "path": str(output_path),
                "raw_path": str(raw_path),
                "source_duration": round(
                    float(
                        item.get("audio_duration")
                        or item.get("source_duration")
                        or 0.0
                    ),
                    4,
                ),
                "scheduled_duration": round(duration, 4),
                "timeline_start": round(
                    float(item.get("output_start") or 0.0),
                    4,
                ),
                "timeline_end": round(
                    float(item.get("output_end") or duration),
                    4,
                ),
                "tempo_ratio": round(rate, 4),
            }
        )
        if on_progress:
            on_progress(
                92 + round(index / total * 6),
                f"Synchronizing voice line {index} of {len(segments)}",
            )

    return generated, failures

def segment_times(plan: dict[str, Any]) -> dict[str, tuple[float, float]]:
    return {
        str(item.get("segment_id") or ""): (
            float(item.get("output_start") or 0.0),
            float(item.get("output_end") or 0.0),
        )
        for item in plan.get("segments", [])
        if isinstance(item, dict) and str(item.get("segment_id") or "")
    }


def remap_subtitles(
    subtitles: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map original subtitle rows inside continuous grouped TTS takes.

    CONTINUOUS_NARRATION_V2_20260803
    """
    originals = {
        str(item.get("id") or ""): dict(item)
        for item in subtitles
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    timing_by_id: dict[str, tuple[float, float]] = {}

    for item in plan.get("segments", []):
        if not isinstance(item, dict):
            continue
        lead_id = str(item.get("segment_id") or "")
        member_ids = [
            str(value)
            for value in (item.get("member_ids") or ([lead_id] if lead_id else []))
            if str(value)
        ]
        if not member_ids:
            continue

        source_start = float(item.get("source_start") or item.get("timeline_start") or 0.0)
        source_end = max(
            source_start + 0.001,
            float(item.get("source_end") or item.get("timeline_end") or source_start + 0.001),
        )
        output_start = float(item.get("output_start") or 0.0)
        output_end = max(
            output_start + 0.001,
            float(item.get("output_end") or output_start + 0.001),
        )
        source_span = max(0.001, source_end - source_start)
        output_span = max(0.001, output_end - output_start)

        for member_id in member_ids:
            original = originals.get(member_id)
            if not original:
                continue
            original_start = float(original.get("start") or source_start)
            original_end = max(
                original_start + 0.04,
                float(original.get("end") or original_start + 0.04),
            )
            relative_start = min(
                1.0,
                max(0.0, (original_start - source_start) / source_span),
            )
            relative_end = min(
                1.0,
                max(relative_start + 0.001, (original_end - source_start) / source_span),
            )
            mapped_start = output_start + relative_start * output_span
            mapped_end = min(output_end, output_start + relative_end * output_span)
            timing_by_id[member_id] = (
                mapped_start,
                max(mapped_start + 0.06, mapped_end),
            )

        if lead_id and lead_id not in timing_by_id:
            audio_duration = max(
                0.05,
                float(item.get("audio_duration") or item.get("source_duration") or 0.05),
            )
            rate = max(0.05, float(item.get("audio_rate") or 1.0))
            spoken_end = min(output_end, output_start + audio_duration / rate)
            timing_by_id[lead_id] = (
                output_start,
                max(output_start + 0.08, spoken_end),
            )

    return [
        (
            {
                **item,
                "start": timing_by_id[str(item.get("id") or "")][0],
                "end": timing_by_id[str(item.get("id") or "")][1],
            }
            if str(item.get("id") or "") in timing_by_id
            else dict(item)
        )
        for item in subtitles
    ]

def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    else:
        try:
            process.terminate()
        except OSError:
            pass


def _run_ffmpeg_block_progress(
    command: list[str],
    *,
    block_index: int,
    block_count: int,
    completed_duration: float,
    block_duration: float,
    total_duration: float,
    on_progress: ProgressCallback | None,
    is_cancelled: CancelCallback | None,
) -> None:
    """Run one small FFmpeg retiming block and expose real global progress."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail: list[str] = []
    assert process.stdout is not None

    for line in process.stdout:
        clean = line.strip()
        if clean:
            tail.append(clean)
            tail = tail[-100:]

        if is_cancelled and is_cancelled():
            _stop_process_tree(process)
            raise SyncCancelled("Video synchronization cancelled")

        if clean.startswith("out_time_ms=") or clean.startswith("out_time_us="):
            try:
                seconds = max(0.0, int(clean.split("=", 1)[1]) / 1_000_000)
            except ValueError:
                continue

            rendered = completed_duration + min(seconds, block_duration)
            ratio = min(1.0, rendered / max(0.1, total_duration))
            if on_progress:
                on_progress(
                    4 + round(ratio * 14),
                    (
                        f"{SYNC_SERVICE_BUILD} | Retiming block "
                        f"{block_index}/{block_count} | {round(ratio * 100)}%"
                    ),
                )

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            "Retimed video block rendering failed: "
            f"{' | '.join(tail)[-2200:]}"
        )


def _escape_concat_path(path: Path) -> str:
    # FFmpeg concat files use single-quoted paths. Escape the rare quote safely.
    return str(path.resolve()).replace("\\", "/").replace("'", r"'\''")


def _chunked(
    items: list[dict[str, Any]],
    size: int,
) -> list[list[dict[str, Any]]]:
    """Compatibility helper for non-video callers."""
    chunk_size = max(8, int(size))
    return [
        items[index:index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _interval_scale(item: dict[str, Any]) -> float:
    source_duration = max(
        0.000001,
        float(item.get("source_end") or 0.0)
        - float(item.get("source_start") or 0.0),
    )
    output_duration = max(
        0.000001,
        float(item.get("output_duration") or source_duration),
    )
    return output_duration / source_duration


def _coalesce_render_intervals(
    intervals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge adjacent intervals with the same continuous time slope.

    Segment identity is irrelevant to video rendering. Merging equal slopes
    shortens the setpts expression and removes redundant control points without
    changing a single output timestamp.
    """
    merged: list[dict[str, Any]] = []

    for original in intervals:
        item = dict(original)
        source_start = float(item.get("source_start") or 0.0)
        source_end = float(item.get("source_end") or source_start)
        if source_end - source_start <= 0.001:
            continue

        source_duration = source_end - source_start
        output_duration = max(
            0.000001,
            float(item.get("output_duration") or source_duration),
        )
        item["source_duration"] = source_duration
        item["output_duration"] = output_duration

        if merged:
            previous = merged[-1]
            previous_end = float(previous.get("source_end") or 0.0)
            contiguous = abs(previous_end - source_start) <= 0.0008
            same_scale = abs(
                _interval_scale(previous) - _interval_scale(item)
            ) <= 0.000025

            if contiguous and same_scale:
                previous["source_end"] = source_end
                previous["source_duration"] = (
                    float(previous.get("source_duration") or 0.0)
                    + source_duration
                )
                previous["output_duration"] = (
                    float(previous.get("output_duration") or 0.0)
                    + output_duration
                )
                previous["output_end"] = (
                    float(previous.get("output_start") or 0.0)
                    + float(previous["output_duration"])
                )
                continue

        merged.append(item)

    return merged


def _expression_safe_blocks(
    intervals: list[dict[str, Any]],
    *,
    requested_size: int,
    maximum_expression_chars: int = 5000,
    maximum_controls: int = 48,
) -> list[list[dict[str, Any]]]:
    """Split control points before FFmpeg's expression parser recursion limit.

    The Windows FFmpeg build rejects deeply nested setpts expressions around
    the size generated by 90+ controls. V11 measures the actual expression and
    closes a block before it approaches that limit.
    """
    hard_limit = max(
        8,
        min(int(requested_size), int(maximum_controls)),
    )
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for item in intervals:
        candidate = [*current, item]
        candidate_offset = float(
            candidate[0].get("source_start") or 0.0
        )
        expression, _duration = _continuous_pts_expression(
            candidate,
            source_offset=candidate_offset,
        )

        exceeds_limit = (
            len(candidate) > hard_limit
            or len(expression) > maximum_expression_chars
        )
        if current and exceeds_limit:
            blocks.append(current)
            current = [item]
        else:
            current = candidate

    if current:
        blocks.append(current)

    return blocks

def _parse_rate(value: str) -> Fraction | None:
    candidate = str(value or "").strip()
    if not candidate or candidate in {"0/0", "N/A"}:
        return None
    try:
        parsed = Fraction(candidate)
    except (ValueError, ZeroDivisionError):
        return None
    numeric = float(parsed)
    if numeric < 1.0 or numeric > 120.0:
        return None
    return parsed


def _probe_video_rate(path: Path) -> tuple[str, float]:
    """Return a stable CFR rate close to the source's real average rate."""
    try:
        completed = subprocess.run(
            [
                _media_tool("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,r_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        payload = json.loads(completed.stdout or "{}")
        stream = next(
            (
                item
                for item in payload.get("streams", [])
                if isinstance(item, dict)
            ),
            {},
        )
        selected = (
            _parse_rate(str(stream.get("avg_frame_rate") or ""))
            or _parse_rate(str(stream.get("r_frame_rate") or ""))
        )
        if selected is not None:
            return f"{selected.numerator}/{selected.denominator}", float(selected)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return "30/1", 30.0


def _continuous_pts_expression(
    block: list[dict[str, Any]],
    *,
    source_offset: float,
) -> tuple[str, float]:
    """Build one continuous piecewise-linear PTS map for a whole block.

    Unlike trim/reset/concat per segment, this never restarts video timestamps
    inside the block. Durations that previously required tpad are represented
    as distributed slow motion, so no final frame is cloned.
    """
    specs: list[tuple[float, float, float, float]] = []
    output_cursor = 0.0

    for item in block:
        absolute_start = float(item.get("source_start") or 0.0)
        absolute_end = float(item.get("source_end") or absolute_start)
        local_start = max(0.0, absolute_start - source_offset)
        local_end = max(local_start + 0.000001, absolute_end - source_offset)
        source_duration = max(0.000001, local_end - local_start)
        output_duration = max(
            0.000001,
            float(item.get("output_duration") or source_duration),
        )
        scale = output_duration / source_duration
        specs.append((local_start, local_end, output_cursor, scale))
        output_cursor += output_duration

    if not specs:
        raise RuntimeError("Cannot build a continuous map for an empty block")

    input_seconds = "((PTS-STARTPTS)*TB)"

    def formula(spec: tuple[float, float, float, float]) -> str:
        start, _end, output_start, scale = spec
        return (
            f"({output_start:.12f}+"
            f"({input_seconds}-{start:.12f})*{scale:.12f})"
        )

    expression = formula(specs[-1])
    for spec in reversed(specs[:-1]):
        _start, end, _output_start, _scale = spec
        expression = (
            f"if(lt({input_seconds},{end:.12f}),"
            f"{formula(spec)},{expression})"
        )

    return expression, output_cursor


def _build_continuous_block_filter(
    block: list[dict[str, Any]],
    *,
    source_offset: float,
    include_source_audio: bool,
    audio_input_label: str,
    fps_spec: str,
    frame_count: int,
) -> tuple[str, float]:
    expression, output_total = _continuous_pts_expression(
        block,
        source_offset=source_offset,
    )
    filters: list[str] = [
        (
            "[0:v]"
            f"setpts='({expression})/TB',"
            f"fps=fps={fps_spec}:round=near:eof_action=pass,"
            f"trim=end_frame={max(1, int(frame_count))},"
            "setpts=PTS-STARTPTS[vout]"
        )
    ]

    if include_source_audio:
        audio_labels: list[str] = []
        for index, item in enumerate(block):
            absolute_start = float(item.get("source_start") or 0.0)
            absolute_end = float(item.get("source_end") or absolute_start)
            start = max(0.0, absolute_start - source_offset)
            end = max(start + 0.001, absolute_end - source_offset)
            source_duration = max(0.001, absolute_end - absolute_start)
            output_duration = max(
                0.001,
                float(item.get("output_duration") or source_duration),
            )
            effective_rate = _clamp(
                source_duration / output_duration,
                0.5,
                2.0,
            )
            filters.append(
                f"[{audio_input_label}]atrim=start={start:.8f}:end={end:.8f},"
                "asetpts=PTS-STARTPTS,"
                f"atempo={effective_rate:.8f},"
                "aresample=48000,"
                "aformat=sample_fmts=fltp:sample_rates=48000:"
                "channel_layouts=stereo,"
                f"apad=whole_dur={output_duration:.8f},"
                f"atrim=duration={output_duration:.8f}[a{index}]"
            )
            audio_labels.append(f"[a{index}]")

        filters.append(
            f"{''.join(audio_labels)}"
            f"concat=n={len(audio_labels)}:v=0:a=1,"
            "aresample=async=1:first_pts=0,"
            "asetpts=PTS-STARTPTS[aout]"
        )

    return ";\n".join(filters), output_total

# DUBROOM_FAST_SUBS_V2_SYNC
def render_retimed_source(
    source_path: Path,
    target_path: Path,
    plan: dict[str, Any],
    *,
    include_source_audio: bool = True,
    source_audio_path: Path | None = None,
    block_size: int = 48,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> Path:
    """Render continuous CFR blocks with no per-segment video cuts.

    Each block receives one piecewise-linear timestamp map. Segment boundaries
    remain timing control points, but the actual video stream is never split or
    reset there. This removes micro-freezes caused by frame rounding, tpad and
    VFR concat seams.
    """
    source = source_path.expanduser().resolve()
    target = target_path.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(
            "The source video required for synchronization is missing"
        )

    intervals = [
        dict(item)
        for item in plan.get("intervals", [])
        if isinstance(item, dict)
        and float(item.get("source_end") or 0.0)
        - float(item.get("source_start") or 0.0)
        > 0.001
    ]
    if not intervals:
        raise RuntimeError(
            "The synchronization plan contains no renderable video interval"
        )

    audio_source = (
        source_audio_path.expanduser().resolve()
        if source_audio_path and source_audio_path.is_file()
        else None
    )
    source_has_audio = _has_audio(audio_source or source)
    render_audio = bool(include_source_audio and source_has_audio)
    audio_input_label = "1:a" if audio_source else "0:a"
    fps_spec, fps_value = _probe_video_rate(source)

    render_intervals = _coalesce_render_intervals(intervals)
    blocks = _expression_safe_blocks(
        render_intervals,
        requested_size=max(8, int(block_size)),
        maximum_expression_chars=5000,
        maximum_controls=48,
    )
    block_durations = [
        max(
            0.001,
            sum(float(item.get("output_duration") or 0.0) for item in block),
        )
        for block in blocks
    ]
    total_duration = max(0.1, sum(block_durations))

    # Allocate integer CFR frames by cumulative rounding. This keeps total drift
    # below half a frame across the whole movie instead of half a frame per block.
    block_frame_counts: list[int] = []
    cumulative_seconds = 0.0
    previous_frames = 0
    for duration in block_durations:
        cumulative_seconds += duration
        cumulative_frames = max(
            previous_frames + 1,
            round(cumulative_seconds * fps_value),
        )
        block_frame_counts.append(cumulative_frames - previous_frames)
        previous_frames = cumulative_frames

    ffmpeg = _media_tool("ffmpeg")
    nvenc_usable, nvenc_reason = _nvenc_runtime_usable()
    if not nvenc_usable:
        raise RuntimeError(
            f"{SYNC_SERVICE_BUILD}: NVENC is required but unavailable. "
            f"{nvenc_reason}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.stem}.tmp{target.suffix}")
    temporary.unlink(missing_ok=True)

    gop = max(12, round(fps_value * 2.0))
    nvenc_arguments = [
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p2",
        "-tune",
        "hq",
        "-rc",
        "vbr",
        "-cq",
        "18",
        "-b:v",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(gop),
        "-forced-idr",
        "1",
    ]

    diagnostics = plan.get("diagnostics") or {}
    if on_progress:
        on_progress(
            3,
            (
                f"{SYNC_SERVICE_BUILD} | continuous CFR {fps_spec} | "
                f"{len(intervals)} source intervals, "f"{len(render_intervals)} merged controls in {len(blocks)} "f"parser-safe blocks | "
                f"{int(diagnostics.get('video_extension_count') or 0)} "
                "frame holds converted to smooth timing"
            ),
        )

    try:
        with tempfile.TemporaryDirectory(
            prefix="dubroom-continuous-retime-",
            dir=target.parent,
        ) as working_folder:
            working = Path(working_folder)
            rendered_blocks: list[Path] = []
            completed_duration = 0.0

            for block_index, (block, block_duration, frame_count) in enumerate(
                zip(blocks, block_durations, block_frame_counts),
                start=1,
            ):
                if is_cancelled and is_cancelled():
                    raise SyncCancelled("Video synchronization cancelled")

                source_start = float(block[0].get("source_start") or 0.0)
                source_end = float(block[-1].get("source_end") or source_start)
                source_span = max(0.05, source_end - source_start)

                filter_text, mapped_duration = _build_continuous_block_filter(
                    block,
                    source_offset=source_start,
                    include_source_audio=render_audio,
                    audio_input_label=audio_input_label,
                    fps_spec=fps_spec,
                    frame_count=frame_count,
                )

                filter_path = working / f"block-{block_index:04d}.ffgraph"
                block_path = working / f"block-{block_index:04d}.mkv"
                filter_path.write_text(filter_text, encoding="utf-8")

                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-y",
                    "-ss",
                    f"{source_start:.8f}",
                    "-t",
                    f"{source_span:.8f}",
                    "-i",
                    str(source),
                ]
                if render_audio and audio_source:
                    command.extend(
                        [
                            "-ss",
                            f"{source_start:.8f}",
                            "-t",
                            f"{source_span:.8f}",
                            "-i",
                            str(audio_source),
                        ]
                    )
                command.extend(
                    [
                        "-filter_complex_script",
                        str(filter_path),
                        "-map",
                        "[vout]",
                    ]
                )
                if render_audio:
                    command.extend(["-map", "[aout]"])

                command.extend(nvenc_arguments)
                command.extend(
                    [
                        "-r",
                        fps_spec,
                        "-fps_mode",
                        "cfr",
                    ]
                )
                if render_audio:
                    # FLAC block streams cannot be concatenated safely with a
                    # packet-level copy: later blocks may retain incompatible
                    # frame parameters and become undecodable. PCM keeps every
                    # retimed block lossless and independently concatenable.
                    command.extend(["-c:a", "pcm_s24le", "-ar", "48000"])
                else:
                    command.append("-an")

                command.extend(
                    [
                        "-progress",
                        "pipe:1",
                        "-nostats",
                        str(block_path),
                    ]
                )

                try:
                    _run_ffmpeg_block_progress(
                        command,
                        block_index=block_index,
                        block_count=len(blocks),
                        completed_duration=completed_duration,
                        block_duration=block_duration,
                        total_duration=total_duration,
                        on_progress=on_progress,
                        is_cancelled=is_cancelled,
                    )
                except RuntimeError as exc:
                    expression, _ = _continuous_pts_expression(
                        block,
                        source_offset=source_start,
                    )
                    raise RuntimeError(
                        f"{SYNC_SERVICE_BUILD}: continuous block "
                        f"{block_index}/{len(blocks)} failed "
                        f"({len(block)} controls, "
                        f"{len(expression)} expression characters). {exc}"
                    ) from exc
                finally:
                    filter_path.unlink(missing_ok=True)

                if not block_path.is_file() or block_path.stat().st_size < 1024:
                    raise RuntimeError(
                        f"{SYNC_SERVICE_BUILD}: block {block_index} "
                        "did not produce a readable video"
                    )

                rendered_blocks.append(block_path)
                completed_duration += mapped_duration

            if on_progress:
                on_progress(
                    19,
                    (
                        f"{SYNC_SERVICE_BUILD} | Joining "
                        f"{len(rendered_blocks)} CFR blocks"
                    ),
                )

            concat_file = working / "concat.txt"
            concat_file.write_text(
                "\n".join(
                    f"file '{_escape_concat_path(path)}'"
                    for path in rendered_blocks
                ),
                encoding="utf-8",
            )

            concat_command = [
                ffmpeg,
                "-hide_banner",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-map",
                "0:v:0",
            ]
            if render_audio:
                concat_command.extend(["-map", "0:a:0"])
            concat_command.extend(["-c:v", "copy"])
            if render_audio:
                # Rebuild one continuous PCM stream while retaining the
                # already-rendered video packets verbatim.
                concat_command.extend(["-c:a", "pcm_s24le", "-ar", "48000"])
            concat_command.extend(
                [
                    "-fflags",
                    "+genpts",
                    "-avoid_negative_ts",
                    "make_zero",
                    str(temporary),
                ]
            )

            completed = subprocess.run(
                concat_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{SYNC_SERVICE_BUILD}: CFR block concatenation failed: "
                    f"{(completed.stderr or completed.stdout)[-2200:]}"
                )

        if not temporary.is_file() or temporary.stat().st_size < 1024:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(
                "FFmpeg did not create a readable synchronized source video"
            )

        os.replace(temporary, target)
        if on_progress:
            on_progress(
                20,
                (
                    f"{SYNC_SERVICE_BUILD} | Continuous synchronized "
                    f"source ready at {fps_spec}"
                ),
            )
        return target

    except Exception:
        temporary.unlink(missing_ok=True)
        raise
