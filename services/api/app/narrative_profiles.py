from __future__ import annotations

from typing import Any


NARRATIVE_PROFILES: dict[str, dict[str, Any]] = {
    "natural_recap": {
        "point_of_view": "external_third_person",
        "narrator_role": "An external storyteller who knows the complete plot.",
        "tone": "Fluid, engaging and easy to follow, like a premium story recap.",
        "prompt": (
            "Rewrite the entire script as continuous external third-person narration. The narrator stands "
            "outside the story, knows the complete plot, and guides the listener through each action, cause, "
            "reaction and consequence. Convert first-person recap narration into character names and "
            "third-person pronouns. Keep first person only inside unmistakable direct dialogue that is truly "
            "spoken by a character. Use complete subject-verb sentences and natural transitions; avoid "
            "headline-like fragments, slogans, clipped noun phrases and stacks of tiny sentences. Every "
            "segment must sound like the continuation of one coherent story while preserving all verified facts. "
            "CONTINUOUS_NARRATION_V2_20260803. When neighbouring transcript rows are combined into one "
            "voice group, treat them as one spoken paragraph: do not reset tone, repeat subjects or add "
            "sentence-ending punctuation at artificial ASR boundaries."
        ),
    },
    "external_narrator": {
        "point_of_view": "external_third_person",
        "narrator_role": "A neutral external narrator observing the characters.",
        "tone": "Clear, restrained and chronological.",
        "prompt": (
            "Use a neutral external third-person narrator. Explain events clearly and chronologically, "
            "with discreet transitions. Avoid first-person narration, hype, editorial comments and "
            "invented inner thoughts."
        ),
    },
    "cinematic_omniscient": {
        "point_of_view": "omniscient_third_person",
        "narrator_role": "A cinematic omniscient narrator who understands the whole story.",
        "tone": "Elegant, visual and immersive with controlled dramatic rhythm.",
        "prompt": (
            "Tell the story through an omniscient third-person cinematic narrator. Build scenes with "
            "smooth reveals, visual phrasing and controlled tension. The narrator may explain verified "
            "motives or information established by the full transcript, but must never invent facts."
        ),
    },
    "documentary": {
        "point_of_view": "external_third_person",
        "narrator_role": "A documentary narrator presenting verified events.",
        "tone": "Precise, sober, authoritative and accessible.",
        "prompt": (
            "Use a documentary-style external narrator. Prioritize chronology, clarity and factual "
            "precision. Keep names, numbers, relationships and causal links explicit. Avoid melodrama, "
            "slang and first-person protagonist narration."
        ),
    },
    "dramatic": {
        "point_of_view": "external_third_person",
        "narrator_role": "An external dramatic storyteller.",
        "tone": "Intense and emotional, but controlled rather than exaggerated.",
        "prompt": (
            "Use an external third-person dramatic recap style. Strengthen rhythm, stakes and emotional "
            "turns using only facts supported by the story. Do not exaggerate powers, relationships, "
            "motives or consequences."
        ),
    },
    "dark_suspense": {
        "point_of_view": "external_third_person",
        "narrator_role": "An external suspense narrator revealing information gradually.",
        "tone": "Dark, tense and mysterious with deliberate pauses.",
        "prompt": (
            "Tell the story in third person with a dark suspense rhythm. Reveal verified information at "
            "the most effective moment, use concise ominous transitions and preserve uncertainty where "
            "the characters do not yet know the truth. Never fabricate mysteries."
        ),
    },
    "comedic_ironic": {
        "point_of_view": "external_third_person",
        "narrator_role": "A witty external narrator commenting lightly on events.",
        "tone": "Playful, ironic and conversational without becoming a parody.",
        "prompt": (
            "Use a witty third-person external narrator. Add light irony through phrasing and timing, "
            "not through invented jokes or altered facts. Serious, tragic or emotional scenes must keep "
            "their intended weight."
        ),
    },
    "short_condensed": {
        "point_of_view": "external_third_person",
        "narrator_role": "A fast external narrator for short-form storytelling.",
        "tone": "Concise, energetic and immediately understandable.",
        "prompt": (
            "Use concise third-person external narration suited to short-form video. Remove verbal "
            "redundancy and enter each event quickly, while preserving every essential fact, name, "
            "number, negation and causal link."
        ),
    },
    "mc_first_person": {
        "point_of_view": "protagonist_first_person",
        "narrator_role": "The confirmed main character recounting their own experience.",
        "tone": "Personal and immersive while limited to what the protagonist can know.",
        "prompt": (
            "Tell recap narration from the confirmed main character's first-person point of view. "
            "Convert only facts the protagonist can know; preserve direct dialogue and never invent "
            "thoughts, motives or information unavailable to that character."
        ),
    },
    "multi_character": {
        "point_of_view": "external_narrator_plus_dialogue",
        "narrator_role": "One external narrator plus clearly separated character dialogue.",
        "tone": "Narration remains coherent while each character keeps a distinct personality.",
        "prompt": (
            "Keep third-person external narration distinct from direct character dialogue. Preserve "
            "speaker identity, personality, intention and point of view. Never convert narrator lines "
            "into character speech or merge lines belonging to different speakers."
        ),
    },
}


