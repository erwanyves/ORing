# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
"""
ORing.py — Macro FreeCAD : insertion parametrique de joints toriques.

CHANGER LA LANGUE :
  Editer ORing/lang.txt, mettre  en  ou  fr  sur la premiere ligne.
  Sauvegarder. Relancer la macro.
  Si lang.txt est absent → auto-detection.
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

print(f"[ORing] macro_dir  : {_macro_dir}")
print(f"[ORing] oring_dir  : {_oring_dir}")
print(f"[ORing] oring_dir existe : {os.path.isdir(_oring_dir)}")

# ---------------------------------------------------------------------------
# Langue — FORCER LE RECHARGEMENT du module pour contourner le cache Python
# ---------------------------------------------------------------------------
try:
    # Purger tous les modules ORing du cache Python
    mods_a_purger = [k for k in sys.modules if 'i18n' in k or
                     (k.startswith('modules.') and 'ORing' not in k
                      and k in sys.modules)]
    for _m in list(sys.modules.keys()):
        if _m in ('modules.i18n', 'modules.dialogue', 'modules.calcul',
                  'modules.utils', 'modules.joints', 'modules.materiaux',
                  'modules.metadata', 'modules.oring_3d',
                  'modules.sketch_arbre', 'modules.sketch_alesage',
                  'modules.__init__', 'modules'):
            del sys.modules[_m]
    print("[ORing] Cache modules purgé")

    import modules.i18n as _i18n
    _lang = _i18n.init(_oring_dir)
    print(f"[ORing] Langue active : '{_lang}'")

except Exception as _e:
    print(f"[ORing] ERREUR i18n : {_e}")
    import traceback; traceback.print_exc()

# ---------------------------------------------------------------------------
# Lancement du dialogue
# ---------------------------------------------------------------------------
try:
    from modules.dialogue import lancer_dialogue
    lancer_dialogue()
except ImportError as e:
    try:
        from PySide2 import QtWidgets
        QtWidgets.QMessageBox.critical(
            None, "ORing — Import error",
            f"Cannot load module:\n\n{e}\n\n"
            f"Check that ORing/ is in:\n{_macro_dir}"
        )
    except Exception:
        pass
    raise
