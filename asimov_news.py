from scraping_sites.site import all_sites
import os
from datetime import datetime
import sys
import pickle
import webbrowser
from math import ceil

from pytimedinput import timedInput

from storage import NewsStore
from updater import BackgroundUpdater

class AsimovNews:
    PAGE_SIZE = 10

    def __init__(self):
        self.all_sites = all_sites()

        self.screen = 0

        self.page = 1
        self.search_term = None
        self.channel_filter = None
        self.date_range = None

        self.store = NewsStore()
        self._migrate_legacy_pickle_if_needed()

        self.sites = self.store.get_active_sites()

        # Coleta em background compartilhada com a versao web (updater.py)
        self.updater = BackgroundUpdater(self.store)
        self.updater.start()

    def _migrate_legacy_pickle_if_needed(self):
        if not self.store.is_empty() or 'news' not in os.listdir():
            return

        with open('news', 'rb') as fp:
            old_news = pickle.load(fp)
        old_sites = []
        if 'sites' in os.listdir():
            with open('sites', 'rb') as fp:
                old_sites = pickle.load(fp)

        self.store.migrate_from_pickle(old_news, old_sites)
        print(f'Migradas {len(old_news)} noticias do arquivo antigo para o banco SQLite (asimov_news.db).')
        input('Pressione Enter para continuar...')

    def _receive_command(self, valid_commands, timeout=30):
        command, timed = timedInput('>>', timeout)
        while command.lower() not in valid_commands and not timed:
            print("Comando inválido. Digite novamente\n")
            command, timed = timedInput('>>', timeout)
        command = 0 if command == '' else command
        return command

    def main_loop(self):
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')

            match self.screen:
                case 0:
                    print('SEJA BEM VINDO AO ASIMOV NEWS.')
                    print('Por favor escolha algum item do menu')
                    print('')
                    print("1. Ultimas Noticias\n2. Adicionar site\n3. Remover sites\n4. Buscar por assunto\n5. Selecionar canal\n6. Fechar o Programa")

                    self.screen = int(self._receive_command(['1', '2', '3', '4', '5', '6'], 5))

                case 1:
                    self.display_news()
                    valid = ['p', 'a', 'l', 'v']
                    if self.search_term: valid.append('x')
                    if self.channel_filter: valid.append('c')
                    if self.date_range: valid.append('d')
                    command = self._receive_command(valid, 5)
                    match command:
                        case 'p':
                            if self.page < self.max_page: self.page += 1

                        case 'a':
                                if self.page > 1: self.page -= 1

                        case 'v':
                            self.screen = 0
                            self.search_term = None
                            self.channel_filter = None
                            self.date_range = None
                            continue

                        case 'x':
                            self.search_term = None
                            self.page = 1

                        case 'c':
                            self.channel_filter = None
                            self.page = 1

                        case 'd':
                            self.date_range = None
                            self.page = 1

                        case 'l':
                            raw_link = input('>> Insira o numero da materia que deseja abrir: ')
                            if not raw_link.isdigit():
                                print('Numero invalido!')
                            else:
                                indice = int(raw_link) - 1 - self.page_offset
                                if indice < 0 or indice >= len(self.filtered_news):
                                    print('Materia inexistente!')
                                else:
                                    url = self.filtered_news[indice]['link']
                                    if not webbrowser.open(url):
                                        print(f'Nao foi possivel abrir o navegador automaticamente. Link: {url}')
                                        input('Pressione Enter para continuar...')
                                # if platform == "linux" or platform == "linux2": # Linux
                                #     chrome_path = '/usr/bin/google-chrome %s'
                                # elif platform == "darwin": # OS X
                                #     chrome_path = 'open -a /Applications/Google\ Chrome.app %s'
                                # elif platform == "win32": # Windows
                                #     chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                                # webbrowser.get(f"\"{chrome_path}\" %s").open(link)

                case 2:
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print('Digite o numero do site que deseja adicionar para a lista de sites ativos.\nPressione 0 para voltar para o menu.')
                    print("\tSITES ATIVOS ===============\n")
                    for i in self.sites:
                        print('\t', i)

                    print("\n\tSITES INATIVOS =============")
                    offline_sites = [i for i in self.all_sites if i not in self.sites]
                    for i in range(len(offline_sites)):
                        print(f'\t{i+1}. {offline_sites[i]}')
                    site= int(self._receive_command([str(i) for i in range(len(offline_sites)+1)], 50))

                    if site == 0:
                        self.screen=0
                        continue
                    novo_site = offline_sites[site-1]
                    self.sites += [novo_site]
                    self.store.add_active_site(novo_site)

                case 3:
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print('Digite o numero do site para remove-lo. Caso queira voltar para o Menu, digite 0\n')
                    for i in range(len(self.sites)):
                        print(f'\t{i+1}. {self.sites[i]}')
                    site= int(self._receive_command([str(i) for i in range(len(self.sites)+1)], 50))
                    if site == 0:
                        self.screen=0
                        continue

                    site_removido = self.sites.pop(site-1)
                    self.store.remove_active_site(site_removido)

                case 4:
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print('Digite o assunto que deseja buscar (ex: nome de uma pessoa, servico do GDF, "saude no DF").')
                    print('Deixe em branco e pressione Enter para voltar ao menu.\n')
                    termo = input('>> Buscar: ').strip()
                    if not termo:
                        self.screen = 0
                        continue
                    self.search_term = termo

                    print('\nFiltrar por periodo? (opcional)')
                    ano_inicial_raw = input('>> Ano inicial (ou Enter para buscar em todo o historico): ').strip()
                    if ano_inicial_raw.isdigit():
                        ano_final_raw = input(f'>> Ano final (ou Enter para usar {datetime.now().year}): ').strip()
                        ano_inicial = int(ano_inicial_raw)
                        ano_final = int(ano_final_raw) if ano_final_raw.isdigit() else datetime.now().year
                        if ano_final < ano_inicial:
                            ano_inicial, ano_final = ano_final, ano_inicial
                        self.date_range = (datetime(ano_inicial, 1, 1), datetime(ano_final, 12, 31, 23, 59, 59))
                    else:
                        self.date_range = None

                    self.page = 1
                    self.screen = 1

                case 5:
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print('Escolha o canal de noticias que deseja visualizar sozinho.')
                    print('Pressione 0 para voltar a ver todos os canais ativos.\n')
                    for i, site in enumerate(self.all_sites):
                        marcador = ' (ativo)' if site in self.sites else ' (inativo)'
                        print(f'\t{i+1}. {site}{marcador}')
                    canal = int(self._receive_command([str(i) for i in range(len(self.all_sites)+1)], 30))

                    if canal == 0:
                        self.channel_filter = None
                    else:
                        self.channel_filter = self.all_sites[canal-1]
                    self.page = 1
                    self.screen = 1

                case 6:
                    self.updater.stop()
                    sys.exit()

    def display_news(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"Último update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.search_term:
            print(f'Filtro de busca: "{self.search_term}" (X - limpar busca)')
        if self.channel_filter:
            print(f'Canal selecionado: {self.channel_filter.upper()} (C - limpar canal)')
        if self.date_range:
            print(f'Periodo: {self.date_range[0].year} a {self.date_range[1].year} (D - limpar periodo)')

        fontes = [self.channel_filter] if self.channel_filter else self.sites

        if self.date_range:
            min_date, max_date = self.date_range
        elif self.search_term:
            # busca por assunto olha todo o historico por padrao, nao so o ano atual
            min_date, max_date = None, None
        else:
            min_date, max_date = datetime(datetime.now().year, 1, 1), None

        total = self.store.count_news(fontes=fontes, search=self.search_term, min_date=min_date, max_date=max_date)
        self.max_page = max(1, ceil(total / self.PAGE_SIZE))

        if self.page > self.max_page: self.page = 1

        constante = (self.page - 1) * self.PAGE_SIZE
        self.page_offset = constante
        self.filtered_news = self.store.get_news(
            fontes=fontes,
            search=self.search_term,
            min_date=min_date,
            max_date=max_date,
            limit=self.PAGE_SIZE,
            offset=constante,
        )

        if not self.filtered_news:
            if self.search_term:
                print(f'Nenhuma noticia encontrada para o assunto "{self.search_term}".')
            else:
                print('Nenhuma noticia encontrada.')
        else:
            for i, article in enumerate(self.filtered_news):
                marcador_data = '~' if article.get('data_estimada') else ' '
                print(f"{constante+i+1}. {marcador_data}{article['data'].strftime('%d/%m/%Y %H:%M')} - {article['fonte'].upper()} - {article['materia']}")
        print(f'Page {self.page}/{self.max_page} ({total} materias)')

        print('================================================================\n')
        print('Comandos:')
        comandos = 'P - Proxima Pagina | A - Pagina Anterior | L - Abrir materia no navegador | V - Voltar'
        if self.search_term:
            comandos += ' | X - Limpar busca'
        if self.channel_filter:
            comandos += ' | C - Limpar canal'
        if self.date_range:
            comandos += ' | D - Limpar periodo'
        print(comandos)



self = AsimovNews()
self.main_loop()
