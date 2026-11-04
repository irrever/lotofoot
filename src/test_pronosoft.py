"""Contrôles de la lecture des grilles Pronosoft et du fichier de relevés (sans accès au site)."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pronosoft  # noqa: E402

PAGE = """<html><body>
<h2>Loto Foot 7 n137</h2>
<table>
<tr><td class="equipe1">Villarreal</td><td class="equipe2">Paris SG</td><td><span class="score-ft">0-6</span></td></tr>
<tr><td class="equipe1">Bod/Glimt</td><td class="equipe2">Lille</td><td><span class="score-ft">0-0</span></td></tr>
<tr><td class="equipe1">Lens</td><td class="equipe2">Lille</td><td><span class="score-ft">a-b</span></td></tr>
</table>
</body></html>"""


class FauxLecteur:
    def lire(self, chemin):
        self.chemin = chemin
        return PAGE


class Lecture(unittest.TestCase):
    def test_grilles_et_issues(self):
        grilles = pronosoft.lire_loto(PAGE)
        self.assertEqual(len(grilles), 1)
        self.assertEqual(grilles[0]['libelle'], 'Loto Foot 7 n137')
        self.assertEqual([(m['domicile'], m['score'], m['issue']) for m in grilles[0]['matchs']],
                         [('Villarreal', '0-6', '2'), ('Bod/Glimt', '0-0', 'N')])


class Fusion(unittest.TestCase):
    def test_garde_la_date_du_premier_releve(self):
        existants = [{'domicile': 'Villarreal', 'exterieur': 'Paris SG', 'score': '0-6', 'vu': '2026-11-04',
                      'grilles': ['Loto Foot 15 n90']}]
        matchs, nouveaux = pronosoft.fusionner_loto(existants, pronosoft.lire_loto(PAGE), '2026-11-05')
        self.assertEqual(nouveaux, 1)
        ancien = next(m for m in matchs if m['domicile'] == 'Villarreal')
        self.assertEqual((ancien['vu'], ancien['grilles']), ('2026-11-04', ['Loto Foot 15 n90', 'Loto Foot 7 n137']))
        self.assertEqual(next(m for m in matchs if m['domicile'] == 'Bod/Glimt')['vu'], '2026-11-05')

    def test_collecte_ecrit_le_fichier(self):
        with tempfile.TemporaryDirectory() as dossier:
            sortie = pathlib.Path(dossier) / 'pronosoft.json'
            pronosoft.collecter(FauxLecteur(), sortie=sortie, aujourdhui=dt.date(2026, 11, 5))
            contenu = json.loads(sortie.read_text(encoding='utf-8'))
            self.assertEqual((contenu['maj'], len(contenu['matchs'])), ('2026-11-05', 2))


if __name__ == '__main__':
    unittest.main()
