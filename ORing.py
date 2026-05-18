# Chemin : ORing.FCMacro
# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
"""
ORing.py — Macro FreeCAD : insertion parametrique de joints toriques.

CHANGER LA LANGUE :
  Editer ORing/lang.txt, mettre  en  ou  fr  sur la premiere ligne.
  Sauvegarder. Relancer la macro.
  Fichier absent ou vide → auto-detection.
  Code inconnu (pas de .json correspondant) → anglais.
"""

import sys
import os
import importlib

# ---------------------------------------------------------------------------
# Dossier Macro
# ---------------------------------------------------------------------------
try:
    import FreeCAD
    _macro_dir = FreeCAD.getUserMacroDir(True)
except Exception:
    _macro_dir = None

if not _macro_dir:
    try:
        _f = __file__
        if _f:
            _macro_dir = os.path.dirname(os.path.abspath(_f))
    except Exception:
        _macro_dir = None

if not _macro_dir:
    _macro_dir = os.getcwd()

_oring_dir = os.path.join(_macro_dir, "ORing")

for _p in [_macro_dir, _oring_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

print(f"[ORing] macro_dir : {_macro_dir}")
print(f"[ORing] oring_dir : {_oring_dir}")

# ---------------------------------------------------------------------------
# Langue
# ORDRE CRITIQUE :
#   1. Recharger i18n ET initialiser la langue
#   2. Purger les autres modules (dialogue, calcul, etc.)
#   3. Importer dialogue (qui fait "from .i18n import tr" → tr() déjà opérationnel)
# ---------------------------------------------------------------------------
try:
    # 1. Recharger i18n (forcer la réexécution des définitions globales)
    if 'modules.i18n' in sys.modules:
        _i18n = importlib.reload(sys.modules['modules.i18n'])
    else:
        import modules.i18n as _i18n

    # 2. Initialiser la langue AVANT tout autre import de module ORing
    _lang = _i18n.init(_oring_dir)
    print(f"[ORing] Langue active : '{_lang}'  ({len(_i18n._translations)} traductions chargées)")

    # 3. Purger les modules métier pour forcer leur rechargement avec tr() opérationnel
    for _m in list(sys.modules.keys()):
        if _m in ('modules.dialogue', 'modules.calcul',
                  'modules.utils', 'modules.joints', 'modules.materiaux',
                  'modules.metadata', 'modules.oring_3d',
                  'modules.sketch_arbre', 'modules.sketch_alesage',
                  'modules.__init__', 'modules'):
            del sys.modules[_m]
    print("[ORing] Cache modules métier purgé")

except Exception as _e:
    print(f"[ORing] ERREUR i18n : {_e}")
    import traceback; traceback.print_exc()

# ---------------------------------------------------------------------------
# Lancement du dialogue
# (dialogue.py est importé ici → "from .i18n import tr" → tr() déjà initialisé)
# ---------------------------------------------------------------------------
try:
    from modules.dialogue import lancer_dialogue
    lancer_dialogue()
except ImportError as e:
    try:
        try:
            from PySide2 import QtWidgets
        except ImportError:
            from PySide6 import QtWidgets
        QtWidgets.QMessageBox.critical(
            None, "ORing — Import error",
            f"Cannot load module:\n\n{e}\n\n"
            f"Check that ORing/ is in:\n{_macro_dir}"
        )
    except Exception:
        pass
    raise

