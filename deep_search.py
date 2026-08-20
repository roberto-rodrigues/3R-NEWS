"""Busca profunda no arquivo dos canais (sob demanda).

A busca normal do R3 News so olha o banco local (o que ja foi coletado). Este modulo
consulta a busca/arquivo dos proprios sites por um termo, filtra por faixa de tempo e
importa os achados no banco, para que passem a aparecer na busca normal.

Primeiro build: adaptador para sites WordPress, que expoem um feed de busca em
`{base}?s={termo}&paged={n}&feed=rss2` com titulo, link e data real. A paginacao permite
voltar no tempo ate cobrir a faixa pedida. Novos adaptadores (g1, EBC, Correio) podem ser
adicionados em ADAPTERS sem mexer no restante do app.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

import requests

from scraping_sites.site import REQUEST_HEADERS, _soup, Site

# Timeout curto e sem retry: a busca profunda roda sob demanda (clique do usuario),
# entao e melhor uma fonte falhar rapido do que travar a resposta.
SEARCH_TIMEOUT = 8
# Quantas paginas de busca vasculhar. Com faixa de tempo, vamos mais fundo (parando assim
# que a pagina fica mais antiga que o inicio da faixa); sem faixa, so as primeiras.
MAX_PAGINAS_COM_FAIXA = 12
MAX_PAGINAS_SEM_FAIXA = 2

# Fontes WordPress cujo feed de busca funciona (testado).
WORDPRESS_SEARCH = {
    'politicadistrital-df': 'https://www.politicadistrital.com.br/',
    'jornaldoguara': 'https://jornaldoguara.com.br/',
    'conectadoaopoder-df': 'https://conectadoaopoder.com.br/',
}


def _fetch(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=SEARCH_TIMEOUT)
    response.raise_for_status()
    return response


def _search_wordpress(base, termo, min_date=None):
    max_paginas = MAX_PAGINAS_COM_FAIXA if min_date else MAX_PAGINAS_SEM_FAIXA
    resultados = []
    for pagina in range(1, max_paginas + 1):
        url = f"{base}?s={quote(termo)}&paged={pagina}&feed=rss2"
        try:
            soup = _soup(_fetch(url), 'xml')
        except Exception:
            break
        itens = soup.find_all('item')
        if not itens:
            break

        mais_antiga = None
        for item in itens:
            title = item.find('title')
            link = item.find('link')
            if title is None or link is None:
                continue
            title_text = title.get_text(strip=True)
            link_href = link.get_text(strip=True)
            if not title_text or not link_href:
                continue
            pub_date = item.find('pubDate')
            data = Site._parse_rss_date(pub_date.get_text(strip=True)) if pub_date else None
            resultados.append({'materia': title_text, 'link': link_href, 'data': data})
            if data and (mais_antiga is None or data < mais_antiga):
                mais_antiga = data

        # itens vem do mais novo ao mais antigo; se ja passamos do inicio da faixa, para.
        if min_date and mais_antiga and mais_antiga < min_date:
            break
    return resultados


# Cada adaptador recebe (base_url, termo, min_date) e devolve [{materia, link, data}].
ADAPTERS = {fonte: (_search_wordpress, base) for fonte, base in WORDPRESS_SEARCH.items()}


def supported_sources():
    return sorted(ADAPTERS)


def deep_search(store, termo, min_date=None, max_date=None, log=print):
    """Busca `termo` no arquivo de cada canal suportado e importa os achados no banco.

    Consulta os canais em paralelo (rede), mas grava no banco em serie (SQLite). Faixa de
    tempo: itens com data real fora de [min_date, max_date] sao descartados; itens sem data
    conhecida sao descartados quando ha faixa definida. Retorna (novas, encontradas).
    """
    termo = (termo or '').strip()
    if not termo:
        return 0, 0

    tem_faixa = bool(min_date or max_date)

    def _buscar(par):
        fonte, (adaptador, base) = par
        try:
            return fonte, adaptador(base, termo, min_date)
        except Exception as exc:
            log(f"[{datetime.now():%H:%M:%S}] busca profunda falhou em '{fonte}': {exc}")
            return fonte, []

    with ThreadPoolExecutor(max_workers=len(ADAPTERS)) as executor:
        coletas = list(executor.map(_buscar, ADAPTERS.items()))

    novas = 0
    encontradas = 0
    for fonte, resultados in coletas:
        for item in resultados:
            data_real = item['data']
            if data_real is not None:
                if min_date and data_real < min_date:
                    continue
                if max_date and data_real > max_date:
                    continue
            elif tem_faixa:
                continue

            encontradas += 1
            data = data_real or datetime.now()
            novas += store.add_news(fonte, item['materia'], item['link'], data, estimada=data_real is None)
    return novas, encontradas
