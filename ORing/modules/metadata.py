# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/metadata.py
# -*- coding: utf-8 -*-
"""
ORing/modules/metadata.py

Gestion du App::Part conteneur et des métadonnées de chaque assemblage joint.

Schéma des propriétés personnalisées (groupe "ORing") :
  — Identifiant unique —
    uuid_joint          str   identifiant immuable (ex. "OJ-20260312-214507-a3f2")
  — Contexte —
    oring_version       str   version du schéma (ex. "2.0")
    position            str   "arbre" | "alesage"
    type_montage        str   "statique" | "dynamique_translation" | ...
    pression_bar        float pression max (bar)
    temperature_C       float température max (°C)
    fluide              str   fluide (indicatif)
    plan_esquisse       str   "XZ" | "YZ"
  — Matériau —
    materiau            str   abréviation (ex. "NBR")
  — Joint / Gorge —
    standard            str   ex. "ISO_3601"
    serie               str   ex. "S4"
    d2_mm               float diamètre de corde (mm)
    squeeze_cible_pct   float squeeze saisi (0 = auto)
  — Pièces FreeCAD —
    body_gorge_label    str   Label du body portant la gorge
    body_comp_label     str   Label du body complémentaire
    param_gorge         str   nom du paramètre Ø body gorge
    param_comp          str   nom du paramètre Ø body comp.
    param_gorge_rayon   str   "rayon" | "diametre"
    param_comp_rayon    str   "rayon" | "diametre"
    d_comp_ref_mm       float valeur Ø comp. au moment du calcul (réf. dérive)
    d_gorge_ref_mm      float valeur Ø gorge au moment du calcul (réf. dérive)
    jeu_radial_mm       float jeu radial (mm)
    lcs_label           str   Label du LCS de référence
  — Résultats calculés —
    d1_mm               float d1 joint sélectionné (mm)
    h_mm                float profondeur radiale gorge (mm)
    b_mm                float largeur gorge (mm)
    squeeze_reel_pct    float squeeze réel calculé (%)
    fill_pct            float taux de remplissage (%)
    rayon_gorge_mm      float rayon fond de gorge (mm)

Fonctions principales :
    generer_uuid_joint()              → str   UUID unique immuable
    trouver_part_par_uuid(doc, uuid)  → Part  lookup robuste par UUID
    creer_part_oring(...)             → Part  création avec UUID auto
    lister_parts_oring(doc)           → list  tous les joints du doc
    verifier_derives(doc)             → list  joints dont la géométrie a changé
    detecter_doublon(doc, candidat)   → (bool, Part)
"""

import re
import uuid as _uuid_mod
import datetime

try:
    import FreeCAD as App
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False


# =============================================================================
# Version du schéma — incrémenter si le schéma change
# =============================================================================
ORING_VERSION = "2.0"


# =============================================================================
# Génération d'identifiant unique
# =============================================================================

def generer_uuid_joint() -> str:
    """
    Génère un identifiant unique pour un assemblage joint torique.

    Format : ``OJ-YYYYMMDD-HHMMSS-xxxx``
    Exemple : ``OJ-20260312-214507-a3f2``

    - Préfixe ``OJ`` (O-ring Joint) → filtrage rapide
    - Horodatage lisible (date + heure locale)
    - 4 caractères hexadécimaux aléatoires → unicité même à la même seconde

    L'identifiant est immuable après création : il n'est jamais recalculé
    lors des modifications ultérieures du joint.
    """
    now   = datetime.datetime.now()
    rnd4  = _uuid_mod.uuid4().hex[:4]
    return f"OJ-{now.strftime('%Y%m%d-%H%M%S')}-{rnd4}"

# Préfixe des noms de Part ORing dans le document
ORING_PART_PREFIX = "ORing_"


# =============================================================================
# Nommage
# =============================================================================

def _sanitize(label: str) -> str:
    """Remplace les caractères non alphanumériques par '_'."""
    return re.sub(r'[^A-Za-z0-9]', '_', label)


