# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/calcul.py
# -*- coding: utf-8 -*-
"""
ORing/modules/calcul.py
Moteur de calcul ISO 3601 — dimensionnement complet d'une gorge joint torique.
Testable sans FreeCAD.

Pipeline (conforme feuille de route) :
    0-1  contexte + conditions
    2    matériau
    3-4  d2 + position montage
    5    d1 (table ISO + stretch)
    6    serrage cible
    7    profondeur h
    8    largeur b + fill
    9    risque extrusion
    10   tolérances / surface + variation de serrage
    11   synthèse

─────────────────────────────────────────────────────────────────
CONVENTION ENTRÉES

  position = 'arbre'
    diametre_piece_mm = D_ALESAGE  (diamètre de l'alésage du logement)
    jeu_radial_mm     = jeu radial entre arbre et alésage (0 pour statique)
    D_arbre = D_alesage − 2 × jeu_radial  (calculé en interne)
    → d1 sélectionné pour s'étirer sur D_arbre (stretch = (D_arbre−d1)/d1)
    → rayon_contact   = D_alesage / 2   (surface contre laquelle le joint s'appuie)
    → rayon_gorge     = rayon_contact − h

  position = 'alesage'
    diametre_piece_mm = D_ALESAGE  (diamètre de l'alésage où la gorge est usinée)
    jeu_radial_mm     = jeu radial entre arbre et alésage
    D_arbre = D_alesage − 2 × jeu_radial  (calculé en interne)
    → d1 sélectionné pour compression initiale légère sur D_alesage
    → rayon_contact   = D_alesage / 2   (fond de l'alésage)
    → rayon_gorge     = rayon_contact + h  (gorge taillée vers l'extérieur)
─────────────────────────────────────────────────────────────────
"""

import math
import json
import os
from .materiaux import verifier_conditions, get_durete_standard
from .joints    import (choisir_serie, choisir_d1, get_serie,
                        get_plage_squeeze, get_plage_fill,
                        get_limites_extrusion)

# ===========================================================================
# Chargement des paramètres de calcul depuis parametres_calcul.json
# ===========================================================================
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'parametres_calcul.json')

_PARAMS_CACHE = None

def _params() -> dict:
    global _PARAMS_CACHE
    if _PARAMS_CACHE is None:
        chemin = os.path.abspath(_PARAMS_PATH)
        if not os.path.isfile(chemin):
            raise FileNotFoundError(f"parametres_calcul.json introuvable : {chemin}")
        with open(chemin, 'r', encoding='utf-8') as f:
            _PARAMS_CACHE = json.load(f)
    return _PARAMS_CACHE


# Listes accessibles à l'import (chargées depuis JSON au premier accès)
def _get_list(cle: str) -> list:
    return _params()[cle]

class _ListProxy:
    """Proxy permettant d'utiliser STANDARDS / TYPES_MONTAGE / POSITIONS
    comme de vraies listes tout en restant synchronisé avec le JSON."""
    def __init__(self, cle):        self._cle = cle
    def __iter__(self):             return iter(_get_list(self._cle))
    def __contains__(self, item):   return item in _get_list(self._cle)
    def __len__(self):              return len(_get_list(self._cle))
    def __getitem__(self, i):       return _get_list(self._cle)[i]
    def __repr__(self):             return repr(_get_list(self._cle))

STANDARDS     = _ListProxy('standards_disponibles')
TYPES_MONTAGE = _ListProxy('types_montage')
POSITIONS     = _ListProxy('positions')


# ===========================================================================
# Table ISO 286-1 — chargée depuis parametres_calcul.json
# ===========================================================================

def it_value(diametre_mm: float, grade: int) -> float:
    """
    Retourne la valeur IT (µm) pour un diamètre nominal et un grade ISO 286-1.

    Paramètres
    ----------
    diametre_mm : diamètre nominal (mm)
    grade       : grade IT (6 à 11)

    Retourne
    --------
    IT en µm (float)
    """
    it_cfg = _params()['it_iso286']
    grades = it_cfg['_grades']          # [6, 7, 8, 9, 10, 11]
    if grade not in grades:
        raise ValueError(f"Grade IT{grade} non supporté. Valeurs : {grades}")
    col = grades.index(grade)           # index dans 'valeurs'

    if diametre_mm <= 0:
        raise ValueError("Diamètre doit être > 0")

    for row in it_cfg['table']:
        if row['d_min'] < diametre_mm <= row['d_max']:
            return float(row['valeurs'][col])

    # Hors table : retourner la dernière ligne (extrapolation conservative)
    return float(it_cfg['table'][-1]['valeurs'][col])


# ===========================================================================
# Classe résultat
# ===========================================================================

