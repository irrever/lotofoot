"""Charge les grilles Loto Foot ouvertes (7, 8, 12 et 15 matchs) dans grilles/.

Pour chaque format, on examine les dernières grilles listées par ruedesjoueurs.com et on ne garde que
celles dont la clôture n'est pas encore passée. Pour chacune : le numéro, l'heure de clôture, la liste
des matchs. Ni pronostics, ni cotes. Écrit grilles/loto-foot-<format>.json et grilles/statut.json.

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
from zoneinfo import ZoneInfo

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.ruedesjoueurs.com'
UA = 'Lotofoot-grilles/1.0 (+https://github.com/irrever/lotofoot)'
FORMATS = (7, 8, 12, 15)
CANDIDATES = 3  # nombre de grilles les plus récentes examinées pour chaque format
PAUSE = 2  # secondes entre deux requêtes
PARIS = ZoneInfo('Europe/Paris')
MOIS = {'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
        'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12}

# Noms utilisés sur le site, quand ils diffèrent de ceux de la base de l'application
CORRESPONDANCES = {
    'Bayer Leverkusen': 'Leverkusen', 'Az Alkmaar': 'AZ Alkmaar', 'Juventus Turin': 'Juventus',
    'Celta Vigo': 'Celta', 'Saint-Gilloise': 'St. Gilloise', 'Brighton Hove': 'Brighton',
    'FC Séville': 'Sevilla', 'Annecy FC': 'Annecy', 'Man. United': 'Man United', 'Inter Milan': 'Inter',
    'Naples': 'Napoli', 'Como 1907': 'Como', 'Lazio Rome': 'Lazio', 'CF Valence': 'Valencia',
    'Atl. Madrid': 'Ath Madrid', 'FC Barcelone': 'Barcelona',
    'AS Rome': 'Roma', 'FC Porto': 'Porto', 'Club Bruges': 'Club Brugge', 'Man. City': 'Man City',
    'AEK Athènes': 'AEK', 'Betis Séville': 'Betis', 'Slo.Bratislava': 'Slovan Bratislava',
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


def cloture_de(texte):
    """« mardi 3 novembre 2026 à 20 h 55 » -> date et heure de Paris, ou None."""
    m = re.search(r'(\d{1,2}) ([a-zéûèô]+) (\d{4}) à (\d{1,2}) h (\d{2})', texte)
    if not m or m.group(2) not in MOIS:
        return None
    return dt.datetime(int(m.group(3)), MOIS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)), tzinfo=PARIS)


def lire_grille(format_, href):
    """Renvoie (matchs, texte de clôture, date de clôture), ou None si le site n'affiche plus de clôture."""
    texte = lignes(lire(SITE + href))
    cloture = None
    for l in texte:
        m = re.search(r'clôture le ([^)]+)\)', l)
        if m:
            cloture = m.group(1).strip()
            break
    if cloture is None:
        return None
    date = cloture_de(cloture)
    if date is None:
        raise ValueError('date de clôture illisible : %s' % cloture)
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
    return matchs, cloture, date


def canonique(nom):
    return CORRESPONDANCES.get(nom, nom)


def grilles_ouvertes(format_):
    """Grilles dont la clôture n'est pas passée, de la plus proche à la plus lointaine."""
    index = lire('%s/paris-sportifs/lotofoot-%d.html' % (SITE, format_))
    motif = r'href="(/paris-sportifs/lotofoot-%d/numero-%d-(\d+)-(\d{4})[^"]*\.html)"' % (format_, format_)
    recentes = sorted({(int(a), int(n), href) for href, n, a in re.findall(motif, index)}, reverse=True)
    if not recentes:
        raise ValueError('aucune grille listée sur la rubrique')
    maintenant = dt.datetime.now(dt.timezone.utc)
    ouvertes = []
    for annee, numero, href in recentes[:CANDIDATES]:
        time.sleep(PAUSE)
        lu = lire_grille(format_, href)
        if lu is None:
            continue
        matchs, cloture, date = lu
        if date <= maintenant:
            continue
        ouvertes.append({
            'numero': numero,
            'nom': 'Loto Foot %d · grille N°%d' % (format_, numero),
            'cloture': date.isoformat(),
            'validite': cloture,
            'source': 'ruedesjoueurs.com',
            'url': SITE + href,
            'matchs': [{'domicile': canonique(a), 'exterieur': canonique(b), 'libelle': '%s – %s' % (a, b)}
                       for a, b in matchs],
        })
    return sorted(ouvertes, key=lambda g: g['cloture'])


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
            ouvertes = grilles_ouvertes(format_)
            inconnues = []
            for g in ouvertes:
                for m in g['matchs']:
                    for nom in (m['domicile'], m['exterieur']):
                        if nom not in connues and nom not in inconnues:
                            inconnues.append(nom)
            ecrire_si_change(os.path.join(sortie, 'loto-foot-%d.json' % format_), {'format': format_, 'grilles': ouvertes})
            statut['formats'][str(format_)] = {'ok': True, 'grilles_ouvertes': [g['numero'] for g in ouvertes],
                                               'equipes_inconnues': inconnues, 'erreur': None}
            detail = ', '.join('n°%d clôture %s' % (g['numero'], g['validite']) for g in ouvertes) or 'aucune grille ouverte'
            print('Loto Foot %d : %s%s' % (format_, detail, (' ; équipes inconnues : ' + ', '.join(inconnues)) if inconnues else ''))
        except Exception as e:  # une erreur sur un format n'empêche pas les autres ; l'ancien fichier est gardé
            echecs += 1
            statut['formats'][str(format_)] = {'ok': False, 'erreur': str(e)}
            print('Loto Foot %d : échec (%s) ; la version précédente est gardée' % (format_, e), file=sys.stderr)
        time.sleep(PAUSE)
    ecrire_si_change(os.path.join(sortie, 'statut.json'), statut)
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, 'grilles')))