def trouver_objet(doc, name: str = '', label: str = '',
                  type_id: str = '') -> object:
    """
    Trouve un objet FreeCAD en cherchant d'abord par Name (stable),
    puis par Label si Name absent ou introuvable (rétrocompatibilité).

    Paramètres
    ----------
    doc     : document FreeCAD
    name    : Name interne de l'objet (inchangeable, prioritaire)
    label   : Label visible dans l'arbre (modifiable par l'utilisateur)
    type_id : si non vide, filtre sur TypeId (ex. 'PartDesign::Body')

    Retourne (objet, found_by_name) ou (None, False).
    Utiliser trouver_objet_simple() pour l'API sans tuple.
    """
    if doc is None:
        return None, False

    # 1. Recherche par Name (fiable même après renommage du Label)
    if name:
        obj = doc.getObject(name)
        if obj is not None:
            if not type_id or getattr(obj, 'TypeId', '') == type_id:
                return obj, True

    # 2. Fallback : recherche par Label
    if label:
        for obj in doc.Objects:
            if type_id and getattr(obj, 'TypeId', '') != type_id:
                continue
            if getattr(obj, 'Label', '') == label:
                return obj, False   # trouvé par Label → Name à mettre à jour

    return None, False


def trouver_objet(doc, name: str = '', label: str = '',
                  type_id: str = '') -> object:
    """Version simple (rétrocompatible) : retourne l'objet ou None."""
    obj, _ = _trouver_objet_avec_flag(doc, name=name, label=label, type_id=type_id)
    return obj


def _trouver_objet_avec_flag(doc, name: str = '', label: str = '',
                              type_id: str = ''):
    """Version interne retournant (objet, found_by_name)."""
    if doc is None:
        return None, False
    if name:
        obj = doc.getObject(name)
        if obj is not None:
            if not type_id or getattr(obj, 'TypeId', '') == type_id:
                return obj, True
    if label:
        for obj in doc.Objects:
            if type_id and getattr(obj, 'TypeId', '') != type_id:
                continue
            if getattr(obj, 'Label', '') == label:
                return obj, False
    return None, False


def auto_heal_names(doc, part, meta: dict) -> dict:
    """
    Vérifie que les Names stockés dans meta sont cohérents avec le document.
    Si un objet est retrouvé par Label (Name manquant ou périmé), met à jour
    meta ET les propriétés du Part silencieusement.
    Retourne le meta mis à jour.
    """
    if doc is None or part is None:
        return meta

    updated = {}

    for key_name, key_label, tid in [
        ('body_gorge_name', 'body_gorge_label', 'PartDesign::Body'),
        ('body_comp_name',  'body_comp_label',  'PartDesign::Body'),
        ('lcs_name',        'lcs_label',        ''),
    ]:
        stored_name  = meta.get(key_name, '')
        stored_label = meta.get(key_label, '')
        obj, by_name = _trouver_objet_avec_flag(doc,
                                                 name    = stored_name,
                                                 label   = stored_label,
                                                 type_id = tid)
        if obj is None:
            continue
        current_name  = obj.Name
        current_label = obj.Label

        # Mettre à jour le Name si manquant ou incorrect
        if current_name != stored_name:
            updated[key_name]  = current_name
            updated[key_label] = current_label
            print(f"[ORing heal] '{part.Name}' {key_name}: "
                  f"'{stored_name}' → '{current_name}' "
                  f"(label='{current_label}')")
        # Mettre à jour le Label s'il a changé
        elif current_label != stored_label:
            updated[key_label] = current_label
            print(f"[ORing heal] '{part.Name}' {key_label}: "
                  f"'{stored_label}' → '{current_label}'")

    if updated:
        meta = dict(meta)
        meta.update(updated)
        try:
            ecrire_metadonnees(part, meta)
        except Exception as _e:
            print(f"[ORing heal] écriture meta échouée : {_e}")

    return meta


