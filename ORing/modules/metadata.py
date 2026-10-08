# Chemin : modules/metadata.py
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

from .i18n import tr
from .oring_debug import print  # noqa: A004 — masquage partage, voir oring_debug.py

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


# NOTE (06/09/2026, action 7 du plan) : une PREMIERE definition de
# trouver_objet() figurait ici, renvoyant un tuple (objet, found_by_name).
# Elle etait morte -- masquee par la definition ci-dessous, chargee ensuite --
# et sa docstring decrivait un contrat que plus aucun appelant n'utilisait.
# Retiree : la version tuple reste disponible sous son vrai nom,
# _trouver_objet_avec_flag().


def trouver_objet(doc, name: str = '', label: str = '',
                  type_id: str = '') -> object:
    """Version simple (rétrocompatible) : retourne l'objet ou None."""
    obj, _ = _trouver_objet_avec_flag(doc, name=name, label=label, type_id=type_id)
    return obj


def _chercher_objet_dans(doc, name: str, label: str, type_id: str):
    """
    Recherche dans UN document : par Name d'abord, puis par Label.

    NOTE (06/09/2026) : plus appelée par _trouver_objet_avec_flag(), qui
    apparie désormais l'ensemble du périmètre via apparier_objet(). Conservée
    telle quelle pour un usage strictement mono-document, où le Name est
    unique et cette règle sans ambiguïté.
    """
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


def apparier_objet(candidats, name: str = '', label: str = '',
                   type_id: str = '', candidats_nom_seul=None):
    """
    Choisit, dans une liste de candidats pouvant provenir de PLUSIEURS
    documents, celui qui correspond au couple (Name, Label) mémorisé.

    POURQUOI (06/09/2026, faux positif signalé par l'utilisateur)
    ------------------------------------------------------------
    `Name` n'est unique QUE dans son document. « Body » est le nom par défaut
    de tout PartDesign::Body : dans un assemblage multi-fichiers, Arbre.FCStd
    et Alesage.FCStd contiennent chacun un objet nommé « Body ». Depuis
    l'Étape A2, les recherches traversent les documents du périmètre ; un
    appariement par Name seul y désigne le premier « Body » rencontré — pas
    forcément le bon. Symptôme : fausse « dérive du diamètre de référence »
    (Ø réf 20.000 → valeur actuelle 19.800), la valeur lue provenant du
    composant voisin.

    Les Labels, eux, sont distincts (« Arbre », « Alesage ») : ils sont le
    discriminant fiable entre documents.

    ORDRE DE PRÉFÉRENCE
      1. Name ET Label concordants — identification certaine ;
      2. Label seul — le Name a changé (objet recréé) ;
      3. Name seul, cherché dans ``candidats_nom_seul`` (par défaut :
         ``candidats``) et accepté seulement s'il y est UNIQUE — cas du
         renommage, comportement historique mono-document. Restreindre cette
         passe au document demandé est ce qui empêche de désigner l'objet
         homonyme d'un autre document.

    Retourne ``(objet, trouve_par_nom)``, ou ``(None, False)``.
    """
    def _filtrer(liste):
        return [o for o in (liste or [])
                if o is not None
                and (not type_id or getattr(o, 'TypeId', '') == type_id)]

    retenus = _filtrer(candidats)

    # 1. Name ET Label
    if name and label:
        for o in retenus:
            if (getattr(o, 'Name', '') == name
                    and getattr(o, 'Label', '') == label):
                return o, True

    # 2. Label seul (l'ordre de `candidats` fait foi : document demandé d'abord)
    if label:
        par_label = [o for o in retenus if getattr(o, 'Label', '') == label]
        if par_label:
            if name:
                for o in par_label:
                    if getattr(o, 'Name', '') == name:
                        return o, True
            return par_label[0], False

    # 3. Name seul, dans le périmètre restreint et seulement s'il y est unique
    if name:
        base = retenus if candidats_nom_seul is None \
            else _filtrer(candidats_nom_seul)
        par_nom = [o for o in base if getattr(o, 'Name', '') == name]
        if len(par_nom) == 1:
            return par_nom[0], True

    return None, False


def _trouver_objet_avec_flag(doc, name: str = '', label: str = '',
                              type_id: str = ''):
    """
    Version interne retournant (objet, found_by_name).

    Balaie `doc` PUIS les documents sources atteints par ses App::Link
    (Étape A2 du support des liens, 06/09/2026 : le LCS et le sketch de gorge
    d'un composant lié vivent dans son document source), et apparie le tout
    par apparier_objet() — (Name, Label) d'abord, Label ensuite, Name seul en
    dernier et dans `doc` uniquement.

    CORRECTIF (06/09/2026) : le repli précédent interrogeait les documents un
    par un, chacun avec la règle « Name d'abord ». Comme « Body » est le nom
    par défaut de tout PartDesign::Body, il pouvait retourner le Body d'un
    AUTRE composant — d'où la fausse dérive de diamètre signalée par
    l'utilisateur. Le comportement mono-document, lui, est inchangé : le
    périmètre s'y réduit à [doc].
    """
    if doc is None:
        return None, False

    candidats = list(getattr(doc, 'Objects', []) or [])
    propres = list(candidats)      # passe 3 : document demandé uniquement

    try:
        from .utils import documents_du_perimetre
        for autre in documents_du_perimetre(doc):
            if autre is doc:
                continue
            candidats.extend(getattr(autre, 'Objects', []) or [])
    except Exception:
        pass

    return apparier_objet(candidats, name=name, label=label,
                          type_id=type_id, candidats_nom_seul=propres)


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
        raise RuntimeError(tr("FreeCAD not available"))

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

