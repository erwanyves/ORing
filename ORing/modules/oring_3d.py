# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/oring_3d.py
# -*- coding: utf-8 -*-
"""
oring_3d.py  — Génération du corps 3D joint torique déformé.

Approche paramétrique (suit le LCS quand la pièce se déplace) :
  1. PartDesign::Body indépendant (même Placement que le body pièce)
  2. Sketch attaché au LCS via AttachmentSupport → se recalcule avec le LCS
  3. PartDesign::Revolution 360° autour de H_Axis → tore

Profil oblong conservant l'aire de section du joint circulaire au repos :
  h_ob = r_max − r_min   (espace disponible dans la gorge)
  r_ob = h_ob / 2
  L    = (π·(d2/2)² − π·r_ob²) / h_ob   (longueur droite)
  b_ob = L + h_ob

Ordre des géométries dans le sketch (conforme XML de référence) :
  G0 : ArcOfCircle — demi-cercle GAUCHE  centre=(−L/2, r_c)  90° → 270°
  G1 : ArcOfCircle — demi-cercle DROIT   centre=(+L/2, r_c)  270° → 450°
  G2 : LineSegment — ligne HAUTE  (−L/2, r_max) → (+L/2, r_max)
  G3 : LineSegment — ligne BASSE  (−L/2, r_min) → (+L/2, r_min)

Contraintes (9) :
  [0] Tangent(0,1 ; 2,1)           G0.start ↔ G2.p1
  [1] Tangent(0,2 ; 3,1)           G0.end   ↔ G3.p1
  [2] Tangent(1,2 ; 2,2)           G1.end   ↔ G2.p2
  [3] Tangent(1,1 ; 3,2)           G1.start ↔ G3.p2
  [4] Equal(0, 1)                  rayons égaux
  [5] Symmetric(0,3 ; 1,3 ; -2)   centres symétriques par V_Axis
  [6] DistanceX(0,3 ; 1,3) = L    'LargeurOblong'
  [7] Radius(0) = r_ob             'RayonOblong'
  [8] DistanceY(3, 1, r_min)       'RayonIntOblong'  (format 3-args)
"""

import math
import re as _re

try:
    import FreeCAD as App
    import Part
    import Sketcher
    import PartDesign          # noqa
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False
    class _Vec:
        def __init__(self, x=0, y=0, z=0): self.x, self.y, self.z = x, y, z
    class _App:
        Vector = _Vec
        class Rotation:
            def __init__(self, *a): pass
        class Placement:
            def __init__(self, *a): pass
        class Units:
            @staticmethod
            def Quantity(s): return s
    class _Part:
        class LineSegment:
            def __init__(self, *a): pass
        class ArcOfCircle:
            def __init__(self, *a): pass
        class Circle:
            def __init__(self, *a): pass
    class _Sketcher:
        class Constraint:
            def __init__(self, *a): pass
    App      = _App
    Part     = _Part
    Sketcher = _Sketcher

from .calcul import ResultatCalcul


# =============================================================================
# Couleurs materiaux — chargees depuis parametres_calcul.json
# =============================================================================

def _charger_couleurs():
    import json, os
    _dir  = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    _path = os.path.join(_dir, 'parametres_calcul.json')
    try:
        with open(_path, encoding='utf-8') as f:
            data = json.load(f)
        section = data.get('couleurs_materiaux', {})
        defaut  = section.get('_defaut', {'rgb': [30, 25, 22], 'shininess': 5})
        palette = {k.upper(): v for k, v in section.items() if not k.startswith('_')}
        print(f"[ORing couleurs] palette chargee : {len(palette)} materiaux depuis {_path}")
        return palette, defaut
    except Exception as e:
        print(f"[ORing couleurs] AVERT chargement palette echoue ({_path}) : {e}")
        return {}, {'rgb': [30, 25, 22], 'shininess': 5}

_COULEURS_PALETTE, _COULEUR_DEFAUT = _charger_couleurs()


