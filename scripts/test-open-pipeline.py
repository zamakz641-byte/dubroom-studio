from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.open_source_policy import (  # noqa: E402
    is_open_source_license,
)
from services.api.app.main import SegmentRecord, _build_voice_groups  # noqa: E402
from services.api.app.segmentation import resegment_for_dubbing  # noqa: E402
from services.api.app.translation_worker import (  # noqa: E402
    timing_instruction,
    timing_unit_count,
)


def word(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "word": text, "probability": 1.0}


def main() -> None:
    assert is_open_source_license("Apache-2.0")
    assert is_open_source_license("MIT code")
    assert not is_open_source_license("CC-BY-NC-4.0 research only")
    assert not is_open_source_license("OpenRAIL-M weights")
    assert not is_open_source_license("Llama Community License")

    long_words = [
        word(index * 0.55, (index + 1) * 0.55, f" {token}")
        for index, token in enumerate(
            "This long sentence explains the entire confrontation, but it also "
            "contains a clean clause boundary and must remain pleasant to dub.".split()
        )
    ]
    rows = resegment_for_dubbing(
        [
            {
                "start": 0,
                "end": long_words[-1]["end"],
                "text": "".join(item["word"] for item in long_words).strip(),
                "words": long_words,
            },
            {
                "start": long_words[-1]["end"] + 0.1,
                "end": long_words[-1]["end"] + 0.5,
                "text": "Who?",
                "words": [
                    word(
                        long_words[-1]["end"] + 0.1,
                        long_words[-1]["end"] + 0.5,
                        " Who?",
                    )
                ],
            },
            {
                "start": long_words[-1]["end"] + 0.6,
                "end": long_words[-1]["end"] + 2.2,
                "text": "Who is behind this?",
                "words": [
                    word(
                        long_words[-1]["end"] + 0.6,
                        long_words[-1]["end"] + 0.9,
                        " Who",
                    ),
                    word(
                        long_words[-1]["end"] + 0.9,
                        long_words[-1]["end"] + 1.1,
                        " is",
                    ),
                    word(
                        long_words[-1]["end"] + 1.1,
                        long_words[-1]["end"] + 1.5,
                        " behind",
                    ),
                    word(
                        long_words[-1]["end"] + 1.5,
                        long_words[-1]["end"] + 2.2,
                        " this?",
                    ),
                ],
            },
        ]
    )
    assert rows
    assert all(float(row["end"]) - float(row["start"]) <= 10.51 for row in rows)
    assert any("Who? Who is behind this?" in row["text"] for row in rows)
    assert [row["id"] for row in rows] == [
        f"asr-{index:04d}" for index in range(1, len(rows) + 1)
    ]

    # Provider chunks can end in the middle of a sentence. Rebuild the global
    # Word timelines are now grouped into a natural continuous dubbing block.
    # This avoids the short, choppy voice clips that the Multi-Speaker test
    # exposed while preserving every sentence boundary inside the block.
    sentence_tokens = (
        "The room was too small to get comfortable. "
        "Someone suddenly knocked outside. The door opened."
    ).split()
    sentence_words = [
        word(index * 0.32, (index + 1) * 0.32, f" {token}")
        for index, token in enumerate(sentence_tokens)
    ]
    provider_rows = [
        {
            "start": sentence_words[0]["start"],
            "end": sentence_words[7]["end"],
            "text": "".join(item["word"] for item in sentence_words[:8]).strip(),
            "words": sentence_words[:8],
        },
        {
            "start": sentence_words[8]["start"],
            "end": sentence_words[12]["end"],
            "text": "".join(item["word"] for item in sentence_words[8:13]).strip(),
            "words": sentence_words[8:13],
        },
        {
            "start": sentence_words[13]["start"],
            "end": sentence_words[-1]["end"],
            "text": "".join(item["word"] for item in sentence_words[13:]).strip(),
            "words": sentence_words[13:],
        },
    ]
    sentence_rows = resegment_for_dubbing(provider_rows)
    assert [item["text"] for item in sentence_rows] == [
        "The room was too small to get comfortable. "
        "Someone suddenly knocked outside. The door opened."
    ]
    assert sentence_rows[0]["start"] == 0.0
    assert sentence_rows[0]["end"] == sentence_words[-1]["end"]

    instruction, _, upper = timing_instruction(
        {"duration_seconds": 3.0},
        "fr",
    )
    assert "3.00 seconds" in instruction
    assert timing_unit_count("Une phrase française naturelle.", "fr") <= upper
    voice_segments = [
        SegmentRecord(
            id=f"asr-{index:04d}",
            left=0,
            width=1,
            lane=0,
            speaker="Narrator",
            label=f"ASR {index}",
            color="#fff",
            start=f"00:00:{start:05.2f}",
            end=f"00:00:{end:05.2f}",
            sourceText=text,
            translatedText=text,
            adaptedText=text,
            emotion="Neutral",
            intensity=35,
            pace=100,
            fit=0,
            locked=False,
        )
        for index, (start, end, text) in enumerate(
            [
                (0.0, 1.5, "Le nom de mon père était Ying."),
                (1.6, 5.2, "Nous avions bu l'élixir d'immortalité."),
                (5.3, 7.5, "Deux mille ans passèrent."),
                (7.6, 12.0, "Puis le compte à rebours apparut."),
            ],
            start=1,
        )
    ]
    voice_groups = _build_voice_groups(voice_segments)
    assert len(voice_groups) == 2
    assert voice_groups[0]["member_ids"] == [
        "asr-0001",
        "asr-0002",
        "asr-0003",
    ]
    assert voice_groups[0]["timeline_end"] < voice_groups[1]["timeline_start"]
    print(
        {
            "ok": True,
            "segments": len(rows),
            "maximum_duration": max(
                float(row["end"]) - float(row["start"]) for row in rows
            ),
            "timing_upper": upper,
            "voice_groups": len(voice_groups),
        }
    )


if __name__ == "__main__":
    main()
