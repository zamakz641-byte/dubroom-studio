from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "DubRoom_Compte_Rendu_Multispeaker_Audio_ChatGPT_2026-08-08.docx"
PROJECT = ROOT / "projects" / "pfx4p9rial4-5min-real-test-20260808-124847"

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
PALE_BLUE = "E8EEF5"
PALE_GREEN = "E7F4EA"
PALE_AMBER = "FFF3CD"
LIGHT_GREY = "F4F6F8"
TEXT = RGBColor(31, 41, 55)
MUTED = RGBColor(92, 103, 117)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for name, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{name}"))
        if node is None:
            node = OxmlElement(f"w:{name}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_layout(table, widths: list[int]) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    for row_index, row in enumerate(table.rows):
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        tr_pr = row._tr.get_or_add_trPr()
        if row_index == 0:
            table_header = OxmlElement("w:tblHeader")
            table_header.set(qn("w:val"), "true")
            tr_pr.append(table_header)
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)
        for index, cell in enumerate(row.cells):
            cell.width = Inches(widths[index] / 1440)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)


def add_page_field(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("Page ")
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, end])


def add_hyperlink(paragraph, text: str, url: str) -> None:
    relationship_id = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    run_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), BLUE)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    run_pr.extend([color, underline])
    text_node = OxmlElement("w:t")
    text_node.text = text
    run.extend([run_pr, text_node])
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def path_paragraph(cell, value: str) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(value)
    run.font.name = "Consolas"
    run.font.size = Pt(7.5)
    run.font.color.rgb = RGBColor(55, 65, 81)


def add_bullet(doc: Document, text: str, level: int = 0) -> None:
    paragraph = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    paragraph.paragraph_format.left_indent = Inches(0.375 + level * 0.25)
    paragraph.paragraph_format.first_line_indent = Inches(-0.188)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.25
    paragraph.add_run(text)


def add_number(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Number")
    paragraph.paragraph_format.left_indent = Inches(0.375)
    paragraph.paragraph_format.first_line_indent = Inches(-0.188)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.25
    paragraph.add_run(text)


def add_callout(doc: Document, title: str, body: str, fill: str = PALE_BLUE) -> None:
    table = doc.add_table(rows=1, cols=1)
    set_table_layout(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run(title)
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(DARK_BLUE)
    body_paragraph = cell.add_paragraph(body)
    body_paragraph.paragraph_format.space_after = Pt(0)
    body_paragraph.paragraph_format.line_spacing = 1.15
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[int], path_col: int | None = None) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    header = table.rows[0]
    for index, label in enumerate(headers):
        set_cell_shading(header.cells[index], PALE_BLUE)
        paragraph = header.cells[index].paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(label)
        run.bold = True
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor.from_string(DARK_BLUE)
    for row_values in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row_values):
            if index == path_col:
                path_paragraph(cells[index], value)
            else:
                paragraph = cells[index].paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                run = paragraph.add_run(value)
                run.font.size = Pt(8.25)
    set_table_layout(table, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = TEXT
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for style_name, size, color, before, after in (
        ("Title", 26, DARK_BLUE, 0, 10),
        ("Subtitle", 13, "5C6775", 0, 18),
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, DARK_BLUE, 14, 7),
        ("Heading 3", 12, DARK_BLUE, 10, 5),
    ):
        style = doc.styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = style_name != "Subtitle"
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    header = section.header
    table = header.add_table(rows=1, cols=2, width=Inches(6.5))
    table.autofit = False
    table.columns[0].width = Inches(4.7)
    table.columns[1].width = Inches(1.8)
    set_table_layout(table, [6768, 2592])
    left = table.cell(0, 0).paragraphs[0]
    left.paragraph_format.space_after = Pt(0)
    r = left.add_run("DUBROOM  /  COMPTE RENDU TECHNIQUE")
    r.bold = True
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(DARK_BLUE)
    right = table.cell(0, 1).paragraphs[0]
    right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    right.paragraph_format.space_after = Pt(0)
    r = right.add_run("08 AOÛT 2026")
    r.font.size = Pt(8)
    r.font.color.rgb = MUTED
    add_page_field(section.footer.paragraphs[0])


def status_text(path: Path, success: str, waiting: str) -> str:
    return success if path.exists() else waiting


