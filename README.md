=========================================

** Clé API (optionnelle) pour le calendrier économique

Les actus RSS marchent sans clé.
Si tu veux aussi le calendrier économique (Trading Economics), crée un compte développeur et mets la clé dans .env :

TRADING_ECONOMICS_API_KEY=ta_clef_ici

=========================================
1.  venv Python 3.12/3.13 recommandé
    pip install -r requirements.txt

======== A faire ========

1. Refaire le texte descriptif de l'ia
2. Ajouter les indicateurs
3. Connecter l'api de new economique


trading_app/
├─ main.py
├─ README.md
├─ requirements.txt
├─ .env                  ← ⚠️ contient tes identifiants (MT5 + GROQ)
├─ assets/
│  └─ styles.qss         ← vide pour l’instant (tu styles déjà via QSS inline)
├─ app/
   ├─ ui/
   │  └─ main_window.py  ← fenêtrage, splitter Chart + Panneau IA, toolbar (symbole/TF)
   ├─ chart/
   │  ├─ chart_view.py   ← QWebEngineView, QWebChannel, pont Python↔JS, charge chart.html
   │  ├─ chart_bridge.py ← signaux `seriesLoaded` / `barUpdated` vers JS
   │  ├─ chart.html      ← Lightweight Charts + logiques JS (goLive, auto-gap, etc.)
   │  └─ js/
   │     ├─ lightweight-charts.standalone.production.js
   │     └─ qwebchannel.js
   ├─ data/
   │  ├─ mt5_source.py   ← DataWorker (thread) : historique + ticks MT5, agrégation M1/M5/M30
   │  ├─ resample.py     ← CandleAggregator (construction/MAJ de bougies)
   │  └─ models.py       ← Pydantic `Bar`
   └─ chat/
      ├─ chat_panel.py       ← onglets Chat & Actus, input auto-grandissant, bouton envoi
      ├─ chat_controller.py  ← colle les données marché + le prompt utilisateur
      └─ chat_service_groq.py← client Groq (par défaut `llama-3.3-70b-versatile`)

    