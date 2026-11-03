"""Relève les blessés et suspendus des championnats suivis, avec la source API-Football.

Chaque exécution compare la liste actuelle à celle de l'exécution précédente et n'ajoute au journal
(data/absences/evenements.jsonl) que les changements :
- « debut » : un joueur apparaît dans la liste ;
- « fin » : un joueur n'y figure plus.
La date enregistrée est la date de l'observation, pas la date réelle de la blessure.

Sans clé d'accès (variable d'environnement API_FOOTBALL_KEY), le script ne fait rien.
Un championnat en erreur garde son état précédent : il n'est jamais marqué comme rétabli.
Aucune cote n'est demandée.

Usage : python3 src/absences.py
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

RACINE = pathlib.Path(__file__).resolve().parent.parent
DOSSIER = RACINE / 'data' / 'absences'
ETAT = DOSSIER / 'etat.json'
JOURNAL = DOSSIER / 'evenements.jsonl'
LIGUES = json.load(open(RACINE / 'data' / 'ligues_api.json', encoding='utf-8'))
BASE = os.environ.get('API_FOOTBALL_BASE', 'https://v3.football.api-sports.io')
SAISON = int(os.environ.get('API_FOOTBALL_SAISON', '2026'))  # saison 2026-27 : année de début
PAUSE = float(os.environ.get('API_FOOTBALL_PAUSE', '3'))  # secondes entre deux appels (limite par minute)


def appeler(cle, chemin, params):
    """Une requête vers l'API. Lève une erreur si l'API signale un problème."""
    url = BASE + chemin + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'x-apisports-key': cle, 'User-Agent': 'Lotofoot-absences/1.0'})
    with urllib.request.urlopen(req, timeout=60) as rep:
        donnees = json.load(rep)
    if donnees.get('errors'):
        raise RuntimeError('API : %s' % donnees['errors'])
    return donnees


def toutes_les_pages(cle, chemin, params):
    resultats, page = [], 1
    while True:
        donnees = appeler(cle, chemin, dict(params, page=page))
        resultats += donnees.get('response') or []
        if page >= int((donnees.get('paging') or {}).get('total') or 1):
            return resultats
        page += 1
        time.sleep(PAUSE)


def blesses(cle, identifiant):
    """Blessés et suspendus d'un championnat, un joueur une seule fois, et le nom du championnat."""
    liste, nom = {}, ''
    for x in toutes_les_pages(cle, '/injuries', {'league': identifiant, 'season': SAISON}):
        joueur, equipe = x.get('player') or {}, x.get('team') or {}
        nom = nom or (x.get('league') or {}).get('name', '')
        if joueur.get('id') is None:
            continue
        liste[str(joueur['id'])] = {
            'joueur_id': joueur['id'], 'joueur': joueur.get('name', ''),
            'type': joueur.get('type', ''), 'raison': joueur.get('reason', ''),
            'equipe_id': equipe.get('id'), 'equipe': equipe.get('name', ''),
        }
    return liste, nom


def main():
    cle = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not cle:
        print('Aucune clé API-Football : rien à relever.')
        return 0
    DOSSIER.mkdir(parents=True, exist_ok=True)
    etat = json.load(open(ETAT, encoding='utf-8')) if ETAT.exists() else {}
    aujourd = dt.datetime.now(dt.timezone.utc).date().isoformat()
    lignes, erreurs = [], 0
    for code, identifiant in LIGUES.items():
        try:
            actuels, nom = blesses(cle, identifiant)
        except Exception as e:
            print('%-4s erreur : %s' % (code, e))
            erreurs += 1
            time.sleep(PAUSE)
            continue
        precedents = etat.get(code, {})
        for cle_joueur, a in actuels.items():
            if cle_joueur not in precedents:
                lignes.append(dict(a, date=aujourd, ligue=code, evenement='debut'))
        for cle_joueur, a in precedents.items():
            if cle_joueur not in actuels:
                lignes.append(dict(a, date=aujourd, ligue=code, evenement='fin'))
        etat[code] = actuels
        print('%-4s %-28s blessés et suspendus : %d' % (code, nom or '(nom inconnu)', len(actuels)))
        time.sleep(PAUSE)
    if erreurs == len(LIGUES):
        print('Aucun championnat relevé : état et journal inchangés.')
        return 1
    if lignes:
        with open(JOURNAL, 'a', encoding='utf-8') as f:
            for ligne in lignes:
                f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    with open(ETAT, 'w', encoding='utf-8') as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    print('Changements enregistrés : %d (%d championnat(s) en erreur)' % (len(lignes), erreurs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
