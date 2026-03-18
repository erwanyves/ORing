# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/sketch_arbre.py
# -*- coding: utf-8 -*-
"""
ORing/modules/sketch_arbre.py

Generation parametrique du sketch de gorge joint torique SUR ARBRE.

Systeme de coordonnees (plan XZ, axe Z = axe de la piece) :
  - Sketch X  : direction axiale  (= 3D Z quand plan XZ)
  - Sketch Y  : direction radiale (= rayon, distance depuis l'axe Z)
  - Sketch X=0 : plan median de la gorge (axe de symetrie axiale)
  - Revolution autour de V_Axis (sketch X=0) = axe Z en 3D

La demi-section va de X=-b/2 (bord gauche de gorge) a X=0 (plan median).
Apres revolution 360 deg, cela cree un anneau. La symetrie par le plan
XY (Mirrored) complete la gorge en -b/2 ... +b/2.

Indices des 10 geometries :
  0  : ligne construction  — repere horizontal haut (RayonArbre)
  1  : ligne active        — paroi inclinee (depouille)
  2  : ligne active        — fond de gorge (horizontal)
  3  : ligne active        — flanc axial (vertical, X=0)
  4  : arc actif           — conge haut gorge
  5  : point construction  — repere jonction haut
  6  : arc actif           — conge fond gorge
  7  : point construction  — repere fond
  8  : ligne active        — bord superieur gorge (horizontal)
  9  : ligne construction  — repere alesage

Contraintes dimensionnelles nommees :
  demiLargeur       — b/2 (demi-largeur construction)
  demiLargeurGorge  — b/2 effectif
  RayonGorge        — rayon fond de gorge
  RayonArbre        — rayon de l'arbre
  RayonAlesage      — rayon de l'alesage (construction)
  FilletHautGorge   — rayon conge haut
  FilletFondGorge   — rayon conge fond
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
# Rayons de conges (proportionnels a d2)
# =============================================================================

def _fillet_haut(d2: float) -> float:
    return round(max(0.05, min(0.40, 0.06 * d2)), 3)

def _fillet_fond(d2: float) -> float:
    return round(max(0.05, min(0.25, 0.04 * d2)), 3)


# =============================================================================
# Positions initiales des geometries
# =============================================================================

def _positions_initiales(r_arbre, r_gorge, demi_largeur,
                          depouille_rad, fillet_haut, fillet_fond):
    """
    Calcule les positions initiales EXACTES de toutes les geometries.

    Formules derivees des conditions de tangence geometrique :

    Gorge arbre — la paroi G1 passe par G7=(-b2, r_gorge) avec direction
    (-sin(dep), cos(dep)). Les arcs G4 (haut) et G6 (bas) sont tangents
    a G1 par construction, ce qui donne :

      cx4 = -b2 - h*tan(dep) - f_haut*(1-sin(dep))/cos(dep)
      cx6 = -b2 + f_fond*(1-sin(dep))/cos(dep)

    Ces formules donnent exactement les valeurs du solveur FreeCAD.
    Des positions exactes evitent toute ambiguite de convergence.
    """
    h   = r_arbre - r_gorge
    b2  = demi_largeur
    s   = math.sin(depouille_rad)
    c   = math.cos(depouille_rad)
    t   = s / c          # tan(dep)
    k   = (1 - s) / c   # (1-sin)/cos

    # ── Centres des arcs (formules exactes depuis tangence avec G1) ──────────
    cx4 = -b2 - h * t - fillet_haut * k   # centre arc conge haut
    cy4 = r_arbre - fillet_haut
    cx6 = -b2 + fillet_fond * k            # centre arc conge fond
    cy6 = r_gorge + fillet_fond

    # ── Points de tangence G1 avec les arcs ──────────────────────────────────
    # G4 start (angle = dep) : center + r*(cos,sin)
    px_th = cx4 + fillet_haut * c
    py_th = cy4 + fillet_haut * s
    # G6 start (angle = π+dep) : center + r*(-cos,-sin)
    px_tf = cx6 - fillet_fond * c
    py_tf = cy6 - fillet_fond * s

    # ── G2 : fond de gorge horizontal, de G6_end a l'axe ─────────────────────
    # G6 end (angle = 3π/2) : center + r*(0,-1)
    G2_x1 = cx6    # = cx6 + 0
    G2_y1 = r_gorge  # = cy6 - f_fond

    # ── G5 : intersection de G1 (extended) avec y=r_arbre ────────────────────
    # G1 passe par G7=(-b2, r_gorge) avec pente tan(dep) en x/y.
    # A y=r_arbre : x = -b2 - h*tan(dep)
    G5_x = -b2 - h * t

    # ── G0 construction : horizontal a r_arbre, longueur = b2/2 ──────────────
    dL0 = 0.5 * b2
    G0_x2 = cx4          # end of G0 = G4_end.x = G8_start.x
    G0_x1 = cx4 - dL0   # start of G0

    # ── G9 construction : reference alesage, aligne avec G0 ──────────────────
    # G9_start sur l'axe Y (x=0), G9_end aligne avec G0_start
    # Hauteur : r_alesage approx = r_arbre + h*0.05 (sera corrige par contrainte)
    r_alesage_approx = r_arbre + max(0.05, h * 0.05)

    return {
        'G0_p1': App.Vector(G0_x1,  r_arbre, 0),
        'G0_p2': App.Vector(G0_x2,  r_arbre, 0),
        'G1_p1': App.Vector(px_th,  py_th,   0),
        'G1_p2': App.Vector(px_tf,  py_tf,   0),
        'G2_p1': App.Vector(G2_x1,  r_gorge, 0),
        'G2_p2': App.Vector(0.0,    r_gorge, 0),
        'G3_p1': App.Vector(0.0,    r_gorge, 0),
        'G3_p2': App.Vector(0.0,    r_arbre, 0),
        'G4_center': App.Vector(cx4, cy4, 0),
        'G4_r': fillet_haut,
        'G4_a1': depouille_rad,
        'G4_a2': math.pi / 2,
        'G5':   App.Vector(G5_x,    r_arbre, 0),
        'G6_center': App.Vector(cx6, cy6, 0),
        'G6_r': fillet_fond,
        'G6_a1': math.pi + depouille_rad,
        'G6_a2': 3 * math.pi / 2,
        'G7':   App.Vector(-b2,     r_gorge, 0),
        'G8_p1': App.Vector(G0_x2,  r_arbre, 0),
        'G8_p2': App.Vector(0.0,    r_arbre, 0),
        'G9_p1': App.Vector(0.0,    r_alesage_approx, 0),
        'G9_p2': App.Vector(G0_x1,  r_alesage_approx, 0),
    }


# =============================================================================
# Recherche du plan d'esquisse (XZ ou YZ)
# =============================================================================

def _trouver_plan(doc, body, plan_nom: str = 'XZ'):
    """
    Retourne le plan XZ_Plane ou YZ_Plane de l'origine du body ou du document.
    plan_nom : 'XZ' ou 'YZ'
    """
    tag = plan_nom.upper()   # 'XZ' ou 'YZ'

    # Chercher d'abord l'origine du body
    if body and hasattr(body, 'Origin') and body.Origin:
        for feat in body.Origin.OriginFeatures:
            if feat.TypeId == 'App::Plane' and tag in feat.Name.upper():
                return feat

    # Fallback : parcourir toutes les origines du document
    for obj in doc.Objects:
        if obj.TypeId == 'App::Origin':
            for feat in obj.OriginFeatures:
                if feat.TypeId == 'App::Plane' and tag in feat.Name.upper():
                    return feat
    return None


# =============================================================================
# Fonction principale
# =============================================================================

def generer_sketch_gorge_arbre(doc,
                                resultat: ResultatCalcul,
                                body=None,
                                lcs=None,
                                nom_sketch: str = 'GorgeArbre',
                                depouille_deg: float = 2.0,
                                plan: str = 'XZ',
                                r_alesage_reel: float = None,
                                suffixe: str = '') -> object:
    """
    Genere le sketch parametrique de gorge sur arbre dans FreeCAD.

    Parametres
    ----------
    doc             : document FreeCAD actif
    resultat        : ResultatCalcul issu de calcul.py
    body            : PartDesign::Body cible (None = premier body disponible)
    lcs             : LCS de reference (None = plan XZ ou YZ selon 'plan')
    nom_sketch      : nom de l'objet Sketch dans le document
    depouille_deg   : angle de depouille en degres (defaut 2 deg)
    plan            : plan d'esquisse — 'XZ' (defaut) ou 'YZ'
                      Z est l'axe de revolution de la piece dans les deux cas.
    r_alesage_reel  : rayon reel de l'alesage (mm) utilise pour la ligne de
                      construction G9. Si None, estime a r_arbre * 1.03.
                      Passer resultat.diametre_piece_mm / 2 depuis le dialogue
                      (cas gorge sur arbre : diametre_piece = D_alesage).

    Retourne
    --------
    L'objet Sketcher::SketchObject cree.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError("FreeCAD non disponible")

    # ── Parametres dimensionnels ──────────────────────────────────────────────
    #
    # IMPORTANT — convention rayon_arbre dans ResultatCalcul :
    #   Pour position='arbre', resultat.rayon_arbre = D_alesage/2 (surface de
    #   contact = bore). Le sketch attend la surface PHYSIQUE de l'arbre =
    #   D_arbre/2 = resultat.d_arbre/2.
    #   La profondeur de gorge h = resultat.h est identique dans les deux repères.
    #
    r_arbre  = round(resultat.d_arbre / 2.0, 4)   # surface physique de l'arbre
    r_gorge  = round(resultat.rayon_gorge, 4)       # fond de gorge arrondi (issu de calcul.py)
    b2       = round(resultat.b / 2.0, 4)
    d2       = resultat.d2
    dep_rad  = math.radians(depouille_deg)
    f_haut   = _fillet_haut(d2)
    f_fond   = _fillet_fond(d2)

    # Rayon alesage pour la ligne de construction G9
    # r_alesage_reel = D_alesage/2 (passé depuis dialogue), toujours > r_arbre
    if r_alesage_reel is not None and r_alesage_reel > r_arbre:
        r_alesage = r_alesage_reel
    elif hasattr(resultat, 'rayon_alesage') and resultat.rayon_alesage:
        r_alesage = resultat.rayon_alesage
    else:
        r_alesage = round(r_arbre * 1.03, 3)

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
    pos = _positions_initiales(r_arbre, r_gorge, b2, dep_rad, f_haut, f_fond)

    sketch.addGeometry(Part.LineSegment(pos['G0_p1'], pos['G0_p2']), True)   # G0 construction
    sketch.addGeometry(Part.LineSegment(pos['G1_p1'], pos['G1_p2']), False)  # G1 paroi
    sketch.addGeometry(Part.LineSegment(pos['G2_p1'], pos['G2_p2']), False)  # G2 fond
    sketch.addGeometry(Part.LineSegment(pos['G3_p1'], pos['G3_p2']), False)  # G3 flanc
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(pos['G4_center'], App.Vector(0, 0, 1), pos['G4_r']),
            pos['G4_a1'], pos['G4_a2']), False)                              # G4 conge haut
    sketch.addGeometry(Part.Point(pos['G5']), True)                          # G5 pt constr.
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(pos['G6_center'], App.Vector(0, 0, 1), pos['G6_r']),
            pos['G6_a1'], pos['G6_a2']), False)                              # G6 conge fond
    sketch.addGeometry(Part.Point(pos['G7']), True)                          # G7 pt constr.
    sketch.addGeometry(Part.LineSegment(pos['G8_p1'], pos['G8_p2']), False)  # G8 bord sup
    sketch.addGeometry(Part.LineSegment(pos['G9_p1'], pos['G9_p2']), True)   # G9 ref alesage

    for _ in range(3):
        doc.recompute()

    # ── Contraintes structurelles ─────────────────────────────────────────────
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 0))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 2))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 8))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', 9))
    sketch.addConstraint(Sketcher.Constraint('Vertical',   3))
    sketch.addConstraint(Sketcher.Constraint('Vertical', 4, 3, 0, 2))
    sketch.addConstraint(Sketcher.Constraint('Vertical', 0, 1, 9, 2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 7, 1, 1))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 7, 1, 2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 2, 2, -2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 9, 1, -2))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 5, 1, 1))
    sketch.addConstraint(Sketcher.Constraint('PointOnObject', 5, 1, 8))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 2, 2, 3, 1))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 3, 2, 8, 2))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 0, 2, 4, 2))
    sketch.addConstraint(Sketcher.Constraint('Coincident', 0, 2, 8, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 2, 1, 6, 2))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 1, 4, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 2, 6, 1))

    doc.recompute()

    # ── Contraintes dimensionnelles nommees ───────────────────────────────────
    dL0 = round(b2 * 0.5, 4)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceX', 0, 1, 0, 2, dL0))
    sketch.setDatum(idx, App.Units.Quantity(f'{dL0} mm'))
    sketch.renameConstraint(idx, 'demiLargeur' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceX', 7, 1, -1, 1, b2))
    sketch.setDatum(idx, App.Units.Quantity(f'{b2} mm'))
    sketch.renameConstraint(idx, 'demiLargeurGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', 2, 2, r_gorge))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_gorge} mm'))
    sketch.renameConstraint(idx, 'RayonGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', 3, 2, r_arbre))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_arbre} mm'))
    sketch.renameConstraint(idx, 'RayonArbre' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', 9, 1, r_alesage))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_alesage} mm'))
    sketch.renameConstraint(idx, 'RayonAlesage' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Radius', 4, f_haut))
    sketch.setDatum(idx, App.Units.Quantity(f'{f_haut} mm'))
    sketch.renameConstraint(idx, 'FilletHautGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Radius', 6, f_fond))
    sketch.setDatum(idx, App.Units.Quantity(f'{f_fond} mm'))
    sketch.renameConstraint(idx, 'FilletFondGorge' + suffixe)

    idx = sketch.addConstraint(
        Sketcher.Constraint('Angle', 3, 1, 1, 2, dep_rad))
    sketch.setDatum(idx, App.Units.Quantity(f'{depouille_deg} deg'))
    sketch.renameConstraint(idx, 'depouille' + suffixe)

    doc.recompute()

    _rapport(sketch, nom_sketch, resultat, b2, r_gorge, r_arbre, r_alesage,
             f_haut, f_fond, depouille_deg)
    return sketch


