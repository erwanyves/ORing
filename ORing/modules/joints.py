# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/joints.py
# -*- coding: utf-8 -*-
"""
ORing/modules/joints.py
Chargement et requêtes sur la table multi-standards joints toriques.
Standards supportés : ISO_3601, DIN_3771, JIS_B2401, METRIC, AS_568
Testable sans FreeCAD.
"""

import json
import os
import math

_JSON_PATH    = os.path.join(os.path.dirname(__file__), '..', 'data', 'joints_standards.json')
_PARAMS_PATH  = os.path.join(os.path.dirname(__file__), '..', 'data', 'parametres_calcul.json')

_PARAMS_CACHE = None

def _charger_params() -> dict:
    chemin = os.path.abspath(_PARAMS_PATH)
    if not os.path.isfile(chemin):
        # Fallback : valeurs ISO par défaut si le fichier est absent
        return {
            'standards_disponibles': ['ISO_3601', 'DIN_3771', 'JIS_B2401', 'METRIC', 'AS_568'],
            'stretch': {
                'arbre':   {'min_accepte': -0.5, 'max_filtre': 6.0, 'max_avertissement': 3.0,
                            'max_acceptable': 5.0, 'cible': 2.0},
                'alesage': {'compression_min': 0.0, 'compression_max': 3.0}
            }
        }
    with open(chemin, 'r', encoding='utf-8') as f:
        return json.load(f)

def _params_calcul() -> dict:
    global _PARAMS_CACHE
    if _PARAMS_CACHE is None:
        _PARAMS_CACHE = _charger_params()
    return _PARAMS_CACHE

# STANDARDS_DISPONIBLES synchronisé avec le JSON (rétrocompatibilité)
class _ListProxy:
    def __init__(self, cle):        self._cle = cle
    def __iter__(self):             return iter(_params_calcul()[self._cle])
    def __contains__(self, item):   return item in _params_calcul()[self._cle]
    def __len__(self):              return len(_params_calcul()[self._cle])
    def __getitem__(self, i):       return _params_calcul()[self._cle][i]
    def __repr__(self):             return repr(_params_calcul()[self._cle])

STANDARDS_DISPONIBLES = _ListProxy('standards_disponibles')


class ErreurJoints(Exception):
    pass


def _charger_table() -> dict:
    chemin = os.path.abspath(_JSON_PATH)
    if not os.path.isfile(chemin):
        raise ErreurJoints(f"Fichier joints introuvable : {chemin}")
    with open(chemin, 'r', encoding='utf-8') as f:
        return json.load(f)


_TABLE = None

def _table() -> dict:
    global _TABLE
    if _TABLE is None:
        _TABLE = _charger_table()
    return _TABLE


# ---------------------------------------------------------------------------
# Navigation dans la table
# ---------------------------------------------------------------------------

def liste_standards() -> list[str]:
    """Retourne la liste des standards disponibles."""
    return list(_table()['standards'].keys())


def get_standard(standard: str) -> dict:
    """Retourne le bloc d'un standard. Lève ErreurJoints si inconnu."""
    s = standard.upper()
    t = _table()['standards']
    if s not in t:
        raise ErreurJoints(
            f"Standard '{standard}' inconnu. Disponibles : {list(t.keys())}"
        )
    return t[s]


def liste_series(standard: str) -> list[str]:
    """Retourne les identifiants de séries d'un standard."""
    return list(get_standard(standard)['series'].keys())


def get_serie(standard: str, serie: str) -> dict:
    """Retourne le bloc d'une série dans un standard."""
    s = get_standard(standard)
    if serie not in s['series']:
        raise ErreurJoints(
            f"Série '{serie}' inconnue dans {standard}. "
            f"Disponibles : {list(s['series'].keys())}"
        )
    return s['series'][serie]


def liste_d2(standard: str) -> list[float]:
    """Retourne la liste des d2 nominaux pour un standard."""
    return [get_serie(standard, s)['d2_nominal']
            for s in liste_series(standard)]


def joints_de_serie(standard: str, serie: str) -> list[dict]:
    """Retourne la liste des joints (avec d1) pour une série donnée."""
    return get_serie(standard, serie)['joints']


# ---------------------------------------------------------------------------
# Sélection automatique de la série selon le contexte
# ---------------------------------------------------------------------------

