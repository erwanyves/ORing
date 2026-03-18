# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/sketch_alesage.py
# -*- coding: utf-8 -*-
"""
ORing/modules/sketch_alesage.py

Generation parametrique du sketch de gorge joint torique DANS ALESAGE.

Systeme de coordonnees (plan XZ, axe Z = axe de la piece) :
  - Sketch X  : direction axiale  (= 3D Z quand plan XZ)
  - Sketch Y  : direction radiale (= rayon depuis l'axe Z)
  - Sketch X=0 : plan median de la gorge (axe de symetrie axiale)
  - Revolution autour de V_Axis (sketch X=0) = axe Z en 3D

Difference fondamentale avec arbre :
  La gorge s'ouvre VERS L'EXTERIEUR (r_gorge > r_alesage).

Indices des 10 geometries :
  0  : ligne construction  — repere horizontal bas (RayonAlesage)
  1  : ligne active        — paroi inclinee (depouille)
  2  : ligne active        — fond de gorge (horizontal, y=r_gorge)
  3  : ligne active        — flanc axial (vertical, X=0)
  4  : arc actif           — conge entree gorge (FilletHautGorge)
  5  : point construction  — repere jonction bas/G1
  6  : arc actif           — conge fond gorge (FilletFondGorge)
  7  : point construction  — repere fond
  8  : ligne active        — bord inferieur gorge (horizontal, y=r_alesage)
  9  : ligne construction  — repere arbre (RayonArbre)

Contraintes dimensionnelles nommees :
  demiLargeur       — demi-largeur ligne de construction G0
  demiLargeurGorge  — distance G7 -> axe Y
  RayonGorge        — rayon fond de gorge
  RayonAlesage      — rayon de l'alesage (surface interieure)
  RayonArbre        — rayon de l'arbre (construction)
  FilletHautGorge   — rayon conge entree gorge
  FilletFondGorge   — rayon conge fond gorge
  depouille         — angle de depouille (rad)
"""

import math

try:
    import FreeCAD as App
    import Part
    import Sketcher
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False
    class _Vec:
        def __init__(self, x=0, y=0, z=0): self.x=x; self.y=y; self.z=z
    class App:
        Vector = _Vec
        class Placement: pass
        class Units:
            @staticmethod
            def Quantity(s): return s

from .calcul import ResultatCalcul


# =============================================================================
# Conges proportionnels a d2
# =============================================================================

def _fillet_haut(d2: float) -> float:
    return round(max(0.05, min(0.40, 0.06 * d2)), 3)

def _fillet_fond(d2: float) -> float:
    return round(max(0.05, min(0.25, 0.04 * d2)), 3)


# =============================================================================
# Positions initiales des geometries
# =============================================================================

