# -*- coding: utf-8 -*-
"""
ORing/modules/materiaux.py
Chargement et requêtes sur la table des matériaux joints toriques.
Testable sans FreeCAD.
"""

import json
import os

# Chemin vers le fichier JSON (relatif à ce module)
_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'materiaux.json')


class ErreurMateriaux(Exception):
    """Exception levée lors d'un problème sur la table matériaux."""
    pass


def _charger_table() -> dict:
    """Charge et retourne le contenu brut du JSON matériaux."""
    chemin = os.path.abspath(_JSON_PATH)
    if not os.path.isfile(chemin):
        raise ErreurMateriaux(f"Fichier matériaux introuvable : {chemin}")
    with open(chemin, 'r', encoding='utf-8') as f:
        return json.load(f)


# Cache en mémoire — chargé une seule fois
_TABLE = None

def _table() -> dict:
    global _TABLE
    if _TABLE is None:
        _TABLE = _charger_table()
    return _TABLE['materiaux']


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def liste_materiaux() -> list[str]:
    """Retourne la liste des abréviations disponibles (ex. ['NBR', 'FKM', ...])."""
    return list(_table().keys())


def get_materiau(abreviation: str) -> dict:
    """
    Retourne le dictionnaire complet d'un matériau.
    Lève ErreurMateriaux si l'abréviation est inconnue.
    """
    t = _table()
    cle = abreviation.upper()
    if cle not in t:
        raise ErreurMateriaux(
            f"Matériau '{abreviation}' inconnu. Disponibles : {list(t.keys())}"
        )
    return t[cle]


def get_plage_temperature(abreviation: str) -> tuple[float, float]:
    """Retourne (T_min_C, T_max_C) pour le matériau donné."""
    m = get_materiau(abreviation)
    return m['temperature']['min_C'], m['temperature']['max_C']


def get_pression_max(abreviation: str) -> float:
    """Retourne la pression maximale en bar."""
    return get_materiau(abreviation)['pression_max_bar']


def get_durete_disponibles(abreviation: str) -> list[int]:
    """Retourne la liste des duretés Shore A disponibles."""
    return get_materiau(abreviation)['durete_shore_A']


def get_durete_standard(abreviation: str) -> int | None:
    """Retourne la dureté Shore A standard recommandée."""
    return get_materiau(abreviation)['durete_standard']


def est_compatible(abreviation: str, fluide: str) -> bool:
    """
    Retourne True si le fluide est dans la liste de compatibilité,
    False s'il est dans la liste d'incompatibilité,
    None si le fluide n'est pas référencé.
    """
    m = get_materiau(abreviation)
    fluide_n = fluide.lower()
    if fluide_n in [f.lower() for f in m['compatibilite']]:
        return True
    if fluide_n in [f.lower() for f in m['incompatibilite']]:
        return False
    return None


def verifier_conditions(abreviation: str,
                        temperature_C: float,
                        pression_bar: float,
                        fluide: str = None) -> dict:
    """
    Vérifie la compatibilité d'un matériau avec les conditions données.

    Retourne un dictionnaire :
    {
        'valide': bool,
        'alertes': [str, ...],   # problèmes bloquants
        'avertissements': [str, ...]  # points d'attention non bloquants
    }
    """
    alertes = []
    avertissements = []

    m = get_materiau(abreviation)
    t_min = m['temperature']['min_C']
    t_max = m['temperature']['max_C']
    p_max = m['pression_max_bar']

    # Température
    if temperature_C < t_min:
        alertes.append(
            f"Température {temperature_C}°C inférieure au minimum {t_min}°C pour {abreviation}"
        )
    elif temperature_C > t_max:
        alertes.append(
            f"Température {temperature_C}°C supérieure au maximum {t_max}°C pour {abreviation}"
        )
    elif temperature_C > t_max * 0.85:
        avertissements.append(
            f"Température {temperature_C}°C proche du maximum {t_max}°C pour {abreviation}"
        )

    # Pression
    if pression_bar > p_max:
        alertes.append(
            f"Pression {pression_bar} bar supérieure au maximum {p_max} bar pour {abreviation}"
        )
    elif pression_bar > p_max * 0.8:
        avertissements.append(
            f"Pression {pression_bar} bar proche du maximum {p_max} bar pour {abreviation}"
        )

    # Fluide
    if fluide:
        compat = est_compatible(abreviation, fluide)
        if compat is False:
            alertes.append(
                f"Fluide '{fluide}' INCOMPATIBLE avec {abreviation}"
            )
        elif compat is None:
            avertissements.append(
                f"Fluide '{fluide}' non référencé pour {abreviation} — vérifier manuellement"
            )

    # Cas spécial PTFE
    if abreviation.upper() == 'PTFE':
        avertissements.append(
            "PTFE : utilisation comme bague anti-extrusion uniquement, pas comme JT dynamique"
        )

    return {
        'valide': len(alertes) == 0,
        'alertes': alertes,
        'avertissements': avertissements
    }


def materiaux_compatibles(temperature_C: float,
                          pression_bar: float,
                          fluide: str = None,
                          exclure_ptfe: bool = True) -> list[str]:
    """
    Retourne la liste des matériaux compatibles avec les conditions données.
    Par défaut, exclut le PTFE (cas spécial).
    """
    resultats = []
    for abrev in liste_materiaux():
        if exclure_ptfe and abrev == 'PTFE':
            continue
        controle = verifier_conditions(abrev, temperature_C, pression_bar, fluide)
        if controle['valide']:
            resultats.append(abrev)
    return resultats


# ---------------------------------------------------------------------------
# Test autonome
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=== Test module materiaux.py ===\n")

    print("Matériaux disponibles :", liste_materiaux())
    print()

    m = get_materiau('NBR')
    print(f"NBR — T° : {get_plage_temperature('NBR')} °C  |  P max : {get_pression_max('NBR')} bar")
    print(f"NBR — Duretés : {get_durete_disponibles('NBR')}  |  Standard : {get_durete_standard('NBR')} Shore A")
    print()

    print("NBR compatible huiles_minérales :", est_compatible('NBR', 'huiles_minérales'))
    print("NBR compatible cétones :", est_compatible('NBR', 'cétones'))
    print("NBR compatible fluide_inconnu :", est_compatible('NBR', 'fluide_inconnu'))
    print()

    r = verifier_conditions('NBR', temperature_C=80, pression_bar=150, fluide='huiles_minérales')
    print("Vérification NBR 80°C / 150 bar / huiles_minérales :")
    print(f"  Valide : {r['valide']}")
    print(f"  Alertes : {r['alertes']}")
    print(f"  Avertissements : {r['avertissements']}")
    print()

    r2 = verifier_conditions('NBR', temperature_C=130, pression_bar=500, fluide='cétones')
    print("Vérification NBR 130°C / 500 bar / cétones :")
    print(f"  Valide : {r2['valide']}")
    print(f"  Alertes : {r2['alertes']}")
    print()

    compatibles = materiaux_compatibles(temperature_C=100, pression_bar=50, fluide='eau_chaude')
    print(f"Matériaux compatibles à 100°C / 50 bar / eau_chaude : {compatibles}")
