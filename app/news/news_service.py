# app/news/news_service.py
from __future__ import annotations
import os, time, html
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
import feedparser
from dateutil import parser as dtparser
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

# ---------- Modèle ----------
@dataclass
class NewsItem:
    title: str
    source: str
    dt: datetime
    url: Optional[str] = None
    summary: Optional[str] = None
    tag: Optional[str] = None  # ex: RSS, Calendar, Fed, BoC, ECB…

# ---------- Helpers ----------
def _to_toronto(dt: datetime) -> datetime:
    # Toronto: EDT/EST; on garde un affichage "locale" simple sans dépendance pytz.
    # Si dt est naïf -> suppose UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Décalage dynamique (approx) : -4h été, -5h hiver. On calcule par rule of thumb:
    # Pour une vraie précision, ajouter `pytz` / `zoneinfo`. Ici on reste simple.
    month = dt.month
    offset = -4 if 3 <= month <= 11 else -5
    return dt.astimezone(timezone(timedelta(hours=offset)))

def _safe(s: Optional[str]) -> str:
    return html.escape(s or "")

def build_news_html(items: List[NewsItem]) -> str:
    """Construit l’HTML pour ChatPanel.demo_fill_news()"""
    def row(it: NewsItem) -> str:
        dtt = _to_toronto(it.dt)
        hhmm = dtt.strftime("%H:%M")
        tz_lbl = "ET"
        summary_html = f"<div style='margin-top:6px;opacity:.9'>{_safe(it.summary)}</div>" if it.summary else ""
        title_html = (
            f"<a href='{_safe(it.url)}' target='_blank' style='color:#93c5fd;text-decoration:none'>{_safe(it.title)}</a>"
            if it.url else _safe(it.title)
        )
        tag = f"<span style='border:1px solid #334155;border-radius:10px;padding:2px 8px;font-size:11px;opacity:.8'>{_safe(it.tag or 'RSS')}</span>"
        return f"""
          <div style="padding:10px 0;border-bottom:1px solid #1f2937">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <div style="font-weight:600">{title_html}</div>
              {tag}
            </div>
            <div style="opacity:.8;font-size:12px">{_safe(it.source)} • {hhmm} {tz_lbl}</div>
            {summary_html}
          </div>
        """
    body = "".join(row(it) for it in items) if items else "<div>Aucune actu</div>"
    return f"""
      <div style="font:13px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#e5e7eb;background:#0b1220;padding:12px">
        <div style="font-weight:700;margin-bottom:8px">Actus économiques</div>
        {body}
      </div>
    """

# ---------- Providers ----------
class RssProvider:
    """Agrégateur RSS (banques centrales + finance/forex)"""
    # Tu peux ajouter/retirer des feeds ici. Beaucoup sont stables.
    FEEDS = [
        # Banques centrales
        {"source": "Federal Reserve (Monetary Policy)", "url": "https://www.federalreserve.gov/feeds/press_monetarypolicy.xml", "tag": "Fed"},
        {"source": "Bank of Canada — Press releases",      "url": "https://www.bankofcanada.ca/content_type/press-releases/feed/", "tag": "BoC"},
        {"source": "ECB — Press releases",                  "url": "https://www.ecb.europa.eu/rss/press.html", "tag": "ECB"},

        # Finance / Marchés
        {"source": "MarketWatch — Top Stories",             "url": "https://www.marketwatch.com/rss/topstories", "tag": "Markets"},
        {"source": "Myfxbook — Forex News",                 "url": "https://www.myfxbook.com/rss/forex-news", "tag": "FX"},
    ]

    def fetch(self, max_per_feed: int = 10) -> List[NewsItem]:
        out: List[NewsItem] = []
        headers = {"User-Agent": "trading_app/1.0"}
        for feed in self.FEEDS:
            try:
                parsed = feedparser.parse(feed["url"], request_headers=headers)
                for entry in parsed.entries[:max_per_feed]:
                    title = entry.get("title") or ""
                    link  = entry.get("link")
                    summary = (entry.get("summary") or entry.get("description") or "")
                    # published_parsed peut manquer selon le flux
                    dt_raw = None
                    if "published" in entry:
                        try:
                            dt_raw = dtparser.parse(entry["published"])
                        except Exception:
                            dt_raw = None
                    if dt_raw is None and "updated" in entry:
                        try:
                            dt_raw = dtparser.parse(entry["updated"])
                        except Exception:
                            dt_raw = None
                    if dt_raw is None:
                        dt_raw = datetime.utcnow().replace(tzinfo=timezone.utc)

                    out.append(NewsItem(
                        title=title.strip(),
                        source=feed["source"],
                        dt=dt_raw,
                        url=link,
                        summary=summary.strip(),
                        tag=feed.get("tag", "RSS")
                    ))
            except Exception:
                # On ignore silencieusement un feed défaillant
                continue
        return out

