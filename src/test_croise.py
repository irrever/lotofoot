"""Contrôles du calcul entre championnats : constantes identiques à l’application, formules, noms d’équipes."""
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import croise  # noqa: E402

APP = pathlib.Path(__file__).resolve().parent.parent / 'standalone' / 'app.html'
VARS = ['dW', 'dD', 'dL', 'eW', 'eD', 'eL', 'forme', 'gf', 'ga', 'rest', 'load', 'cadF', 'cadA', 'cor', 'car']
MODELE = {'ordonnee': {'H': 0.1, 'D': 0.0, 'A': -0.1}, 'coef': {c: [0.01] * 25 for c in 'HDA'},
          'moyenne': [0.0] * 25, 'echelle': [1.0] * 25}


def vecteur(elo, **valeurs):
    v = {k: 0.5 for k in VARS}
    v.update(valeurs)
    v['elo'] = elo
    return v


def equipe(nom, ligue, elo, malus=0, **valeurs):
    t = {'equipe': nom, 'ligue': ligue, 'vec': vecteur(elo, **valeurs)}
    if malus:
        t['absences'] = {'malus': malus}
    return t


def donnees_test():
    return {
        'equipes': [equipe('Arsenal', 'E0', 1800, dW=0.6), equipe('Chelsea', 'E0', 1700, dW=0.8),
                    equipe('Girona', 'SP1', 1650, dW=0.2), equipe('Betis', 'SP1', 1600, dW=0.4)],
        'stats': {'notes': [{'code': 'E0', 'note': 100.0}, {'code': 'SP1', 'note': 80.0}],
                  'points_elo_par_note': 4},
        'modele': MODELE,
    }


class Parite(unittest.TestCase):
    """Les constantes de src/croise.py sont celles de l’application (standalone/app.html)."""

    @classmethod
    def setUpClass(cls):
        cls.texte = APP.read_text(encoding='utf-8')

    def test_championnats_hypothese(self):
        bloc = re.search(r'var CHAMPIONNATS_HYPOTHESE = \{(.*?)\n  \};', self.texte, re.S).group(1)
        trouves = {c: {'pays': p, 'note': float(n)}
                   for c, p, n in re.findall(r"(\w+): \{ pays: '([^']+)', note: ([\d.]+) \}", bloc)}
        attendus = {c: {'pays': v['pays'], 'note': float(v['note'])}
                    for c, v in croise.CHAMPIONNATS_HYPOTHESE.items()}
        self.assertEqual(trouves, attendus)

    def test_clubs_hypothese(self):
        bloc = re.search(r'var CLUBS_HYPOTHESE = \{(.*?)\n  \};', self.texte, re.S).group(1)
        trouves = {nom: {'ligue': lg, 'elo': int(elo), 'niveau': niv, 'motif': motif}
                   for nom, lg, elo, niv, motif in re.findall(
                       r"'([^']+)': \{ ligue: '(\w+)', elo: (\d+), niveau: '(\w+)', motif: '([^']*)' \}", bloc)}
        self.assertEqual(trouves, croise.CLUBS_HYPOTHESE)

    def test_alias_equipes(self):
        bloc = re.search(r'var ALIAS = \{(.*?)\n  \};', self.texte, re.S).group(1)
        self.assertEqual(dict(re.findall(r"'([^']+)': '([^']+)'", bloc)), croise.ALIAS_EQUIPES)

    def test_variables_du_niveau_et_des_moyennes(self):
        self.assertIn('var NIVEAU_VARS = [%s];' % ', '.join("'%s'" % v for v in croise.NIVEAU_VARS), self.texte)
        self.assertIn('[%s]' % ', '.join("'%s'" % v for v in croise.VARS_MOYENNE), self.texte)