def choisir_serie(standard: str,
                  diametre_nominal_mm: float,
                  pression_bar: float = 0) -> str:
    """
    Recommande une série dans un standard donné, selon le diamètre et la pression.

    Retourne l'identifiant de série (ex. 'S2', 'M4', 'D2', 'P_S2').
    Stratégie : on cherche la série dont le d2 est le mieux adapté
    à la combinaison diamètre / pression.
    """
    s = get_standard(standard)
    series = s['series']
    d = diametre_nominal_mm
    p = pression_bar

    # Table de recommandation générique par d2 cible
    # Règle : d2 ≈ 10–15 % du diamètre nominal, avec correction pression
    d2_cible = d * 0.12
    if p > 200:
        d2_cible = max(d2_cible, 5.0)
    elif p > 100:
        d2_cible = max(d2_cible, 3.5)
    elif p > 50:
        d2_cible = max(d2_cible, 2.5)

    # On sélectionne la série dont le d2 est le plus proche de la cible
    # tout en vérifiant que d1 demandé est dans la plage de la série
    meilleures = []
    for nom_serie, bloc in series.items():
        d2 = bloc['d2_nominal']
        joints = bloc['joints']
        d1_min = min(j['d1'] for j in joints)
        d1_max = max(j['d1'] for j in joints)
        if d1_min <= d <= d1_max:
            ecart = abs(d2 - d2_cible)
            meilleures.append((ecart, nom_serie))

    if not meilleures:
        # Fallback : série avec le plus grand d1_max
        nom_serie = max(
            series.items(),
            key=lambda kv: max(j['d1'] for j in kv[1]['joints'])
        )[0]
        return nom_serie

    meilleures.sort()
    return meilleures[0][1]


# ---------------------------------------------------------------------------
# Sélection du d1
# ---------------------------------------------------------------------------

def choisir_d1(standard: str,
               serie: str,
               diametre_piece_mm: float,
               position: str = 'arbre') -> dict:
    """
    Sélectionne le d1 optimal pour un diamètre de pièce donné.

    position : 'arbre'   → joint étiré sur le FOND DE GORGE (D_fond)
                           stretch = (D_fond − d1) / d1 × 100, plage 0–5 %
                           Passer diametre_piece_mm = D_fond = D_arbre − 2×h
               'alesage' → légère compression radiale initiale (0–3 %)
                           stretch = (D_arbre − d1) / d1 × 100, plage −3–0 %
                           Passer diametre_piece_mm = D_arbre

    Retourne :
    {
        'd1'          : float,
        'd2'          : float,
        'standard'    : str,
        'serie'       : str,
        'code'        : str | None,   # code normalisé si disponible (JIS)
        'stretch_pct' : float,        # positif = étirement, négatif = compression
        'valide'      : bool,
        'alertes'     : [str]
    }
    """
    alertes = []
    bloc = get_serie(standard, serie)
    d2 = bloc['d2_nominal']
    joints = bloc['joints']

    if not joints:
        raise ErreurJoints(f"Aucun joint dans {standard}/{serie}")

    # Seuils depuis parametres_calcul.json
    _st_cfg = _params_calcul()['stretch']

    if position == 'arbre':
        STRETCH_MAX  = _st_cfg['arbre']['max_filtre']        # filtre sélection (6%)
        STRETCH_MIN  = _st_cfg['arbre']['min_accepte']       # tolérance légère (-0.5%)
        STRETCH_CIBLE = _st_cfg['arbre']['cible']            # valeur cible (2%)
        STRETCH_MAX_ACCEPTABLE = _st_cfg['arbre']['max_acceptable']     # 5%
        STRETCH_MAX_AVERT      = _st_cfg['arbre']['max_avertissement']  # 3%

        def _st(j):
            return (diametre_piece_mm - j['d1']) / j['d1'] * 100

        candidats = [j for j in joints if STRETCH_MIN <= _st(j) <= STRETCH_MAX]
        if candidats:
            joint = min(candidats, key=lambda j: abs(_st(j) - STRETCH_CIBLE))
        else:
            joint = min(joints, key=lambda j: abs(_st(j)))
            alertes.append(
                f"Aucun d1 dans la plage {STRETCH_MIN}–{STRETCH_MAX}% "
                f"pour D_arbre={diametre_piece_mm} mm dans {standard}/{serie}"
            )

    else:  # alesage
        COMPR_MIN = _st_cfg['alesage']['compression_min']   # 0%
        COMPR_MAX = _st_cfg['alesage']['compression_max']   # 3%

        def _cp(j):
            return (j['d1'] - diametre_piece_mm) / j['d1'] * 100

        candidats = [j for j in joints if COMPR_MIN <= _cp(j) <= COMPR_MAX]
        if candidats:
            joint = min(candidats, key=lambda j: _cp(j))
        else:
            joint = min(joints, key=lambda j: abs(_cp(j)))
            alertes.append(
                f"Aucun d1 avec compression {COMPR_MIN}–{COMPR_MAX}% "
                f"pour D_arbre={diametre_piece_mm} mm dans {standard}/{serie}"
            )

    d1 = joint['d1']
    code = joint.get('code', None)
    stretch_pct = round((diametre_piece_mm - d1) / d1 * 100, 2)

    # Contrôle stretch / compression — seuils issus de parametres_calcul.json
    avertissements = []
    if position == 'arbre':
        if stretch_pct > STRETCH_MAX_ACCEPTABLE:
            alertes.append(
                f"Étirement {stretch_pct:.1f}% > {STRETCH_MAX_ACCEPTABLE}% max — "
                f"choisir un d1 plus grand ou une autre série"
            )
        elif stretch_pct > STRETCH_MAX_AVERT:
            avertissements.append(
                f"Étirement {stretch_pct:.1f}% > {STRETCH_MAX_AVERT}% — "
                f"limite dynamique recommandée"
            )
        elif stretch_pct < STRETCH_MIN:
            alertes.append(
                f"d1={d1} mm > D_fond={diametre_piece_mm} mm — série inadaptée"
            )
    else:
        compr = -stretch_pct
        if compr > COMPR_MAX:
            alertes.append(
                f"Compression initiale {compr:.1f}% > {COMPR_MAX}% max pour alésage"
            )

    return {
        'd1'            : d1,
        'd2'            : d2,
        'standard'      : standard,
        'serie'         : serie,
        'code'          : code,
        'stretch_pct'   : stretch_pct,
        'valide'        : len(alertes) == 0,
        'alertes'       : alertes,
        'avertissements': avertissements
    }


