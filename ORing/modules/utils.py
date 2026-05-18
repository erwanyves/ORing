# Chemin : modules/utils.py
# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/utils.py
# -*- coding: utf-8 -*-
"""
ORing/modules/utils.py
Fonctions utilitaires partagées — lecture paramètres FreeCAD, gestion Body/LCS,
messages d'erreur, helpers géométriques.
Nécessite FreeCAD (sauf les fonctions marquées # SANS FREECAD).

─── Étape 1a (mars 2026) ────────────────────────────────────────────────────
Ajout de trois fonctions de filtrage :
  lister_bodies_valides_gorge()  — bodies avec LCS + paramètre nommé
  lister_bodies_valides_comp()   — bodies avec paramètre nommé (hors exclusion)
  doc_a_bodies_valides()         — test rapide pour la validation démarrage (1b)
─────────────────────────────────────────────────────────────────────────────
"""

import math

from .i18n import tr

# Import FreeCAD conditionnel — permet les tests partiels hors FreeCAD
try:
    import FreeCAD as App
    import FreeCADGui as Gui
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False


# =============================================================================
# MESSAGES ET DIALOGUES
# =============================================================================

def message_erreur(titre: str, texte: str) -> None:
    """Affiche une boîte d'erreur Qt ou imprime en console selon le contexte."""
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.critical(None, titre, texte)
    else:
        print(f"[ERREUR] {titre} : {texte}")


def message_avertissement(titre: str, texte: str) -> None:
    """Affiche une boîte d'avertissement Qt ou imprime en console."""
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.warning(None, titre, texte)
    else:
        print(f"[AVERT.] {titre} : {texte}")


def message_info(titre: str, texte: str, parent=None) -> None:
    """Affiche une boîte d'information Qt ou imprime en console.

    parent : widget Qt parent — si fourni, la boîte est centrée sur ce widget.
    """
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.information(parent, titre, texte)
    else:
        print(f"[INFO]  {titre} : {texte}")


# =============================================================================
# ACCÈS AU DOCUMENT FREECAD
# =============================================================================

