from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ENGINE_ID = "tts-omnivoice-hq"
MIN_PY = (3, 10)
MAX_PY = (3, 13)
MIN_TORCH = (2, 4)

PROBE_CODE = r"""
import json, sys
p = {
    "python": sys.executable,
    "major": sys.version_info.major,
    "minor": sys.version_info.minor,
    "torch_ok": False,
    "torchaudio_ok": False,
    "cuda": False,
    "torch_version": "",
    "torchaudio_version": "",
    "cuda_version": "",
    "torch_package": "",
    "torchaudio_package": "",
    "package_root": "",
    "error": "",
}
try:
    import torch
    from pathlib import Path
    p["torch_ok"] = True
    p["torch_version"] = str(torch.__version__)
    p["cuda"] = bool(torch.cuda.is_available())
    p["cuda_version"] = str(torch.version.cuda or "")
    p["torch_package"] = str(Path(torch.__file__).resolve().parent)
    p["package_root"] = str(Path(torch.__file__).resolve().parent.parent)
except Exception as exc:
    p["error"] = "torch: " + repr(exc)
try:
    import torchaudio
    from pathlib import Path
    p["torchaudio_ok"] = True
    p["torchaudio_version"] = str(torchaudio.__version__)
    p["torchaudio_package"] = str(Path(torchaudio.__file__).resolve().parent)
except Exception as exc:
    p["error"] += " torchaudio: " + repr(exc)
print("DUBROOM_JSON=" + json.dumps(p))
"""


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True):
    shown = " ".join(f'"{x}"' if " " in x else x for x in cmd)
    print("> " + shown)
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if check and result.returncode != 0:
        raise RuntimeError(f"Commande echouee ({result.returncode}): {cmd[0]}")
    return result


def version2(value: str) -> tuple[int, int]:
    try:
        core = str(value).split("+", 1)[0].split(".")
        return int(core[0]), int(core[1])
    except Exception:
        return 0, 0


def valid_python(info: dict[str, Any] | None) -> bool:
    if not info:
        return False
    v = (int(info.get("major") or 0), int(info.get("minor") or 0))
    return MIN_PY <= v <= MAX_PY


def valid_torch(info: dict[str, Any] | None) -> bool:
    return bool(
        valid_python(info)
        and info.get("torch_ok")
        and info.get("torchaudio_ok")
        and info.get("cuda")
        and version2(str(info.get("torch_version") or "")) >= MIN_TORCH
        and Path(str(info.get("torch_package") or "")).is_dir()
        and Path(str(info.get("torchaudio_package") or "")).is_dir()
        and Path(str(info.get("package_root") or "")).is_dir()
    )


def probe(exe: Path) -> dict[str, Any] | None:
    try:
        if not exe.is_file():
            return None
        p = subprocess.run(
            [str(exe), "-c", PROBE_CODE],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=45,
        )
        if p.returncode != 0:
            return None
        for line in reversed(p.stdout.splitlines()):
            if line.startswith("DUBROOM_JSON="):
                return json.loads(line[len("DUBROOM_JSON="):])
    except Exception:
        return None
    return None


def project_root(value: str | None) -> Path:
    for candidate in [
        Path(value) if value else None,
        Path.cwd(),
        Path(r"D:\manhwa studio\anime_manga_manhua_dubbing_app"),
    ]:
        if candidate is None:
            continue
        try:
            candidate = candidate.resolve()
        except Exception:
            continue
        if (candidate / "models" / "tts-catalog.json").is_file():
            return candidate
    raise RuntimeError("Racine DubRoom introuvable")


def candidates(root: Path, target_python: Path):
    result = []
    seen = set()
    for scan in (root / "data" / "environments", root / "data" / "toolchains"):
        if not scan.is_dir():
            continue
        for exe in scan.rglob("python.exe"):
            key = str(exe).casefold()
            if key == str(target_python).casefold() or key in seen:
                continue
            seen.add(key)
            info = probe(exe)
            if valid_python(info):
                result.append((exe, info or {}))
    return result


def choose_source(items):
    valid = [(exe, info) for exe, info in items if valid_torch(info)]
    if not valid:
        return None

    def score(item):
        exe, info = item
        s = str(exe).casefold()
        score = 0
        if "qwen3" in s:
            score += 100
        if "chatterbox" in s:
            score += 60
        if str(info.get("cuda_version")) == "12.8":
            score += 30
        if version2(str(info.get("torch_version"))) >= (2, 8):
            score += 20
        return score

    return max(valid, key=score)


