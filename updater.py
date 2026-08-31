"""Coleta de noticias reutilizavel (Fase 2).

Extrai o loop de atualizacao que antes vivia dentro da versao de terminal, para que
tanto o CLI (asimov_news.py) quanto a interface web (web.py) usem exatamente o mesmo
codigo de coleta e a mesma lista de fontes (scraping_sites.site.all_sites).
"""
import threading
import time
from datetime import datetime

from scraping_sites.site import Site, all_sites
from storage import now_brt

UPDATE_INTERVAL_SECONDS = 30 * 60


def collect_once(store, sites=None, log=print, time_budget=None):
    """Faz uma passada por todas as fontes, gravando as noticias novas em `store`.

    Falha em uma fonte nao interrompe as demais. Datas ausentes sao gravadas como a hora
    da coleta e marcadas com estimada=True (ver storage.add_news / coluna data_estimada).
    `time_budget` (segundos) limita a passada: fontes restantes sao puladas ao estourar,
    para caber no maxDuration da funcao serverless quando disparada via /coletar.
    Retorna a quantidade de noticias processadas.
    """
    sites = sites if sites is not None else all_sites()
    inicio = time.monotonic()
    total = 0
    for nome in sites:
        if time_budget is not None and time.monotonic() - inicio > time_budget:
            log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Orcamento de {time_budget}s estourado; fontes restantes puladas")
            break
        try:
            site = Site(nome)
            site.update_news()
        except Exception as exc:
            log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Falha ao atualizar '{nome}': {exc}")
            continue

        agora = now_brt()
        linhas = [
            (nome, item['materia'], item['link'], item['data'] or agora, item['data'] is None)
            for item in site.news
        ]
        # Uma unica conexao por fonte, em vez de uma por materia (ver add_news_many).
        try:
            store.add_news_many(linhas)
        except Exception as exc:
            log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Falha ao gravar '{nome}': {exc}")
            continue
        total += len(linhas)
    return total


class BackgroundUpdater:
    """Roda collect_once em intervalos, numa thread daemon. Compartilhado por CLI e web."""

    def __init__(self, store, interval=UPDATE_INTERVAL_SECONDS, sites=None, log=print):
        self.store = store
        self.interval = interval
        self.sites = sites
        self.log = log
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                collect_once(self.store, self.sites, self.log)
            except Exception as exc:  # rede/IO inesperado nao pode matar a thread
                self.log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Erro na coleta: {exc}")
            self._stop.wait(self.interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