# =============================================================================
# Rapport console
# =============================================================================

def _rapport(sketch, nom, r, b2, r_gorge, r_arbre, r_alesage,
             f_haut, f_fond, dep_deg):
    print("=" * 55)
    print(f"SKETCH GORGE ARBRE : {nom}")
    print("=" * 55)
    print(f"  d1 = {r.d1} mm   d2 = {r.d2} mm")
    print(f"  h  = {r.h:.3f} mm   b  = {r.b:.3f} mm  (b/2 = {b2:.4f})")
    print(f"  RayonArbre   = {r_arbre:.3f} mm")
    print(f"  RayonGorge   = {r_gorge:.3f} mm")
    print(f"  RayonAlesage = {r_alesage:.3f} mm  (construction)")
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
    print("=== Test sketch_arbre.py (hors FreeCAD) ===\n")
    print(f"FreeCAD disponible : {FREECAD_DISPONIBLE}")

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from ORing.modules.calcul import calculer_gorge

    r = calculer_gorge(
        diametre_piece_mm=80.0,  # D_alesage pour gorge sur arbre
        position='arbre',
        type_montage='statique',
        materiau='NBR',
        pression_bar=50,
        temperature_C=60,
        standard='ISO_3601',
    )

    d2     = r.d2
    b2     = round(r.b / 2.0, 4)
    dep    = math.radians(2.0)
    f_haut = _fillet_haut(d2)
    f_fond = _fillet_fond(d2)

    print(f"Parametres calcules pour D_alesage=80 mm / ISO_3601 :")
    print(f"  d2         = {d2} mm")
    print(f"  r_arbre    = {r.rayon_arbre:.3f} mm")
    print(f"  r_gorge    = {r.rayon_gorge:.3f} mm")
    print(f"  h          = {r.h:.3f} mm")
    print(f"  b/2        = {b2:.4f} mm")
    print(f"  FilletHaut = {f_haut:.3f} mm")
    print(f"  FilletFond = {f_fond:.3f} mm")
    print()

    pos = _positions_initiales(r.rayon_arbre, r.rayon_gorge, b2, dep, f_haut, f_fond)
    print("Positions initiales :")
    for k, v in pos.items():
        if hasattr(v, 'x'):
            print(f"  {k:12s} : ({v.x:.4f}, {v.y:.4f})")
        else:
            print(f"  {k:12s} : {v:.4f}")

