"""Équipes nationales : chiffres du modèle pour les sélections (estimation), écrits dans data/selections.json.

Source : historique des matchs internationaux (dépôt martj42/international_results, sur GitHub).
Méthode : la même que pour les clubs (Elo, forme, buts, bilans à domicile et à l’extérieur), avec les mêmes
constantes. Repos, charge, tirs, corners et cartons ne sont pas disponibles pour les sélections : l’application
les ramène à la moyenne du modèle, par rôle (domicile ou extérieur).

Usage : python3 selections.py [chemin_du_csv]
Sans téléchargement possible, le fichier publié précédemment est conservé.
"""
import collections, csv, datetime as dt, json, math, pathlib, sys, urllib.request

RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = 'https://raw.githubusercontent.com/martj42/international_results/master/results.csv'
CACHE = RACINE / 'data' / 'raw' / 'international_results.csv'   # ignoré par git
PUBLIEES = RACINE / 'data' / 'donnees_publiees.json'
SORTIE = RACINE / 'data' / 'selections.json'

# Mêmes constantes que les clubs (data/model_state.json)
K, HA, S_ELO, C_ELO = 30, 90, 250, 0.6
SHRINK, WIN_HA, WIN_FORM, WIN_STAT, LOAD_DAYS, REST_CAP = 8, 20, 5, 10, 30, 21
PTS = {'W': 3, 'D': 1, 'L': 0}
CODE_LIGUE, NOM_LIGUE = 'SEL', 'Équipes nationales'

# Nations des grilles : nom affiché dans l’application -> nom dans le fichier source
NATIONS = {
    'Albanie': 'Albania', 'Allemagne': 'Germany', 'Andorre': 'Andorra', 'Angleterre': 'England',
    'Argentine': 'Argentina', 'Arménie': 'Armenia', 'Autriche': 'Austria', 'Azerbaïdjan': 'Azerbaijan',
    'Belgique': 'Belgium', 'Biélorussie': 'Belarus', 'Bosnie-Herzégovine': 'Bosnia and Herzegovina',
    'Bulgarie': 'Bulgaria', 'Chili': 'Chile', 'Chypre': 'Cyprus', 'Colombie': 'Colombia', 'Croatie': 'Croatia',
    'Danemark': 'Denmark', 'Écosse': 'Scotland', 'Espagne': 'Spain', 'Estonie': 'Estonia', 'Finlande': 'Finland',
    'France': 'France', 'Gibraltar': 'Gibraltar', 'Géorgie': 'Georgia', 'Grèce': 'Greece', 'Hongrie': 'Hungary',
    'Irlande': 'Republic of Ireland', 'Irlande du Nord': 'Northern Ireland', 'Islande': 'Iceland', 'Italie': 'Italy',
    'Îles Féroé': 'Faroe Islands', 'Kazakhstan': 'Kazakhstan', 'Lettonie': 'Latvia', 'Liechtenstein': 'Liechtenstein',
    'Luxembourg': 'Luxembourg', 'Macédoine du Nord': 'North Macedonia', 'Moldavie': 'Moldova',
    'Monténégro': 'Montenegro', 'Norvège': 'Norway', 'Pays de Galles': 'Wales', 'Pays-Bas': 'Netherlands',
    'Pologne': 'Poland', 'Portugal': 'Portugal', 'Roumanie': 'Romania', 'Saint-Marin': 'San Marino',
    'Serbie': 'Serbia', 'Slovaquie': 'Slovakia', 'Slovénie': 'Slovenia', 'Suisse': 'Switzerland', 'Suède': 'Sweden',
    'Tchéquie': 'Czech Republic', 'Turquie': 'Turkey', 'Ukraine': 'Ukraine', 'Uruguay': 'Uruguay',
}
# Adversaires affichés en français (les autres gardent leur nom du fichier source)
AFFICHAGE = {v: k for k, v in NATIONS.items()}
AFFICHAGE.update({
    'Morocco': 'Maroc', 'Brazil': 'Brésil', 'Japan': 'Japon', 'United States': 'États-Unis', 'Mexico': 'Mexique',
    'Australia': 'Australie', 'Egypt': 'Égypte', 'Algeria': 'Algérie', 'Tunisia': 'Tunisie', 'Senegal': 'Sénégal',
    'Cameroon': 'Cameroun', 'Ivory Coast': 'Côte d’Ivoire', 'South Korea': 'Corée du Sud',
    'Saudi Arabia': 'Arabie saoudite', 'Ecuador': 'Équateur', 'Peru': 'Pérou', 'Bolivia': 'Bolivie', 'Israel': 'Israël',
    'Malta': 'Malte', 'Iran': 'Iran', 'Qatar': 'Qatar', 'Nigeria': 'Nigeria', 'Ghana': 'Ghana', 'Paraguay': 'Paraguay',
    'Venezuela': 'Venezuela', 'Kosovo': 'Kosovo', 'China PR': 'Chine', 'New Zealand': 'Nouvelle-Zélande',
    'Jamaica': 'Jamaïque', 'Panama': 'Panama', 'Honduras': 'Honduras', 'El Salvador': 'Salvador', 'Iraq': 'Irak',
    'Uzbekistan': 'Ouzbékistan', 'Indonesia': 'Indonésie', 'Thailand': 'Thaïlande', 'Vietnam': 'Vietnam',
    'Bahrain': 'Bahreïn', 'Oman': 'Oman', 'United Arab Emirates': 'Émirats arabes unis', 'South Africa': 'Afrique du Sud',
    'Mali': 'Mali', 'DR Congo': 'RD Congo', 'Trinidad and Tobago': 'Trinité-et-Tobago', 'Haiti': 'Haïti',
    'Guatemala': 'Guatemala', 'Cuba': 'Cuba', 'Guinea': 'Guinée', 'Kenya': 'Kenya', 'Zambia': 'Zambie',
    'Uganda': 'Ouganda', 'Ethiopia': 'Éthiopie', 'Angola': 'Angola', 'Gabon': 'Gabon', 'India': 'Inde',
    'Myanmar': 'Birmanie', 'Cape Verde': 'Cap-Vert', 'Dominican Republic': 'République dominicaine',
})
TOURNOIS = {
    'Friendly': 'Amical', 'FIFA World Cup': 'Coupe du monde', 'FIFA World Cup qualification': 'Qualif. Coupe du monde',
    'UEFA Euro': 'Euro', 'UEFA Euro qualification': 'Qualif. Euro', 'UEFA Nations League': 'Ligue des nations',
    'African Cup of Nations': 'CAN', 'Copa América': 'Copa América', 'AFC Asian Cup': 'Coupe d’Asie',
    'CONCACAF Gold Cup': 'Gold Cup',
}
LETTRE = {'W': 'V', 'D': 'N', 'L': 'D'}


