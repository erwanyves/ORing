# Chemin : modules/oring_debug.py
# -*- coding: utf-8 -*-
"""
ORing/modules/oring_debug.py

Bruit de diagnostic — désactivable (audit UX, point 2.6).

`dialogue.py` (dont les modules extraits `widgets.py`,
supprimes le 15/09/2026 : copies mortes) contenaient plus de 165 print()
de traçage ("[ORing DIAG]", "[ORing TNP]", "[ORing lies]", "[ORing modif]",
...), historiquement utiles pour déboguer les opérations FreeCAD complexes
(topologie, TNP, mise à jour des joints liés) mais qui s'affichaient aussi
en usage normal, noyant les avertissements/erreurs FreeCAD légitimes dans
le Report View.

Plutôt que de retirer ~165 appels un par un (risque d'erreur élevé sans
pouvoir tester dans FreeCAD), `print()` est redéfini ici une seule fois et
importé (`from .oring_debug import print`) par chaque module qui en a
besoin : les lignes "ERREUR"/"AVERT" restent toujours visibles, le reste
est silencieux par défaut et réactivable via la variable d'environnement
ORING_DEBUG=1 (ou en modifiant ORING_DEBUG ci-dessous).

Module partagé en interne à ORing uniquement (pas de dépendance croisée
avec une autre macro).
"""
import builtins as _builtins_debug
import os as _os_debug

# Valeur relevée à l'import — laissée modifiable à la main, comme l'annonce la
# docstring ci-dessus (`oring_debug.ORING_DEBUG = True` dans la console).
ORING_DEBUG = _os_debug.environ.get('ORING_DEBUG', '') not in ('', '0', 'false', 'False')


# Vocabulaire qui fait passer une ligne MALGRE le masquage.
#
# Il ne contenait que ('ERREUR', 'erreur', 'AVERT', 'Erreur') jusqu'au
# 13/09/2026. Relevé ce jour-là : **quinze lignes d'ORing signalent un
# problème sans employer aucun de ces quatre mots** et étaient donc
# silencieuses — « métadonnées introuvables », « sketch introuvable →
# fallback », « lang.txt : code invalide → auto-détection », « {lang}.json
# introuvable → anglais forcé », « masquage impossible : … ».
#
# Plusieurs l'étaient depuis l'origine ; d'autres le sont devenues le
# 13/09/2026 en routant neuf modules vers ce masquage — j'ai donc éteint des
# avertissements réels en croyant ne supprimer que du bruit.
#
# Le vocabulaire ci-dessous est **relevé sur le code**, pas imaginé.
# Comparaison insensible à la casse : « Error », « ERREUR » et « erreur »
# passent tous.
#
# LIMITE ASSUMÉE : filtrer sur des sous-chaînes reste une heuristique, pas un
# critère. Le critère juste serait l'intention de l'auteur — une fonction
# distincte pour les traces de mise au point. Il est tenable là où les appels
# se comptent (SpringFull : 9), pas ici où ils dépassent 300. À reconsidérer
# si le bruit réapparaît.
_MOTS_ALERTE = (
    'erreur', 'error', 'avert', 'warning',
    'introuvable', 'not found', 'invalide', 'impossible',
    'échec', 'echec', 'failed', 'refus', 'fallback',
)


def _actif() -> bool:
    """Le masquage est-il levé ? Décidé à CHAQUE APPEL, pas à l'import.

    Corrige une régression du 13/09/2026, introduite le jour même en routant
    neuf modules vers ce masquage partagé : `ORing.py` purge `sys.modules`
    à chaque lancement, mais **sa liste ne contient pas `modules.oring_debug`**.
    Ce module reste donc chargé pour toute la session FreeCAD, et une valeur
    d'ORING_DEBUG relevée à l'import y serait figée — poser
    `os.environ['ORING_DEBUG'] = '1'` puis relancer la macro n'aurait plus
    aucun effet, alors que c'est la manière documentée de rallumer les traces
    (`mecanismes_partages.md` §5).

    Lire l'environnement à chaque appel coûte une recherche dans un
    dictionnaire par ligne supprimée. C'est sans commune mesure avec le coût
    d'une trace qu'on ne sait plus rallumer.
    """
    if ORING_DEBUG:
        return True
    return _os_debug.environ.get('ORING_DEBUG', '') not in (
        '', '0', 'false', 'False')


def print(*args, **kwargs):  # noqa: A001 — masquage intentionnel, voir ci-dessus
    if _actif():
        _builtins_debug.print(*args, **kwargs)
        return
    _texte = args[0] if args else ''
    if isinstance(_texte, str) and any(m in _texte.lower() for m in _MOTS_ALERTE):
        _builtins_debug.print(*args, **kwargs)
