import re
import time
from urllib.parse import urlparse, urljoin
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BRT = ZoneInfo("America/Sao_Paulo")

REQUEST_HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
REQUEST_TIMEOUT = 10
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3

DATA_HORA_PATTERN = re.compile(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2})h(\d{2})')


def _get_with_retry(url, **kwargs):
    ultimo_erro = None
    for tentativa in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            ultimo_erro = exc
            if tentativa < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY_SECONDS)
    raise ultimo_erro


def _soup(response, parser='html.parser'):
    """Cria o BeautifulSoup decodificando com o charset correto.

    Para XML/RSS o proprio lxml le a declaracao <?xml encoding?> dos bytes, entao
    passamos response.content direto. Para HTML, o requests assume ISO-8859-1 quando
    o header HTTP nao traz charset (ex.: correio-df), o que corrompe paginas que na
    verdade sao UTF-8; nesse caso preferimos a deteccao estatistica do charset_normalizer.
    """
    if parser == 'xml':
        return BeautifulSoup(response.content, 'xml')
    encoding = response.encoding
    if not encoding or encoding.lower() == 'iso-8859-1':
        encoding = response.apparent_encoding or 'utf-8'
    return BeautifulSoup(response.content.decode(encoding, errors='replace'), parser)


# Sites com feed RSS: fonte estável e com data de publicacao real,
# ao contrário de raspar classes CSS que mudam a cada redesign do site.
RSS_FEEDS = {
    'veja': 'https://veja.abril.com.br/ultimas-noticias/rss',
    'cnn': 'https://www.cnnbrasil.com.br/feed/',
    'globo': 'https://g1.globo.com/rss/g1/',  # g1 e o portal de noticias do grupo Globo
    'agenciabrasil': 'https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml',  # Agencia Brasil (EBC), federal
    'metropoles-df': 'https://www.metropoles.com/distrito-federal/feed',
    'g1-df': 'https://g1.globo.com/rss/g1/df/distrito-federal/',
    'politicadistrital-df': 'https://www.politicadistrital.com.br/category/brasil/distrito-federal/feed/',
    'jornaldoguara': 'https://jornaldoguara.com.br/feed/',
    'conectadoaopoder-df': 'https://conectadoaopoder.com.br/categoria/distrito_federal/feed/',
}

# Sites sem RSS disponivel: fallback via scraping de HTML.
# 'selectors' e uma lista de (nome_da_tag, classe_css) candidatas a titulo de materia.
HTML_TARGETS = {
    'r7': {
        'url': 'https://www.r7.com/',
        'selectors': [('h3', 'base-font-primary'), ('h4', 'card-font-primary')],
    },
    'r7-df': {
        'url': 'https://noticias.r7.com/brasilia/balanco-geral-df/',
        'selectors': [('h3', 'base-font-primary'), ('h4', 'card-font-primary')],
    },
}

# Sites baseados em <article><h2>titulo</h2></article>. O 'webpart_url' e opcional:
# quando presente, "extra_pages" simula cliques no botao "Mais Noticias" buscando
# paginas extras via um endpoint HTML descoberto no JS da pagina do Correio Braziliense
# (frontend/src/assets/js/listar_mais_editorias.js -> webparts/{site_id}/{site_sec}/{pagina}/).
ARTICLE_TARGETS = {
    'correio-df': {
        'url': 'https://www.correiobraziliense.com.br/cidades-df',
        'base_domain': 'https://www.correiobraziliense.com.br',
        'webpart_url': 'https://www.correiobraziliense.com.br/webparts/1/1/{page}/',
        'extra_pages': 2,  # simula 2 cliques em "Mais Noticias"
    },
    'gpsbrasilia': {
        'url': 'https://gpsbrasilia.com.br/',
        'base_domain': 'https://gpsbrasilia.com.br',
    },
}