# NOTE (04/09/2026) : le suffixe est désormais traduit via tr('equipped')
# au lieu d'être codé en dur en français — voir _nom_conteneur() ci-dessous.
# Ce nom est un simple libellé d'AFFICHAGE (Label du App::Part conteneur),
# jamais relu ni comparé par le programme : trouver_ou_creer_conteneur()
# retrouve un conteneur déjà existant via son TypeId dans InList (voir
# _trouver_part_parent()), jamais par correspondance de nom. La langue
# active au moment de la création n'a donc AUCUNE influence sur le
# déroulement du programme, quelle que soit la langue de l'utilisateur qui
# rouvre le document ensuite (ex. un ensemble créé en italien affichera
# "... equipaggiato" pour un utilisateur français, sans que cela ne perturbe
# rien). Les conteneurs déjà créés avant ce correctif gardent leur nom
# existant tel quel (jamais renommé automatiquement).


def body_oring_de(part, meta: dict = None, doc_repli=None):
    """Retrouve le corps ORing (le tore) d'un joint, **dans son document**.

    Le corps ORing d'un composant lié vit dans le document SOURCE de ce
    composant, pas dans l'assemblage : `doc_actif.getObject(nom)` y rend
    None. La racine correcte est `part.Document` — le Part du joint et son
    corps vivent dans le même document, par construction (le corps est dans
    le `Group` du Part).

    Deux passes, dans cet ordre :

    1. **par le `Name`** stocké dans les métadonnées, cherché dans le
       document du Part ;
    2. **à défaut, par balayage de `part.Group`** — FreeCAD renomme les
       objets au recompute, le `Name` stocké peut être périmé.

    La seconde passe existait déjà, recopiée à l'identique en six endroits ;
    c'est elle qui masquait le défaut de la première partout sauf au
    recolorage du lancement, qui ne l'avait pas.

    Et ce n'est pas seulement une recherche qui échouait : `Name` n'identifie
    que **dans** un document (`mecanismes_partages.md` §6.1 règle 6). Cherché
    dans l'assemblage, un `Name` de composant peut désigner un tout autre
    objet. Enraciner sur `part.Document` ferme les deux cas d'un coup.

    `doc_repli` : document où chercher quand `part` est None ou sans
    document — conserve le comportement des appelants qui tentaient la
    résolution même sans Part.

    Retourne le corps, ou None. **Ne lève jamais.**

    Action A4-a de `plan_action_2026-09-06.md` (11/09/2026).
    """
    doc = getattr(part, 'Document', None) or doc_repli

    if meta is None and part is not None:
        try:
            meta = lire_metadonnees(part)
        except Exception:
            meta = {}

    nom = (meta or {}).get('body_oring_name', '')
    if nom and doc is not None:
        try:
            objet = doc.getObject(nom)
        except Exception:
            objet = None
        if objet is not None:
            return objet

    for enfant in (getattr(part, 'Group', None) or []):
        try:
            if (getattr(enfant, 'TypeId', '') == 'PartDesign::Body'
                    and getattr(enfant, 'Label', '').startswith('ORing')):
                print("[ORing] Body ORing trouvé dans Part.Group : '%s'"
                      % getattr(enfant, 'Name', '?'))
                return enfant
        except Exception:
            continue

    return None


def _nom_conteneur(body_gorge, position: str) -> str:
    """
    Construit le Label du conteneur à partir du Label du body portant la gorge,
    dans la langue active au moment de la création.
    Ex (FR): 'Axe' → 'Axe équipé'   Ex (EN): 'Axe' → 'Axe equipped'
    """
    base = getattr(body_gorge, 'Label', 'Corps') or 'Corps'
    return f"{base} {tr('equipped')}"   # même suffixe arbre/alésage


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

    # Le conteneur doit vivre dans le document du body PORTEUR, qui n'est
    # pas le document actif quand le composant est inséré comme App::Link
    # dans un assemblage multi-fichiers (06/09/2026, spec
    # claude/spec_support_liens_assemblage.md §7). Un App::Part ne peut de
    # toute façon pas contenir un objet d'un autre document.
    # En mono-document, body_gorge.Document EST doc : rien ne change.
    doc = getattr(body_gorge, 'Document', None) or doc

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

    # ── Re-routage des liens (Étape B, 06/09/2026) ──────────────────────
    # Si le corps portant la gorge est référencé par des App::Link (composant
    # inséré dans un assemblage multi-fichiers), ces liens doivent désormais
    # pointer sur le conteneur « ... équipé » — sinon le joint reste invisible
    # dans l'assemblage. Idempotent : un lien déjà routé sur le conteneur est
    # ignoré. Aucun effet en mono-document (aucun lien vers le body).
    # Voir claude/spec_support_liens_assemblage.md §7.
    try:
        _rerouter_liens_vers_conteneur(body_gorge, conteneur, doc)
    except Exception as _e_rr:
        print(f"[ORing liens] re-routage AVERT : {_e_rr}")

    return conteneur