def _positions_initiales(r_alesage, r_gorge, b2, depouille_rad,
                          f_haut, f_fond):
    """
    Positions initiales EXACTES pour la gorge dans l'alésage.

    La gorge s'ouvre vers l'extérieur (r_gorge > r_alesage).
    La paroi G1 est inclinée (dépouille) de r_alesage (bas, entrée) vers
    r_gorge (haut, fond). Direction paroi : (-sin(dep), cos(dep)).

    Formules exactes des centres (tangence géométrique stricte) :
      cx4 = -b2 - h*tan(dep) - f_haut*(1-sin)/cos   (miroir de sketch_arbre)
      cx6 = -b2 + f_fond*(1-sin)/cos
    avec h = r_gorge - r_alesage

    Angles des arcs (CCW) :
      G4 : 3π/2 → 2π-dep   (tangent à G8 en bas, à G1 en haut-gauche)
      G6 : π/2  → π-dep    (tangent à G2 en haut, à G1 en bas-gauche)
    """
    h  = r_gorge - r_alesage
    s  = math.sin(depouille_rad)
    c  = math.cos(depouille_rad)
    t  = s / c
    k  = (1 - s) / c

    # ── Centres des arcs (formules exactes de tangence) ───────────────────────
    cx4 = -b2 - h * t - f_haut * k   # centre conge haut (entree alesage)
    cy4 = r_alesage + f_haut
    cx6 = -b2 + f_fond * k            # centre conge fond
    cy6 = r_gorge - f_fond

    # ── Angles des arcs ───────────────────────────────────────────────────────
    a4_s = 3 * math.pi / 2            # 270° — tangent à G8 (bas du cercle)
    a4_e = 2 * math.pi - depouille_rad # 360°-dep — tangent à G1
    a6_s = math.pi / 2                 # 90° — tangent à G2 (haut du cercle)
    a6_e = math.pi - depouille_rad    # 180°-dep — tangent à G1

    # ── Points de tangence G1 ─────────────────────────────────────────────────
    # G4 à angle (2π-dep) : center + r*(cos(2π-dep), sin(2π-dep)) = (+cos, -sin)
    # G6 à angle (π-dep)  : center + r*(cos(π-dep),  sin(π-dep))  = (-cos, +sin)
    G1_p1  = App.Vector(cx4 + f_haut * c, cy4 - f_haut * s, 0)
    G1_p2  = App.Vector(cx6 - f_fond  * c, cy6 + f_fond  * s, 0)

    # ── Autres géométries ─────────────────────────────────────────────────────
    dx     = h * t                     # décalage horizontal du fond (dépouille)
    G2_p1  = App.Vector(-(b2 - dx),   r_gorge, 0)
    G2_p2  = App.Vector(0.0,           r_gorge, 0)
    G3_p1  = App.Vector(0.0,  r_gorge,  0)
    G3_p2  = App.Vector(0.0,  r_alesage, 0)
    # G5 : intersection de G1 étendue avec y=r_alesage = -b2 - h*tan(dep)
    G5     = App.Vector(-b2 - h * t,  r_alesage, 0)
    G7     = App.Vector(-b2, r_gorge, 0)
    G8_p1  = App.Vector(cx4, r_alesage, 0)
    G8_p2  = App.Vector(0.0, r_alesage, 0)

    dL0    = 0.5
    G0_p1  = App.Vector(cx4 - dL0, r_alesage, 0)
    G0_p2  = App.Vector(cx4,        r_alesage, 0)

    r_arbre_approx = r_alesage * 0.98
    G9_p1  = App.Vector(cx4 - dL0, r_arbre_approx, 0)
    G9_p2  = App.Vector(0.0,        r_arbre_approx, 0)

    return {
        'G0_p1': G0_p1, 'G0_p2': G0_p2,
        'G1_p1': G1_p1, 'G1_p2': G1_p2,
        'G2_p1': G2_p1, 'G2_p2': G2_p2,
        'G3_p1': G3_p1, 'G3_p2': G3_p2,
        'G4_center': App.Vector(cx4, cy4, 0), 'G4_r': f_haut,
        'G4_a1': a4_s,  'G4_a2': a4_e,
        'G5': G5,
        'G6_center': App.Vector(cx6, cy6, 0), 'G6_r': f_fond,
        'G6_a1': a6_s,  'G6_a2': a6_e,
        'G7': G7,
        'G8_p1': G8_p1, 'G8_p2': G8_p2,
        'G9_p1': G9_p1, 'G9_p2': G9_p2,
    }


# =============================================================================
# Recherche du plan d'esquisse (XZ ou YZ)
# =============================================================================

def _trouver_plan(doc, body, plan_nom: str = 'XZ'):
    tag = plan_nom.upper()
    if body and hasattr(body, 'Origin') and body.Origin:
        for feat in body.Origin.OriginFeatures:
            if feat.TypeId == 'App::Plane' and tag in feat.Name.upper():
                return feat
    for obj in doc.Objects:
        if obj.TypeId == 'App::Origin':
            for feat in obj.OriginFeatures:
                if feat.TypeId == 'App::Plane' and tag in feat.Name.upper():
                    return feat
    return None