# ---------------------------------------------------------------------------
# Recommandations globales
# ---------------------------------------------------------------------------

def get_plage_squeeze(type_montage: str) -> dict:
    """type_montage : 'statique' | 'dynamique_translation' | 'dynamique_rotation'"""
    plages = _table()['plages_squeeze_recommandees']
    if type_montage not in plages:
        raise ErreurJoints(
            f"Type '{type_montage}' inconnu. "
            f"Valeurs : {[k for k in plages if not k.startswith('_')]}"
        )
    return plages[type_montage]


def get_plage_fill(type_montage: str) -> dict:
    """type_montage : 'statique' | 'dynamique' (ou 'dynamique_translation'/'rotation')"""
    plages = _table()['plages_fill_recommandees']
    cle = 'statique' if type_montage == 'statique' else 'dynamique'
    return plages[cle]


def get_limites_extrusion(type_montage: str) -> dict:
    """type_montage : 'statique' | 'dynamique_translation' | 'dynamique_rotation'"""
    limites = _table()['limites_extrusion']
    cle = 'statique_bar' if type_montage == 'statique' else 'dynamique_bar'
    return limites[cle]


# ---------------------------------------------------------------------------
# Test autonome
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=== Test module joints.py — multi-standards ===\n")

    print("Standards disponibles :", liste_standards())
    print()

    for std in liste_standards():
        d2s = liste_d2(std)
        print(f"{std:12s} — séries : {liste_series(std)}")
        print(f"{'':12s}   d2 (mm) : {d2s}")
    print()

    # Test ISO 3601
    s = choisir_serie('ISO_3601', 30.0, 80)
    r = choisir_d1('ISO_3601', s, 30.0, 'arbre')
    print(f"ISO_3601 / Ø30 arbre / 80 bar : série={s} d1={r['d1']} d2={r['d2']} "
          f"stretch={r['stretch_pct']}% valide={r['valide']}")

    # Test DIN 3771
    s = choisir_serie('DIN_3771', 25.0, 50)
    r = choisir_d1('DIN_3771', s, 25.0, 'arbre')
    print(f"DIN_3771 / Ø25 arbre / 50 bar : série={s} d1={r['d1']} d2={r['d2']} "
          f"stretch={r['stretch_pct']}%")

    # Test JIS B2401
    s = choisir_serie('JIS_B2401', 15.0, 30)
    r = choisir_d1('JIS_B2401', s, 15.0, 'arbre')
    print(f"JIS_B2401 / Ø15 arbre / 30 bar : série={s} d1={r['d1']} d2={r['d2']} "
          f"code={r['code']} stretch={r['stretch_pct']}%")

    # Test Métrique catalogue
    s = choisir_serie('METRIC', 30.0, 100)
    r = choisir_d1('METRIC', s, 30.0, 'alesage')
    print(f"METRIC   / Ø30 alésage / 100 bar : série={s} d1={r['d1']} d2={r['d2']} "
          f"stretch={r['stretch_pct']}%")

    print()
    print("Plage squeeze statique :", get_plage_squeeze('statique'))
    print("Plage squeeze dyn. translation :", get_plage_squeeze('dynamique_translation'))
    print("Limites extrusion dynamique :", get_limites_extrusion('dynamique_translation'))
