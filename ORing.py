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

__version__ = "3.0.1"

import sys
import os
import importlib


def _trace(message):
    """
    Traces de démarrage du lanceur.

    Elles sortaient inconditionnellement : ce sont les seules de la macro
    dans ce cas, `oring_debug` masquant tout le reste. On les aligne sur le
    même interrupteur — lu ici dans l'environnement plutôt qu'importé, car
    ce lanceur s'exécute AVANT que `ORing/modules/` ne soit importable.
    Les erreurs, elles, restent inconditionnelles.
    """
    if os.environ.get('ORING_DEBUG', '') not in ('', '0', 'false', 'False'):
        print(f"[ORing] {message}")

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

_trace(f"macro_dir : {_macro_dir}")
_trace(f"oring_dir : {_oring_dir}")

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
    _trace(f"Langue active : '{_lang}'  ({len(_i18n._translations)} traductions chargées)")

    # 3. Purger les modules métier pour forcer leur rechargement avec tr()
    #    opérationnel.
    #
    #    BALAYAGE PAR PRÉFIXE, et non liste écrite à la main (transposé de
    #    Swaging.FCMacro::_preparer_import, la forme de référence du projet).
    #
    #    POURQUOI (mesuré le 15/09/2026) : la liste en dur couvrait 11 noms
    #    alors que `ORing/modules/` en contenait 16. QUATRE modules réellement
    #    importés n'étaient jamais rechargés — helper_i18n, oring_debug,
    #    prerequis_helper, qt_compat. Un correctif déployé dans l'un d'eux ne
    #    prenait pas effet sans redémarrer FreeCAD, et AUCUN MD5 ne le
    #    révélait : le fichier sur le disque était juste, le code en mémoire
    #    était l'ancien. C'est un niveau silencieux entre « déployé » et
    #    « confirmé ». Confirmé guéri le 15/09 (marqueur posé sur
    #    `modules.oring_debug`, disparu après relance).
    #
    #    RECTIFICATION : la première rédaction de ce commentaire citait aussi
    #    `tnp_recovery.py` (68 Ko) et `widgets.py` comme « jamais rechargés »,
    #    et mettait le premier en avant à cause de sa taille. C'était faux :
    #    ces deux-là n'étaient importés par PERSONNE — jamais chargés, donc
    #    jamais périmés. Copies mortes et divergentes, supprimées le même jour
    #    (claude/constat_modules_morts_oring.md). Un fichier volumineux dans
    #    un dossier n'est pas du code qui tourne.
    #
    #    Le balayage est insensible à l'ajout d'un module : c'est le défaut
    #    de CLASSE, pas son occurrence, qui disparaît.
    #
    #    `modules.i18n` est la seule exception, et elle est délibérée : il
    #    vient d'être rechargé ET initialisé à l'étape 2 ci-dessus. Le purger
    #    perdrait la langue active.
    _CONSERVER = ('modules.i18n',)
    _purges = [_n for _n in list(sys.modules)
               if (_n == 'modules' or _n.startswith('modules.'))
               and _n not in _CONSERVER]
    for _m in _purges:
        del sys.modules[_m]
    _trace(f"Cache modules métier purgé ({len(_purges)} modules)")

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