def _appliquer_couleur_test(body) -> None:
    """TEST TEMPORAIRE : applique rouge vif via 3 methodes pour identifier laquelle fonctionne."""
    try:
        import FreeCADGui as Gui
        import FreeCAD as App
    except ImportError:
        return

    r, g, b = 1.0, 0.0, 0.0  # rouge vif inratable

    cibles = [body]
    tip = getattr(body, 'Tip', None)
    if tip is not None:
        cibles.append(tip)
    for feat in getattr(body, 'Group', []):
        if feat not in cibles:
            cibles.append(feat)

    gui_doc = Gui.ActiveDocument
    for obj in cibles:
        try:
            nom = getattr(obj, 'Name', '')
            if not nom:
                continue
            vo = gui_doc.getObject(nom)
            if vo is None:
                continue

            # Methode 1
            try:
                mat = App.Material()
                mat.DiffuseColor = (r, g, b, 0.0)
                vo.ShapeMaterial = mat
                print(f"[TEST rouge] {nom} ShapeMaterial OK")
            except Exception as e1:
                print(f"[TEST rouge] {nom} ShapeMaterial : {e1}")

            # Methode 2 : getUserDefinedMaterial
            try:
                mat = vo.getUserDefinedMaterial()
                if mat is not None:
                    mat.DiffuseColor = (r, g, b, 0.0)
                    after = vo.getUserDefinedMaterial()
                    print(f"[TEST rouge] {nom} getUserDefined apres : {after.DiffuseColor}")
            except Exception as e2:
                print(f"[TEST rouge] {nom} getUserDefinedMaterial : {e2}")

            # Methode 3 : setElementColors
            try:
                if hasattr(vo, 'setElementColors'):
                    vo.setElementColors({'Face': (r, g, b, 0.0)})
                    ec = vo.getElementColors() if hasattr(vo, 'getElementColors') else {}
                    print(f"[TEST rouge] {nom} getElementColors apres : {ec}")
            except Exception as e3:
                print(f"[TEST rouge] {nom} setElementColors : {e3}")

            # PropertiesList (liste interne FreeCAD, plus complete que dir())
            try:
                pl = vo.PropertiesList
                couleur_props = [p for p in pl if any(
                    k in p.lower() for k in ('color','colour','material','diffuse'))]
                print(f"[TEST rouge] {nom} PropertiesList couleur : {couleur_props}")
            except Exception as e4:
                print(f"[TEST rouge] {nom} PropertiesList : {e4}")

        except Exception as e:
            print(f"[TEST rouge] {nom} erreur : {e}")

    try:
        Gui.updateGui()
    except Exception:
        pass
    print("[TEST rouge] FIN — verifier visuellement si le tore est rouge")


def appliquer_couleur_materiau(body, materiau: str) -> None:
    """Applique la couleur du matériau sur le joint ORing (FreeCAD 1.0).

    Utilise ViewObject.ShapeColor (tuple RGBA float 0-1) : méthode la plus
    directe et la plus persistante, non effacée par un recompute ultérieur
    dès lors qu'elle est appliquée APRÈS le dernier recompute du flux.
    """
    try:
        import FreeCADGui as Gui
    except ImportError:
        return

    try:
        cle    = (materiau or '').upper().strip()
        entree = _COULEURS_PALETTE.get(cle, _COULEUR_DEFAUT)
        r, g, b = [x / 255.0 for x in entree['rgb']]
        couleur_rgba = (r, g, b, 0.0)   # alpha 0 = opaque dans FreeCAD

        # Cibles : Body lui-même + Tip (Revolution) + features 3D du groupe
        cibles = [body]
        tip = getattr(body, 'Tip', None)
        if tip is not None and tip not in cibles:
            cibles.append(tip)
        for feat in getattr(body, 'Group', []):
            if feat not in cibles and getattr(feat, 'TypeId', '') not in (
                    'Sketcher::SketchObject',):
                cibles.append(feat)

        gui_doc = Gui.ActiveDocument
        if gui_doc is None:
            return

        nb_ok = 0
        for obj in cibles:
            nom = getattr(obj, 'Name', None)
            if not nom:
                continue
            try:
                vo = gui_doc.getObject(nom)
                if vo is None:
                    continue
                if hasattr(vo, 'ShapeColor'):
                    vo.ShapeColor = couleur_rgba
                if hasattr(vo, 'LineColor'):
                    vo.LineColor = (r * 0.6, g * 0.6, b * 0.6, 0.0)
                if hasattr(vo, 'Transparency'):
                    vo.Transparency = 0
                nb_ok += 1
            except Exception as e_obj:
                print(f"[ORing couleurs]   '{nom}' : {e_obj}")

        print(f"[ORing couleurs] '{getattr(body,'Name','?')}' mat={cle} "
              f"rgb=({int(r*255)},{int(g*255)},{int(b*255)}) sur {nb_ok}/{len(cibles)} objet(s)")

    except Exception as e:
        print(f"[ORing couleurs] AVERT appliquer_couleur_materiau : {e}")



