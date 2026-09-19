# DubRoom Studio

Studio desktop local pour analyser, traduire, réécrire et doubler des vidéos d'anime, de manga et de manhwa.

## Fonctionnalités

- import de vidéos locales ou YouTube ;
- transcription et segmentation multi-locuteurs ;
- traduction et préparation de scripts narratifs ;
- bibliothèque de voix et génération TTS ;
- préservation, séparation et mastering audio ;
- synchronisation temporelle et export vidéo.

## Architecture

- `apps/desktop` : interface Electron, React et TypeScript ;
- `services/api` : API locale FastAPI ;
- `scripts` : installation, diagnostic, benchmarks et pipelines ;
- `config` : configuration de l'application ;
- `docs` : contrats et documentation technique.

## Développement

Prérequis : Node.js, npm et Python 3.12.

```powershell
cd apps/desktop
npm install
npm run dev
```

Pour l'API :

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Le lanceur Windows `Lancer-DubRoom.vbs` utilise les runtimes locaux configurés sur la machine.

## Modèles IA

Les modèles, checkpoints, environnements Python, médias utilisateur et sorties générées ne sont pas inclus dans ce dépôt. Les scripts présents dans `scripts/engines` permettent de préparer les composants nécessaires.

## Statut

Projet en développement actif, destiné à une utilisation locale sous Windows.
