# Créer « DubRoom Script Director »

## Configuration

1. Ouvrir <https://chatgpt.com/gpts/editor>.
2. Choisir **Créer**, puis l’onglet de configuration manuelle.
3. Nom : **DubRoom Script Director**
4. Description :

   > Adapte les manifestes de transcription DubRoom en scripts multilingues naturels, narratifs, cohérents, minutés et directement réimportables.

5. Pour le GPT chinois Multi-Speaker, copier tout le contenu de
   `INSTRUCTIONS_CHINESE_MULTISPEAKER_V3_8000.txt` dans **Instructions**.
6. Ajouter `KNOWLEDGE_MULTISPEAKER_JSON_V3.txt` dans **Connaissances**.
7. Activer :
   - **Recherche web**
   - **Interpréteur de code et analyse de données**
8. Laisser désactivés :
   - génération d’images ;
   - Canvas, sauf besoin personnel ;
   - Actions et applications externes.
9. Enregistrer avec la visibilité **Moi uniquement** pendant les tests.

## Amorces de conversation

- `Je joins un manifeste DubRoom. Adapte tout le script dans la langue cible et rends-moi le JSON importable.`
- `Vérifie cette traduction DubRoom, corrige les contresens et rééquilibre les durées sans modifier les identifiants.`
- `Adapte ce manifeste en français, style récap naturel et cinématographique.`
- `Analyse d’abord toute l’histoire, puis rends un script oral non littéral compatible DubRoom.`

## Premier test

Dans DubRoom :

1. pour un projet multispeaker, lancer d’abord **Analyser les changements de voix** afin de fournir les indices acoustiques ;
2. exporter la transcription au format **Manifeste pour traduction** ;
3. joindre le fichier JSON au GPT ;
4. utiliser la première amorce ;
5. télécharger le fichier `.json` créé par l'outil d'analyse de données ;
6. l’importer dans le même projet DubRoom ;
7. vérifier les personnages fusionnés, leur sexe/âge approximatif et quelques segments au début, au milieu et à la fin avant de lancer le casting des voix.

Le GPT doit être utilisé dans une nouvelle conversation pour chaque manifeste important, car un GPT personnalisé ne conserve pas automatiquement la mémoire des conversations précédentes.

## Important : V2 et V3

- V3 est réservé aux projets **Multi-Speaker**.
- Les projets **Voix unique** restent en V2 et utilisent `INSTRUCTIONS_A_COLLER.md`
  avec `CONTRAT_MANIFESTE_DUBROOM.md`.
- Ne jamais mélanger les instructions V2 et V3 dans le même GPT.