class ResultatCalcul:
    """Conteneur structuré pour tous les résultats du calcul."""

    def __init__(self):
        # --- Entrées ---
        self.standard        : str   = ''
        self.position        : str   = ''
        self.type_montage    : str   = ''
        self.materiau        : str   = ''
        self.pression_bar    : float = 0.0
        self.temperature_C   : float = 20.0
        self.fluide          : str   = ''
        self.squeeze_cible   : float = 0.0

        # --- Diamètres pièces ---
        self.d_alesage       : float = 0.0   # diamètre alésage (entrée)
        self.d_arbre         : float = 0.0   # diamètre arbre physique
        self.jeu_radial      : float = 0.0   # jeu radial arbre/alésage

        # Compatibilité avec appels existants
        @property
        def diametre_piece(self):
            return self.d_alesage

        # --- Joint sélectionné ---
        self.serie           : str   = ''
        self.d1              : float = 0.0
        self.d2              : float = 0.0
        self.code_joint      : str   = ''
        self.stretch_pct     : float = 0.0

        # --- Gorge calculée ---
        self.squeeze_pct     : float = 0.0
        self.h               : float = 0.0
        self.b               : float = 0.0
        self.fill_pct        : float = 0.0

        # Rayons pour sketch FreeCAD
        # rayon_arbre  = rayon de la surface de contact (alésage pour arbre, arbre pour alésage)
        # rayon_gorge  = rayon du fond de gorge
        self.rayon_arbre     : float = 0.0   # surface de contact joint (≡ D_alesage/2 pour arbre)
        self.rayon_gorge     : float = 0.0   # fond de gorge

        # --- Extrusion ---
        self.risque_extrusion    : str  = 'faible'
        self.bague_antiextrusion : bool = False

        # --- Tolérances ---
        self.ra_recommande   : str   = ''
        self.tolerance_h     : str   = ''
        self.tolerance_b     : str   = ''

        # --- Qualité ---
        self.valide          : bool  = False
        self.alertes         : list  = []
        self.avertissements  : list  = []

    def __repr__(self):
        return (
            f"ResultatCalcul("
            f"D_al={self.d_alesage}, D_arbre={self.d_arbre}, "
            f"d1={self.d1}, d2={self.d2}, h={self.h:.3f}, b={self.b:.3f}, "
            f"squeeze={self.squeeze_pct:.1f}%, fill={self.fill_pct:.1f}%, "
            f"valide={self.valide})"
        )


# ===========================================================================
# Fonction principale
# ===========================================================================

