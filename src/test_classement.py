"""Contrôles du classement Elo : seules les équipes de la saison en cours sont classées dans leur championnat."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import teams  # noqa: E402
from features2 import equipes_de_la_saison  # noqa: E402


class Rang(unittest.TestCase):
    def test_anciennes_equipes_exclues_du_rang(self):
        R = {('F2', 'Dijon'): 1500.0, ('F2', 'Ancienne'): 1700.0, ('F2', 'Nouvelle'): 1600.0,
             ('E0', 'Arsenal'): 1800.0}
        actifs = {('F2', 'Dijon'), ('F2', 'Nouvelle')}
        self.assertEqual(teams.rang_elo(R, 'F2', 'Dijon', actifs), 2)
        self.assertEqual(teams.rang_elo(R, 'F2', 'Nouvelle', actifs), 1)
        self.assertIsNone(teams.rang_elo(R, 'F2', 'Ancienne', actifs))

    def test_rangs_restent_dans_la_taille_du_championnat(self):
        R = {('F2', 'Equipe%d' % i): 1500.0 + i for i in range(20)}
        R.update({('F2', 'Ancienne%d' % i): 1400.0 + i for i in range(4)})
        actifs = {('F2', 'Equipe%d' % i) for i in range(20)}
        rangs = sorted(teams.rang_elo(R, 'F2', 'Equipe%d' % i, actifs) for i in range(20))
        self.assertEqual(rangs, list(range(1, 21)))

    def test_saison_la_plus_recente(self):
        rows = [{'season': '2526', 'league': 'F2', 'home': 'A', 'away': 'B'},
                {'season': '2627', 'league': 'F2', 'home': 'C', 'away': 'D'}]
        self.assertEqual(equipes_de_la_saison(rows), {('F2', 'C'), ('F2', 'D')})


if __name__ == '__main__':
    unittest.main()
