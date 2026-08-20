"""Dispara uma unica passada de coleta (usado pelo workflow do GitHub Actions).

Uso:
    python scripts/run_collect.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import NewsStore  # noqa: E402
from updater import collect_once  # noqa: E402

if __name__ == '__main__':
    store = NewsStore()
    total = collect_once(store)
    print(f'Collected {total} items')
