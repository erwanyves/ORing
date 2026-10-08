# Chemin : modules/qt_compat.py
# -*- coding: utf-8 -*-
"""
ORing/modules/qt_compat.py

Bootstrap FreeCAD + Qt partagé par `dialogue.py` et les modules qui en ont
été extraits — ces trois-là supprimés depuis, jamais importés : expose
`App`, `Gui`, `QtWidgets`, `QtCore`, `QtGui`, `FREECAD_DISPONIBLE`.

Hors de FreeCAD (tests, import isolé), remplace Qt par des classes factices
(`_Stub`) inertes plutôt que de lever une exception à l'import — permet à
ces modules d'être importés (et donc testés unitairement) sans FreeCAD.

Module partagé en interne à ORing uniquement (pas de dépendance croisée
avec une autre macro) — c'est l'unique point de bootstrap Qt de la macro,
que tous ses autres modules importent.
"""

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
    except ImportError:
        from PySide6 import QtWidgets, QtCore, QtGui
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False
    class _Stub:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, name): return _Stub
        def __call__(self, *a, **kw): return _Stub()
    class QtWidgets:
        QDialog        = _Stub
        QGroupBox      = _Stub
        QWidget        = _Stub
        QComboBox      = _Stub
        QDoubleSpinBox = _Stub
        QLineEdit      = _Stub
        QTextEdit      = _Stub
        QLabel         = _Stub
        QPushButton    = _Stub
        QRadioButton   = _Stub
        QButtonGroup   = _Stub
        QTabWidget     = _Stub
        QScrollArea    = _Stub
        QFrame         = _Stub
        QSizePolicy    = _Stub
        QFormLayout    = _Stub
        QGridLayout    = _Stub
        QVBoxLayout    = _Stub
        QHBoxLayout    = _Stub
        QApplication   = _Stub
        QMessageBox    = _Stub
        QTableWidget   = _Stub
        QTableWidgetItem = _Stub
        QHeaderView    = _Stub
    class QtCore:
        class Qt:
            AlignCenter    = 0
            AlignLeft      = 0
            AlignVCenter   = 0
            AlignRight     = 0
            UserRole       = 0
    class QtGui:
        QBrush = _Stub
        QColor = _Stub
