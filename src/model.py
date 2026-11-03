"""Probabilités 1 / N / 2 à partir de l’écart de niveau entre deux équipes (logit ordonné).

Seules ces deux fonctions servent à la mise à jour quotidienne. Aucune cote n’est utilisée.
"""
import math


def sigmoid(z):
    if z >= 0:
        e = math.exp(-z); return 1.0 / (1.0 + e)
    e = math.exp(z); return e / (1.0 + e)


def probs_from_x(x, c):
    """Ordered logit: x = rating advantage (home incl.), c = draw half-width."""
    ph = sigmoid(x - c)
    pa = sigmoid(-c - x)
    pd = max(1e-9, 1.0 - ph - pa)
    s = ph + pd + pa
    return ph / s, pd / s, pa / s
