"""Contrôles du rapport de la veille et des résultats des grilles, avec des données fictives."""
import datetime as dt
import pathlib
import sys
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


class JourDeLaVeille(unittest.TestCase):
    def setUp(self):
        veille = dt.date(2026, 11, 3)
        self.rows = [
            {'league': 'F1', 'home': 'Lens', 'away': 'Lille', 'date': veille, 'result': 'H', 'hg': 2, 'ag': 1},
            {'league': 'F1', 'home': 'Brest', 'away': 'Nice', 'date': veille, 'result': 'A', 'hg': 0, 'ag': 2},
            {'league': 'E0', 'home': 'Arsenal', 'away': 'Chelsea', 'date': veille, 'result': 'D', 'hg': 1, 'ag': 1},
        ]
        self.journal = [
            {'ligue': 'F1', 'domicile': 'Lens', 'exterieur': 'Lille', 'date': '2026-11-03', 'pronostic': '1',
             'proba': {'1': 0.5, 'N': 0.25, '2': 0.25}},
            {'ligue': 'F1', 'domicile': 'Brest', 'exterieur': 'Nice', 'date': '2026-11-03', 'pronostic': '1',
             'proba': {'1': 0.6, 'N': 0.2, '2': 0.2}, 'malus': {'domicile': -4, 'exterieur': -13}},
        ]
        self.jour = rapport.jour_de_la_veille(self.rows, self.journal, [], {}, {'F1': 'France L1'},
                                              dt.date(2026, 11, 4))

    def test_structure_du_jour(self):
        self.assertEqual(self.jour['date'], '2026-11-03')
        self.assertEqual(self.jour['joues'], 3)
        self.assertEqual(self.jour['avec_prevision'], 2)
        self.assertEqual(self.jour['precision'], {'ok': 1, 'n': 2})
        lens = next(m for m in self.jour['matchs'] if m['domicile'] == 'Lens')
        self.assertEqual(lens['championnat'], 'France L1')

    def test_surprise_et_absences(self):
        brest = next(m for m in self.jour['matchs'] if m['domicile'] == 'Brest')
        self.assertTrue(brest['surprise'])
        self.assertEqual(brest['verdict'], 'ko')
        self.assertEqual(brest['absences'], {'domicile': -4, 'exterieur': -13})
        arsenal = next(m for m in self.jour['matchs'] if m['domicile'] == 'Arsenal')
        self.assertIsNone(arsenal['prevu'])

    def test_markdown(self):
        texte = rapport.markdown_jour(self.jour)
        self.assertIn('Matchs joués la veille dans nos 16 championnats : **3**, dont **2**', texte)
        self.assertIn('Précision : **1 / 2** (50 %).', texte)
        self.assertIn('Résultats surprenants', texte)
        self.assertIn('pas de prévision', texte)

    def test_sans_matchs_veille(self):
        jour = rapport.jour_de_la_veille([], [], [], {}, {}, dt.date(2026, 11, 4))
        self.assertEqual((jour['joues'], jour['avec_prevision'], jour['precision']), (0, 0, None))


class GrillesResume(unittest.TestCase):
    def test_match_joue_marque_bon_pronostic(self):
        entree = {'format': 8, 'numero': 154, 'n': 1, 'ligue': 'F1', 'domicile': 'Lens', 'exterieur': 'Lille',
                  'cloture': '2026-11-03T20:00:00+01:00', 'pronostic': '1',
                  'proba': {'1': 0.5, 'N': 0.25, '2': 0.25}, 'id': 'a'}
        idx = {('F1', 'Lens', 'Lille'): [(dt.date(2026, 11, 3), 'H', 2, 1)]}
        resume = rapport.grilles_resume([entree], idx, {'F1': 'France L1'})
        self.assertEqual(resume['precision'], {'ok': 1, 'n': 1})
        match = resume['liste'][0]['matchs'][0]
        self.assertEqual((match['verdict'], match['score'], match['championnat']), ('ok', '2 – 1', 'France L1'))

    def test_match_a_venir_et_hors_suivi(self):
        entrees = [{'format': 15, 'numero': 92, 'n': 1, 'ligue': 'F1', 'domicile': 'Paris SG', 'exterieur': 'Troyes',
                    'cloture': '2026-11-07T20:40:00+01:00', 'pronostic': '1',
                    'proba': {'1': 0.83, 'N': 0.13, '2': 0.04}, 'id': 'b'},
                   {'format': 15, 'numero': 92, 'n': 2, 'domicile': 'Dinamo Zagreb', 'exterieur': 'Lens',
                    'cloture': '2026-11-07T20:40:00+01:00', 'non_prevu': 'équipe hors des 16 championnats suivis',
                    'id': 'c'}]
        resume = rapport.grilles_resume(entrees, {}, {})
        self.assertEqual(resume['precision'], {'ok': 0, 'n': 0})
        self.assertEqual(resume['a_venir'], 1)
        matchs = resume['liste'][0]['matchs']
        self.assertIsNone(matchs[0]['verdict'])
        self.assertIn('non_prevu', matchs[1])

    def test_grille_privee_absente_du_journal(self):
        self.assertIn(153, rapport.GRILLES_PRIVEES)


if __name__ == '__main__':
    unittest.main()