def _rerouter_liens_vers_conteneur(body_gorge, conteneur, doc_source):
    """
    Fait pointer sur `conteneur` tous les liens qui visaient encore
    `body_gorge`, puis remet les liaisons d'assemblage en cohérence.

    Retourne la liste [(lien, etat_origine)] permettant une annulation par
    utils.restaurer_lien().
    """
    from .utils import liens_vers, rerouter_lien, rafraichir_assemblages

    liens = liens_vers(body_gorge)
    if not liens:
        return []

    reroutes = []
    docs_a_rafraichir = [doc_source]
    for lien in liens:
        etat = rerouter_lien(lien, conteneur)
        if etat is not None:
            reroutes.append((lien, etat))
            try:
                if lien.Document not in docs_a_rafraichir:
                    docs_a_rafraichir.append(lien.Document)
            except Exception:
                pass

    if reroutes:
        rafraichir_assemblages(docs_a_rafraichir)
    return reroutes

# =============================================================================
# Détection des Parts ORing existants
# =============================================================================

def _parts_oring_du_document(doc) -> list:
    """Joints ORing d'UN document, sans parcours des liens."""
    if doc is None:
        return []
    return [
        obj for obj in doc.Objects
        if obj.TypeId == 'App::Part'
        and obj.Name.startswith(ORING_PART_PREFIX)
        and hasattr(obj, 'oring_version')
    ]


def lister_parts_oring(doc) -> list:
    """
    Retourne la liste des App::Part dont le nom commence par ORING_PART_PREFIX
    et qui possèdent la propriété oring_version — dans `doc` ET dans les
    documents sources atteints par ses App::Link.

    Correctif du 06/09/2026 (Étape A2 du support des liens) : depuis l'Étape A,
    le joint d'un composant lié est créé dans le document SOURCE du composant.
    Un balayage limité à `doc.Objects` laissait donc l'onglet « joints »
    désespérément vide dans un assemblage multi-fichiers — symptôme rapporté
    par l'utilisateur. Voir claude/spec_support_liens_assemblage.md §6.

    En mono-document, le périmètre se réduit à [doc] : résultat identique à
    l'implémentation précédente, à l'objet près.
    """
    if doc is None:
        return []
    try:
        from .utils import documents_du_perimetre
        docs = documents_du_perimetre(doc)
    except Exception:
        docs = [doc]

    resultat = []
    vus = set()
    for d in docs:
        for part in _parts_oring_du_document(d):
            cle = (d.Name, part.Name)
            if cle in vus:
                continue
            vus.add(cle)
            resultat.append(part)
    return resultat


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

        # Le joint d'un composant lié vit dans le document SOURCE de ce
        # composant (Étape A). On cherche donc d'abord dans le document DU
        # JOINT — le body portant la gorge y est, sans ambiguïté possible.
        #
        # PUIS, en repli, dans le périmètre de l'ASSEMBLAGE. C'est
        # indispensable pour le body COMPLÉMENTAIRE, qui vit dans un
        # troisième fichier : documents_du_perimetre() suit les App::Link
        # SORTANTS, or un document composant n'en a aucun — son périmètre se
        # réduit à lui-même. Seul l'assemblage, qui pointe les deux
        # composants, permet de les atteindre tous les deux.
        # (Correctif du 06/09/2026 : l'enracinement sur le seul document du
        # joint faisait retomber le côté complémentaire à courant=None —
        # dérive de ce côté non détectée, en silence.)
        doc_part = getattr(part, 'Document', None) or doc

        def _resoudre_body(name, label):
            obj = trouver_objet(doc_part, name=name, label=label,
                                type_id='PartDesign::Body')
            if obj is None and doc_part is not doc:
                obj = trouver_objet(doc, name=name, label=label,
                                    type_id='PartDesign::Body')
            return obj

        # Retrouver le body complémentaire — appariement (Name, Label)
        body_comp = _resoudre_body(meta.get('body_comp_name', ''),
                                   meta.get('body_comp_label', ''))

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
            body_gorge = _resoudre_body(meta.get('body_gorge_name', ''),
                                        meta.get('body_gorge_label', ''))
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
            'part':          part,
            'meta':          meta,
            'ref':           ref,
            'courant':       courant_comp,
            'derive':        derive,
            'delta':         delta,
            'delta_comp':    delta_comp,
            'delta_gorge':   delta_gorge,
            # BUGFIX (02/09/2026, signale par l'utilisateur) : necessaires a
            # dialogue._recalculer_apres_derive() pour determiner QUEL cote a
            # reellement derive (comp et/ou gorge) et afficher/agir sur le bon
            # cote au lieu de toujours supposer que seul le comp a change.
            'courant_gorge': courant_gorge,
            'ref_gorge':     ref_gorge,
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