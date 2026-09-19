from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.translation_worker import (  # noqa: E402
    deterministic_fidelity,
    deterministic_context_merge,
    narrative_instruction,
    normalise_story_context,
    parse_json_output,
    translation_groups,
    translation_units,
    validate_suggested_glossary,
)
from services.api.app.terminology_service import analyse_transcript  # noqa: E402


def main() -> None:
    fenced = '```json\n[{"id":"1","translation":"Bonjour"}]\n```'
    assert parse_json_output(fenced, []) == [{"id": "1", "translation": "Bonjour"}]

    segments = [
        {"id": str(index), "text": " ".join(["word"] * 30)}
        for index in range(5)
    ]
    groups = translation_groups(segments)
    assert [len(group) for group in groups] == [2, 2, 1]
    assert translation_units("It starts at 4 p.m. It is already 3.58.") == [
        "It starts at 4 p.m.",
        "It is already 3.58.",
    ]
    assert "first-person" in narrative_instruction(
        {"narrative_profile": "mc_first_person"}
    )
    natural_recap_prompt = narrative_instruction(
        {"narrative_profile": "natural_recap"}
    )
    assert "third-person" in natural_recap_prompt
    assert "never make the narrator speak as the protagonist" in natural_recap_prompt
    assert "omniscient" in narrative_instruction(
        {"narrative_profile": "cinematic_omniscient"}
    )
    assert "calm delivery" in narrative_instruction(
        {
            "narrative_profile": "natural_recap",
            "narrative_instructions": "calm delivery",
        }
    )

    context = {"characters": [{"name": "Yujin"}]}
    audit = deterministic_fidelity(
        "Yujin arrived at 3.58. The gate opens at 4.",
        "Elle est arrivée.",
        context,
    )
    issue_types = {item["type"] for item in audit["issues"]}
    assert {"number_missing", "name_missing", "possible_omission"} <= issue_types
    assert audit["score"] < 50

    nested_context = normalise_story_context(
        {
            "summary": json.dumps(
                {
                    "summary": "A hunter returns in time.",
                    "characters": [{"name": "Yujin", "gender": "female"}],
                    "glossary": {"convenience store": "supérette", "Crocs": "Crocs"},
                }
            )
        },
        {"convenience store": "supérette", "Crocs": "Crocs"},
    )
    assert nested_context["summary"] == "A hunter returns in time."
    terminology_audit = deterministic_fidelity(
        "She wore her convenience store uniform with white Crocs.",
        "Elle portait son uniforme de dépanneuse avec des crochets blancs.",
        nested_context,
    )
    terminology_issues = {item["type"] for item in terminology_audit["issues"]}
    assert "terminology_mismatch" in terminology_issues
    assert len(terminology_audit["issues"]) == 2
    agreement_audit = deterministic_fidelity(
        "Yujin died protecting her friend.",
        "Yujin est morte en protegeant son ami.",
        {"glossary": {"died": "mort"}},
    )
    assert not agreement_audit["issues"]
    first_person_audit = deterministic_fidelity(
        "Yujin entered the gate alone.",
        "Je suis entrée seule dans le portail.",
        {
            "narrative_profile": "mc_first_person",
            "characters": [
                {"name": "Yujin", "role": "main character", "gender": "female"}
            ],
            "locked_glossary": {"gate": "portail"},
        },
    )
    assert not first_person_audit["issues"]
    bad_french_audit = deterministic_fidelity(
        "The friend had already died.",
        "L'ami avait déjà mort.",
        {},
    )
    assert "french_grammar_error" in {
        item["type"] for item in bad_french_audit["issues"]
    }
    running_audit = deterministic_fidelity(
        "She ran.",
        "Je suis courue.",
        {"narrative_profile": "mc_first_person"},
    )
    assert "french_grammar_error" in {
        item["type"] for item in running_audit["issues"]
    }
    term_report = analyse_transcript(
        "unit-gate-break",
        "en",
        "fr",
        [
            {
                "id": "1",
                "text": "Emergency alerts began across the city. A Gate Break would happen at 4 p.m.",
            }
        ],
    )
    gate_break = next(item for item in term_report["candidates"] if item["normalized_term"] == "gate break")
    assert gate_break["suspicion_score"] >= 9
    assert gate_break["action"] in {"web_research_and_review", "use_validated_glossary"}
    merged = deterministic_context_merge(
        [
            {"summary": "Part one.", "characters": [{"name": "Yujin"}], "glossary": {"gate": "portail"}},
            {"summary": "Part two.", "characters": [{"name": "Yujin"}, {"name": "Mina"}], "glossary": {"rank": "rang"}},
        ]
    )
    assert merged["summary"] == "Part one. Part two."
    assert [item["name"] for item in merged["characters"]] == ["Yujin", "Mina"]
    assert merged["glossary"] == {"gate": "portail", "rank": "rang"}
    validated = validate_suggested_glossary(
        {
            "glossary": {
                "white crocs": "crocs blancs",
                "convenience store worker": "vendeuse de souvenirs",
                "gate break": "rupture de porte",
            }
        },
        ["Une rupture de porte approche.", "Elle porte des crochets blancs."],
    )
    assert validated == {"gate break": "rupture de porte"}

    catalog = json.loads((ROOT / "models" / "translation-catalog.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in catalog["models"]}
    assert by_id["translation-madlad400-3b-int8"]["license"] == "Apache-2.0"
    assert "non-commercial" in by_id["translation-nllb-600m-int8"]["license"]

    print(
        json.dumps(
            {
                "ok": True,
                "checks": [
                    "strict JSON extraction",
                    "50-200 word coherent grouping",
                    "multi-sentence specialist translation units",
                    "deterministic omission/name/number audit",
                    "nested dossier recovery and mandatory terminology audit",
                    "French agreement tolerant terminology audit",
                    "suspicious genre term scoring",
                    "narrative profile direction",
                    "first-person protagonist fidelity",
                    "targeted French auxiliary audit",
                    "French running auxiliary audit",
                    "commercial MADLAD and experimental NLLB licensing",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
