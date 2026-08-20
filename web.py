"""Interface web local do Asimov News (Fase 1 - visualizador de leitura).

Roda um servidor Flask sobre o mesmo banco SQLite usado pela versao de terminal,
reaproveitando a camada NewsStore. Nao altera o schema nem coleta noticias: apenas
le e exibe, com busca, filtros combinados (canal + periodo) e paginacao.

Uso:
    python web.py            # abre em http://127.0.0.1:5000
"""
import os
from datetime import datetime
from math import ceil

from flask import Flask, render_template, request, redirect, url_for
from markupsafe import Markup, escape

from storage import NewsStore, normalize_text, now_brt
from updater import BackgroundUpdater
from scraping_sites.site import all_sites
from deep_search import deep_search, supported_sources

PAGE_SIZE = 20
# Valor especial do filtro de canal: restringe o feed as fontes ativas (sites_ativos).
ESCOPO_ATIVOS = '__ativos__'
# Coletar em background junto com o servidor (Fase 2). Defina ASIMOV_NO_COLLECT=1 para
# subir a interface apenas como visualizador, sem raspar as fontes.
COLETAR = os.environ.get('ASIMOV_NO_COLLECT') != '1'

app = Flask(__name__)
store = NewsStore()


def _parse_int(value, default=None):
    value = (value or '').strip()
    return int(value) if value.isdigit() else default


def _highlight(texto, termo):
    """Envolve as ocorrencias de `termo` em <mark>, de forma insensivel a acento e caixa.

    A busca do banco e feita sobre o texto normalizado (sem acento, minusculo), entao o
    destaque tambem precisa casar assim. Normalizamos caractere a caractere, guardando o
    indice original de cada posicao normalizada, e mapeamos os trechos casados de volta ao
    texto original. O escape de HTML e aplicado em todos os pedacos (seguro contra XSS).
    """
    termo_norm = normalize_text(termo) if termo else ''
    if not termo_norm:
        return escape(texto)

    norm_chars = []
    orig_index = []
    for i, ch in enumerate(texto):
        for nc in normalize_text(ch):
            norm_chars.append(nc)
            orig_index.append(i)
    norm_str = ''.join(norm_chars)

    resultado = Markup('')
    cursor = 0
    busca = 0
    passo = len(termo_norm)
    while True:
        pos = norm_str.find(termo_norm, busca)
        if pos == -1:
            break
        ini = orig_index[pos]
        fim = orig_index[pos + passo - 1] + 1
        resultado += escape(texto[cursor:ini])
        resultado += Markup('<mark>') + escape(texto[ini:fim]) + Markup('</mark>')
        cursor = fim
        busca = pos + passo
    resultado += escape(texto[cursor:])
    return resultado