def calculer_gorge(
    diametre_piece_mm  : float,
    position           : str   = 'arbre',
    type_montage       : str   = 'statique',
    materiau           : str   = 'NBR',
    pression_bar       : float = 0.0,
    temperature_C      : float = 20.0,
    fluide             : str   = '',
    standard           : str   = 'ISO_3601',
    serie              : str   = '',
    squeeze_cible_pct  : float = 0.0,
    jeu_radial_mm      : float = 0.0,
) -> ResultatCalcul:
    """
    Calcule toutes les dimensions d'une gorge joint torique.

    Paramètres
    ----------
    diametre_piece_mm : Ø de l'ALÉSAGE dans tous les cas
                        - position='arbre'   → alésage du logement
                        - position='alesage' → alésage où la gorge est usinée
    position          : 'arbre' | 'alesage'
    type_montage      : 'statique' | 'dynamique_translation' | 'dynamique_rotation'
    materiau          : 'NBR' | 'FKM' | 'EPDM' | 'VMQ' | 'FFKM' | 'PTFE'
    pression_bar      : pression de service maximale
    temperature_C     : température de service maximale
    fluide            : fluide en contact (facultatif)
    standard          : 'ISO_3601' | 'DIN_3771' | 'JIS_B2401' | 'METRIC'
    serie             : identifiant série (vide = auto)
    squeeze_cible_pct : serrage cible % (0 = valeur centrale norme)
    jeu_radial_mm     : jeu radial entre arbre et alésage
                        (0 pour statique — utilisé pour D_arbre = D_al − 2×jeu)
    """

    r = ResultatCalcul()
    r.standard      = standard
    r.position      = position
    r.type_montage  = type_montage
    r.materiau      = materiau.upper()
    r.pression_bar  = pression_bar
    r.temperature_C = temperature_C
    r.fluide        = fluide
    r.squeeze_cible = squeeze_cible_pct
    r.jeu_radial    = jeu_radial_mm

    # Diamètres physiques
    r.d_alesage = diametre_piece_mm
    r.d_arbre   = max(0.0, diametre_piece_mm - 2.0 * jeu_radial_mm)

    # ------------------------------------------------------------------
    # Étape 0-1 : validation des entrées
    # ------------------------------------------------------------------
    if position not in POSITIONS:
        r.alertes.append(f"Position '{position}' invalide. Valeurs : {POSITIONS}")
        return r
    if type_montage not in TYPES_MONTAGE:
        r.alertes.append(f"Type '{type_montage}' invalide. Valeurs : {TYPES_MONTAGE}")
        return r
    if standard not in STANDARDS:
        r.alertes.append(f"Standard '{standard}' inconnu. Valeurs : {STANDARDS}")
        return r
    if diametre_piece_mm <= 0:
        r.alertes.append("Diamètre alésage doit être > 0 mm")
        return r

    # ------------------------------------------------------------------
    # Étape 2 : vérification matériau
    # ------------------------------------------------------------------
    ctrl_mat = verifier_conditions(
        r.materiau, temperature_C, pression_bar,
        fluide if fluide else None
    )
    r.alertes        += ctrl_mat['alertes']
    r.avertissements += ctrl_mat['avertissements']

    # ------------------------------------------------------------------
    # Étapes 3-4 : sélection série / d2
    # Utilise le diamètre de référence pour dimensionner d2 :
    #   arbre   → D_arbre (arbre physique, plus petit que l'alésage)
    #   alesage → D_alesage
    # ------------------------------------------------------------------
    d_ref_serie = r.d_arbre if position == 'arbre' else r.d_alesage
    serie_demandee = serie   # mémorise le choix explicite ('' = mode AUTO)
    if not serie:
        serie = choisir_serie(standard, d_ref_serie, pression_bar)
    r.serie = serie

    # ------------------------------------------------------------------
    # Étape 5 : sélection d1
    # arbre   → d1 tel que stretch = (D_arbre − d1)/d1 ≤ 5%
    #           soit d1 ≥ D_arbre / 1.05  ET  d1 ≤ D_arbre
    # alesage → d1 ≥ D_alesage (légère compression initiale)
    #
    # Stratégie :
    #   1. Essayer la série courante.
    #   2. Si stretch > 5%, essayer toutes les autres séries du standard
    #      et retenir celle qui donne le stretch le plus faible ≤ 5%.
    #   3. Si aucune série ne satisfait, garder le meilleur trouvé et
    #      émettre uniquement un avertissement (non bloquant), sauf si
    #      le stretch dépasse 8% (alerte bloquante).
    # ------------------------------------------------------------------
    from .joints import liste_series as _liste_series

    # Référence pour la sélection de d1 :
    #
    #   Gorge ARBRE : le joint s'étire SUR LE FOND DE GORGE (D_fond).
    #     D_fond = D_arbre − 2×h,  avec h = d2 × (1 − squeeze/100)
    #     → d1 ≈ D_fond / 1.03  (stretch 3 % cible, plage 0–5 %)
    #     ISO 3601 / Parker O-Ring Handbook §3.3
    #
    #   Gorge ALÉSAGE : le joint subit une légère compression radiale
    #     initiale, d1 ≥ D_arbre  (compression 0–3 %).
    #
    # Pour gorge arbre, on pré-calcule D_fond en utilisant le squeeze
    # cible (ou la valeur par défaut du type de montage) et le d2 déjà
    # connu (issu de choisir_serie). Le squeeze sera recalculé
    # formellement à l'étape 6 — cette pré-calc ne sert qu'à d_ref_d1.
    if position == 'arbre':
        # d2 de la série déjà choisie (avant que r.d2 soit assigné)
        _d2_serie    = get_serie(standard, serie)['d2_nominal']
        _plage_sq_d1 = get_plage_squeeze(type_montage)
        _sq_d1       = squeeze_cible_pct if squeeze_cible_pct > 0 else _plage_sq_d1['cible']
        _h_d1        = _d2_serie * (1.0 - _sq_d1 / 100.0)
        d_ref_d1     = round(r.d_arbre - 2.0 * _h_d1, 6)   # = D_fond
    else:
        # Alésage : d1 vs D_arbre (compression initiale 0–3%)
        d_ref_d1 = r.d_arbre

    res_d1   = choisir_d1(standard, serie, d_ref_d1, position)

    # Recherche dans les autres séries si le stretch est hors limite
    _sg = _params()['stretch_global']
    STRETCH_MAX_BLOQUANT = _sg['max_bloquant']   # au-delà → alerte bloquante
    STRETCH_MAX_CIBLE    = _sg['max_cible']       # objectif

    # Correction automatique de série UNIQUEMENT en mode AUTO (serie_demandee == '').
    # Si l'utilisateur a explicitement choisi une série, on la respecte même si
    # le d1 optimal est en dehors de la plage — on émet un avertissement seulement.
    if not res_d1['valide'] and position == 'arbre' and not serie_demandee:
        toutes_series = _liste_series(standard)
        meilleur = res_d1
        for s in toutes_series:
            if s == serie:
                continue
            candidat = choisir_d1(standard, s, d_ref_d1, position)
            # Préférer le candidat si valide
            if candidat['valide'] and not meilleur['valide']:
                meilleur = candidat
                meilleur['_serie_override'] = s
                break
            # Sinon : préférer uniquement si stretch positif ET plus faible
            stretch_c = candidat['stretch_pct']
            stretch_m = meilleur['stretch_pct']
            if (not meilleur['valide']
                    and 0.0 <= stretch_c
                    and stretch_c < max(stretch_m, STRETCH_MAX_BLOQUANT)):
                meilleur = candidat
                meilleur['_serie_override'] = s

        if meilleur is not res_d1:
            serie_originale = serie
            serie = meilleur.get('_serie_override', serie)
            r.serie = serie
            res_d1  = meilleur
            r.avertissements.append(
                f"Série auto-corrigée {serie_originale} → {serie} "
                f"pour satisfaire stretch ≤ {STRETCH_MAX_CIBLE}%"
            )

    r.d1          = res_d1['d1']
    r.d2          = res_d1['d2']
    r.code_joint  = res_d1.get('code') or ''
    r.stretch_pct = res_d1['stretch_pct']

    for a in res_d1.get('alertes', []):
        if '> 5%' in a:
            if r.stretch_pct > STRETCH_MAX_BLOQUANT:
                # Vraiment trop grand : alerte bloquante
                r.alertes.append(a)
            else:
                # Entre 5% et 8% : avertissement seulement
                r.avertissements.append(
                    f"Stretch {r.stretch_pct:.1f}% légèrement > {STRETCH_MAX_CIBLE}% "
                    f"(acceptable jusqu'à {STRETCH_MAX_BLOQUANT}% — vérifier le montage)"
                )
        else:
            r.avertissements.append(a)

    # ------------------------------------------------------------------
    # Étape 6 : serrage (squeeze) cible
    # ------------------------------------------------------------------
    plage_sq = get_plage_squeeze(type_montage)
    if squeeze_cible_pct == 0:
        squeeze = plage_sq['cible']
    else:
        squeeze = squeeze_cible_pct
        if squeeze < plage_sq['min']:
            r.alertes.append(
                f"Squeeze {squeeze:.1f}% < minimum recommandé "
                f"{plage_sq['min']}% pour '{type_montage}'"
            )
        elif squeeze > plage_sq['max']:
            r.alertes.append(
                f"Squeeze {squeeze:.1f}% > maximum recommandé "
                f"{plage_sq['max']}% pour '{type_montage}'"
            )
    r.squeeze_pct = squeeze

    # ------------------------------------------------------------------
    # Étape 7 : profondeur radiale h = d2 × (1 − squeeze/100)
    # ------------------------------------------------------------------
    h = r.d2 * (1.0 - squeeze / 100.0)
    r.h = round(h, 3)

    # ------------------------------------------------------------------
    # Étape 8 : largeur b et taux de remplissage
    # ------------------------------------------------------------------
    plage_fill   = get_plage_fill(type_montage)
    fill_cible   = (plage_fill['min'] + plage_fill['max']) / 2.0
    section_joint = math.pi * (r.d2 / 2.0) ** 2
    b_min         = section_joint / (h * plage_fill['max'] / 100.0)
    _bp = _params()['b_pratique']
    coeff_b = _bp.get(type_montage, _bp.get('dynamique_translation', 1.55))
    b_pratique    = coeff_b * r.d2
    b = max(b_min, b_pratique)
    b = math.ceil(b / 0.05) * 0.05
    r.b = round(b, 3)

    fill_reel  = section_joint / (r.b * h) * 100.0
    r.fill_pct = round(fill_reel, 1)

    if fill_reel > plage_fill['max']:
        r.alertes.append(
            f"Fill {fill_reel:.1f}% > {plage_fill['max']}% max "
            f"(gorge trop étroite) — augmenter b"
        )
    elif fill_reel < plage_fill['min']:
        r.avertissements.append(
            f"Fill {fill_reel:.1f}% < {plage_fill['min']}% min "
            f"(gorge trop large) — réduire b si possible"
        )

    # ------------------------------------------------------------------
    # Rayons pour sketch FreeCAD
    # rayon_arbre = rayon de la SURFACE DE CONTACT du joint
    #   arbre   → surface alésage = D_alesage/2
    #   alesage → surface arbre   = D_arbre/2
    # rayon_gorge = fond de la gorge
    # ------------------------------------------------------------------
    if position == 'arbre':
        # Gorge sur l'arbre, joint écrasé contre l'alésage
        r.rayon_arbre = round(r.d_alesage / 2.0, 4)
        r.rayon_gorge = round(r.rayon_arbre - h,  4)
    else:
        # Gorge dans l'alésage, joint écrasé contre l'arbre
        r.rayon_arbre = round(r.d_arbre   / 2.0, 4)
        r.rayon_gorge = round(r.d_alesage / 2.0 + h, 4)

    # Arrondi du fond de gorge au 0.1 mm (diamètre = 2 × rayon_gorge)
    # Arrondir rayon_gorge au 0.05 mm → diamètre arrondi au 0.1 mm
    r.rayon_gorge = round(r.rayon_gorge / 0.05) * 0.05

    # ------------------------------------------------------------------
    # Étape 9 : risque extrusion
    # ------------------------------------------------------------------
    limites = get_limites_extrusion(type_montage)
    if pression_bar >= limites['bague_obligatoire']:
        r.risque_extrusion    = 'critique'
        r.bague_antiextrusion = True
        r.alertes.append(
            f"Pression {pression_bar} bar ≥ {limites['bague_obligatoire']} bar "
            f"→ bague anti-extrusion OBLIGATOIRE"
        )
    elif pression_bar >= limites['critique']:
        r.risque_extrusion    = 'critique'
        r.bague_antiextrusion = True
        r.avertissements.append(
            f"Pression {pression_bar} bar ≥ {limites['critique']} bar "
            f"→ bague anti-extrusion fortement recommandée"
        )
    elif pression_bar >= limites['attention']:
        r.risque_extrusion = 'attention'
        r.avertissements.append(
            f"Pression {pression_bar} bar ≥ {limites['attention']} bar "
            f"→ surveiller le jeu radial et la dureté (≥ 80 Shore A conseillé)"
        )

    durete_std = get_durete_standard(r.materiau)
    if durete_std and pression_bar > 50 and durete_std < 80:
        r.avertissements.append(
            f"Dureté standard {durete_std} Shore A — "
            f"envisager 80 ou 90 Shore A à {pression_bar} bar"
        )

    # ------------------------------------------------------------------
    # Étape 10 : tolérances indicatives (ISO 3601-2 / règles usuelles)
    # ------------------------------------------------------------------
    if type_montage == 'statique':
        _tol = _params()['tolerances_gorge']['statique']
        r.ra_recommande = 'Ra ≤ 1.6 µm'
        r.tolerance_h   = f'+0.000 / -{round(h * _tol["h_coeff_inf"], 3):.3f} mm ({_tol["qualite_h"]} indicatif)'
        r.tolerance_b   = f'+{round(b * _tol["b_coeff_sup"], 3):.3f} / -0.000 mm ({_tol["qualite_b"]} indicatif)'
    else:
        _tol = _params()['tolerances_gorge']['dynamique']
        r.ra_recommande = 'Ra ≤ 0.4 µm (surface en mouvement)'
        r.tolerance_h   = f'+0.000 / -{round(h * _tol["h_coeff_inf"], 3):.3f} mm ({_tol["qualite_h"]} indicatif)'
        r.tolerance_b   = f'+{round(b * _tol["b_coeff_sup"], 3):.3f} / -0.000 mm ({_tol["qualite_b"]} indicatif)'

    # ------------------------------------------------------------------
    # Étape 11 : conclusion
    # ------------------------------------------------------------------
    r.valide = len(r.alertes) == 0

    return r


