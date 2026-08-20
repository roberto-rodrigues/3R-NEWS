import os
import unicodedata
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
import psycopg.rows
from dotenv import load_dotenv

load_dotenv()

BRT = ZoneInfo("America/Sao_Paulo")


def now_brt():
    """Hora atual no fuso de Brasilia, ingenua (sem tzinfo) -- consistente com o resto
    do banco independente do fuso do host que roda o processo (local, GitHub Actions e
    Vercel podem estar em fusos diferentes; datetime.now() sozinho pegaria o do host)."""
    return datetime.now(BRT).replace(tzinfo=None)


def normalize_text(text):
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()


class NewsStore:
    def __init__(self, database_url=None):
        self.database_url = database_url or os.environ['DATABASE_URL']
        self._init_schema()

    def _connect(self):
        return psycopg.connect(
            self.database_url,
            prepare_threshold=None,
            row_factory=psycopg.rows.dict_row,
        )

    def _init_schema(self):
        with closing(self._connect()) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS noticias (
                    id BIGSERIAL PRIMARY KEY,
                    fonte TEXT NOT NULL,
                    materia TEXT NOT NULL,
                    materia_normalizada TEXT NOT NULL,
                    link TEXT NOT NULL,
                    data TIMESTAMP NOT NULL,
                    data_estimada INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(fonte, materia)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_noticias_data ON noticias(data DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_noticias_fonte ON noticias(fonte)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_noticias_busca ON noticias(materia_normalizada)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sites_ativos (
                    fonte TEXT PRIMARY KEY
                )
            ''')
            conn.commit()

    def add_news(self, fonte, materia, link, data, estimada=False):
        """Insere a noticia (ignorando duplicatas por fonte+materia). Retorna 1 se foi
        inserida de fato, 0 se ja existia."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                '''INSERT INTO noticias (fonte, materia, materia_normalizada, link, data, data_estimada)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (fonte, materia) DO NOTHING''',
                (fonte, materia, normalize_text(materia), link, data, int(bool(estimada))),
            )
            conn.commit()
            return cursor.rowcount

    def get_news(self, fontes=None, search=None, min_date=None, max_date=None, limit=None, offset=0):
        if fontes is not None and len(fontes) == 0:
            return []

        query = 'SELECT fonte, materia, link, data, data_estimada FROM noticias'
        conditions = []
        params = []

        if fontes:
            placeholders = ','.join('%s' * len(fontes))
            conditions.append(f'fonte IN ({placeholders})')
            params.extend(fontes)
        if search:
            conditions.append('materia_normalizada LIKE %s')
            params.append(f'%{normalize_text(search)}%')
        if min_date:
            conditions.append('data >= %s')
            params.append(min_date)
        if max_date:
            conditions.append('data <= %s')
            params.append(max_date)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY data DESC'
        if limit is not None:
            query += ' LIMIT %s OFFSET %s'
            params.extend([limit, offset])

        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                'fonte': row['fonte'],
                'materia': row['materia'],
                'link': row['link'],
                'data': row['data'],
                'data_estimada': bool(row['data_estimada']),
            }
            for row in rows
        ]

    def count_news(self, fontes=None, search=None, min_date=None, max_date=None):
        if fontes is not None and len(fontes) == 0:
            return 0

        query = 'SELECT COUNT(*) AS c FROM noticias'
        conditions = []
        params = []

        if fontes:
            placeholders = ','.join('%s' * len(fontes))
            conditions.append(f'fonte IN ({placeholders})')
            params.extend(fontes)
        if search:
            conditions.append('materia_normalizada LIKE %s')
            params.append(f'%{normalize_text(search)}%')
        if min_date:
            conditions.append('data >= %s')
            params.append(min_date)
        if max_date:
            conditions.append('data <= %s')
            params.append(max_date)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        with closing(self._connect()) as conn:
            return conn.execute(query, params).fetchone()['c']

    def get_active_sites(self):
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT fonte FROM sites_ativos').fetchall()
        return [row['fonte'] for row in rows]

    def get_all_sources(self):
        """Fontes distintas que ja possuem noticias no banco, em ordem alfabetica."""
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT DISTINCT fonte FROM noticias ORDER BY fonte').fetchall()
        return [row['fonte'] for row in rows]

    def count_by_source(self):
        """Quantidade de noticias por fonte, como dict {fonte: total}."""
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT fonte, COUNT(*) AS c FROM noticias GROUP BY fonte').fetchall()
        return {row['fonte']: row['c'] for row in rows}

    def get_date_bounds(self):
        """Menor e maior ano com noticias, para montar o filtro de periodo. (None, None) se vazio."""
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT MIN(data) AS mn, MAX(data) AS mx FROM noticias').fetchone()
        if not row or row['mn'] is None:
            return None, None
        return row['mn'].year, row['mx'].year

    def add_active_site(self, fonte):
        with closing(self._connect()) as conn:
            conn.execute(
                'INSERT INTO sites_ativos (fonte) VALUES (%s) ON CONFLICT (fonte) DO NOTHING',
                (fonte,),
            )
            conn.commit()

    def remove_active_site(self, fonte):
        with closing(self._connect()) as conn:
            conn.execute('DELETE FROM sites_ativos WHERE fonte = %s', (fonte,))
            conn.commit()

    def is_empty(self):
        with closing(self._connect()) as conn:
            count = conn.execute('SELECT COUNT(*) AS c FROM noticias').fetchone()['c']
        return count == 0
