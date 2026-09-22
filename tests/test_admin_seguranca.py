"""Testes de segurança da área de administração do 3R-NEWS.

Contexto (18/09/2026): em produção, /canais respondia HTTP 200 sem login — a
ausência de ADMIN_KEY deixava a página aberta, permitindo que qualquer visitante
ligasse/desligasse as fontes de notícia do site. Além disso, o `SECRET_KEY` tinha
valor padrão conhecido, o que permitiria forjar o cookie de admin assim que uma
senha fosse configurada.

Estes testes fixam o comportamento correto: em produção o acesso é FECHADO por
padrão; fora de produção, segue liberado para o trabalho local.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

SEGREDO_CONHECIDO = "dev-only-insecure-key"


def carrega_web(monkeypatch, **env):
    """Importa o web.py em ambiente limpo, com store dublê (não toca no banco)."""
    for chave in ("ADMIN_KEY", "SECRET_KEY", "VERCEL", "VERCEL_ENV", "FLASK_ENV"):
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in env.items():
        monkeypatch.setenv(chave, valor)

    import storage

    class _StoreDuble:
        """Dublê do NewsStore: nenhum teste aqui deve tocar no banco."""

        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, nome):
            # os templates chamam varios metodos do store; devolve valores neutros
            if nome.startswith(("get_visitas", "count_")):
                return lambda *a, **k: 0
            return lambda *a, **k: []

    monkeypatch.setattr(storage, "NewsStore", _StoreDuble)
    sys.modules.pop("web", None)
    return importlib.import_module("web")


def test_producao_sem_admin_key_fecha_a_area(monkeypatch):
    """O caso do incidente: produção sem ADMIN_KEY não pode liberar /canais."""
    web = carrega_web(monkeypatch, VERCEL="1")
    with web.app.test_client() as cliente:
        resposta = cliente.get("/canais")
    assert resposta.status_code in (301, 302), "producao sem ADMIN_KEY deve exigir login"


def test_desenvolvimento_sem_admin_key_continua_liberado(monkeypatch):
    web = carrega_web(monkeypatch)
    with web.app.test_request_context():
        assert web._admin_ok() is True


def test_producao_sem_admin_key_nega_mesmo_com_sessao(monkeypatch):
    web = carrega_web(monkeypatch, VERCEL="1")
    with web.app.test_request_context():
        assert web._admin_ok() is False


def test_login_com_senha_correta_autentica(monkeypatch):
    web = carrega_web(monkeypatch, VERCEL="1", ADMIN_KEY="segredo-de-teste")
    with web.app.test_client() as cliente:
        resposta = cliente.post("/admin-login", data={"senha": "segredo-de-teste"})
        assert resposta.status_code == 302
        with cliente.session_transaction() as sessao:
            assert sessao.get("admin") is True


def test_login_com_senha_errada_nao_autentica(monkeypatch):
    web = carrega_web(monkeypatch, VERCEL="1", ADMIN_KEY="segredo-de-teste")
    with web.app.test_client() as cliente:
        resposta = cliente.post("/admin-login", data={"senha": "errada"})
        assert resposta.status_code == 200
        with cliente.session_transaction() as sessao:
            assert sessao.get("admin") is None


def test_login_sem_admin_key_configurada_responde_503(monkeypatch):
    """Sem chave configurada não há como autenticar: melhor recusar que liberar."""
    web = carrega_web(monkeypatch, VERCEL="1")
    with web.app.test_client() as cliente:
        resposta = cliente.post("/admin-login", data={"senha": ""})
    assert resposta.status_code == 503


def test_secret_key_nao_usa_o_valor_conhecido_em_producao(monkeypatch):
    web = carrega_web(monkeypatch, VERCEL="1")
    assert web.app.secret_key != SEGREDO_CONHECIDO
    assert len(str(web.app.secret_key)) >= 32


def test_secret_key_configurada_e_respeitada(monkeypatch):
    web = carrega_web(monkeypatch, VERCEL="1", SECRET_KEY="chave-escolhida-pelo-usuario")
    assert web.app.secret_key == "chave-escolhida-pelo-usuario"