# ===========================================================================
# Écarts ISO 286-1 — ajustements H/f et H/g
# ===========================================================================

# Écarts fondamentaux "es" (µm) pour les qualités f et g
# Source : ISO 286-1:2010, tableau des écarts fondamentaux
# Colonnes : (d_min_exclu, d_max_inclu, es_f, es_g)
_ECARTS_FONDAMENTAUX = [
    (   0,    3,   -6,   -2),
    (   3,    6,  -10,   -4),
    (   6,   10,  -13,   -5),
    (  10,   18,  -16,   -6),
    (  18,   30,  -20,   -7),
    (  30,   50,  -25,   -9),
    (  50,   80,  -30,  -10),
    (  80,  120,  -36,  -12),
    ( 120,  180,  -43,  -14),
    ( 180,  250,  -50,  -15),
    ( 250,  315,  -56,  -17),
    ( 315,  400,  -62,  -18),
    ( 400,  500,  -68,  -20),
]


def ecarts_arbre(diametre_mm: float, lettre: str, grade: int) -> dict:
    """
    Retourne les écarts de l'arbre (f ou g) et de l'alésage H associé.

    Paramètres
    ----------
    diametre_mm : diamètre nominal de l'ajustement (mm)
    lettre      : 'f' ou 'g'
    grade       : grade IT de l'arbre (6–9) ; l'alésage prend grade+1

    Retourne
    --------
    dict {
        'designation'   : str    ex. 'H7/g6'
        'es_arbre_µm'   : float  écart supérieur arbre (négatif)
        'ei_arbre_µm'   : float  écart inférieur arbre (négatif)
        'EI_alesage_µm' : float  0.0
        'ES_alesage_µm' : float  +IT_H (positif)
        'IT_arbre_µm'   : float
        'IT_alesage_µm' : float
        'jeu_min_µm'    : float  jeu minimal garanti  = −es_arbre
        'jeu_max_µm'    : float  jeu maximal          = IT_H − ei_arbre
        'jeu_min_mm'    : float  jeu minimal radial (mm)
        'jeu_max_mm'    : float  jeu maximal radial (mm)
    }
    """
    lettre = lettre.lower()
    if lettre not in ('f', 'g'):
        raise ValueError(f"Lettre '{lettre}' non supportée. Valeurs : f, g")
    if grade not in range(6, 10):
        raise ValueError(f"Grade {grade} hors plage (6–9)")

    es_µm = None
    for d_min, d_max, ef, eg in _ECARTS_FONDAMENTAUX:
        if d_min < diametre_mm <= d_max:
            es_µm = ef if lettre == 'f' else eg
            break
    if es_µm is None:
        es_µm = _ECARTS_FONDAMENTAUX[-1][2 if lettre == 'f' else 3]

    IT_arbre   = it_value(diametre_mm, grade)
    IT_alesage = it_value(diametre_mm, grade + 1)

    es  = float(es_µm)
    ei  = es - IT_arbre          # µm, négatif
    EI  = 0.0
    ES  = IT_alesage             # µm, positif

    # Jeu diamétral (µm) → radial (mm)
    jeu_min = -es               # µm, jeu garanti minimum
    jeu_max = ES - ei           # µm, jeu maximal
    jeu_min_mm = jeu_min / 2000.0
    jeu_max_mm = jeu_max / 2000.0

    return {
        'designation'   : f"H{grade + 1}/{lettre}{grade}",
        'lettre'        : lettre,
        'grade_arbre'   : grade,
        'grade_alesage' : grade + 1,
        'es_arbre_µm'   : es,
        'ei_arbre_µm'   : ei,
        'EI_alesage_µm' : EI,
        'ES_alesage_µm' : ES,
        'IT_arbre_µm'   : IT_arbre,
        'IT_alesage_µm' : IT_alesage,
        'jeu_min_µm'    : jeu_min,
        'jeu_max_µm'    : jeu_max,
        'jeu_min_mm'    : jeu_min_mm,
        'jeu_max_mm'    : jeu_max_mm,
    }