# Sites que usam o mesmo template de listagem <a class="lista-interna">,
# com titulo no atributo alt da imagem e data no formato "DD/MM/AAAA - HHhMM".
LISTA_INTERNA_TARGETS = {
    'ipebrasilia-gdf': {'url': 'https://www.ipebrasilia.com.br/gdf'},
    'ipebrasilia-cldf': {'url': 'https://www.ipebrasilia.com.br/cldf'},
    'brasiliamaisnoticias': {'url': 'https://brasiliamaisnoticias.com.br/brasilia'},
}

# Portais que listam materias como <a> soltos (sem RSS). Configuravel por selector:
#   link_selector     -> CSS que seleciona a ancora da materia
#   title_selector    -> CSS opcional dentro da ancora para o titulo limpo (ex.: 'h3');
#                        se ausente, usa o texto da propria ancora
#   parse_date_from_text -> extrai data no padrao "DD/MM/AAAA - HHhMM" do texto e a remove do titulo
#   min_title_len     -> descarta ancoras de navegacao/curtas
LINK_LIST_TARGETS = {
    'agenciabrasilia-df': {
        'url': 'https://agenciabrasilia.df.gov.br/noticias',
        'base_domain': 'https://agenciabrasilia.df.gov.br',
        'link_selector': 'a.card-result',
        'title_selector': 'h3',
    },
    'agenciacldf-df': {
        'url': 'https://www.cl.df.gov.br/web/guest/agencia-cldf',
        'base_domain': 'https://www.cl.df.gov.br',
        'link_selector': 'a[href*="/-/"]',
        'parse_date_from_text': True,
        'min_title_len': 20,
    },
}


def all_sites():
    """Fonte unica da verdade: todas as fontes suportadas, derivadas das configuracoes de
    coleta acima. Adicionar um site a qualquer dicionario de targets ja o registra no app
    (CLI e web), sem precisar manter uma lista paralela."""
    return (
        list(RSS_FEEDS)
        + list(HTML_TARGETS)
        + list(ARTICLE_TARGETS)
        + list(LISTA_INTERNA_TARGETS)
        + list(LINK_LIST_TARGETS)
    )


