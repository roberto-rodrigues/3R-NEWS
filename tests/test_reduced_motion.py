"""Movimento reduzido deve valer também para o botão de voltar ao topo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_botao_topo_respeita_preferencia_de_movimento():
    base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
    assert "matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'" in base
