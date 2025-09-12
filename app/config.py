# app/config.py
import os

# =========================
#  Chart / Data behavior
# =========================

# Tu préfères garder désactivé : on ne force pas un nombre de barres en continu.
ENFORCE_MIN_BARS: bool = False

# Seuil minimum de bougies à charger UNIQUEMENT au tout premier rendu
# pour éviter le bug "une seule bougie".
FIRST_LOAD_MIN_BARS: int = int(os.getenv("FIRST_LOAD_MIN_BARS", "120"))

# Délai de sécurité (ms) : si on n'a pas atteint le seuil au bout de ce temps,
# on envoie quand même ce qu'on a et on passe en mode live.
FIRST_LOAD_TIMEOUT_MS: int = int(os.getenv("FIRST_LOAD_TIMEOUT_MS", "2500"))

# =========================
#  MT5 / Data source
# =========================

# Chemin MT5 (laisse vide pour auto-détection ; sinon renseigne via .env)
MT5_PATH: str = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

# Symbole & timeframe par défaut (si ton UI ne les fournit pas encore)
DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "EURUSD")
DEFAULT_TIMEFRAME: str = os.getenv("DEFAULT_TIMEFRAME", "M5")  # M1, M5, M15, M30, H1, etc.

# Nombre d'historiques à tenter pour le premier chargement (si dispo)
INITIAL_HISTORY_BARS: int = int(os.getenv("INITIAL_HISTORY_BARS", "300"))

# =========================
#  Logs
# =========================

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
