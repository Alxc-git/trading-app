# app/chat/chat_service_groq.py
from __future__ import annotations
import os, json, requests, time
from dataclasses import dataclass
from typing import List, Dict, Any

from PyQt6.QtCore import (
    QObject, pyqtSignal, pyqtSlot, QThread, QMetaObject, Qt
)
from dotenv import load_dotenv

__all__ = ["GroqChatService"]

# Charge .env
load_dotenv()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEBUG = os.getenv("GROQ_DEBUG", "0").strip() in ("1","true","True")

def _log(*a):
    if GROQ_DEBUG:
        print("[GROQ]", *a, flush=True)

@dataclass
class ChatRequest:
    model: str
    messages: List[Dict[str, Any]]
    temperature: float = 0.3
    max_tokens: int = 800
    timeout_sec: float = 45.0

class ChatWorker(QObject):
    finished   = pyqtSignal()
    succeeded  = pyqtSignal(str)   # texte réponse
    failed     = pyqtSignal(str)   # message d'erreur

    def __init__(self, request: ChatRequest):
        super().__init__()
        self.request = request

    @pyqtSlot()
    def run(self):
        _log("worker started; model:", self.request.model)
        if not GROQ_API_KEY:
            self.failed.emit("Clé GROQ_API_KEY absente dans .env")
            self.finished.emit()
            return
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.request.model,
                "messages": self.request.messages,
                "temperature": self.request.temperature,
                "max_tokens": self.request.max_tokens,
                "stream": False,
            }
            t0 = time.time()
            resp = requests.post(
                GROQ_CHAT_URL, headers=headers, data=json.dumps(payload),
                timeout=self.request.timeout_sec
            )
            dt = time.time() - t0
            _log(f"HTTP status={resp.status_code} in {dt:.2f}s")

            if resp.status_code != 200:
                self.failed.emit(f"HTTP {resp.status_code} – {resp.text[:300]}")
                self.finished.emit()
                return

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self.succeeded.emit(content)

        except requests.Timeout:
            self.failed.emit("Timeout HTTP côté client")
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()

class GroqChatService(QObject):
    responseReady = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        super().__init__()
        self.model = model
        # On RETIENT threads + workers pour éviter le GC
        self._jobs: list[tuple[QThread, ChatWorker]] = []

    def ask(self, messages: List[Dict[str, Any]]):
        _log("ask() called; will spawn thread")

        req = ChatRequest(model=self.model, messages=messages)
        thr = QThread()
        worker = ChatWorker(req)
        worker.moveToThread(thr)

        # Connexions
        # (1) Lancer run() via QueuedConnection -> garantit exécution dans le thread
        thr.started.connect(lambda: QMetaObject.invokeMethod(
            worker, "run", Qt.ConnectionType.QueuedConnection
        ))
        # (2) Propager signaux
        worker.succeeded.connect(self.responseReady.emit)
        worker.failed.connect(self.error.emit)
        # (3) Cycle de vie
        worker.finished.connect(thr.quit)
        worker.finished.connect(worker.deleteLater)
        thr.finished.connect(lambda: self._cleanup(thr, worker))
        thr.finished.connect(thr.deleteLater)

        # Conserver une référence (évite le GC du worker)
        self._jobs.append((thr, worker))
        thr.start()

    def _cleanup(self, thr: QThread, worker: ChatWorker):
        # Retire la paire (thr, worker) de la liste
        for i, (t, w) in enumerate(self._jobs):
            if t is thr and w is worker:
                self._jobs.pop(i)
                break
        _log("thread finished; cleaned up")