# ===========================================================================
# Calcul de variation de serrage selon tolérances
# ===========================================================================

def calculer_variation_serrage(
    resultat          : ResultatCalcul,
    it_grade_alesage  : int   = 8,     # Grade IT alésage (8 = IT8 = H8 courant)
    it_grade_gorge    : int   = 8,     # Grade IT fond de gorge (diamètre gorge)
    it_grade_position : int   = 7,     # Grade IT tolérance de position (excentricité)
    excentricite_mm   : float = None,  # Excentricité imposée (mm) — None = calculé depuis IT
) -> dict:
    """
    Calcule la variation de serrage (squeeze) en fonction des tolérances ISO.

    Deux cas analysés :
    ─────────────────────────────────────────────────────────────────────
    CAS 1 — Axes coaxiaux
      La gorge et la surface de contact sont parfaitement concentriques.
      La variation de h vient uniquement des tolérances dimensionnelles :
        h_max = h_nom + (IT_al + IT_gr) / 2    → squeeze minimal
        h_min = h_nom                           → squeeze nominal/maximal
                                                  (tolérances H/h ne permettent pas
                                                   une gorge moins profonde que le nominal)

    CAS 2 — Excentricité maximale
      Les axes sont décalés de e_max.
      Le joint est comprimé de façon non uniforme sur sa circonférence.
      Sur le côté serré  : h_eff = h_min − e_max  → squeeze maximum local
      Sur le côté ouvert : h_eff = h_max + e_max  → squeeze minimum local
      Si squeeze_min_local ≤ 0 : perte de contact → alerte
    ─────────────────────────────────────────────────────────────────────

    Conventions tolerances (ISO 286-1) :
      Alésage  → qualité H : EI = 0,  ES = +IT_al
      Gorge    → qualité h : es = 0,  ei = −IT_gr
      → h peut uniquement augmenter par rapport au nominal (gorge jamais moins profonde)

    Paramètres
    ----------
    resultat          : ResultatCalcul issu de calculer_gorge()
    it_grade_alesage  : grade IT pour l'alésage  (6–11, défaut 8)
    it_grade_gorge    : grade IT pour la gorge   (6–11, défaut 8)
    it_grade_position : grade IT tolérance de position (excentricité calculée)
    excentricite_mm   : excentricité imposée (mm) — si None, calculée depuis IT_position

    Retourne
    --------
    dict {
        'h_nominal'     : float,   # profondeur gorge nominale (mm)
        'd2'            : float,   # diamètre corde (mm)
        'it_alesage_µm' : float,   # IT alésage (µm)
        'it_gorge_µm'   : float,   # IT fond de gorge (µm)
        'it_position_µm': float,   # IT position (µm)
        'delta_h_max_mm': float,   # variation max de h au-dessus du nominal
        'cas1'          : { ... }, # résultats coaxiaux
        'cas2'          : { ... }, # résultats avec excentricité
        'alertes'       : [str],
    }
    """
    alertes = []
    r   = resultat
    h   = r.h
    d2  = r.d2

    # ── Tolérances ISO 286-1 ────────────────────────────────────────────
    # IT alésage : appliqué sur D_alesage
    IT_al  = it_value(r.d_alesage, it_grade_alesage)   # µm
    # IT gorge  : appliqué sur D_gorge_fond = 2 × rayon_gorge
    D_gorge_fond = 2.0 * r.rayon_gorge
    IT_gr  = it_value(D_gorge_fond, it_grade_gorge)     # µm
    # IT position : pour excentricité calculée
    IT_pos = it_value(r.d_alesage, it_grade_position)   # µm

    # Conversion en mm
    IT_al_mm  = IT_al  / 1000.0
    IT_gr_mm  = IT_gr  / 1000.0
    IT_pos_mm = IT_pos / 1000.0

    # ── Variation de h (CAS 1 — coaxial) ──────────────────────────────
    # Avec tolérances H/h (alésage H, gorge h) :
    #   ES_alesage = +IT_al  (bore peut être plus grand)
    #   ei_gorge   = -IT_gr  (gorge peut être plus profonde = D_fond plus petit)
    #   → h peut seulement augmenter par rapport au nominal
    delta_h_max = (IT_al_mm + IT_gr_mm) / 2.0  # en mm (radial = diametral/2)

    h_min_cas1 = h                      # nominal — bore min + gorge nominale
    h_max_cas1 = h + delta_h_max        # bore max + gorge max profondeur

    sq_max_cas1 = (d2 - h_min_cas1) / d2 * 100.0  # = squeeze nominal
    sq_min_cas1 = (d2 - h_max_cas1) / d2 * 100.0

    if sq_min_cas1 < 5.0:
        alertes.append(
            f"Cas 1 : squeeze minimal {sq_min_cas1:.1f}% < 5% — "
            f"risque d'étanchéité insuffisante en pire cas coaxial"
        )

    # ── Excentricité maximale (CAS 2) ─────────────────────────────────
    if excentricite_mm is not None:
        e_max = excentricite_mm
        source_e = f"imposée ({e_max:.3f} mm)"
    else:
        # Excentricité calculée depuis la tolérance de position
        # e_max = IT_position / 2  (la position peut dériver de ±IT/2 sur le rayon)
        e_max = IT_pos_mm / 2.0
        source_e = f"calculée depuis IT{it_grade_position} ({IT_pos:.0f} µm → e={e_max:.3f} mm)"

    # Sur le côté serré  : l'espace est réduit de e_max
    # Sur le côté ouvert : l'espace est augmenté de e_max
    h_min_local = h_min_cas1 - e_max   # pire cas serré
    h_max_local = h_max_cas1 + e_max   # pire cas lâche

    sq_max_local = (d2 - h_min_local) / d2 * 100.0   # côté serré
    sq_min_local = (d2 - h_max_local) / d2 * 100.0   # côté lâche

    contact_perdu = h_max_local >= d2  # h ≥ d2 → joint ne touche plus
    surcompression = h_min_local <= 0  # h ≤ 0 → joint pincé à mort

    if contact_perdu:
        alertes.append(
            f"Cas 2 : perte de contact (h_max_local={h_max_local:.3f} mm ≥ d2={d2} mm) "
            f"— joint non étanche côté excentré"
        )
    elif sq_min_local < 5.0:
        alertes.append(
            f"Cas 2 : squeeze local minimal {sq_min_local:.1f}% < 5% "
            f"côté excentré — étanchéité à vérifier"
        )
    if surcompression:
        alertes.append(
            f"Cas 2 : écrasement total (h_min_local={h_min_local:.3f} mm ≤ 0) "
            f"— joint détruit côté serré"
        )
    elif sq_max_local > 35.0:
        alertes.append(
            f"Cas 2 : squeeze local maximal {sq_max_local:.1f}% > 35% "
            f"côté serré — risque de détérioration accélérée"
        )

    return {
        'h_nominal'      : round(h,         4),
        'd2'             : d2,
        'squeeze_nominal': round(r.squeeze_pct, 2),
        'it_grade_alesage': it_grade_alesage,
        'it_grade_gorge'  : it_grade_gorge,
        'it_alesage_µm'   : IT_al,
        'it_gorge_µm'    : IT_gr,
        'it_position_µm' : IT_pos,
        'delta_h_max_mm' : round(delta_h_max, 4),
        'source_e'       : source_e,
        'e_max_mm'       : round(e_max, 4),

        'cas1': {
            'label'       : 'Axes coaxiaux',
            'h_min'       : round(h_min_cas1,  4),
            'h_max'       : round(h_max_cas1,  4),
            'squeeze_min' : round(sq_min_cas1, 2),
            'squeeze_max' : round(sq_max_cas1, 2),
            'delta_squeeze': round(sq_max_cas1 - sq_min_cas1, 2),
        },

        'cas2': {
            'label'             : 'Excentricité maximale',
            'e_max_mm'          : round(e_max,        4),
            'h_min_local'       : round(h_min_local,  4),
            'h_max_local'       : round(h_max_local,  4),
            'squeeze_min_local' : round(sq_min_local, 2),
            'squeeze_max_local' : round(sq_max_local, 2),
            'delta_squeeze'     : round(sq_max_local - sq_min_local, 2),
            'contact_perdu'     : contact_perdu,
            'surcompression'    : surcompression,
        },

        'alertes': alertes,
    }


