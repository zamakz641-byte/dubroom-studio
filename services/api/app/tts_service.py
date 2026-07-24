import asyncio
import inspect
from pathlib import Path


class TTSService:
    def __init__(self, models_root: Path):
        self.models_root = models_root
        self.device = "cpu"
        self.kokoro_dir = self.models_root / "Kokoro-82M"
        self.supertonic_dir = self.models_root / "supertonic"
        
        self.kokoro_pipeline = None
        self.kokoro_current_lang = None
        self.supertonic_tts = None
        
        self.kokoro_lang_map = {
            "fr": "f",
            "en": "a",
            "gb": "b",
            "jp": "j",
            "es": "e",
            "zh": "z",
        }
        
        self.default_kokoro_voices = {
            "fr": "af_bella",
            "en": "am_liam",
            "gb": "bf_alice",
            "jp": "jf_alpha",
            "es": "ef_dora",
            "zh": "zf_xiaobei",
        }
        
        self.default_edge_voices = {
            "fr": "fr-FR-DeniseNeural",
            "en": "en-US-GuyNeural",
            "gb": "en-GB-RyanNeural",
            "es": "es-ES-AlvaroNeural",
            "jp": "ja-JP-KeitaNeural",
        }

        self.default_supertonic_voice = "M1"
        self.supertonic_langs = {
            "ar",
            "bg",
            "cs",
            "da",
            "de",
            "el",
            "en",
            "es",
            "et",
            "fi",
            "fr",
            "hi",
            "hr",
            "hu",
            "id",
            "it",
            "ja",
            "ko",
            "lt",
            "lv",
            "na",
            "nl",
            "pl",
            "pt",
            "ro",
            "ru",
            "sk",
            "sl",
            "sv",
            "tr",
            "uk",
            "vi",
        }

    def _get_kokoro(self, lang: str):
        deps = self._load_kokoro_dependencies()
        if not deps:
            return None

        np, sf, torch, KPipeline, KModel = deps
        k_code = self.kokoro_lang_map.get(lang.lower(), "a")
        if self.kokoro_pipeline is None or self.kokoro_current_lang != k_code:
            try:
                config_path = self.kokoro_dir / "config.json"
                model_path = self.kokoro_dir / "kokoro-v1_0.pth"

                if not model_path.exists():
                    print(f"[TTS] Kokoro model not found at {model_path}")
                    return None

                self.device = "cuda" if torch.cuda.is_available() else "cpu"
                model = KModel(config=str(config_path), model=str(model_path)).to(self.device).eval()
                self.kokoro_pipeline = KPipeline(lang_code=k_code, model=model, device=self.device)
                self.kokoro_current_lang = k_code
            except Exception as exc:
                print(f"[TTS] Error loading Kokoro: {exc}")
                return None
        return self.kokoro_pipeline

    def _load_kokoro_dependencies(self):
        try:
            import numpy as np
            import soundfile as sf
            import torch
            from kokoro import KModel, KPipeline
        except ImportError as exc:
            print(f"[TTS] Kokoro dependency missing: {exc}")
            return None
        return np, sf, torch, KPipeline, KModel

    def generate_kokoro(self, text: str, output_path: str, lang: str = "en", voice: str | None = None, speed: float = 1.0) -> bool:
        deps = self._load_kokoro_dependencies()
        if not deps:
            return False
        np, sf, torch, _, _ = deps

        pipeline = self._get_kokoro(lang)
        if not pipeline:
            return False

        voice_name = voice or self.default_kokoro_voices.get(lang, "am_liam")
        if not voice_name.endswith(".pt"):
            voice_path = self.kokoro_dir / "voices" / f"{voice_name}.pt"
        else:
            voice_path = Path(voice_name)
            
        if not voice_path.exists():
            print(f"[TTS] Voice file not found: {voice_path}")
            # Try to fallback to default
            voice_path = self.kokoro_dir / "voices" / f"{self.default_kokoro_voices.get(lang, 'am_liam')}.pt"
            if not voice_path.exists():
                return False

        try:
            all_audio = []
            with torch.inference_mode():
                generator = pipeline(text, voice=str(voice_path), speed=speed)
                for _, _, audio in generator:
                    if audio is not None:
                        all_audio.append(np.asarray(audio))

            if not all_audio:
                return False

            combined_audio = np.concatenate(all_audio)
            sf.write(output_path, combined_audio, 24000)
            return True
        except Exception as exc:
            print(f"[TTS] Kokoro generation error: {exc}")
            return False

    async def _generate_edge_async(self, text: str, output_path: str, voice: str, speed: float = 1.0):
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(f"edge-tts dependency missing: {exc}") from exc

        rate_str = f"{int((speed - 1.0) * 100):+d}%" if speed != 1.0 else "+0%"
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(output_path)

    def generate_edge(self, text: str, output_path: str, lang: str = "en", voice: str | None = None, speed: float = 1.0) -> bool:
        voice_name = voice or self.default_edge_voices.get(lang, "en-US-GuyNeural")
        try:
            asyncio.run(self._generate_edge_async(text, output_path, voice_name, speed))
            return True
        except Exception as exc:
            print(f"[TTS] Edge generation error: {exc}")
            return False

    def _load_supertonic_dependencies(self):
        try:
            from supertonic import TTS
        except ImportError as exc:
            print(f"[TTS] Supertonic dependency missing: {exc}")
            return None
        return TTS

    def _get_supertonic(self):
        TTS = self._load_supertonic_dependencies()
        if not TTS:
            return None
        if self.supertonic_tts is None:
            try:
                # First explicit Supertonic use may download public ONNX assets.
                self.supertonic_dir.mkdir(parents=True, exist_ok=True)
                self.supertonic_tts = TTS(model_dir=self.supertonic_dir, auto_download=True)
            except Exception as exc:
                print(f"[TTS] Error loading Supertonic: {exc}")
                return None
        return self.supertonic_tts

    def _normalise_supertonic_lang(self, lang: str | None) -> str:
        if not lang:
            return "en"
        value = lang.strip().lower()
        aliases = {
            "gb": "en",
            "jp": "ja",
            "jpn": "ja",
            "eng": "en",
            "fra": "fr",
            "fre": "fr",
            "spa": "es",
            # Supertonic 3 public language list does not include Chinese yet.
            "zh": "na",
            "cn": "na",
        }
        value = aliases.get(value, value)
        if "-" in value:
            value = value.split("-", 1)[0]
        return value if value in self.supertonic_langs else "na"

    def _get_supertonic_voice_style(self, tts, voice: str | None):
        voice_value = (voice or self.default_supertonic_voice).strip()
        voice_path = Path(voice_value)

        if voice_path.suffix.lower() == ".json" or voice_path.exists():
            if not voice_path.exists():
                print(f"[TTS] Supertonic voice style not found: {voice_path}")
            else:
                path_method = getattr(tts, "get_voice_style_from_path", None)
                if callable(path_method):
                    try:
                        return path_method(str(voice_path))
                    except Exception as exc:
                        print(f"[TTS] Supertonic custom voice load failed: {exc}")

                load_method = getattr(tts, "load_voice_style", None)
                if callable(load_method):
                    try:
                        return load_method(str(voice_path))
                    except Exception as exc:
                        print(f"[TTS] Supertonic custom voice load failed: {exc}")

                get_voice_style = getattr(tts, "get_voice_style", None)
                if callable(get_voice_style):
                    for kwargs in (
                        {"voice_style_path": str(voice_path)},
                        {"voice_path": str(voice_path)},
                        {"path": str(voice_path)},
                    ):
                        try:
                            return get_voice_style(**kwargs)
                        except TypeError:
                            continue
                        except Exception as exc:
                            print(f"[TTS] Supertonic custom voice load failed: {exc}")
                            break

            print("[TTS] Falling back to Supertonic preset voice M1")
            voice_value = self.default_supertonic_voice

        return tts.get_voice_style(voice_name=voice_value)

    def generate_supertonic(
        self,
        text: str,
        output_path: str,
        lang: str = "en",
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bool:
        tts = self._get_supertonic()
        if not tts:
            return False

        try:
            voice_style = self._get_supertonic_voice_style(tts, voice)
            safe_speed = max(0.7, min(2.0, float(speed or 1.05)))
            kwargs = {
                "text": text,
                "voice_style": voice_style,
                "total_steps": 8,
                "speed": safe_speed,
            }
            synthesize_params = inspect.signature(tts.synthesize).parameters
            if "lang" in synthesize_params:
                kwargs["lang"] = self._normalise_supertonic_lang(lang)
            elif "language" in synthesize_params:
                kwargs["language"] = self._normalise_supertonic_lang(lang)

            wav, _duration = tts.synthesize(**kwargs)
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            tts.save_audio(wav, str(output))
            return True
        except Exception as exc:
            print(f"[TTS] Supertonic generation error: {exc}")
            return False

    def generate(self, text: str, output_path: str, engine: str = "edge", lang: str = "en", voice: str | None = None, speed: float = 1.0) -> bool:
        """Main entry point for generating TTS."""
        if engine == "kokoro":
            success = self.generate_kokoro(text, output_path, lang, voice, speed)
            if success:
                return True
            print("[TTS] Kokoro failed, falling back to Edge TTS")
            engine = "edge"
            
        if engine == "edge":
            return self.generate_edge(text, output_path, lang, voice, speed)

        if engine == "supertonic":
            success = self.generate_supertonic(text, output_path, lang, voice, speed)
            if success:
                return True
            print("[TTS] Supertonic failed, falling back to Edge TTS")
            return self.generate_edge(text, output_path, lang, None, speed)
            
        return False
