"""Contrôles du relevé du Quinté+ : analyse des pages, adresses de course, robots.txt, déroulement d’une journée."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import quinte  # noqa: E402

PRONOSTIC = ("Accueil › Quinté+ du jour Pronostic du Quinté+ du jeudi 5 novembre 2026 Prix D'avranches à Vincennes, "
             "départ 13:55. La sélection Turfin en 8 chevaux classés par leur note. Quinté+ R1C1 · Vincennes Prix "
             "D'avranches Attelé 2100 m jeudi 5 novembre 2026 13:55 départ")

COURSE = ("<p>Prochains départs</p> Prix D'avranches R1C1 · Vincennes · jeudi 5 novembre 2026 · 13:55. "
          "Réunion R1 Vincennes R2 Lignieres C1 C2 VI Prix D'avranches Vincennes | Attelé | 2100 m | 17 partants | "
          "Corde à gauche | 59 000 € d'allocation Quinté+ Multi Tiercé Quarté+ Couplé 2sur4 13:55 jeudi 5 novembre 2026 "
          '<tbody class="pt " data-vp="0" data-num="9" data-cote="3.5" data-note="0" data-courses="0"> <tr class="l"> '
          '<td><span class="ncas"><span class="num">9</span></span></td> <td class="nom"> '
          '<a href="/cheval/READY%20STAR">Ready Star</a> <span class="mus"></span></td></tr></tbody>'
          '<tbody class="pt " data-vp="0" data-num="2" data-cote="9.0" data-note="0" data-courses="0"> <tr class="l"> '
          '<td><span class="ncas"><span class="num">2</span></span></td> <td class="nom"> '
          '<a href="/cheval/X">Horatius D&#39;ela</a></td></tr></tbody>')

ARRIVEE = ("Arrivée du Quinté+ du jour 5 novembre à Vincennes : 9-6-15-1-5, rapports PMU · Turfin "
           "Arrivée officielle : 9 - 6 - 15 - 1 - 5 . L'arrivée officielle et les rapports PMU du Quinté+. "
           "Résultat du Quinté+ du jour — 05/11/2026 R1C1 · Vincennes · 13:55 · Attelé · 2100 m · Prix D'avranches "
           "Arrivée officielle 1 9 Ready Star 3,5 2 6 Humanity Pellini 14,0 3 15 Competivo 11,0 4 1 Kotkie 37,0 "
           "5 5 Every Time Winner 4,3 Ce qu'on annonçait à 10h, avant le départ → Rapports officiels Quinté+ "
           "9 6 15 1 5 3439,70 € 9 6 15 1 5 45,60 € 6 15 1 5 2,10 € 9 6 15 1,80 € Quarté+ 9 6 15 1 739,80 € "
           "9 6 15 1 69,70 € 9 6 15 6,10 € Tiercé 9 6 15 98,40 € 9 6 15 17,20 € Dividendes officiels PMU")

ARRIVEE_PAS_ENCORE = "Arrivée du Quinté+ du jour 5 novembre à Vincennes : résultat dès 13:55, rapports PMU · Turfin"


class Analyses(unittest.TestCase):
    def test_programme_de_la_journee(self):
        p = quinte.parse_programme(PRONOSTIC)
        self.assertEqual(p, {'date': '2026-11-05', 'reunion': 1, 'numero': 1, 'nom': "Prix D'avranches",
                             'hippodrome': 'Vincennes', 'discipline': 'Attelé', 'distance_m': 2100, 'heure': '13:55'})
        self.assertEqual(quinte.url_course(p), 'https://turfin.fr/course/2026-11-05/r1c1-vincennes-prix-d-avranches')

    def test_adresse_de_course(self):
        self.assertEqual(quinte.slug('Grand National Du Trot'), 'grand-national-du-trot')
        self.assertEqual(quinte.slug('Pont De Vivaux'), 'pont-de-vivaux')

    def test_course_partants_corde_et_allocation(self):
        c = quinte.parse_course(COURSE)
        self.assertEqual((c['partants'], c['corde'], c['allocation_eur'], c['distance_m']), (17, 'gauche', 59000, 2100))
        self.assertEqual(c['liste'], [{'numero': 9, 'nom': 'Ready Star'}, {'numero': 2, 'nom': "Horatius D'ela"}])
        self.assertNotIn('cote', json.dumps(c))  # ni cotes ni notes des partants n’entrent dans les données

    def test_arrivee_ordre_et_rapports(self):
        a = quinte.parse_arrivee(ARRIVEE)
        self.assertEqual(a['ordre'], [9, 6, 15, 1, 5])
        self.assertEqual([x['nom'] for x in a['arrivants']][:2], ['Ready Star', 'Humanity Pellini'])
        quinte_ = [(r['type'], r['combinaison'], r['rapport']) for r in a['rapports'] if r['pari'] == 'Quinté+']
        self.assertEqual(quinte_[:2], [('ordre', [9, 6, 15, 1, 5], 3439.7), ('désordre', [9, 6, 15, 1, 5], 45.6)])
        self.assertIn(('bonus4', [6, 15, 1, 5], 2.1), quinte_)
        self.assertIn(('bonus3', [9, 6, 15], 1.8), [(r['type'], r['combinaison'], r['rapport']) for r in a['rapports']
                                                     if r['pari'] == 'Quinté+'])

    def test_arrivee_pas_encore_publiee(self):
        self.assertIsNone(quinte.parse_arrivee(ARRIVEE_PAS_ENCORE))

    def test_robots_txt(self):
        robots = 'User-agent: *\nDisallow: /api/\nAllow: /arrivee-du-quinte\n'
        self.assertTrue(quinte.autorise_robots(robots, 'https://turfin.fr/arrivee-du-quinte/2026-11-04'))
        self.assertFalse(quinte.autorise_robots(robots, 'https://turfin.fr/api/widget/quinte'))


class Journee(unittest.TestCase):
    """Déroulement d’une journée avec des pages factices : le programme, puis l’arrivée une heure après le départ."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = pathlib.Path(self.dossier.name) / 'jours.json'
        self.appels = []
        self.arrivee = None  # texte renvoyé pour la page d’arrivée (None : pas encore publiée)

    def tearDown(self):
        self.dossier.cleanup()

    def telecharger(self, url):
        self.appels.append(url)
        if url == quinte.URL_PRONOSTIC:
            return PRONOSTIC
        if url.startswith(quinte.TURFIN + '/course/'):
            return COURSE
        if url.startswith(quinte.URL_ARRIVEE):
            return self.arrivee if self.arrivee else ARRIVEE_PAS_ENCORE
        raise AssertionError('adresse inattendue : ' + url)

    def maj(self, heure_utc):
        maintenant = dt.datetime.fromisoformat('2026-11-05T' + heure_utc + '+00:00')
        return quinte.maj(maintenant=maintenant, jour=dt.date(2026, 11, 5), telecharger=self.telecharger,
                          chemin=self.chemin)

    def donnees(self):
        return json.loads(self.chemin.read_text(encoding='utf-8'))['2026-11-05']

    def test_programme_releve_aux_heures_prevues_seulement(self):
        self.maj('13:00')  # hors des heures prévues pour le programme
        self.assertEqual(self.appels, [])
        self.maj('08:05')
        self.assertEqual(self.donnees()['course']['heure'], '13:55')
        self.assertEqual(self.donnees()['course']['depart_utc'], '2026-11-05T12:55+00:00')

    def test_arrivee_une_heure_apres_le_depart(self):
        self.maj('08:05')
        self.appels.clear()
        self.maj('13:30')  # 35 minutes après le départ : pas encore
        self.assertEqual(self.appels, [])
        resume = self.maj('14:00')  # une heure après le départ, la page n’est pas encore à jour
        self.assertIn('arrivée 2026-11-05 : pas encore publiée', resume['messages'])
        self.assertNotIn('arrivee', self.donnees())
        self.arrivee = ARRIVEE
        self.maj('14:10')
        arrivee = self.donnees()['arrivee']
        self.assertEqual((arrivee['ordre'], len(arrivee['rapports'])), ([9, 6, 15, 1, 5], 9))  # 4 Quinté+, 3 Quarté+, 2 Tiercé
        self.assertEqual(self.appels[-1], quinte.URL_ARRIVEE)

    def test_arrivee_non_relancee_une_fois_publiee(self):
        self.maj('08:05')
        self.arrivee = ARRIVEE
        self.maj('14:10')
        self.appels.clear()
        resume = self.maj('14:20')
        self.assertEqual(self.appels, [])
        self.assertFalse(resume['modifie'])

    def test_course_introuvable_apres_trois_heures(self):
        self.maj('08:05')
        self.maj('18:00')  # plus de trois heures après l’heure prévue pour l’arrivée
        self.assertEqual(self.donnees()['arrivee_etat'], 'introuvable')

    def test_fichier_relu_et_ecrit_seulement_si_changement(self):
        self.maj('08:05')
        self.arrivee = ARRIVEE
        self.maj('14:10')
        self.assertEqual(quinte.charger(self.chemin)['2026-11-05']['arrivee']['ordre'], [9, 6, 15, 1, 5])
        date_ecriture = self.chemin.stat().st_mtime_ns
        self.maj('14:20')
        self.assertEqual(self.chemin.stat().st_mtime_ns, date_ecriture)


if __name__ == '__main__':
    unittest.main()