def afficher_variation_serrage(v: dict) -> None:
    """Affiche le rapport de variation de serrage."""
    sep = "─" * 58
    print(sep)
    print("VARIATION DE SERRAGE — ANALYSE TOLÉRANCES")
    print(sep)
    print(f"  h nominal         = {v['h_nominal']:.4f} mm")
    print(f"  d2                = {v['d2']} mm")
    print(f"  Squeeze nominal   = {v['squeeze_nominal']:.2f} %")
    print()
    print(f"  IT alésage  IT{v.get('it_grade_alesage','?')} = {v['it_alesage_µm']:.0f} µm  "
          f"→ ±{v['it_alesage_µm']/2000:.4f} mm radial")
    print(f"  IT gorge    IT{v.get('it_grade_gorge','?')} = {v['it_gorge_µm']:.0f} µm  "
          f"→ ±{v['it_gorge_µm']/2000:.4f} mm radial")
    print(f"  Δh max            = +{v['delta_h_max_mm']:.4f} mm  (gorge plus profonde)")
    print()

    c1 = v['cas1']
    print(f"  ┌─ CAS 1 : {c1['label']}")
    print(f"  │  h ∈ [{c1['h_min']:.4f} ; {c1['h_max']:.4f}] mm")
    print(f"  │  Squeeze ∈ [{c1['squeeze_min']:.1f}% ; {c1['squeeze_max']:.1f}%]")
    print(f"  │  Δsqueeze = {c1['delta_squeeze']:.1f} points de %")
    print(f"  └─ {'✅ OK' if c1['squeeze_min'] >= 5 else '⚠ squeeze min trop faible'}")
    print()

    c2 = v['cas2']
    print(f"  ┌─ CAS 2 : {c2['label']}")
    print(f"  │  Excentricité e_max = {c2['e_max_mm']:.4f} mm  ({v['source_e']})")
    print(f"  │  h local ∈ [{c2['h_min_local']:.4f} ; {c2['h_max_local']:.4f}] mm")
    print(f"  │  Squeeze local ∈ [{c2['squeeze_min_local']:.1f}% ; {c2['squeeze_max_local']:.1f}%]")
    print(f"  │  Δsqueeze total = {c2['delta_squeeze']:.1f} points de %")
    etat = []
    if c2['contact_perdu']: etat.append("❌ PERTE DE CONTACT")
    if c2['surcompression']: etat.append("❌ SURCOMPRESSION")
    if not etat:
        if c2['squeeze_min_local'] < 5: etat.append("⚠ squeeze local < 5%")
        else: etat.append("✅ OK")
    print(f"  └─ {' | '.join(etat)}")
    print()

    if v['alertes']:
        print("  ⚠ Alertes :")
        for a in v['alertes']:
            print(f"     • {a}")
    print(sep)