# =============================================================================
# Calcul des dimensions oblongues
# =============================================================================

def _dims_oblong(d2: float, h_ob: float,
                 r_min: float, r_max: float,
                 position: str = 'arbre') -> dict:
    """Calcule les dimensions de la section oblongue par conservation du VOLUME.

    Le caoutchouc etant incompressible (nu ~ 0.5), c'est le volume du tore
    qui se conserve, pas la section :

        V = 2*pi * R_c * A_section  =  constante

    => A_def = pi*(d2/2)^2 * R_c_repos / R_c_def

    R_c_repos : centroide du tore au repos (joint circulaire non comprime)
        arbre   : fond de gorge = r_min  =>  R_c_repos = r_min + d2/2
        alesage : fond de gorge = r_max  =>  R_c_repos = r_max - d2/2

    R_c_def   : centroide deformed = milieu de l'espace disponible
        R_c_def = (r_min + r_max) / 2

    La correction est faible pour les joints courants (d2 << D_gorge)
    mais rigoureuse pour les gros joints sur petits diametres.
    """
    r_ob = h_ob / 2.0

    # Centroide au repos
    if position == 'arbre':
        r_c_repos = r_min + d2 / 2.0
    else:
        r_c_repos = r_max - d2 / 2.0

    # Centroide deformed
    r_c_def = (r_min + r_max) / 2.0

    # Correction volumique
    if r_c_def > 1e-9:
        facteur = r_c_repos / r_c_def
    else:
        facteur = 1.0

    aire_repos = math.pi * (d2 / 2.0) ** 2
    aire_def   = aire_repos * facteur

    L_droite = (aire_def - math.pi * r_ob ** 2) / h_ob

    return {
        'r_ob':       round(r_ob,     6),
        'L_droite':   round(L_droite, 6),
        'b_ob':       round(L_droite + h_ob, 6),
        'r_c_repos':  round(r_c_repos, 6),
        'r_c_def':    round(r_c_def,   6),
        'facteur':    round(facteur,   6),
        'aire_repos': round(aire_repos, 6),
        'aire_def':   round(aire_def,   6),
        'valide':     L_droite > 1e-6,
    }


# =============================================================================
# Utilitaires
# =============================================================================

def _trouver_body_parent(lcs, doc):
    """Retourne le PartDesign::Body propriétaire du LCS."""
    for obj in doc.Objects:
        if obj.TypeId == 'PartDesign::Body':
            grp = getattr(obj, 'Group', None) or []
            if lcs in grp:
                return obj
    return None


# =============================================================================
# Fonction principale
# =============================================================================

def calculer_dims_oblongues(d2: float, r_gorge: float,
                            r_contact: float, position: str) -> dict:
    """
    Calcule les dimensions de la section oblongue du tore.
    Exposée publiquement pour permettre la mise à jour in-place.
    """
    r_min = round(min(r_gorge, r_contact), 6)
    r_max = round(max(r_gorge, r_contact), 6)
    h_ob  = round(r_max - r_min, 6)
    if h_ob < 1e-9:
        return {'valide': False}
    r_ob = h_ob / 2.0
    if position == 'arbre':
        r_c_repos = r_min + d2 / 2.0
        r_c_def   = (r_min + r_max) / 2.0
    else:
        r_c_repos = r_max - d2 / 2.0
        r_c_def   = (r_min + r_max) / 2.0
    aire_repos = math.pi * (d2 / 2.0) ** 2
    facteur    = r_c_repos / r_c_def if r_c_def > 1e-9 else 1.0
    aire_def   = aire_repos * facteur
    L_droite   = (aire_def - math.pi * r_ob ** 2) / h_ob
    return {
        'r_ob':      round(r_ob, 6),
        'L_droite':  round(L_droite, 6),
        'b_ob':      round(L_droite + h_ob, 6),
        'r_c_repos': round(r_c_repos, 6),
        'r_c_def':   round(r_c_def, 6),
        'r_min':     r_min,
        'r_max':     r_max,
        'h_ob':      h_ob,
        'valide':    L_droite > 1e-6,
    }


