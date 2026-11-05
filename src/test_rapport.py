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
    def test_championnat_football_data(self):
        rows = [{'league': 'F1', 'home': 'Lens', 'away': 'Lille', 'date': dt.date(2026, 11, 3), 'result': 'H',
                 'hg': 2, 'ag': 1}]
        r = rapport.resultat_match(entree(), rapport.index_resultats(rows), {})
        self.assertEqual((r['source'], r['issue'], r['score']), ('football-data', '1', '2 – 1'))

    def test_pronosoft_nom_canonique_et_fenetre(self):
        releves = [{'domicile': 'Bod/Glimt', 'exterieur': 'Lille', 'score': '0-0', 'vu': '2026-11-04'}]
        idx = rapport.index_pronosoft(releves)
        e = entree(domicile='Bodø/Glimt', ligue=None)
        del e['ligue']
        r = rapport.resultat_match(e, {}, idx)
        self.assertEqual((r['source'], r['issue'], r['score']), ('pronosoft', 'N', '0 – 0'))
        hors = rapport.index_pronosoft([dict(releves[0], vu='2026-12-30')])
        self.assertIsNone(rapport.resultat_match(e, {}, hors))
        avant = rapport.index_pronosoft([dict(releves[0], vu='2026-11-01')])
        self.assertIsNone(rapport.resultat_match(e, {}, avant))


