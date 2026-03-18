# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : ORing.py
# -*- coding: utf-8 -*-
"""
ORing.py  —  Macro FreeCAD : insertion parametrique de joints toriques

Structure attendue dans le dossier Macro :
    Macro/
    ├── ORing.py           <-- ce fichier (point d'entree)
    └── ORing/
        ├── __init__.py
        └── modules/
            ├── __init__.py
            ├── calcul.py
            ├── dialogue.py
            ├── joints.py
            ├── materiaux.py
            ├── sketch_arbre.py
            ├── sketch_alesage.py
            ├── oring_3d.py
            └── utils.py

FreeCAD ne resout pas __file__ correctement dans tous les contextes.
On utilise FreeCAD.getUserMacroDir(True) comme base fiable.
"""

import sys
import os

# ── Résolution du dossier Macro ──────────────────────────────────────────────
# Methode 1 : via FreeCAD API (fiable dans tous les contextes)
try:
    import FreeCAD
    _macro_dir = FreeCAD.getUserMacroDir(True)
except Exception:
    _macro_dir = None

# Methode 2 : via __file__ si disponible et non vide
if not _macro_dir:
    try:
        _f = __file__
        if _f:
            _macro_dir = os.path.dirname(os.path.abspath(_f))
    except Exception:
        _macro_dir = None

# Methode 3 : repertoire courant en dernier recours
if not _macro_dir:
    _macro_dir = os.getcwd()

# ── Ajout au sys.path ────────────────────────────────────────────────────────
# On ajoute le dossier Macro ET le dossier ORing/ (pour que
# "from modules.xxx import" fonctionne depuis l'interieur du package)
_oring_dir = os.path.join(_macro_dir, "ORing")

for _p in [_macro_dir, _oring_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Diagnostic (visible dans la console FreeCAD) ─────────────────────────────
print(f"[ORing] Macro dir  : {_macro_dir}")
print(f"[ORing] ORing dir  : {_oring_dir}")
print(f"[ORing] Dir existe : {os.path.isdir(_oring_dir)}")

# ── Lancement du dialogue ────────────────────────────────────────────────────
try:
    from modules.dialogue import lancer_dialogue
    lancer_dialogue()
except ImportError as e:
    # Afficher un message clair dans FreeCAD
    try:
        from PySide2 import QtWidgets
        QtWidgets.QMessageBox.critical(
            None,
            "ORing — Erreur d'import",
            f"Impossible de charger le module :\n\n{e}\n\n"
            f"Verifiez que le dossier ORing/ est bien dans :\n{_macro_dir}\n\n"
            f"sys.path contient :\n" + "\n".join(sys.path[:6])
        )
    except Exception:
        pass
    raise