def generer_oring_3d(doc,
                     resultat: ResultatCalcul,
                     lcs,
                     position: str   = 'arbre',
                     nom_body: str   = 'ORing',
                     nom_sketch: str = 'SketchORing',
                     part_oring      = None) -> object:
    """
    Crée un PartDesign::Body contenant un tore oblong paramétrique.
    Le sketch est attaché au LCS → suit automatiquement tout déplacement.

    part_oring : App::Part ORing cible. Si fourni, le body est créé
                 directement dedans (évite les problèmes de conteneur actif).
    Retourne le body créé.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError("FreeCAD non disponible")
    if lcs is None:
        raise ValueError("LCS requis pour positionner le joint 3D")

    # ── Rayons ──────────────────────────────────────────────────────────────
    # Utiliser rayon_arbre / rayon_gorge déjà calculés par calcul.py :
    #   arbre   : rayon_arbre = D_alesage/2 (contact),  rayon_gorge = D_arbre/2 - h
    #   alesage : rayon_arbre = D_arbre/2   (contact arbre), rayon_gorge = D_alesage/2 + h
    r_gorge   = round(float(getattr(resultat, 'rayon_gorge',
                  resultat.d_arbre / 2.0 - resultat.h
                  if position == 'arbre'
                  else resultat.d_alesage / 2.0 + resultat.h)), 4)
    r_contact = round(float(getattr(resultat, 'rayon_arbre',
                  resultat.d_alesage / 2.0
                  if position == 'arbre'
                  else resultat.d_arbre / 2.0)), 4)

    r_min = round(min(r_gorge, r_contact), 6)
    r_max = round(max(r_gorge, r_contact), 6)
    h_ob  = round(r_max - r_min, 6)
    r_c   = round((r_min + r_max) / 2.0, 6)

    dims = _dims_oblong(resultat.d2, h_ob, r_min, r_max, position)
    if not dims['valide']:
        print(f"[ORing 3D] AVERT : L={dims['L_droite']:.4f}mm ≤ 0 (squeeze excessif)")

    r_ob = dims['r_ob']
    L    = dims['L_droite']

    _rapport_dims(resultat, position, r_gorge, r_contact, h_ob, r_ob, L,
                  dims['b_ob'], r_c, r_min, dims=dims)

    # ── Body ─────────────────────────────────────────────────────────────────
    # FreeCAD place doc.addObject dans le "conteneur actif" (ActivePart).
    # Pour contourner ça, on désactive temporairement l'ActivePart, on crée
    # le body à la racine du document, puis on l'ajoute explicitement au
    # Part ORing cible. C'est la seule méthode fiable pour App::Part.
    _active_part_saved = None
    try:
        import FreeCADGui as Gui
        _active_part_saved = Gui.ActiveDocument.ActiveView.getActiveObject('pdbody')             if hasattr(Gui, 'ActiveDocument') and Gui.ActiveDocument else None
    except Exception:
        pass

    try:
        # Suspendre le conteneur actif le temps de la création
        if FREECAD_DISPONIBLE:
            try:
                import FreeCADGui as Gui
                if hasattr(Gui, 'ActiveDocument') and Gui.ActiveDocument:
                    Gui.ActiveDocument.ActiveView.setActiveObject('pdbody', None)
            except Exception:
                pass
        body = doc.addObject('PartDesign::Body', nom_body)
    finally:
        # Restaurer le conteneur actif
        try:
            import FreeCADGui as Gui
            if (_active_part_saved is not None
                    and hasattr(Gui, 'ActiveDocument') and Gui.ActiveDocument):
                Gui.ActiveDocument.ActiveView.setActiveObject(
                    'pdbody', _active_part_saved)
        except Exception:
            pass

    body.Label = nom_body

    # Ajouter explicitement au Part ORing cible
    if part_oring is not None:
        # Retirer de tout parent éventuel (cas où FreeCAD aurait quand même
        # capturé le body malgré la désactivation du conteneur actif)
        for _p in list(getattr(body, 'InList', [])):
            if getattr(_p, 'TypeId', '') == 'App::Part':
                try:
                    _p.removeObject(body)
                    print(f"[ORing 3D] body retiré de '{_p.Label}' avant addObject")
                except Exception:
                    pass
        part_oring.addObject(body)
        print(f"[ORing 3D] body '{nom_body}' ajouté à Part '{part_oring.Label}'")
    else:
        # FIX #2 : part_oring manquant → signaler et retirer le body de tout parent
        # pour éviter qu'il se retrouve dans un Part au hasard
        print(f"[ORing 3D] AVERT : part_oring=None pour body '{nom_body}' — "
              f"vérifier l'appelant (body sera à la racine du document)")
        for _p in list(getattr(body, 'InList', [])):
            if getattr(_p, 'TypeId', '') == 'App::Part':
                try:
                    _p.removeObject(body)
                    print(f"[ORing 3D] body déplacé hors de '{_p.Label}' (part_oring=None)")
                except Exception:
                    pass

    # Aligner le Placement du body ORing sur celui du body pièce.
    # Sans ça, FreeCAD résout AttachmentSupport avec le LCS en coordonnées
    # locales du body ORing (à l'origine), pas en coordonnées globales.
    body_parent = _trouver_body_parent(lcs, doc)
    if body_parent is not None:
        # Liaison paramétrique : le body ORing suit le body pièce
        # setExpression crée un lien dynamique — recalculé à chaque recompute
        try:
            body.setExpression('Placement', f'{body_parent.Name}.Placement')
            print(f"[ORing 3D] Placement lié à '{body_parent.Label}' par expression")
        except Exception as e_expr:
            # Fallback statique si setExpression non supporté
            body.Placement = body_parent.Placement
            print(f"[ORing 3D] Placement copié (expression non supportée : {e_expr})")
    doc.recompute([body])

    # ── Sketch attaché au LCS ────────────────────────────────────────────────
    sketch = body.newObject('Sketcher::SketchObject', nom_sketch)

    # Suffixe unique dérivé du nom interne FreeCAD (garanti unique dans le doc)
    suffixe = '_' + _re.sub(r'[^A-Za-z0-9]', '_', sketch.Name)

    # ObjectXZ : H_Axis du sketch = axe X du LCS (axial) → révolution OK
    # AttachmentOffset rotation Z +90° : aligne H_Axis sur l'axe de la pièce
    sketch.AttachmentSupport = [(lcs, '')]
    sketch.MapMode           = 'ObjectXZ'
    sketch.AttachmentOffset  = App.Placement(
        App.Vector(0, 0, 0),
        App.Rotation(App.Vector(0, 0, 1), 90)
    )
    doc.recompute([body])

    _ajouter_geometries(sketch, r_ob, L, r_c, r_min, r_max)
    for _ in range(3):
        doc.recompute([body])

    _ajouter_contraintes(sketch, r_ob, L, r_min, suffixe)
    doc.recompute([body])

    # ── Révolution 360° ──────────────────────────────────────────────────────
    # PartDesign::Revolution est ADDITIF sur un body vide → crée le solide.
    # NE PAS définir Symmetric ni Reversed : ces attributs n'existent pas
    # sur PartDesign::Revolution en FreeCAD 1.0.
    rev = body.newObject('PartDesign::Revolution', 'TorusORing')
    rev.Profile       = sketch
    rev.ReferenceAxis = (sketch, ['H_Axis'])
    rev.Angle         = 360.0
    doc.recompute([body])

    # Tip obligatoire : sans ça la feature est créée mais inactive dans l'arbre
    body.Tip = rev
    doc.recompute([body])

    try:
        sketch.ViewObject.Visibility = False
    except Exception:
        pass

    # Couleur appliquée par l'appelant (dialogue.py) après le dernier recompute.

    print(f"[ORing 3D] '{nom_body}' créé — r_c={r_c:.3f} h={h_ob:.3f} b={dims['b_ob']:.3f} mm")
    return body


# =============================================================================
# Géométries
# =============================================================================

def _ajouter_geometries(sketch, r_ob, L, r_c, r_min, r_max):
    """
    G0 arc gauche  : centre (−L/2, r_c)  90° → 270°
    G1 arc droit   : centre (+L/2, r_c)  270° → 450°
    G2 ligne haute : (−L/2, r_max) → (+L/2, r_max)
    G3 ligne basse : (−L/2, r_min) → (+L/2, r_min)
    """
    L2 = L / 2.0

    # G0 — demi-cercle gauche (start=haut@90°, end=bas@270°)
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(App.Vector(-L2, r_c, 0), App.Vector(0, 0, 1), r_ob),
            math.pi / 2,
            3 * math.pi / 2),
        False)

    # G1 — demi-cercle droit (start=bas@270°, end=haut@450°)
    sketch.addGeometry(
        Part.ArcOfCircle(
            Part.Circle(App.Vector(+L2, r_c, 0), App.Vector(0, 0, 1), r_ob),
            3 * math.pi / 2,
            5 * math.pi / 2),
        False)

    # G2 — ligne haute
    sketch.addGeometry(
        Part.LineSegment(
            App.Vector(-L2, r_max, 0),
            App.Vector(+L2, r_max, 0)),
        False)

    # G3 — ligne basse
    sketch.addGeometry(
        Part.LineSegment(
            App.Vector(-L2, r_min, 0),
            App.Vector(+L2, r_min, 0)),
        False)


# =============================================================================
# Contraintes
# =============================================================================

def _ajouter_contraintes(sketch, r_ob, L, r_min, suffixe: str = ''):
    """
    9 contraintes — conforme au XML de référence.

    Topologie (pos=1=start, pos=2=end, pos=3=centre arc) :
      G0.start(pos=1) @ 90°  = haut-gauche
      G0.end  (pos=2) @ 270° = bas-gauche
      G1.start(pos=1) @ 270° = bas-droit
      G1.end  (pos=2) @ 450° = haut-droit
    """
    # 4 Tangent endpoints (coïncidence + tangence en un seul appel)
    sketch.addConstraint(Sketcher.Constraint('Tangent', 0, 1, 2, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 0, 2, 3, 1))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 2, 2, 2))
    sketch.addConstraint(Sketcher.Constraint('Tangent', 1, 1, 3, 2))

    # Equal — même rayon pour G0 et G1
    sketch.addConstraint(Sketcher.Constraint('Equal', 0, 1))

    # Symmetric — centres G0(pos=3) et G1(pos=3) symétriques par V_Axis(-2)
    sketch.addConstraint(Sketcher.Constraint('Symmetric', 0, 3, 1, 3, -2))

    # DistanceX — distance entre les centres = L
    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceX', 0, 3, 1, 3, L))
    sketch.setDatum(idx, App.Units.Quantity(f'{L:.6f} mm'))
    sketch.renameConstraint(idx, 'LargeurOblong' + suffixe)

    # Radius — rayon de G0
    idx = sketch.addConstraint(Sketcher.Constraint('Radius', 0, r_ob))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_ob:.6f} mm'))
    sketch.renameConstraint(idx, 'RayonOblong' + suffixe)

    # DistanceY — Y de G3.p1 = r_min  (format 3-args)
    idx = sketch.addConstraint(
        Sketcher.Constraint('DistanceY', 3, 1, r_min))
    sketch.setDatum(idx, App.Units.Quantity(f'{r_min:.6f} mm'))
    sketch.renameConstraint(idx, 'RayonIntOblong' + suffixe)


# =============================================================================
# Rapport
# =============================================================================

def _rapport_dims(r, position, r_gorge, r_contact, h_ob, r_ob, L, b_ob,
                  r_c, r_min, dims=None):
    print("=" * 58)
    print("ORING 3D — SECTION OBLONGUE")
    print("=" * 58)
    print(f"  Position    : gorge sur {'arbre' if position == 'arbre' else 'alesage'}")
    print(f"  d2          = {r.d2} mm")
    print(f"  r_gorge     = {r_gorge:.4f} mm")
    print(f"  r_contact   = {r_contact:.4f} mm")
    print(f"  r_min       = {r_min:.4f} mm")
    print(f"  r_ob        = {r_ob:.4f} mm  (h_ob = {h_ob:.4f})")
    print(f"  L_droite    = {L:.4f} mm")
    print(f"  b_ob        = {b_ob:.4f} mm")
    if dims:
        A_repos = dims.get('aire_repos', math.pi * (r.d2 / 2.0) ** 2)
        A_def   = dims.get('aire_def',   A_repos)
        facteur = dims.get('facteur',    1.0)
        r_cr    = dims.get('r_c_repos',  0.0)
        r_cd    = dims.get('r_c_def',    r_c)
        A_ob    = math.pi * r_ob ** 2 + 2.0 * r_ob * L
        print(f"  R_c repos   = {r_cr:.4f} mm")
        print(f"  R_c def     = {r_cd:.4f} mm")
        print(f"  Facteur V   = {facteur:.6f}  (R_c_repos/R_c_def)")
        print(f"  Aire repos  = {A_repos:.4f} mm²")
        print(f"  Aire def    = {A_def:.4f} mm²")
        print(f"  Aire oblong = {A_ob:.4f} mm²  (ecart={abs(A_def - A_ob):.2e})")
    else:
        A_c  = math.pi * (r.d2 / 2.0) ** 2
        A_ob = math.pi * r_ob ** 2 + 2.0 * r_ob * L
        print(f"  Aire        : {A_c:.4f} -> {A_ob:.4f} mm²  (ecart={abs(A_c - A_ob):.2e})")
    print("=" * 58)