class Noms(unittest.TestCase):
    def test_cle_sans_accents_ni_points(self):
        self.assertEqual(croise.cle('Atl. Madrid'), 'atl madrid')
        self.assertEqual(croise.cle('  Bodø/Glimt '), 'bodø/glimt')

    def test_noms_pronosoft(self):
        self.assertEqual(croise.canon_pronosoft('Bod/Glimt'), 'Bodø/Glimt')
        self.assertEqual(croise.canon_pronosoft('Atl. Madrid'), 'Ath Madrid')
        self.assertEqual(croise.canon_pronosoft('Lille'), 'Lille')
        self.assertEqual(croise.canon_pronosoft('FC Barcelone'), 'Barcelona')
        self.assertEqual(croise.canon_pronosoft('Inter Milan'), 'Inter')
        self.assertEqual(croise.canon_pronosoft('AS Rome'), 'Roma')
        self.assertEqual(croise.canon_pronosoft('AEK Athnes'), 'AEK')
        self.assertEqual(croise.canon_pronosoft('Betis Sville'), 'Betis')
        self.assertEqual(croise.canon_pronosoft('Como 1907'), 'Como')
        self.assertEqual(croise.canon_pronosoft('Club Bruges'), 'Club Brugge')
        self.assertEqual(croise.canon_pronosoft('FC Porto'), 'Porto')
        self.assertEqual(croise.canon_pronosoft('Naples'), 'Napoli')
        self.assertEqual(croise.canon_pronosoft('Parme'), 'Parma')
        self.assertEqual(croise.canon_pronosoft('La Corogne'), 'La Coruna')

    def test_trouver_equipe(self):
        d = donnees_test()
        self.assertEqual(croise.trouver_equipe(d, 'PSG'), None)  # pas dans ce jeu de données
        d['equipes'].append(equipe('Paris SG', 'F1', 1700))
        self.assertEqual(croise.trouver_equipe(d, 'PSG')['equipe'], 'Paris SG')
        self.assertIsNone(croise.trouver_equipe(d, 'Équipe inconnue'))

    def test_clubs_estimes_des_grilles_12(self):
        d = donnees_test()
        self.assertEqual(croise.trouver_equipe(d, 'Ferencvaros')['equipe'], 'Ferencváros')
        self.assertEqual(croise.trouver_equipe(d, 'Salzbourg')['ligue'], 'AT1')
        self.assertEqual(croise.trouver_equipe(d, 'Sparta Prague')['vec']['elo'], 1666)
        self.assertAlmostEqual(croise.moyenne_elo_ligue(d, 'HU1'), 1512 + 0.96 * 37.5, places=9)


class Calculs(unittest.TestCase):
    def test_meme_championnat_sans_ajustement(self):
        d = donnees_test()
        r = croise.calcul_match(d, d['equipes'][0], d['equipes'][1])
        self.assertEqual((r['methode'], r['gap'], r['croise']), ('meme_championnat', 0.0, False))
        self.assertEqual(r['ecart'], 100.0)
        self.assertAlmostEqual(sum(r['p'].values()), 1.0, places=9)

    def test_niveau_ajuste_ramene_au_plus_fort(self):
        d = donnees_test()
        girona = d['equipes'][2]
        ajuste = croise.niveau_ajuste(girona['vec'], 'SP1', 'E0', d)
        # moyenne E0 de dW = 0,7 ; moyenne SP1 = 0,3 ; ratio 80 / 100
        self.assertAlmostEqual(ajuste['dW'], 0.7 + 0.8 * (0.2 - 0.3), places=9)
        self.assertEqual(croise.niveau_ajuste(girona['vec'], 'E0', 'SP1', d), girona['vec'])

    def test_ecart_de_championnat(self):
        d = donnees_test()
        r = croise.calcul_match(d, d['equipes'][2], d['equipes'][0])  # Girona (SP1) reçoit Arsenal (E0)
        self.assertEqual((r['methode'], r['gap'], r['croise']), ('inter_championnats', -80.0, True))
        # position dans le championnat : Girona 1650 contre une moyenne SP1 de 1625, Arsenal 1800 contre 1750
        self.assertEqual(r['ecart'], round((1650 - 1625) - (1800 - 1750) - 80, 1))

    def test_moyenne_elo_championnat_hypothese(self):
        self.assertAlmostEqual(croise.moyenne_elo_ligue(donnees_test(), 'NO1'), 1512 + 0.96 * 47.5, places=9)
        self.assertAlmostEqual(croise.moyenne_elo_ligue(donnees_test(), 'SP1'), 1625.0, places=9)

    def test_absences_baissent_lelo(self):
        d = donnees_test()
        d['equipes'][0]['absences'] = {'malus': -13}
        r = croise.calcul_match(d, d['equipes'][0], d['equipes'][1])
        self.assertEqual(r['ecart'], 100.0 - 13)
        self.assertEqual(r['malus'], {'domicile': -13, 'exterieur': 0})

    def test_club_hypothese(self):
        d = donnees_test()
        bodo = croise.trouver_equipe(d, 'Bodø/Glimt')
        self.assertEqual((bodo['ligue'], bodo['vec']['elo'], bodo['hypothese']), ('NO1', 1782, True))
        self.assertAlmostEqual(bodo['vec']['dW'], (0.6 + 0.8 + 0.2 + 0.4) / 4, places=9)  # moyenne des équipes
        r = croise.calcul_match(d, bodo, d['equipes'][0])
        self.assertEqual((r['methode'], r['hypothese'], r['nh']), ('hypothese', ['Bodø/Glimt'], 47.5))

    def test_probabilites_du_match_normalisees(self):
        d = donnees_test()
        r = croise.calcul_match(d, d['equipes'][2], d['equipes'][1])
        self.assertAlmostEqual(sum(r['p'].values()), 1.0, places=9)