# ===========================================================================
# Affichage synthèse
# ===========================================================================

def afficher_synthese(r: ResultatCalcul) -> None:
    sep = "=" * 60
    print(sep)
    print("SYNTHÈSE CALCUL JOINT TORIQUE")
    print(sep)
    print(f"Standard     : {r.standard}")
    print(f"Position     : {r.position}")
    print(f"Type montage : {r.type_montage}")
    print(f"Matériau     : {r.materiau}")
    print(f"D alésage    : {r.d_alesage} mm  (entrée)")
    print(f"D arbre      : {r.d_arbre} mm  (= D_al − 2×{r.jeu_radial} mm jeu)")
    print(f"Pression     : {r.pression_bar} bar  |  T° : {r.temperature_C}°C")
    if r.fluide:
        print(f"Fluide       : {r.fluide}")
    print()
    print("--- Joint sélectionné ---")
    print(f"Série        : {r.serie}")
    print(f"d1 (int.)    : {r.d1} mm  "
          f"(stretch = {r.stretch_pct:.2f}% sur D_arbre={r.d_arbre} mm)")
    print(f"d2 (corde)   : {r.d2} mm")
    if r.code_joint:
        print(f"Code         : {r.code_joint}")
    print()
    print("--- Gorge calculée ---")
    print(f"Squeeze      : {r.squeeze_pct:.1f} %")
    print(f"h (profond.) : {r.h:.3f} mm")
    print(f"b (largeur)  : {r.b:.3f} mm")
    print(f"Fill         : {r.fill_pct:.1f} %")
    if r.position == 'arbre':
        print(f"R contact    : {r.rayon_arbre:.4f} mm  (= D_alesage/2)")
        print(f"R fond gorge : {r.rayon_gorge:.4f} mm  (= R_contact − h)")
    else:
        print(f"R contact    : {r.rayon_arbre:.4f} mm  (= D_arbre/2)")
        print(f"R fond gorge : {r.rayon_gorge:.4f} mm  (= R_alesage + h)")
    print()
    print("--- Extrusion ---")
    print(f"Risque       : {r.risque_extrusion}")
    print(f"Bague        : {'OUI ⚠' if r.bague_antiextrusion else 'non nécessaire'}")
    print()
    print("--- Tolérances indicatives ---")
    print(f"h            : {r.tolerance_h}")
    print(f"b            : {r.tolerance_b}")
    print(f"Rugosité     : {r.ra_recommande}")
    print()
    if r.alertes:
        print("⛔ ALERTES :")
        for a in r.alertes:
            print(f"   • {a}")
    if r.avertissements:
        print("⚠  Avertissements :")
        for a in r.avertissements:
            print(f"   • {a}")
    print()
    print(f"Résultat : {'✅ VALIDE' if r.valide else '❌ INVALIDE — voir alertes'}")
    print(sep)


