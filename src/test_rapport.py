"""Contrôles du rapport quotidien et du visuel des grilles, avec des données fictives."""
import datetime as dt
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rapport  # noqa: E402


class Calculs(unittest.TestCase):
    def test_probabilites_normalisees(self):
        h = {'vec': {k: 0.5 for k in ['dW', 'dD', 'dL', 'forme', 'gf', 'ga', 'rest', 'load', 'cadF', 'cadA', 'cor', 'car',
                                      'eW', 'eD', 'eL']}}
        a = {'vec': dict(h['vec'])}
        modele = {'ordonnee': {'H': 0.1, 'D': 0.0, 'A': -0.1},
                  'coef': {c: [0.01] * 25 for c in 'HDA'}, 'moyenne': [0.0] * 25, 'echelle': [1.0] * 25}
        p = rapport.proba_match(h, a, modele, 100)
        self.assertAlmostEqual(sum(p.values()), 1.0, places=9)
        self.assertGreater(p['H'], p['A'])

    def test_fenetre_de_resultat(self):
        idx = {('F1', 'Lens', 'Lille'): [(dt.date(2026, 11, 7), 'H', 2, 1)]}
        self.assertIsNotNone(rapport.resultat_de(idx, 'F1', 'Lens', 'Lille', dt.date(2026, 11, 6)))
        self.assertIsNone(rapport.resultat_de(idx, 'F1', 'Lens', 'Lille', dt.date(2026, 11, 20)))
        self.assertIsNone(rapport.resultat_de(idx, 'F1', 'Lille', 'Lens', dt.date(2026, 11, 7)))

    def test_date_francaise(self):
        self.assertEqual(rapport.date_fr(dt.date(2026, 11, 3)), '3 novembre 2026')
        self.assertEqual(rapport.date_fr(dt.date(2026, 11, 1)), '1er novembre 2026')


class RapportDuJour(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self._origine = rapport.RAPPORTS
        rapport.RAPPORTS = pathlib.Path(self._dossier.name)

    def tearDown(self):
        rapport.RAPPORTS = self._origine
        self._dossier.cleanup()

    def test_bilan_de_la_veille(self):
        veille = dt.date(2026, 11, 3)
        rows = [
            {'league': 'F1', 'home': 'Lens', 'away': 'Lille', 'date': veille, 'result': 'H', 'hg': 2, 'ag': 1},
            {'league': 'F1', 'home': 'Brest', 'away': 'Nice', 'date': veille, 'result': 'A', 'hg': 0, 'ag': 2},
            {'league': 'E0', 'home': 'Arsenal', 'away': 'Chelsea', 'date': veille, 'result': 'D', 'hg': 1, 'ag': 1},
        ]
        journal = [
            {'ligue': 'F1', 'domicile': 'Lens', 'exterieur': 'Lille', 'date': '2026-11-03', 'pronostic': '1',
             'proba': {'1': 0.5, 'N': 0.25, '2': 0.25}},
            {'ligue': 'F1', 'domicile': 'Brest', 'exterieur': 'Nice', 'date': '2026-11-03', 'pronostic': '1',
             'proba': {'1': 0.6, 'N': 0.2, '2': 0.2}},
        ]
        rapport.rapport_du_jour(rows, journal, [], dt.date(2026, 11, 4))
        texte = (pathlib.Path(self._dossier.name) / 'jour-2026-11-03.md').read_text(encoding='utf-8')
        self.assertIn('Matchs joués la veille dans nos 16 championnats : **3**, dont **2**', texte)
        self.assertIn('Précision : **1 / 2** (50 %).', texte)
        self.assertIn('Résultats surprenants', texte)
        self.assertIn('Brest – Nice', texte)
        self.assertIn('pas de prévision enregistrée', texte)


class VisuelGrilles(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self._origine = rapport.RAPPORTS
        rapport.RAPPORTS = pathlib.Path(self._dossier.name)

    def tearDown(self):
        rapport.RAPPORTS = self._origine
        self._dossier.cleanup()

    def test_match_joue_marque_bon_pronostic(self):
        entree = {'format': 8, 'numero': 154, 'n': 1, 'ligue': 'F1', 'domicile': 'Lens', 'exterieur': 'Lille',
                  'cloture': '2026-11-03T20:00:00+01:00', 'pronostic': '1',
                  'proba': {'1': 0.5, 'N': 0.25, '2': 0.25}}
        idx = {('F1', 'Lens', 'Lille'): [(dt.date(2026, 11, 3), 'H', 2, 1)]}
        rapport.page_grilles([entree], idx, dt.datetime(2026, 11, 4, 8, 0, tzinfo=dt.timezone.utc), {'F1': 'France L1'})
        texte = (pathlib.Path(self._dossier.name) / 'grilles.html').read_text(encoding='utf-8')
        self.assertIn('class="match ok"', texte)
        self.assertIn('✓ prévu', texte)
        self.assertIn('France L1', texte)
        self.assertIn('1 / 1 (100 %)', texte)


if __name__ == '__main__':
    unittest.main()
