from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import main as api
from services.api.app import sync_service


def segment(
    segment_id: str,
    speaker: str,
    start: str,
    end: str,
    text: str,
) -> api.SegmentRecord:
    return api.SegmentRecord(
        id=segment_id,
        left=0.0,
        width=10.0,
        lane=0,
        speaker=speaker,
        label=segment_id,
        color="#8b5cf6",
        start=start,
        end=end,
        sourceText=text,
        translatedText=text,
        adaptedText=text,
        emotion="Neutral",
        intensity=35,
        pace=100,
        fit=0,
        locked=False,
    )


def main() -> None:
    assertions: list[str] = []
    segments = [
        segment("s1", "Speaker 1", "00:00:00.000", "00:00:01.500", "Bonjour."),
        segment("s2", "Speaker 1", "00:00:01.650", "00:00:02.900", "Comment vas-tu ?"),
        segment("s3", "Speaker 2", "00:00:03.000", "00:00:04.400", "Très bien, merci."),
        segment("s4", "Speaker 1", "00:00:04.500", "00:00:05.700", "Parfait."),
    ]

    groups = api._build_voice_groups(
        segments,
        preferred_seconds=20.0,
        maximum_seconds=20.0,
        maximum_gap_seconds=1.0,
    )
    assert [group["member_ids"] for group in groups] == [
        ["s1", "s2"],
        ["s3"],
        ["s4"],
    ]
    for group in groups:
        speakers = {member.speaker for member in group["members"]}
        assert len(speakers) == 1, speakers
    assertions.append("Speaker boundaries preserved in TTS grouping")

    filter_graph, output_total = sync_service._build_continuous_block_filter(
        [
            {
                "source_start": 0.0,
                "source_end": 1.5,
                "output_duration": 1.7,
            },
            {
                "source_start": 1.5,
                "source_end": 3.0,
                "output_duration": 1.3,
            },
        ],
        source_offset=0.0,
        include_source_audio=True,
        audio_input_label="1:a",
        fps_spec="30/1",
        frame_count=90,
    )
    assert "[0:v]setpts=" in filter_graph
    assert "[1:a]atrim=start=" in filter_graph
    assert "concat=n=2:v=0:a=1" in filter_graph
    assert abs(output_total - 3.0) < 0.001, output_total
    assertions.append("Demucs bed follows the same continuous sync map")

    print(f"Multi-speaker pipeline tests passed: {len(assertions)} assertions")
    for assertion in assertions:
        print(f"- {assertion}")


if __name__ == "__main__":
    main()
