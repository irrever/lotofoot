"""Quinté+ du jour : programme (réunion, heure, distance, partants) et arrivée avec rapports, une heure après le départ.

Sources : pages publiques de turfin.fr (programme du jour, page de course, arrivée et rapports PMU). Son API, son module
pour sites tiers (/widget, /api/) et ses notes ne sont pas utilisés ; ses règles robots.txt sont respectées (un contrôle
avant chaque requête). Une page par course et par tentative, avec un identifiant explicite.

Sortie : data/quinte/jours.json, lu par l’application (standalone/construire.py) et par le workflow quinte.yml.
Usage : python3 src/quinte.py maj            (relève le programme aux heures prévues, l’arrivée une heure après le départ)
        python3 src/quinte.py maj --forcer-programme
"""
import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import unicodedata
import urllib.request
import urllib.robotparser
import zoneinfo

RACINE = pathlib.Path(__file__).resolve().parent.parent
SORTIE = RACINE / 'data' / 'quinte' / 'jours.json'
TURFIN = 'https://turfin.fr'
URL_PRONOSTIC = TURFIN + '/pronostic/quinte-du-jour'
URL_ARRIVEE = TURFIN + '/arrivee-du-quinte'
UA = 'lotofoot-quinte/1.0 (relevé ponctuel, une page par course, identifié)'
JETON_ROBOTS = 'lotofoot-quinte'
FUSEAU = zoneinfo.ZoneInfo('Europe/Paris')
DELAI_ARRIVEE = dt.timedelta(hours=1)    # résultats relevés une heure après le départ
FIN_RECHERCHE = dt.timedelta(hours=3)    # au-delà, sans arrivée publiée, la course est notée « introuvable »
HEURES_PROGRAMME_UTC = (8, 9, 10)        # heures UTC, soit 9 h, 10 h et 11 h à Paris : le programme du jour y est relevé, une fois par heure au plus
JOURS_CONSERVES = 14
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre',
        'décembre']
DISCIPLINES = r'Attelé|Monté|Plat|Haies|Steeple-chase|Cross-country'
PARIS_RAPPORTS = r'Quinté\+|Quarté\+|Tiercé|Mini Multi|Multi|2sur4|Couplé placé|Couplé|Simple placé|Simple'


def texte(page):
    """Texte lisible d’une page HTML : sans scripts, sans balises, espaces réduits."""
    page = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', page, flags=re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page))).strip()


def date_fr(jour, mois, annee):
    return dt.date(int(annee), MOIS.index(mois) + 1, int(jour))