def get_document_actif():
    """
    Retourne le document FreeCAD actif.
    Lève RuntimeError si aucun document n'est ouvert.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError(tr("FreeCAD not available"))
    doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError(tr("Active document not found"))
    return doc


def get_selection() -> list:
    """Retourne la liste des objets actuellement sélectionnés dans FreeCAD."""
    if not FREECAD_DISPONIBLE:
        return []
    return Gui.Selection.getSelection()


# =============================================================================
# BODY ET OBJETS
# =============================================================================

def lister_bodies(doc=None) -> list:
    """
    Retourne la liste de tous les PartDesign::Body du document.
    """
    if not FREECAD_DISPONIBLE:
        return []
    if doc is None:
        doc = get_document_actif()
    return [obj for obj in doc.Objects
            if obj.TypeId == 'PartDesign::Body']


def get_body_selectionne() -> object | None:
    """
    Retourne le premier Body sélectionné, ou None.
    Cherche d'abord dans la sélection active, sinon retourne None.
    """
    if not FREECAD_DISPONIBLE:
        return None
    sel = get_selection()
    for obj in sel:
        if obj.TypeId == 'PartDesign::Body':
            return obj
        # L'objet peut être une feature dans un body
        if hasattr(obj, 'getParent'):
            parent = obj.getParent()
            if parent and parent.TypeId == 'PartDesign::Body':
                return parent
    return None


def lister_lcs(body) -> list:
    """
    Retourne la liste des LCS (Local Coordinate System / PartDesign::CoordinateSystem)
    contenus dans un Body.
    """
    if not FREECAD_DISPONIBLE or body is None:
        return []
    lcs_list = []
    for obj in body.Group:
        if obj.TypeId in ('PartDesign::CoordinateSystem',
                          'App::LocalCoordSys',
                          'PartDesign::Point'):
            lcs_list.append(obj)
    return lcs_list


# =============================================================================
# FILTRAGE DES BODIES (étape 1a)
# =============================================================================

def lister_lcs_libres(body, doc=None) -> list:
    """
    Retourne la liste des LCS du body qui ne sont pas encore occupés
    par un joint ORing existant dans le document.

    Un LCS est considéré "occupé" si ses métadonnées dans un Part ORing
    référencent ce LCS (par label) pour ce body.
    """
    tous = lister_lcs(body)
    if not tous:
        return []
    if not FREECAD_DISPONIBLE or doc is None:
        # Sans doc, impossible de vérifier — retourner tous les LCS
        return tous
    try:
        # Collecter les labels LCS déjà utilisés pour ce body
        from .metadata import lister_parts_oring, lire_metadonnees
        deja_pris = set()
        body_name  = getattr(body, 'Name', '')
        body_label = getattr(body, 'Label', '')
        for part in lister_parts_oring(doc):
            try:
                m = lire_metadonnees(part)
                # Vérifier que ce joint appartient bien à ce body
                if (m.get('body_gorge_name') == body_name
                        or m.get('body_gorge_label') == body_label):
                    lcs_lbl = m.get('lcs_label', '')
                    if lcs_lbl:
                        deja_pris.add(lcs_lbl)
            except Exception:
                pass
        return [lcs for lcs in tous if lcs.Label not in deja_pris]
    except Exception:
        return tous   # En cas d'erreur, retourner tous (pas de faux-négatif)


def lister_bodies_valides_gorge(doc=None) -> list:
    """
    Retourne les bodies utilisables comme pièce portant la GORGE.

    Critères :
      1. Au moins 1 LCS LIBRE (non déjà occupé par un joint ORing existant)
      2. Au moins 1 paramètre nommé (contrainte sketch ou alias spreadsheet)
         excluant les paramètres internes de gorge ORing

    Ces deux conditions garantissent que la macro peut :
      1. Accrocher le sketch au plan XZ d'un LCS disponible
      2. Mettre à jour le diamètre de la pièce via le paramètre nommé

    Un body dont tous les LCS sont déjà utilisés par des joints existants
    n'est PAS proposé (le combo LCS serait vide et la création impossible).
    """
    bodies = lister_bodies(doc)
    resultat = []
    for b in bodies:
        if _est_body_oring(b):
            continue  # exclure les corps ORing générés par la macro
        # Vérifier LCS libres (pas juste LCS existants)
        if not lister_lcs_libres(b, doc):
            continue
        # Vérifier paramètres nommés (hors paramètres internes de gorge)
        if not lister_parametres_body(b):
            continue
        resultat.append(b)
    return resultat


def lister_bodies_valides_comp(doc=None, exclure=None) -> list:
    """
    Retourne les bodies utilisables comme pièce COMPLÉMENTAIRE.

    Critères :
      - au moins 1 paramètre nommé (diamètre ou rayon de la pièce)
      - ne pas être le body déjà sélectionné pour la gorge (exclure)

    Paramètre exclure : objet Body à exclure (None = aucune exclusion).
    """
    bodies = lister_bodies(doc)
    resultat = []
    for b in bodies:
        if exclure is not None and b is exclure:
            continue
        if _est_body_oring(b):
            continue  # exclure les corps ORing générés par la macro (#5)
        if lister_parametres_body(b):
            resultat.append(b)
    return resultat


def doc_a_bodies_valides(doc=None) -> bool:
    """
    Retourne True si le document contient au moins un body apte à recevoir
    une gorge (LCS + paramètre nommé).

    Utilisé par la validation au démarrage (étape 1b) : si False, la macro
    affiche un message d'instruction et se ferme sans modifier le document.
    """
    return len(lister_bodies_valides_gorge(doc)) > 0


# =============================================================================
# PARAMÈTRES NOMMÉS FREECAD
# =============================================================================

# =============================================================================
# FILTRES D'EXCLUSION
# =============================================================================

# Préfixes des noms de contraintes propres aux esquisses de gorge ORing.
# Ces contraintes ne sont PAS des paramètres utilisateur et ne doivent
# pas apparaître dans la liste de sélection du paramètre Ø/R.
# Préfixes des contraintes internes générées par la macro ORing.
# Utilisation en startswith() (insensible à la casse) pour couvrir les
# suffixes numériques que FreeCAD ajoute en cas de doublons : RayonGorge1, etc.
_PREFIXES_CONTRAINTES_GORGE = (
    'rayongorge', 'rayonarbre', 'rayonalesage',
    'fillethautgorge', 'filletfondgorge',
    'depouille', 'demilargeur', 'demilargeurgorge', 'largeurgorge',
)


def _est_contrainte_gorge(nom: str) -> bool:
    """Retourne True si le nom de contrainte appartient aux esquisses de gorge ORing."""
    n = nom.lower().strip()
    return any(n.startswith(p) for p in _PREFIXES_CONTRAINTES_GORGE)


def _est_body_oring(body) -> bool:
    """
    Retourne True si le body est un corps ORing généré par la macro
    (Label commence par 'ORing' OU appartient à un Part dont le Name
    commence par 'ORing_').
    Ces bodies ne doivent pas apparaître dans les listes de sélection.
    """
    if body is None:
        return False
    # Critère 1 : Label du body
    if getattr(body, 'Label', '').startswith('ORing'):
        return True
    # Critère 2 : parent App::Part avec Name commençant par 'ORing_'
    for parent in getattr(body, 'InList', []):
        if (getattr(parent, 'TypeId', '') == 'App::Part'
                and getattr(parent, 'Name', '').startswith('ORing_')):
            return True
    return False


# Types de contraintes dimensionnelles Sketcher
_TYPES_DIMENSIONNELS = {
    'DistanceX', 'DistanceY', 'Distance',
    'Radius', 'Diameter', 'Angle',
}


def lister_parametres_body(body) -> dict:
    """
    Retourne un dictionnaire {nom: valeur_mm} des paramètres nommés
    d'un Body.

    Cherche dans :
    1. Les contraintes nommées de tous les Sketches du body
       (types dimensionnels : DistanceX, DistanceY, Distance, Radius,
        Diameter, Angle)
    2. Les Spreadsheets attachés au body (alias de cellules)
    """
    if not FREECAD_DISPONIBLE or body is None:
        return {}

    params = {}

    for obj in body.Group:

        # ── Sketches ──────────────────────────────────────────────────────
        if obj.TypeId == 'Sketcher::SketchObject':
            try:
                for c in obj.Constraints:
                    # Garder uniquement les contraintes nommées dimensionnelles
                    # Exclure les contraintes internes des esquisses de gorge (#4)
                    if (c.Name
                            and c.Name.strip()
                            and c.Type in _TYPES_DIMENSIONNELS
                            and not _est_contrainte_gorge(c.Name)):
                        # Ne pas écraser un param déjà trouvé dans un autre sketch
                        if c.Name not in params:
                            params[c.Name] = c.Value  # valeur en mm (unités internes)
            except Exception:
                pass  # sketch non initialisé ou corrompu — on passe

        # ── Spreadsheets ──────────────────────────────────────────────────
        elif obj.TypeId == 'Spreadsheet::Sheet':
            try:
                # getContents() renvoie la liste des cellules utilisées
                for cell_addr in obj.getContents():
                    alias = obj.getAlias(cell_addr)
                    if alias:
                        try:
                            val = obj.get(alias)  # lecture par alias
                            if isinstance(val, (int, float)):
                                if alias not in params:
                                    params[alias] = float(val)
                        except Exception:
                            pass
            except Exception:
                pass

    return params


def get_valeur_parametre(body, nom_param: str) -> float | None:
    """
    Retourne la valeur (en mm) d'un paramètre nommé dans un Body.
    Retourne None si le paramètre est introuvable.
    """
    params = lister_parametres_body(body)
    return params.get(nom_param, None)


def set_valeur_parametre(body, nom_param: str, valeur_mm: float) -> bool:
    """
    Met à jour la valeur d'un paramètre nommé dans un Body.
    Cherche d'abord dans les Sketches, puis dans les Spreadsheets.
    Retourne True si la mise à jour a réussi.
    """
    if not FREECAD_DISPONIBLE or body is None:
        return False

    doc = body.Document

    for obj in body.Group:

        # Sketch — contraintes nommées
        if obj.TypeId == 'Sketcher::SketchObject':
            try:
                for i, c in enumerate(obj.Constraints):
                    if c.Name == nom_param:
                        obj.setDatum(i, App.Units.Quantity(f'{valeur_mm} mm'))
                        doc.recompute()
                        return True
            except Exception:
                pass

        # Spreadsheet
        elif obj.TypeId == 'Spreadsheet::Sheet':
            try:
                for cell_addr in obj.getContents():
                    alias = obj.getAlias(cell_addr)
                    if alias == nom_param:
                        obj.set(cell_addr, str(valeur_mm))
                        doc.recompute()
                        return True
            except Exception:
                pass

    return False


# =============================================================================
# GÉOMÉTRIE — PLACEMENT ET LCS  # SANS FREECAD (calculs purs)
# =============================================================================

def rayon_vers_diametre(rayon_mm: float) -> float:
    """Convertit un rayon en diamètre."""
    return rayon_mm * 2.0


def diametre_vers_rayon(diametre_mm: float) -> float:
    """Convertit un diamètre en rayon."""
    return diametre_mm / 2.0


def volume_joint_torique(d1_mm: float, d2_mm: float) -> float:
    """
    Calcule le volume d'un joint torique (mm³).
    V = pi² x (d2/2)² x (d1 + d2) / 2
    """  # SANS FREECAD
    r_corde = d2_mm / 2.0
    r_moyen = (d1_mm + d2_mm) / 2.0
    return math.pi ** 2 * r_corde ** 2 * r_moyen


def dimensions_oblong(d1_mm: float, d2_mm: float,
                      position: str = 'arbre') -> dict:
    """
    Calcule les dimensions de la section oblong du joint torique
    pour la représentation 3D dans FreeCAD.
    Retourne la section au repos (non comprimée).
    """  # SANS FREECAD
    return {
        'largeur'   : d2_mm,
        'hauteur'   : d2_mm,
        'rayon_bout': d2_mm / 2.0,
    }


def placement_plan_median(rayon_piece_mm: float,
                           demi_largeur_gorge_mm: float,
                           position: str = 'arbre') -> dict:
    """
    Calcule le placement du plan médian de la gorge.
    """  # SANS FREECAD
    return {
        'rayon_moyen_gorge': rayon_piece_mm,
        'demi_largeur'     : demi_largeur_gorge_mm,
        'position'         : position,
    }


# =============================================================================
# HELPERS SKETCH FREECAD
# =============================================================================

def creer_sketch_sur_plan(body, plan_nom: str = 'XZ_Plane',
                           nom_sketch: str = 'Sketch'):
    """
    Crée un nouveau Sketch dans un Body, attaché au plan indiqué.
    Retourne l'objet Sketch.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError("FreeCAD non disponible")

    import Sketcher

    sketch = body.newObject('Sketcher::SketchObject', nom_sketch)
    sketch.MapMode = 'FlatFace'

    # Chercher le plan dans les features d'origine du body
    plan = None
    for obj in body.Document.Objects:
        if obj.TypeId == 'App::Origin':
            for feat in obj.OriginFeatures:
                if feat.TypeId == 'App::Plane' and plan_nom in feat.Name:
                    plan = feat
                    break
    if plan is None:
        raise RuntimeError(f"Plan '{plan_nom}' introuvable dans le document")

    sketch.AttachmentSupport = plan
    sketch.AttachmentOffset  = App.Placement()
    body.Document.recompute()
    return sketch