def nom_part(position: str, lcs_label: str) -> str:
    """
    Construit le nom du App::Part.
    Exemple : "ORing_arbre_LCS_gorge1"
    """
    return f"{ORING_PART_PREFIX}{_sanitize(position)}_{_sanitize(lcs_label)}"


# =============================================================================
# Écriture des propriétés
# =============================================================================

# Définition du schéma : (nom_prop, type_fc, valeur_defaut)
_SCHEMA = [
    # Identifiant unique (immuable après création)
    ("uuid_joint",        "App::PropertyString", ""),
    # Contexte
    ("oring_version",     "App::PropertyString", ""),
    ("position",          "App::PropertyString", ""),
    ("type_montage",      "App::PropertyString", ""),
    ("pression_bar",      "App::PropertyFloat",  0.0),
    ("temperature_C",     "App::PropertyFloat",  20.0),
    ("fluide",            "App::PropertyString", ""),
    ("plan_esquisse",     "App::PropertyString", ""),
    # Matériau
    ("materiau",          "App::PropertyString", ""),
    # Joint / Gorge
    ("standard",          "App::PropertyString", ""),
    ("serie",             "App::PropertyString", ""),
    ("d2_mm",             "App::PropertyFloat",  0.0),
    ("squeeze_cible_pct", "App::PropertyFloat",  0.0),
    # Pièces FreeCAD
    ("body_gorge_label",  "App::PropertyString", ""),
    ("body_gorge_name",   "App::PropertyString", ""),   # Name stable (résistant aux renommages)
    ("body_comp_label",   "App::PropertyString", ""),
    ("body_comp_name",    "App::PropertyString", ""),   # Name stable
    ("param_gorge",       "App::PropertyString", ""),
    ("param_comp",        "App::PropertyString", ""),
    ("param_gorge_rayon", "App::PropertyString", ""),
    ("param_comp_rayon",  "App::PropertyString", ""),
    ("d_comp_ref_mm",     "App::PropertyFloat",  0.0),
    ("d_gorge_ref_mm",    "App::PropertyFloat",  0.0),
    ("jeu_radial_mm",     "App::PropertyFloat",  0.0),
    ("lcs_label",         "App::PropertyString", ""),
    ("lcs_name",          "App::PropertyString", ""),   # Name stable du LCS
    # Résultats
    ("d1_mm",             "App::PropertyFloat",  0.0),
    ("h_mm",              "App::PropertyFloat",  0.0),
    ("b_mm",              "App::PropertyFloat",  0.0),
    ("squeeze_reel_pct",  "App::PropertyFloat",  0.0),
    ("fill_pct",          "App::PropertyFloat",  0.0),
    ("rayon_gorge_mm",    "App::PropertyFloat",  0.0),
    # Grades IT tolérances
    ("it_grade_alesage",  "App::PropertyInteger", 8),
    ("it_grade_gorge",    "App::PropertyInteger", 8),
    # Ajustement ISO 286-1
    ("mode_jeu",          "App::PropertyString",  "manuel"),   # 'manuel' | 'f' | 'g'
    ("lettre_ajustement", "App::PropertyString",  ""),          # 'f' | 'g' | ''
    ("grade_arbre",       "App::PropertyInteger", 7),
]


def _ajouter_proprietes(part):
    """
    Ajoute toutes les propriétés du schéma au Part si elles n'existent pas déjà.
    Idempotent : un double appel ne crée pas de doublon.
    """
    for nom, type_fc, _ in _SCHEMA:
        if not hasattr(part, nom):
            part.addProperty(
                type_fc, nom, "ORing",
                f"ORing — {nom}"
            )


def ecrire_metadonnees(part, meta: dict):
    """
    Écrit le dictionnaire de métadonnées `meta` sur le App::Part.

    Les clés de `meta` correspondent exactement aux noms du schéma.
    Les clés inconnues sont ignorées silencieusement.
    """
    _ajouter_proprietes(part)
    for nom, _, _ in _SCHEMA:
        if nom in meta:
            try:
                setattr(part, nom, meta[nom])
            except Exception as e:
                print(f"[ORing meta] AVERT : impossible d'écrire '{nom}' : {e}")
    # Version toujours forcée à la valeur courante
    part.oring_version = ORING_VERSION