# =============================================================================
# Fonction principale
# =============================================================================

def generer_sketch_gorge_alesage(doc,
                                  resultat: ResultatCalcul,
                                  body=None,
                                  lcs=None,
                                  nom_sketch: str = 'GorgeAlesage',
                                  depouille_deg: float = 2.0,
                                  plan: str = 'XZ',
                                  r_arbre_reel: float = None,
                                  suffixe: str = '') -> object:
    """
    Genere le sketch parametrique de gorge dans alesage dans FreeCAD.

    Parametres
    ----------
    doc           : document FreeCAD actif
    resultat      : ResultatCalcul issu de calcul.py
    body          : PartDesign::Body cible (None = premier body disponible)
    lcs           : LCS de reference (None = plan selon 'plan')
    nom_sketch    : nom de l'objet Sketch dans le document
    depouille_deg : angle de depouille en degres (defaut 2 deg)
    plan          : plan d'esquisse — 'XZ' (defaut) ou 'YZ'
    r_arbre_reel  : rayon reel de l'arbre (mm) pour la ligne de construction G9.
                    Si None, estime a r_alesage * 0.97.
                    Passer le diametre de la piece complementaire / 2 depuis
                    le dialogue (cas gorge dans alesage : complementaire = arbre).

    Retourne
    --------
    L'objet Sketcher::SketchObject cree.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError("FreeCAD non disponible")

    # ── Parametres dimensionnels ──────────────────────────────────────────────
    #
    # IMPORTANT — convention rayon_arbre dans ResultatCalcul :
    #   Pour position='alesage', resultat.rayon_arbre = D_arbre/2 (surface de
    #   contact = arbre). Le sketch attend la surface PHYSIQUE de l'alesage =
    #   D_alesage/2 = resultat.d_alesage/2.
    #   La profondeur de gorge h = resultat.h est identique dans les deux repères.
    #
    r_alesage = round(resultat.d_alesage / 2.0, 4)  # surface physique de l'alesage
    r_gorge   = round(resultat.rayon_gorge, 4)       # fond gorge arrondi (issu de calcul.py)
    b2        = round(resultat.b / 2.0, 4)
    d2        = resultat.d2
    dep_rad   = math.radians(depouille_deg)
    f_haut    = _fillet_haut(d2)
    f_fond    = _fillet_fond(d2)

    # Rayon arbre pour la ligne de construction G9
    # r_arbre_reel = D_arbre/2 (passé depuis dialogue), toujours < r_alesage
    if r_arbre_reel is not None and r_arbre_reel < r_alesage:
        r_arbre = r_arbre_reel
    elif hasattr(resultat, 'rayon_arbre_comp') and resultat.rayon_arbre_comp:
        r_arbre = resultat.rayon_arbre_comp
    else:
        r_arbre = round(r_alesage * 0.97, 3)

    # ── Body cible ────────────────────────────────────────────────────────────
    if body is None:
        from .utils import lister_bodies
        bodies = lister_bodies(doc)
        if not bodies:
            raise RuntimeError("Aucun PartDesign::Body dans le document")
        body = bodies[0]

    # ── Creation du sketch ────────────────────────────────────────────────────
    sketch = body.newObject('Sketcher::SketchObject', nom_sketch)

    # Suffixe unique : on utilise le nom interne FreeCAD de l'esquisse
    # (garanti unique dans le document) si aucun suffixe explicite n'est fourni.
    if not suffixe:
        import re as _re_sk
        suffixe = '_' + _re_sk.sub(r'[^A-Za-z0-9]', '_', sketch.Name)


    # ── Attachement ────────────────────────────────────────────────────────
    # Le sketch est concu avec :
    #   sketch X (H) = axial  (DistanceX = demi-largeur b/2)
    #   sketch Y (V) = radial (DistanceY = RayonGorge, RayonArbre...)
    #   revolution autour de H_Axis (ligne Y=0) = axe de la piece
    #
    # Avec ObjectXZ sur le LCS (Z = axe piece) :
    #   H → LCS X (radial),  V → LCS Z (axial)   ← INVERSE par rapport au sketch
    #
    # Correction : AttachmentOffset rotation 90° autour du normal du sketch
    # (normal sketch = LCS -Y avec ObjectXZ).
    # Apres rotation +90° autour du local Z :
    #   H → LCS Z (axial)   ✓   revolution autour H_Axis → LCS Z ✓
    #   V → LCS -X (radial) ✓   DistanceY = rayon depuis axe ✓

    if lcs is not None:
        sketch.AttachmentSupport = [(lcs, '')]
        sketch.MapMode = 'ObjectXZ'
        sketch.AttachmentOffset = App.Placement(
            App.Vector(0, 0, 0),
            App.Rotation(App.Vector(0, 0, 1), 90)  # permute H et V
        )
    else:
        support = _trouver_plan(doc, body, plan)
        if support is None:
            raise RuntimeError(
                f"Plan {plan}_Plane introuvable dans le document"
            )
        sketch.AttachmentSupport = [(support, '')]
        sketch.MapMode = 'FlatFace'
        sketch.AttachmentOffset = App.Placement()

    doc.recompute()

    # ── Geometries ────────────────────────────────────────────────────────────
    pos = _positions_initiales(r_alesage, r_gorge, b2, dep_rad, f_haut, f_fond)

    sketch.addGeometry(Part.LineSegment(pos['G0_p1'], pos['G0_p2']), True)   # G0 construction bas
    sketch.addGeometry(Part.LineSegment(pos['G1_p1'], pos['G1_p2']), False)  # G1 paroi
    sketch.addGeometry(Part.LineSegment(pos['G2_p1'], pos['G2_p2']), False)  # G2 fond
    sketch.addGeometry(Part.LineSegment(pos['G3_p1'], pos['G3_p2']), False)  # G3 flanc axial
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(pos['G4_center'], App.Vector(0, 0, 1), pos['G4_r']),
            pos['G4_a1'], pos['G4_a2']), False)                              # G4 conge entree
    sketch.addGeometry(Part.Point(pos['G5']), True)                          # G5 pt constr.
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(pos['G6_center'], App.Vector(0, 0, 1), pos['G6_r']),
            pos['G6_a1'], pos['G6_a2']), False)                              # G6 conge fond
    sketch.addGeometry(Part.Point(pos['G7']), True)                          # G7 pt constr.
    sketch.addGeometry(Part.LineSegment(pos['G8_p1'], pos['G8_p2']), False)  # G8 bord inf
    sketch.addGeometry(Part.LineSegment(pos['G9_p1'], pos['G9_p2']), True)   # G9 ref arbre

    for _ in range(3):
        doc.recompute()

    # ── Contraintes structurelles ─────────────────────────────────────────────
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 0))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 2, 2, -2))
    sketch.addConstraint(Sketcher.Constraint('Coincident',   3, 1, 2, 2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 3, 2, -2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 5, 1, 0))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 5, 1, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 0, 2, 4, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 1, 4, 2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 7, 1, 1))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 7, 1, 2))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 2, 6, 2))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 2, 1, 6, 1))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 8, 1, 0, 2))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 8, 2, 3, 2))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 8))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 9))
    sketch.addConstraint(Sketcher.Constraint('Vertical', 9, 1, 0, 1))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 9, 2, -2))

    doc.recompute()

    # ── Contraintes dimensionnelles nommees ───────────────────────────────────
    dL0 = 0.5

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceX', 0, 1, 0, 2, dL0))
    sketch.setDatum(idx, App.Units.Quantity(f'{dL0} mm'))
    # (pas de renommage — identique au prototype)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Distance', 7, 1, -2, 0, b2))
    sketch.setDatum(idx, App.Units.Quantity(f'{b2} mm'))
    sketch.renameConstraint(idx, 'demiLargeurGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Angle', 1, 2, 3, 1, dep_rad))
    sketch.setDatum(idx, App.Units.Quantity(f'{depouille_deg} deg'))
    sketch.renameConstraint(idx, 'depouille' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', -1, 1, 3, 2, r_alesage))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_alesage} mm'))
    sketch.renameConstraint(idx, 'RayonAlesage' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', -1, 1, 2, 2, r_gorge))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_gorge} mm'))
    sketch.renameConstraint(idx, 'RayonGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Radius', 4, f_haut))
    sketch.setDatum(idx, App.Units.Quantity(f'{f_haut} mm'))
    sketch.renameConstraint(idx, 'FilletHautGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Radius', 6, f_fond))
    sketch.setDatum(idx, App.Units.Quantity(f'{f_fond} mm'))
    sketch.renameConstraint(idx, 'FilletFondGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', -1, 1, 9, 2, r_arbre))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_arbre} mm'))
    sketch.renameConstraint(idx, 'RayonArbre' + suffixe)

    doc.recompute()

    _rapport(sketch, nom_sketch, resultat, b2, r_gorge, r_alesage, r_arbre,
             f_haut, f_fond, depouille_deg)
    return sketch


# =============================================================================
# Rapport console
# =============================================================================

def _rapport(sketch, nom, r, b2, r_gorge, r_alesage, r_arbre,
             f_haut, f_fond, dep_deg):
    print("=" * 55)
    print(f"SKETCH GORGE ALESAGE : {nom}")
    print("=" * 55)
    print(f"  d1 = {r.d1} mm   d2 = {r.d2} mm")
    print(f"  h  = {r.h:.3f} mm   b  = {r.b:.3f} mm  (b/2 = {b2:.4f})")
    print(f"  RayonAlesage = {r_alesage:.3f} mm")
    print(f"  RayonGorge   = {r_gorge:.3f} mm")
    print(f"  RayonArbre   = {r_arbre:.3f} mm  (construction)")
    print(f"  FilletHaut   = {f_haut:.3f} mm")
    print(f"  FilletFond   = {f_fond:.3f} mm")
    print(f"  Depouille    = {dep_deg} deg")
    print(f"  Geometries   : {len(sketch.Geometry)}")
    print(f"  Contraintes  : {len(sketch.Constraints)}")
    m = len(sketch.MalformedConstraints)
    print(f"  Malformees   : {m}")
    print("  OK Esquisse entierement contrainte" if m == 0
          else f"  ATTENTION {m} contrainte(s) malformee(s)")
    print("=" * 55)


# =============================================================================
# Test autonome (hors FreeCAD)
# =============================================================================
if __name__ == '__main__':
    print("=== Test sketch_alesage.py (hors FreeCAD) ===\n")
    print(f"FreeCAD disponible : {FREECAD_DISPONIBLE}")

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from ORing.modules.calcul import calculer_gorge

    r = calculer_gorge(
        diametre_piece_mm=50.0,  # D_arbre pour gorge dans alesage
        position='alesage',
        type_montage='statique',
        materiau='NBR',
        pression_bar=30,
        temperature_C=60,
        standard='ISO_3601',
    )

    d2        = r.d2
    r_alesage = r.rayon_arbre
    r_gorge   = r.rayon_gorge
    b2        = round(r.b / 2.0, 4)
    dep_rad   = math.radians(2.0)
    f_haut    = _fillet_haut(d2)
    f_fond    = _fillet_fond(d2)

    print(f"Parametres calcules pour D_arbre=50 mm / ISO_3601 :")
    print(f"  d2           = {d2} mm")
    print(f"  r_alesage    = {r_alesage:.3f} mm")
    print(f"  r_gorge      = {r_gorge:.3f} mm  (r_gorge > r_alesage : {r_gorge > r_alesage})")
    print(f"  h            = {r.h:.3f} mm")
    print(f"  b/2          = {b2:.4f} mm")