def probs_from_x(x, c):
    sig = lambda z: 1 / (1 + math.exp(-z))
    ph, pa = sig(x - c), sig(-c - x)
    pd = max(1e-9, 1 - ph - pa)
    s = ph + pd + pa
    return ph / s, pd / s, pa / s


def moyennes_modele():
    """Moyennes du modèle des clubs pour les variables absentes des sélections (rôle domicile)."""
    m = json.load(open(PUBLIEES, encoding='utf-8'))['modele']['moyenne']
    return {'cadF': m[17], 'cadA': m[18], 'cor': m[21], 'car': m[23]}


def charger(argument):
    if argument:
        return pathlib.Path(argument)
    try:
        with urllib.request.urlopen(SOURCE, timeout=120) as rep:
            contenu = rep.read()
    except Exception as erreur:  # réseau indisponible : on ne publie pas de données anciennes
        print('Sélections : téléchargement impossible :', erreur)
        return None
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(contenu)
    return CACHE


def compte(liste):
    return {'V': sum(1 for x in liste if x[2] == 'W'), 'N': sum(1 for x in liste if x[2] == 'D'),
            'D': sum(1 for x in liste if x[2] == 'L'), 'n': len(liste)}


def rencontre(x):
    d, lieu, res, buts, encaisses, adversaire, tournoi = x
    return {'date': d.isoformat(), 'adv': AFFICHAGE.get(adversaire, adversaire), 'score': f'{buts}–{encaisses}',
            'lieu': {'dom': 'dom.', 'ext': 'ext.', None: 'neutre'}[lieu], 'res': LETTRE[res],
            'tournoi': TOURNOIS.get(tournoi, tournoi)}


