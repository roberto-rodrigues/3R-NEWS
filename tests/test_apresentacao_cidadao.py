"""Contrato mínimo de conteúdo da apresentação cidadã do 3R NEWS."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ApresentacaoCidadaoTests(unittest.TestCase):
    def test_home_explains_purpose_before_search(self):
        base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
        home = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
        self.assertIn('{% block mast_intro %}{% endblock %}', base)
        self.assertLess(base.index('{% block mast_intro %}'), base.index('<div class="searchbar">'))
        self.assertIn('{% block mast_intro %}', home)
        self.assertIn('Notícias do DF em um só lugar', home)
        self.assertIn('pesquise um assunto', home)
        self.assertIn('site da fonte original', home)

    def test_footer_clarifies_responsibility_and_css_is_synced(self):
        base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
        self.assertIn('O 3R-NEWS reúne links de notícias publicadas por outras fontes.', base)
        self.assertIn('responsabilidade do veículo que a publicou', base)
        css = (ROOT / 'static/style.css').read_bytes()
        self.assertEqual(css, (ROOT / 'public/static/style.css').read_bytes())
        self.assertIn(b'.mast-intro', css)
        self.assertIn(b'.ft{border-top:1px solid var(--fio);padding:var(--sp4) var(--sp4) var(--sp5)', css)
        self.assertIn('class="ft-note"><span>', base)
        self.assertIn(b'.ft-note{flex-basis:100%;margin:0;font-size:14px', css)
        self.assertIn(b'.ft-note span{display:block;max-width:78ch}', css)


if __name__ == '__main__':
    unittest.main()