# ===========================================================================
# Tests autonomes
# ===========================================================================
if __name__ == '__main__':
    print("\n### IT table — vérification ###")
    for d, g, expected in [(25, 8, 33), (50, 7, 30), (100, 9, 87)]:
        v = it_value(d, g)
        ok = '✅' if v == expected else f'⚠ attendu {expected}'
        print(f"  it_value({d}, IT{g}) = {v:.0f} µm  {ok}")

    print("\n### CAS 1 : gorge sur ARBRE Ø30 (D_alesage=30) / statique / NBR ###")
    r1 = calculer_gorge(
        diametre_piece_mm=30.0,   # D_alesage
        position='arbre',
        type_montage='statique',
        materiau='NBR',
        pression_bar=50,
        temperature_C=60,
        fluide='huiles_minérales',
        standard='ISO_3601',
        jeu_radial_mm=0.0,        # statique → jeu nul
    )
    afficher_synthese(r1)
    v1 = calculer_variation_serrage(r1, it_grade_alesage=8, it_grade_gorge=8)
    afficher_variation_serrage(v1)

    print("\n### CAS 2 : gorge sur ARBRE dynamique translation, jeu=0.05 mm ###")
    r2 = calculer_gorge(
        diametre_piece_mm=50.0,   # D_alesage
        position='arbre',
        type_montage='dynamique_translation',
        materiau='NBR',
        pression_bar=80,
        temperature_C=60,
        standard='ISO_3601',
        jeu_radial_mm=0.05,       # jeu radial 0.05 mm → D_arbre = 49.9
    )
    afficher_synthese(r2)
    v2 = calculer_variation_serrage(
        r2,
        it_grade_alesage=7,
        it_grade_gorge=7,
        excentricite_mm=0.05,     # excentricité mesurée / imposée
    )
    afficher_variation_serrage(v2)

    print("\n### CAS 3 : gorge ALESAGE Ø80 / statique / FKM ###")
    r3 = calculer_gorge(
        diametre_piece_mm=80.0,
        position='alesage',
        type_montage='statique',
        materiau='FKM',
        pression_bar=120,
        temperature_C=150,
        standard='ISO_3601',
        jeu_radial_mm=0.0,
    )
    afficher_synthese(r3)
    v3 = calculer_variation_serrage(r3)
    afficher_variation_serrage(v3)