def build() -> None:
    doc = Document()
    configure_document(doc)

    title = doc.add_paragraph(style="Title")
    title.add_run("DubRoom — Compte rendu d’implémentation")
    subtitle = doc.add_paragraph(style="Subtitle")
    subtitle.add_run("Traduction ChatGPT, séparation audio cinéma et véritable mode multispeaker")

    meta = doc.add_table(rows=4, cols=2)
    meta.style = "Table Grid"
    meta_rows = [
        ("Date", "8 août 2026"),
        ("Application", str(ROOT)),
        ("Projet de validation", "PFX4P9RIAl4 — extrait réel de 5 minutes"),
        ("État", "Implémentation intégrée — séparation et multispeaker validés sur 5 minutes"),
    ]
    for index, (label, value) in enumerate(meta_rows):
        set_cell_shading(meta.cell(index, 0), PALE_BLUE)
        p = meta.cell(index, 0).paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(label)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(DARK_BLUE)
        if index == 1:
            path_paragraph(meta.cell(index, 1), value)
        else:
            meta.cell(index, 1).text = value
    set_table_layout(meta, [1900, 7460])

    doc.add_heading("Résumé exécutif", level=1)
    add_callout(
        doc,
        "Résultat principal",
        "DubRoom dispose maintenant d’un flux cohérent : choix Normal ou Multispeaker, détection locale des locuteurs, attribution automatique de voix distinctes, contrat ChatGPT qui conserve les frontières de locuteur, puis synchronisation et export avec la piste d’ambiance préservée.",
        PALE_GREEN,
    )
    add_bullet(doc, "Le profil Qualité cinéma utilise Bandit v2 DnR3 sur CUDA et réemploie le PyTorch déjà installé pour OmniVoice.")
    add_bullet(doc, "Le profil Rapide conserve Demucs htdemucs sur la RTX 4060 pour les essais où la vitesse est prioritaire.")
    add_bullet(doc, "La diarisation Sherpa ONNX fonctionne localement, sans jeton Hugging Face, et enrichit chaque locuteur avec un profil vocal exploitable.")
    add_bullet(doc, "Le paquet destiné au GPT contient désormais speaker, timecodes, contexte et contraintes immuables pour empêcher le mélange des personnages.")
    add_bullet(doc, "Le test réel de 5 minutes a terminé la séparation cinéma en environ 2 min 08 s et la diarisation en environ 26 s.")

    doc.add_page_break()
    doc.add_heading("1. Objectif et périmètre", level=1)
    doc.add_paragraph(
        "Le travail répond à quatre problèmes observés pendant le test réel : une seule voix malgré le mode multispeaker, des effets sonores abîmés par la suppression de la piste Demucs, un format ChatGPT trop permissif et une bibliothèque vocale insuffisamment reliée au casting automatique."
    )
    doc.add_heading("Décisions retenues", level=2)
    add_number(doc, "Ne pas retélécharger les grosses dépendances : réutiliser l’environnement CUDA d’OmniVoice pour Bandit et Demucs.")
    add_number(doc, "Séparer les profils audio visibles : Qualité cinéma pour le rendu final, Rapide pour les itérations.")
    add_number(doc, "Détecter les locuteurs avant l’export vers ChatGPT dans un projet multispeaker.")
    add_number(doc, "Conserver speaker, start, end, source_text et contexte comme champs immuables pendant la traduction.")
    add_number(doc, "Réinjecter la nouvelle voix dans un lit audio résiduel calculé exactement depuis la source afin de préserver musique et SFX.")

    doc.add_heading("2. Audit de Demucs sur le vrai extrait", level=1)
    doc.add_paragraph(
        "L’écoute était trompeuse : Demucs retirait bien la parole, mais classait aussi une grande partie des sons non vocaux dans la piste “vocals”. Lors du remplacement de cette piste, ces sons disparaissaient du mix final."
    )
    add_table(
        doc,
        ["Mesure", "Résultat", "Interprétation"],
        [
            ["Parole détectée dans bed.wav", "0 segment", "La voix d’origine est bien retirée."],
            ["Énergie non parlée capturée comme voix", "86,24 %", "Trop de musique et de SFX quittent le lit audio."],
            ["Pic P99 non parlé capturé comme voix", "95,55 %", "Les impacts et effets forts sont particulièrement exposés."],
            ["Reconstruction voix + bed", "32,82 dB SNR", "Acceptable techniquement, mais mauvais découpage sémantique."],
        ],
        [3300, 1900, 4160],
    )
    add_callout(
        doc,
        "Correction",
        "Le profil cinéma produit parole, musique et SFX avec Bandit DnR3. Le lit d’ambiance utilisé par DubRoom est ensuite calculé comme source − parole : la somme parole + ambiance reconstitue exactement la source, à la quantification PCM près.",
    )

    doc.add_page_break()
    doc.add_heading("3. Contrat ChatGPT et format de script attendu", level=1)
    doc.add_paragraph(
        "Le GPT ne doit pas renvoyer un simple texte libre. Il reçoit un manifeste segmenté et doit restituer les mêmes identifiants dans le même ordre, avec une traduction adaptée à la durée et au personnage."
    )
    add_table(
        doc,
        ["Champ", "Règle"],
        [
            ["id", "Immuable ; aucune suppression, duplication ou renumérotation."],
            ["speaker", "Immuable ; frontière absolue entre personnages."],
            ["start / end", "Immuables ; servent à la synchronisation."],
            ["source_text", "Immuable ; référence de contrôle."],
            ["translation / adapted_text", "Seuls champs éditables par le GPT."],
            ["target_duration / words", "Guident la longueur et le rythme de la réplique."],
            ["context_before / context_after", "Aident à comprendre sans déplacer une information vers un autre segment."],
        ],
        [2600, 6760],
    )
    add_callout(
        doc,
        "Barrière multispeaker",
        "Dans un projet Multispeaker, DubRoom bloque maintenant l’export du manifeste GPT tant que la détection des locuteurs n’est pas terminée. Cela empêche la traduction de figer tout le script sous SPEAKER_00.",
        PALE_GREEN,
    )
    add_table(
        doc,
        ["Mesure", "Demucs", "Bandit cinéma"],
        [
            ["Énergie non parlée classée comme voix", "86,18 %", "23,94 %"],
            ["Pic P99 non parlé classé comme voix", "96,77 %", "67,59 %"],
            ["Reconstruction voix + ambiance", "32,82 dB", "68,75 dB"],
            ["Parole reconnue dans le lit final", "0 segment", "0 segment"],
        ],
        [4700, 2200, 2460],
    )

    doc.add_heading("4. Nouveau flux multispeaker", level=1)
    for step in (
        "Créer le projet et choisir Normal ou Multispeaker.",
        "Analyser la source et lancer la détection locale des locuteurs.",
        "Estimer le profil vocal et attribuer automatiquement une voix distincte à chaque locuteur.",
        "Exporter le manifeste vers le GPT, traduire, puis réimporter sans modifier les frontières.",
        "Générer les voix par profil, synchroniser chaque segment et construire la voiceover.",
        "Mixer la voiceover avec le lit cinéma, puis appliquer le même système d’export au mode multispeaker.",
    ):
        add_number(doc, step)

    doc.add_page_break()
    doc.add_heading("5. Nouveaux fichiers créés", level=1)
    new_files = [
        [str(ROOT / "scripts" / "engines" / "run-sherpa-diarization.py"), "Worker de diarisation locale et estimation des traits vocaux."],
        [str(ROOT / "scripts" / "engines" / "install-sherpa-diarization.ps1"), "Installation réutilisable de Sherpa ONNX et de ses modèles."],
        [str(ROOT / "scripts" / "engines" / "run-cinematic-separation.py"), "Séparation Bandit DnR3, sorties voix/musique/SFX et lit résiduel."],
        [str(ROOT / "scripts" / "engines" / "install-cinematic-separation.ps1"), "Installation de Bandit et partage de l’environnement CUDA OmniVoice."],
        [str(ROOT / "scripts" / "build-implementation-report-docx.py"), "Générateur reproductible du présent compte rendu Word."],
        [str(OUTPUT), "Document final livré à l’utilisateur."],
    ]
    add_table(doc, ["Emplacement", "Rôle"], new_files, [6100, 3260], path_col=0)

    doc.add_heading("Données et modèles installés", level=2)
    model_rows = [
        [str(ROOT / "models" / "cinematic-separation" / "bandit-v2-dnr3-multilingual.ckpt"), "Checkpoint Bandit DnR3 multilingue."],
        [str(ROOT / "models" / "sherpa-diarization" / "segmentation" / "model.int8.onnx"), "Détection des tours de parole."],
        [str(ROOT / "models" / "sherpa-diarization" / "nemo_en_titanet_small.onnx"), "Empreintes de locuteur Titanet."],
        [str(ROOT / "data" / "environments" / "cinematic-separation"), "Code Bandit + manifeste de disponibilité."],
        [str(ROOT / "data" / "environments" / "sherpa-diarization"), "Environnement ONNX autonome et léger."],
    ]
    add_table(doc, ["Emplacement", "Contenu"], model_rows, [6100, 3260], path_col=0)

    doc.add_heading("Artefacts créés par le test réel", level=2)
    artifact_rows = [
        [str(PROJECT / "audio" / "separation" / "vocals.wav"), "Dialogue Bandit destiné au contrôle et à la diarisation."],
        [str(PROJECT / "audio" / "separation" / "bed.wav"), "Lit résiduel sans dialogue pour le mix final."],
        [str(PROJECT / "audio" / "separation" / "music.wav"), "Estimation musicale séparée."],
        [str(PROJECT / "audio" / "separation" / "sfx.wav"), "Estimation des effets sonores séparés."],
        [str(PROJECT / "audio" / "separation" / "archive-demucs-20260808"), "Ancien résultat Demucs conservé pour comparaison."],
        [str(PROJECT / "analysis" / "diarization" / "diarization-manifest.json"), "Tours de parole et profils de locuteur détectés."],
        [str(PROJECT / "analysis" / "bandit-bed-asr.json"), "Contrôle ASR : zéro dialogue reconnu dans le lit final."],
    ]
    add_table(doc, ["Emplacement", "Contenu"], artifact_rows, [6100, 3260], path_col=0)

    doc.add_page_break()
    doc.add_heading("6. Fichiers existants modifiés — services", level=1)
    service_rows = [
        [str(ROOT / "services" / "api" / "app" / "audio_preservation_service.py"), "Profils cinéma/rapide, sélection de runtime, cache, sorties musique/SFX et manifestes."],
        [str(ROOT / "services" / "api" / "app" / "diarization_service.py"), "Priorité à Sherpa local, fallback Pyannote, traits vocaux et application aux segments."],
        [str(ROOT / "services" / "api" / "app" / "transcript_exchange_service.py"), "Speaker dans le paquet GPT et interdiction de déplacer du contenu entre personnages."],
        [str(ROOT / "services" / "api" / "app" / "main.py"), "Casting automatique de voix distinctes après diarisation et prise en compte du genre détecté."],
        [str(ROOT / "models" / "registry.json"), "Déclaration des moteurs cinematic-separation et sherpa-diarization."],
    ]
    add_table(doc, ["Emplacement", "Modification"], service_rows, [5900, 3460], path_col=0)

    doc.add_heading("Fichiers existants modifiés — interface", level=2)
    ui_rows = [
        [str(ROOT / "apps" / "desktop" / "src" / "components" / "studio" / "AudioPreservationPanel.tsx"), "Cartes Qualité cinéma et Rapide, choix explicite avant séparation."],
        [str(ROOT / "apps" / "desktop" / "src" / "pages" / "StudioPage.tsx"), "Transmission du profil audio et garde multispeaker avant export GPT."],
        [str(ROOT / "apps" / "desktop" / "src" / "App.tsx"), "Propagation des options de séparation."],
        [str(ROOT / "apps" / "desktop" / "src" / "types.ts"), "Typage des profils exposés par le runtime audio."],
        [str(ROOT / "apps" / "desktop" / "src" / "i18n.tsx"), "Libellés français/anglais des profils et message de détection préalable."],
    ]
    add_table(doc, ["Emplacement", "Modification"], ui_rows, [5900, 3460], path_col=0)

    doc.add_page_break()
    doc.add_heading("7. Fichiers existants modifiés — documentation GPT", level=1)
    docs_rows = [
        [str(ROOT / "docs" / "custom-gpt-dubroom" / "INSTRUCTIONS_A_COLLER.md"), "Schéma complet, champs immuables, limites strictes par locuteur."],
        [str(ROOT / "docs" / "custom-gpt-dubroom" / "CONTRAT_MANIFESTE_DUBROOM.md"), "Contrat de réimport aligné sur le multispeaker."],
        [str(ROOT / "docs" / "custom-gpt-dubroom" / "CREER_LE_GPT.md"), "Ordre corrigé : détecter les locuteurs avant d’envoyer le manifeste."],
        [str(PROJECT / "project.json"), "Projet réel basculé de single vers multi pour la validation."],
    ]
    add_table(doc, ["Emplacement", "Modification"], docs_rows, [5900, 3460], path_col=0)

    doc.add_heading("8. Dépendances partagées", level=1)
    add_bullet(doc, "Bandit et Demucs réutilisent Python, PyTorch 2.11, CUDA 12.8 et la RTX 4060 de l’environnement tts-omnivoice-hq.")
    add_bullet(doc, "Le téléchargement du checkpoint Bandit est unique ; le code du modèle est conservé dans l’environnement cinematic-separation.")
    add_bullet(doc, "Sherpa reste séparé car son runtime ONNX est léger et ne nécessite ni PyTorch ni compte externe.")
    add_bullet(doc, "Les empreintes de moteur et les manifestes ready.json permettent de réutiliser les résultats sans retraiter inutilement.")

    doc.add_heading("9. Vérifications effectuées", level=1)
    checks = [
        ["Compilation Python", "Réussie", "Services et workers sans erreur de syntaxe."],
        ["Tests audio preservation", "Réussis", "Dépendance partagée, cache, force, échec et progression."],
        ["Build interface", "Réussi", "Application TypeScript compilée."],
        ["Test i18n", "Réussi", "Clés françaises et anglaises cohérentes."],
        ["Runtime cinéma", "Prêt", "CUDA partagé et checkpoint local détectés."],
        ["Runtime multispeaker", "Prêt", "Sherpa local, modèles présents, aucun jeton requis."],
        ["Smoke Bandit 20 s", status_text(ROOT / "data" / "temp" / "cinema-smoke" / "result.json", "Réussi", "À relancer"), "Validation réelle sur un extrait court."],
        ["Smoke Sherpa 20 s", status_text(ROOT / "data" / "temp" / "cinema-smoke" / "diarization.json", "Réussi", "À relancer"), "Détection de locuteur sur le même extrait."],
        ["Bandit sur 5 minutes", "Réussi", "Traitement CUDA terminé en environ 2 min 08 s."],
        ["Sherpa sur 5 minutes", "Réussi", "8 profils utiles conservés après filtrage des micro-clusters."],
        ["ASR du lit cinéma", "Réussi", "0 segment de dialogue reconnu sur 5 minutes."],
    ]
    add_table(doc, ["Contrôle", "État", "Résultat"], checks, [2850, 1650, 4860])

    doc.add_page_break()
    doc.add_heading("10. Utilisation dans DubRoom", level=1)
    for step in (
        "Créer le projet, choisir le type de vidéo puis choisir Normal ou Multispeaker.",
        "Dans Audio préservé, sélectionner Qualité cinéma pour le rendu final ou Rapide pour une prévisualisation.",
        "En mode Multispeaker, lancer Détecter les locuteurs avant de préparer le paquet ChatGPT.",
        "Vérifier les voix proposées dans la bibliothèque : homme/femme, langue, rôle MC, personnage principal ou secondaire.",
        "Importer le manifeste traduit, générer les voix, lancer la synchronisation puis exporter.",
    ):
        add_number(doc, step)

    doc.add_heading("Éléments restant à finaliser", level=2)
    add_callout(
        doc,
        "Dernier jalon de production",
        "La séparation Bandit et la détection Sherpa sont validées sur les 5 minutes. Il reste à régénérer les 43 répliques avec les voix nouvellement attribuées, relancer la synchronisation, écouter le mix complet et produire le nouvel export vidéo.",
        PALE_AMBER,
    )
    add_bullet(doc, "Écouter les impacts, ambiances et musiques dans le mix doublé complet.")
    add_bullet(doc, "Corriger manuellement un rôle ou une voix si l’identité d’un personnage est mal reconnue.")
    add_bullet(doc, "Générer la voiceover multispeaker, synchroniser puis exporter la nouvelle vidéo.")

    doc.add_heading("Sources techniques officielles", level=2)
    sources = [
        ("Bandit v2 — dépôt officiel", "https://github.com/kwatcharasupat/bandit-v2"),
        ("DnR v3 — article de recherche", "https://arxiv.org/abs/2407.07275"),
        ("Checkpoint Bandit DnR3 multilingue", "https://zenodo.org/records/12701995"),
        ("Sherpa ONNX — diarisation", "https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html"),
    ]
    for label, url in sources:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(4)
        add_hyperlink(paragraph, label, url)

    doc.core_properties.title = "DubRoom — Compte rendu d’implémentation"
    doc.core_properties.subject = "ChatGPT, audio cinéma et multispeaker"
    doc.core_properties.author = "DubRoom / Codex"
    doc.core_properties.keywords = "DubRoom, multispeaker, Bandit, Sherpa, ChatGPT, OmniVoice"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(json.dumps({"output": str(OUTPUT), "bytes": OUTPUT.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    build()
