"""Contrôles des résultats de grilles (pronostic, verdict, raison, bilan), avec des données fictives."""
import datetime as dt
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import croise  # noqa: E402
import rapport  # noqa: E402
from test_croise import donnees_test  # noqa: E402

CLOTURE = '2026-11-03T20:55:00+01:00'


def entree(**champs):
    base = {'id': 'x', 'n': 1, 'format': 15, 'numero': 91, 'domicile': 'Lens', 'exterieur': 'Lille',
            'cloture': CLOTURE, 'date': '2026-11-03', 'pronostic': '1',
            'proba': {'1': 0.6, 'N': 0.25, '2': 0.15}, 'malus': {'domicile': 0, 'exterieur': 0}, 'ligue': 'F1'}
    base.update(champs)
    return base


class Calculs(unittest.TestCase):
    def test_probabilites_normalisees(self):
        h = {'vec': {k: 0.5 for k in ['dW', 'dD', 'dL', 'forme', 'gf', 'ga', 'rest', 'load', 'cadF', 'cadA', 'cor', 'car',
                                      'eW', 'eD', 'eL']}}
        a = {'vec': dict(h['vec'])}
        p = croise.proba_match(h, a, {'ordonnee': {'H': 0.1, 'D': 0.0, 'A': -0.1},
                                      'coef': {c: [0.01] * 25 for c in 'HDA'}, 'moyenne': [0.0] * 25,
                                      'echelle': [1.0] * 25}, 100)
        self.assertAlmostEqual(sum(p.values()), 1.0, places=9)
        self.assertGreater(p['H'], p['A'])

    def test_date_francaise(self):
        self.assertEqual(rapport.date_fr(dt.date(2026, 11, 3)), '3 novembre 2026')
        self.assertEqual(rapport.date_fr(dt.date(2026, 11, 1)), '1er novembre 2026')


class Explications(unittest.TestCase):
    def test_bon_pronostic_favori(self):
        a = rapport.analyser(entree(), {'issue': '1', 'score': '2 – 1', 'source': 'football-data'})
        self.assertEqual(a['statut'], 'ok')
        self.assertIn('Lens était favori à 60 %', a['explication'])
        self.assertIsNone(a['cause'])

    def test_favori_battu(self):
        a = rapport.analyser(entree(), {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'})
        self.assertEqual((a['statut'], a['cause']), ('ko', 'surprise'))
        self.assertIn('Lens était favori à 60 %', a['explication'])

    def test_match_nul_non_anticipe(self):
        e = entree(pronostic='1', proba={'1': 0.4, 'N': 0.3, '2': 0.3})
        a = rapport.analyser(e, {'issue': 'N', 'score': '1 – 1', 'source': 'pronosoft'})
        self.assertEqual((a['statut'], a['cause']), ('ko', 'nul'))

    def test_absences_du_favori(self):
        e = entree(malus={'domicile': -13, 'exterieur': 0})
        a = rapport.analyser(e, {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'})
        self.assertEqual(a['cause'], 'surprise')
        self.assertEqual(a['facteurs'], ['absences'])
        self.assertIn('13 points Elo', a['explication'])

    def test_club_hors_championnats(self):
        e = entree(hypothese=['Bodø/Glimt'], ligue=None)
        del e['ligue']
        a = rapport.analyser(e, {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'})
        self.assertEqual(a['cause'], 'surprise')
        self.assertEqual(a['facteurs'], ['hypothese'])

    def test_match_serre(self):
        e = entree(pronostic='1', proba={'1': 0.42, 'N': 0.3, '2': 0.28})
        a = rapport.analyser(e, {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'})
        self.assertEqual((a['statut'], a['cause']), ('ko', 'serre'))

    def test_sans_pronostic_et_en_attente(self):
        sans = rapport.analyser({'non_prevu': 'équipe hors des 16 championnats suivis'}, None)
        self.assertEqual(sans['statut'], 'sans_pronostic')
        self.assertIn('Pas de pronostic', sans['explication'])
        self.assertEqual(rapport.analyser(entree(), None)['statut'], 'attente')


class Resultats(unittest.TestCase):
    def test_resultat_par_numero_de_grille_et_position(self):
        grilles = {'7-138': {'libelle': 'Loto Foot 7 n138', 'maj': '2026-11-06', 'matchs': [
            {'domicile': 'Leverkusen', 'exterieur': 'Marseille', 'score': '0-1', 'issue': '2'},
            {'domicile': 'Juventus Turin', 'exterieur': 'Lille', 'score': '1-2', 'issue': '2'}]}}
        e = {'format': 7, 'numero': 138, 'n': 2, 'cloture': '2026-11-05T20:55:00+01:00',
             'domicile': 'Juventus', 'exterieur': 'Lille'}
        r = rapport.resultat_grille(e, grilles)
        self.assertEqual((r['source'], r['issue'], r['score']), ('pronosoft', '2', '1 – 2'))

    def test_sans_grille_ou_sans_score_pas_de_resultat(self):
        grilles = {'7-138': {'libelle': 'Loto Foot 7 n138', 'maj': '2026-11-06', 'matchs': [
            {'domicile': 'Leverkusen', 'exterieur': 'Marseille', 'score': None, 'issue': None}]}}
        e = {'format': 7, 'numero': 138, 'n': 1, 'cloture': '2026-11-05T20:55:00+01:00',
             'domicile': 'Leverkusen', 'exterieur': 'Marseille'}
        self.assertIsNone(rapport.resultat_grille(e, grilles))
        self.assertIsNone(rapport.resultat_grille(dict(e, numero=999), grilles))


if __name__ == '__main__':
    unittest.main()
