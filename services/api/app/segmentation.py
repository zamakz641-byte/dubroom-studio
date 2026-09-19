from __future__ import annotations

import re
from typing import Any


HARD_END_RE = re.compile(r"[.!?\u2026][\"'\u2019\u201d)\]]*$")
SOFT_END_RE = re.compile(r"[,;:\u2014-][\"'\u2019\u201d)\]]*$")
CONNECTORS = {
    "and", "as", "because", "but", "for", "however", "if", "or", "so",
    "then", "though", "when", "while", "who", "which", "that", "yet",
    "et", "mais", "car", "donc", "or", "ni", "parce", "quand", "lorsque",
    "qui", "que", "dont", "où", "puis",
}


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _word_text(word: dict[str, Any]) -> str:
    return str(word.get("word") or "")


def _join_words(words: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    for word in words:
        raw = _word_text(word)
        token = raw.strip()
        if not token:
            continue
        if not pieces:
            pieces.append(token)
        elif raw[:1].isspace():
            pieces.append(" " + token)
        elif re.match(r"^[,.;:!?%\)\]\}]", token):
            pieces.append(token)
        elif pieces[-1].endswith(("'" , "\u2019", "-")):
            pieces.append(token)
        else:
            pieces.append(" " + token)
    joined = "".join(pieces).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", joined))


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'’-]+\b", text, flags=re.UNICODE))


def _duration(row: dict[str, Any]) -> float:
    return max(0.0, _number(row.get("end")) - _number(row.get("start")))


def _speaker_key(row: dict[str, Any]) -> str:
    return str(
        row.get("speaker")
        or row.get("speaker_id")
        or row.get("speaker_label")
        or ""
    ).strip()


def _same_speaker(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_key = _speaker_key(first)
    second_key = _speaker_key(second)
    return not first_key or not second_key or first_key == second_key


def _row_from_words(
    source: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    row = dict(source)
    row["words"] = words
    row["start"] = _number(words[0].get("start"), _number(source.get("start")))
    row["end"] = _number(words[-1].get("end"), _number(source.get("end")))
    row["text"] = _join_words(words)
    return row


def _boundary_score(
    words: list[dict[str, Any]],
    boundary: int,
    target_end: float,
) -> float:
    current = _word_text(words[boundary - 1]).strip()
    following = (
        re.sub(r"^[^\w]+", "", _word_text(words[boundary]).strip()).casefold()
        if boundary < len(words)
        else ""
    )
    end = _number(words[boundary - 1].get("end"))
    score = -abs(end - target_end) * 5
    if HARD_END_RE.search(current):
        score += 120
    elif SOFT_END_RE.search(current):
        score += 75
    if following in CONNECTORS:
        score -= 60
    return score


def split_long_segment(
    row: dict[str, Any],
    *,
    preferred_seconds: float = 4.8,
    maximum_seconds: float = 7.0,
    minimum_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Split long ASR streams at word timestamps and natural punctuation."""
    words = [
        dict(word)
        for word in (row.get("words") or [])
        if isinstance(word, dict)
        and word.get("start") is not None
        and word.get("end") is not None
    ]
    start = _number(row.get("start"))
    end = _number(row.get("end"), start)
    internal_sentence_end = any(
        HARD_END_RE.search(_word_text(word).strip())
        for word in words[:-1]
    )
    if len(words) < 4 or (
        end - start <= maximum_seconds and not internal_sentence_end
    ):
        return [dict(row)]

    parts: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(words):
        part_start = _number(words[cursor].get("start"), start)
        remaining_duration = _number(words[-1].get("end"), end) - part_start

        if remaining_duration <= maximum_seconds:
            sentence_boundary = next(
                (
                    boundary
                    for boundary in range(cursor + 1, len(words))
                    if HARD_END_RE.search(_word_text(words[boundary - 1]).strip())
                    and _number(words[boundary - 1].get("end"), part_start)
                    - part_start >= minimum_seconds
                    and _number(words[-1].get("end"), end)
                    - _number(words[boundary - 1].get("end"), part_start)
                    >= minimum_seconds
                ),
                None,
            )
            if sentence_boundary is None:
                parts.append(_row_from_words(row, words[cursor:]))
                break
            parts.append(_row_from_words(row, words[cursor:sentence_boundary]))
            cursor = sentence_boundary
            continue

        candidates: list[int] = []
        for boundary in range(cursor + 1, len(words)):
            boundary_end = _number(words[boundary - 1].get("end"), part_start)
            elapsed = boundary_end - part_start
            remaining = _number(words[-1].get("end"), end) - boundary_end
            if elapsed < minimum_seconds:
                continue
            if elapsed > maximum_seconds:
                break
            if remaining >= minimum_seconds:
                candidates.append(boundary)

        if not candidates:
            boundary = min(
                len(words),
                max(
                    cursor + 1,
                    next(
                        (
                            index
                            for index in range(cursor + 1, len(words) + 1)
                            if _number(words[index - 1].get("end"), part_start)
                            - part_start >= maximum_seconds
                        ),
                        len(words),
                    ),
                ),
            )
        else:
            hard_candidates = [
                value
                for value in candidates
                if HARD_END_RE.search(_word_text(words[value - 1]).strip())
            ]
            if hard_candidates:
                boundary = hard_candidates[0]
            else:
                target_end = part_start + preferred_seconds
                boundary = max(
                    candidates,
                    key=lambda value: _boundary_score(words, value, target_end),
                )

        parts.append(_row_from_words(row, words[cursor:boundary]))
        cursor = boundary

    return [part for part in parts if str(part.get("text") or "").strip()]


def _merge_rows(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    merged = dict(first)
    first_words = [
        dict(word) for word in (first.get("words") or []) if isinstance(word, dict)
    ]
    second_words = [
        dict(word) for word in (second.get("words") or []) if isinstance(word, dict)
    ]
    merged["start"] = _number(first.get("start"))
    merged["end"] = _number(second.get("end"), _number(first.get("end")))
    first_members = list(first.get("member_ids") or [first.get("id")])
    second_members = list(second.get("member_ids") or [second.get("id")])
    merged["member_ids"] = [
        str(value) for value in [*first_members, *second_members] if value
    ]
    if first_words and second_words:
        merged["words"] = first_words + second_words
        merged["text"] = _join_words(merged["words"])
    else:
        merged["words"] = first_words + second_words
        merged["text"] = (
            f"{str(first.get('text') or '').strip()} "
            f"{str(second.get('text') or '').strip()}"
        ).strip()
    return merged


def _needs_merge(
    row: dict[str, Any],
    *,
    minimum_complete_seconds: float,
    minimum_fragment_seconds: float,
    minimum_words: int,
) -> bool:
    text = str(row.get("text") or "").strip()
    duration = _duration(row)
    words = _word_count(text)
    complete = bool(HARD_END_RE.search(text))

    # A complete short sentence is preserved unless it is extremely tiny.
    if complete:
        return duration < minimum_complete_seconds or words < minimum_words

    # Incomplete ASR fragments need more room because TTS has to continue the
    # same thought naturally instead of restarting after one or two words.
    return duration < minimum_fragment_seconds or words < minimum_words


def merge_short_fragments(
    rows: list[dict[str, Any]],
    *,
    maximum_seconds: float = 7.0,
    maximum_gap: float = 0.50,
    minimum_complete_seconds: float = 2.0,
    minimum_fragment_seconds: float = 2.70,
    minimum_words: int = 3,
) -> list[dict[str, Any]]:
    """Remove unusably short ASR rows before translation and TTS.

    This is transcription-time segmentation, not TTS-time grouping. Complete
    rows shorter than two seconds and incomplete thoughts shorter than roughly
    2.7 seconds are joined before translation. Every returned row later produces
    exactly one WAV file.
    """
    result = [dict(row) for row in rows if str(row.get("text") or "").strip()]
    if len(result) < 2:
        return result

    changed = True
    while changed and len(result) > 1:
        changed = False
        index = 0
        while index < len(result):
            current = result[index]
            if not _needs_merge(
                current,
                minimum_complete_seconds=minimum_complete_seconds,
                minimum_fragment_seconds=minimum_fragment_seconds,
                minimum_words=minimum_words,
            ):
                index += 1
                continue

            candidates: list[tuple[float, str, int]] = []

            if index + 1 < len(result):
                following = result[index + 1]
                gap = _number(following.get("start")) - _number(current.get("end"))
                combined = _number(following.get("end")) - _number(current.get("start"))
                if (
                    _same_speaker(current, following)
                    and -0.05 <= gap <= maximum_gap
                    and combined <= maximum_seconds
                ):
                    # A short row normally belongs with what follows. This keeps
                    # one thought inside one future TTS file instead of making the
                    # voice restart after every tiny sentence.
                    penalty = max(0.0, gap)
                    if not HARD_END_RE.search(str(current.get("text") or "").strip()):
                        penalty -= 0.12
                    candidates.append((penalty, "forward", index + 1))

            if index > 0:
                previous = result[index - 1]
                gap = _number(current.get("start")) - _number(previous.get("end"))
                combined = _number(current.get("end")) - _number(previous.get("start"))
                if (
                    _same_speaker(previous, current)
                    and -0.05 <= gap <= maximum_gap
                    and combined <= maximum_seconds
                ):
                    # Backward merging remains available for the last row or
                    # when the following row cannot fit, but forward is preferred.
                    penalty = max(0.0, gap) + 0.30
                    if not HARD_END_RE.search(str(previous.get("text") or "").strip()):
                        penalty -= 0.10
                    candidates.append((penalty, "backward", index - 1))

            if not candidates:
                index += 1
                continue

            _, direction, neighbour_index = min(candidates, key=lambda item: item[0])
            if direction == "forward":
                result[index] = _merge_rows(current, result[neighbour_index])
                del result[neighbour_index]
            else:
                result[neighbour_index] = _merge_rows(result[neighbour_index], current)
                del result[index]
                index = max(0, neighbour_index)
            changed = True

    return result


def coalesce_word_timeline(
    rows: list[dict[str, Any]],
    *,
    maximum_gap: float = 0.65,
) -> list[dict[str, Any]]:
    """Rebuild continuous word streams without crossing speakers or long pauses."""
    streams: list[dict[str, Any]] = []
    current_source: dict[str, Any] | None = None
    current_words: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current_source, current_words
        if current_source is not None and current_words:
            streams.append(_row_from_words(current_source, current_words))
        current_source = None
        current_words = []

    for row in sorted(rows, key=lambda item: _number(item.get("start"))):
        words = [
            dict(word)
            for word in (row.get("words") or [])
            if isinstance(word, dict)
            and word.get("start") is not None
            and word.get("end") is not None
        ]
        if not words:
            flush()
            streams.append(dict(row))
            continue

        gap = (
            _number(words[0].get("start"))
            - _number(current_words[-1].get("end"))
            if current_words
            else 0.0
        )
        speaker_changed = (
            current_source is not None
            and not _same_speaker(current_source, row)
        )
        if current_words and (gap > maximum_gap or speaker_changed):
            flush()
        if current_source is None:
            current_source = dict(row)
        current_words.extend(words)
    flush()
    return streams


def resegment_for_dubbing(
    rows: list[dict[str, Any]],
    *,
    preferred_seconds: float = 5.8,
    maximum_seconds: float = 9.0,
    minimum_complete_seconds: float = 2.8,
    minimum_fragment_seconds: float = 3.5,
    minimum_words: int = 5,
    maximum_merge_gap: float = 0.55,
) -> list[dict[str, Any]]:
    """Create narration-friendly transcript anchors before translation.

    CONTINUOUS_NARRATION_V2_20260803. Future ASR runs prefer complete
    5-9 second passages and merge incomplete tiny fragments.

    Final invariant: one returned row equals one future TTS file. No later TTS
    stage is allowed to concatenate these rows.
    """
    split_rows: list[dict[str, Any]] = []
    for row in coalesce_word_timeline(rows):
        split_rows.extend(
            split_long_segment(
                row,
                preferred_seconds=preferred_seconds,
                maximum_seconds=maximum_seconds,
                minimum_seconds=minimum_complete_seconds,
            )
        )

    result = merge_short_fragments(
        split_rows,
        maximum_seconds=maximum_seconds,
        maximum_gap=maximum_merge_gap,
        minimum_complete_seconds=minimum_complete_seconds,
        minimum_fragment_seconds=minimum_fragment_seconds,
        minimum_words=minimum_words,
    )
    for index, row in enumerate(result, start=1):
        row["id"] = f"asr-{index:04d}"
    return result