def target_site(python: Path) -> Path:
    p = subprocess.run(
        [str(python), "-c", "import site; print(site.getsitepackages()[0])"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    site = Path(p.stdout.strip()).resolve()
    # Windows venvs should normally report Lib/site-packages. Fall back to the
    # canonical path if an unusual Python build reports the venv root.
    if site.name.casefold() != "site-packages":
        canonical = python.parent.parent / "Lib" / "site-packages"
        if canonical.is_dir():
            site = canonical.resolve()
    return site


def remove_path(path: Path):
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=False)


def remove_stale_torch(site: Path):
    (site / "dubroom_shared_torch.pth").unlink(missing_ok=True)
    for name in ("torch", "torchaudio", "torchgen", "functorch"):
        path = site / name
        if path.exists():
            print("Nettoyage ancien package local:", path.name)
            remove_path(path)
    for pattern in ("torch-*.dist-info", "torchaudio-*.dist-info"):
        for path in site.glob(pattern):
            print("Nettoyage ancienne metadata:", path.name)
            remove_path(path)


def hardlink_tree(source: Path, dest: Path) -> tuple[int, int]:
    files = 0
    logical_bytes = 0

    if source.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, dest)
        return 1, source.stat().st_size

    dest.mkdir(parents=True, exist_ok=True)
    for src in source.rglob("*"):
        rel = src.relative_to(source)
        dst = dest / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            # Avoid silently copying a potentially huge file.
            raise RuntimeError(f"Symlink inattendu dans le package Torch Windows: {src}")

        os.link(src, dst)
        files += 1
        try:
            logical_bytes += src.stat().st_size
        except OSError:
            pass

    return files, logical_bytes


def collect_source_roots(info: dict[str, Any]) -> list[Path]:
    package_root = Path(str(info["package_root"])).resolve()
    torch_pkg = Path(str(info["torch_package"])).resolve()
    torchaudio_pkg = Path(str(info["torchaudio_package"])).resolve()

    if torch_pkg.parent != package_root:
        raise RuntimeError(f"Racine Torch incoherente: {torch_pkg} vs {package_root}")
    if torchaudio_pkg.parent != package_root:
        raise RuntimeError(f"Racine Torchaudio incoherente: {torchaudio_pkg} vs {package_root}")

    roots: list[Path] = [torch_pkg, torchaudio_pkg]

    for name in ("torchgen", "functorch"):
        p = package_root / name
        if p.exists():
            roots.append(p)

    torch_dist = sorted(package_root.glob("torch-*.dist-info"))
    ta_dist = sorted(package_root.glob("torchaudio-*.dist-info"))

    if not torch_dist:
        raise RuntimeError(f"Metadata torch-*.dist-info introuvable dans {package_root}")
    if not ta_dist:
        raise RuntimeError(f"Metadata torchaudio-*.dist-info introuvable dans {package_root}")

    # Pick the newest-looking metadata entry if stale versions coexist.
    roots.append(torch_dist[-1])
    roots.append(ta_dist[-1])
    return roots


def mirror_torch(info: dict[str, Any], dest_site: Path):
    package_root = Path(str(info["package_root"])).resolve()
    if package_root.drive.casefold() != dest_site.drive.casefold():
        raise RuntimeError(
            "Torch source et OmniVoice ne sont pas sur le meme volume; "
            "hardlinks NTFS impossibles."
        )

    roots = collect_source_roots(info)
    remove_stale_torch(dest_site)

    total_files = 0
    total_bytes = 0
    try:
        for src in roots:
            dst = dest_site / src.name
            print("Hardlink:", src)
            count, size = hardlink_tree(src, dst)
            total_files += count
            total_bytes += size
    except Exception:
        remove_stale_torch(dest_site)
        raise

    return total_files, total_bytes


def ensure_venv(source_python: Path, source_info: dict[str, Any], venv: Path) -> Path:
    target = venv / "Scripts" / "python.exe"
    if target.is_file():
        info = probe(target)
        src_minor = (int(source_info["major"]), int(source_info["minor"]))
        dst_minor = (
            int((info or {}).get("major") or 0),
            int((info or {}).get("minor") or 0),
        )
        if dst_minor != src_minor:
            print("Recreation du venv OmniVoice pour Python", f"{src_minor[0]}.{src_minor[1]}")
            shutil.rmtree(venv, ignore_errors=True)

    if not target.is_file():
        print("Creation du venv OmniVoice avec le meme Python que Torch...")
        run([str(source_python), "-m", "venv", str(venv)])
    return target