def recompute_document(doc=None) -> None:
    """Recalcule le document FreeCAD actif."""
    if not FREECAD_DISPONIBLE:
        return
    if doc is None:
        doc = get_document_actif()
    doc.recompute()


# =============================================================================
# TEST AUTONOME (hors FreeCAD)
# =============================================================================
if __name__ == '__main__':
    print("=== Test module utils.py (hors FreeCAD) ===\n")

    print(f"FreeCAD disponible : {FREECAD_DISPONIBLE}")
    print()

    print(f"rayon_vers_diametre(15.0) = {rayon_vers_diametre(15.0)} mm")
    print(f"diametre_vers_rayon(30.0) = {diametre_vers_rayon(30.0)} mm")
    print()

    d1, d2 = 29.87, 3.53
    vol = volume_joint_torique(d1, d2)
    print(f"Volume JT d1={d1} / d2={d2} : {vol:.2f} mm3")
    print()

    obl = dimensions_oblong(d1, d2, 'arbre')
    print(f"Section oblong (au repos) : {obl}")
    print()

    placement = placement_plan_median(15.0, 2.5, 'arbre')
    print(f"Placement plan median : {placement}")
    print()

    message_info("Test", "Message d'information (mode console)")
    message_avertissement("Test", "Avertissement (mode console)")