class Journal(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = rapport.JOURNAL_GRILLES
        rapport.JOURNAL_GRILLES = pathlib.Path(self.dossier.name) / 'grilles.jsonl'
        self.donnees = donnees_test()
        self.grilles = [{'format': 7, 'numero': 91, 'cloture': CLOTURE, 'matchs': [
            {'domicile': 'Arsenal', 'exterieur': 'Chelsea'},
            {'domicile': 'Bodø/Glimt', 'exterieur': 'Girona'},
            {'domicile': 'Inconnu FC', 'exterieur': 'Girona'}]}]

    def tearDown(self):
        rapport.JOURNAL_GRILLES = self.ancien
        self.dossier.cleanup()

    def test_pronostic_enregistre_une_fois(self):
        nouvelles = rapport.enregistrer_grilles(self.donnees, self.grilles, 'maintenant', dt.date(2026, 11, 2))
        self.assertEqual(len(nouvelles), 3)
        self.assertEqual(nouvelles[0]['ligue'], 'E0')
        self.assertEqual(nouvelles[1]['methode'], 'hypothese')
        self.assertIn('non_prevu', nouvelles[2])
        # Deuxième passage le même jour : seul le match resté sans pronostic est recalculé.
        seconde = rapport.enregistrer_grilles(self.donnees, self.grilles, 'maintenant', dt.date(2026, 11, 2))
        self.assertEqual([e['domicile'] for e in seconde], ['Inconnu FC'])

    def test_ancienne_methode_remplacee_si_grille_ouverte(self):
        import json
        ancienne = {'id': '2026-11-03|Arsenal|Chelsea', 'enregistree_le': 'avant',
                    'proba': {'1': 0.5, 'N': 0.3, '2': 0.2}, 'pronostic': '1'}
        rapport.JOURNAL_GRILLES.write_text(json.dumps(ancienne) + '\n', encoding='utf-8')
        fermee = rapport.enregistrer_grilles(self.donnees, [self.grilles[0]], 'maintenant', dt.date(2026, 11, 5))
        self.assertNotIn('2026-11-03|Arsenal|Chelsea', [e['id'] for e in fermee])  # grille close : rien n’est refait
        ouverte = rapport.enregistrer_grilles(self.donnees, [self.grilles[0]], 'maintenant', dt.date(2026, 11, 2))
        arsenal = next(e for e in ouverte if e['domicile'] == 'Arsenal')
        self.assertEqual((arsenal['version_methode'], arsenal['remplace']), (rapport.VERSION_METHODE, 'avant'))
        derniere = rapport.derniere_entree(rapport.charger_jsonl(rapport.JOURNAL_GRILLES))
        self.assertEqual(derniere['2026-11-03|Arsenal|Chelsea']['version_methode'], rapport.VERSION_METHODE)

    def test_sans_pronostic_refait_tant_que_la_grille_est_ouverte(self):
        rapport.enregistrer_grilles(self.donnees, self.grilles, 'maintenant', dt.date(2026, 11, 2))
        apres_cloture = rapport.enregistrer_grilles(self.donnees, self.grilles, 'maintenant', dt.date(2026, 11, 5))
        self.assertEqual(apres_cloture, [])  # grille close : aucune prévision n’est ajoutée après coup

    def test_derniere_entree_remplace_la_precedente(self):
        entrees = [{'id': 'a', 'v': 1}, {'id': 'a', 'v': 2}]
        self.assertEqual(rapport.derniere_entree(entrees)['a']['v'], 2)


class Bilan(unittest.TestCase):
    def test_causes_et_tranches(self):
        donnees = [
            (entree(), {'issue': '1', 'score': '2 – 1', 'source': 'football-data'}),
            (entree(), {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'}),
            (entree(malus={'domicile': -13, 'exterieur': 0}), {'issue': '2', 'score': '0 – 1', 'source': 'pronosoft'}),
            ({'non_prevu': 'équipe hors des 16 championnats suivis'}, None),
        ]
        analyses = [{'e': e, 'res': r, 'a': rapport.analyser(e, r)} for e, r in donnees]
        b = rapport.bilan(analyses)
        self.assertEqual((b['resolus'], b['ok'], b['ko'], b['sans_pronostic']), (3, 1, 2, 1))
        self.assertEqual(b['precision'], round(1 / 3, 3))
        self.assertEqual({c['code']: c['n'] for c in b['causes']}, {'surprise': 2})
        self.assertEqual({c['code']: c['n'] for c in b['facteurs']}, {'absences': 1})
        self.assertEqual(b['tranches'][2], {'libelle': 'pronostic à 60 % et plus', 'n': 3, 'ok': 1})

    def test_grilles_recentes_et_completes(self):
        ancienne = entree(id='old', numero=90, cloture='2026-10-20T20:55:00+01:00')
        recente = entree(id='new', numero=91, n=1, domicile='Lens', exterieur='Lille')
        seconde = entree(id='new2', numero=91, n=2, domicile='Paris SG', exterieur='Troyes', ligue='F1')
        analyses = [{'e': e, 'res': None, 'a': rapport.analyser(e, None)} for e in (ancienne, recente, seconde)]
        grilles = rapport.grilles_resumees(analyses, {'F1': 'France L1'})
        self.assertEqual([g['numero'] for g in grilles], [91, 90])
        self.assertFalse(grilles[0]['complete'])
        self.assertEqual([m['n'] for m in grilles[0]['matchs']], [1, 2])
        self.assertEqual(grilles[0]['matchs'][0]['championnat'], 'France L1')


class Releves(unittest.TestCase):
    def test_grilles_non_suivies_seulement(self):
        matchs = [
            {'domicile': 'Aston Villa', 'exterieur': 'Fulham', 'score': '1-1', 'vu': '2026-11-04', 'grilles': ['Loto Foot 15 n90']},
            {'domicile': 'Lens', 'exterieur': 'Lille', 'score': '2-0', 'vu': '2026-11-04', 'grilles': ['Loto Foot 15 n91']},
            {'domicile': 'Ancien', 'exterieur': 'Match', 'score': '0-1', 'vu': '2026-10-01', 'grilles': ['Loto Foot 15 n80']},
            {'domicile': 'Perso', 'exterieur': 'Grille', 'score': '0-0', 'vu': '2026-11-04', 'grilles': ['Loto Foot 7 n153']},
        ]
        r = rapport.releves_pronosoft(matchs, {(15, 91)}, dt.date(2026, 11, 5))
        self.assertEqual([(g['format'], g['numero']) for g in r], [(15, 90)])
        self.assertEqual(r[0]['releve'], '2026-11-04')
        self.assertEqual(r[0]['matchs'], [{'domicile': 'Aston Villa', 'exterieur': 'Fulham', 'score': '1 – 1', 'issue': 'N'}])


if __name__ == '__main__':
    unittest.main()