def bootstrap_small_deps(target_python: Path):
    run([str(target_python), "-m", "ensurepip", "--upgrade"], check=False)
    run([
        str(target_python), "-m", "pip", "install", "--upgrade",
        "pip", "setuptools", "wheel", "packaging",
        "filelock", "typing-extensions", "sympy", "networkx",
        "jinja2", "fsspec",
    ])


def validate_reused_torch(target_python: Path):
    info = probe(target_python)
    if not valid_torch(info):
        raise RuntimeError(
            "Torch/Torchaudio reutilises ne sont pas importables dans OmniVoice. "
            "V8 s'arrete sans telecharger PyTorch. "
            f"Diagnostic: {(info or {}).get('error', 'probe failed')}"
        )
    print("\nReutilisation Torch validee:")
    print(" Torch:", info.get("torch_version"))
    print(" Torchaudio:", info.get("torchaudio_version"))
    print(" CUDA:", info.get("cuda_version"))
    print(" Torch package:", info.get("torch_package"))
    return info


def install_omnivoice(target_python: Path):
    print("\nInstallation OmniVoice 0.2.1 sans dependances...")
    run([str(target_python), "-m", "pip", "install", "--no-deps", "omnivoice==0.2.1"])

    print("\nInstallation des dependances OmniVoice hors Torch/Torchaudio...")
    run([
        str(target_python), "-m", "pip", "install",
        "--upgrade-strategy", "only-if-needed",
        "transformers>=5.3.0",
        "accelerate",
        "pydub",
        "gradio",
        "tensorboardX",
        "webdataset",
        "numpy",
        "soundfile",
        "librosa",
        "num2words>=0.5.14",
        "huggingface_hub",
    ])


def validate_omnivoice(target_python: Path):
    code = r"""
import json
import torch, torchaudio, transformers
import omnivoice
from omnivoice import OmniVoice, VoiceClonePrompt
p = {
    "torch": str(torch.__version__),
    "torchaudio": str(torchaudio.__version__),
    "cuda": bool(torch.cuda.is_available()),
    "cuda_version": str(torch.version.cuda or ""),
    "omnivoice": str(getattr(omnivoice, "__version__", "0.2.1")),
    "transformers": str(transformers.__version__),
}
if not p["cuda"]:
    raise SystemExit("CUDA indisponible")
print("DUBROOM_JSON=" + json.dumps(p))
"""
    p = run([str(target_python), "-c", code])
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("DUBROOM_JSON="):
            return json.loads(line[len("DUBROOM_JSON="):])
    raise RuntimeError("Validation OmniVoice incomplete")


def download_model(target_python: Path, model_root: Path, runtime_root: Path):
    target = model_root / "model"
    target.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    helper = runtime_root / "download_omnivoice_model.py"
    helper.write_text(
        r"""
from pathlib import Path
from huggingface_hub import snapshot_download
import os

target = Path(os.environ["DUB_OMNIVOICE_MODEL_DIR"])
snapshot_download(
    repo_id="k2-fsa/OmniVoice",
    revision="main",
    local_dir=str(target),
    token=os.environ.get("HF_TOKEN") or None,
)
print("MODEL_OK=" + str(target))
""".strip() + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["DUB_OMNIVOICE_MODEL_DIR"] = str(target)
    print("\nTelechargement/verification du checkpoint OmniVoice uniquement...")
    run([str(target_python), str(helper)], env=env)


def write_ready(
    model_root: Path,
    runtime_root: Path,
    target_python: Path,
    source_python: Path,
    source_info: dict[str, Any],
    runtime_info: dict[str, Any],
    linked_files: int,
    linked_bytes: int,
):
    model_root.mkdir(parents=True, exist_ok=True)
    model_json = {
        "engine_id": ENGINE_ID,
        "repo_id": "k2-fsa/OmniVoice",
        "revision": "main",
        "runtime": "dubroom-native-tts",
        "dtype": "float16",
        "quantization": "none",
        "num_step": 32,
        "model_path": str((model_root / "model").resolve()),
        "local_only": True,
        "commercial_use": False,
    }
    (model_root / "model.json").write_text(json.dumps(model_json, indent=2), encoding="utf-8")

    py = probe(target_python) or {}
    ready = {
        "engine_id": ENGINE_ID,
        "runtime": "dubroom-native-tts",
        "variant": "hq-fp16",
        "dtype": "float16",
        "quantization": "none",
        "num_step": 32,
        "python": str(target_python),
        "python_minor": f"{py.get('major')}.{py.get('minor')}",
        "torch_reused": True,
        "torch_reuse_method": "ntfs-hardlinks",
        "torch_source_python": str(source_python),
        "torch_source_package_root": str(source_info.get("package_root")),
        "torch_source_package": str(source_info.get("torch_package")),
        "torchaudio_source_package": str(source_info.get("torchaudio_package")),
        "torch_linked_files": linked_files,
        "torch_logical_bytes_reused": linked_bytes,
        "torch": runtime_info.get("torch"),
        "torchaudio": runtime_info.get("torchaudio"),
        "cuda": runtime_info.get("cuda"),
        "cuda_version": runtime_info.get("cuda_version"),
        "omnivoice": runtime_info.get("omnivoice"),
        "transformers": runtime_info.get("transformers"),
        "local_only": True,
        "commercial_use": False,
    }
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "ready.json").write_text(json.dumps(ready, indent=2), encoding="utf-8")
    print("\nready.json:")
    print(json.dumps(ready, indent=2))


