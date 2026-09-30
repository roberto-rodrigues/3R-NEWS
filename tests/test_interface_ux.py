"""A busca e os filtros devem ser operáveis e compreensíveis sem depender da visão."""
import importlib
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_home_expoe_busca_e_filtros_acessiveis(monkeypatch):
    import storage

    class Store:
        def __init__(self, *args, **kwargs):
            pass

        def count_news(self, **kwargs):
            return 0

        def get_news(self, **kwargs):
            return []

        def get_visitas(self):
            return 0

        def get_latest_news_date(self):
            return None

        def get_date_bounds(self):
            return (2024, 2026)

        def get_all_sources(self):
            return ['cnn']

        def get_active_sites(self):
            return ['cnn']

    monkeypatch.setattr(storage, 'NewsStore', Store)
    sys.modules.pop('web', None)
    web = importlib.import_module('web')
    with web.app.test_client() as client:
        response = client.get('/?q=educacao&fonte=cnn')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    search = soup.select_one('input[name=q]')
    assert search['type'] == 'search'
    assert search['aria-label'] == 'Buscar notícias'
    assert soup.select_one('.contagem')['role'] == 'status'
    assert soup.select_one('.atalho-on')['aria-current'] == 'page'
    for link in soup.select('.chip a'):
        assert link.get('aria-label', '').startswith('Remover filtro')