class Site:
    def __init__(self, opcao: str):
        self.opcao = opcao.lower()
        self.news = []

    def update_news(self):
        if self.opcao in RSS_FEEDS:
            self.news = self._scrape_rss(RSS_FEEDS[self.opcao])
        elif self.opcao in HTML_TARGETS:
            self.news = self._scrape_html(HTML_TARGETS[self.opcao])
        elif self.opcao in ARTICLE_TARGETS:
            self.news = self._scrape_article_based(ARTICLE_TARGETS[self.opcao])
        elif self.opcao in LISTA_INTERNA_TARGETS:
            self.news = self._scrape_lista_interna(LISTA_INTERNA_TARGETS[self.opcao])
        elif self.opcao in LINK_LIST_TARGETS:
            self.news = self._scrape_link_list(LINK_LIST_TARGETS[self.opcao])
        else:
            raise ValueError(f"Site nao suportado: {self.opcao}")

    def _scrape_rss(self, feed_url):
        response = _get_with_retry(feed_url)
        soup = _soup(response, 'xml')

        news = []
        for item in soup.find_all('item'):
            title = item.find('title')
            link = item.find('link')
            if title is None or link is None:
                continue

            title_text = title.get_text(strip=True)
            link_href = link.get_text(strip=True)
            if not title_text or not link_href:
                continue

            pub_date_tag = item.find('pubDate')
            data = self._parse_rss_date(pub_date_tag.get_text(strip=True)) if pub_date_tag else None

            news.append({'materia': title_text, 'link': link_href, 'data': data})
        return news

    @staticmethod
    def _parse_rss_date(raw_date):
        try:
            parsed = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            # RFC 2822 permite offset "-0000" (confianca desconhecida), que o
            # parsedate_to_datetime devolve sem tzinfo. Feeds como o do G1 usam
            # esse valor como UTC de fato, entao assumimos UTC antes de converter.
            parsed = parsed.replace(tzinfo=timezone.utc)
        # normaliza para horario de Brasilia ingênuo, independente do fuso do host
        # que roda o scraper (local, GitHub Actions etc. podem estar em fusos diferentes)
        parsed = parsed.astimezone(BRT).replace(tzinfo=None)
        return parsed

    def _scrape_html(self, target):
        response = _get_with_retry(target['url'])
        soup = _soup(response)

        news = []
        seen_links = set()
        for anchor in soup.find_all('a'):
            href = anchor.get('href')
            if not href or self._is_homepage_link(href):
                continue

            for tag_name, css_class in target['selectors']:
                child = getattr(anchor, tag_name, None)
                if child is None:
                    continue
                if css_class not in (child.get('class') or []):
                    continue

                title_text = child.get_text(strip=True)
                if title_text and href not in seen_links:
                    news.append({'materia': title_text, 'link': href, 'data': None})
                    seen_links.add(href)
        return news

    def _scrape_article_based(self, target):
        news = []
        seen_links = set()

        self._collect_article_page(target['url'], target['base_domain'], news, seen_links)

        webpart_url = target.get('webpart_url')
        if webpart_url:
            for page in range(2, target.get('extra_pages', 0) + 2):
                try:
                    self._collect_article_page(webpart_url.format(page=page), target['base_domain'], news, seen_links)
                except requests.RequestException:
                    break

        return news

    def _collect_article_page(self, url, base_domain, news, seen_links):
        response = _get_with_retry(url)
        soup = _soup(response)

        for article in soup.find_all('article'):
            title_tag = article.find(['h1', 'h2', 'h3'])
            if title_tag is None:
                continue

            link_tag = article.find_parent('a') or article.find('a', href=True)
            if link_tag is None:
                continue

            href = urljoin(base_domain, link_tag.get('href'))
            title_text = title_tag.get_text(strip=True)
            if title_text and href not in seen_links:
                news.append({'materia': title_text, 'link': href, 'data': None})
                seen_links.add(href)

    def _scrape_lista_interna(self, target):
        response = _get_with_retry(target['url'])
        soup = _soup(response)

        news = []
        seen_links = set()
        for anchor in soup.find_all('a', class_='lista-interna'):
            href = anchor.get('href')
            if not href or href in seen_links:
                continue

            img = anchor.find('img')
            title_text = (img.get('alt') if img else '') or ''
            title_text = title_text.strip()
            if not title_text:
                continue

            data = self._parse_data_hora(anchor.get_text(' ', strip=True))

            news.append({'materia': title_text, 'link': href, 'data': data})
            seen_links.add(href)
        return news

    def _scrape_link_list(self, target):
        response = _get_with_retry(target['url'])
        soup = _soup(response)

        news = []
        seen_links = set()
        for anchor in soup.select(target['link_selector']):
            href = anchor.get('href')
            if not href:
                continue
            href = urljoin(target['base_domain'], href)
            if href in seen_links:
                continue

            title_selector = target.get('title_selector')
            if title_selector:
                title_node = anchor.select_one(title_selector)
                title_text = title_node.get_text(' ', strip=True) if title_node else ''
            else:
                title_text = anchor.get_text(' ', strip=True)

            data = None
            if target.get('parse_date_from_text'):
                data = self._parse_data_hora(anchor.get_text(' ', strip=True))
                title_text = DATA_HORA_PATTERN.sub('', title_text).strip(' -–')

            if len(title_text) < target.get('min_title_len', 1):
                continue

            news.append({'materia': title_text, 'link': href, 'data': data})
            seen_links.add(href)
        return news

    @staticmethod
    def _parse_data_hora(texto):
        match = DATA_HORA_PATTERN.search(texto)
        if not match:
            return None
        data_str, hora, minuto = match.groups()
        try:
            return datetime.strptime(f'{data_str} {hora}:{minuto}', '%d/%m/%Y %H:%M')
        except ValueError:
            return None

    @staticmethod
    def _is_homepage_link(href):
        parsed = urlparse(href)
        return parsed.path in ('', '/') and not parsed.query