def profile_definition(profile: str | None) -> dict[str, Any]:
    key = str(profile or "natural_recap").strip().lower()
    selected = NARRATIVE_PROFILES.get(key, NARRATIVE_PROFILES["natural_recap"])
    return {"id": key if key in NARRATIVE_PROFILES else "natural_recap", **selected}


def profile_instruction(profile: str | None, custom: str | None = None) -> str:
    selected = profile_definition(profile)
    instruction = str(selected["prompt"])
    direction = str(custom or "").strip()
    if direction:
        instruction += f" Additional project direction: {direction[:800]}"
    return instruction


def exchange_contract(profile: str | None, custom: str | None = None) -> dict[str, Any]:
    selected = profile_definition(profile)
    third_person = selected["point_of_view"] != "protagonist_first_person"
    rules = [
        "Preserve every verified fact, name, number, negation, relationship, cause and consequence.",
        "Rewrite as natural spoken narration instead of translating sentence structures literally.",
        "Use complete grammatical sentences with an explicit subject and verb whenever the source permits it; avoid telegraphic fragments and headline-style wording.",
        "Connect causes, actions, reactions and consequences naturally so the result reads as one continuous story.",
        "Treat ASR boundaries as timing anchors rather than mandatory sentence boundaries; continue grammar across neighbouring rows when the meaning continues.",
        "Keep the complete meaning while fitting the available duration at a natural speaking rate.",
        "Direct dialogue may retain first-person pronouns only when the source clearly represents spoken dialogue, and it must remain attributed to its speaker.",
        "Do not turn recap narration, inner explanation or scene description into quoted dialogue merely because the source uses I or you.",
    ]
    if third_person:
        rules.insert(
            0,
            "Narration must use third person. The narrator must never say I or we as if they were the protagonist.",
        )
    else:
        rules.insert(
            0,
            "Narration uses the confirmed protagonist's first person and only information that character can know.",
        )
    return {
        "profile": selected["id"],
        "point_of_view": selected["point_of_view"],
        "narrator_role": selected["narrator_role"],
        "tone": selected["tone"],
        "style_instruction": selected["prompt"],
        "project_direction": str(custom or "").strip()[:800],
        "rules": rules,
        "forbidden": [
            "invented facts, motives, powers, relationships or events",
            "literal calques that sound translated",
            "commentary about the translation task",
            "merging or renumbering DubRoom segment identifiers",
            "headline fragments, clipped noun phrases or artificial slogan-like narration",
            "turning external narration into invented direct dialogue",
        ],
    }
