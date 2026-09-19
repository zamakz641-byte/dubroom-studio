# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, os, json, time, shutil, subprocess, webbrowser
from pathlib import Path
from datetime import datetime

ROOT = Path(sys.argv[1]).resolve()
LIB = ROOT / "data" / "voice-library" / "omnivoice"
VOICES_DIR = LIB / "voices"
CATALOG = LIB / "voice_catalog.json"
IMPORT_CFG = ROOT / "scripts" / "engines" / "anime-voice-import-profiles.json"
SAMPLE_RATE = 24000

OFFICIAL_TAGS = {
    "laughter": "[laughter]",
    "sigh": "[sigh]",
    "confirmation_en": "[confirmation-en]",
    "question_en": "[question-en]",
    "question_ah": "[question-ah]",
    "question_oh": "[question-oh]",
    "question_ei": "[question-ei]",
    "question_yi": "[question-yi]",
    "surprise_ah": "[surprise-ah]",
    "surprise_oh": "[surprise-oh]",
    "surprise_wa": "[surprise-wa]",
    "surprise_yo": "[surprise-yo]",
    "dissatisfaction_hnn": "[dissatisfaction-hnn]",
}

QUICK_TESTS = {
    "neutral_fr": "Le portail vient de s'ouvrir. Reste derriere moi, je vais verifier ce qu'il y a de l'autre cote.",
    "laughter": "[laughter] Tu pensais vraiment que j'allais perdre ? Cette fois, c'est moi qui ai gagne.",
    "surprise": "[surprise-oh] Je ne m'attendais absolument pas a voir ca ici.",
    "sigh": "[sigh] C'est enfin termine. On peut rentrer maintenant.",
}

FULL_COMMON = {
    **QUICK_TESTS,
    "question": "[question-en] Tu es certain que c'est la bonne porte ?",
    "dissatisfaction": "[dissatisfaction-hnn] Tu appelles vraiment ca un plan ? On aurait pu tous y rester.",
    "anger": "Ne prononce plus son nom. La prochaine fois que tu le menaces, je ne te laisserai pas repartir.",
    "sadness": "Je lui avais promis de revenir. Maintenant, il ne reste plus personne a qui tenir cette promesse.",
    "fear": "N'avance pas. Quelque chose nous observe depuis l'obscurite, et je ne pense pas que ce soit humain.",
    "tenderness": "Tu peux te reposer maintenant. Je reste ici, et je ne laisserai personne te faire de mal.",
}

STYLE_TESTS = {
    "hero": "Meme si je dois continuer seul, j'irai jusqu'au bout. Je refuse d'abandonner maintenant.",
    "calm": "Reste calme. Observe d'abord son mouvement, puis attaque seulement quand il ouvre sa garde.",
    "charismatic": "Tu as fait tout ce chemin pour me defier ? Tres bien. Montre-moi au moins quelque chose d'interessant.",
    "villain": "Tu peux courir si ca t'amuse. La sortie est deja condamnee, et je sais exactement ou tu vas aller.",
    "female_soft": "Tout va bien. Respire doucement et reste pres de moi, personne ne te fera de mal ici.",
    "female_strong": "Je n'ai besoin de personne pour gagner ce combat. Ecarte-toi et regarde bien.",
    "child": "Je crois que j'ai entendu quelque chose derriere la porte. Tu viens avec moi ?",
}

