"""Contract tests for the O Hoje DF/Brasília search source."""
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scraping_sites.site import Site, all_sites
from updater import collect_once


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode('utf-8')
        self.encoding = 'utf-8'
        self.apparent_encoding = 'utf-8'

    def raise_for_status(self):
        return None


def search_html(*cards):
    return (
        '<!doctype html><html><body class="search search-results wp-theme-ohoje">'
        '<main id="main">' + ''.join(cards) + '</main></body></html>'
    )


def article_card(post_id, href, title):
    return (
        f'<a href="{href}"><article class="row article-list-invert '
        f'category-cidades post-{post_id} post type-post status-publish hentry">'
        f'<div class="txt"><h2 class="titulo-txt">{title}</h2></div>'
        '</article></a>'
    )


class OHojeSourceTests(unittest.TestCase):
    def test_ohoje_source_searches_both_terms_and_deduplicates_articles(self):
        first = 'https://ohoje.com/2026/10/13/noticia-df/'
        shared = 'https://ohoje.com/2026/10/12/noticia-compartilhada/'
        second = 'https://ohoje.com/2026/10/11/noticia-brasilia/'
        pages = {
            'distrito federal': search_html(
                article_card(101, first, 'Notícia do Distrito Federal'),
                article_card(102, shared, 'Notícia de Brasília'),
            ),
            'brasília': search_html(
                article_card(102, shared, 'Notícia de Brasília'),
                article_card(103, second, 'Notícia em Brasília'),
            ),
        }
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            if 's=distrito%20federal' in url:
                return FakeResponse(pages['distrito federal'])
            if 's=bras%C3%ADlia' in url:
                return FakeResponse(pages['brasília'])
            raise AssertionError(f'Consulta inesperada: {url}')

        site = Site('ohoje-df')
        with patch('scraping_sites.site.requests.get', side_effect=fake_get):
            site.update_news()

        self.assertEqual(len(requested), 2)
        self.assertEqual({item['link'] for item in site.news}, {first, shared, second})
        self.assertEqual(len(site.news), 3)
        item = next(item for item in site.news if item['link'] == first)
        self.assertEqual(item['materia'], 'Notícia do Distrito Federal')
        self.assertEqual(item['data'].strftime('%Y-%m-%d'), '2026-10-13')
        self.assertTrue(item['estimada'])
        self.assertIn('ohoje-df', all_sites())

    def test_title_link_is_preferred_over_an_earlier_image_link(self):
        image_url = 'https://ohoje.com/2026/10/21/foto-link/'
        title_url = 'https://ohoje.com/2026/10/20/titulo-link/'
        other_url = 'https://ohoje.com/2026/10/19/outra-materia/'
        card = (
            '<article class="post type-post status-publish">'
            f'<a href="{image_url}">Imagem</a>'
            f'<h2><a href="{title_url}">Notícia correta</a></h2>'
            '</article>'
        )
        pages = {
            'distrito federal': search_html(card),
            'brasília': search_html(article_card(302, other_url, 'Outra notícia')),
        }

        def fake_get(url, **kwargs):
            if 's=distrito%20federal' in url:
                return FakeResponse(pages['distrito federal'])
            if 's=bras%C3%ADlia' in url:
                return FakeResponse(pages['brasília'])
            raise AssertionError(f'Consulta inesperada: {url}')

        site = Site('ohoje-df')
        with patch('scraping_sites.site.requests.get', side_effect=fake_get):
            site.update_news()

        links = {item['link'] for item in site.news}
        self.assertIn(title_url, links)
        self.assertNotIn(image_url, links)

    def test_non_https_article_links_are_rejected(self):
        unsafe_url = 'javascript://ohoje.com/2026/10/21/materia-insegura/'
        valid_url = 'https://ohoje.com/2026/10/20/materia-valida/'
        pages = {
            'distrito federal': search_html(
                article_card(301, unsafe_url, 'Link inseguro'),
            ),
            'brasília': search_html(
                article_card(302, valid_url, 'Matéria válida'),
            ),
        }

        def fake_get(url, **kwargs):
            if 's=distrito%20federal' in url:
                return FakeResponse(pages['distrito federal'])
            if 's=bras%C3%ADlia' in url:
                return FakeResponse(pages['brasília'])
            raise AssertionError(f'Consulta inesperada: {url}')

        site = Site('ohoje-df')
        with patch('scraping_sites.site.requests.get', side_effect=fake_get):
            site.update_news()

        self.assertEqual([item['link'] for item in site.news], [valid_url])

    def test_search_follows_next_links_but_caps_each_query_at_three_pages(self):
        urls = [
            'https://ohoje.com/?s=distrito%20federal',
            'https://ohoje.com/page/2/?s=distrito%20federal',
            'https://ohoje.com/page/3/?s=distrito%20federal',
            'https://ohoje.com/?s=bras%C3%ADlia',
            'https://ohoje.com/page/2/?s=bras%C3%ADlia',
            'https://ohoje.com/page/3/?s=bras%C3%ADlia',
        ]
        pages = {
            urls[0]: search_html(
                article_card(201, 'https://ohoje.com/2026/10/20/df-1/', 'DF 1'),
                '<a href="javascript://ohoje.com/page/2/?s=distrito%20federal">JS</a>',
                '<a href="/arquivo/page/2/?s=distrito%20federal">Caminho errado</a>',
                '<a href="/page/2/?s=distrito%20federal">2</a>',
            ),
            urls[1]: search_html(
                article_card(202, 'https://ohoje.com/2026/10/19/df-2/', 'DF 2'),
                '<a href="/page/3/?s=distrito%20federal">3</a>',
            ),
            urls[2]: search_html(
                article_card(203, 'https://ohoje.com/2026/10/18/df-3/', 'DF 3'),
                '<a href="/page/4/?s=distrito%20federal">4</a>',
            ),
            urls[3]: search_html(
                article_card(204, 'https://ohoje.com/2026/10/20/br-1/', 'Brasília 1'),
                '<a href="/page/2/?s=bras%C3%ADlia">2</a>',
            ),
            urls[4]: search_html(
                article_card(205, 'https://ohoje.com/2026/10/17/br-2/', 'Brasília 2'),
                '<a href="/page/3/?s=bras%C3%ADlia">3</a>',
            ),
            urls[5]: search_html(
                article_card(206, 'https://ohoje.com/2026/10/16/br-3/', 'Brasília 3'),
                '<a href="/page/4/?s=bras%C3%ADlia">4</a>',
            ),
        }
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            if url not in pages:
                raise AssertionError(f'Página além do limite ou URL inesperada: {url}')
            return FakeResponse(pages[url])

        site = Site('ohoje-df')
        with patch('scraping_sites.site.requests.get', side_effect=fake_get):
            site.update_news()

        self.assertEqual(requested, urls)
        self.assertEqual(len(site.news), 6)

    def test_ohoje_is_in_homepage_channel_shortcuts(self):
        template_path = Path(__file__).resolve().parents[1] / 'templates' / 'index.html'
        template = template_path.read_text(encoding='utf-8')
        self.assertIn("('ohoje-df', 'O Hoje (DF/Brasília)')", template)

    def test_approximate_news_timestamp_has_truthful_tooltip(self):
        template_path = Path(__file__).resolve().parents[1] / 'templates' / 'index.html'
        template = template_path.read_text(encoding='utf-8')
        self.assertEqual(template.count('title="Data ou horário aproximado"'), 3)
        self.assertNotIn('title="Data é a hora de coleta"', template)

    def test_collect_once_preserves_explicit_estimated_date_flag(self):
        date_item = {
            'materia': 'Notícia do Distrito Federal',
            'link': 'https://ohoje.com/2026/10/13/noticia-df/',
            'data': datetime(2026, 10, 13),
            'estimada': True,
        }

        class FakeSite:
            def __init__(self, name):
                self.news = [date_item]

            def update_news(self):
                return None

        class FakeStore:
            rows = []

            def add_news_many(self, rows):
                self.rows = list(rows)

        store = FakeStore()
        with patch('updater.Site', FakeSite):
            collect_once(store, sites=['ohoje-df'], log=lambda _: None)

        self.assertEqual(len(store.rows), 1)
        self.assertEqual(store.rows[0][3], date_item['data'])
        self.assertTrue(store.rows[0][4])


if __name__ == '__main__':
    unittest.main()
