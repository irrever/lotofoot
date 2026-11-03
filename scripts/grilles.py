"""Charge les grilles Loto Foot publiées (7, 8 et 15 matchs) dans grilles/.

Pour chaque format, on lit la page de la dernière grille publiée par ruedesjoueurs.com et on n'en
retient que la liste des matchs, la fin de validation et le numéro de grille : ni pronostics, ni cotes.
Écrit grilles/loto-foot-<format>.json (seulement si la grille change) et grilles/statut.json.

Bibliothèque standard uniquement. Usage : python3 scripts/grilles.py [dossier de sortie]
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.ruedesjoueurs.com'
UA = 'Lotofoot-grilles/1.0 (+https://github.com/irrever/lotofoot)'
FORMATS = (7, 8, 15)
PAUSE = 3  # secondes entre deux requêtes

# Noms utilisés sur le site, quand ils diffèrent de ceux de la base de l'application
CORRESPONDANCES = {
    'Bayer Leverkusen': 'Leverkusen', 'Az Alkmaar': 'AZ Alkmaar', 'Juventus Turin': 'Juventus',
    'Celta Vigo': 'Celta', 'Saint-Gilloise': 'St. Gilloise', 'Brighton Hove': 'Brighton',
    'FC Séville': 'Sevilla', 'Annecy FC': 'Annecy', 'Man. United': 'Man United', 'Inter Milan': 'Inter',
    'Naples': 'Napoli', 'Como 1907': 'Como', 'Lazio Rome': 'Lazio', 'CF Valence': 'Valencia',
    'Atl. Madrid': 'Ath Madrid', 'FC Barcelone': 'Barcelona',
}


def lire(url):
    requete = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return reponse.read().decode('utf-8', 'replace')


def lignes(page):
    page = re.sub(r'<(script|style)\b.*?</\1>', ' ', page, flags=re.S | re.I)
    page = re.sub(r'<(br|/p|/div|/h[1-6]|/li|/tr|/td|/a)[^>]*>', '\n', page, flags=re.I)
    texte = html.unescape(re.sub(r'<[^>]+>', ' ', page))
    return [re.sub(r'\s+', ' ', l).strip() for l in texte.split('\n') if l.strip()]


def derniere_grille(format_):
    """Renvoie (année, numéro, adresse) de la grille la plus récente listée pour ce format."""
    page = lire('%s/paris-sportifs/lotofoot-%d.html' % (SITE, format_))
    motif = r'href="(/paris-sportifs/lotofoot-%d/numero-%d-(\d+)-(\d{4})[^"]*\.html)"' % (format_, format_)
    trouvees = [(int(a), int(n), href) for href, n, a in re.findall(motif, page)]
    if not trouvees:
        raise ValueError('aucune grille listée sur la rubrique')
    return max(trouvees)


def lire_grille(format_, adresse):
    """Renvoie (liste de (domicile, extérieur) tels qu'écrits sur le site, fin de validation)."""
    texte = lignes(lire(SITE + adresse))
    debut = next((i for i, l in enumerate(texte) if 'Analyse des matchs' in l), None)
    if debut is None:
        raise ValueError('liste des matchs introuvable sur la page')
    fin = next((i for i in range(debut + 1, len(texte))
                if 'Résultat Loto Foot' in texte[i] or 'Quel est le prono' in texte[i]), len(texte))
    matchs = []
    for l in texte[debut:fin]:
        m = re.match(r'^Pronostic (.+?) – (.+)$', l)
        if m and m.group(1) not in [a for a, _ in matchs]:
            matchs.append((m.group(1).strip(), m.group(2).strip()))
    if len(matchs) != format_:
        raise ValueError('%d matchs trouvés pour un format de %d' % (len(matchs), format_))
    validite = ''
    for l in texte:
        m = re.search(r'clôture le ([^)]+)\)', l)
        if m:
            validite = m.group(1).strip()
            break
    return matchs, validite


def canonique(nom):
    return CORRESPONDANCES.get(nom, nom)


def equipes_connues():
    with open(os.path.join(RACINE, 'donnees.json'), encoding='utf-8') as f:
        return {t['equipe'] for t in json.load(f)['equipes']}


def ecrire_si_change(chemin, objet):
    texte = json.dumps(objet, ensure_ascii=False, indent=1) + '\n'
    if os.path.exists(chemin):
        with open(chemin, encoding='utf-8') as f:
            if f.read() == texte:
                return False
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(texte)
    return True


def main(sortie):
    connues = equipes_connues()
    statut = {'verifie_le': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'formats': {}}
    echecs = 0
    for format_ in FORMATS:
        try:
            annee, numero, adresse = derniere_grille(format_)
            time.sleep(PAUSE)
            matchs, validite = lire_grille(format_, adresse)
            grille = {
                'format': format_,
                'numero': numero,
                'nom': 'Loto Foot %d · grille N°%d' % (format_, numero),
                'validite': validite,
                'source': 'ruedesjoueurs.com',
                'url': SITE + adresse,
                'matchs': [],
            }
            inconnues = []
            for a, b in matchs:
                d, e = canonique(a), canonique(b)
                for nom in (d, e):
                    if nom not in connues and nom not in inconnues:
                        inconnues.append(nom)
                grille['matchs'].append({'domicile': d, 'exterieur': e, 'libelle': '%s – %s' % (a, b)})
            ecrire_si_change(os.path.join(sortie, 'loto-foot-%d.json' % format_), grille)
            statut['formats'][str(format_)] = {'ok': True, 'numero': numero, 'equipes_inconnues': inconnues, 'erreur': None}
            detail = (', équipes inconnues : ' + ', '.join(inconnues)) if inconnues else ''
            print('Loto Foot %d : grille n°%d, %d matchs%s' % (format_, numero, len(matchs), detail))
        except Exception as e:  # une erreur sur un format n'empêche pas les autres
            echecs += 1
            statut['formats'][str(format_)] = {'ok': False, 'erreur': str(e)}
            print('Loto Foot %d : échec (%s) ; la grille précédente est gardée' % (format_, e), file=sys.stderr)
        time.sleep(PAUSE)
    ecrire_si_change(os.path.join(sortie, 'statut.json'), statut)
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, 'grilles')))