PROFILES = [
  {
    "id": "ANM01",
    "name": "Anime - Young Hero (Yuji Ref)",
    "character": "Yuji Itadori",
    "gender": "male",
    "age": "young adult",
    "pitch": "moderate pitch",
    "traits": [
      "heroic",
      "energetic",
      "friendly",
      "expressive"
    ],
    "roles": [
      "protagonist",
      "young_male",
      "hero"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583344-jujutsu-kaisen-cursed-clash-pc-yuji-itadori-japanese-voice",
    "test_style": "hero"
  },
  {
    "id": "ANM02",
    "name": "Anime - Calm Protagonist (Megumi Ref)",
    "character": "Megumi Fushiguro",
    "gender": "male",
    "age": "young adult",
    "pitch": "moderate pitch",
    "traits": [
      "calm",
      "serious",
      "reserved",
      "cold"
    ],
    "roles": [
      "protagonist",
      "rival",
      "young_male"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583336-jujutsu-kaisen-cursed-clash-pc-megumi-fushiguro-japanese-voice",
    "test_style": "calm"
  },
  {
    "id": "ANM03",
    "name": "Anime - Charismatic Male (Gojo Ref)",
    "character": "Satoru Gojo",
    "gender": "male",
    "age": "young adult",
    "pitch": "moderate pitch",
    "traits": [
      "charismatic",
      "confident",
      "playful",
      "powerful"
    ],
    "roles": [
      "mentor",
      "protagonist",
      "leader"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583353-jujutsu-kaisen-cursed-clash-pc-satoru-gojo-young-japanese-voice/",
    "test_style": "charismatic"
  },
  {
    "id": "ANM04",
    "name": "Anime - Deep Villain (Sukuna Ref)",
    "character": "Ryomen Sukuna",
    "gender": "male",
    "age": "adult",
    "pitch": "low pitch",
    "traits": [
      "deep",
      "dominant",
      "cold",
      "threatening"
    ],
    "roles": [
      "antagonist",
      "villain",
      "boss"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583340-jujutsu-kaisen-cursed-clash-pc-ryomen-sukuna-japanese-voice",
    "test_style": "villain"
  },
  {
    "id": "ANM05",
    "name": "Anime - Unstable Villain (Mahito Ref)",
    "character": "Mahito",
    "gender": "male",
    "age": "young adult",
    "pitch": "moderate pitch",
    "traits": [
      "playful",
      "unstable",
      "creepy",
      "expressive"
    ],
    "roles": [
      "antagonist",
      "villain",
      "trickster"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583334-jujutsu-kaisen-cursed-clash-pc-mahito-japanese-voice/",
    "test_style": "villain"
  },
  {
    "id": "ANF01",
    "name": "Anime - Soft Female (Shinobu Ref)",
    "character": "Shinobu Kocho",
    "gender": "female",
    "age": "young adult",
    "pitch": "high pitch",
    "traits": [
      "soft",
      "calm",
      "elegant",
      "controlled"
    ],
    "roles": [
      "female_lead",
      "support",
      "healer"
    ],
    "source_url": "https://www.101soundboards.com/boards/1584153-demon-slayer-kimetsu-no-yaiba-the-hinokami-chronicles-2-pc-shinobu-kocho-japanese",
    "test_style": "female_soft"
  },
  {
    "id": "ANF02",
    "name": "Anime - Strong Young Female (Nobara Ref)",
    "character": "Nobara Kugisaki",
    "gender": "female",
    "age": "young adult",
    "pitch": "high pitch",
    "traits": [
      "strong",
      "confident",
      "energetic",
      "sharp"
    ],
    "roles": [
      "female_lead",
      "fighter",
      "young_female"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583337-jujutsu-kaisen-cursed-clash-pc-nobara-kugisaki-japanese-voice",
    "test_style": "female_strong"
  },
  {
    "id": "ANF03",
    "name": "Anime - Young Girl (Rika Ref)",
    "character": "Rika",
    "gender": "female",
    "age": "child",
    "pitch": "high pitch",
    "traits": [
      "young",
      "emotional",
      "bright",
      "intense"
    ],
    "roles": [
      "young_girl",
      "child",
      "secondary"
    ],
    "source_url": "https://www.101soundboards.com/boards/1583367-jujutsu-kaisen-cursed-clash-pc-rika-japanese-voice",
    "test_style": "child"
  },
  {
    "id": "ANF04",
    "name": "Anime - Child Girl (Hanako Ref)",
    "character": "Hanako Kamado",
    "gender": "female",
    "age": "child",
    "pitch": "high pitch",
    "traits": [
      "child",
      "innocent",
      "soft",
      "bright"
    ],
    "roles": [
      "child",
      "young_girl",
      "family"
    ],
    "source_url": "https://www.101soundboards.com/boards/1584175-demon-slayer-kimetsu-no-yaiba-the-hinokami-chronicles-2-pc-hanako-kamado-japanese",
    "test_style": "child"
  },
  {
    "id": "ANF05",
    "name": "Anime - Warm Adult Female (Kie Ref)",
    "character": "Kie Kamado",
    "gender": "female",
    "age": "adult",
    "pitch": "moderate pitch",
    "traits": [
      "warm",
      "mature",
      "calm",
      "motherly"
    ],
    "roles": [
      "mother",
      "adult_female",
      "support"
    ],
    "source_url": "https://www.101soundboards.com/boards/1584176-demon-slayer-kimetsu-no-yaiba-the-hinokami-chronicles-2-pc-kie-kamado-japanese",
    "test_style": "female_soft"
  }
]

def pause():
    input("\nAppuie sur Entree pour continuer...")

def ensure_dirs():
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_CFG.parent.mkdir(parents=True, exist_ok=True)
    IMPORT_CFG.write_text(json.dumps({"version":1,"profiles":PROFILES}, ensure_ascii=False, indent=2), encoding="utf-8")

def backup_catalog():
    if CATALOG.exists():
        backup_dir = LIB / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(CATALOG, backup_dir / f"voice_catalog-before-anime-{stamp}.json")

def open_sources(profiles=None):
    profiles = profiles or PROFILES
    for p in profiles:
        print(f"Ouverture source {p['id']} - {p['character']}")
        webbrowser.open(p["source_url"], new=2)
        time.sleep(0.35)

def pick_audio(profile):
    # Windows GUI file picker. Multiple clips allowed.
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        title = f"{profile['id']} - {profile['character']} : selectionne 1 a 4 clips propres (3-10 s total)"
        files = filedialog.askopenfilenames(
            title=title,
            filetypes=[
                ("Audio", "*.wav *.flac *.ogg *.mp3 *.m4a *.aac *.opus"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        root.destroy()
        return [Path(x) for x in files]
    except Exception as exc:
        print(f"[WARN] Fenetre de selection indisponible: {exc}")
        raw = input("Colle le chemin du fichier audio: ").strip().strip('"')
        return [Path(raw)] if raw else []

def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return Path(p)
    candidates = [
        ROOT / "ffmpeg.exe",
        ROOT / "bin" / "ffmpeg.exe",
        ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        ROOT / "data" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        ROOT / "data" / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def normalize_reference(files, out_path):
    import numpy as np
    import soundfile as sf
    import torch

    chunks = []
    target_total = int(SAMPLE_RATE * 9.5)
    ffmpeg = find_ffmpeg()

    for idx, src in enumerate(files):
        if not src.exists():
            continue

        wav = None
        sr = None

        # First try soundfile.
        try:
            data, sr = sf.read(str(src), always_2d=False)
            if data.ndim > 1:
                data = data.mean(axis=1)
            wav = torch.tensor(data, dtype=torch.float32)
        except Exception:
            pass

        # Then torchaudio.
        if wav is None:
            try:
                import torchaudio
                t, sr = torchaudio.load(str(src))
                if t.ndim == 2:
                    t = t.mean(dim=0)
                wav = t.float()
            except Exception:
                pass

        # Last fallback: ffmpeg -> temp wav.
        if wav is None and ffmpeg:
            tmp = out_path.parent / f".tmp_{idx}.wav"
            subprocess.run(
                [str(ffmpeg), "-y", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), str(tmp)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            data, sr = sf.read(str(tmp), always_2d=False)
            tmp.unlink(missing_ok=True)
            wav = torch.tensor(data, dtype=torch.float32)

        if wav is None:
            raise RuntimeError(
                f"Impossible de lire {src.name}. Telecharge de preference la version WAV, "
                "ou installe/ajoute FFmpeg au PATH."
            )

        # Resample with torch interpolation to avoid adding dependencies.
        if int(sr) != SAMPLE_RATE:
            n = max(1, round(len(wav) * SAMPLE_RATE / int(sr)))
            wav = torch.nn.functional.interpolate(
                wav[None, None, :], size=n, mode="linear", align_corners=False
            )[0,0]

        # Remove outer near-silence only.
        abswav = wav.abs()
        if len(abswav):
            threshold = max(float(abswav.max()) * 0.015, 0.001)
            nz = torch.where(abswav > threshold)[0]
            if len(nz):
                pad = int(SAMPLE_RATE * 0.08)
                a = max(0, int(nz[0]) - pad)
                b = min(len(wav), int(nz[-1]) + pad)
                wav = wav[a:b]

        chunks.append(wav)
        if sum(len(x) for x in chunks) >= target_total:
            break

    if not chunks:
        raise RuntimeError("Aucun audio valide selectionne.")

    # Small 80ms separation between clips so words don't collide.
    sep = torch.zeros(int(SAMPLE_RATE * 0.08))
    merged_parts = []
    for i, c in enumerate(chunks):
        if i:
            merged_parts.append(sep)
        merged_parts.append(c)
    wav = torch.cat(merged_parts)[:target_total]

    # Normalize conservatively.
    peak = float(wav.abs().max()) if len(wav) else 0.0
    if peak > 0:
        wav = wav * min(0.93 / peak, 4.0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), wav.numpy(), SAMPLE_RATE)
    return len(wav) / SAMPLE_RATE

def load_model():
    import torch
    from omnivoice import OmniVoice
    print("\nChargement OmniVoice une seule fois sur CUDA...")
    print("CUDA:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU :", torch.cuda.get_device_name(0))
        device = "cuda:0"
        dtype = torch.float16
    else:
        print("[WARN] CUDA non disponible, passage CPU.")
        device = "cpu"
        dtype = torch.float32

    # ref_text=None triggers OmniVoice's built-in Whisper auto-transcription.
    # If its ASR is not cached, OmniVoice may need network access once.
    return OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map=device,
        dtype=dtype,
        asr_device="cpu",   # avoids consuming extra VRAM during prompt transcription
    )

def save_prompt(prompt, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(prompt, "save") and callable(prompt.save):
        prompt.save(str(path))
        return "VoiceClonePrompt.save"
    import torch
    torch.save(prompt, str(path))
    return "torch.save"

def generate_audio(model, prompt, text, out_path, steps=32):
    import numpy as np
    import soundfile as sf
    audio = model.generate(
        text=text,
        voice_clone_prompt=prompt,
        num_step=steps,
        speed=1.0,
    )
    x = audio[0] if isinstance(audio, (list, tuple)) else audio
    try:
        import torch
        if torch.is_tensor(x):
            x = x.detach().float().cpu().numpy()
    except Exception:
        pass
    x = np.asarray(x).squeeze()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), x, SAMPLE_RATE)

def build_tests(model, prompt, profile, voice_dir, mode):
    tests = {}
    if mode == "none":
        return tests
    suite = dict(QUICK_TESTS if mode == "quick" else FULL_COMMON)
    suite["character_style"] = STYLE_TESTS.get(profile.get("test_style"), STYLE_TESTS["hero"])
    tests_dir = voice_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for i, (test_id, text) in enumerate(suite.items(), 1):
        print(f"    Test {i}/{len(suite)} : {test_id}")
        p = tests_dir / f"{test_id}.wav"
        try:
            t0 = time.perf_counter()
            generate_audio(model, prompt, text, p, steps=32)
            tests[test_id] = {
                "path": str(p.relative_to(LIB)),
                "text": text,
                "status": "generated",
                "generation_seconds": round(time.perf_counter()-t0, 3),
            }
        except Exception as exc:
            tests[test_id] = {"path": str(p.relative_to(LIB)), "text": text, "status":"failed","error":str(exc)}
            print("      [WARN]", exc)
    return tests

def merge_catalog(records):
    existing = {}
    root_payload = {}
    if CATALOG.exists():
        try:
            root_payload = json.loads(CATALOG.read_text(encoding="utf-8"))
            existing = root_payload.get("voices", {})
        except Exception:
            root_payload = {}
            existing = {}
    for r in records:
        existing[r["id"]] = {
            "id": r["id"],
            "name": r["name"],
            "gender": r["gender"],
            "age": r["age"],
            "pitch": r["pitch"],
            "traits": r.get("traits", []),
            "roles": r.get("roles", []),
            "reference_path": r["reference_path"],
            "prompt_path": r["prompt_path"],
            "enabled": True,
            "locked": False,
        }
    payload = {
        **root_payload,
        "version": 1,
        "engine": "omnivoice",
        "sample_rate": SAMPLE_RATE,
        "official_expressive_controls": OFFICIAL_TAGS,
        "voices": existing,
        "last_anime_import": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = CATALOG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CATALOG)

def import_profiles(selected_profiles, test_mode):
    ensure_dirs()
    backup_catalog()

    # Select audio BEFORE model load to avoid holding VRAM while browsing.
    selections = []
    for idx, profile in enumerate(selected_profiles, 1):
        print("\n" + "="*72)
        print(f"[{idx}/{len(selected_profiles)}] {profile['id']} - {profile['character']}")
        print("Source:", profile["source_url"])
        choice = input("Ouvrir la page source dans le navigateur ? [O/n] ").strip().lower()
        if choice not in ("n","non","no"):
            webbrowser.open(profile["source_url"], new=2)
        print("Selectionne ensuite 1 a 4 clips propres. Annuler = ignorer cette voix.")
        files = pick_audio(profile)
        if files:
            selections.append((profile, files))
            print("Selection:", ", ".join(p.name for p in files))
        else:
            print("Ignoree.")

    if not selections:
        print("\nAucun fichier selectionne. Rien n'a ete modifie.")
        return

    # Build normalized refs first.
    prepared = []
    print("\nPreparation des references...")
    for profile, files in selections:
        voice_dir = VOICES_DIR / profile["id"]
        ref = voice_dir / "reference.wav"
        dur = normalize_reference(files, ref)
        print(f"  {profile['id']}: reference.wav = {dur:.2f}s")
        prepared.append((profile, ref))

    # Load once, then clone all prompts.
    model = load_model()
    records = []
    for idx, (profile, ref) in enumerate(prepared, 1):
        print("\n" + "="*72)
        print(f"CLONAGE [{idx}/{len(prepared)}] {profile['id']} - {profile['character']}")
        voice_dir = VOICES_DIR / profile["id"]
        prompt_path = voice_dir / "prompt.pt"
        profile_path = voice_dir / "profile.json"

        try:
            print("  Auto-transcription de la reference + creation VoiceClonePrompt...")
            prompt = model.create_voice_clone_prompt(ref_audio=str(ref), ref_text=None)
            save_method = save_prompt(prompt, prompt_path)
            print("  prompt.pt OK")
            tests = build_tests(model, prompt, profile, voice_dir, test_mode)

            payload = {
                **profile,
                "engine": "omnivoice",
                "model": "k2-fsa/OmniVoice",
                "origin": "local_anime_reference",
                "private_only": True,
                "reference_text": None,
                "reference_transcription": "auto_by_omnivoice_whisper",
                "reference_path": str(ref.relative_to(LIB)),
                "prompt_path": str(prompt_path.relative_to(LIB)),
                "prompt_save_method": save_method,
                "num_step": 32,
                "sample_rate": SAMPLE_RATE,
                "locked": False,
                "enabled": True,
                "tests": tests,
                "official_expressive_controls": list(OFFICIAL_TAGS.values()),
            }
            profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            records.append(payload)
        except Exception as exc:
            print(f"[ERREUR] {profile['id']}: {exc}")

    if records:
        merge_catalog(records)
        print("\n" + "="*72)
        print("IMPORT TERMINE")
        print("="*72)
        print("Voix ajoutees a DubRoom:")
        for r in records:
            print(f"  {r['id']}  ->  {r['name']}")
        print("\nCatalogue:", CATALOG)
        print("Les profils existants ont ete conserves.")
        print("Redemarre DubRoom s'il etait deja ouvert pour forcer le rechargement du catalogue.")
    else:
        print("\nAucune voix n'a pu etre ajoutee.")

def select_one():
    print("\nProfils disponibles:")
    for i,p in enumerate(PROFILES,1):
        print(f" [{i:02d}] {p['id']} - {p['character']} - {p['name']}")
    raw = input("\nNumero ou ID: ").strip().upper()
    if raw.isdigit():
        i = int(raw)-1
        return PROFILES[i] if 0 <= i < len(PROFILES) else None
    return next((p for p in PROFILES if p["id"] == raw), None)

def show_catalog():
    if not CATALOG.exists():
        print("Catalogue absent.")
        return
    c = json.loads(CATALOG.read_text(encoding="utf-8"))
    voices = c.get("voices", {})
    print(f"\n{len(voices)} voix dans le catalogue OmniVoice:")
    for k,v in voices.items():
        print(f"  {k:8s} | {v.get('name','')}")

def main():
    ensure_dirs()
    while True:
        print("\n" + "="*72)
        print(" DUBROOM - ANIME VOICE DIRECT IMPORTER")
        print("="*72)
        print("Projet :", ROOT)
        print("Library:", LIB)
        print()
        print("[1] Ajouter les 10 voix + tests RAPIDES")
        print("[2] Ajouter les 10 voix + tests EMOTIONS COMPLETS")
        print("[3] Ajouter les 10 voix SANS tests")
        print("[4] Ajouter UNE voix + tests emotions complets")
        print("[5] Ouvrir toutes les pages sources")
        print("[6] Lister les voix actuellement dans DubRoom")
        print("[7] Quitter")
        choice = input("\nChoix : ").strip()

        if choice == "1":
            import_profiles(PROFILES, "quick")
            pause()
        elif choice == "2":
            import_profiles(PROFILES, "full")
            pause()
        elif choice == "3":
            import_profiles(PROFILES, "none")
            pause()
        elif choice == "4":
            p = select_one()
            if p:
                import_profiles([p], "full")
            else:
                print("Profil invalide.")
            pause()
        elif choice == "5":
            open_sources()
            pause()
        elif choice == "6":
            show_catalog()
            pause()
        elif choice == "7":
            return
        else:
            print("Choix invalide.")

if __name__ == "__main__":
    main()