def lire_metadonnees(part) -> dict:
    """
    Lit les métadonnées d'un App::Part ORing et retourne un dict.
    Retourne {} si le Part ne possède pas la propriété oring_version.
    """
    if not hasattr(part, 'oring_version'):
        return {}
    meta = {}
    for nom, _, defaut in _SCHEMA:
        meta[nom] = getattr(part, nom, defaut)
    return meta


# =============================================================================
# Création du App::Part conteneur
# =============================================================================

def creer_part_oring(doc, nom: str, body_oring, meta: dict):
    """
    Crée un App::Part nommé `nom` dans `doc`, y place `body_oring`,
    et écrit toutes les métadonnées.

    Retourne le Part créé.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError("FreeCAD non disponible")

    part = doc.addObject('App::Part', nom)
    part.Label = nom

    # Ajouter le body ORing au Part
    # Retirer de tout parent éventuel avant addObject (FreeCAD peut avoir
    # capturé le body dans le conteneur actif lors de doc.addObject).
    if body_oring is not None:
        for _parent in list(getattr(body_oring, 'InList', [])):
            if getattr(_parent, 'TypeId', '') == 'App::Part':
                try:
                    _parent.removeObject(body_oring)
                except Exception:
                    pass
        part.addObject(body_oring)
        print(f"[ORing meta] body_oring '{body_oring.Label}' ajouté à Part '{part.Label}'")

    # Générer l'UUID si absent (ne jamais écraser un UUID existant)
    meta_finale = dict(meta)
    if not meta_finale.get('uuid_joint'):
        meta_finale['uuid_joint'] = generer_uuid_joint()

    # Écrire les métadonnées
    ecrire_metadonnees(part, meta_finale)

    doc.recompute()
    print(f"[ORing meta] Part '{nom}' créé — uuid={meta_finale['uuid_joint']}")
    return part




# =============================================================================
# Conteneur Part principal (body_gorge + joints ORing)
# =============================================================================

CONTENEUR_SUFFIX_ARBRE   = ' équipé'
CONTENEUR_SUFFIX_ALESAGE = ' équipé'


def _nom_conteneur(body_gorge, position: str) -> str:
    """
    Construit le Label du conteneur à partir du Label du body portant la gorge.
    Ex: 'Axe' → 'Axe équipé'
    """
    base = getattr(body_gorge, 'Label', 'Corps') or 'Corps'
    return base + CONTENEUR_SUFFIX_ARBRE   # même suffixe arbre/alésage


def _trouver_part_parent(obj) -> object:
    """
    Retourne le premier App::Part dans la liste des parents de obj,
    ou None si obj n'est pas encore dans un App::Part.
    """
    for parent in getattr(obj, 'InList', []):
        if getattr(parent, 'TypeId', '') == 'App::Part':
            return parent
    return None


def trouver_ou_creer_conteneur(doc, body_gorge, position: str):
    """
    Trouve ou crée le App::Part conteneur regroupant body_gorge et ses joints.

    - Si body_gorge est déjà dans un App::Part  → retourne ce Part.
    - Sinon crée App::Part "<body.Label> équipé", y place body_gorge,
      et retourne le Part créé.

    Paramètres
    ----------
    doc         : document FreeCAD courant
    body_gorge  : Body portant la gorge (PartDesign::Body)
    position    : 'arbre' ou 'alesage' (non utilisé pour le nom mais
                  conservé pour extension future)

    Retourne le App::Part conteneur.
    """
    if not FREECAD_DISPONIBLE or doc is None or body_gorge is None:
        return None

    # 1. Chercher un App::Part parent existant
    conteneur = _trouver_part_parent(body_gorge)
    if conteneur is not None:
        print(f"[ORing conteneur] body '{body_gorge.Label}' → "
              f"Part existant '{conteneur.Label}'")
        return conteneur

    # 2. Créer un nouveau conteneur
    nom = _nom_conteneur(body_gorge, position)
    conteneur = doc.addObject('App::Part', nom)
    conteneur.Label = nom
    conteneur.addObject(body_gorge)
    doc.recompute()
    print(f"[ORing conteneur] Part '{nom}' créé pour body '{body_gorge.Label}'")
    return conteneur


def rattacher_joint_au_conteneur(doc, part_oring, body_gorge, position: str):
    """
    S'assure que part_oring est enfant du conteneur associé à body_gorge.

    - Trouve ou crée le conteneur via trouver_ou_creer_conteneur().
    - Si part_oring n'est pas déjà dans ce conteneur, l'y ajoute.
    - Retourne le conteneur.

    Cette fonction est idempotente : appelable plusieurs fois sans effet
    de bord si la structure est déjà correcte.
    """
    if not FREECAD_DISPONIBLE or doc is None:
        return None

    conteneur = trouver_ou_creer_conteneur(doc, body_gorge, position)
    if conteneur is None:
        return None

    # Vérifier si part_oring est déjà enfant du conteneur
    deja_present = part_oring in getattr(conteneur, 'Group', [])
    if not deja_present:
        # Retirer part_oring de son éventuel parent actuel avant de le déplacer
        parent_actuel = _trouver_part_parent(part_oring)
        if parent_actuel is not None and parent_actuel != conteneur:
            try:
                parent_actuel.removeObject(part_oring)
                print(f"[ORing conteneur] '{part_oring.Label}' retiré de "
                      f"'{parent_actuel.Label}' (déplacement)")
            except Exception as _e:
                print(f"[ORing conteneur] removeObject échoué : {_e}")
        conteneur.addObject(part_oring)
        print(f"[ORing conteneur] '{part_oring.Label}' → "
              f"conteneur '{conteneur.Label}'")
    else:
        print(f"[ORing conteneur] '{part_oring.Label}' déjà dans "
              f"'{conteneur.Label}' — rien à faire")

    doc.recompute()
    return conteneur

# =============================================================================
# Détection des Parts ORing existants
# =============================================================================

def lister_parts_oring(doc) -> list:
    """
    Retourne la liste des App::Part dont le nom commence par ORING_PART_PREFIX
    et qui possèdent la propriété oring_version.
    """
    if doc is None:
        return []
    return [
        obj for obj in doc.Objects
        if obj.TypeId == 'App::Part'
        and obj.Name.startswith(ORING_PART_PREFIX)
        and hasattr(obj, 'oring_version')
    ]


def trouver_part_par_uuid(doc, uuid_str: str):
    """
    Recherche un App::Part ORing par son ``uuid_joint``.

    Retourne le Part si trouvé, ``None`` sinon.

    Cette fonction est la méthode de référence pour identifier un joint
    de façon robuste, même après renommage de son body ou de son LCS.
    """
    if not uuid_str:
        return None
    for part in lister_parts_oring(doc):
        if getattr(part, 'uuid_joint', '') == uuid_str:
            return part
    return None


def verifier_derives(doc) -> list:
    """
    Pour chaque Part ORing existant, compare d_comp_ref_mm stocké
    avec la valeur courante du paramètre body_comp / param_comp.

    Retourne une liste de dict :
      { 'part': part, 'meta': meta, 'ref': float, 'courant': float,
        'derive': bool, 'delta': float }
    """
    from .utils import lister_parametres_body

    resultats = []
    for part in lister_parts_oring(doc):
        meta = lire_metadonnees(part)
        ref  = meta.get('d_comp_ref_mm', 0.0)

        # Retrouver le body complémentaire — Name d'abord, Label en fallback
        body_comp = trouver_objet(doc,
            name    = meta.get('body_comp_name', ''),
            label   = meta.get('body_comp_label', ''),
            type_id = 'PartDesign::Body')

        # ── Côté complémentaire ─────────────────────────────────────────────
        courant_comp = None
        if body_comp:
            params = lister_parametres_body(body_comp)
            nom_p  = meta.get('param_comp', '')
            val    = params.get(nom_p)
            if val is not None:
                courant_comp = val * 2.0 if meta.get('param_comp_rayon') == 'rayon' else val
        print(f"[ORing derive] part='{part.Name}' comp: nom='{meta.get('param_comp','')}' "
              f"courant={courant_comp} ref={ref}")

        # ── Côté gorge ──────────────────────────────────────────────────────
        ref_gorge  = float(meta.get('d_gorge_ref_mm', 0.0))
        courant_gorge = None
        if ref_gorge > 0:
            body_gorge = trouver_objet(doc,
                name    = meta.get('body_gorge_name', ''),
                label   = meta.get('body_gorge_label', ''),
                type_id = 'PartDesign::Body')
            if body_gorge:
                params_g = lister_parametres_body(body_gorge)
                nom_pg   = meta.get('param_gorge', '')
                val_g    = params_g.get(nom_pg)
                if val_g is not None:
                    courant_gorge = val_g * 2.0 if meta.get('param_gorge_rayon') == 'rayon' else val_g
            print(f"[ORing derive]   gorge: nom='{meta.get('param_gorge','')}' "
                  f"courant={courant_gorge} ref_gorge={ref_gorge}")

        # ── Décision finale : dérive si l'un des deux côtés a changé ───────
        delta_comp  = abs(courant_comp  - ref)        if courant_comp  is not None else None
        delta_gorge = abs(courant_gorge - ref_gorge)  if courant_gorge is not None and ref_gorge > 0 else None

        if delta_comp is not None and delta_gorge is not None:
            delta  = max(delta_comp, delta_gorge)
        elif delta_comp is not None:
            delta  = delta_comp
        else:
            delta  = delta_gorge

        derive = delta is not None and delta > 0.001
        print(f"[ORing derive]   delta_comp={delta_comp} delta_gorge={delta_gorge} "
              f"→ delta={delta} derive={derive}")

        resultats.append({
            'part':         part,
            'meta':         meta,
            'ref':          ref,
            'courant':      courant_comp,
            'derive':       derive,
            'delta':        delta,
            'delta_comp':   delta_comp,
            'delta_gorge':  delta_gorge,
        })

    return resultats


# =============================================================================
# Détection de doublon
# =============================================================================

# Clés comparées pour décider qu'un joint est identique à un existant.
# Deux joints sont doublons si body+LCS+géométrie+calcul sont tous identiques.
_CLES_DOUBLON = [
    'body_gorge_label',   # même pièce porteuse
    'lcs_label',          # même repère → même emplacement physique
    'position',           # arbre / alésage
    'param_gorge',        # paramètre Ø gorge (contexte géométrique)
    'param_comp',         # paramètre Ø complémentaire
]
# standard, serie, d2_mm, squeeze_cible_pct, jeu_radial_mm exclus :
# changer le joint ne change pas l'emplacement physique, c'est toujours un doublon.

# Tolérance pour les comparaisons numériques (mm / %)
_TOL = 1e-6


def _egaux(v1, v2) -> bool:
    """Compare deux valeurs scalaires ou chaînes."""
    if isinstance(v1, float) and isinstance(v2, float):
        return abs(v1 - v2) < _TOL
    return v1 == v2


def detecter_doublon(doc, candidat: dict):
    """
    Vérifie si un joint identique au `candidat` existe déjà dans `doc`.

    `candidat` est un dict avec les mêmes clés que le schéma de métadonnées
    (subset suffisant : les _CLES_DOUBLON).

    Retourne (True, part_existant) si doublon détecté,
    ou       (False, None) sinon.
    """
    for part in lister_parts_oring(doc):
        meta = lire_metadonnees(part)
        if not meta:
            continue
        if all(_egaux(meta.get(k), candidat.get(k)) for k in _CLES_DOUBLON):
            return True, part
    return False, None
