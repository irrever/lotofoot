"""Contrôles hors réseau du relevé des absences : lecture des pages, rapprochement des noms, malus.
Les noms de joueurs et de clubs ci-dessous sont fictifs (ou ceux des clubs, pour le rapprochement)."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import footactu as fa  # noqa: E402

BLESSURES = '''<html><body><table><tbody>
<tr class="border-t border-gray-100 hover:bg-gray-50 align-top">
  <td class="px-4 py-3"><div class="flex items-center gap-2"><img class="w-6 h-6 object-contain">
    <a class="font-semibold text-gray-900 hover:text-[#9f1239]" href="/club/lens">RC Lens</a></div></td>
  <td class="px-4 py-3 text-center"><span class="inline-flex items-center justify-center w-7">2</span></td>
  <td class="px-4 py-3 text-center"><span class="text-gray-300">0</span></td>
  <td class="px-4 py-3"><div class="flex flex-wrap gap-1.5">
    <span class="inline-flex items-center gap-1 text-xs">A. Exemple<span class="opacity-60">Blessure musculaire</span></span>
    <span class="inline-flex items-center gap-1 text-xs">T. Essai<span class="opacity-60">Suspension</span></span>
  </div></td>
</tr>
<tr class="border-t border-gray-100 hover:bg-gray-50 align-top">
  <td class="px-4 py-3"><div class="flex items-center gap-2"><img class="w-6 h-6 object-contain">
    <a class="font-semibold text-gray-900" href="/club/havre">Le Havre Athletic Club</a></div></td>
  <td class="px-4 py-3"><div class="flex flex-wrap gap-1.5">
    <span class="inline-flex items-center gap-1 text-xs">J. Modele<span class="opacity-60">Blessure cheville</span></span>
  </div></td>
</tr>
</tbody></table>
<script>var ligne = "<tr class='border-t'><td>Faux club</td></tr>";</script></body></html>'''

CLASSEMENT = '''<html><body><table>
<thead><tr class="bg-gray-50 text-gray-400 text-xs font-bold">
  <th class="px-4 py-3 text-left w-10">Rang</th><th class="px-4 py-3 text-left">Joueur</th></tr></thead>
<tbody>
<tr class="border-t border-gray-100 hover:bg-[#fff1f2]/30 transition-colors">
  <td class="px-4 py-3 font-bold text-[#9f1239]">1</td>
  <td class="px-4 py-3 font-semibold text-gray-900">Alassane Exemple</td>
  <td class="px-4 py-3"><a class="flex items-center gap-2 hover:text-[#9f1239]"><img class="w-5 h-5">
    <span class="text-sm font-medium">RC Lens</span></a></td>
  <td class="px-4 py-3 text-center"><span class="font-extrabold text-base text-[#9f1239]">12</span></td>
  <td class="px-4 py-3 text-center text-gray-500">14</td>
</tr>
<tr class="border-t border-gray-100 hover:bg-[#fff1f2]/30 transition-colors">
  <td class="px-4 py-3 font-bold text-[#9f1239]">2</td>
  <td class="px-4 py-3 font-semibold text-gray-900">Bruno Essai</td>
  <td class="px-4 py-3"><a class="flex items-center gap-2"><img class="w-5 h-5">
    <span class="text-sm font-medium">Lille OSC</span></a></td>
  <td class="px-4 py-3 text-center"><span class="font-extrabold text-base">9</span></td>
  <td class="px-4 py-3 text-center text-gray-500">13</td>
</tr>
</tbody></table></body></html>'''

NOMS_LIGUE = ['Lens', 'Lyon', 'Paris SG', 'Paris FC', 'Lille', 'Nice', 'Troyes', 'Brest', 'Le Havre', 'Marseille',
              'Toulouse', 'Angers', 'Auxerre']


class LecturePages(unittest.TestCase):
    def test_blessures_clubs_et_joueurs(self):
        lignes = fa.lire_blessures(BLESSURES)
        self.assertEqual([c for c, _ in lignes], ['RC Lens', 'Le Havre Athletic Club'])
        self.assertEqual([len(j) for _, j in lignes], [2, 1])
        self.assertEqual(lignes[0][1], [('exemple', 'a'), ('essai', 't')])

    def test_script_ignore(self):
        self.assertNotIn('Faux club', [c for c, _ in fa.lire_blessures(BLESSURES)])

    def test_classement(self):
        self.assertEqual(fa.lire_classement(CLASSEMENT),
                         [('Alassane Exemple', 'RC Lens', 12), ('Bruno Essai', 'Lille OSC', 9)])


class Joueurs(unittest.TestCase):
    def test_initiale_et_nom_complet(self):
        self.assertTrue(fa.meme_joueur(fa.cle_joueur('A. Exemple'), fa.cle_joueur('Alassane Exemple')))
        self.assertFalse(fa.meme_joueur(fa.cle_joueur('A. Exemple'), fa.cle_joueur('B. Exemple')))
        self.assertTrue(fa.meme_joueur(fa.cle_joueur('K. Mbappé'), fa.cle_joueur('Kylian Mbappe')))
        self.assertIsNone(fa.cle_joueur(''))


class Rapprochement(unittest.TestCase):
    def test_alias_et_proches(self):
        cas = {'RC Lens': 'Lens', 'Olympique Lyonnais': 'Lyon', 'Paris Saint-Germain': 'Paris SG',
               'Paris FC': 'Paris FC', 'Estac': 'Troyes', 'OGC Nice': 'Nice', 'Lille OSC': 'Lille',
               'Olympique de Marseille': 'Marseille', 'Le Havre Athletic Club': 'Le Havre',
               'Toulouse Football Club': 'Toulouse', 'SCO Angers': 'Angers', 'AJ Auxerre': 'Auxerre',
               'Stade Brestois': 'Brest'}
        for club, attendu in cas.items():
            self.assertEqual(fa.rapprocher(club, NOMS_LIGUE), attendu, club)

    def test_inconnu(self):
        self.assertIsNone(fa.rapprocher('Club Inconnu Sans Rapport', NOMS_LIGUE))


class Malus(unittest.TestCase):
    def test_buteur_seul(self):
        r = fa.bilan_equipe([('exemple', 'a')], [('exemple', 'a')], [])
        self.assertEqual((r['absents'], r['buteur'], r['passeur'], r['malus']), (1, True, False, -10))

    def test_passeur_seul(self):
        r = fa.bilan_equipe([('essai', 'b')], [], [('essai', 'b')])
        self.assertEqual((r['buteur'], r['passeur'], r['malus']), (False, True, -5))

    def test_meme_joueur_buteur_et_passeur_compte_une_fois(self):
        r = fa.bilan_equipe([('exemple', 'a')], [('exemple', 'a')], [('exemple', 'a')])
        self.assertEqual((r['buteur'], r['passeur'], r['malus']), (True, False, -10))

    def test_autres_absents(self):
        r = fa.bilan_equipe([('x%d' % i, 'a') for i in range(3)], [], [])
        self.assertEqual(r['malus'], -6)

    def test_plafond_autres(self):
        r = fa.bilan_equipe([('x%d' % i, 'a') for i in range(8)], [], [])
        self.assertEqual(r['malus'], -10)

    def test_plafond_total(self):
        absents = [('exemple', 'a'), ('essai', 'b')] + [('x%d' % i, 'c') for i in range(8)]
        r = fa.bilan_equipe(absents, [('exemple', 'a')], [('essai', 'b')])
        self.assertEqual(r['malus'], -20)

    def test_meilleurs_egalites(self):
        self.assertEqual(fa.meilleurs([(('a', 'x'), 5), (('b', 'x'), 5), (('c', 'x'), 3)]),
                         [('a', 'x'), ('b', 'x')])
        self.assertEqual(fa.meilleurs([(('a', 'x'), 0)]), [])


class Fraicheur(unittest.TestCase):
    def test_releve_du_jour_et_veille_seulement(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = pathlib.Path(d) / 'du_jour.json'
            original = fa.DU_JOUR
            fa.DU_JOUR = chemin
            try:
                for ecart, attendu in ((0, True), (1, True), (2, False)):
                    jour = dt.date.today() - dt.timedelta(days=ecart)
                    chemin.write_text(json.dumps({'date': jour.isoformat(), 'championnats': {}}), encoding='utf-8')
                    self.assertEqual(fa.du_jour_frais() is not None, attendu, ecart)
            finally:
                fa.DU_JOUR = original

    def test_absences_par_equipe(self):
        releve = {'championnats': {'F1': {'Lens': {'absents': 3, 'buteur': True, 'passeur': False, 'malus': -12}}}}
        self.assertEqual(fa.absences_par_equipe(releve),
                         {('F1', 'Lens'): {'nombre': 3, 'buteur': True, 'passeur': False, 'malus': -12}})
        self.assertEqual(fa.absences_par_equipe(None), {})


if __name__ == '__main__':
    unittest.main()