class TradingEconomicsCalendarProvider:
    """Calendrier éco via Trading Economics (optionnel, nécessite une clé)."""
    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def fetch(self, countries: List[str], window_before_h: int = 12, window_after_h: int = 24, importance: Optional[int] = None) -> List[NewsItem]:
        if not self.api_key:
            return []

        now_utc = datetime.utcnow()
        d1 = (now_utc - timedelta(hours=window_before_h)).strftime("%Y-%m-%dT%H:%M")
        d2 = (now_utc + timedelta(hours=window_after_h)).strftime("%Y-%m-%dT%H:%M")
        # API docs: https://docs.tradingeconomics.com/ (Calendar snapshot/country/importance)
        # Exemple d'endpoint:
        # https://api.tradingeconomics.com/calendar?c=YOUR_KEY&country=United%20States,Canada,Euro%20Area&d1=...&d2=...&importance=2
        base = "https://api.tradingeconomics.com/calendar"
        params = {
            "c": self.api_key,
            "country": ",".join(countries),
            "d1": d1,
            "d2": d2
        }
        if importance:
            params["importance"] = str(importance)

        try:
            r = requests.get(base, params=params, timeout=10)
            r.raise_for_status()
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else []
        except Exception:
            return []

        items: List[NewsItem] = []
        for ev in data:
            # champs typiques: 'Country', 'Category', 'Event', 'Date', 'Actual', 'Previous', 'Forecast', 'Importance'
            title_bits = [ev.get("Event") or ev.get("Category") or "Economic Event"]
            # Ajout des valeurs si dispo
            af = []
            if ev.get("Actual"):   af.append(f"Act: {ev['Actual']}")
            if ev.get("Forecast"): af.append(f"Fcst: {ev['Forecast']}")
            if ev.get("Previous"): af.append(f"Prev: {ev['Previous']}")
            if af:
                title_bits.append(" | ".join(af))
            title = " — ".join(title_bits)

            # Date
            try:
                dt_ev = dtparser.parse(ev.get("Date") or ev.get("DateUtc") or "")
            except Exception:
                dt_ev = datetime.utcnow().replace(tzinfo=timezone.utc)

            items.append(NewsItem(
                title=title,
                source=f"Trading Economics ({ev.get('Country','')})",
                dt=dt_ev,
                url=ev.get("Link") or "https://tradingeconomics.com/calendar",
                summary=ev.get("Category") or "",
                tag="Calendar"
            ))
        return items

# ---------- Service orchestrateur ----------
class NewsService(QObject):
    htmlReady = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news")
        self._future = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

        self._rss = RssProvider()
        self._te = TradingEconomicsCalendarProvider(api_key=os.getenv("TRADING_ECONOMICS_API_KEY"))

        # Pays du calendrier (modifiable)
        self.calendar_countries = ["United States", "Canada", "Euro Area"]

    def start(self, interval_ms: int = 180_000):
        """Démarre le refresh périodique (3 min par défaut) et rafraîchit immédiatement."""
        self._timer.start(interval_ms)
        self.refresh()  # premier tir

    def stop(self):
        self._timer.stop()

    def refresh(self):
        """Lance un fetch en background si aucun fetch n’est en cours."""
        if self._future and not self._future.done():
            return
        self._future = self._executor.submit(self._collect_all)
        self._future.add_done_callback(self._on_done)

    # ---- background ----
    def _collect_all(self) -> str:
        rss_items = self._rss.fetch(max_per_feed=8)

        cal_items: List[NewsItem] = []
        if self._te.is_enabled():
            cal_items = self._te.fetch(self.calendar_countries, window_before_h=12, window_after_h=24, importance=None)

        all_items = rss_items + cal_items
        # Trie décroissant par date
        all_items.sort(key=lambda it: it.dt, reverse=True)
        # Garde ~30 éléments pour rester léger
        all_items = all_items[:30]
        return build_news_html(all_items)

    def _on_done(self, fut):
        try:
            html_out = fut.result()
            self.htmlReady.emit(html_out)
        except Exception:
            # silence si erreur
            pass