def calculer(chemin, asof):
    rows = []
    with open(chemin, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                d = dt.date.fromisoformat(r['date'])
            except ValueError:
                continue
            if d > asof or not r['home_score'] or not r['away_score']:
                continue
            rows.append((d, r['home_team'], r['away_team'], int(r['home_score']), int(r['away_score']),
                         r['neutral'] == 'TRUE', r['tournament']))
    rows.sort()
    R = collections.defaultdict(lambda: 1500.0)
    # équipe -> [(date, lieu, résultat du point de vue de l’équipe, buts pour, buts contre, adversaire, compétition)]
    hist = collections.defaultdict(list)
    for d, h, a, hs, als, neutre, tournoi in rows:
        ha = 0 if neutre else HA
        ph, pd, pa = probs_from_x((R[h] + ha - R[a]) / S_ELO, C_ELO)
        res = 'W' if hs > als else ('D' if hs == als else 'L')
        delta = K * ({'W': 1.0, 'D': 0.5, 'L': 0.0}[res] - (ph + 0.5 * pd))
        R[h] += delta
        R[a] -= delta
        hist[h].append((d, None if neutre else 'dom', res, hs, als, a, tournoi))
        hist[a].append((d, None if neutre else 'ext', {'W': 'L', 'D': 'D', 'L': 'W'}[res], als, hs, h, tournoi))

    tout = [x for v in hist.values() for x in v]
    prior_gf = sum(x[3] for x in tout) / len(tout)
    pW = sum(1 for x in tout if x[2] == 'W') / len(tout)
    pD = sum(1 for x in tout if x[2] == 'D') / len(tout)
    pL = 1 - pW - pD

    def part(liste):
        n = len(liste)
        v = sum(1 for x in liste if x[2] == 'W')
        nul = sum(1 for x in liste if x[2] == 'D')
        return ((v + SHRINK * pW) / (n + SHRINK), (nul + SHRINK * pD) / (n + SHRINK),
                ((n - v - nul) + SHRINK * pL) / (n + SHRINK))

    moyen = moyennes_modele()
    equipes, matchs = [], {}
    for nom, source in NATIONS.items():
        lst = hist.get(source, [])
        if not lst:
            print('Sélections : aucun match trouvé pour', nom, '(', source, ')')
            continue
        if sum(1 for x in lst if x[0] >= dt.date(2022, 1, 1)) < 3:
            print('Sélections : trop peu de matchs depuis 2022 pour', nom)
            continue
        dom = [x for x in lst if x[1] == 'dom'][-WIN_HA:]
        ext = [x for x in lst if x[1] == 'ext'][-WIN_HA:]
        dW, dD, dL = part(dom)
        eW, eD, eL = part(ext)
        derniers = lst[-WIN_FORM:]
        forme = sum(PTS[x[2]] for x in derniers) / len(derniers)
        recent = lst[-WIN_STAT:]
        gf = (sum(x[3] for x in recent) + SHRINK * prior_gf) / (len(recent) + SHRINK)
        ga = (sum(x[4] for x in recent) + SHRINK * prior_gf) / (len(recent) + SHRINK)
        jours = (asof - lst[-1][0]).days
        charge = sum(1 for x in lst if 0 < (asof - x[0]).days <= LOAD_DAYS)
        elo = R[source]
        vec = {'elo': elo, 'dW': dW, 'dD': dD, 'dL': dL, 'eW': eW, 'eD': eD, 'eL': eL, 'forme': forme,
               'gf': gf, 'ga': ga, 'rest': float(min(REST_CAP, jours)), 'load': float(charge), **moyen}
        equipes.append({
            'ligue': CODE_LIGUE, 'ligue_nom': NOM_LIGUE, 'equipe': nom,
            'domicile': compte(dom), 'exterieur': compte(ext),
            'forme': ''.join(LETTRE[x[2]] for x in derniers),
            'buts_pour': round(gf, 2), 'buts_contre': round(ga, 2),
            'tirs_cadres_pour': None, 'tirs_cadres_contre': None, 'corners_pour': None, 'cartons': None,
            'jours_depuis_dernier_match': jours, 'matchs_30_jours': charge,
            'elo': round(elo), 'rang_elo_dans_le_championnat': None, 'vec': vec,
        })
        matchs[nom] = {'derniere': lst[-1][0].isoformat(),
                       'derniers': [rencontre(x) for x in reversed(derniers)]}
    dernier = max(x[0] for x in tout)
    return {'version': 1, 'asof': asof.isoformat(),
            'source': f'martj42/international_results, {len(rows)} matchs, dernier le {dernier.isoformat()}',
            'equipes': equipes, 'matchs': matchs}


def main():
    chemin = charger(sys.argv[1] if len(sys.argv) > 1 else None)
    if chemin is None:
        print('Sélections : données non mises à jour, le fichier publié est conservé.')
        return
    resultat = calculer(chemin, dt.date.today())
    SORTIE.write_text(json.dumps(resultat, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('Sélections :', len(resultat['equipes']), 'équipes, données arrêtées au', resultat['asof'])


if __name__ == '__main__':
    main()
