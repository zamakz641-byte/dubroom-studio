from __future__ import annotations

import html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

try:
    from .config import PATHS
except ImportError:
    from config import PATHS


DB_PATH = PATHS.data / "terminology.sqlite3"
DOMAIN_MARKERS = {
    "awakening", "awakened", "aura", "boss", "breakthrough", "class",
    "constellation", "cultivation", "demonic", "dungeon", "familiar", "gate",
    "guild", "hunter", "mana", "murim", "necromancer", "qi", "raid", "rank",
    "ranker", "realm", "regressor", "reincarnator", "relic", "returner",
    "sect", "skill", "summon", "system", "trait",
}
EVENT_MARKERS = {
    "alert", "alerts", "appeared", "began", "break", "broke", "charged",
    "destroyed", "emergency", "entered", "escaped", "happen", "happened",
    "occur", "occurred", "opening", "poured", "triggered", "would",
}
POLYSEMY_RISK_TERMS = {
    "break", "class", "core", "gate", "rank", "realm", "returner", "skill",
    "system", "trait",
}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "but", "by", "for",
    "from", "had", "has", "have", "he", "her", "him", "his", "i", "in", "into",
    "is", "it", "its", "of", "on", "or", "she", "that", "the", "their", "them",
    "they", "this", "to", "was", "were", "with", "you",
    "already", "allowing", "appeared", "called", "entered", "inside", "made", "near", "straight", "would",
}
SEED_EN_FR = [
    ("gate", "hunter_gate", "portail", ["faille"], "Passage reliant le monde réel à un donjon ou une zone hostile.", 0.78),
    ("dungeon", "hunter_gate", "donjon", [], "Zone fermée contenant des monstres, objectifs et récompenses.", 0.97),
    ("gate break", "world_event", "rupture de portail", ["rupture de donjon", "déferlement de monstres"], "Événement où des monstres franchissent un portail instable et atteignent le monde réel.", 0.74),
    ("dungeon break", "world_event", "rupture de donjon", ["déferlement du donjon"], "Événement où les monstres d'un donjon envahissent le monde réel.", 0.82),
    ("hunter", "hunter_gate", "chasseur", ["chasseuse"], "Personne éveillée chargée d'affronter les donjons et monstres.", 0.96),
    ("awakened", "hunter_gate", "Éveillé", ["éveillée"], "Humain ayant obtenu des capacités surnaturelles.", 0.90),
    ("awakening", "hunter_gate", "Éveil", [], "Événement donnant des capacités surnaturelles.", 0.91),
    ("ranker", "system", "classé", ["ranker"], "Combattant placé dans un classement officiel.", 0.72),
    ("returner", "regression", "revenant", ["retourné"], "Personne revenue d'un autre monde ou d'une autre époque.", 0.65),
    ("regressor", "regression", "régresseur", ["revenant dans le passé"], "Personne ayant remonté sa propre chronologie.", 0.83),
    ("reincarnator", "regression", "réincarné", [], "Personne née de nouveau dans un autre corps ou une autre vie.", 0.92),
    ("constellation", "system", "constellation", [], "Entité cosmique ou sponsor surnaturel dans certains univers à système.", 0.86),
    ("guild", "organisation", "guilde", [], "Organisation regroupant des chasseurs ou aventuriers.", 0.98),
    ("raid", "hunter_gate", "raid", ["expédition"], "Opération coordonnée contre un donjon ou un boss.", 0.90),
    ("boss monster", "creature", "monstre boss", ["boss"], "Monstre principal d'une zone ou d'un donjon.", 0.82),
    ("mana core", "magic", "noyau de mana", [], "Organe ou réservoir concentrant le mana.", 0.93),
    ("spiritual energy", "cultivation", "énergie spirituelle", [], "Énergie utilisée dans les univers de cultivation.", 0.96),
    ("cultivation", "cultivation", "cultivation", ["progression spirituelle"], "Discipline d'accumulation et de raffinement de l'énergie.", 0.88),
    ("realm", "cultivation", "royaume", ["niveau", "stade"], "Palier de progression dans un système de cultivation.", 0.61),
    ("breakthrough", "cultivation", "percée", ["franchissement de palier"], "Passage à un niveau supérieur de cultivation.", 0.76),
    ("artifact", "item", "artefact", [], "Objet doté d'un pouvoir surnaturel.", 0.98),
    ("relic", "item", "relique", [], "Objet ancien ou sacré doté de pouvoir.", 0.97),
    ("skill", "system", "compétence", ["aptitude"], "Pouvoir nommé accordé ou appris dans un système.", 0.93),
    ("trait", "system", "trait", ["caractéristique"], "Propriété passive d'un personnage.", 0.79),
    ("class", "system", "classe", [], "Archétype ou métier attribué par un système.", 0.92),
    ("familiar", "summoning", "familier", [], "Créature liée à un invocateur.", 0.96),
    ("summon", "summoning", "invocation", ["invoquer"], "Créature invoquée ou action d'invoquer.", 0.82),
    ("necromancer", "class", "nécromancien", [], "Utilisateur de magie liée aux morts.", 0.99),
    ("qi deviation", "murim", "déviation du qi", ["déviation énergétique"], "Dérèglement dangereux de l'énergie interne.", 0.85),
    ("demonic cult", "murim", "culte démoniaque", [], "Organisation martiale associée aux arts démoniaques.", 0.91),
    ("martial master", "murim", "maître martial", [], "Pratiquant de très haut niveau des arts martiaux.", 0.94),
    ("creature", "creature", "créature", ["monstre", "être", "bête"], "Être vivant ou surnaturel, terme neutre sans hostilité implicite.", 0.71),
    ("monster", "creature", "monstre", ["créature", "abomination"], "Entité généralement hostile ou dangereuse.", 0.94),
    ("beast", "creature", "bête", ["créature bestiale", "monstre"], "Créature dont le caractère animal est important.", 0.82),
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialise() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_term TEXT NOT NULL,
                normalized_term TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                category TEXT,
                definition TEXT,
                preferred_translation TEXT,
                alternatives_json TEXT NOT NULL DEFAULT '[]',
                forbidden_json TEXT NOT NULL DEFAULT '[]',
                scope TEXT NOT NULL DEFAULT 'global',
                project_id TEXT,
                status TEXT NOT NULL DEFAULT 'suggested',
                confidence REAL NOT NULL DEFAULT 0,
                suspicion_score INTEGER NOT NULL DEFAULT 0,
                occurrences INTEGER NOT NULL DEFAULT 0,
                examples_json TEXT NOT NULL DEFAULT '[]',
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_terms_identity
                ON terms(normalized_term, source_language, target_language, scope, IFNULL(project_id, ''));
            CREATE INDEX IF NOT EXISTS idx_terms_project
                ON terms(project_id, source_language, target_language, status);
            CREATE TABLE IF NOT EXISTS term_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term_id INTEGER NOT NULL,
                previous_translation TEXT,
                corrected_translation TEXT NOT NULL,
                apply_globally INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(term_id) REFERENCES terms(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS translation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM terms WHERE scope='global' AND source_language='en' AND target_language='fr'"
        ).fetchone()[0]
        if count == 0:
            timestamp = _now()
            connection.executemany(
                """
                INSERT INTO terms(
                    source_term, normalized_term, source_language, target_language,
                    category, definition, preferred_translation, alternatives_json,
                    scope, status, confidence, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        term, term.casefold(), "en", "fr", category, definition,
                        preferred, json.dumps(alternatives, ensure_ascii=False),
                        "global", "reference", confidence, timestamp, timestamp,
                    )
                    for term, category, preferred, alternatives, definition, confidence in SEED_EN_FR
                ],
            )


def _row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("alternatives_json", "forbidden_json", "examples_json", "sources_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key) or "[]")
    result["locked"] = result["status"] in {"approved", "locked"}
    return result


def list_terms(
    project_id: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    initialise()
    clauses = []
    values: list[Any] = []
    if project_id:
        clauses.append("(project_id=? OR scope='global')")
        values.append(project_id)
    if source_language:
        clauses.append("source_language=?")
        values.append(source_language.lower())
    if target_language:
        clauses.append("target_language=?")
        values.append(target_language.lower())
    if status:
        clauses.append("status=?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM terms {where} ORDER BY scope='project' DESC, suspicion_score DESC, source_term",
            values,
        ).fetchall()
    return [_row(row) for row in rows]


def resolved_glossary(project_id: str, source_language: str, target_language: str) -> dict[str, str]:
    terms = list_terms(project_id, source_language, target_language)
    result: dict[str, str] = {}
    for term in reversed(terms):
        if term["status"] not in {"approved", "locked"}:
            continue
        preferred = str(term.get("preferred_translation") or "").strip()
        if preferred:
            result[str(term["source_term"])] = preferred
    return result


def upsert_term(payload: dict[str, Any]) -> dict[str, Any]:
    initialise()
    source_term = str(payload.get("source_term") or "").strip()
    if not source_term:
        raise ValueError("source_term is required")
    source_language = str(payload.get("source_language") or "en").lower()
    target_language = str(payload.get("target_language") or "fr").lower()
    project_id = str(payload.get("project_id") or "").strip() or None
    scope = str(payload.get("scope") or ("project" if project_id else "global"))
    timestamp = _now()
    values = {
        "source_term": source_term,
        "normalized_term": source_term.casefold(),
        "source_language": source_language,
        "target_language": target_language,
        "category": str(payload.get("category") or ""),
        "definition": str(payload.get("definition") or ""),
        "preferred_translation": str(payload.get("preferred_translation") or ""),
        "alternatives_json": json.dumps(payload.get("alternatives") or [], ensure_ascii=False),
        "forbidden_json": json.dumps(payload.get("forbidden") or [], ensure_ascii=False),
        "scope": scope,
        "project_id": project_id,
        "status": str(payload.get("status") or "suggested"),
        "confidence": max(0.0, min(1.0, float(payload.get("confidence") or 0))),
        "suspicion_score": max(0, int(payload.get("suspicion_score") or 0)),
        "occurrences": max(0, int(payload.get("occurrences") or 0)),
        "examples_json": json.dumps(payload.get("examples") or [], ensure_ascii=False),
        "sources_json": json.dumps(payload.get("sources") or [], ensure_ascii=False),
        "updated_at": timestamp,
    }
    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT id FROM terms WHERE normalized_term=? AND source_language=? AND
            target_language=? AND scope=? AND IFNULL(project_id,'')=IFNULL(?,'')
            """,
            (values["normalized_term"], source_language, target_language, scope, project_id),
        ).fetchone()
        if existing:
            assignments = ", ".join(f"{key}=?" for key in values)
            connection.execute(
                f"UPDATE terms SET {assignments} WHERE id=?",
                [*values.values(), existing["id"]],
            )
            term_id = existing["id"]
        else:
            values["created_at"] = timestamp
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            cursor = connection.execute(
                f"INSERT INTO terms({columns}) VALUES({placeholders})",
                list(values.values()),
            )
            term_id = cursor.lastrowid
        row = connection.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
    return _row(row)


def approve_term(term_id: int, preferred_translation: str, apply_globally: bool = False) -> dict[str, Any]:
    initialise()
    preferred = preferred_translation.strip()
    if not preferred:
        raise ValueError("preferred_translation is required")
    with _connect() as connection:
        current = connection.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
        if not current:
            raise ValueError("term not found")
        timestamp = _now()
        connection.execute(
            """
            UPDATE terms SET preferred_translation=?, status='locked', confidence=1,
            scope=CASE WHEN ? THEN 'global' ELSE scope END,
            project_id=CASE WHEN ? THEN NULL ELSE project_id END, updated_at=? WHERE id=?
            """,
            (preferred, int(apply_globally), int(apply_globally), timestamp, term_id),
        )
        connection.execute(
            """
            INSERT INTO term_corrections(term_id,previous_translation,corrected_translation,apply_globally,created_at)
            VALUES(?,?,?,?,?)
            """,
            (term_id, current["preferred_translation"], preferred, int(apply_globally), timestamp),
        )
        row = connection.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
    return _row(row)


def _candidate_phrases(texts: list[str]) -> tuple[Counter[str], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    def remember_example(term: str, text: str) -> None:
        if len(examples[term]) < 3 and text not in examples[term]:
            examples[term].append(text)

    for text in texts:
        tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
        lowered = [token.casefold() for token in tokens]
        sentence_candidates: set[str] = set()
        title_pattern = re.compile(
            r"\b(?:[A-Z]{2,}|[A-Z][a-z]+)"
            r"(?:\s+(?:of|the|has|no|[A-Z]{2,}|[A-Z][a-z]+)){1,7}\b"
        )
        for match in title_pattern.finditer(text):
            if sum(
                token[:1].isupper()
                for token in match.group(0).split()
                if token.casefold() not in {"of", "the", "has", "no"}
            ) < 2:
                continue
            normalised = match.group(0).casefold()
            sentence_candidates.add(normalised)
            remember_example(normalised, text)
        for size in (1, 2, 3):
            for index in range(len(tokens) - size + 1):
                phrase_tokens = tokens[index:index + size]
                phrase_lower = lowered[index:index + size]
                while phrase_lower and phrase_lower[0] in STOPWORDS:
                    phrase_lower = phrase_lower[1:]
                    phrase_tokens = phrase_tokens[1:]
                while phrase_lower and phrase_lower[-1] in STOPWORDS:
                    phrase_lower = phrase_lower[:-1]
                    phrase_tokens = phrase_tokens[:-1]
                if not phrase_lower or all(token in STOPWORDS for token in phrase_lower):
                    continue
                if any(token in STOPWORDS and token not in {"of", "the"} for token in phrase_lower[1:-1]):
                    continue
                phrase = " ".join(phrase_tokens)
                normalised = " ".join(phrase_lower)
                has_domain = any(token in DOMAIN_MARKERS for token in phrase_lower)
                title_case = size > 1 and sum(token[:1].isupper() for token in phrase_tokens) >= 2
                if size == 1 and not has_domain:
                    continue
                if size > 1 and not has_domain and not title_case:
                    continue
                sentence_candidates.add(normalised)
                remember_example(normalised, text)
        for normalised in sentence_candidates:
            counts[normalised] += 1
    return counts, examples


def analyse_transcript(
    project_id: str,
    source_language: str,
    target_language: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    initialise()
    with _connect() as connection:
        connection.execute(
            """
            DELETE FROM terms
            WHERE project_id=? AND source_language=? AND target_language=? AND status='suspected'
            """,
            (project_id, source_language, target_language),
        )
    texts = [str(item.get("text") or "").strip() for item in segments if str(item.get("text") or "").strip()]
    counts, examples = _candidate_phrases(texts)
    existing = list_terms(project_id, source_language, target_language)
    by_normalized: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for term in existing:
        by_normalized[str(term["normalized_term"])].append(term)
    candidates: list[dict[str, Any]] = []
    detected_titles = {
        normalised
        for normalised, term_examples in examples.items()
        if any(
            (match := re.search(rf"\b{re.escape(normalised)}\b", example, re.IGNORECASE))
            and sum(token[:1].isupper() for token in match.group(0).split() if token.casefold() not in {"of", "the", "has", "no"}) >= 2
            for example in term_examples
        )
    }
    for normalised, occurrences in counts.items():
        if any(
            normalised != title and re.search(rf"\b{re.escape(normalised)}\b", title)
            for title in detected_titles
        ):
            continue
        words = normalised.split()
        known = by_normalized.get(normalised, [])
        has_domain = any(word in DOMAIN_MARKERS for word in words)
        context_words = set(
            token.casefold()
            for example in examples[normalised]
            for token in re.findall(r"[A-Za-z][A-Za-z'-]*", example)
        )
        event_context = bool(EVENT_MARKERS & context_words)
        nearby_domain = len(DOMAIN_MARKERS & context_words) >= 2
        polysemy_risk = bool(POLYSEMY_RISK_TERMS & set(words))
        specialized_compound = len(words) > 1 and (has_domain or nearby_domain or event_context)
        title_case = False
        for example in examples[normalised]:
            match = re.search(rf"\b{re.escape(normalised)}\b", example, re.IGNORECASE)
            if match and sum(token[:1].isupper() for token in match.group(0).split()) >= 2:
                title_case = True
                break
        score = 0
        signals: list[str] = []
        if title_case:
            score += 3
            signals.append("title_or_proper_name")
        if occurrences >= 3:
            score += 3
            signals.append("repeated_term")
        if has_domain:
            score += 2
            signals.append("domain_marker")
        if event_context:
            score += 2
            signals.append("event_context")
        if specialized_compound:
            score += 2
            signals.append("specialized_compound")
        if polysemy_risk:
            score += 2
            signals.append("polysemy_risk")
        if nearby_domain and not has_domain:
            score += 1
            signals.append("near_domain_terms")
        if not known:
            score += 2
            signals.append("not_in_glossary")
        if len(words) > 1:
            score += 1
            signals.append("multi_word_expression")
        if any(word in {"rank", "skill", "class", "gate", "dungeon", "realm"} for word in words):
            score += 1
            signals.append("genre_keyword")
        if score < 3:
            continue
        project_reference = next((term for term in known if term["scope"] == "project"), None)
        global_reference = next((term for term in known if term["scope"] == "global"), None)
        reference = project_reference or global_reference
        action = "translate_normally"
        if score >= 9:
            action = "web_research_and_review"
        elif score >= 6:
            action = "web_research"
        elif score >= 3:
            action = "local_verification"
        if reference and reference["status"] in {"approved", "locked"}:
            action = "use_validated_glossary"
        candidates.append(
            {
                "term": reference["source_term"] if reference else normalised,
                "normalized_term": normalised,
                "occurrences": occurrences,
                "suspicion_score": score,
                "signals": signals,
                "action": action,
                "examples": examples[normalised],
                "local_match": reference,
                "project_match": project_reference,
                "semantic_type": (
                    str(reference.get("category") or "")
                    if reference
                    else "world_event"
                    if event_context and any(word in {"break", "awakening", "raid"} for word in words)
                    else "specialized_expression"
                ),
                "known_definition": str(reference.get("definition") or "") if reference else "",
                "translation_hypotheses": (
                    [
                        value
                        for value in [
                            str(reference.get("preferred_translation") or ""),
                            *(str(value) for value in reference.get("alternatives", [])),
                        ]
                        if value
                    ]
                    if reference
                    else []
                ),
                "needs_web_research": score >= 6 and not (reference and reference["status"] in {"approved", "locked"}),
                "needs_review": not (reference and reference["status"] in {"approved", "locked"})
                and (score >= 9 or not reference or reference["status"] not in {"approved", "locked"}),
            }
        )
    candidates = [
        candidate
        for candidate in candidates
        if candidate["local_match"]
        or not any(
            candidate["normalized_term"] != other["normalized_term"]
            and re.search(rf"\b{re.escape(candidate['normalized_term'])}\b", other["normalized_term"])
            and set(candidate["examples"]) & set(other["examples"])
            and other["suspicion_score"] >= candidate["suspicion_score"]
            for other in candidates
        )
    ]
    candidates.sort(key=lambda item: (-item["suspicion_score"], -item["occurrences"], item["term"]))
    for candidate in candidates:
        if candidate["project_match"]:
            continue
        reference = candidate.get("local_match") or {}
        upsert_term(
            {
                "source_term": candidate["term"],
                "source_language": source_language,
                "target_language": target_language,
                "project_id": project_id,
                "scope": "project",
                "category": reference.get("category") or candidate.get("semantic_type") or "",
                "definition": reference.get("definition") or "",
                "preferred_translation": reference.get("preferred_translation") or "",
                "alternatives": reference.get("alternatives") or [],
                "forbidden": reference.get("forbidden") or [],
                "status": "suspected",
                "confidence": reference.get("confidence") or 0,
                "suspicion_score": candidate["suspicion_score"],
                "occurrences": candidate["occurrences"],
                "examples": candidate["examples"],
            }
        )
    return {
        "project_id": project_id,
        "source_language": source_language,
        "target_language": target_language,
        "candidate_count": len(candidates),
        "review_count": sum(1 for item in candidates if item["needs_review"]),
        "candidates": candidates,
    }


def _fetch(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "DubRoom-Studio/0.1 terminology research (+local desktop app)",
            "Accept-Language": "en,fr;q=0.8",
        },
    )
    with urlopen(request, timeout=8) as response:
        return response.read(900_000).decode("utf-8", errors="replace")


def web_research(
    term: str,
    source_language: str,
    target_language: str,
    examples: list[str] | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    examples = [str(value).strip() for value in (examples or []) if str(value).strip()]
    context_tokens = Counter(
        token.casefold()
        for example in examples
        for token in re.findall(r"[A-Za-z][A-Za-z'-]*", example)
        if token.casefold() in DOMAIN_MARKERS or token.casefold() in EVENT_MARKERS
    )
    context_hint = " ".join(token for token, _ in context_tokens.most_common(4))
    category_hint = str(category or "").replace("_", " ").strip()
    # Strict open-source mode: terminology research is restricted to
    # Wikimedia's open MediaWiki stack and openly licensed knowledge bases.
    # Closed search engines are intentionally not queried by the application.
    queries = [
        f"Wikipedia: {term}",
        f"Wiktionary: {term}",
    ]
    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    for domain, label in (
        ("en.wikipedia.org", "Wikipedia"),
        ("en.wiktionary.org", "Wiktionary"),
    ):
        try:
            api_url = (
                f"https://{domain}/w/api.php?action=query&list=search"
                f"&srsearch={quote_plus(term)}&srlimit=5&format=json"
            )
            result = json.loads(_fetch(api_url))
            for item in result.get("query", {}).get("search", []):
                title = str(item.get("title") or "")
                snippet = re.sub(
                    r"\s+", " ",
                    html.unescape(re.sub(r"<[^>]+>", " ", str(item.get("snippet") or ""))),
                ).strip()
                haystack = f"{title} {snippet}".casefold()
                term_tokens = [token for token in re.findall(r"[a-z0-9]+", term.casefold()) if len(token) > 2]
                exact_title = title.casefold() == term.casefold()
                if term_tokens and not exact_title and not all(token in haystack for token in term_tokens):
                    continue
                if (
                    len(term_tokens) > 1
                    and term.casefold() not in haystack
                    and not any(marker in haystack for marker in ("anime", "dungeon", "hunter", "manga", "manhwa", "monster", "webtoon"))
                ):
                    continue
                url = f"https://{domain}/wiki/{quote_plus(title.replace(' ', '_'))}"
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append(
                    {
                        "query": f"{label}: {term}",
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "relevance_score": round(
                            min(
                                1.0,
                                0.45
                                + (0.3 if exact_title else 0)
                                + (0.15 if term.casefold() in haystack else 0),
                            ),
                            3,
                        ),
                    }
                )
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    sources.sort(key=lambda item: float(item.get("relevance_score") or 0), reverse=True)
    selected_sources = sources[:8]
    independent_hosts = {
        urlparse(str(item.get("url") or "")).netloc.casefold()
        for item in selected_sources
        if str(item.get("url") or "")
    }
    high_relevance = sum(float(item.get("relevance_score") or 0) >= 0.7 for item in selected_sources)
    evidence_confidence = min(
        0.9,
        0.25
        + min(0.3, len(independent_hosts) * 0.08)
        + min(0.25, high_relevance * 0.07)
        + (0.1 if context_hint else 0),
    )
    return {
        "term": term,
        "source_language": source_language,
        "target_language": target_language,
        "queries": queries,
        "context_examples": examples[:3],
        "context_hint": context_hint,
        "category": category or "",
        "sources": selected_sources,
        "source_count": len(selected_sources),
        "independent_source_count": len(independent_hosts),
        "evidence_confidence": round(evidence_confidence, 3),
        "needs_human_review": evidence_confidence < 0.72,
        "errors": errors,
        "researched_at": _now(),
    }


def research_term(term_id: int) -> dict[str, Any]:
    initialise()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
    if not row:
        raise ValueError("term not found")
    examples = json.loads(row["examples_json"] or "[]")
    result = web_research(
        row["source_term"],
        row["source_language"],
        row["target_language"],
        examples=examples,
        category=row["category"],
    )
    with _connect() as connection:
        connection.execute(
            """
            UPDATE terms SET sources_json=?, status='researched',
            confidence=MAX(confidence, ?), updated_at=? WHERE id=?
            """,
            (
                json.dumps(result["sources"], ensure_ascii=False),
                float(result.get("evidence_confidence") or 0),
                _now(),
                term_id,
            ),
        )
    return result


def research_candidates(report: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    researched = []
    terms = list_terms(
        report.get("project_id"),
        report.get("source_language"),
        report.get("target_language"),
    )
    by_normalized = {
        term["normalized_term"]: term
        for term in terms
        if term.get("project_id") == report.get("project_id")
    }
    for candidate in report.get("candidates", []):
        if len(researched) >= limit:
            break
        if not candidate.get("needs_web_research"):
            continue
        record = by_normalized.get(candidate.get("normalized_term"))
        if not record:
            continue
        try:
            researched.append(research_term(int(record["id"])))
        except Exception as exc:
            researched.append({"term": candidate.get("term"), "sources": [], "errors": [str(exc)]})
    return researched


def save_context_suggestions(
    project_id: str,
    source_language: str,
    target_language: str,
    glossary: dict[str, Any],
) -> None:
    existing = {
        term["normalized_term"]: term
        for term in list_terms(project_id, source_language, target_language)
        if term.get("project_id") == project_id
    }
    for source_term, target_term in glossary.items():
        source_text = str(source_term or "").strip()
        target_text = str(target_term or "").strip()
        if not source_text or not target_text:
            continue
        previous = existing.get(source_text.casefold())
        if previous and previous.get("status") in {"approved", "locked"}:
            continue
        upsert_term(
            {
                "source_term": source_text,
                "source_language": source_language,
                "target_language": target_language,
                "project_id": project_id,
                "scope": "project",
                "category": previous.get("category") if previous else "",
                "definition": previous.get("definition") if previous else "",
                "preferred_translation": target_text,
                "status": "suggested",
                "confidence": previous.get("confidence") if previous else 0.45,
                "suspicion_score": previous.get("suspicion_score") if previous else 0,
                "occurrences": previous.get("occurrences") if previous else 0,
                "examples": previous.get("examples") if previous else [],
                "sources": previous.get("sources") if previous else [],
            }
        )


def remember_translations(
    project_id: str,
    source_language: str,
    target_language: str,
    pairs: list[tuple[str, str]],
) -> None:
    timestamp = _now()
    with _connect() as connection:
        connection.executemany(
            """
            INSERT INTO translation_memory(
                project_id,source_language,target_language,source_text,translated_text,approved,created_at
            ) VALUES(?,?,?,?,?,0,?)
            """,
            [
                (project_id, source_language, target_language, source, translated, timestamp)
                for source, translated in pairs
                if source.strip() and translated.strip()
            ],
        )


def remember_approved_translation(
    project_id: str,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str,
) -> None:
    if not source_text.strip() or not translated_text.strip():
        return
    timestamp = _now()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE translation_memory SET approved=0
            WHERE project_id=? AND source_language=? AND target_language=? AND source_text=?
            """,
            (project_id, source_language, target_language, source_text),
        )
        connection.execute(
            """
            INSERT INTO translation_memory(
                project_id,source_language,target_language,source_text,translated_text,approved,created_at
            ) VALUES(?,?,?,?,?,1,?)
            """,
            (project_id, source_language, target_language, source_text, translated_text, timestamp),
        )


def approved_memory(
    project_id: str,
    source_language: str,
    target_language: str,
) -> dict[str, str]:
    initialise()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT source_text, translated_text FROM translation_memory
            WHERE project_id=? AND source_language=? AND target_language=? AND approved=1
            ORDER BY id
            """,
            (project_id, source_language, target_language),
        ).fetchall()
    return {str(row["source_text"]): str(row["translated_text"]) for row in rows}