@app.route('/')
def index():
    termo = (request.args.get('q') or '').strip()
    fonte = (request.args.get('fonte') or '').strip()
    hoje = request.args.get('hoje') == '1'
    ano_ini = _parse_int(request.args.get('ano_ini'))
    ano_fim = _parse_int(request.args.get('ano_fim'))
    page = _parse_int(request.args.get('page'), 1) or 1
    # Resultado da ultima busca profunda (preenchido pelo redirect de /busca-profunda).
    deep_resultado = _parse_int(request.args.get('novas')) if 'novas' in request.args else None

    if ano_ini and ano_fim and ano_fim < ano_ini:
        ano_ini, ano_fim = ano_fim, ano_ini

    if fonte == ESCOPO_ATIVOS:
        fontes = store.get_active_sites()
    elif fonte:
        fontes = [fonte]
    else:
        fontes = None
    if hoje:
        # "Noticias de hoje" tem precedencia sobre o filtro de periodo por ano.
        agora = now_brt()
        min_date = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = agora.replace(hour=23, minute=59, second=59, microsecond=999999)
        ano_ini = ano_fim = None
    else:
        min_date = datetime(ano_ini, 1, 1) if ano_ini else None
        max_date = datetime(ano_fim, 12, 31, 23, 59, 59) if ano_fim else None

    filtros = dict(fontes=fontes, search=termo or None, min_date=min_date, max_date=max_date)
    total = store.count_news(**filtros)
    max_page = max(1, ceil(total / PAGE_SIZE))
    page = min(max(page, 1), max_page)
    offset = (page - 1) * PAGE_SIZE

    noticias = store.get_news(limit=PAGE_SIZE, offset=offset, **filtros)
    for n in noticias:
        n['titulo_html'] = _highlight(n['materia'], termo)

    ano_min, ano_max = store.get_date_bounds()

    return render_template(
        'index.html',
        noticias=noticias,
        total=total,
        page=page,
        max_page=max_page,
        primeiro=offset + 1 if total else 0,
        ultimo=min(offset + PAGE_SIZE, total),
        termo=termo,
        fonte=fonte,
        hoje=hoje,
        ano_ini=ano_ini or '',
        ano_fim=ano_fim or '',
        fontes_disponiveis=store.get_all_sources(),
        n_ativos=len(store.get_active_sites()),
        escopo_ativos=ESCOPO_ATIVOS,
        deep_resultado=deep_resultado,
        deep_sources=supported_sources(),
        ano_min=ano_min,
        ano_max=ano_max,
        tem_filtro=bool(termo or fonte or ano_ini or ano_fim or hoje),
        atualizado_em=now_brt().strftime('%d/%m/%Y %H:%M'),
    )


@app.route('/busca-profunda', methods=['POST'])
def busca_profunda():
    termo = (request.form.get('q') or '').strip()
    fonte = (request.form.get('fonte') or '').strip()
    hoje = request.form.get('hoje') == '1'
    ano_ini = _parse_int(request.form.get('ano_ini'))
    ano_fim = _parse_int(request.form.get('ano_fim'))
    if ano_ini and ano_fim and ano_fim < ano_ini:
        ano_ini, ano_fim = ano_fim, ano_ini

    if hoje:
        agora = now_brt()
        min_date = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = agora.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        min_date = datetime(ano_ini, 1, 1) if ano_ini else None
        max_date = datetime(ano_fim, 12, 31, 23, 59, 59) if ano_fim else None

    novas = 0
    if termo:
        novas, _ = deep_search(store, termo, min_date=min_date, max_date=max_date)

    # Volta para o feed com os mesmos filtros e a contagem de importadas.
    return redirect(url_for(
        'index', q=termo, fonte=fonte or None,
        ano_ini=ano_ini or None, ano_fim=ano_fim or None,
        hoje=('1' if hoje else None), novas=novas,
    ))


@app.route('/canais', methods=['GET', 'POST'])
def canais():
    todas = all_sites()

    if request.method == 'POST':
        marcados = set(request.form.getlist('ativos'))
        atuais = set(store.get_active_sites())
        for fonte in todas:
            if fonte in marcados and fonte not in atuais:
                store.add_active_site(fonte)
            elif fonte not in marcados and fonte in atuais:
                store.remove_active_site(fonte)
        return redirect(url_for('canais', salvo=1))

    ativos = set(store.get_active_sites())
    contagens = store.count_by_source()
    canais_info = [
        {'nome': f, 'ativo': f in ativos, 'total': contagens.get(f, 0)}
        for f in todas
    ]
    return render_template(
        'canais.html',
        canais=canais_info,
        n_ativos=len(ativos),
        n_total=len(todas),
        salvo=request.args.get('salvo') == '1',
        total=store.count_news(),
        atualizado_em=now_brt().strftime('%d/%m/%Y %H:%M'),
    )


if __name__ == '__main__':
    # Com o reloader do Flask ativo, o processo pai apenas observa arquivos; a coleta deve
    # rodar so no processo filho (WERKZEUG_RUN_MAIN) para nao duplicar as raspagens.
    if COLETAR and os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        BackgroundUpdater(store).start()
    app.run(host='127.0.0.1', port=5000, debug=True)
