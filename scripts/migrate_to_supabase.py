"""Migracao unica: copia asimov_news.db (SQLite local) para o Supabase (Postgres).

Roda uma vez, da maquina local. Seguro executar de novo (ON CONFLICT DO NOTHING),
caso precise retomar apos uma falha no meio do caminho.

Uso:
    python scripts/migrate_to_supabase.py
"""
import os
import sqlite3
import sys
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import NewsStore, normalize_text  # noqa: E402

SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'asimov_news.db')


def _sqlite_rows():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    with closing(conn):
        noticias = conn.execute(
            'SELECT fonte, materia, link, data, data_estimada FROM noticias'
        ).fetchall()
        sites = [row['fonte'] for row in conn.execute('SELECT fonte FROM sites_ativos').fetchall()]
    return noticias, sites


def main():
    from datetime import datetime

    noticias, sites = _sqlite_rows()
    print(f'Lidas {len(noticias)} noticias e {len(sites)} canais ativos do SQLite local.')

    store = NewsStore()

    with closing(store._connect()) as conn:
        inseridas = 0
        for i, row in enumerate(noticias, 1):
            data = datetime.fromisoformat(row['data'])
            cursor = conn.execute(
                '''INSERT INTO noticias (fonte, materia, materia_normalizada, link, data, data_estimada)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (fonte, materia) DO NOTHING''',
                (row['fonte'], row['materia'], normalize_text(row['materia']), row['link'], data, row['data_estimada']),
            )
            inseridas += cursor.rowcount
            if i % 500 == 0:
                conn.commit()
                print(f'  {i}/{len(noticias)}...')
        for fonte in sites:
            conn.execute('INSERT INTO sites_ativos (fonte) VALUES (%s) ON CONFLICT (fonte) DO NOTHING', (fonte,))
        conn.commit()

    print(f'Migracao concluida: {inseridas} noticias novas inseridas no Supabase.')
    print(f'Total agora no Supabase: {store.count_news()} (SQLite local tinha {len(noticias)}).')


if __name__ == '__main__':
    main()