def slug(nom):
    """Partie d’adresse d’une course : minuscules, sans accents, tirets à la place des autres caractères."""
    s = ''.join(c for c in unicodedata.normalize('NFD', nom.lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def url_course(prog):
    return '%s/course/%s/r%dc%d-%s-%s' % (TURFIN, prog['date'], prog['reunion'], prog['numero'],
                                          slug(prog['hippodrome']), slug(prog['nom']))


def parse_programme(page):
    """En-tête du Quinté+ du jour : date, réunion, course, nom, hippodrome, discipline, distance, heure. None si absent."""
    t = texte(page)
    m = re.search(r'Pronostic du Quinté\+ du [^\d]*?(\d{1,2}) (\w+) (\d{4}) (.+?) à (.+?), départ (\d{1,2}:\d{2})', t)
    rc = re.search(r'Quinté\+ R(\d+)C(\d+) · .*? (%s) (\d{3,4}) m' % DISCIPLINES, t)
    if not (m and rc):
        return None
    jour, mois, annee, nom, hippodrome, heure = m.groups()
    return {'date': date_fr(jour, mois, annee).isoformat(), 'reunion': int(rc.group(1)), 'numero': int(rc.group(2)),
            'nom': nom.strip(), 'hippodrome': hippodrome.strip(), 'discipline': rc.group(3),
            'distance_m': int(rc.group(4)), 'heure': heure}


def parse_course(page):
    """Page de course : corde, allocation, nombre de partants et liste des partants (numéro, nom). None si illisible."""
    t = texte(page)
    i = t.find('Prochains départs')
    entete = t[i + len('Prochains départs'):] if i >= 0 else t
    h = re.search(r'(.+?) R(\d+)C(\d+) · (.+?) · \w+ (\d{1,2}) (\w+) (\d{4}) · (\d{1,2}:\d{2})', entete)
    d = re.search(r'\| (%s) \| (\d{3,4}) m \| (\d+) partants \| Corde à (\w+) \| ([\d ]+) € d.allocation' % DISCIPLINES, t)
    if not (h and d):
        return None
    liste = [{'numero': int(n), 'nom': texte(nom)} for n, nom in
             re.findall(r'<tbody class="pt[^"]*"[^>]*data-num="(\d+)"[^>]*>\s*<tr.*?<td class="nom">\s*<a[^>]*>(.*?)</a>',
                        page, flags=re.S)]
    return {'nom': h.group(1).strip(), 'reunion': int(h.group(2)), 'numero': int(h.group(3)),
            'hippodrome': h.group(4).strip(), 'date': date_fr(h.group(5), h.group(6), h.group(7)).isoformat(),
            'heure': h.group(8), 'discipline': d.group(1), 'distance_m': int(d.group(2)), 'partants': int(d.group(3)),
            'corde': d.group(4), 'allocation_eur': int(d.group(5).replace(' ', '')), 'liste': liste}


NOMBRE_ARRIVES = {'Quinté+': 5, 'Quarté+': 4, 'Tiercé': 3}


def type_rapport(pari, combinaison, deja_vu):
    """Ordre et désordre pour les paris à l’arrivée (la première ligne est l’ordre), bonus à 3 ou 4 chevaux, sinon simple."""
    n = len(combinaison)
    if pari in NOMBRE_ARRIVES and n == NOMBRE_ARRIVES[pari]:
        return 'désordre' if tuple(combinaison) in deja_vu else 'ordre'
    if pari in ('Quinté+', 'Quarté+') and n in (3, 4):
        return 'bonus%d' % n
    return 'simple'


def parse_arrivee(page):
    """Arrivée officielle (cinq premiers, dans l’ordre) et rapports PMU pour 1 € misé. None si pas encore publiée."""
    t = texte(page)
    h = re.search(r'Résultat du Quinté\+ du[^0-9]*(\d{2})/(\d{2})/(\d{4}) R(\d+)C(\d+)', t)
    o = re.search(r'Arrivée officielle : (\d+) - (\d+) - (\d+) - (\d+) - (\d+)', t)
    if not (h and o):
        return None
    debut = t.find('Arrivée officielle 1')
    fin = re.search(r'Ce qu.on annonçait', t[debut:]) if debut >= 0 else None
    bloc = t[debut: debut + fin.start()] if fin else ''
    arrivants = [{'rang': int(r), 'numero': int(n), 'nom': nom.strip()}
                 for r, n, nom in re.findall(r'\b([1-5]) (\d{1,2}) ([^\d,]+?) \d+,\d\b', bloc)]
    ordre = [int(x) for x in o.groups()]
    if [a['numero'] for a in sorted(arrivants, key=lambda a: a['rang'])] != ordre or len(arrivants) != 5:
        return None
    debut_r = t.find('Rapports officiels')
    fin_r = t.find('Dividendes officiels PMU', debut_r)
    bloc_r = t[debut_r + len('Rapports officiels'): fin_r if fin_r > debut_r else None] if debut_r >= 0 else ''
    morceaux = re.split('(%s)' % PARIS_RAPPORTS, bloc_r)
    rapports = []
    for i in range(1, len(morceaux) - 1, 2):
        pari, contenu = morceaux[i], morceaux[i + 1]
        vus = set()
        for combi, montant in re.findall(r'((?:\d{1,2} )*\d{1,2}) (\d+,\d{2}) €', contenu):
            nums = [int(x) for x in combi.split()]
            rapports.append({'pari': pari, 'type': type_rapport(pari, nums, vus), 'combinaison': nums,
                             'rapport': float(montant.replace(',', '.'))})
            vus.add(tuple(nums))
    return {'date': dt.date(int(h.group(3)), int(h.group(2)), int(h.group(1))).isoformat(),
            'reunion': int(h.group(4)), 'numero': int(h.group(5)), 'ordre': ordre, 'arrivants': arrivants,
            'rapports': rapports}


def autorise_robots(texte_robots, url):
    """Vrai si le fichier robots.txt autorise notre jeton pour cette adresse."""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(texte_robots.splitlines())
    return rp.can_fetch(JETON_ROBOTS, url)


_ROBOTS = {}


def telecharger_turfin(url):
    """Page de turfin.fr, si son robots.txt l’autorise à notre jeton. Erreur sinon (ou si robots.txt est illisible)."""
    if 'robots' not in _ROBOTS:
        try:
            _ROBOTS['robots'] = fetch(TURFIN + '/robots.txt')
        except Exception:
            _ROBOTS['robots'] = None
    if _ROBOTS['robots'] is None or not autorise_robots(_ROBOTS['robots'], url):
        raise RuntimeError('non autorisé par robots.txt : ' + url)
    return fetch(url)


def fetch(url):
    requete = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,text/plain'})
    with urllib.request.urlopen(requete, timeout=20) as reponse:
        return reponse.read().decode('utf-8', errors='replace')


def depart_utc(date_iso, heure):
    h, m = (int(x) for x in heure.split(':'))
    local = dt.datetime.combine(dt.date.fromisoformat(date_iso), dt.time(h, m), tzinfo=FUSEAU)
    return local.astimezone(dt.timezone.utc)


def charger(chemin=SORTIE):
    return json.loads(chemin.read_text(encoding='utf-8')) if chemin.exists() else {}


def enregistrer(donnees, chemin=SORTIE):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix('.tmp')
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    os.replace(tmp, chemin)


def relever_programme(jour, telecharger, messages):
    """Programme et partants du Quinté+ du jour, s’il est affiché pour ce jour. None sinon."""
    try:
        prog = parse_programme(telecharger(URL_PRONOSTIC))
    except Exception as err:
        messages.append('programme : %s' % err)
        return None
    if not prog or prog['date'] != jour.isoformat():
        messages.append('pas de Quinté+ annoncé pour le %s' % jour.isoformat())
        return None
    course = {**prog, 'url': url_course(prog),
              'depart_utc': depart_utc(prog['date'], prog['heure']).isoformat(timespec='minutes')}
    try:
        detail = parse_course(telecharger(course['url']))
        if detail and (detail['reunion'], detail['numero']) == (prog['reunion'], prog['numero']):
            course.update({k: detail[k] for k in ('partants', 'corde', 'allocation_eur', 'liste')})
    except Exception as err:
        messages.append('détail de course : %s' % err)
    messages.append('programme %s : R%dC%d %s, %s' % (jour.isoformat(), prog['reunion'], prog['numero'],
                                                      prog['hippodrome'], prog['heure']))
    return course


def relever_course(adresse, jour, telecharger, messages):
    """Programme d’une course d’après sa page (pour un jour passé, quand le programme du jour n’a pas été relevé)."""
    try:
        detail = parse_course(telecharger(adresse))
    except Exception as err:
        messages.append('course %s : %s' % (adresse, err))
        return None
    if not detail or detail['date'] != jour.isoformat():
        messages.append('course %s : pas celle du %s' % (adresse, jour.isoformat()))
        return None
    return {**detail, 'url': adresse, 'depart_utc': depart_utc(detail['date'], detail['heure']).isoformat(timespec='minutes')}


def maj(maintenant=None, jour=None, telecharger=None, chemin=SORTIE, forcer_programme=False, adresse_course=None,
        forcer_arrivee=False):
    """Met à jour data/quinte/jours.json : programme du jour aux heures prévues, puis arrivée une heure après le départ.
    Le fichier n’est réécrit que si une donnée change. Renvoie un résumé (modifié, messages)."""
    telecharger = telecharger or telecharger_turfin
    maintenant = (maintenant or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    aujourdhui = maintenant.astimezone(FUSEAU).date()
    jour = jour or aujourdhui
    donnees = charger(chemin)
    messages, modifie = [], False

    e = donnees.setdefault(jour.isoformat(), {})
    heure_programme = maintenant.hour in HEURES_PROGRAMME_UTC and maintenant.minute < 10
    if jour >= aujourdhui and 'course' not in e and (heure_programme or forcer_programme):
        course = relever_programme(jour, telecharger, messages)
        if course:
            e['course'] = course
            modifie = True
    if adresse_course and 'course' not in e:
        course = relever_course(adresse_course, jour, telecharger, messages)
        if course:
            e['course'] = course
            modifie = True

    for d in (jour, jour - dt.timedelta(days=1)):
        e = donnees.get(d.isoformat(), {})
        c = e.get('course')
        if not c or 'arrivee' in e:
            continue
        due = depart_utc(c['date'], c['heure']) + DELAI_ARRIVEE
        if maintenant < due:
            continue
        if maintenant > due + FIN_RECHERCHE and not forcer_arrivee:
            if e.get('arrivee_etat') != 'introuvable':
                e['arrivee_etat'] = 'introuvable'
                modifie = True
            continue
        url = URL_ARRIVEE if d == aujourdhui else '%s/%s' % (URL_ARRIVEE, d.isoformat())
        try:
            arr = parse_arrivee(telecharger(url))
        except Exception as err:
            messages.append('arrivée %s : %s' % (d.isoformat(), err))
            continue
        if arr and (arr['date'], arr['reunion'], arr['numero']) == (d.isoformat(), c['reunion'], c['numero']):
            e['arrivee'] = {'ordre': arr['ordre'], 'arrivants': arr['arrivants'], 'rapports': arr['rapports'],
                            'source': url, 'vue_le': maintenant.isoformat(timespec='seconds')}
            e.pop('arrivee_etat', None)
            modifie = True
            messages.append('arrivée %s : %s' % (d.isoformat(), '-'.join(str(n) for n in arr['ordre'])))
        else:
            messages.append('arrivée %s : pas encore publiée' % d.isoformat())

    if modifie:
        for cle in sorted(donnees)[:-JOURS_CONSERVES]:
            del donnees[cle]
        enregistrer(donnees, chemin)
    return {'modifie': modifie, 'messages': messages}


def main(argv=None):
    p = argparse.ArgumentParser(description='Quinté+ du jour : programme et arrivée, une heure après le départ.')
    p.add_argument('commande', choices=['maj'])
    p.add_argument('--jour', help='AAAA-MM-JJ (par défaut : aujourd’hui, à Paris)')
    p.add_argument('--maintenant', help='instant ISO 8601 (pour les essais)')
    p.add_argument('--forcer-programme', action='store_true', help='relève le programme à toute heure')
    p.add_argument('--course-url', help='adresse de la page de course, pour un jour passé (avec --jour)')
    a = p.parse_args(argv)
    maintenant = dt.datetime.fromisoformat(a.maintenant) if a.maintenant else None
    jour = dt.date.fromisoformat(a.jour) if a.jour else None
    resume = maj(maintenant=maintenant, jour=jour, forcer_programme=a.forcer_programme, adresse_course=a.course_url,
                 forcer_arrivee=bool(a.course_url))
    for m in resume['messages']:
        print(m)
    print('données modifiées' if resume['modifie'] else 'aucun changement')
    return 0


if __name__ == '__main__':
    sys.exit(main())
