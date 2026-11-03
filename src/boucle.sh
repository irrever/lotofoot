#!/bin/sh
# Boucle d’observation, à lancer une fois par jour avant les matchs :
# 1. publier.py récupère les résultats et met à jour le modèle ;
# 2. journal.py enregistre les prévisions des matchs à venir (avant leur déroulement) ;
# 3. bilan.py compare les prévisions et les résultats, et rédige le bilan.
# Usage : sh boucle.sh [--sans-telechargement]
set -e
cd "$(dirname "$0")"
python3 publier.py "$@"
python3 journal.py
python3 bilan.py
# Reconstruit les deux versions de l’application avec le bilan à jour
python3 ../standalone/construire.py
