"""Dedup por URL na coleta (NewsStore.add_news_many), sem banco real."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from storage import NewsStore

AGORA = datetime(2026, 11, 21, 1, 0)


class FakeConn:
    """Registra os SQLs; responde SELECT de links com `existentes`."""

    def __init__(self, existentes=()):
        self.existentes = set(existentes)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        cur = MagicMock()
        if sql.lstrip().startswith('SELECT link'):
            cur.fetchall.return_value = [
                {'link': l} for l in params[0] if l in self.existentes
            ]
        else:  # INSERT ... RETURNING id: uma linha por valor enviado
            n = len(params) // 6
            cur.fetchall.return_value = [{'id': i} for i in range(n)]
        return cur

    def commit(self):
        pass

    def close(self):
        pass


def store_com(conn):
    store = NewsStore.__new__(NewsStore)  # evita _init_schema (precisa de Postgres)
    store._connect = lambda: conn
    return store


def linha(fonte, titulo, link):
    return (fonte, titulo, link, AGORA, False)


class DedupPorUrlTests(unittest.TestCase):
    def test_descarta_url_ja_existente_com_titulo_diferente(self):
        conn = FakeConn(existentes={'https://x.com/a'})
        n = store_com(conn).add_news_many([
            linha('f1', 'Titulo reescrito', 'https://x.com/a'),
            linha('f1', 'Outra', 'https://x.com/b'),
        ])
        insert = [c for c in conn.calls if c[0].lstrip().startswith('INSERT')][0]
        self.assertEqual(n, 1)
        self.assertNotIn('https://x.com/a', insert[1])
        self.assertIn('https://x.com/b', insert[1])

    def test_dedup_dentro_do_lote_mantem_a_primeira(self):
        conn = FakeConn()
        n = store_com(conn).add_news_many([
            linha('f1', 'A', 'https://x.com/a'),
            linha('f2', 'A de novo', 'https://x.com/a'),
        ])
        self.assertEqual(n, 1)

    def test_tudo_duplicado_nao_faz_insert(self):
        conn = FakeConn(existentes={'https://x.com/a'})
        n = store_com(conn).add_news_many([linha('f1', 'A', 'https://x.com/a')])
        self.assertEqual(n, 0)
        self.assertFalse(any(c[0].lstrip().startswith('INSERT') for c in conn.calls))

    def test_lista_vazia(self):
        self.assertEqual(store_com(FakeConn()).add_news_many([]), 0)

    def test_consulta_usa_any_para_aproveitar_o_indice_de_link(self):
        conn = FakeConn()
        store_com(conn).add_news_many([linha('f1', 'A', 'https://x.com/a')])
        self.assertIn('link = ANY', conn.calls[0][0])


if __name__ == '__main__':
    unittest.main()
