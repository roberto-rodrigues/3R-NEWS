import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime


def normalize_text(text):
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()


class NewsStore:
    def __init__(self, db_path='asimov_news.db'):
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with closing(self._connect()) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS noticias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fonte TEXT NOT NULL,
                    materia TEXT NOT NULL,
                    materia_normalizada TEXT NOT NULL,
                    link TEXT NOT NULL,
                    data TIMESTAMP NOT NULL,
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

            # data_estimada = 1 quando a data e a hora da coleta (datetime.now()), nao a
            # publicacao real. Migracao nao-destrutiva: a coluna e adicionada uma unica vez e
            # o backfill marca as linhas historicas pela assinatura de microssegundos, que so
            # aparece em datetime.now() (datas de RSS/HTML tem resolucao de segundo/minuto).
            existing_columns = [row[1] for row in conn.execute('PRAGMA table_info(noticias)')]
            if 'data_estimada' not in existing_columns:
                conn.execute('ALTER TABLE noticias ADD COLUMN data_estimada INTEGER NOT NULL DEFAULT 0')
                conn.execute("UPDATE noticias SET data_estimada = 1 WHERE data LIKE '%.%'")

            conn.commit()

    def add_news(self, fonte, materia, link, data, estimada=False):
        """Insere a noticia (ignorando duplicatas por fonte+materia). Retorna 1 se foi
        inserida de fato, 0 se ja existia."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                '''INSERT OR IGNORE INTO noticias (fonte, materia, materia_normalizada, link, data, data_estimada)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (fonte, materia, normalize_text(materia), link, data.isoformat(), int(bool(estimada))),
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
            placeholders = ','.join('?' * len(fontes))
            conditions.append(f'fonte IN ({placeholders})')
            params.extend(fontes)
        if search:
            conditions.append('materia_normalizada LIKE ?')
            params.append(f'%{normalize_text(search)}%')
        if min_date:
            conditions.append('data >= ?')
            params.append(min_date.isoformat())
        if max_date:
            conditions.append('data <= ?')
            params.append(max_date.isoformat())
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY data DESC'
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                'fonte': row['fonte'],
                'materia': row['materia'],
                'link': row['link'],
                'data': datetime.fromisoformat(row['data']),
                'data_estimada': bool(row['data_estimada']),
            }
            for row in rows
        ]

    def count_news(self, fontes=None, search=None, min_date=None, max_date=None):
        if fontes is not None and len(fontes) == 0:
            return 0

        query = 'SELECT COUNT(*) FROM noticias'
        conditions = []
        params = []

        if fontes:
            placeholders = ','.join('?' * len(fontes))
            conditions.append(f'fonte IN ({placeholders})')
            params.extend(fontes)
        if search:
            conditions.append('materia_normalizada LIKE ?')
            params.append(f'%{normalize_text(search)}%')
        if min_date:
            conditions.append('data >= ?')
            params.append(min_date.isoformat())
        if max_date:
            conditions.append('data <= ?')
            params.append(max_date.isoformat())
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        with closing(self._connect()) as conn:
            return conn.execute(query, params).fetchone()[0]

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
            row = conn.execute('SELECT MIN(data), MAX(data) FROM noticias').fetchone()
        if not row or row[0] is None:
            return None, None
        return datetime.fromisoformat(row[0]).year, datetime.fromisoformat(row[1]).year

    def add_active_site(self, fonte):
        with closing(self._connect()) as conn:
            conn.execute('INSERT OR IGNORE INTO sites_ativos (fonte) VALUES (?)', (fonte,))
            conn.commit()

    def remove_active_site(self, fonte):
        with closing(self._connect()) as conn:
            conn.execute('DELETE FROM sites_ativos WHERE fonte = ?', (fonte,))
            conn.commit()

    def is_empty(self):
        with closing(self._connect()) as conn:
            count = conn.execute('SELECT COUNT(*) FROM noticias').fetchone()[0]
        return count == 0

    def migrate_from_pickle(self, news_list, sites_list):
        with closing(self._connect()) as conn:
            for item in news_list:
                estimada = 1 if item['data'].microsecond else 0
                conn.execute(
                    '''INSERT OR IGNORE INTO noticias (fonte, materia, materia_normalizada, link, data, data_estimada)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (item['fonte'], item['materia'], normalize_text(item['materia']), item['link'], item['data'].isoformat(), estimada),
                )
            for fonte in sites_list:
                conn.execute('INSERT OR IGNORE INTO sites_ativos (fonte) VALUES (?)', (fonte,))
            conn.commit()