def donnees_contrib():
    """Données de test avec des coefficients propres à chaque issue : avec MODELE (mêmes coefficients pour H, D et A),
    aucune variable ne change les probabilités, donc aucun effet à mesurer."""
    d = donnees_test()
    d['modele'] = {'ordonnee': {'H': 0.0, 'D': 0.0, 'A': 0.0}, 'coef': {'H': [0.02] * 25, 'D': [0.0] * 25, 'A': [-0.02] * 25},
                   'moyenne': [0.0] * 25, 'echelle': [1.0] * 25}
    return d


class Contributions(unittest.TestCase):
    def test_tous_les_facteurs_et_les_25_variables(self):
        d = donnees_contrib()
        r = croise.calcul_match(d, d['equipes'][0], d['equipes'][1])
        codes = {'niveau', 'championnat', 'absences'} | {code for code, _ in croise.GROUPES_VARIABLES}
        self.assertEqual(set(r['contributions']), codes)
        self.assertEqual(len(codes), 23)
        # chaque variable du modèle (sauf l’écart Elo, découpé en trois facteurs) appartient à un seul groupe
        self.assertEqual(sorted(j for _, indices in croise.GROUPES_VARIABLES for j in indices), list(range(1, 25)))

    def test_proba_identique_a_la_decomposition(self):
        d = donnees_contrib()
        h, a = d['equipes'][0], d['equipes'][1]
        r = croise.calcul_match(d, h, a)
        x = croise.vecteur_match(croise.avec_absences(h), croise.avec_absences(a), r['ecart'])
        self.assertEqual(croise.probas_x(x, d['modele']), r['p'])

    def test_facteur_a_sa_moyenne_sans_effet(self):
        d = donnees_contrib()
        d['equipes'][0]['vec']['forme'] = 0.0  # moyenne du modèle de test : 0
        r = croise.calcul_match(d, d['equipes'][0], d['equipes'][1])
        self.assertEqual(r['contributions']['forme_dom'], {'H': 0.0, 'D': 0.0, 'A': 0.0})

    def test_niveau_et_absences_dans_le_bon_sens(self):
        d = donnees_contrib()
        d['equipes'][0]['absences'] = {'malus': -13}  # Arsenal (1800) reçoit Chelsea (1700) : écart 100 − 13
        r = croise.calcul_match(d, d['equipes'][0], d['equipes'][1])
        self.assertGreater(r['contributions']['niveau']['H'], 0)
        self.assertLess(r['contributions']['niveau']['A'], 0)
        self.assertLess(r['contributions']['absences']['H'], 0)  # les absences d’Arsenal lui retirent de la probabilité
        self.assertGreater(r['contributions']['absences']['A'], 0)

    def test_ecart_de_championnat_separe_du_niveau(self):
        d = donnees_contrib()
        r = croise.calcul_match(d, d['equipes'][2], d['equipes'][0])  # Girona (SP1) reçoit Arsenal (E0) : écart −80
        self.assertLess(r['contributions']['championnat']['H'], 0)
        self.assertGreater(r['contributions']['championnat']['A'], 0)


if __name__ == '__main__':
    unittest.main()