def deploy_wrapper(root: Path):
    engines = root / "scripts" / "engines"
    engines.mkdir(parents=True, exist_ok=True)
    helper_dst = engines / "install-omnivoice-runtime.py"
    src = Path(__file__).resolve()
    if src.resolve() != helper_dst.resolve():
        shutil.copy2(src, helper_dst)

    ps1 = engines / "install-omnivoice-hq.ps1"
    lines = [
        '$ErrorActionPreference = "Stop"',
        '$runner = $env:DUB_BASE_PYTHON',
        'if ([string]::IsNullOrWhiteSpace($runner)) { $runner = "python" }',
        '$modelRoot = $env:DUB_ENGINE_MODELS',
        'if ([string]::IsNullOrWhiteSpace($modelRoot)) { throw "DUB_ENGINE_MODELS missing" }',
        '$projectRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent',
        '$helper = Join-Path $PSScriptRoot "install-omnivoice-runtime.py"',
        '& $runner $helper --root $projectRoot',
        'if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }',
        '',
    ]
    ps1.write_bytes("\r\n".join(lines).encode("ascii"))


def self_test():
    assert valid_python({"major": 3, "minor": 10})
    assert valid_python({"major": 3, "minor": 13})
    assert not valid_python({"major": 3, "minor": 14})
    print("SELF_TEST_OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    root = project_root(args.root)
    runtime_root = root / "data" / "environments" / ENGINE_ID
    venv = runtime_root / "venv"
    target_python = venv / "Scripts" / "python.exe"
    model_root = root / "models" / ENGINE_ID

    print("=" * 72)
    print(" DUBROOM - OMNIVOICE RUNTIME V8 - TRUE PACKAGE PATH")
    print("=" * 72)
    print("Racine:", root)
    print("V8 ne repatche aucun fichier source.")
    print("V8 ne telecharge JAMAIS PyTorch automatiquement.\n")

    deploy_wrapper(root)

    items = candidates(root, target_python)
    source = choose_source(items)
    if source is None:
        raise RuntimeError(
            "Aucun environnement DubRoom compatible avec Torch + Torchaudio + CUDA trouve."
        )

    source_python, source_info = source
    print("Torch source choisi:")
    print(" Python:", source_python)
    print(" Torch:", source_info.get("torch_version"))
    print(" Torchaudio:", source_info.get("torchaudio_version"))
    print(" CUDA:", source_info.get("cuda_version"))
    print(" Torch package:", source_info.get("torch_package"))
    print(" Torchaudio package:", source_info.get("torchaudio_package"))
    print(" Package root:", source_info.get("package_root"))

    target_python = ensure_venv(source_python, source_info, venv)
    bootstrap_small_deps(target_python)

    dest_site = target_site(target_python)
    print(" OmniVoice site-packages:", dest_site)

    files, logical_bytes = mirror_torch(source_info, dest_site)
    print(
        f"\nTorch/Torchaudio hardlinkes: {files} fichiers, "
        f"{logical_bytes / (1024**3):.2f} Gio logiques reutilises sans seconde copie."
    )

    validate_reused_torch(target_python)
    install_omnivoice(target_python)
    validate_reused_torch(target_python)
    runtime_info = validate_omnivoice(target_python)

    download_model(target_python, model_root, runtime_root)
    write_ready(
        model_root, runtime_root, target_python,
        source_python, source_info, runtime_info,
        files, logical_bytes,
    )

    print("\n" + "=" * 72)
    print(" OMNIVOICE HQ PRET - TORCH REUTILISE")
    print("=" * 72)
    print("Aucun package PyTorch n'a ete telecharge par V8.")
    print("FP16 / 32 steps / aucune quantification")
    print("Redemarre DubRoom.")


if __name__ == "__main__":
    main()
