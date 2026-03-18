# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/dialogue.py
# -*- coding: utf-8 -*-
"""
ORing/modules/dialogue.py

Logique des diametres (point cle) :
  - Gorge sur arbre   : piece complementaire = ALESAGE
                        => diametre alesage utilise pour le calcul du squeeze
                        => serrage radial = entre fond de gorge et alesage
  - Gorge dans alesage: piece complementaire = ARBRE
                        => diametre arbre utilise pour le calcul du squeeze
                        => serrage radial = entre arbre et fond de gorge

Sequence FreeCAD lors de "Appliquer" :
  1. Generation du sketch de demi-gorge dans le plan XZ (axe Z = axe piece)
  2. PartDesign::Groove (revolution 360 deg autour de V_Axis = axe Z)
     => cree la demi-gorge (de X=0 a X=-b/2 en coords sketch)
  3. PartDesign::Mirrored par rapport au plan XY (Z=0)
     => complete la gorge symetriquement (de -b/2 a +b/2)

─── Étape 1a (mars 2026) ────────────────────────────────────────────────────
Filtrage des listes de bodies :
  - WidgetSelectBody accepte maintenant une liste pre-filtree via set_bodies()
  - Body principal : uniquement les bodies avec LCS + parametre nomme
  - Body complementaire : uniquement les bodies avec parametre nomme,
    en excluant dynamiquement le body deja selectionne pour la gorge

─── Étape 1b (mars 2026) ────────────────────────────────────────────────────
Validation au demarrage :
  - lancer_dialogue() verifie qu'au moins un body valide existe dans le doc
  - Si aucun body conforme : affichage d'un message d'instruction + fermeture

─── Étape 1c (mars 2026) ────────────────────────────────────────────────────
Indicateur visuel du serrage par defaut :
  - spin_squeeze a 0 = mode automatique (valeur cible ISO selon type montage)
  - lbl_squeeze_info affiche la valeur calculee par get_plage_squeeze()
  - Style gris italique = auto ; bleu = manuel dans la plage ; orange gras = hors plage

─── Refonte panneau unique (mars 2026) ──────────────────────────────────────
Interface monopage remplacant les 4 onglets :
  sections verticales : Contexte / Materiau / Pieces FreeCAD / Joint-Gorge
  pieces FreeCAD en 2 colonnes (arbre | alesage)
  zone resultats + boutons en pied de fenetre
─────────────────────────────────────────────────────────────────────────────
"""

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide2 import QtWidgets, QtCore, QtGui
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

from .calcul    import calculer_gorge, afficher_synthese, TYPES_MONTAGE, STANDARDS, ecarts_arbre, it_value
from .materiaux import liste_materiaux, get_materiau
from .joints    import liste_series, liste_d2, get_plage_squeeze, choisir_d1
from .utils     import (lister_bodies, lister_lcs, lister_parametres_body,
                        lister_bodies_valides_gorge, lister_bodies_valides_comp,
                        doc_a_bodies_valides,
                        message_erreur, message_info, get_document_actif)


# =============================================================================
# MESSAGE D'INSTRUCTION (étape 1b)
# =============================================================================

_MSG_PREREQUIS = """\
Pour utiliser cette macro, votre document doit contenir :

  • Au moins un Body destiné à recevoir la gorge
    → Ce body doit posséder un LCS (pour l'accrochage du sketch)
      et un paramètre nommé définissant le diamètre ou le rayon
      d'implantation.

  • Au moins un Body complémentaire
    → Ce body doit posséder un paramètre nommé définissant
      le diamètre ou le rayon d'appui.

La macro se ferme.
Veuillez préparer vos bodies et relancer."""


# =============================================================================
# LIBELLES SELON POSITION
# =============================================================================

def _libelles_position(position: str) -> tuple:
    if position == 'arbre':
        return (
            "Piece portant la GORGE = ARBRE  ← sketch genere ICI",
            "Piece SANS gorge = ALESAGE  (diametre de reference)",
        )
    else:
        return (
            "Piece portant la GORGE = ALESAGE  ← sketch genere ICI",
            "Piece SANS gorge = ARBRE  (diametre de reference)",
        )


# =============================================================================
# WIDGET : selection Body + parametre diametre
# =============================================================================

# =============================================================================
# DIAGRAMME AJUSTEMENT ISO 286-1
# =============================================================================

class _DiagrammeAjustement(QtWidgets.QWidget):
    """
    Widget compact visualisant un ajustement H/f ou H/g ISO 286-1.
    Affiche la bande alésage H (bleu) et la bande arbre f/g (rouge)
    autour de la ligne zéro (diamètre nominal), avec annotations.
    """
    _HAUTEUR = 140

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = None          # dict retourné par ecarts_arbre()
        self.setMinimumHeight(self._HAUTEUR)
        self.setMaximumHeight(self._HAUTEUR)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Fixed)

    def set_data(self, data: dict):
        """Met à jour les données et force un repaint."""
        self._data = data
        self.update()

    def clear(self):
        self._data = None
        self.update()

    def paintEvent(self, event):
        if not FREECAD_DISPONIBLE:
            return
        from PySide2.QtGui import QPainter, QColor, QPen, QFont
        from PySide2.QtCore import Qt, QRectF

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W = self.width()
        H = self._HAUTEUR

        # ── Fond ─────────────────────────────────────────────────────────
        p.fillRect(0, 0, W, H, QColor('#f8f8f8'))

        if self._data is None:
            p.setPen(QColor('#aaaaaa'))
            p.drawText(0, 0, W, H, Qt.AlignCenter,
                       "Sélectionner mode ISO\npour afficher le diagramme")
            return

        d   = self._data
        ES  = d['ES_alesage_µm']   # positif
        EI  = d['EI_alesage_µm']   # 0
        es  = d['es_arbre_µm']     # négatif
        ei  = d['ei_arbre_µm']     # négatif

        # Plage totale à représenter (µm) avec marge 20 %
        total = max(ES, -ei) * 1.25 + 1.0
        marge_g = 90   # px à gauche pour labels
        marge_d = 10
        marge_h = 12
        marge_b = 24

        zone_w = W - marge_g - marge_d
        zone_h = H - marge_h - marge_b

        def y_of(val_µm):
            """val_µm > 0 → au-dessus du zéro → y plus petit."""
            frac = val_µm / total
            return marge_h + zone_h * 0.5 - frac * zone_h * 0.5

        y0 = int(y_of(0))

        # ── Ligne zéro ───────────────────────────────────────────────────
        pen0 = QPen(QColor('#444444'), 1.5)
        p.setPen(pen0)
        p.drawLine(marge_g - 5, y0, W - marge_d, y0)

        # ── Bande alésage H (bleu) ────────────────────────────────────────
        y_ES = int(y_of(ES))
        y_EI = int(y_of(EI))
        rect_H = QRectF(marge_g, y_ES, zone_w * 0.45, y_EI - y_ES)
        p.fillRect(rect_H, QColor(100, 150, 220, 160))
        p.setPen(QPen(QColor(60, 100, 180), 1))
        p.drawRect(rect_H)

        # ── Bande arbre f/g (rouge) ───────────────────────────────────────
        y_es = int(y_of(es))
        y_ei = int(y_of(ei))
        rect_A = QRectF(marge_g + zone_w * 0.55, y_es, zone_w * 0.45, y_ei - y_es)
        p.fillRect(rect_A, QColor(220, 90, 80, 160))
        p.setPen(QPen(QColor(180, 50, 40), 1))
        p.drawRect(rect_A)

        # ── Flèches jeu min / jeu max ─────────────────────────────────────
        x_fl = int(marge_g + zone_w * 0.5)
        # jeu_min : de y_EI à y_es  (deux bandes se rapprochent)
        jeu_min = d['jeu_min_µm']
        jeu_max = d['jeu_max_µm']

        pen_jeu = QPen(QColor('#226600'), 1, Qt.DashLine)
        p.setPen(pen_jeu)
        p.drawLine(x_fl, y_EI, x_fl, y_es)

        # ── Labels texte ──────────────────────────────────────────────────
        fnt_small = QFont()
        fnt_small.setPointSize(7)
        fnt_bold  = QFont()
        fnt_bold.setPointSize(8)
        fnt_bold.setBold(True)

        p.setFont(fnt_small)
        p.setPen(QColor('#333333'))

        # Côté gauche : labels valeurs µm
        def lbl_left(val, y, color='#333333'):
            p.setPen(QColor(color))
            txt = f"{val:+.1f} µm"
            p.drawText(0, y - 8, marge_g - 4, 16, Qt.AlignRight | Qt.AlignVCenter, txt)

        lbl_left(ES,  y_ES,  '#3355aa')
        lbl_left(EI,  y_EI,  '#3355aa')
        lbl_left(es,  y_es,  '#aa2222')
        lbl_left(ei,  y_ei,  '#aa2222')

        # Étiquette alésage
        p.setPen(QColor('#3355aa'))
        p.setFont(fnt_bold)
        cx_H = int(marge_g + zone_w * 0.225)
        p.drawText(cx_H - 25, marge_h, 50, 14, Qt.AlignCenter,
                   f"Ø H{d['grade_alesage']}")

        # Étiquette arbre
        p.setPen(QColor('#aa2222'))
        cx_A = int(marge_g + zone_w * 0.775)
        p.drawText(cx_A - 30, marge_h, 60, 14, Qt.AlignCenter,
                   f"∅ {d['lettre'].upper()}{d['grade_arbre']}")

        # Jeux
        p.setFont(fnt_small)
        p.setPen(QColor('#226600'))
        y_mid = int((y_EI + y_es) / 2)
        p.drawText(x_fl + 3, y_mid - 8, 70, 14, Qt.AlignLeft | Qt.AlignVCenter,
                   f"j min={jeu_min:.1f} µm")
        p.drawText(x_fl + 3, y_mid + 4, 70, 14, Qt.AlignLeft | Qt.AlignVCenter,
                   f"j max={jeu_max:.1f} µm")

        # Désignation centrale en bas
        p.setFont(fnt_bold)
        p.setPen(QColor('#222222'))
        p.drawText(0, H - marge_b, W, marge_b,
                   Qt.AlignCenter, d['designation'])

        p.end()


class WidgetSelectBody(QtWidgets.QGroupBox):
    """
    Widget de sélection d'un Body et de son paramètre diamètre/rayon.

    Étape 1a : accepte une liste pre-filtree de bodies via le constructeur
    ou via set_bodies() (refresh dynamique pour exclusion du body principal).
    """

    def __init__(self, titre, doc, bodies=None, parent=None):
        """
        Paramètres
        ----------
        titre   : titre du QGroupBox
        doc     : document FreeCAD actif
        bodies  : liste pre-filtree de bodies (None = tous les bodies du doc)
        parent  : widget parent Qt
        """
        super().__init__(titre, parent)
        self._doc    = doc
        # Utilise la liste fournie ou repli sur la liste complète
        self._bodies = bodies if bodies is not None else lister_bodies(doc)

        layout = QtWidgets.QFormLayout(self)

        self.combo_body = QtWidgets.QComboBox()
        layout.addRow("Body :", self.combo_body)

        self.combo_param = QtWidgets.QComboBox()
        self.combo_param.addItem("— selectionner —", None)
        layout.addRow("Paramètre Ø :", self.combo_param)

        self.radio_diametre = QtWidgets.QRadioButton("Diametre")
        self.radio_rayon    = QtWidgets.QRadioButton("Rayon")
        self.radio_diametre.setChecked(True)
        grp = QtWidgets.QButtonGroup(self)
        grp.addButton(self.radio_diametre)
        grp.addButton(self.radio_rayon)
        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.radio_diametre)
        hl.addWidget(self.radio_rayon)
        layout.addRow("Le parametre est un :", hl)

        self.label_valeur = QtWidgets.QLabel("—")
        layout.addRow("Valeur lue :", self.label_valeur)

        # Connexions avant _peupler_combo_body pour que _on_body_change
        # trouve combo_param déjà créé lors de l'auto-sélection initiale
        self.combo_body.currentIndexChanged.connect(self._on_body_change)
        self.combo_param.currentIndexChanged.connect(self._on_param_change)
        self.radio_diametre.toggled.connect(self._on_param_change)

        # Peuplement en dernier : déclenche éventuellement l'auto-sélection
        self._peupler_combo_body(self._bodies)

    # ------------------------------------------------------------------
    # Gestion de la liste de bodies (étape 1a)
    # ------------------------------------------------------------------

    def _peupler_combo_body(self, bodies):
        """Peuple le combo body depuis une liste de bodies.
        Auto-sélectionne si un seul body disponible."""
        self.combo_body.clear()
        self.combo_body.addItem("— selectionner —", None)
        for b in bodies:
            self.combo_body.addItem(b.Label, b)
        # Auto-sélection si un seul choix possible
        if len(bodies) == 1:
            self.combo_body.setCurrentIndex(1)

    def set_bodies(self, bodies):
        """
        Rafraîchit la liste des bodies disponibles (étape 1a).
        Conserve la sélection courante si elle est encore dans la nouvelle liste.
        Utilisé pour l'exclusion dynamique du body principal dans le widget
        complémentaire.
        """
        body_courant = self.combo_body.currentData()
        self.combo_body.blockSignals(True)
        self._bodies = bodies
        self._peupler_combo_body(bodies)
        # Restaurer la sélection précédente si elle est toujours disponible
        if body_courant is not None:
            for i in range(self.combo_body.count()):
                if self.combo_body.itemData(i) is body_courant:
                    self.combo_body.setCurrentIndex(i)
                    break
        self.combo_body.blockSignals(False)
        self._on_body_change(0)

    # ------------------------------------------------------------------
    def _on_body_change(self, _):
        body = self.combo_body.currentData()
        self.combo_param.blockSignals(True)
        self.combo_param.clear()
        self.combo_param.addItem("— selectionner —", None)
        if body:
            params = lister_parametres_body(body)
            for nom in sorted(params.keys()):
                val = params[nom]
                self.combo_param.addItem(f"{nom}  ({val:.3f} mm)", nom)
            # Auto-sélection si un seul paramètre disponible
            if len(params) == 1:
                self.combo_param.setCurrentIndex(1)
        self.combo_param.blockSignals(False)
        self._on_param_change()

    def _auto_radio_depuis_nom(self, nom: str):
        """
        Pré-coche radio Rayon si nom commence par R/r,
        Diamètre si D/d. Ignore les autres préfixes.
        Bloque les signaux pour ne pas déclencher de recalcul prématuré.
        """
        if not nom:
            return
        premier = nom[0].lower()
        if premier == 'r':
            self.radio_rayon.blockSignals(True)
            self.radio_diametre.blockSignals(True)
            self.radio_rayon.setChecked(True)
            self.radio_rayon.blockSignals(False)
            self.radio_diametre.blockSignals(False)
        elif premier == 'd':
            self.radio_rayon.blockSignals(True)
            self.radio_diametre.blockSignals(True)
            self.radio_diametre.setChecked(True)
            self.radio_rayon.blockSignals(False)
            self.radio_diametre.blockSignals(False)
        # Autres préfixes → ne pas toucher au radio courant

    def _on_param_change(self, _=None):
        nom  = self.combo_param.currentData()
        body = self.combo_body.currentData()
        if nom and body:
            # Auto-détecter rayon/diamètre selon le préfixe du nom (#R/D)
            self._auto_radio_depuis_nom(nom)
            params = lister_parametres_body(body)
            val    = params.get(nom)
            if val is not None:
                if self.radio_rayon.isChecked():
                    self.label_valeur.setText(
                        f"r {val:.2f} mm  →  Ø {val*2:.2f} mm"
                    )
                else:
                    self.label_valeur.setText(f"Ø {val:.2f} mm")
                return
        self.label_valeur.setText("—")

    def get_diametre_mm(self):
        nom  = self.combo_param.currentData()
        body = self.combo_body.currentData()
        if not nom or not body:
            return None
        params = lister_parametres_body(body)
        val    = params.get(nom)
        if val is None:
            return None
        return val * 2.0 if self.radio_rayon.isChecked() else val

    def get_body(self):
        return self.combo_body.currentData()

    def get_nom_parametre(self):
        return self.combo_param.currentData()

    def est_en_rayon(self):
        return self.radio_rayon.isChecked()

    def est_complete(self):
        return (self.combo_body.currentData() is not None
                and self.combo_param.currentData() is not None)


# =============================================================================
# DIALOGUE PRINCIPAL
# =============================================================================

def _lcs_deja_utilises(doc) -> set:
    """
    Retourne l'ensemble des Labels de LCS déjà référencés par un App::Part ORing
    existant dans le document.  Ces LCS sont exclus du combo de sélection.
    """
    if doc is None:
        return set()
    try:
        from .metadata import lister_parts_oring
        utilises = set()
        for part in lister_parts_oring(doc):
            label = getattr(part, 'lcs_label', None)
            if label:
                utilises.add(label)
        return utilises
    except Exception:
        return set()


# =============================================================================
# HIGHLIGHT BODY ORING AU SURVOL DU TABLEAU
# =============================================================================

# Snapshot complet des états visuels au lancement de la macro
# {obj_name: {'ShapeColor': ..., 'Transparency': ...}}
# Pris une seule fois au démarrage, restauré à la fermeture.
_visual_snapshot = {}
# États modifiés lors du hover courant (sous-ensemble de _visual_snapshot)
_hover_saved = {}


def _prendre_snapshot(doc):
    """Sauvegarde l'état visuel de tous les bodies du document."""
    _visual_snapshot.clear()
    if doc is None:
        return
    try:
        for obj in doc.Objects:
            if obj.TypeId == 'PartDesign::Body':
                try:
                    vo = obj.ViewObject
                    _visual_snapshot[obj.Name] = {
                        'ShapeColor':   tuple(getattr(vo, 'ShapeColor',   (0.8, 0.8, 0.8))),
                        'Transparency': int(getattr(vo, 'Transparency', 0)),
                    }
                except Exception:
                    pass
    except Exception as e:
        print(f"[ORing snapshot] {e}")


def _restaurer_snapshot(doc):
    """Restaure exactement l'état visuel capturé au lancement.
    Les bodies créés APRÈS le snapshot (nouveaux joints) sont aussi remis
    à Transparency=0 pour éviter les transparences résiduelles du hover.
    """
    if doc is None:
        return
    try:
        for obj in doc.Objects:
            if obj.TypeId != 'PartDesign::Body':
                continue
            try:
                vo   = obj.ViewObject
                saved = _visual_snapshot.get(obj.Name)
                if saved:
                    vo.ShapeColor   = saved['ShapeColor']
                    vo.Transparency = saved['Transparency']
                else:
                    # Body créé après le snapshot → remettre opaque sans changer la couleur
                    vo.Transparency = 0
            except Exception:
                pass
        _hover_saved.clear()
    except Exception as e:
        print(f"[ORing snapshot restaurer] {e}")


def _hover_appliquer(part, doc):
    """
    Survol d'une ligne du tableau :
    - Body ORing : couleur jaune vif, opaque, DrawStyle Solid
    - Autres bodies du doc : mis à 80 % de transparence (effet "premier plan")
    """
    if part is None or doc is None:
        return
    try:
        import FreeCADGui as Gui
        # Trouver le body ORing dans le Part
        body_oring = None
        for child in getattr(part, 'Group', []):
            if child.TypeId == 'PartDesign::Body' and child.Label.startswith('ORing'):
                body_oring = child
                break
        if body_oring is None:
            return

        # Mettre en transparence tous les autres bodies visibles
        for obj in doc.Objects:
            if (obj.TypeId == 'PartDesign::Body'
                    and obj is not body_oring
                    and getattr(obj, 'Visibility', False)):
                try:
                    vo = obj.ViewObject
                    _hover_saved[obj.Name] = {
                        'Transparency': getattr(vo, 'Transparency', 0),
                    }
                    vo.Transparency = 80
                except Exception:
                    pass

        # Highlight du body ORing
        vo_o = body_oring.ViewObject
        _hover_saved[body_oring.Name] = {
            'ShapeColor':   getattr(vo_o, 'ShapeColor',   (0.8, 0.8, 0.8)),
            'Transparency': getattr(vo_o, 'Transparency', 0),
        }
        vo_o.ShapeColor   = (1.0, 0.85, 0.0)   # jaune vif
        vo_o.Transparency = 0                    # opaque
        # Sélection dans la vue 3D
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body_oring.Name)
    except Exception as e:
        print(f"[ORing hover] appliquer : {e}")


def _hover_retirer(doc):
    """
    Fin de survol : restaure l'état visuel depuis le snapshot de lancement.
    """
    if doc is None:
        return
    try:
        import FreeCADGui as Gui
        # Restaurer depuis le snapshot (source de vérité)
        # Les bodies absents du snapshot (créés pendant la session) → Transparency=0
        for obj in doc.Objects:
            if obj.TypeId != 'PartDesign::Body':
                continue
            try:
                vo    = obj.ViewObject
                saved = _visual_snapshot.get(obj.Name)
                if saved:
                    vo.ShapeColor   = saved['ShapeColor']
                    vo.Transparency = saved['Transparency']
                else:
                    vo.Transparency = 0
            except Exception:
                pass
        _hover_saved.clear()
        Gui.Selection.clearSelection()
    except Exception as e:
        print(f"[ORing hover] retirer : {e}")


# Fonctions alias conservés pour compatibilité interne
def _appliquer_highlight_body_oring(part, doc): pass
def _retirer_highlight_body_oring(part, doc):   pass



class _TableJointsHover(QtWidgets.QTableWidget):
    """
    QTableWidget avec highlight hover :
    - mouseMoveEvent : highlight de la ligne sous le curseur
    - leaveEvent     : restaure toutes les propriétés
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)   # recevoir mouseMoveEvent sans bouton pressé
        self._hover_row    = -1       # dernière ligne survolée
        self._locked_row   = -1       # ligne verrouillée par clic (-1 = aucune)
        self._hover_doc    = None     # document FreeCAD courant (injecté par dialogue)
        self._hover_parts  = []       # liste ordonnée des Parts (index = ligne)

    def mouseMoveEvent(self, event):
        # Si une ligne est verrouillée par clic, le hover est suspendu
        if self._locked_row >= 0:
            super().mouseMoveEvent(event)
            return
        row = self.rowAt(event.pos().y())
        if row != self._hover_row:
            if self._hover_row >= 0:
                _hover_retirer(self._hover_doc)
            self._hover_row = row
            if 0 <= row < len(self._hover_parts):
                _hover_appliquer(self._hover_parts[row], self._hover_doc)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._locked_row >= 0:
            # Ligne verrouillée : le highlight RESTE jusqu'au clic Modifier.
            # On ne touche ni au highlight ni au verrou.
            pass
        elif self._hover_row >= 0:
            _hover_retirer(self._hover_doc)
        self._hover_row = -1
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        row = self.rowAt(event.pos().y())
        if row >= 0:
            if self._locked_row == row:
                # Second clic sur la ligne verrouillée : déverrouiller et déselectionner.
                # On consomme l'événement (sans super()) pour éviter que Qt re-sélectionne
                # la ligne après le clearSelection().
                _hover_retirer(self._hover_doc)
                self._locked_row = -1
                self.selectionModel().clearSelection()
                # Passer en mode hover sur la ligne courante
                self._hover_row = row
                if 0 <= row < len(self._hover_parts):
                    _hover_appliquer(self._hover_parts[row], self._hover_doc)
                return   # ne pas appeler super() — évite la re-sélection Qt
            else:
                # Nouveau clic : changer de ligne verrouillée
                if self._locked_row >= 0:
                    _hover_retirer(self._hover_doc)
                if 0 <= row < len(self._hover_parts):
                    _hover_appliquer(self._hover_parts[row], self._hover_doc)
                self._locked_row = row
                self._hover_row  = -1
        else:
            # Clic en dehors des lignes : déverrouiller
            if self._locked_row >= 0:
                _hover_retirer(self._hover_doc)
                self._locked_row = -1
        super().mousePressEvent(event)

    def enterEvent(self, event):
        """Activation du hover dès l'entrée dans le tableau (sans clic préalable)."""
        # Forcer un mouseMoveEvent synthétique pour déclencher le hover immédiatement
        # si une ligne est sous le curseur à l'entrée de l'onglet 3.
        super().enterEvent(event)
        if self._locked_row >= 0:
            return  # ligne verrouillée — pas de hover libre
        try:
            from PySide2.QtGui import QCursor
            pos_global = QCursor.pos()
            pos_local  = self.viewport().mapFromGlobal(pos_global)
            row = self.rowAt(pos_local.y())
            if row >= 0 and row != self._hover_row:
                if self._hover_row >= 0:
                    _hover_retirer(self._hover_doc)
                self._hover_row = row
                if 0 <= row < len(self._hover_parts):
                    _hover_appliquer(self._hover_parts[row], self._hover_doc)
        except Exception:
            pass

    def deverrouiller(self):
        """Appelé depuis le dialogue pour retirer le highlight verrouillé."""
        if self._locked_row >= 0:
            _hover_retirer(self._hover_doc)
            self._locked_row = -1
            self._hover_row  = -1


class DialogueORing(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ORing — Dimensionnement joint torique")
        self.setMinimumWidth(620)
        self.setModal(True)
        self._resultat            = None
        self._part_en_modification = None   # None = mode création, Part = mode modif
        self._parts_liste          = []     # index ligne → Part (onglet 3)
        self._d_comp_ref_modif     = 0.0    # diamètre de référence en mode modif
        self._calcul_en_cours      = False  # garde anti-réentrance calcul
        self._appliquer_en_cours   = False  # garde anti-réentrance _on_appliquer
        self._onglet_init_en_cours = False  # garde anti-réentrance _onglet_initial
        self._dernier_radio_rayon  = False  # mémoire radio diam/rayon (#8)

        try:
            self._doc = get_document_actif()
        except RuntimeError as e:
            message_erreur("ORing", str(e))
            self._doc = None

        # Snapshot de l'état visuel initial — restauré à la fermeture
        _prendre_snapshot(self._doc)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        """
        3 onglets (mars 2026) :
          Onglet 1 — Contexte + Matériau
          Onglet 2 — Pièces FreeCAD + Joint/Gorge + synthèse résultats (A)
          Onglet 3 — Joints existants dans le document (B)
          Boutons   — hors onglets, toujours visibles en pied
        """
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── Onglets ───────────────────────────────────────────────────────
        tabs = QtWidgets.QTabWidget()
        self._tabs = tabs
        outer.addWidget(tabs, stretch=1)

        # — Onglet 1 : Contexte + Matériau ─────────────────────────────
        w1 = QtWidgets.QWidget()
        v1 = QtWidgets.QVBoxLayout(w1)
        v1.setSpacing(6)
        v1.addWidget(self._section_contexte())
        v1.addWidget(self._section_materiau())
        v1.addStretch()
        tabs.addTab(w1, "1 · Contexte / Matériau")

        # — Onglet 2 : Pièces + Joint/Gorge + synthèse résultats ───────
        w2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(w2)
        v2.setSpacing(6)
        v2.addWidget(self._section_pieces())
        v2.addWidget(self._section_joint())
        v2.addWidget(self._section_synthese())   # (A) résultats de gorge
        # (B) Analyse tolérances IT — désactivée temporairement
        v2.addStretch()
        tabs.addTab(w2, "2 · Pièces / Joint / Résultats")

        # — Onglet 3 : Joints existants ────────────────────────────────
        w3 = QtWidgets.QWidget()
        v3 = QtWidgets.QVBoxLayout(w3)
        v3.setSpacing(6)
        v3.addWidget(self._section_joints_existants())   # (B) tableau
        tabs.addTab(w3, "3 · Joints existants")

        # Rafraîchir l'onglet 3 à l'activation
        tabs.currentChanged.connect(self._on_tab_change)

        # ── Boutons (hors onglets) ────────────────────────────────────────
        bl = QtWidgets.QHBoxLayout()
        self.btn_appliquer = QtWidgets.QPushButton("Appliquer dans FreeCAD")
        self.btn_fermer    = QtWidgets.QPushButton("Fermer")
        self.btn_appliquer.setEnabled(False)

        self.btn_appliquer.clicked.connect(self._on_appliquer)
        self.btn_fermer.clicked.connect(self.reject)
        bl.addWidget(self.btn_appliquer)
        bl.addStretch()
        bl.addWidget(self.btn_fermer)
        outer.addLayout(bl)

    def _onglet_initial(self, derives_precalcules=None):
        """
        Détermine l'onglet à afficher à l'ouverture du dialogue.
        Si au moins une dérive est détectée, bascule sur l'onglet 3
        pour alerter l'utilisateur dès l'ouverture.
        Appelée juste avant exec_().

        Note : setCurrentIndex() doit être différé via QTimer.singleShot(0)
        car exec_() n'a pas encore démarré la boucle d'événements Qt au moment
        de l'appel. Sans ce délai, le changement d'onglet est ignoré.
        """
        if self._onglet_init_en_cours:
            print("[ORing onglet3] _onglet_initial réentrant ignoré")
            return
        self._onglet_init_en_cours = True
        try:
            from .metadata import verifier_derives, lister_parts_oring
            doc = self._doc
            if doc is None:
                return
            # Réutiliser un calcul déjà fait (évite le double verifier_derives)
            derives = derives_precalcules if derives_precalcules is not None else verifier_derives(doc)
            nb_derives = sum(1 for d in derives if d.get('derive'))
            if nb_derives > 0:
                def _basculer():
                    self._rafraichir_joints_existants()
                    self._tabs.setCurrentIndex(2)
                QtCore.QTimer.singleShot(0, _basculer)
            else:
                # Pré-remplir le tableau même sans dérive (onglet 3 prêt à consulter)
                QtCore.QTimer.singleShot(0, self._rafraichir_joints_existants)
        except Exception:
            import traceback
            print(f"[ORing onglet3] _onglet_initial ERREUR :\n{traceback.format_exc()}")
            QtCore.QTimer.singleShot(0, self._rafraichir_joints_existants)
        finally:
            self._onglet_init_en_cours = False

    # ------------------------------------------------------------------
    # A — Synthèse résultats (widget structuré)
    # ------------------------------------------------------------------
    def _section_synthese(self):
        """
        GroupBox 'Résultats du calcul' avec grille de labels colorés.
        Remplace l'ancien QTextEdit zone_resultats.

        Lignes affichées :
          Joint      : standard · série — Ø d2  [code]
          d1         : valeur mm   stretch X.X %
          Gorge      : h = X.XXX mm   b = X.XXX mm
          Squeeze    : XX.X %   Fill : XX.X %
          Ø fond     : XX.XX mm
          Extrusion  : Faible / Modéré / Élevé [BAGUE REQUISE]
          ──────────────────────────────────────
          Statut     : ✓ VALIDE  /  ✗ INVALIDE
          Alertes    : liste rouge
          Avertiss.  : liste orange
        """
        grp = QtWidgets.QGroupBox("Résultats du calcul")
        grid = QtWidgets.QGridLayout(grp)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 6, 8, 6)

        def _lbl_val():
            """Label valeur : gras, agrandit si nécessaire."""
            lbl = QtWidgets.QLabel("—")
            lbl.setMinimumWidth(240)
            return lbl

        etiquettes = [
            ("Joint",     "Joint sélectionné (standard / série / d2)"),
            ("d1",        "Diamètre intérieur joint + étirement"),
            ("Gorge",     "Profondeur h et largeur b de la gorge"),
            ("Squeeze",   "Taux de serrage réel et taux de remplissage"),
            ("Ø fond",    "Diamètre au fond de gorge"),
            ("Extrusion", "Risque d'extrusion"),
        ]
        self._synth_vals = {}
        for row, (etiq, tip) in enumerate(etiquettes):
            lbl_e = QtWidgets.QLabel(etiq + " :")
            lbl_e.setStyleSheet("font-size: 9pt;")
            lbl_e.setToolTip(tip)
            lbl_v = _lbl_val()
            grid.addWidget(lbl_e, row, 0)
            grid.addWidget(lbl_v, row, 1)
            self._synth_vals[etiq] = lbl_v

        # Séparateur horizontal
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        grid.addWidget(sep, len(etiquettes), 0, 1, 2)

        # Ligne statut
        self.lbl_synth_statut = QtWidgets.QLabel("En attente de calcul…")
        self.lbl_synth_statut.setStyleSheet(
            "font-weight: bold; font-size: 10pt;"
        )
        grid.addWidget(self.lbl_synth_statut, len(etiquettes) + 1, 0, 1, 2)

        # Zone alertes / avertissements (QLabel multiligne)
        self.lbl_synth_alertes = QtWidgets.QLabel("")
        self.lbl_synth_alertes.setWordWrap(True)
        self.lbl_synth_alertes.hide()
        grid.addWidget(self.lbl_synth_alertes, len(etiquettes) + 2, 0, 1, 2)

        return grp

    def _section_tolerances(self):
        """Tolérances ISO 286-1 — désactivées temporairement."""
        import sys
        class _Stub:
            def hide(self): pass
            def show(self): pass
        return _Stub()
    def _maj_synthese(self, r):
        """
        Met à jour tous les labels de _section_synthese() depuis le résultat r.
        Appelé depuis _on_calculer().
        """
        position = self.combo_position.currentData()
        label_d  = "D_fond" if position == 'arbre' else "D_arbre"

        # ── Joint ──
        if r.d2 is not None:
            txt_joint = f"{r.standard} · {r.serie} — Ø {r.d2} mm"
            if r.code_joint:
                txt_joint += f"  [{r.code_joint}]"
            self._synth_vals["Joint"].setText(txt_joint)
            self._synth_vals["Joint"].setStyleSheet("")
        else:
            self._synth_vals["Joint"].setText("—")

        # ── d1 + stretch ──
        if r.d1 is not None and r.stretch_pct is not None:
            st = r.stretch_pct
            txt_d1 = f"{r.d1} mm   ({label_d}) stretch {st:.2f} %"
            if st > 5.0:
                style = "color: #cc0000; font-weight: bold;"
            elif st > 3.0:
                style = "color: #b05000; font-weight: bold;"
            elif st < 0:
                style = "color: #cc0000; font-weight: bold;"
            else:
                style = "color: #1a7a1a; font-weight: bold;"
            self._synth_vals["d1"].setText(txt_d1)
            self._synth_vals["d1"].setStyleSheet(style)
        else:
            self._synth_vals["d1"].setText("—")
            self._synth_vals["d1"].setStyleSheet("")

        # ── Gorge (h, b) ──
        if r.h is not None and r.b is not None:
            self._synth_vals["Gorge"].setText(
                f"h = {r.h:.3f} mm   b = {r.b:.3f} mm"
            )
            self._synth_vals["Gorge"].setStyleSheet("")
        else:
            self._synth_vals["Gorge"].setText("—")

        # ── Squeeze + Fill ──
        if r.squeeze_pct is not None and r.fill_pct is not None:
            sq   = r.squeeze_pct
            fill = r.fill_pct
            # fill : vert si 75–85% statique / 65–75% dynamique ; orange sinon
            fill_ok = (70 <= fill <= 90)
            fill_style = "" if fill_ok else "color: #b05000;"
            self._synth_vals["Squeeze"].setText(
                f"squeeze {sq:.1f} %   fill {fill:.1f} %"
            )
            self._synth_vals["Squeeze"].setStyleSheet(fill_style)
        else:
            self._synth_vals["Squeeze"].setText("—")
            self._synth_vals["Squeeze"].setStyleSheet("")

        # ── Ø fond de gorge ──
        if r.rayon_gorge is not None:
            self._synth_vals["Ø fond"].setText(
                f"{r.rayon_gorge * 2:.4f} mm"
            )
        else:
            self._synth_vals["Ø fond"].setText("—")

        # ── Extrusion ──
        if r.risque_extrusion:
            txt_ext = str(r.risque_extrusion)
            if r.bague_antiextrusion:
                txt_ext += "   ⚠ BAGUE ANTI-EXTRUSION REQUISE"
                style_ext = "color: #cc0000; font-weight: bold;"
            elif "lev" in txt_ext.lower():
                style_ext = "color: #cc6600;"
            else:
                style_ext = "color: #1a7a1a;"
            self._synth_vals["Extrusion"].setText(txt_ext)
            self._synth_vals["Extrusion"].setStyleSheet(style_ext)
        else:
            self._synth_vals["Extrusion"].setText("—")
            self._synth_vals["Extrusion"].setStyleSheet("")

        # ── Statut global ──
        if r.valide:
            self.lbl_synth_statut.setText("✓  VALIDE")
            self.lbl_synth_statut.setStyleSheet(
                "font-weight: bold; font-size: 10pt; color: #1a7a1a;"
            )
        else:
            self.lbl_synth_statut.setText("✗  INVALIDE — voir alertes")
            self.lbl_synth_statut.setStyleSheet(
                "font-weight: bold; font-size: 10pt; color: #cc0000;"
            )

        # ── Alertes + avertissements ──
        lignes = []
        for a in (r.alertes or []):
            lignes.append(f'<span style="color:#cc0000;">⛔ {a}</span>')
        for a in (r.avertissements or []):
            lignes.append(f'<span style="color:#b05000;">⚠ {a}</span>')
        if lignes:
            self.lbl_synth_alertes.setText("<br>".join(lignes))
            self.lbl_synth_alertes.show()
        else:
            self.lbl_synth_alertes.setText("")
            self.lbl_synth_alertes.hide()

    def _maj_tolerances(self, r):
        """Tolérances ISO 286-1 — désactivées temporairement."""
        pass

    def _section_joints_existants(self):
        """
        GroupBox contenant un QTableWidget listant tous les App::Part
        ORing du document courant, avec leurs métadonnées principales
        et un indicateur de dérive paramétrique.
        """
        grp = QtWidgets.QGroupBox("Joints O-Ring insérés dans ce document")
        vl  = QtWidgets.QVBoxLayout(grp)
        vl.setSpacing(6)

        # Barre de contrôle
        hl = QtWidgets.QHBoxLayout()
        self.lbl_joints_nb = QtWidgets.QLabel("Aucun joint trouvé.")
        self.lbl_joints_nb.setStyleSheet("font-style: italic;")

        # Filtre position
        self.combo_filtre_position = QtWidgets.QComboBox()
        self.combo_filtre_position.addItem("Tous",    "")
        self.combo_filtre_position.addItem("Arbre",   "arbre")
        self.combo_filtre_position.addItem("Alésage", "alesage")
        self.combo_filtre_position.setFixedWidth(90)
        self.combo_filtre_position.setToolTip("Filtrer par position de gorge")
        self.combo_filtre_position.currentIndexChanged.connect(
            self._on_filtre_position_change
        )

        self.btn_refresh_joints = QtWidgets.QPushButton("↻  Rafraîchir")
        self.btn_refresh_joints.setFixedWidth(110)
        self.btn_refresh_joints.clicked.connect(self._rafraichir_joints_existants)
        self.btn_recalibrer_couleurs = QtWidgets.QPushButton("🎨  Couleurs")
        self.btn_recalibrer_couleurs.setFixedWidth(110)
        self.btn_recalibrer_couleurs.setToolTip(
            "Recolorie tous les joints selon leur matériau.\n"
            "Utile si des couleurs sont incorrectes ou manquantes."
        )
        self.btn_recalibrer_couleurs.clicked.connect(self._on_recalibrer_couleurs)
        self.btn_modifier_joint = QtWidgets.QPushButton("✎  Modifier")
        self.btn_modifier_joint.setFixedWidth(110)
        self.btn_modifier_joint.setEnabled(False)
        self.btn_modifier_joint.setToolTip(
            "Pré-remplit le dialogue avec les paramètres du joint sélectionné "
            "pour les modifier et régénérer la gorge.\n"            "Double-clic sur une ligne produit le même effet."
        )
        self.btn_modifier_joint.clicked.connect(self._on_clic_modifier)
        hl.addWidget(self.lbl_joints_nb)
        hl.addStretch()
        hl.addWidget(QtWidgets.QLabel("Position :"))
        hl.addWidget(self.combo_filtre_position)
        hl.addWidget(self.btn_modifier_joint)
        hl.addWidget(self.btn_recalibrer_couleurs)
        hl.addWidget(self.btn_refresh_joints)
        vl.addLayout(hl)

        # Tableau
        COLONNES = [
            "", "Position", "LCS", "Body gorge",
            "Std / Série", "d2 (mm)", "d1 (mm)",
            "h (mm)", "b (mm)", "Squeeze %", "Fill %",
            "Δ dérive"
        ]
        self.table_joints = _TableJointsHover(0, len(COLONNES))
        self.table_joints.setHorizontalHeaderLabels(COLONNES)
        self.table_joints.setEditTriggers(
            QtWidgets.QTableWidget.NoEditTriggers
        )
        self.table_joints.setSelectionBehavior(
            QtWidgets.QTableWidget.SelectRows
        )
        self.table_joints.setAlternatingRowColors(True)
        self.table_joints.verticalHeader().setVisible(False)
        self.table_joints.selectionModel().selectionChanged.connect(
            self._on_selection_joint_change
        ) if hasattr(self.table_joints, 'selectionModel') else None
        # Double-clic → Modifier directement
        self.table_joints.doubleClicked.connect(
            lambda _: self._on_clic_modifier()
        )
        try:
            hdr = self.table_joints.horizontalHeader()
            hdr.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
            hdr.setStretchLastSection(True)
            # Tri par colonne au clic sur l'en-tête
            self.table_joints.setSortingEnabled(True)
            hdr.setSortIndicatorShown(True)
        except Exception:
            pass
        vl.addWidget(self.table_joints)

        # Note explicative — masquée par défaut, affichée si dérive détectée
        self.lbl_note_derive = QtWidgets.QLabel(
            "⚠ = le diamètre de la pièce complémentaire a changé depuis l'insertion "
            "— cliquer Modifier pour recalculer automatiquement."
        )
        self.lbl_note_derive.setStyleSheet("font-size: 8pt;")
        self.lbl_note_derive.setWordWrap(True)
        self.lbl_note_derive.hide()   # cachée jusqu'à ce qu'une dérive existe
        vl.addWidget(self.lbl_note_derive)

        return grp

    def _rafraichir_joints_existants(self):
        """
        Relit les App::Part ORing du document et remplit table_joints.
        Appelle verifier_derives() pour détecter les dérives.
        """
        try:
            from .metadata import lister_parts_oring, lire_metadonnees, verifier_derives
        except ImportError:
            return

        doc = self._doc
        self.table_joints.setRowCount(0)

        if doc is None:
            self.lbl_joints_nb.setText("Aucun document FreeCAD actif.")
            self._parts_liste = []
            return

        try:
            self._rafraichir_joints_existants_interne(
                doc, lister_parts_oring, lire_metadonnees, verifier_derives
            )
        except Exception as _e_raf:
            import traceback
            print(f"[ORing onglet3] ERREUR _rafraichir_joints_existants :\n"
                  f"{traceback.format_exc()}")
            self.lbl_joints_nb.setText(
                f"Erreur de rafraîchissement : {_e_raf}\n"
                "(voir console FreeCAD)"
            )

    def _rafraichir_joints_existants_interne(
            self, doc, lister_parts_oring, lire_metadonnees, verifier_derives):
        """Corps de _rafraichir_joints_existants, isolé pour traçabilité des exceptions."""
        derives_info = {}
        try:
            derives_info = {
                d['part'].Name: d for d in verifier_derives(doc)
            }
        except Exception as _e_derive:
            print(f"[ORing onglet3] verifier_derives exception : {_e_derive}")
            # derives_info reste {} : les joints seront affichés sans statut dérive

        parts = lister_parts_oring(doc)
        nb = len(parts)
        self._parts_liste = list(parts)
        # Désactiver le tri pendant le remplissage (évite les décalages d'index)
        self.table_joints.setSortingEnabled(False)   # mémorise pour _on_clic_modifier
        # Injecter immédiatement dans la table pour que le hover soit opérationnel
        # dès l'activation de l'onglet, sans attendre un clic ou une sélection.
        self.table_joints._hover_doc   = self._doc
        self.table_joints._hover_parts = list(parts)

        for idx, part in enumerate(parts):
            meta  = lire_metadonnees(part)
            deriv = derives_info.get(part.Name, {})

            a_derive = deriv.get('derive', False)
            delta     = deriv.get('delta') if a_derive else None

            # Col 0 : icône statut (⚠ danger ou ✓ OK)
            if a_derive:
                icone_txt = "⚠"
                icone_color = QtGui.QColor(200, 80, 0)
                tooltip_icone = (
                    f"Dérive détectée : Δ {delta:.3f} mm\n"
                    "Le diamètre de la pièce complémentaire a changé\n"
                    "depuis l'insertion. Cliquez Modifier pour recalculer."
                )
            else:
                icone_txt = "✓"
                icone_color = QtGui.QColor(20, 140, 20)
                tooltip_icone = "Dimensions cohérentes avec les métadonnées."

            item_icone = QtWidgets.QTableWidgetItem(icone_txt)
            item_icone.setTextAlignment(QtCore.Qt.AlignCenter)
            item_icone.setForeground(QtGui.QBrush(icone_color))
            item_icone.setFont(
                QtGui.QFont("", 11, QtGui.QFont.Bold)
            )
            item_icone.setToolTip(tooltip_icone)
            item_icone.setFlags(
                item_icone.flags() & ~QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEnabled
            )
            # Stocker le Name du Part en UserRole pour lookup robuste après tri
            item_icone.setData(QtCore.Qt.UserRole, part.Name)

            def _flt(key, defaut=0.0):
                try:
                    return float(meta.get(key, defaut) or defaut)
                except (TypeError, ValueError):
                    return defaut

            vals = [
                None,   # col 0 : réservée à l'icône (insérée ci-dessous)
                str(meta.get('position', '—') or '—'),
                str(meta.get('lcs_label', '—') or '—'),
                str(meta.get('body_gorge_label', '—') or '—'),
                f"{meta.get('standard','?')} · {meta.get('serie','') or '(Auto)' if not meta.get('serie_auto') else 'Auto→' + (meta.get('serie','') or '?')}",
                f"{_flt('d2_mm'):.2f}",
                f"{_flt('d1_mm'):.2f}",
                f"{_flt('h_mm'):.3f}",
                f"{_flt('b_mm'):.3f}",
                f"{_flt('squeeze_reel_pct'):.1f}",
                f"{_flt('fill_pct'):.1f}",
                f"{delta:.3f} mm" if delta is not None else "",
            ]

            self.table_joints.insertRow(idx)
            self.table_joints.setItem(idx, 0, item_icone)
            for col, val in enumerate(vals):
                if col == 0:
                    continue   # déjà posé
                item = QtWidgets.QTableWidgetItem(val)
                item.setTextAlignment(
                    QtCore.Qt.AlignCenter if col != 3 else QtCore.Qt.AlignLeft
                    | QtCore.Qt.AlignVCenter
                )
                self.table_joints.setItem(idx, col, item)

        nb_derives = sum(1 for d in derives_info.values() if d.get('derive'))
        if nb == 0:
            self.lbl_joints_nb.setText("Aucun joint O-Ring inséré dans ce document.")
            if hasattr(self, '_tabs'):
                self._tabs.setTabText(2, "3 · Joints existants")
                try:
                    self._tabs.tabBar().setTabTextColor(2, QtGui.QColor())
                except Exception:
                    pass
        elif nb == 1:
            msg = "1 joint O-Ring trouvé."
            if nb_derives:
                msg += "  ⚠ Dérive détectée — cliquer Modifier pour recalculer."
            self.lbl_joints_nb.setText(msg)
        else:
            msg = f"{nb} joints O-Ring trouvés."
            if nb_derives:
                msg += (f"  ⚠ {nb_derives} dérive(s) détectée(s) — "
                        f"cliquer Modifier pour recalculer.")
            self.lbl_joints_nb.setText(msg)

        # Réactiver le tri après remplissage complet
        self.table_joints.setSortingEnabled(True)
        # Appliquer le filtre position
        self._appliquer_filtre_position()
        # Afficher/masquer la note selon la présence de dérives
        if hasattr(self, 'lbl_note_derive'):
            if nb_derives > 0:
                self.lbl_note_derive.show()
            else:
                self.lbl_note_derive.hide()

        # ── Titre de l'onglet 3 : alerte visuelle si dérives ────────────
        if hasattr(self, '_tabs'):
            if nb_derives > 0:
                titre = f"3 · Joints existants  ⚠ {nb_derives}"
                # Colorer l'onglet en orange pour attirer l'attention
                self._tabs.setTabText(2, titre)
                try:
                    bar = self._tabs.tabBar()
                    bar.setTabTextColor(2, QtGui.QColor(200, 80, 0))
                except Exception:
                    pass
            else:
                self._tabs.setTabText(2, "3 · Joints existants")
                try:
                    bar = self._tabs.tabBar()
                    bar.setTabTextColor(2, QtGui.QColor())  # couleur par défaut
                except Exception:
                    pass

    def _on_filtre_position_change(self, _=None):
        """Applique le filtre de position sur le tableau."""
        self._appliquer_filtre_position()

    def _appliquer_filtre_position(self):
        """Masque les lignes dont la position ne correspond pas au filtre."""
        if not hasattr(self, 'combo_filtre_position') or not hasattr(self, 'table_joints'):
            return
        filtre = self.combo_filtre_position.currentData() or ''
        nb_visibles = 0
        for row in range(self.table_joints.rowCount()):
            if not filtre:
                self.table_joints.setRowHidden(row, False)
                nb_visibles += 1
            else:
                # La position est en colonne 1
                item = self.table_joints.item(row, 1)
                pos_val = (item.text() if item else '').lower()
                visible = (pos_val == filtre)
                self.table_joints.setRowHidden(row, not visible)
                if visible:
                    nb_visibles += 1
        # Mettre à jour le compteur si filtré
        if filtre:
            total = self.table_joints.rowCount()
            self.lbl_joints_nb.setText(
                f"{nb_visibles} / {total} joint(s) affiché(s) — filtre : {filtre}"
            )

    def _on_selection_joint_change(self, *_):
        """Active le bouton Modifier si une ligne est sélectionnée."""
        rows = self.table_joints.selectionModel().selectedRows()
        self.btn_modifier_joint.setEnabled(bool(rows))
        # Injecter doc et liste des Parts dans le tableau pour le hover
        self.table_joints._hover_doc   = self._doc
        self.table_joints._hover_parts = list(self._parts_liste)
        # Déverrouiller si la sélection est vidée (clic en dehors, Échap…)
        if not rows:
            self.table_joints.deverrouiller()

    def _recalculer_apres_derive(self, part, meta: dict, derive_info: dict):
        """
        Appelée lorsque la pièce complémentaire a dérivé par rapport aux métadonnées.

        1. Calcule le nouveau diamètre de la pièce principale (body gorge)
           en appliquant le jeu radial prescrit au diamètre courant de la pièce comp.
        2. Met à jour le paramètre FreeCAD correspondant dans le body gorge.
        3. Recherche le meilleur joint compatible (même série → même norme → autre norme).
        4. Présente un dialogue de confirmation à l'utilisateur.

        Retourne un dict meta mis à jour (pour pre-fill) ou None si annulé / erreur.
        Si l'utilisateur annule, le paramètre FreeCAD est remis à sa valeur initiale.
        """
        try:
            from .calcul  import calculer_gorge
            from .joints  import liste_standards, liste_series, get_plage_squeeze
            from .utils   import set_valeur_parametre, lister_parametres_body
        except ImportError as e:
            print('[ORing dérive] import: ' + str(e))
            return None

        doc          = self._doc
        position     = meta.get('position', 'arbre')
        standard     = meta.get('standard', '')
        serie_ref    = meta.get('serie', '')
        type_montage = meta.get('type_montage', 'statique')
        squeeze_cible   = float(meta.get('squeeze_cible_pct', 0.0))
        jeu_radial      = float(meta.get('jeu_radial_mm', 0.0))
        pression_bar    = float(meta.get('pression_bar', 0.0))
        temperature_C   = float(meta.get('temperature_C', 20.0))
        param_gorge     = meta.get('param_gorge', '')
        param_gorge_mode = meta.get('param_gorge_rayon', 'diametre')

        d_comp_courant = float(derive_info.get('courant', 0.0))
        d_comp_ancien  = float(derive_info.get('ref', 0.0))

        if d_comp_courant <= 0:
            print('[ORing dérive] diamètre comp. courant invalide')
            return None

        # Nouveau diamètre gorge
        if position == 'arbre':
            d_gorge_nouveau = d_comp_courant - 2.0 * jeu_radial
        else:
            d_gorge_nouveau = d_comp_courant + 2.0 * jeu_radial

        val_freecad = d_gorge_nouveau / 2.0 if param_gorge_mode == 'rayon' else d_gorge_nouveau

        # Retrouver le body gorge
        from .metadata import trouver_objet as _trouver_obj
        body_gorge = _trouver_obj(doc,
            name    = meta.get('body_gorge_name', ''),
            label   = meta.get('body_gorge_label', ''),
            type_id = 'PartDesign::Body')

        # Sauvegarder valeur avant modif pour pouvoir annuler
        val_gorge_avant = None
        if body_gorge and param_gorge:
            params = lister_parametres_body(body_gorge)
            val_gorge_avant = params.get(param_gorge)

        # Appliquer le nouveau diamètre dès le dialogue de confirmation
        # (anticipation : sera ré-appliqué dans _on_appliquer via _mettre_a_jour_parametre)
        if body_gorge and param_gorge:
            ok = set_valeur_parametre(body_gorge, param_gorge, val_freecad)
            print('[ORing dérive] set_valeur_parametre("' + param_gorge + '", '
                  + repr(round(val_freecad, 4)) + ') → ' + ('OK' if ok else 'ECHEC'))

        # Recherche du meilleur joint
        plage_sq = get_plage_squeeze(type_montage)
        sq_min   = plage_sq['min']
        sq_max   = plage_sq['max']

        def _essayer(std, ser):
            try:
                r = calculer_gorge(
                    diametre_piece_mm = d_gorge_nouveau,
                    position          = position,
                    type_montage      = type_montage,
                    standard          = std,
                    serie             = ser,
                    squeeze_cible_pct = squeeze_cible,
                    pression_bar      = pression_bar,
                    temperature_C     = temperature_C,
                )
                if sq_min <= float(r.squeeze_pct) <= sq_max:
                    return r
            except Exception:
                pass
            return None

        resultat_propose = None
        standard_propose = standard
        serie_proposee   = serie_ref
        origine          = ''

        # 1) Même série
        r = _essayer(standard, serie_ref)
        if r:
            resultat_propose = r
            origine = 'même série (' + standard + ' · ' + serie_ref + ')'

        # 2) Autres séries du même standard
        if resultat_propose is None:
            try:
                for s in liste_series(standard):
                    if s == serie_ref:
                        continue
                    r = _essayer(standard, s)
                    if r:
                        resultat_propose = r
                        serie_proposee   = s
                        origine = 'même norme (' + standard + ' · ' + s + ')'
                        break
            except Exception:
                pass

        # 3) Autres standards
        if resultat_propose is None:
            try:
                for std in liste_standards():
                    if std == standard:
                        continue
                    for s in liste_series(std):
                        r = _essayer(std, s)
                        if r:
                            resultat_propose = r
                            standard_propose = std
                            serie_proposee   = s
                            origine = 'autre norme (' + std + ' · ' + s + ')'
                            break
                    if resultat_propose:
                        break
            except Exception:
                pass

        # Construire le message de confirmation
        ligne1 = ('Le diamètre de la pièce complémentaire a changé :\n'
                  '  Ancien : ' + '{:.3f}'.format(d_comp_ancien) + ' mm'
                  '  →  Courant : ' + '{:.3f}'.format(d_comp_courant) + ' mm\n\n')
        ligne2 = ('Le diamètre de la pièce portant la gorge a été ajusté :\n'
                  '  ' + param_gorge + ' = ' + '{:.3f}'.format(d_gorge_nouveau)
                  + ' mm  (jeu radial = ' + '{:.3f}'.format(jeu_radial) + ' mm)\n\n')

        if resultat_propose:
            r = resultat_propose
            ligne3 = ('Joint retenu (' + origine + ') :\n'
                      '  d2 = ' + '{:.2f}'.format(float(r.d2)) + ' mm'
                      '  h = ' + '{:.3f}'.format(float(r.h)) + ' mm'
                      '  b = ' + '{:.3f}'.format(float(r.b)) + ' mm\n'
                      '  Squeeze : ' + '{:.1f}'.format(float(r.squeeze_pct)) + ' %'
                      '  Fill : ' + '{:.1f}'.format(float(r.fill_pct)) + ' %\n\n'
                      'Continuer vers le dialogue de modification ?')
        else:
            ligne3 = ('\u26a0 Aucun joint avec un squeeze acceptable n\'a été trouvé\n'
                      'pour ce nouveau diamètre.\n'
                      'Le dialogue s\'ouvrira pour vous permettre de choisir manuellement.\n\n'
                      'Continuer ?')

        msg = ligne1 + ligne2 + ligne3

        reponse = QtWidgets.QMessageBox.question(
            self,
            'ORing — Dérive détectée',
            msg,
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        )

        if reponse != QtWidgets.QMessageBox.Ok:
            # Annulé : remettre l'ancien paramètre FreeCAD
            if body_gorge and param_gorge and val_gorge_avant is not None:
                set_valeur_parametre(body_gorge, param_gorge, val_gorge_avant)
            return None

        # Construire le meta mis à jour pour le pre-fill
        meta_updated = dict(meta)
        meta_updated['standard']      = standard_propose
        meta_updated['serie']         = serie_proposee
        meta_updated['d_comp_ref_mm'] = d_comp_courant
        # d_gorge_ref_mm = diamètre de la pièce portant la gorge (côté opposé au comp)
        jeu_mm = float(meta.get('jeu_radial_mm', 0.0))
        if position == 'arbre':
            meta_updated['d_gorge_ref_mm'] = d_comp_courant - 2.0 * jeu_mm
        else:
            meta_updated['d_gorge_ref_mm'] = d_comp_courant + 2.0 * jeu_mm
        if resultat_propose:
            r = resultat_propose
            meta_updated['d2_mm']            = float(r.d2)
            meta_updated['d1_mm']            = float(r.d1)
            meta_updated['h_mm']             = float(r.h)
            meta_updated['b_mm']             = float(r.b)
            meta_updated['squeeze_reel_pct'] = float(r.squeeze_pct)
            meta_updated['fill_pct']         = float(r.fill_pct)
            self._resultat = resultat_propose
        return meta_updated

    def _on_clic_modifier(self):
        """
        Lit les métadonnées du joint sélectionné dans le tableau,
        pré-remplit tous les widgets du dialogue, bascule sur l'onglet 2,
        et active le mode modification.
        """
        rows = self.table_joints.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()

        # Lookup robuste : récupérer le Name stocké en UserRole (résistant au tri)
        part = None
        item0 = self.table_joints.item(row, 0)
        if item0 is not None:
            part_name = item0.data(QtCore.Qt.UserRole)
            if part_name and self._doc:
                part = self._doc.getObject(part_name)

        # Fallback sur _parts_liste si UserRole absent (ancienne ligne sans UserRole)
        if part is None:
            if row >= len(self._parts_liste):
                return
            part = self._parts_liste[row]

        if part is None:
            return
        try:
            from .metadata import lire_metadonnees
        except ImportError:
            return
        meta = lire_metadonnees(part)
        if not meta:
            message_erreur("ORing", "Impossible de lire les métadonnées de ce joint.")
            return

        # Initialiser AVANT _prefill_depuis_meta pour que _get_diametre_calcul()
        # retourne le bon diamètre et que _saisie_complete() soit correcte.
        self._part_en_modification = part
        self._d_comp_ref_modif = float(meta.get('d_comp_ref_mm', 0.0))

        # Vérifier si une dérive est présente pour ce joint
        try:
            from .metadata import verifier_derives
            infos_derives = verifier_derives(self._doc)
            derive_info = next(
                (d for d in infos_derives if d['part'].Name == part.Name),
                None
            )
            if derive_info and derive_info.get('derive'):
                # Dérive détectée → recalcul automatique + confirmation
                meta_maj = self._recalculer_apres_derive(part, meta, derive_info)
                if meta_maj is None:
                    # Annulé par l'utilisateur — réinitialiser et ne pas ouvrir
                    self._part_en_modification = None
                    self._d_comp_ref_modif = 0.0
                    return
                meta = meta_maj   # pre-fill avec les valeurs recalculées
                # CRUCIAL : resynchroniser _d_comp_ref_modif avec le nouveau
                # diamètre comp. confirmé, sinon _get_diametre_calcul() retourne
                # l'ancienne référence et _on_appliquer calcule le mauvais d_princ.
                self._d_comp_ref_modif = float(
                    meta.get('d_comp_ref_mm', self._d_comp_ref_modif)
                )
        except Exception as e_der:
            print('[ORing dérive] AVERT : ' + str(e_der))

        # Retirer le highlight verrouillé : on quitte la vue tableau
        self.table_joints.deverrouiller()
        self._prefill_depuis_meta(meta)
        self._entrer_mode_modification(part, meta)
        self._tabs.setCurrentIndex(1)   # basculer sur onglet 2

    def _prefill_depuis_meta(self, meta: dict):
        """
        Pré-remplit tous les widgets du dialogue depuis un dict métadonnées.
        Bloque les signaux pendant le remplissage pour éviter les recalculs
        intermédiaires, puis les rétablit tous d'un coup à la fin.
        """
        widgets_a_debloquer = []

        def _set_combo_by_data(combo, valeur):
            """Sélectionne l'item dont currentData() == valeur, si non grisé."""
            model = combo.model()
            for i in range(combo.count()):
                if combo.itemData(i) == valeur:
                    # Vérifier que l'item est activé (pas grisé)
                    item = model.item(i) if model else None
                    if item is not None and not item.isEnabled():
                        return False   # item grisé → ne pas sélectionner
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    widgets_a_debloquer.append(combo)
                    return True
            return False

        def _set_widget_body(widget, body_label, param_nom, est_rayon,
                              body_name=''):
            """Sélectionne body + paramètre + radio dans un WidgetSelectBody."""
            if not hasattr(widget, 'combo_body'):
                return
            # 1. Sélectionner le body par Name (stable) puis Label (fallback)
            widget.combo_body.blockSignals(True)
            for i in range(widget.combo_body.count()):
                b = widget.combo_body.itemData(i)
                if b is not None and (
                        (body_name and b.Name == body_name)
                        or b.Label == body_label):
                    widget.combo_body.setCurrentIndex(i)
                    break
            widget.combo_body.blockSignals(False)
            # Déclencher la mise à jour du combo paramètre
            widget._on_body_change(0)

            # 2. Sélectionner le paramètre par nom
            widget.combo_param.blockSignals(True)
            for i in range(widget.combo_param.count()):
                if widget.combo_param.itemData(i) == param_nom:
                    widget.combo_param.setCurrentIndex(i)
                    break
            widget.combo_param.blockSignals(False)
            widget._on_param_change()

            # 3. Radio rayon / diamètre
            if est_rayon:
                widget.radio_rayon.setChecked(True)
            else:
                widget.radio_diametre.setChecked(True)

        # ── Onglet 1 : Contexte ──────────────────────────────────────────
        _set_combo_by_data(self.combo_position, meta.get('position', 'arbre'))
        _set_combo_by_data(self.combo_plan,     meta.get('plan_esquisse', 'XZ'))
        _set_combo_by_data(self.combo_montage,  meta.get('type_montage', 'statique'))

        if hasattr(self, 'spin_pression'):
            self.spin_pression.setValue(float(meta.get('pression_bar', 0.0)))
        if hasattr(self, 'spin_temperature'):
            self.spin_temperature.setValue(float(meta.get('temperature_C', 20.0)))
        if hasattr(self, 'edit_fluide'):
            self.edit_fluide.setText(str(meta.get('fluide', '')))

        # ── Onglet 1 : Matériau ──────────────────────────────────────────
        _set_combo_by_data(self.combo_materiau, meta.get('materiau', ''))

        # ── Onglet 2 : Joint / Standard / Série ─────────────────────────
        _set_combo_by_data(self.combo_standard, meta.get('standard', 'ISO_3601'))
        # Reconstruire le combo série après changement de standard
        self._rafraichir_combo_serie()
        # Puis sélectionner la série sauvegardée
        _set_combo_by_data(self.combo_serie, meta.get('serie', ''))

        # Squeeze : 0 = auto, valeur > 0 = manuel
        sq = float(meta.get('squeeze_cible_pct', 0.0))
        if hasattr(self, 'spin_squeeze'):
            self.spin_squeeze.blockSignals(True)
            self.spin_squeeze.setValue(sq)
            self.spin_squeeze.blockSignals(False)
            self._on_squeeze_info_change()

        # ── Onglet 2 : Pièces FreeCAD ────────────────────────────────────
        if hasattr(self, 'widget_piece_principale'):
            _set_widget_body(
                self.widget_piece_principale,
                meta.get('body_gorge_label', ''),
                meta.get('param_gorge', ''),
                meta.get('param_gorge_rayon', 'diametre') == 'rayon',
                body_name=meta.get('body_gorge_name', ''),
            )
            # _on_piece_principale_change n'a pas été appelé (signaux bloqués).
            # L'appeler maintenant pour peupler combo_lcs depuis le body sélectionné.
            self._on_piece_principale_change()

        if hasattr(self, 'widget_piece_complementaire'):
            _set_widget_body(
                self.widget_piece_complementaire,
                meta.get('body_comp_label', ''),
                meta.get('param_comp', ''),
                meta.get('param_comp_rayon', 'diametre') == 'rayon',
                body_name=meta.get('body_comp_name', ''),
            )

        # ── LCS : sélectionner APRÈS que combo_lcs soit peuplé ───────────
        if hasattr(self, 'combo_lcs'):
            lcs_label = meta.get('lcs_label', '')
            for i in range(self.combo_lcs.count()):
                lcs_obj = self.combo_lcs.itemData(i)
                if lcs_obj is not None and (lcs_obj.Name == meta.get('lcs_name','') or lcs_obj.Label == lcs_label):
                    self.combo_lcs.setCurrentIndex(i)
                    break
            # Debug : signaler si LCS non trouvé
            if self.combo_lcs.currentData() is None and lcs_label:
                print(f"[ORing prefill] AVERT : LCS '{lcs_label}' non trouvé dans combo_lcs "
                      f"({self.combo_lcs.count()} entrées)")

        # ── Mise à jour du label D pièce principale ─────────────────────
        # (forcer après prefill car les signaux étaient bloqués)
        if hasattr(self, 'label_d_principale_derive'):
            self._on_dims_change()

        # ── Grades IT ────────────────────────────────────────────────────
        # Prefill grades IT — désactivé temporairement

        # ── Prefill ajustement ISO ────────────────────────────────────────
        if hasattr(self, 'combo_mode_jeu'):
            mode_jeu_saved = meta.get('mode_jeu', 'manuel')
            grade_saved    = int(meta.get('grade_arbre', 7))
            # Trouver l'index dans combo_mode_jeu
            for i in range(self.combo_mode_jeu.count()):
                if self.combo_mode_jeu.itemData(i) == mode_jeu_saved:
                    self.combo_mode_jeu.blockSignals(True)
                    self.combo_mode_jeu.setCurrentIndex(i)
                    self.combo_mode_jeu.blockSignals(False)
                    break
            # Grade arbre
            for i in range(self.combo_grade_arbre.count()):
                if self.combo_grade_arbre.itemData(i) == grade_saved:
                    self.combo_grade_arbre.blockSignals(True)
                    self.combo_grade_arbre.setCurrentIndex(i)
                    self.combo_grade_arbre.blockSignals(False)
                    break
            # Appliquer visibilité + diagramme
            self._on_mode_jeu_change()

        # ── Recalcul automatique ─────────────────────────────────────────
        if self._saisie_complete():
            self._on_calculer()

    def _entrer_mode_modification(self, part, meta):
        """
        Active le mode modification :
        - Stocke le diamètre de référence de la pièce complémentaire
        - Verrouille tous les widgets non-modifiables
        - Détecte une dérive du diamètre depuis l'insertion
        - Met à jour le titre et les boutons
        """
        lcs_label  = meta.get('lcs_label', '?')
        body_label = meta.get('body_gorge_label', '?')

        # ── Détecter dérive ───────────────────────────────────────────────
        # Note : _d_comp_ref_modif déjà initialisé dans _on_clic_modifier
        derive_msg = ""
        if hasattr(self, 'widget_piece_complementaire') and self._d_comp_ref_modif > 0:
            d_courant = self.widget_piece_complementaire.get_diametre_mm()
            if d_courant and abs(d_courant - self._d_comp_ref_modif) > 1e-4:
                delta = d_courant - self._d_comp_ref_modif
                derive_msg = (
                    f"⚠  Dérive détectée : Ø référence = {self._d_comp_ref_modif:.3f} mm "
                    f"→ valeur actuelle = {d_courant:.3f} mm  (Δ {delta:+.3f} mm)\n"
                    f"   Le calcul utilise le diamètre de référence de l'insertion. "
                    f"Recréez le joint pour prendre en compte la nouvelle valeur."
                )

        # ── Verrouiller les widgets non-modifiables ───────────────────────
        self._appliquer_verrous_modification(verrouiller=True)

        # ── Titre et bouton Appliquer ─────────────────────────────────────
        self.setWindowTitle(
            f"ORing — Modification : {body_label}  ·  LCS {lcs_label}"
        )
        self.btn_appliquer.setText("Mettre à jour")
        self.btn_appliquer.setEnabled(True)
        self.btn_appliquer.setStyleSheet(
            "QPushButton { background-color: #1a5276; color: white; font-weight: bold; }"
        )
        # ── Bouton Annuler modification ───────────────────────────────────
        if not hasattr(self, 'btn_annuler_modif'):
            self.btn_annuler_modif = QtWidgets.QPushButton("✕  Annuler modification")
            self.btn_annuler_modif.clicked.connect(self._annuler_mode_modification)
            layout_outer = self.layout()
            item = layout_outer.itemAt(layout_outer.count() - 1)
            if item and item.layout():
                bl = item.layout()
                bl.insertWidget(bl.count() - 1, self.btn_annuler_modif)
        self.btn_annuler_modif.show()

        # ── Afficher le spin "nouveau Ø pièce comp." ─────────────────────
        if hasattr(self, 'spin_d_comp_modif') and self._d_comp_ref_modif > 0:
            self.spin_d_comp_modif.setValue(self._d_comp_ref_modif)
            self.spin_d_comp_modif.setVisible(True)
            self.lbl_d_comp_modif.setVisible(True)

        # ── Bandeau dérive si nécessaire ─────────────────────────────────
        if derive_msg:
            # avertissement via QMessageBox (ci-dessous)
            QtWidgets.QMessageBox.warning(
                self,
                "ORing — Dérive du diamètre de référence",
                derive_msg
            )

    def _maj_joints_lies(self, body_modifie_label: str):
        """
        Après modification d'un joint, met à jour automatiquement tous les
        autres joints du document qui partagent le même body (gorge ou comp)
        et dont les dimensions ont dérivé.

        body_modifie_label : Label du body dont les paramètres viennent d'être
                             modifiés (arbre ou alésage).
        """
        from .metadata import lister_parts_oring, lire_metadonnees, verifier_derives
        from .calcul   import calculer_gorge

        doc = self._doc
        if doc is None:
            return

        # Recalculer toutes les dérives après la modification
        derives = [d for d in verifier_derives(doc) if d.get('derive')]
        if not derives:
            return

        print(f"[ORing lies] {len(derives)} joint(s) en dérive après modif de '{body_modifie_label}'")
        import time as _time
        _t_total = _time.time()

        # Déterminer la série du joint modifié et si tous les joints liés
        # partageaient la même série avant la modification.
        # Utilisé pour le choix de série lors du recalcul des joints liés.
        from .metadata import lister_parts_oring, lire_metadonnees as _lmm
        _serie_joint_modifie = ''
        _standard_joint_modifie = ''
        try:
            _all_parts = lister_parts_oring(doc)
            # Retrouver le part du joint modifié par body_modifie_label
            for _pp in _all_parts:
                _mm = _lmm(_pp)
                if (_mm.get('body_gorge_label') == body_modifie_label
                        or _mm.get('body_comp_label') == body_modifie_label):
                    # Prendre le premier Part qui correspond (le joint modifié)
                    # On cherche celui dont le Part est self._part_en_modification
                    # (mais _maj_joints_lies est appelée après _annuler_mode_modif,
                    # donc on prend la série du joint en dérive)
                    pass
            # Prendre la série du premier joint en dérive appartenant au body modifié
            for _d in derives:
                _mm = _d['meta']
                if (_mm.get('body_gorge_label') == body_modifie_label
                        or _mm.get('body_comp_label') == body_modifie_label):
                    _serie_joint_modifie   = _mm.get('serie', '')
                    _standard_joint_modifie = _mm.get('standard', '')
                    break
            # Vérifier si tous les joints liés avaient la même série
            _series_lies = [_d['meta'].get('serie', '') for _d in derives]
            _tous_meme_serie = (len(set(_series_lies)) == 1
                                and _series_lies[0] == _serie_joint_modifie
                                and bool(_serie_joint_modifie))
        except Exception as _e_serie_init:
            _tous_meme_serie = False
            print(f"[ORing lies] init séries : {_e_serie_init}")

        print(f"[ORing lies] série joint modifié='{_serie_joint_modifie}'  "
              f"tous_meme_serie={_tous_meme_serie}")

        for d in derives:
            part = d['part']
            meta = d['meta']

            # Auto-heal : mettre à jour les Names si manquants/périmés
            try:
                from .metadata import auto_heal_names
                meta = auto_heal_names(doc, part, meta)
            except Exception as _eh:
                print(f"[ORing lies]   auto_heal_names : {_eh}")

            # Vérifier que ce joint partage bien le body modifié
            # Comparaison par Name (stable) en priorité, Label en fallback
            body_gorge_name = meta.get('body_gorge_name', '')
            body_comp_name  = meta.get('body_comp_name', '')
            # Retrouver le Name du body modifié depuis son Label
            _body_mod_name = ''
            for _o in doc.Objects:
                if (_o.TypeId == 'PartDesign::Body'
                        and _o.Label == body_modifie_label):
                    _body_mod_name = _o.Name
                    break
            if _body_mod_name:
                partage = (_body_mod_name in (body_gorge_name, body_comp_name))
            else:
                # Fallback Label si body introuvable par Label (renommé entre-temps)
                partage = (meta.get('body_gorge_label') == body_modifie_label
                           or meta.get('body_comp_label')  == body_modifie_label)
            if not partage:
                print(f"[ORing lies]   '{part.Name}' ignoré (body différent)")
                continue

            _t_joint = _time.time()
            print(f"[ORing lies]   Mise à jour automatique : '{part.Name}' "
                  f"(uuid={getattr(part, 'uuid_joint', '?')})")

            position      = meta.get('position', 'arbre')
            jeu_mm        = float(meta.get('jeu_radial_mm', 0.0))

            from .utils import lister_parametres_body

            # ── Lire le body GORGE (porteur de la gorge) ──────────────────
            # C'est toujours la référence géométrique pour calculer D_alesage,
            # quelle que soit la position (arbre ou alésage).
            from .metadata import trouver_objet as _trouver
            body_gorge_obj = _trouver(doc,
                name  = meta.get('body_gorge_name', ''),
                label = meta.get('body_gorge_label', ''),
                type_id = 'PartDesign::Body')

            d_gorge_new     = None
            _param_gorge_ok = False   # True = on a lu le Ø gorge depuis le body
            if body_gorge_obj is not None:
                params_g = lister_parametres_body(body_gorge_obj)
                nom_pg   = meta.get('param_gorge', '')
                val_g    = params_g.get(nom_pg)
                if val_g is not None:
                    d_gorge_new     = val_g * 2.0 if meta.get('param_gorge_rayon') == 'rayon' else val_g
                    _param_gorge_ok = True

            if not _param_gorge_ok:
                # param_gorge absent (joint ancien schéma) : impossible de connaître
                # le Ø courant du body gorge → la géométrie ne peut pas être mise à
                # jour automatiquement. On nettoiera les refs pour effacer la dérive,
                # mais l'utilisateur doit modifier ce joint manuellement.
                print(f"[ORing lies]   '{part.Name}' : param_gorge absent "
                      f"(ancien schéma) — géométrie non mise à jour. "
                      f"Ouvrir le mode Modifier pour reconfigurer ce joint.")

            # ── Lire le body COMP pour d_comp_ref_mm ──────────────────────
            body_comp_obj = _trouver(doc,
                name  = meta.get('body_comp_name', ''),
                label = meta.get('body_comp_label', ''),
                type_id = 'PartDesign::Body')

            d_comp_new = None
            if body_comp_obj is not None:
                params_c = lister_parametres_body(body_comp_obj)
                nom_pc   = meta.get('param_comp', '')
                val_c    = params_c.get(nom_pc)
                if val_c is not None:
                    d_comp_new = val_c * 2.0 if meta.get('param_comp_rayon') == 'rayon' else val_c

            if d_comp_new is None:
                # Fallback comp introuvable : dériver depuis d_gorge_new si disponible
                if d_gorge_new is not None:
                    d_comp_new = d_gorge_new if position == 'alesage' else (d_gorge_new + 2.0 * jeu_mm)
                else:
                    print(f"[ORing lies]   body_comp '{meta.get('body_comp_label','')}' "
                          f"introuvable — ignoré")
                    continue

            # Si param_gorge absent : impossible de déterminer le Ø gorge courant.
            # → Mettre à jour seulement les refs metadata pour sortir du cycle de
            #   dérive, sans toucher à la géométrie (gorge + tore inchangés).
            if not _param_gorge_ok:
                try:
                    from .metadata import ecrire_metadonnees
                    _mn = dict(meta)
                    # d_gorge_ref = approximation depuis d_comp (meilleur effort)
                    _mn['d_comp_ref_mm']  = d_comp_new
                    _mn['d_gorge_ref_mm'] = (d_comp_new - 2.0 * jeu_mm
                                             if position == 'arbre'
                                             else d_comp_new + 2.0 * jeu_mm)
                    ecrire_metadonnees(part, _mn)
                    print(f"[ORing lies]   '{part.Name}' refs Ø mises à jour "
                          f"(géométrie inchangée — modifier manuellement)")
                except Exception as _em:
                    print(f"[ORing lies]   '{part.Name}' metadata secours : {_em}")
                continue

            # Fallback d_gorge_new ne devrait plus être None ici
            # (param_gorge_ok garantit que d_gorge_new est lu depuis le body)
            if position == 'arbre':
                d_alesage_calc = d_gorge_new + 2.0 * jeu_mm
            else:
                d_alesage_calc = d_gorge_new

            print(f"[ORing lies]   d_gorge={d_gorge_new:.3f}  d_alesage_calc={d_alesage_calc:.3f}  d_comp={d_comp_new:.3f}")

            try:
                # 1er essai : série mémorisée
                r_new = calculer_gorge(
                    diametre_piece_mm = d_alesage_calc,
                    position          = position,
                    type_montage      = meta.get('type_montage', 'statique'),
                    materiau          = meta.get('materiau', 'NBR'),
                    pression_bar      = float(meta.get('pression_bar', 0.0)),
                    temperature_C     = float(meta.get('temperature_C', 20.0)),
                    fluide            = meta.get('fluide', ''),
                    standard          = meta.get('standard', ''),
                    serie             = meta.get('serie', ''),
                    squeeze_cible_pct = float(meta.get('squeeze_cible_pct', 0.0)),
                    jeu_radial_mm     = jeu_mm,
                )

                # Vérifier que la série conservée est physiquement adaptée au nouveau Ø.
                # Critères de rejet (valide=True possible même avec série inadaptée) :
                #   1. squeeze hors plage raisonnable
                #   2. d1 > D_arbre : le joint ne peut pas s'étirer sur l'arbre
                #   3. d1 < D_alesage : le joint ne tient pas dans l'alésage
                serie_ok = r_new.valide
                if serie_ok and r_new.squeeze_pct is not None:
                    sq = float(r_new.squeeze_pct)
                    serie_ok = 5.0 <= sq <= 35.0
                if serie_ok and position == 'arbre' and r_new.d1 and r_new.d_arbre:
                    if float(r_new.d1) > float(r_new.d_arbre) * 1.02:
                        serie_ok = False
                if serie_ok and position == 'alesage' and r_new.d1 and r_new.d_alesage:
                    if float(r_new.d1) < float(r_new.d_alesage) * 0.98:
                        serie_ok = False

                # Critère supplémentaire : d2 adapté au diamètre.
                # Une série choisie manuellement pour un petit Ø peut rester
                # géométriquement "valide" après agrandissement (ex. M2/d2=1.5mm
                # sur Ø40 : d1=38.7mm ≤ 40×1.02 → passe) mais être totalement
                # inadaptée en pratique.
                # On compare le d2 mémorisé à celui qu'Auto choisirait : si le
                # ratio dépasse 2 ou est inférieur à 0.5, la série est rejetée.
                if serie_ok and meta.get('serie', ''):
                    try:
                        _r_auto_check = calculer_gorge(
                            diametre_piece_mm = d_alesage_calc,
                            position          = position,
                            type_montage      = meta.get('type_montage', 'statique'),
                            materiau          = meta.get('materiau', 'NBR'),
                            pression_bar      = float(meta.get('pression_bar', 0.0)),
                            temperature_C     = float(meta.get('temperature_C', 20.0)),
                            fluide            = meta.get('fluide', ''),
                            standard          = meta.get('standard', ''),
                            serie             = '',
                            squeeze_cible_pct = float(meta.get('squeeze_cible_pct', 0.0)),
                            jeu_radial_mm     = jeu_mm,
                        )
                        if _r_auto_check.valide and _r_auto_check.d2 and r_new.d2:
                            _ratio = float(r_new.d2) / float(_r_auto_check.d2)
                            if not (0.5 <= _ratio <= 2.0):
                                serie_ok = False
                                print(f"[ORing lies]   série '{meta.get('serie')}' "
                                      f"d2={float(r_new.d2):.2f}mm inadapté "
                                      f"(Auto→d2={float(_r_auto_check.d2):.2f}mm, "
                                      f"ratio={_ratio:.2f}) → recalcul Auto")
                    except Exception:
                        pass  # En cas d'erreur du check Auto, on garde serie_ok tel quel

                if not serie_ok and meta.get('serie', ''):
                    print(f"[ORing lies]   série '{meta.get('serie')}' inadaptée "
                          f"→ recherche série adaptée")
                    from .joints import liste_series, get_serie as _get_serie
                    _std        = meta.get('standard', '')
                    _serie_orig = meta.get('serie', '')
                    _d2_orig    = float(meta.get('d2_mm', 0.0)) or None
                    if _d2_orig is None and _std and _serie_orig:
                        try:
                            _d2_orig = _get_serie(_std, _serie_orig).get('d2_nominal')
                        except Exception:
                            pass
                    _r_proche = None

                    # ── Cas 1 : tous les joints liés avaient la même série
                    #    → imposer directement la série du joint modifié
                    if _tous_meme_serie and _serie_joint_modifie and _std:
                        try:
                            _r_cand = calculer_gorge(
                                diametre_piece_mm = d_alesage_calc,
                                position          = position,
                                type_montage      = meta.get('type_montage', 'statique'),
                                materiau          = meta.get('materiau', 'NBR'),
                                pression_bar      = float(meta.get('pression_bar', 0.0)),
                                temperature_C     = float(meta.get('temperature_C', 20.0)),
                                fluide            = meta.get('fluide', ''),
                                standard          = _std,
                                serie             = _serie_joint_modifie,
                                squeeze_cible_pct = float(meta.get('squeeze_cible_pct', 0.0)),
                                jeu_radial_mm     = jeu_mm,
                            )
                            if _r_cand.valide and _r_cand.squeeze_pct is not None:
                                _sq = float(_r_cand.squeeze_pct)
                                if 5.0 <= _sq <= 35.0:
                                    _r_proche = _r_cand
                                    print(f"[ORing lies]   série imposée (même série) : "
                                          f"'{_serie_joint_modifie}' sq={_sq:.1f}%")
                        except Exception as _e_imp:
                            print(f"[ORing lies]   série imposée échouée : {_e_imp}")

                    # ── Cas 2 : séries différentes ou série imposée invalide
                    #    → chercher d'abord d2 supérieur ≥ d2_orig, puis inférieur
                    if _r_proche is None and _std and _d2_orig:
                        try:
                            _sup = []  # d2 >= d2_orig, tri croissant
                            _inf = []  # d2 < d2_orig, tri décroissant (le plus proche d'abord)
                            for _s in liste_series(_std):
                                if _s == _serie_orig:
                                    continue
                                try:
                                    _d2_s = _get_serie(_std, _s).get('d2_nominal', 0)
                                    if _d2_s >= _d2_orig:
                                        _sup.append((_d2_s - _d2_orig, _s))
                                    else:
                                        _inf.append((_d2_orig - _d2_s, _s))
                                except Exception:
                                    pass
                            _sup.sort(); _inf.sort()
                            _candidats_ordonnes = [s for _, s in _sup] + [s for _, s in _inf]
                            for _s_cand in _candidats_ordonnes:
                                _r_cand = calculer_gorge(
                                    diametre_piece_mm = d_alesage_calc,
                                    position          = position,
                                    type_montage      = meta.get('type_montage', 'statique'),
                                    materiau          = meta.get('materiau', 'NBR'),
                                    pression_bar      = float(meta.get('pression_bar', 0.0)),
                                    temperature_C     = float(meta.get('temperature_C', 20.0)),
                                    fluide            = meta.get('fluide', ''),
                                    standard          = _std,
                                    serie             = _s_cand,
                                    squeeze_cible_pct = float(meta.get('squeeze_cible_pct', 0.0)),
                                    jeu_radial_mm     = jeu_mm,
                                )
                                if _r_cand.valide and _r_cand.squeeze_pct is not None:
                                    _sq = float(_r_cand.squeeze_pct)
                                    if 5.0 <= _sq <= 35.0:
                                        _r_proche = _r_cand
                                        print(f"[ORing lies]   série proche retenue : '{_s_cand}' "
                                              f"(d2={float(_r_cand.d2):.2f}mm, sq={_sq:.1f}%)")
                                        break
                        except Exception as _e_proche:
                            print(f"[ORing lies]   recherche série proche : {_e_proche}")

                    if _r_proche is not None:
                        r_new = _r_proche
                    else:
                        print(f"[ORing lies]   aucune série adaptée → Auto")
                        r_new = calculer_gorge(
                            diametre_piece_mm = d_alesage_calc,
                            position          = position,
                            type_montage      = meta.get('type_montage', 'statique'),
                            materiau          = meta.get('materiau', 'NBR'),
                            pression_bar      = float(meta.get('pression_bar', 0.0)),
                            temperature_C     = float(meta.get('temperature_C', 20.0)),
                            fluide            = meta.get('fluide', ''),
                            standard          = meta.get('standard', ''),
                            serie             = '',
                            squeeze_cible_pct = float(meta.get('squeeze_cible_pct', 0.0)),
                            jeu_radial_mm     = jeu_mm,
                        )
            except Exception as _e_calc:
                print(f"[ORing lies]   calcul échoué : {_e_calc}")
                continue

            if not r_new.valide:
                # Auto aussi invalide : mettre à jour seulement les références Ø
                # pour sortir du cycle de dérive, sans toucher à la géométrie.
                print(f"[ORing lies]   résultat invalide pour '{part.Name}' "
                      f"— références Ø mises à jour, géométrie inchangée")
                try:
                    from .metadata import ecrire_metadonnees as _em_secours
                    _mn = dict(meta)
                    _mn['d_gorge_ref_mm'] = d_gorge_new
                    _mn['d_comp_ref_mm']  = d_comp_new
                    _em_secours(part, _mn)
                except Exception as _em:
                    print(f"[ORing lies]   metadata secours échouée : {_em}")
                continue

            # Mettre à jour la gorge et le tore (non bloquant)
            _geo_ok = False
            try:
                _mettre_a_jour_geometries_existantes(
                    doc            = doc,
                    r              = r_new,
                    position       = position,
                    d_comp_mm      = d_comp_new,
                    meta_existante = meta,
                    part           = part,
                )
                _geo_ok = True
            except Exception as _e_geo:
                import traceback as _tb
                print(f"[ORing lies]   mise à jour géo échouée : {_e_geo}\n{_tb.format_exc()}")
                # Pas de continue : on met à jour les métadonnées dans tous les cas
                # pour que la dérive ne soit plus signalée au prochain rafraîchissement

            # Mettre à jour les métadonnées — TOUJOURS, même si la géo a échoué
            try:
                from .metadata import ecrire_metadonnees
                meta_new = dict(meta)
                uuid_existant = getattr(part, 'uuid_joint', '')
                if uuid_existant:
                    meta_new['uuid_joint'] = uuid_existant
                meta_new['serie']            = str(r_new.serie)          if hasattr(r_new, 'serie') else meta.get('serie', '')
                meta_new['d2_mm']            = float(r_new.d2)           if r_new.d2           else meta.get('d2_mm', 0.0)
                meta_new['d_comp_ref_mm']    = d_comp_new
                meta_new['d_gorge_ref_mm']   = d_gorge_new               # Ø courant body gorge
                meta_new['h_mm']             = float(r_new.h)            if r_new.h            else 0.0
                meta_new['b_mm']             = float(r_new.b)            if r_new.b            else 0.0
                meta_new['d1_mm']            = float(r_new.d1)           if r_new.d1           else 0.0
                meta_new['squeeze_reel_pct'] = float(r_new.squeeze_pct)  if r_new.squeeze_pct  else 0.0
                meta_new['fill_pct']         = float(r_new.fill_pct)     if r_new.fill_pct     else 0.0
                meta_new['rayon_gorge_mm']   = float(r_new.rayon_gorge)  if r_new.rayon_gorge  else 0.0
                ecrire_metadonnees(part, meta_new)
                _statut = '✓' if _geo_ok else '⚠ géo échouée / meta OK'
                print(f"[ORing lies]   '{part.Name}' {_statut}  "
                      f"uuid={uuid_existant or '(ancien schéma)'}  "
                      f"serie={meta_new['serie']}  d2={meta_new['d2_mm']:.2f}  "
                      f"durée={_time.time()-_t_joint:.2f}s")
            except Exception as _e_meta:
                print(f"[ORing lies]   metadata échouée : {_e_meta}")

            # Migration automatique : rattacher le Part ORing au conteneur
            # du body_gorge (idempotent — sans effet si déjà en place)
            try:
                from .metadata import rattacher_joint_au_conteneur, trouver_objet
                _bg = trouver_objet(doc,
                                    name    = meta.get('body_gorge_name', ''),
                                    label   = meta.get('body_gorge_label', ''),
                                    type_id = 'PartDesign::Body')
                if _bg is not None:
                    rattacher_joint_au_conteneur(
                        doc, part, _bg, meta.get('position', 'arbre'))
            except Exception as _e_ct:
                print(f"[ORing lies]   conteneur : {_e_ct}")

        # Commit de la transaction
        try:
            doc.commitTransaction()
        except Exception:
            pass
        print(f"[ORing lies] TOTAL : {_time.time()-_t_total:.2f}s pour {len(derives)} joint(s)")

    def _on_recalibrer_couleurs(self):
        """Recolorie tous les joints ORing du document selon leur matériau.
        1. Restaure d'abord le snapshot (ramène le body gorge à sa couleur d'origine).
        2. Applique les couleurs matériau sur les corps ORing par-dessus.
        3. Un seul Gui.updateGui() en fin de séquence.
        """
        if not self._doc:
            return
        # Étape 1 : restaurer le snapshot pour tous les bodies (y.c. body gorge)
        _restaurer_snapshot(self._doc)
        try:
            from .oring_3d  import appliquer_couleur_materiau
            from .metadata  import lister_parts_oring, lire_metadonnees
            n_ok = 0
            for _p in lister_parts_oring(self._doc):
                try:
                    _m   = lire_metadonnees(_p)
                    _nom = _m.get('body_oring_name', '')
                    _b   = self._doc.getObject(_nom) if _nom else None
                    if _b is None:
                        # Fallback : chercher dans le Group du Part
                        for _child in getattr(_p, 'Group', []):
                            if (_child.TypeId == 'PartDesign::Body'
                                    and _child.Label.startswith('ORing')):
                                _b = _child
                                break
                    if _b is not None:
                        appliquer_couleur_materiau(_b, _m.get('materiau', ''))
                        # Mettre à jour le snapshot
                        try:
                            _vo = _b.ViewObject
                            _visual_snapshot[_b.Name] = {
                                'ShapeColor':   tuple(getattr(_vo, 'ShapeColor', (0.8, 0.8, 0.8))),
                                'Transparency': 0,
                            }
                        except Exception:
                            pass
                        n_ok += 1
                except Exception as _e:
                    print(f"[ORing couleurs] '{_p.Name}' : {_e}")
            print(f"[ORing couleurs] {n_ok} joint(s) recalibrés")
            # Forcer le rafraîchissement 3D immédiat (fix #3)
            try:
                import FreeCADGui as _Gui
                _Gui.updateGui()
            except Exception:
                pass
        except Exception as e:
            print(f"[ORing couleurs] recalibrage échoué : {e}")

    def _annuler_mode_modification(self):
        """Quitte le mode modification : déverrouille les widgets et remet à zéro."""
        # Restaurer IMMÉDIATEMENT les états visuels (avant tout autre traitement)
        # quelle que soit la façon dont on sort du mode modification
        _restaurer_snapshot(self._doc)
        if hasattr(self, 'table_joints'):
            self.table_joints._locked_row = -1
            self.table_joints._hover_row  = -1
        # Mémoriser les valeurs du joint qui vient d'être modifié (ou annulé)
        # avant de réinitialiser _part_en_modification
        _body_modif_label = ''
        _lcs_modif_label  = ''
        if self._part_en_modification is not None and self._doc:
            try:
                from .metadata import lire_metadonnees
                _m = lire_metadonnees(self._part_en_modification)
                _body_modif_label = _m.get('body_gorge_label', '')
                _lcs_modif_label  = _m.get('lcs_label', '')
            except Exception:
                pass

        self._appliquer_verrous_modification(verrouiller=False)
        self._part_en_modification = None
        self._d_comp_ref_modif = 0.0
        # Masquer le spin "nouveau Ø comp." (spécifique au mode modification)
        if hasattr(self, 'spin_d_comp_modif'):
            self.spin_d_comp_modif.setVisible(False)
            self.lbl_d_comp_modif.setVisible(False)
        self.setWindowTitle("ORing — Dimensionnement joint torique")
        self.btn_appliquer.setText("Appliquer dans FreeCAD")
        self.btn_appliquer.setStyleSheet("")
        if hasattr(self, 'btn_annuler_modif'):
            self.btn_annuler_modif.hide()

        # Désactiver Appliquer seulement si body+LCS inchangés (évite doublon)
        _body_courant = (self.widget_piece_principale.get_body().Label
                         if hasattr(self, 'widget_piece_principale')
                         and self.widget_piece_principale.get_body() else '')
        _lcs_courant  = (self.combo_lcs.currentData().Label
                         if hasattr(self, 'combo_lcs')
                         and self.combo_lcs.currentData() else '')
        meme_emplacement = (_body_courant == _body_modif_label
                            and _lcs_courant == _lcs_modif_label)
        if meme_emplacement:
            self.btn_appliquer.setEnabled(False)
            self._resultat = None

        self._on_recalcul_si_resultat()

    def _appliquer_verrous_modification(self, verrouiller: bool):
        """
        Verrouille (verrouiller=True) ou déverrouille (False) les widgets
        non-modifiables en mode modification.

        Modifiables : pression, température, matériau, type de montage,
                      jeu radial, standard, série, squeeze cible.
        Gelés      : position, plan, fluide, pièce principale,
                     pièce complémentaire, LCS.
        """
        actif = not verrouiller  # True = déverrouillé

        widgets_a_geler = []
        if hasattr(self, 'combo_position'):
            widgets_a_geler.append(self.combo_position)
        if hasattr(self, 'combo_plan'):
            widgets_a_geler.append(self.combo_plan)
        if hasattr(self, 'edit_fluide'):
            widgets_a_geler.append(self.edit_fluide)
        if hasattr(self, 'combo_lcs'):
            widgets_a_geler.append(self.combo_lcs)
        if hasattr(self, 'widget_piece_principale'):
            widgets_a_geler.append(self.widget_piece_principale)
        if hasattr(self, 'widget_piece_complementaire'):
            widgets_a_geler.append(self.widget_piece_complementaire)

        for w in widgets_a_geler:
            w.setEnabled(actif)

        # FIX #6 — En mode modification (verrouillé), les radios diam/rayon
        # restent éditables même si le widget pièce est gelé, car l'utilisateur
        # peut avoir saisi le mauvais type au départ.
        if verrouiller:
            for attr in ('widget_piece_principale', 'widget_piece_complementaire'):
                w = getattr(self, attr, None)
                if w is not None:
                    for radio in (getattr(w, 'radio_diametre', None),
                                  getattr(w, 'radio_rayon', None)):
                        if radio is not None:
                            radio.setEnabled(True)

    def _on_tab_change(self, index):
        """Gestion du changement d'onglet : rafraîchi et gère les highlights."""
        if index == 2:
            # Activation de l'onglet 3 : rafraîchir le tableau
            self._rafraichir_joints_existants()
        else:
            # Désactivation de l'onglet 3 : retirer le hover libre uniquement.
            # Le highlight verrouillé (sélection) reste jusqu'au clic Modifier.
            if hasattr(self, 'table_joints'):
                if self.table_joints._locked_row < 0 and self.table_joints._hover_row >= 0:
                    _hover_retirer(self._doc)
                    self.table_joints._hover_row = -1

    # ------------------------------------------------------------------
    # Section Contexte
    # ------------------------------------------------------------------
    def _section_contexte(self):
        grp = QtWidgets.QGroupBox("Contexte")
        f = QtWidgets.QFormLayout(grp)
        f.setVerticalSpacing(8)

        # Ligne 1 : position + pression côte à côte
        hl1 = QtWidgets.QHBoxLayout()
        self.combo_position = QtWidgets.QComboBox()
        self.combo_position.addItem("Gorge sur arbre",    "arbre")
        self.combo_position.addItem("Gorge dans alesage", "alesage")
        self.spin_pression = QtWidgets.QDoubleSpinBox()
        self.spin_pression.setRange(0, 2000)
        self.spin_pression.setSuffix(" bar")
        self.spin_pression.setDecimals(1)
        hl1.addWidget(self.combo_position, 2)
        hl1.addWidget(QtWidgets.QLabel("  Pression max :"), 0)
        hl1.addWidget(self.spin_pression, 1)
        f.addRow("Position gorge :", hl1)

        # Ligne 2 : plan esquisse + température côte à côte
        hl2 = QtWidgets.QHBoxLayout()
        self.combo_plan = QtWidgets.QComboBox()
        self.combo_plan.addItem("Plan XZ  (Z = axe piece)", "XZ")
        self.combo_plan.addItem("Plan YZ  (Z = axe piece)", "YZ")
        self.spin_temperature = QtWidgets.QDoubleSpinBox()
        self.spin_temperature.setRange(-200, 350)
        self.spin_temperature.setSuffix(" °C")
        self.spin_temperature.setValue(20.0)
        self.spin_temperature.setDecimals(0)
        hl2.addWidget(self.combo_plan, 2)
        hl2.addWidget(QtWidgets.QLabel("  Temp. max :"), 0)
        hl2.addWidget(self.spin_temperature, 1)
        f.addRow("Plan d'esquisse :", hl2)

        # Ligne 3 : type de montage
        self.combo_montage = QtWidgets.QComboBox()
        self.combo_montage.addItem("Statique",                "statique")
        self.combo_montage.addItem("Dynamique — translation", "dynamique_translation")
        self.combo_montage.addItem("Dynamique — rotation",    "dynamique_rotation")
        f.addRow("Type de montage :", self.combo_montage)

        # Ligne 4 : fluide (indicatif)
        self.edit_fluide = QtWidgets.QLineEdit()
        self.edit_fluide.setPlaceholderText("ex. huiles_minerales  (indicatif, verifie la compatibilite materiau)")
        f.addRow("Fluide :", self.edit_fluide)

        self.combo_position.currentIndexChanged.connect(self._on_position_change)
        # Recalcul auto quand conditions changent
        self.spin_pression.valueChanged.connect(self._on_recalcul_si_resultat)
        self.spin_temperature.valueChanged.connect(self._on_recalcul_si_resultat)
        self.edit_fluide.editingFinished.connect(self._on_recalcul_si_resultat)
        return grp

    # ------------------------------------------------------------------
    # Section Matériau
    # ------------------------------------------------------------------
    def _section_materiau(self):
        grp = QtWidgets.QGroupBox("Matériau")
        layout = QtWidgets.QVBoxLayout(grp)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.combo_materiau = QtWidgets.QComboBox()
        for abrev in liste_materiaux():
            m = get_materiau(abrev)
            self.combo_materiau.addItem(f"{abrev} — {m['nom_complet']}", abrev)
        form.addRow("Matériau :", self.combo_materiau)

        self.text_materiau_info = QtWidgets.QTextEdit()
        self.text_materiau_info.setReadOnly(True)
        self.text_materiau_info.setMinimumHeight(110)
        self.text_materiau_info.setMaximumHeight(300)
        self.text_materiau_info.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self.text_materiau_info.setFontFamily("Courier")
        self.text_materiau_info.setFontPointSize(9)
        layout.addWidget(self.text_materiau_info)

        self.combo_materiau.currentIndexChanged.connect(self._on_materiau_change)
        self._on_materiau_change()
        return grp

    def _on_materiau_change(self, _=None):
        abrev = self.combo_materiau.currentData()
        if not abrev:
            return
        m = get_materiau(abrev)
        t = m['temperature']
        lignes = [
            f"T  : {t['min_C']}°C ... {t['max_C']}°C",
            f"P  max : {m['pression_max_bar']} bar",
            f"Durete : {m['durete_shore_A']} Shore A  (std : {m['durete_standard']})",
            "",
            "Compatible   : " + ", ".join(m['compatibilite'][:5]) +
            (" ..." if len(m['compatibilite']) > 5 else ""),
            "Incompatible : " + ", ".join(m['incompatibilite'][:4]) +
            (" ..." if len(m['incompatibilite']) > 4 else ""),
        ]
        self.text_materiau_info.setPlainText("\n".join(lignes))
        self._on_recalcul_si_resultat()

    # ------------------------------------------------------------------
    # Section Joint / Gorge
    # ------------------------------------------------------------------
    def _section_joint(self):
        grp = QtWidgets.QGroupBox("Joint / Gorge")
        f = QtWidgets.QFormLayout(grp)
        f.setVerticalSpacing(8)

        # Ligne 1 : Standard + Série + D1 (3 combos sur une ligne)
        hl_std = QtWidgets.QHBoxLayout()
        self.combo_standard = QtWidgets.QComboBox()
        for std in STANDARDS:
            self.combo_standard.addItem(std, std)
        self.combo_serie = QtWidgets.QComboBox()
        self.combo_serie.addItem("Auto", "")
        hl_std.addWidget(self.combo_standard, 2)
        hl_std.addWidget(QtWidgets.QLabel("  Série (d2) :"), 0)
        hl_std.addWidget(self.combo_serie, 3)
        f.addRow("Standard :", hl_std)
        self.combo_standard.currentIndexChanged.connect(self._on_standard_change)
        self.combo_serie.currentIndexChanged.connect(self._on_serie_change)
        self._on_standard_change()

        # Ligne 2 : Squeeze cible
        hl_sq = QtWidgets.QHBoxLayout()
        self.spin_squeeze = QtWidgets.QDoubleSpinBox()
        self.spin_squeeze.setRange(0, 50)
        self.spin_squeeze.setSuffix(" %")
        self.spin_squeeze.setDecimals(1)
        self.spin_squeeze.setValue(0.0)
        self.spin_squeeze.setToolTip(
            "0 = valeur cible automatique selon le type de montage\n"
            "Toute valeur > 0 desactive le mode automatique."
        )
        self.lbl_squeeze_info = QtWidgets.QLabel()
        self.lbl_squeeze_info.setWordWrap(True)
        hl_sq.addWidget(self.spin_squeeze, 0)
        hl_sq.addWidget(self.lbl_squeeze_info, 1)
        f.addRow("Squeeze cible :", hl_sq)
        self.spin_squeeze.valueChanged.connect(self._on_squeeze_info_change)
        self.combo_montage.currentIndexChanged.connect(self._on_squeeze_info_change)
        # Recalcul automatique quand montage ou squeeze changent (si résultat déjà présent)
        self.spin_squeeze.valueChanged.connect(self._on_recalcul_si_resultat)
        self.combo_montage.currentIndexChanged.connect(self._on_recalcul_si_resultat)
        self._on_squeeze_info_change()

        # Ligne 3 : désignation joint calculée (mise à jour par _on_calculer)
        self.lbl_joint_designation = QtWidgets.QLabel("—")
        self.lbl_joint_designation.setStyleSheet("QLabel { font-weight: bold; }")
        f.addRow("Joint sélectionné :", self.lbl_joint_designation)

        # Ligne 4 : dimensions gorge calculées
        self.lbl_joint_dims = QtWidgets.QLabel("—")
        f.addRow("Dimensions gorge :", self.lbl_joint_dims)

        # Grades IT tolérances — désactivés temporairement

        return grp

    def _on_standard_change(self, _=None):
        self._rafraichir_combo_serie()
        self._on_recalcul_si_resultat()

    def _rafraichir_combo_serie(self):
        """
        Reconstruit le combo série en grisrant les séries dont aucun joint
        n'offre un stretch dans la plage acceptable pour le diamètre courant.

        Logique compatible avec choisir_d1() :
          gorge arbre   : d_ref = D_arbre = D_alésage − 2×jeu
            → série compatible si ∃ d1 avec  -0.5% ≤ stretch ≤ 5%
          gorge alésage : d_ref = D_arbre (pièce complémentaire = arbre)
            → série compatible si ∃ d1 avec   0% ≤ compression ≤ 3%

        Utilise QStandardItemModel pour un grisage fiable sous PySide2/FreeCAD.
        """
        # Guard : appelée parfois avant la construction complète du dialogue
        if not hasattr(self, 'combo_standard') or not hasattr(self, 'combo_serie'):
            return

        try:
            from PySide2.QtGui  import QStandardItemModel, QStandardItem, QBrush, QColor
            from PySide2.QtCore import Qt
        except ImportError:
            return

        std      = self.combo_standard.currentData()
        position = self.combo_position.currentData() if hasattr(self, 'combo_position') else 'arbre'
        d_compl  = self._get_diametre_calcul()
        jeu      = self._get_jeu_radial()      if hasattr(self, 'spin_jeu')       else 0.1

        # _get_diametre_calcul() retourne le diamètre de la pièce COMPLÉMENTAIRE :
        #   gorge arbre   → d_compl = D_alésage  ⟹  D_arbre = D_alésage − 2×jeu
        #   gorge alésage → d_compl = D_arbre
        #
        # Référence pour choisir_d1 :
        #   gorge ARBRE   → D_fond = D_arbre − 2×h, h = d2×(1−squeeze/100)
        #                   On approxime avec d2 de chaque série et le squeeze
        #                   courant (ou valeur cible par défaut).
        #   gorge ALÉSAGE → D_arbre directement (compression initiale)
        if d_compl and d_compl > 0:
            if position == 'arbre':
                d_arbre = max(0.0, d_compl - 2.0 * jeu)
            else:
                d_arbre = d_compl
        else:
            d_arbre = 0.0

        # Squeeze effectif : si 0 (mode auto), prendre la valeur cible du type de montage.
        # Même logique que calcul.py étape 6.
        _sq_raw = self.spin_squeeze.value() if hasattr(self, 'spin_squeeze') else 0.0
        if _sq_raw > 0:
            sq_pct = _sq_raw
        else:
            # Mode auto : valeur cible selon type de montage
            _type_mt = (self.combo_montage.currentData()
                        if hasattr(self, 'combo_montage') else 'statique')
            try:
                sq_pct = get_plage_squeeze(_type_mt)['cible']
            except Exception:
                sq_pct = 22.0   # fallback

        # d_ref sera calculé PAR SÉRIE dans la boucle pour gorge arbre
        # (D_fond = D_arbre − 2×h dépend de d2 propre à chaque série)
        d_ref_arbre = d_arbre   # pour gorge alésage et fallback

        serie_courante = self.combo_serie.currentData()

        # Construire un QStandardItemModel : seule API garantissant setEnabled()
        model = QStandardItemModel(self.combo_serie)

        item_auto = QStandardItem('Auto')
        item_auto.setData('', Qt.UserRole)
        item_auto.setEnabled(True)
        item_auto.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        model.appendRow(item_auto)

        if std:
            series = liste_series(std)
            d2s    = liste_d2(std)
            for i, s in enumerate(series):
                d2_val = d2s[i]
                compatible = True
                raison     = ''

                # Pour gorge arbre, D_fond dépend de d2 de la série
                if position == 'arbre' and d_ref_arbre > 0:
                    h_approx = d2_val * (1.0 - sq_pct / 100.0)
                    d_ref = max(0.0, d_ref_arbre - 2.0 * h_approx)
                else:
                    d_ref = d_ref_arbre   # alésage : D_arbre directement

                if d_ref > 0:
                    try:
                        res    = choisir_d1(std, s, d_ref, position)
                        sp     = res.get('stretch_pct', 0.0)
                        d1_res = res.get('d1', 0.0)
                        # Aligner sur le seuil bloquant de calcul.py (max_bloquant=8%)
                        # → grisé seulement si physiquement impossible, orange si 5–8%
                        try:
                            from .joints import _params_calcul as _pc
                            _st = _pc()['stretch']
                            BLOQUANT = _st['arbre']['max_bloquant'] if position == 'arbre' else 999
                            COMPR_MAX = _st['alesage']['compression_max'] if position == 'alesage' else 999
                        except Exception:
                            BLOQUANT, COMPR_MAX = 8.0, 3.0
                        if position == 'arbre':
                            impossible = sp < -0.5 or sp > BLOQUANT
                        else:
                            compr = -sp
                            impossible = compr > COMPR_MAX or sp > 0.5
                        compatible = not impossible
                        if not compatible:
                            if position == 'arbre':
                                raison = (f'd1={d1_res:.1f} > D_fond' if sp < -0.5
                                          else f'stretch {sp:.0f}% > {BLOQUANT:.0f}%')
                            else:
                                raison = (f'd1={d1_res:.1f} < D_arbre' if sp > 0.5
                                          else f'compr. {-sp:.0f}% > {COMPR_MAX:.0f}%')
                        elif sp > 5.0 or (position != 'arbre' and -sp > 1.5):
                            # Compatible mais hors plage idéale → orange
                            raison = f'⚠ stretch {sp:.1f}%' if position == 'arbre' else f'⚠ compr. {-sp:.1f}%'
                        elif res.get('avertissements'):
                            sp2 = sp
                            raison = f'⚠ stretch {sp2:.1f}%'
                    except Exception:
                        pass

                if compatible and not raison:
                    label = f'{s}  (Ø {d2_val} mm)'
                elif compatible and raison:
                    # Compatible mais avec avertissement (stretch 3–5%)
                    label = f'{s}  (Ø {d2_val} mm)  {raison}'
                else:
                    label = f'{s}  (Ø {d2_val} mm)  — {raison}'

                item = QStandardItem(label)
                item.setData(s, Qt.UserRole)
                if not compatible:
                    item.setEnabled(False)
                    item.setForeground(QBrush(QColor(150, 150, 150)))
                elif raison:
                    # Accepté mais affiché en orange pour le warning
                    item.setForeground(QBrush(QColor(180, 100, 0)))
                model.appendRow(item)

        self.combo_serie.blockSignals(True)
        self.combo_serie.setModel(model)

        # Restaurer la sélection précédente uniquement si encore compatible
        restored = False
        if serie_courante:
            for i in range(model.rowCount()):
                it = model.item(i)
                if it and it.data(Qt.UserRole) == serie_courante and it.isEnabled():
                    self.combo_serie.setCurrentIndex(i)
                    restored = True
                    break
        if not restored:
            self.combo_serie.setCurrentIndex(0)

        self.combo_serie.blockSignals(False)

    def _on_serie_change(self, _=None):
        """Remet l'item Auto a son texte neutre si selection manuelle,
        puis recalcule si la saisie est complete.
        Cela garantit que changer le diametre de fil (serie) met
        immediatement a jour le resultat, meme avant un premier clic
        sur Calculer."""
        if self.combo_serie.currentData() != "":
            self.combo_serie.blockSignals(True)
            # Conserver le d2 connu si disponible
            _d2_auto = (self._resultat.d2
                        if self._resultat and self._resultat.d2 else None)
            _lbl = f"Auto (Ø {_d2_auto})" if _d2_auto else "Auto"
            self.combo_serie.setItemText(0, _lbl)
            self.combo_serie.blockSignals(False)
        # Recalculer si la saisie est suffisante (indépendant de _resultat)
        if self._saisie_complete():
            self._on_calculer()

    # ------------------------------------------------------------------
    # Étape 1c — Indicateur visuel squeeze auto / manuel
    # ------------------------------------------------------------------
    def _on_squeeze_info_change(self, _=None):
        """Met a jour lbl_squeeze_info selon le mode (auto=0 ou manuel>0)."""
        if not hasattr(self, 'lbl_squeeze_info') or not hasattr(self, 'combo_montage'):
            return

        type_montage = self.combo_montage.currentData() or 'statique'
        try:
            plage = get_plage_squeeze(type_montage)
        except Exception:
            return

        cible = plage['cible']
        pmin  = plage['min']
        pmax  = plage['max']
        val   = self.spin_squeeze.value()

        if val == 0.0:
            # ── Mode automatique : gris italique ──────────────────────
            self.lbl_squeeze_info.setText(
                f"\u27f3  Auto : {cible:.1f} %   "
                f"(plage recommand\u00e9e : {pmin}\u2013{pmax} %)"
            )
            self.lbl_squeeze_info.setStyleSheet(
                "QLabel { color: #888888; font-style: italic; }"
            )
        else:
            # ── Mode manuel ───────────────────────────────────────────
            hors_plage = (val < pmin or val > pmax)
            if hors_plage:
                self.lbl_squeeze_info.setText(
                    f"\u270e  Manuel  \u2014  recommand\u00e9 : {pmin}\u2013{pmax} %  "
                    f"\u26a0 hors plage"
                )
                self.lbl_squeeze_info.setStyleSheet(
                    "QLabel { color: #cc6600; font-weight: bold; }"
                )
            else:
                self.lbl_squeeze_info.setText(
                    f"\u270e  Manuel  \u2014  recommand\u00e9 : {pmin}\u2013{pmax} %"
                )
                self.lbl_squeeze_info.setStyleSheet(
                    "QLabel { color: #0055aa; }"
                )


    def _on_recalcul_si_resultat(self, _=None):
        """Recalcule dès que la saisie est complète."""
        if self._saisie_complete():
            self._on_calculer()

    # ------------------------------------------------------------------
    # Section Pieces FreeCAD (2 colonnes : gorge | complementaire)
    # ------------------------------------------------------------------
    def _section_pieces(self):
        grp = QtWidgets.QGroupBox("Pièces FreeCAD")
        outer = QtWidgets.QVBoxLayout(grp)

        if self._doc:
            titre_p, titre_c = _libelles_position('arbre')

            # ── 2 colonnes côte à côte ────────────────────────────────────
            cols = QtWidgets.QHBoxLayout()
            cols.setSpacing(8)

            # Colonne gauche : pièce portant la gorge
            left_box = QtWidgets.QVBoxLayout()
            bodies_gorge = lister_bodies_valides_gorge(self._doc)
            self.widget_piece_principale = WidgetSelectBody(
                titre_p, self._doc, bodies=bodies_gorge
            )
            # FIX #8 : pré-cocher radio selon le dernier joint inséré
            if self._dernier_radio_rayon:
                self.widget_piece_principale.radio_rayon.setChecked(True)
            left_box.addWidget(self.widget_piece_principale)

            # LCS dans la colonne gauche (juste sous le widget principal)
            grp_lcs = QtWidgets.QGroupBox("LCS  (plan médian gorge)")
            lcs_layout = QtWidgets.QFormLayout(grp_lcs)
            self.combo_lcs = QtWidgets.QComboBox()
            self.combo_lcs.addItem("— selectionner —", None)
            lcs_layout.addRow("LCS :", self.combo_lcs)
            note_lcs = QtWidgets.QLabel("Plan XZ du LCS = axe Z pièce.")
            note_lcs.setStyleSheet("font-style: italic;")
            lcs_layout.addRow(note_lcs)
            left_box.addWidget(grp_lcs)
            left_box.addStretch()
            cols.addLayout(left_box, 1)

            # Colonne droite : pièce complémentaire
            right_box = QtWidgets.QVBoxLayout()
            bodies_comp = lister_bodies_valides_comp(self._doc, exclure=None)
            self.widget_piece_complementaire = WidgetSelectBody(
                titre_c, self._doc, bodies=bodies_comp
            )
            # FIX #8 : même logique pour la pièce complémentaire
            if self._dernier_radio_rayon:
                self.widget_piece_complementaire.radio_rayon.setChecked(True)
            # Label "dimension de référence" sous le widget complémentaire
            lbl_ref = QtWidgets.QLabel("(Dimension de référence pour le calcul)")
            lbl_ref.setStyleSheet("font-style: italic;")
            right_box.addWidget(self.widget_piece_complementaire)
            right_box.addWidget(lbl_ref)
            right_box.addStretch()
            cols.addLayout(right_box, 1)

            outer.addLayout(cols)

            # ── Jeu radial + diamètre dérivé (pleine largeur) ─────────────
            jeu_form = QtWidgets.QFormLayout()
            jeu_form.setVerticalSpacing(6)

            # ── Nouveau Ø pièce complémentaire (mode modification seulement) ──
            self.lbl_d_comp_modif = QtWidgets.QLabel("Nouveau Ø pièce comp. :")
            self.lbl_d_comp_modif.setVisible(False)
            self.spin_d_comp_modif = QtWidgets.QDoubleSpinBox()
            self.spin_d_comp_modif.setRange(0.1, 5000.0)
            self.spin_d_comp_modif.setSuffix(" mm")
            self.spin_d_comp_modif.setDecimals(3)
            self.spin_d_comp_modif.setVisible(False)
            self.spin_d_comp_modif.setToolTip(
                "Diamètre cible de la pièce complémentaire.\n"
                "En mode modification : permet de recalculer la gorge\n"
                "ET de mettre à jour le paramètre de la pièce complémentaire."
            )
            jeu_form.addRow(self.lbl_d_comp_modif, self.spin_d_comp_modif)
            self.spin_d_comp_modif.valueChanged.connect(self._on_dims_change)

            # ── Mode jeu : Manuel / ISO H/g / ISO H/f ─────────────────
            hl_mode = QtWidgets.QHBoxLayout()
            self.combo_mode_jeu = QtWidgets.QComboBox()
            self.combo_mode_jeu.addItem("Manuel",  "manuel")
            self.combo_mode_jeu.addItem("ISO H/g", "g")
            self.combo_mode_jeu.addItem("ISO H/f", "f")
            self.combo_mode_jeu.setToolTip(
                "Manuel : jeu radial saisi directement.\n"
                "ISO H/g : ajustement à jeu garanti (ex. H7/g6).\n"
                "ISO H/f : ajustement à jeu large (ex. H8/f7).\n"
                "En mode ISO, le jeu minimal calculé est utilisé automatiquement."
            )
            self.lbl_grade_arbre = QtWidgets.QLabel("Grade arbre :")
            self.combo_grade_arbre = QtWidgets.QComboBox()
            for _g in (6, 7, 8, 9):
                self.combo_grade_arbre.addItem(f"IT{_g}", _g)
            self.combo_grade_arbre.setCurrentIndex(1)   # IT7 par défaut
            self.combo_grade_arbre.setToolTip(
                "Grade IT de l'arbre.\nL'alésage H prend le grade + 1 automatiquement."
            )
            self.lbl_designation_iso = QtWidgets.QLabel("")
            self.lbl_designation_iso.setStyleSheet("font-weight: bold; color: #335599;")
            hl_mode.addWidget(self.combo_mode_jeu)
            hl_mode.addWidget(self.lbl_grade_arbre)
            hl_mode.addWidget(self.combo_grade_arbre)
            hl_mode.addWidget(self.lbl_designation_iso)
            hl_mode.addStretch()
            jeu_form.addRow("Mode jeu :", hl_mode)

            # Masquer grade par défaut (mode Manuel)
            self.lbl_grade_arbre.setVisible(False)
            self.combo_grade_arbre.setVisible(False)
            self.lbl_designation_iso.setVisible(False)

            # ── Jeu radial (Manuel) ─────────────────────────────────────
            self.spin_jeu = QtWidgets.QDoubleSpinBox()
            self.spin_jeu.setRange(0.0, 5.0)
            self.spin_jeu.setSuffix(" mm")
            self.spin_jeu.setDecimals(3)
            self.spin_jeu.setValue(0.1)
            self.spin_jeu.setToolTip(
                "Jeu radial entre arbre et alésage.\n"
                "Gorge arbre   : D_arbre   = D_alésage - 2 × jeu\n"
                "Gorge alésage : D_alésage = D_arbre   + 2 × jeu\n"
                "(Désactivé en mode ISO — valeur calculée automatiquement.)"
            )
            jeu_form.addRow("Jeu radial :", self.spin_jeu)

            self.label_d_principale_derive = QtWidgets.QLabel("—")
            self.label_d_principale_derive.setStyleSheet("font-weight: bold;")
            jeu_form.addRow("⇒ D pièce principale :", self.label_d_principale_derive)
            outer.addLayout(jeu_form)

            # ── Diagramme ajustement ISO ────────────────────────────────
            self._diagramme_ajust = _DiagrammeAjustement()
            self._diagramme_ajust.setVisible(False)
            outer.addWidget(self._diagramme_ajust)

            # Connexions
            self.widget_piece_principale.combo_body.currentIndexChanged.connect(
                self._on_piece_principale_change
            )
            self.widget_piece_complementaire.combo_body.currentIndexChanged.connect(
                self._on_dims_change
            )
            self.widget_piece_complementaire.combo_param.currentIndexChanged.connect(
                self._on_dims_change
            )
            self.widget_piece_complementaire.radio_diametre.toggled.connect(
                self._on_dims_change
            )
            self.spin_jeu.valueChanged.connect(self._on_dims_change)
            self.combo_mode_jeu.currentIndexChanged.connect(self._on_mode_jeu_change)
            self.combo_grade_arbre.currentIndexChanged.connect(self._on_mode_jeu_change)
            self.combo_position.currentIndexChanged.connect(self._on_dims_change)
            self._on_dims_change()

            # ── Recalcul automatique dès que la saisie est complète ──────
            self.widget_piece_principale.combo_body.currentIndexChanged.connect(
                self._on_recalcul_si_resultat
            )
            self.widget_piece_principale.combo_param.currentIndexChanged.connect(
                self._on_recalcul_si_resultat
            )
            self.combo_lcs.currentIndexChanged.connect(self._on_recalcul_si_resultat)
            self.combo_lcs.currentIndexChanged.connect(
                lambda _: self._rafraichir_combo_serie()
            )
            self.combo_lcs.currentIndexChanged.connect(self._on_lcs_change)
            self.widget_piece_complementaire.combo_body.currentIndexChanged.connect(
                self._on_recalcul_si_resultat
            )
            self.widget_piece_complementaire.combo_param.currentIndexChanged.connect(
                self._on_recalcul_si_resultat
            )
            # ── Initialisation forcée après connexions ────────────────────
            # Sans cet appel, le LCS combo reste vide si le body principal a
            # été auto-sélectionné AVANT que _on_piece_principale_change
            # soit connecté (problème de timing construction Qt).
            self._on_piece_principale_change()
            self._on_recalcul_si_resultat()

        else:
            outer.addWidget(QtWidgets.QLabel(
                "Aucun document FreeCAD actif.\n"
                "Utilisez le diamètre manuel dans la section Joint / Gorge."
            ))

        return grp

    # ------------------------------------------------------------------
    def _saisie_complete(self) -> bool:
        """
        Retourne True si tous les champs obligatoires sont renseignés :
          - body principal sélectionné
          - paramètre Ø du body principal sélectionné
          - LCS sélectionné
          - body complémentaire sélectionné
          - paramètre Ø du body complémentaire sélectionné
        """
        if not hasattr(self, 'widget_piece_principale'):
            # Pas de doc FreeCAD : on n'interdit pas le calcul (diamètre manuel)
            return True
        if not self.widget_piece_principale.est_complete():
            return False
        if not hasattr(self, 'combo_lcs'):
            return False
        if self.combo_lcs.currentData() is None:
            return False
        # En mode modification, la pièce complémentaire est gelée (non
        # modifiable) et son diamètre est stocké dans _d_comp_ref_modif.
        # On ne bloque pas le calcul sur ce widget.
        if self._part_en_modification is None:
            if not self.widget_piece_complementaire.est_complete():
                return False
        return True

    def _on_saisie_change(self, _=None):
        """Déclenche recalcul si saisie complète, désactive Appliquer sinon."""
        if self._saisie_complete():
            self._on_calculer()
        else:
            if hasattr(self, 'btn_appliquer'):
                self.btn_appliquer.setEnabled(False)
            self._resultat = None

    def _on_dims_change(self, _=None):
        """Recalcule et affiche le diametre derive de la piece principale.
        Rafraîchit aussi le combo série pour mettre à jour les indicateurs
        de compatibilité avec le nouveau diamètre.
        En mode modification, déclenche automatiquement le recalcul dès que
        le diamètre change (pas de bouton Calculer intermédiaire requis)."""
        if self._calcul_en_cours:
            return
        if hasattr(self, 'combo_serie'):
            self._calcul_en_cours = True
            try:
                self._rafraichir_combo_serie()
            finally:
                self._calcul_en_cours = False
        if not hasattr(self, 'spin_jeu'):
            return
        position = self.combo_position.currentData()
        d_comp = self._get_diametre_calcul()
        jeu    = self.spin_jeu.value()
        if d_comp and d_comp > 0:
            if position == 'arbre':
                d_princ = d_comp - 2.0 * jeu
                label   = f"D_arbre = {d_comp:.3f} - 2×{jeu:.3f} = {d_princ:.3f} mm"
            else:
                d_princ = d_comp + 2.0 * jeu
                label   = f"D_alesage = {d_comp:.3f} + 2×{jeu:.3f} = {d_princ:.3f} mm"
            self.label_d_principale_derive.setText(label)
        else:
            self.label_d_principale_derive.setText("—")

        # Rafraîchir le diagramme ISO si actif
        if hasattr(self, 'combo_mode_jeu'):
            lettre = self.combo_mode_jeu.currentData()
            if lettre in ('f', 'g'):
                d_iso = self._get_diametre_iso()
                if d_iso and d_iso > 0:
                    grade = self.combo_grade_arbre.currentData() or 7
                    try:
                        data = ecarts_arbre(d_iso, lettre, grade)
                        self.spin_jeu.blockSignals(True)
                        self.spin_jeu.setValue(round(data['jeu_min_mm'], 4))
                        self.spin_jeu.blockSignals(False)
                        self.lbl_designation_iso.setText(data['designation'])
                        if hasattr(self, '_diagramme_ajust'):
                            self._diagramme_ajust.set_data(data)
                    except Exception:
                        pass

        # Recalcul automatique si la saisie est complète
        # (en mode modification : spin_d_comp_modif remplace le widget pièce complémentaire)
        if self._saisie_complete():
            self._on_calculer()


    def _on_lcs_change(self, _=None):
        """
        FIX #10 — Sélectionne et met en surbrillance le LCS choisi dans
        la vue 3D FreeCAD. Aide l'utilisateur à visualiser l'emplacement
        du plan médian de la gorge avant de valider.
        """
        if not FREECAD_DISPONIBLE:
            return
        try:
            import FreeCADGui as Gui
            lcs = self.combo_lcs.currentData() if hasattr(self, 'combo_lcs') else None
            if lcs is None:
                return
            doc = self._doc
            if doc is None:
                return
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, lcs.Name)
        except Exception as _e:
            pass   # non bloquant — juste une aide visuelle

    def _on_piece_principale_change(self, _=None):
        """
        Déclenché quand le body principal change.
        1. Rafraîchit la liste des LCS du nouveau body principal.
        2. Étape 1a : exclut ce body de la liste des bodies complémentaires.
        """
        if not hasattr(self, 'combo_lcs'):
            return

        body_principal = self.widget_piece_principale.get_body()

        # Rafraîchir le combo LCS
        self.combo_lcs.clear()
        self.combo_lcs.addItem("— selectionner —", None)
        if body_principal:
            lcs_list  = lister_lcs(body_principal)
            deja_pris = _lcs_deja_utilises(self._doc)
            # En mode modification, le LCS du joint en cours reste disponible
            if self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    m = lire_metadonnees(self._part_en_modification)
                    lcs_modif = m.get('lcs_label', '')
                    deja_pris = deja_pris - {lcs_modif}
                except Exception:
                    pass
            lcs_libres = [lcs for lcs in lcs_list
                          if lcs.Label not in deja_pris]
            for lcs in lcs_libres:
                self.combo_lcs.addItem(lcs.Label, lcs)
            # Auto-sélection si un seul LCS disponible
            if len(lcs_libres) == 1:
                self.combo_lcs.setCurrentIndex(1)

        # Étape 1a : rafraîchir la liste complémentaire en excluant le body principal
        if hasattr(self, 'widget_piece_complementaire') and self._doc:
            bodies_comp = lister_bodies_valides_comp(
                self._doc, exclure=body_principal
            )
            self.widget_piece_complementaire.set_bodies(bodies_comp)

    def _on_position_change(self, _=None):
        if not hasattr(self, 'widget_piece_principale'):
            return
        position = self.combo_position.currentData()
        tp, tc = _libelles_position(position)
        self.widget_piece_principale.setTitle(tp)
        if hasattr(self, 'widget_piece_complementaire'):
            self.widget_piece_complementaire.setTitle(tc)
        self._on_dims_change()
        self._on_recalcul_si_resultat()

    # ------------------------------------------------------------------
    # Diametre pour le calcul (= piece complementaire)
    # ------------------------------------------------------------------
    def _get_diametre_calcul(self):
        """
        Retourne le diametre de la piece COMPLEMENTAIRE.
        En mode modification : utilise la valeur de référence stockée dans
        les métadonnées (_d_comp_ref_modif), qui correspond au diamètre
        au moment de l'insertion.
        En mode création : lit le widget widget_piece_complementaire.
        """
        if self._part_en_modification is not None:
            # Priorité 1 : spin_d_comp_modif si visible (saisi manuellement)
            if (hasattr(self, 'spin_d_comp_modif')
                    and self.spin_d_comp_modif.isVisible()):
                return self.spin_d_comp_modif.value()
            # Priorité 2 : valeur courante du paramètre FreeCAD
            # (reflète toute modification faite dans le modèle)
            if hasattr(self, 'widget_piece_complementaire'):
                d_courant = self.widget_piece_complementaire.get_diametre_mm()
                if d_courant and d_courant > 0:
                    return d_courant
            # Priorité 3 : valeur de référence stockée en métadonnées
            if hasattr(self, '_d_comp_ref_modif') and self._d_comp_ref_modif > 0:
                return self._d_comp_ref_modif
        if hasattr(self, 'widget_piece_complementaire'):
            d = self.widget_piece_complementaire.get_diametre_mm()
            if d and d > 0:
                return d
        return 0.0

    def _get_jeu_radial(self) -> float:
        """
        Retourne le jeu radial effectif (mm).
        - Mode Manuel : valeur de spin_jeu.
        - Mode ISO    : jeu_min_mm calculé par ecarts_arbre().
        """
        if not hasattr(self, 'spin_jeu'):
            return 0.1
        if hasattr(self, 'combo_mode_jeu'):
            lettre = self.combo_mode_jeu.currentData()
            if lettre in ('f', 'g'):
                d_iso = self._get_diametre_iso()
                if d_iso and d_iso > 0:
                    grade = self.combo_grade_arbre.currentData() or 7
                    try:
                        data = ecarts_arbre(d_iso, lettre, grade)
                        return data['jeu_min_mm']
                    except Exception:
                        pass
        return self.spin_jeu.value()

    def _get_diametre_iso(self) -> float:
        """
        Diamètre nominal utilisé pour les calculs ISO 286-1.
        Gorge arbre   → diamètre alésage (pièce complémentaire)
        Gorge alésage → diamètre arbre   (pièce complémentaire)
        Dans les deux cas = diamètre de la pièce complémentaire.
        """
        return self._get_diametre_calcul()

    def _on_mode_jeu_change(self, _=None):
        """Bascule Manuel ↔ ISO : active/désactive les widgets et rafraîchit le diagramme."""
        if not hasattr(self, 'combo_mode_jeu'):
            return
        lettre = self.combo_mode_jeu.currentData()
        mode_iso = lettre in ('f', 'g')

        # Visibilité grade + désignation
        self.lbl_grade_arbre.setVisible(mode_iso)
        self.combo_grade_arbre.setVisible(mode_iso)
        self.lbl_designation_iso.setVisible(mode_iso)

        # Activation spin_jeu
        self.spin_jeu.setEnabled(not mode_iso)

        if mode_iso:
            d_iso = self._get_diametre_iso()
            if d_iso and d_iso > 0:
                grade = self.combo_grade_arbre.currentData() or 7
                try:
                    data = ecarts_arbre(d_iso, lettre, grade)
                    # Forcer spin_jeu à la valeur ISO (lecture seule)
                    self.spin_jeu.blockSignals(True)
                    self.spin_jeu.setValue(round(data['jeu_min_mm'], 4))
                    self.spin_jeu.blockSignals(False)
                    self.lbl_designation_iso.setText(data['designation'])
                    if hasattr(self, '_diagramme_ajust'):
                        self._diagramme_ajust.set_data(data)
                        self._diagramme_ajust.setVisible(True)
                except Exception as e:
                    self.lbl_designation_iso.setText("—")
                    if hasattr(self, '_diagramme_ajust'):
                        self._diagramme_ajust.clear()
            else:
                self.lbl_designation_iso.setText("(saisir Ø d'abord)")
                if hasattr(self, '_diagramme_ajust'):
                    self._diagramme_ajust.clear()
                    self._diagramme_ajust.setVisible(True)
        else:
            self.lbl_designation_iso.setText("")
            if hasattr(self, '_diagramme_ajust'):
                self._diagramme_ajust.setVisible(False)
                self._diagramme_ajust.clear()

        self._on_dims_change()

    # ------------------------------------------------------------------
    # Action : Calculer
    # ------------------------------------------------------------------
    def _on_calculer(self):
        diametre = self._get_diametre_calcul()
        if diametre <= 0:
            return   # saisie incomplète — pas de message d'erreur

        position = self.combo_position.currentData()

        avert = ""  # pas d'avertissement : le diametre complementaire est toujours saisi

        _serie_val = self.combo_serie.currentData() or ''

        # calculer_gorge attend TOUJOURS D_alesage comme diametre_piece_mm.
        # _get_diametre_calcul() retourne D_comp :
        #   position 'arbre'   → D_comp = D_alesage  → OK directement
        #   position 'alesage' → D_comp = D_arbre    → recalculer D_alesage
        jeu_mm = self._get_jeu_radial()
        if position == 'alesage':
            d_alesage_calcul = diametre + 2.0 * jeu_mm
        else:
            d_alesage_calcul = diametre

        print(f"[ORing CALCUL] diametre_comp={diametre} d_alesage={d_alesage_calcul} "
              f"position={position} serie='{_serie_val}' "
              f"standard={self.combo_standard.currentData()}")
        self._resultat = calculer_gorge(
            diametre_piece_mm = d_alesage_calcul,
            position          = position,
            type_montage      = self.combo_montage.currentData(),
            materiau          = self.combo_materiau.currentData(),
            pression_bar      = self.spin_pression.value(),
            temperature_C     = self.spin_temperature.value(),
            fluide            = self.edit_fluide.text().strip(),
            standard          = self.combo_standard.currentData(),
            serie             = _serie_val,
            squeeze_cible_pct = self.spin_squeeze.value(),
            jeu_radial_mm     = self._get_jeu_radial(),
        )
        print(f"[ORing CALCUL] → d2={self._resultat.d2} serie_result={self._resultat.serie}")

        self._maj_synthese(self._resultat)    # (A) synthèse structurée
        # self._maj_tolerances(self._resultat)  # (B) désactivé

        # ── Si serie Auto, afficher la valeur d2 retenue dans le combo ──
        r = self._resultat
        if self.combo_serie.currentData() == '' and r.d2 is not None:
            self.combo_serie.blockSignals(True)
            self.combo_serie.setItemText(0, f"Auto (Ø {r.d2})")
            self.combo_serie.blockSignals(False)

        # ── Mise à jour des labels résumés dans la section Joint / Gorge ──
        if r.d1 is not None and r.d2 is not None:
            desig = f"{r.d1} × {r.d2} mm"
            if r.code_joint:
                desig += f"  [{r.code_joint}]"
            self.lbl_joint_designation.setText(desig)
        else:
            self.lbl_joint_designation.setText("—")

        if r.h is not None and r.b is not None:
            dims = (f"h = {r.h:.3f} mm   b = {r.b:.3f} mm   "
                    f"squeeze = {r.squeeze_pct:.1f} %   fill = {r.fill_pct:.1f} %")
            self.lbl_joint_dims.setText(dims)
        else:
            self.lbl_joint_dims.setText("—")
        # ──────────────────────────────────────────────────────────────────

        if self._resultat.valide:
            pass  # pas de style force : herite du theme
        else:
            pass  # idem

        doc_ok = self._doc is not None
        self.btn_appliquer.setEnabled(self._resultat.valide and doc_ok)
        # Griser Calculer : recalcul inutile tant que la saisie n'a pas changé

    def _formater_resultat(self, r):
        position = self.combo_position.currentData()
        label_d  = "D_alesage" if position == 'arbre' else "D_arbre"
        lignes = [
            "=" * 54,
            f"  Joint  : {r.standard} / serie {r.serie}",
            f"  d1 = {r.d1} mm   d2 = {r.d2} mm"
            + (f"   [{r.code_joint}]" if r.code_joint else ""),
            f"  Stretch ({label_d}) : {r.stretch_pct:.2f} %",
            "-" * 54,
            f"  Gorge  : h = {r.h:.3f} mm   b = {r.b:.3f} mm",
            f"  Squeeze: {r.squeeze_pct:.1f} %   Fill: {r.fill_pct:.1f} %",
            f"  Ø fond de gorge : {r.rayon_gorge * 2:.1f} mm",
            "-" * 54,
            f"  Extrusion : {r.risque_extrusion}"
            + ("  BAGUE REQUISE" if r.bague_antiextrusion else ""),
        ]
        if r.alertes:
            lignes += ["-" * 54, "  ALERTES :"]
            for a in r.alertes:
                lignes.append(f"    - {a}")
        if r.avertissements:
            lignes += ["-" * 54, "  Avertissements :"]
            for a in r.avertissements:
                lignes.append(f"    - {a}")
        lignes += [
            "=" * 54,
            f"  {'OK VALIDE' if r.valide else 'INVALIDE — voir alertes'}",
            "=" * 54,
        ]
        return "\n".join(lignes)

    # ------------------------------------------------------------------
    # Action : Appliquer dans FreeCAD
    # ------------------------------------------------------------------
    def _on_appliquer(self):
        """
        Sequence complete :

          0. Mise a jour du parametre diametre de la piece principale
             - Gorge arbre   : D_arbre   = D_alesage - 2 x jeu
             - Gorge alesage : D_alesage = D_arbre   + 2 x jeu
             La piece complementaire (sans gorge) n'est PAS modifiee.

          1. Sketch de demi-gorge accroche au plan XZ du LCS

          2. PartDesign::Groove 360 deg autour de V_Axis (axe Z)

          3. PartDesign::Mirrored par plan XY => gorge complete
        """
        # ── Guard anti-réentrance : empêche toute boucle déclenchée par
        # processEvents() ou QTimer.singleShot() pendant l'application ──
        if self._appliquer_en_cours:
            print("[ORing] _on_appliquer réentrant ignoré")
            return
        if not self._resultat or not self._doc:
            return
        self._appliquer_en_cours = True
        try:
            self._on_appliquer_interne()
        finally:
            self._appliquer_en_cours = False

    def _on_appliquer_interne(self):
        """Corps réel de _on_appliquer, protégé par le guard de réentrance."""
        if not self._resultat or not self._doc:
            return

        # ── Recalcul systématique avant application ──────────────────────────
        # Garantit que self._resultat reflète TOUS les paramètres UI courants
        # (type_montage, squeeze, standard, série, etc.), même si l'utilisateur
        # a modifié des combos sans recliquer "Calculer".
        try:
            from .calcul import calculer_gorge
            _d_comp = self._get_diametre_calcul()
            _pos    = self.combo_position.currentData()
            _jeu    = self._get_jeu_radial()
            _d_al   = (_d_comp + 2.0 * _jeu) if _pos == 'alesage' else _d_comp
            if _d_al > 0:
                self._resultat = calculer_gorge(
                    diametre_piece_mm = _d_al,
                    position          = _pos,
                    type_montage      = self.combo_montage.currentData(),
                    materiau          = self.combo_materiau.currentData(),
                    pression_bar      = self.spin_pression.value(),
                    temperature_C     = self.spin_temperature.value(),
                    fluide            = self.edit_fluide.text().strip(),
                    standard          = self.combo_standard.currentData(),
                    serie             = self.combo_serie.currentData() or '',
                    squeeze_cible_pct = self.spin_squeeze.value(),
                    jeu_radial_mm     = _jeu,
                )
        except Exception as e_recalc:
            print(f"[ORing] AVERT recalcul pre-appliquer : {e_recalc}")

        from .sketch_arbre   import generer_sketch_gorge_arbre
        from .sketch_alesage import generer_sketch_gorge_alesage
        from .oring_3d       import generer_oring_3d
        from .metadata       import creer_part_oring, nom_part, detecter_doublon

        body     = None
        lcs      = None
        position = self.combo_position.currentData()
        plan     = self.combo_plan.currentData()

        if hasattr(self, 'widget_piece_principale'):
            body = self.widget_piece_principale.get_body()
        if hasattr(self, 'combo_lcs'):
            lcs = self.combo_lcs.currentData()

        # Verification : body et LCS requis
        # En mode modification, les widgets pièce/LCS sont gelés mais peuplés
        # via _prefill_depuis_meta. On tente un fallback depuis les objets doc
        # si le combo retourne None (situation dégradée).
        if body is None and self._part_en_modification is not None and self._doc:
            try:
                from .metadata import lire_metadonnees
                _m = lire_metadonnees(self._part_en_modification)
                _bl = _m.get('body_gorge_label', '')
                body = next((b for b in lister_bodies(self._doc)
                             if b.Label == _bl), None)
            except Exception:
                pass
        if lcs is None and self._part_en_modification is not None and self._doc:
            try:
                from .metadata import lire_metadonnees
                _m  = lire_metadonnees(self._part_en_modification)
                _ll = _m.get('lcs_label', '')
                if body:
                    from .utils import lister_lcs
                    lcs = next((l for l in lister_lcs(body)
                                if l.Label == _ll), None)
            except Exception:
                pass

        if body is None:
            message_erreur("ORing",
                "Selectionner la piece portant la GORGE dans l'onglet 4.\n\n"
                "Gorge sur arbre   : selectionner le body ARBRE\n"
                "Gorge dans alesage: selectionner le body ALESAGE"
            )
            return
        if lcs is None:
            message_erreur("ORing",
                "Selectionner un LCS dans l'onglet 4.\n\n"
                "Ce LCS doit appartenir a la piece qui recoit la gorge.\n"
                "Le sketch sera accroche au plan XZ de ce LCS."
            )
            return

        # Helper : lire param_gorge / param_comp depuis le widget OU les métadonnées
        # (le widget est gelé en mode modification → get_nom_parametre() retourne None)
        def _get_param_gorge():
            v = (self.widget_piece_principale.get_nom_parametre()
                 if hasattr(self, 'widget_piece_principale') else None)
            if v is None and self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    v = lire_metadonnees(self._part_en_modification).get('param_gorge') or None
                except Exception:
                    pass
            return v or ''

        def _get_param_gorge_rayon():
            v = (self.widget_piece_principale.est_en_rayon()
                 if hasattr(self, 'widget_piece_principale') else False)
            if not v and self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    v = (lire_metadonnees(self._part_en_modification)
                         .get('param_gorge_rayon', 'diametre') == 'rayon')
                except Exception:
                    pass
            return v

        def _get_param_comp():
            v = (self.widget_piece_complementaire.get_nom_parametre()
                 if hasattr(self, 'widget_piece_complementaire') else None)
            if v is None and self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    v = lire_metadonnees(self._part_en_modification).get('param_comp') or None
                except Exception:
                    pass
            return v or ''

        def _get_param_comp_rayon():
            v = (self.widget_piece_complementaire.est_en_rayon()
                 if hasattr(self, 'widget_piece_complementaire') else False)
            if not v and self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    v = (lire_metadonnees(self._part_en_modification)
                         .get('param_comp_rayon', 'diametre') == 'rayon')
                except Exception:
                    pass
            return v

        # Diametres et jeu
        d_compl = self._get_diametre_calcul()
        if not d_compl or d_compl <= 0:
            message_erreur("ORing",
                "Diametre de la piece complementaire non renseigne.\n"
                "Selectionner le body et le parametre dans l'onglet 4,\n"
                "ou saisir le diametre manuellement dans l'onglet 3."
            )
            return
        jeu = self._get_jeu_radial()

        # Diametre ajuste de la piece principale
        if position == 'arbre':
            # Arbre tourne dans l'alesage : D_arbre = D_alesage - 2*jeu
            d_princ = d_compl - 2.0 * jeu
            r_compl = d_compl / 2.0   # r_alesage pour ligne construction sketch
        else:
            # Gorge dans alesage : D_alesage_piece = D_arbre + 2*jeu
            d_princ = d_compl + 2.0 * jeu
            r_compl = d_compl / 2.0   # r_arbre pour ligne construction sketch

        # ── Contrôle doublon (ignoré en mode modification) ──────────────────
        if self._part_en_modification is None:
            candidat_doublon = {
                'body_gorge_label':  body.Label,
                'lcs_label':         lcs.Label if lcs else '',
                'position':          position,
                'standard':          self.combo_standard.currentData() or '',
                'serie':             self.combo_serie.currentData() or '',
                'd2_mm':             float(self._resultat.d2) if self._resultat.d2 else 0.0,
                'squeeze_cible_pct': float(self.spin_squeeze.value()),
                'jeu_radial_mm':     float(jeu),
                'param_gorge':       _get_param_gorge(),
                'param_comp':        _get_param_comp(),
            }
            est_doublon, part_existant = detecter_doublon(self._doc, candidat_doublon)
            if est_doublon:
                from .metadata import lire_metadonnees
                nom_existant = part_existant.Label if part_existant else '?'
                m = lire_metadonnees(part_existant) if part_existant else {}
                message_erreur(
                    "ORing — Joint déjà existant",
                    f"Un joint est déjà présent à cet emplacement :\n\n"
                    f"  Pièce   : {m.get('body_gorge_label', '?')}\n"
                    f"  LCS     : {m.get('lcs_label', '?')}\n"
                    f"  Joint   : {m.get('standard', '?')} / "
                    f"{m.get('serie', '?')}  "
                    f"d2 = {m.get('d2_mm', 0.0):.2f} mm\n"
                    f"  Squeeze : {m.get('squeeze_cible_pct', 0.0):.1f} %  "
                    f"(réel : {m.get('squeeze_reel_pct', 0.0):.1f} %)\n"
                    f"  Gorge   : h = {m.get('h_mm', 0.0):.3f} mm  "
                    f"b = {m.get('b_mm', 0.0):.3f} mm\n\n"
                    f"  → Part existant : « {nom_existant} »\n\n"
                    "Supprimez l'assemblage existant pour en insérer un nouveau."
                )
                return

        try:
            # ── 0. Log de debug — body et LCS utilises ───────────────────
            print(
                f"[ORing] Body cible (gorge) : {body.Label}  |  "
                f"LCS : {lcs.Label if lcs else 'aucun'}  |  "
                f"Position : {position}"
            )
            # ── 0. Mise a jour du parametre de la piece principale ────────
            if hasattr(self, 'widget_piece_principale'):
                nom_param  = _get_param_gorge() or None
                est_rayon  = _get_param_gorge_rayon()
                print(
                    f"[ORing] d_compl={d_compl:.4f}  jeu={jeu:.4f}  "
                    f"d_princ={d_princ:.4f}  nom_param={nom_param!r}  "
                    f"est_rayon={est_rayon}  body={body.Label if body else 'None'}"
                )
                if nom_param:
                    valeur_param = d_princ / 2.0 if est_rayon else d_princ
                    ok, msg = mettre_a_jour_parametre(
                        body, nom_param, valeur_param
                    )
                    if ok:
                        print(
                            f"[ORing] Parametre '{nom_param}' mis a jour : "
                            f"{valeur_param:.4f} mm "
                            f"({'rayon' if est_rayon else 'diametre'})"
                        )
                        # recompute() obligatoire ici même en mode modification.
                        # Le changement de paramètre (DArbre, DAlesage…) doit
                        # être stabilisé AVANT les setDatum sur le sketch de
                        # gorge. Si les deux changements arrivent dans le même
                        # recompute, FreeCAD les traite dans un ordre qui peut
                        # laisser le Groove ignorer les nouvelles contraintes.
                        # Un 2ème recompute dans _mettre_a_jour_geometries_
                        # existantes propagera ensuite les contraintes.
                        self._doc.recompute()
                    else:
                        message_erreur(
                            "ORing — Parametre non mis a jour",
                            f"Impossible de modifier '{nom_param}' :\n{msg}\n\n"
                            "L'insertion continue avec le diametre actuel."
                        )

            # ── 0b. Mise à jour paramètre pièce complémentaire (mode modif) ──
            if self._part_en_modification is not None:
                if (hasattr(self, 'spin_d_comp_modif')
                        and self.spin_d_comp_modif.isVisible()):
                    d_comp_nouveau = self.spin_d_comp_modif.value()
                    if abs(d_comp_nouveau - self._d_comp_ref_modif) > 1e-4:
                        from .metadata import lire_metadonnees
                        _meta_c          = lire_metadonnees(self._part_en_modification)
                        _body_comp_name  = _meta_c.get('body_comp_name', '')
                        _body_comp_label = _meta_c.get('body_comp_label', '')
                        _param_comp      = _get_param_comp() or _meta_c.get('param_comp', '')
                        _est_rayon_comp  = _get_param_comp_rayon()
                        # Chercher par Name (stable) puis par Label
                        _body_comp = (
                            self._doc.getObject(_body_comp_name)
                            if _body_comp_name else None
                        )
                        if _body_comp is None:
                            _body_comp = next(
                                (o for o in self._doc.Objects
                                 if getattr(o, 'TypeId', '') == 'PartDesign::Body'
                                 and o.Label == _body_comp_label),
                                None
                            )
                        if _body_comp and _param_comp:
                            _val_comp = (d_comp_nouveau / 2.0
                                         if _est_rayon_comp else d_comp_nouveau)
                            _ok, _msg = _mettre_a_jour_parametre(
                                _body_comp, _param_comp, _val_comp
                            )
                            if _ok:
                                print(
                                    f"[ORing] Paramètre comp '{_param_comp}' "
                                    f"mis à jour : {_val_comp:.4f} mm "
                                    f"({'rayon' if _est_rayon_comp else 'diametre'})"
                                )
                                # Même logique : recompute pour stabiliser
                                # avant les setDatum du sketch de gorge.
                                self._doc.recompute()
                            else:
                                message_erreur(
                                    "ORing — Paramètre comp non mis à jour",
                                    f"Impossible de modifier '{_param_comp}' "
                                    f"sur le body '{_body_comp_label}' :\n{_msg}\n\n"
                                    "La gorge est recalculée avec le nouveau diamètre\n"
                                    "mais le body complémentaire n'a pas été modifié."
                                )
                        else:
                            print(
                                f"[ORing] Avertissement : body comp "
                                f"'{_body_comp_label}' ou param '{_param_comp}' "
                                f"introuvable — paramètre comp non mis à jour."
                            )

            # ── 1-5. Géométrie : création ou mise à jour selon le mode ──────
            import re as _re
            _lcs_tag = _re.sub(r'[^A-Za-z0-9]', '_', lcs.Label if lcs else 'G')

            sketch     = None
            body_oring = None

            if self._part_en_modification is not None:
                # ── Mode modification : mettre à jour les géométries existantes ─
                # Forcer un recalcul avec les valeurs UI courantes pour être certain
                # que self._resultat reflète le diamètre affiché (et non l'ancien).
                self._on_calculer()
                if not self._resultat or not self._resultat.valide:
                    message_erreur("ORing — Recalcul",
                        "Le recalcul avec le nouveau diamètre a échoué ou produit\n"
                        "un résultat invalide. Vérifier les paramètres.\n\n"
                        + ('\n'.join(self._resultat.alertes) if self._resultat else '')
                    )
                    return
                from .metadata import lire_metadonnees
                meta_existante = lire_metadonnees(self._part_en_modification)
                # Capturer AVANT ecrire_metadonnees (qui écrasera avec la nouvelle valeur)
                self._d_gorge_ref_avant_modif = float(
                    meta_existante.get('d_gorge_ref_mm', d_princ)
                )
                _mettre_a_jour_geometries_existantes(
                    doc            = self._doc,
                    r              = self._resultat,
                    position       = position,
                    d_comp_mm      = d_compl,
                    meta_existante = meta_existante,
                    part           = self._part_en_modification,
                )
                # Récupérer les références existantes pour les métadonnées
                sketch_nom     = meta_existante.get('sketch_gorge_name', '')
                sketch         = self._doc.getObject(sketch_nom) if sketch_nom else None
                body_oring_nom = meta_existante.get('body_oring_name', '')
                body_oring     = self._doc.getObject(body_oring_nom) if body_oring_nom else None

            else:
                # ── Mode création : générer sketch + groove + oring ────────────
                if position == 'arbre':
                    sketch = generer_sketch_gorge_arbre(
                        doc            = self._doc,
                        body           = body,
                        resultat       = self._resultat,
                        lcs            = lcs,
                        plan           = plan,
                        r_alesage_reel = r_compl,
                        nom_sketch     = f'GorgeArbre_{_lcs_tag}',
                        suffixe        = '',
                    )
                else:
                    sketch = generer_sketch_gorge_alesage(
                        doc          = self._doc,
                        body         = body,
                        resultat     = self._resultat,
                        lcs          = lcs,
                        plan         = plan,
                        r_arbre_reel = r_compl,
                        nom_sketch   = f'GorgeAlesage_{_lcs_tag}',
                        suffixe      = '',
                    )
                if sketch:
                    _appliquer_rainure_et_symetrie(
                        doc      = self._doc,
                        body     = body,
                        sketch   = sketch,
                        lcs      = lcs,
                        position = position,
                    )
                # Créer le Part ORing vide AVANT le body_oring, pour pouvoir
                # passer part_oring à generer_oring_3d et éviter que FreeCAD
                # place le body dans le mauvais conteneur actif.
                _lcs_label_creation = lcs.Label if lcs else ''
                _nom_part_creation  = nom_part(position, _lcs_label_creation)
                _part_cree_avant = self._doc.addObject(
                    'App::Part', _nom_part_creation)
                _part_cree_avant.Label = _nom_part_creation

                body_oring = None
                try:
                    body_oring = generer_oring_3d(
                        doc        = self._doc,
                        resultat   = self._resultat,
                        lcs        = lcs,
                        position   = position,
                        part_oring = _part_cree_avant,
                    )
                    # Le snapshot sera mis à jour par _on_recalibrer_couleurs
                    # appelé en fin de _on_appliquer.
                except Exception as e_oring:
                    print(f"[ORing 3D] Avertissement : corps joint non créé : {e_oring}")

                # Masquer les sketches uniquement à la création
                _masquer_sketches(self._doc, body, body_oring)

            # ── 6. App::Part conteneur + métadonnées ──────────────────────────
            try:
                r = self._resultat
                lcs_label = lcs.Label if lcs else ''
                meta = {
                    # Contexte
                    'position':          position,
                    'type_montage':      self.combo_montage.currentData() or '',
                    'pression_bar':      float(self.spin_pression.value()),
                    'temperature_C':     float(self.spin_temperature.value()),
                    'fluide':            self.edit_fluide.text().strip(),
                    'plan_esquisse':     self.combo_plan.currentData() or 'XZ',
                    # Matériau
                    'materiau':          self.combo_materiau.currentData() or '',
                    # Joint / Gorge
                    'standard':          self.combo_standard.currentData() or '',
                    'serie':             (str(r.serie) if r.serie else (self.combo_serie.currentData() or '')),
                    'serie_auto':        (self.combo_serie.currentData() or '') == '',
                    'd2_mm':             float(r.d2) if r.d2 else 0.0,
                    'squeeze_cible_pct': float(self.spin_squeeze.value()),
                    # Pièces FreeCAD
                    'body_gorge_label':  body.Label,
                    'body_gorge_name':   body.Name,
                    'body_comp_label':   (self.widget_piece_complementaire.get_body().Label
                                          if hasattr(self, 'widget_piece_complementaire')
                                          and self.widget_piece_complementaire.get_body()
                                          else ''),
                    'body_comp_name':    (self.widget_piece_complementaire.get_body().Name
                                          if hasattr(self, 'widget_piece_complementaire')
                                          and self.widget_piece_complementaire.get_body()
                                          else ''),
                    'param_gorge':       _get_param_gorge(),
                    'param_comp':        _get_param_comp(),
                    'param_gorge_rayon': ('rayon' if _get_param_gorge_rayon() else 'diametre'),
                    'param_comp_rayon':  ('rayon' if _get_param_comp_rayon()
                                          else 'diametre'),
                    'd_comp_ref_mm':     float(d_compl),
                    'd_gorge_ref_mm':    float(d_princ),   # diamètre de la pièce portant la gorge
                    'jeu_radial_mm':     float(jeu),
                    'lcs_label':         lcs_label,
                    'lcs_name':          lcs.Name if lcs else '',
                    # Grades IT (tolérances désactivées temporairement)
                    'it_grade_alesage':  8,
                    'it_grade_gorge':    8,
                    # Ajustement ISO 286-1
                    'mode_jeu':          (self.combo_mode_jeu.currentData()
                                          if hasattr(self, 'combo_mode_jeu') else 'manuel'),
                    'lettre_ajustement': (self.combo_mode_jeu.currentData()
                                          if hasattr(self, 'combo_mode_jeu')
                                          and self.combo_mode_jeu.currentData() in ('f','g')
                                          else ''),
                    'grade_arbre':       (int(self.combo_grade_arbre.currentData())
                                          if hasattr(self, 'combo_grade_arbre') else 7),
                    # Résultats
                    'd1_mm':             float(r.d1) if r.d1 else 0.0,
                    'h_mm':              float(r.h)  if r.h  else 0.0,
                    'b_mm':              float(r.b)  if r.b  else 0.0,
                    'squeeze_reel_pct':  float(r.squeeze_pct) if r.squeeze_pct else 0.0,
                    'fill_pct':          float(r.fill_pct)    if r.fill_pct    else 0.0,
                    'rayon_gorge_mm':    float(r.rayon_gorge) if r.rayon_gorge else 0.0,
                    # Références géométriques pour la modification ultérieure
                    # En mode modif : on conserve les noms existants
                    'sketch_gorge_name': (meta_existante.get('sketch_gorge_name', '')
                                          if self._part_en_modification is not None
                                          else (sketch.Name if sketch else '')),
                    'body_oring_name':   (meta_existante.get('body_oring_name', '')
                                          if self._part_en_modification is not None
                                          else (body_oring.Name if body_oring else '')),
                }
                if self._part_en_modification is not None:
                    # ── Mode modification : mettre à jour les métadonnées ──
                    # Conserver l'UUID immuable de l'assemblage existant
                    uuid_existant = getattr(self._part_en_modification,
                                            'uuid_joint', '')
                    if uuid_existant:
                        meta['uuid_joint'] = uuid_existant
                    from .metadata import ecrire_metadonnees
                    ecrire_metadonnees(self._part_en_modification, meta)
                    print(f"[ORing meta] Part '{self._part_en_modification.Label}' "
                          f"mis à jour — uuid={uuid_existant or '(ancien schéma)'}")
                    # Migration automatique : s'assurer que le Part est dans
                    # le conteneur du body gorge (cas joints anciens schéma)
                    try:
                        from .metadata import rattacher_joint_au_conteneur
                        rattacher_joint_au_conteneur(
                            self._doc,
                            self._part_en_modification,
                            body, position)
                    except Exception as _e_c:
                        print(f"[ORing conteneur] modification : {_e_c}")
                else:
                    # ── Mode création : le Part vide _part_cree_avant existe déjà
                    # (créé avant generer_oring_3d pour garantir le bon conteneur).
                    # On écrit juste les métadonnées dessus et on rattache au conteneur.
                    from .metadata import ecrire_metadonnees, rattacher_joint_au_conteneur
                    meta_finale = dict(meta)
                    if not meta_finale.get('uuid_joint'):
                        from .metadata import generer_uuid_joint
                        meta_finale['uuid_joint'] = generer_uuid_joint()
                    ecrire_metadonnees(_part_cree_avant, meta_finale)
                    print(f"[ORing meta] Part '{_part_cree_avant.Label}' "
                          f"finalisé — uuid={meta_finale['uuid_joint']}")
                    # Rattacher le Part ORing au conteneur du body gorge
                    try:
                        rattacher_joint_au_conteneur(
                            self._doc, _part_cree_avant, body, position)
                    except Exception as _e_c:
                        print(f"[ORing conteneur] création : {_e_c}")

            except Exception as e_meta:
                # Non bloquant : les métadonnées sont optionnelles
                print(f"[ORing meta] AVERT : opération metadata échouée : {e_meta}")

            # ── Message de succès ────────────────────────────────────────
            if self._part_en_modification is not None:
                msg_titre = "ORing — Modification appliquée"
                msg_corps = (
                    f"Gorge et joint 3D mis à jour avec succès.\n\n"
                    f"  Standard / Série  : {self.combo_standard.currentData()} "
                    f"/ {self.combo_serie.currentData() or 'Auto'}\n"
                    f"  d2 = {float(self._resultat.d2):.2f} mm  "
                    f"h = {float(self._resultat.h):.3f} mm  "
                    f"b = {float(self._resultat.b):.3f} mm\n"
                    f"  Squeeze réel : {float(self._resultat.squeeze_pct):.1f} %  "
                    f"Fill : {float(self._resultat.fill_pct):.1f} %\n\n"
                    f"  D pièce principale     : {d_princ:.3f} mm\n"
                    f"  D pièce complémentaire : {d_compl:.3f} mm\n"
                    f"  Jeu radial             : {jeu:.3f} mm"
                )
                self._annuler_mode_modification()   # reset titre + bouton
                # _d_gorge_ref_avant_modif capturé depuis meta_existante
                # AVANT ecrire_metadonnees — valeur fiable de l'ancien diamètre.
                _d_gorge_avant = getattr(self, '_d_gorge_ref_avant_modif',
                                         d_princ)   # fallback = pas de changement
                self._d_gorge_ref_avant_modif = d_princ   # reset
                _diametre_change = abs(d_princ - _d_gorge_avant) > 1e-6
                _body_label_pour_lies = body.Label if _diametre_change else None
                if _diametre_change:
                    print(f"[ORing lies] diamètre changé : {_d_gorge_avant:.4f} → {d_princ:.4f} mm")
                else:
                    print(f"[ORing lies] diamètre inchangé ({d_princ:.4f} mm) "
                          f"→ joints liés non recalculés")
            else:
                _body_label_pour_lies = None
                msg_titre = "ORing"
                msg_corps = (
                    f"Gorge generee avec succes !\n\n"
                    f"D piece principale     : {d_princ:.3f} mm\n"
                    f"D piece complementaire : {d_compl:.3f} mm\n"
                    f"Jeu radial             : {jeu:.3f} mm"
                )

            # FIX #8 : mémoriser le choix diam/rayon pour les prochaines insertions
            try:
                if hasattr(self, 'widget_piece_principale'):
                    self._dernier_radio_rayon = (
                        self.widget_piece_principale.radio_rayon.isChecked()
                    )
            except Exception:
                pass

            # ── Couleur matériau (synchrone — visible avant le message) ──────
            self._on_recalibrer_couleurs()

            # ── Afficher le message IMMÉDIATEMENT ────────────────────────────
            # Les tâches lourdes (_maj_joints_lies, _onglet_initial) sont
            # différées via QTimer pour ne pas bloquer l'affichage.
            message_info(msg_titre, msg_corps)

            # ── Tâches post-confirmation (différées) ──────────────────────
            def _post_confirmation():
                if _body_label_pour_lies is None:
                    self._onglet_initial()
                    return

                # Afficher la boîte "Veuillez patienter"
                # Le travail lourd est lancé via un 2e QTimer (singleShot 50ms)
                # pour garantir que Qt a rendu le dialogue avant de bloquer le thread.
                _dlg_attente = None
                try:
                    _dlg_attente = QtWidgets.QMessageBox(self)
                    _dlg_attente.setWindowTitle("ORing — Mise à jour en cours")
                    _dlg_attente.setText(
                        "Mise à jour des joints liés en cours…\n"
                        "Veuillez patienter."
                    )
                    _dlg_attente.setStandardButtons(QtWidgets.QMessageBox.NoButton)
                    _dlg_attente.setModal(True)
                    _dlg_attente.show()
                except Exception:
                    _dlg_attente = None

                def _travail_lourd():
                    try:
                        self._maj_joints_lies(_body_label_pour_lies)
                    except Exception as _e_lies:
                        print(f"[ORing] AVERT _maj_joints_lies : {_e_lies}")

                    if _dlg_attente is not None:
                        try:
                            _dlg_attente.done(0)
                        except Exception:
                            pass

                    try:
                        self._on_recalibrer_couleurs()
                    except Exception:
                        pass

                    from .metadata import verifier_derives as _vd
                    try:
                        _derives = _vd(self._doc) if self._doc else None
                    except Exception:
                        _derives = None
                    self._onglet_initial(derives_precalcules=_derives)

                # 50 ms laisse le temps à Qt de rendre le dialogue
                QtCore.QTimer.singleShot(50, _travail_lourd)

            QtCore.QTimer.singleShot(0, _post_confirmation)

        except Exception:
            import traceback
            message_erreur("ORing — Erreur generation", traceback.format_exc())

    def closeEvent(self, event):
        """Restaure exactement l'état visuel d'origine avant fermeture."""
        _restaurer_snapshot(self._doc)
        if hasattr(self, 'table_joints'):
            self.table_joints._locked_row = -1
            self.table_joints._hover_row  = -1
        super().closeEvent(event)

    def reject(self):
        """Fermeture par Échap ou bouton Fermer."""
        _restaurer_snapshot(self._doc)
        super().reject()

    def get_resultat(self):
        return self._resultat


# =============================================================================
# MODIFICATION : MISE A JOUR DES GEOMETRIES EXISTANTES (Option D)
# =============================================================================

def _set_contrainte(sketch, prefixe: str, valeur, en_degres: bool = False) -> bool:
    """
    Trouve dans sketch la première contrainte dont le nom commence par `prefixe`
    et met à jour sa valeur par INDEX (pas par nom).

    Retourne True si trouvée et mise à jour, False sinon.
    """
    try:
        import FreeCAD as _FC
        for idx, c in enumerate(sketch.Constraints):
            if c.Name.startswith(prefixe):
                ancien = c.Value
                if en_degres:
                    sketch.setDatum(idx, _FC.Units.Quantity(f'{valeur} deg'))
                else:
                    sketch.setDatum(idx, _FC.Units.Quantity(f'{valeur} mm'))
                # Vérifier que la valeur a bien été acceptée par le solveur
                nouveau = sketch.Constraints[idx].Value
                import math
                val_rad = math.radians(valeur) if en_degres else valeur
                accepte = abs(nouveau - val_rad) < 1e-4
                print(f"[ORing setDatum] '{c.Name}' : {ancien:.4f} → {val_rad:.4f}"
                      f"  résultat={nouveau:.4f}  {'✓' if accepte else '✗ REJETÉ'}")
                return True
        # Contrainte non trouvée — afficher les noms pour diagnostic
        noms = [c.Name for c in sketch.Constraints]
        print(f"[ORing modif] contrainte '{prefixe}' absente dans {sketch.Name}. "
              f"Contraintes : {noms}")
    except Exception as e:
        print(f"[ORing modif] setDatum '{prefixe}' EXCEPTION : {e}")
    return False


def _maj_tore_inplace(doc, body_oring, r, position: str) -> bool:
    """
    Met à jour les contraintes du sketch du tore ORing in-place.
    Évite la suppression + recréation (6 recompute → 1 recompute sélectif).

    Les 3 contraintes du sketch oblong sont :
      'LargeurOblong'   = L (distance entre centres des arcs)
      'RayonOblong'     = r_ob (rayon des demi-cercles)
      'RayonIntOblong'  = r_min (rayon intérieur = fond de gorge ou arbre)

    Retourne True si la mise à jour a réussi, False en cas d'échec
    (la mise à jour in-place échoue si la géométrie ne converge pas).
    """
    import math as _m
    try:
        from .oring_3d import calculer_dims_oblongues
    except Exception:
        return False

    try:
        # ── Recalculer les dimensions ────────────────────────────────────
        r_gorge   = round(float(getattr(r, 'rayon_gorge', 0.0)), 6)
        if position == 'arbre':
            r_contact = round(float(getattr(r, 'rayon_arbre',
                               getattr(r, 'd_alesage', 0.0) / 2.0)), 6)
        else:
            r_contact = round(float(getattr(r, 'd_alesage', 0.0) / 2.0), 6)

        r_min = round(min(r_gorge, r_contact), 6)
        r_max = round(max(r_gorge, r_contact), 6)
        h_ob  = round(r_max - r_min, 6)

        dims  = calculer_dims_oblongues(float(r.d2), r_gorge, r_contact, position)
        if not dims.get('valide', False):
            print("[ORing tore inplace] dimensions invalides — fallback suppression/recréation")
            return False

        r_ob = dims['r_ob']
        L    = dims['L_droite']

        # ── Trouver le sketch dans le body ───────────────────────────────
        sketch_tore = None
        for feat in getattr(body_oring, 'Group', []):
            if feat.TypeId == 'Sketcher::SketchObject':
                sketch_tore = feat
                break
        if sketch_tore is None:
            print("[ORing tore inplace] sketch introuvable — fallback")
            return False

        # ── Mettre à jour les 3 contraintes ─────────────────────────────
        ok_L    = _set_contrainte(sketch_tore, 'LargeurOblong',  L)
        ok_r_ob = _set_contrainte(sketch_tore, 'RayonOblong',    r_ob)
        ok_rmin = _set_contrainte(sketch_tore, 'RayonIntOblong', r_min)

        if not (ok_L and ok_r_ob and ok_rmin):
            print("[ORing tore inplace] contrainte(s) manquante(s) — fallback")
            return False

        # ── Solve + recompute sélectif ───────────────────────────────────
        sketch_tore.solve()
        sketch_tore.touch()
        rev = getattr(body_oring, 'Tip', None)
        if rev is not None:
            rev.touch()
        body_oring.touch()
        doc.recompute([body_oring])

        # Vérifier que le solveur a accepté
        if getattr(sketch_tore, 'MalformedConstraints', None):
            if len(sketch_tore.MalformedConstraints) > 0:
                print("[ORing tore inplace] MalformedConstraints — fallback")
                return False

        print(f"[ORing tore inplace] ✓ r_ob={r_ob:.4f} L={L:.4f} r_min={r_min:.4f}")
        return True

    except Exception as _e:
        print(f"[ORing tore inplace] EXCEPTION : {_e} — fallback")
        return False


def _mettre_a_jour_geometries_existantes(doc, r, position: str,
                                          d_comp_mm: float,
                                          meta_existante: dict,
                                          depouille_deg: float = 2.0,
                                          part=None):
    """
    Met à jour in-place les contraintes du sketch de gorge et du sketch du
    tore 3D à partir d'un nouveau ResultatCalcul `r`.

    Paramètres
    ----------
    doc           : document FreeCAD actif
    r             : ResultatCalcul avec les nouvelles dimensions
    position      : 'arbre' ou 'alesage'
    d_comp_mm     : diamètre de la pièce complémentaire (référence, non modifié)
    meta_existante: dict lu depuis lire_metadonnees() du Part ORing existant
    depouille_deg : angle de dépouille en degrés (inchangé en mode modif)
    part          : App::Part ORing contenant le body_oring (fallback fiable)
    """
    import math

    def fillet_haut(d2): return round(max(0.05, min(0.40, 0.06 * d2)), 3)
    def fillet_fond(d2): return round(max(0.05, min(0.25, 0.04 * d2)), 3)

    d2     = float(r.d2)
    b2     = round(float(r.b) / 2.0, 4)
    f_haut = fillet_haut(d2)
    f_fond = fillet_fond(d2)

    # ── Sketch de gorge ─────────────────────────────────────────────────────
    nom_sketch_gorge = meta_existante.get('sketch_gorge_name', '')
    sketch_gorge = doc.getObject(nom_sketch_gorge) if nom_sketch_gorge else None

    if sketch_gorge is None:
        # Fallback : discriminer par AttachmentSupport (LCS) + body d'appartenance
        # Deux joints sur le même body partagent le même préfixe de label —
        # seul le LCS d'attachement les distingue de façon fiable.
        body_gorge_label = meta_existante.get('body_gorge_label', '')
        body_gorge_name2 = meta_existante.get('body_gorge_name', '')
        lcs_label_fb     = meta_existante.get('lcs_label', '')
        lcs_name_fb      = meta_existante.get('lcs_name', '')
        prefixe_sketch   = 'GorgeArbre_' if position == 'arbre' else 'GorgeAlesage_'

        for obj in doc.Objects:
            if obj.TypeId != 'Sketcher::SketchObject':
                continue
            if not obj.Label.startswith(prefixe_sketch):
                continue
            # Critère 1 : AttachmentSupport contient le LCS — cherche par Name d'abord
            try:
                supports = obj.AttachmentSupport   # liste de (obj, sub)
                lcs_match = any(
                    (lcs_name_fb and getattr(s[0], 'Name', '') == lcs_name_fb)
                    or (not lcs_name_fb and getattr(s[0], 'Label', '') == lcs_label_fb)
                    for s in (supports or [])
                )
            except Exception:
                lcs_match = False
            if not lcs_match:
                continue
            # Critère 2 : le sketch est dans le body dont le Label == body_gorge_label
            in_body = any(
                candidate.TypeId == 'PartDesign::Body'
                and candidate.Label == body_gorge_label
                and obj in getattr(candidate, 'Group', [])
                for candidate in doc.Objects
            )
            if in_body:
                sketch_gorge = obj
                print(f"[ORing modif] Sketch gorge retrouvé (LCS='{lcs_label_fb}') : "
                      f"'{obj.Name}'")
                break

    if sketch_gorge is None:
        print(f"[ORing modif] AVERT : sketch gorge introuvable "
              f"(name='{nom_sketch_gorge}', "
              f"body='{meta_existante.get('body_gorge_label','?')}')")
    else:
        # ── Calcul des valeurs cibles ────────────────────────────────────────
        r_comp = d_comp_mm / 2.0
        if position == 'arbre':
            r_arbre   = round(float(r.d_arbre)  / 2.0, 4)
            r_gorge   = round(float(r.rayon_gorge), 4)   # déjà arrondi à 0.05 mm dans calcul.py
            r_alesage = round(r_comp, 4)
        else:
            r_alesage = round(float(r.d_alesage) / 2.0, 4)
            r_gorge   = round(float(r.rayon_gorge), 4)   # déjà arrondi à 0.05 mm dans calcul.py
            r_arbre   = round(r_comp, 4)

        print(f"[ORing modif GORGE] sketch='{sketch_gorge.Name}'  position={position}")
        print(f"[ORing modif GORGE]   → r_arbre={r_arbre}  r_gorge={r_gorge}  r_alesage={r_alesage}")
        # Log des contraintes existantes pour diagnostic
        for _dc in sketch_gorge.Constraints:
            if _dc.Name.startswith(('Rayon', 'demiLargeur', 'Fillet', 'depouille')):
                print(f"[ORing modif GORGE]   avant: '{_dc.Name}' = {_dc.Value:.4f}")

        # ── Recherche du Body et des features PartDesign liés au sketch ──────
        body_gorge_obj = None
        features_liees = []
        for obj in doc.Objects:
            tipo = getattr(obj, 'TypeId', '')
            if tipo == 'PartDesign::Groove':
                # Profile peut être un objet direct ou un tuple (obj, sub_list)
                profil = getattr(obj, 'Profile', None)
                if profil is not None:
                    sk_ref = profil[0] if isinstance(profil, (list, tuple)) else profil
                    if getattr(sk_ref, 'Name', '') == sketch_gorge.Name:
                        features_liees.append(obj)
            elif tipo == 'PartDesign::Mirrored':
                # Mirrored.Originals contient le(s) Groove source, pas le sketch
                # → on l'ajoute si un de ses originaux est déjà dans features_liees,
                # ou on le retrouve via le sketch du Groove original.
                # Recherche différée : on les ajoutera après la boucle.
                pass
            if tipo == 'PartDesign::Body':
                if sketch_gorge in getattr(obj, 'Group', []):
                    body_gorge_obj = obj

        # Ajouter les Mirrored dont le Groove source est lié à notre sketch
        groove_names = {f.Name for f in features_liees}
        for obj in doc.Objects:
            if getattr(obj, 'TypeId', '') == 'PartDesign::Mirrored':
                for orig in (getattr(obj, 'Originals', None) or []):
                    if getattr(orig, 'Name', '') in groove_names:
                        features_liees.append(obj)
                        break

        # Fallback : si features_liees toujours vide, chercher tout Groove/Mirrored
        # appartenant au même body (cas où Profile est stocké différemment).
        if not features_liees and body_gorge_obj is not None:
            for obj in doc.Objects:
                tipo = getattr(obj, 'TypeId', '')
                if tipo in ('PartDesign::Groove', 'PartDesign::Mirrored'):
                    if obj in getattr(body_gorge_obj, 'Group', []):
                        features_liees.append(obj)
            if features_liees:
                print(f"[ORing modif] features_liees via fallback body : "
                      f"{[f.Name for f in features_liees]}")
            else:
                print(f"[ORing modif] AVERT features_liees vide pour '{sketch_gorge.Name}' "
                      f"— recompute via body uniquement")

        def _set_contraintes_neutres():
            """Contraintes non-radiales (largeur, filets, dépouille) : sans dépendance
            d'ordre entre elles, toujours appliquées en premier.
            Note : 'demiLargeur' est présent uniquement dans le sketch arbre.
                   'demiLargeurGorge' existe dans les deux sketches.
                   On ne cherche 'demiLargeur' qu'en excluant le préfixe plus long."""
            # Chercher la contrainte 'demiLargeur' seule (pas demiLargeurGorge)
            # en vérifiant startswith + que ce n'est pas demiLargeurGorge
            for _idx, _c in enumerate(sketch_gorge.Constraints):
                if _c.Name.startswith('demiLargeur') and not _c.Name.startswith('demiLargeurG'):
                    try:
                        import FreeCAD as _FC
                        sketch_gorge.setDatum(_idx, _FC.Units.Quantity(f'{round(b2 * 0.5, 4)} mm'))
                    except Exception as _e:
                        print(f"[ORing modif] setDatum 'demiLargeur' EXCEPTION : {_e}")
                    break
            _set_contrainte(sketch_gorge, 'demiLargeurGorge', b2)
            _set_contrainte(sketch_gorge, 'FilletHautGorge',  f_haut)
            _set_contrainte(sketch_gorge, 'FilletFondGorge',  f_fond)
            _set_contrainte(sketch_gorge, 'depouille',        depouille_deg, en_degres=True)

        def _lire_rayon_courant(nom):
            """Lit la valeur courante d'une contrainte dont le nom commence par `nom`."""
            for _c in sketch_gorge.Constraints:
                if _c.Name.startswith(nom):
                    return _c.Value
            return 0.0

        def _recompute_intermediaire():
            """Solve + recompute intermédiaire : valide l'état courant du sketch
            et permet au solveur d'accepter la prochaine contrainte sans conflit.
            Après doc.recompute(), la référence Python au sketch est rafraîchie :
            FreeCAD peut re-indexer les contraintes en interne, et setDatum(idx)
            échouerait avec l'ancienne référence périmée.
            """
            nonlocal sketch_gorge
            _nom_sketch = sketch_gorge.Name
            sketch_gorge.solve()
            sketch_gorge.touch()
            if features_liees:
                for _f in features_liees:
                    _f.touch()
            elif body_gorge_obj is not None:
                # Aucune feature trouvée par Profile → toucher tout le body
                for _obj in getattr(body_gorge_obj, 'Group', []):
                    try:
                        _obj.touch()
                    except Exception:
                        pass
            if body_gorge_obj is not None:
                body_gorge_obj.touch()
            # Recompute global : le sketch gorge est intégré dans un body
            # avec Groove+Mirrored qui doivent aussi se propager.
            # Un recompute sélectif ne propage pas aux features en aval.
            doc.recompute()
            # Rafraîchir la référence : après recompute, l'ancien objet Python
            # peut avoir des indices de contraintes désynchronisés du solveur C++.
            _sk_fresh = doc.getObject(_nom_sketch)
            if _sk_fresh is not None:
                sketch_gorge = _sk_fresh

        # ── Lecture des valeurs courantes ─────────────────────────────────────
        r_arbre_old   = _lire_rayon_courant('RayonArbre')
        r_gorge_old   = _lire_rayon_courant('RayonGorge')
        r_alesage_old = _lire_rayon_courant('RayonAlesage')
        print(f"[ORing modif GORGE]   avant : r_arbre={r_arbre_old:.4f}  "
              f"r_gorge={r_gorge_old:.4f}  r_alesage={r_alesage_old:.4f}")

        # ── Détection état incohérent ─────────────────────────────────────────
        # Si les valeurs lues sont trop éloignées des cibles (> 50%), le sketch
        # est dans un état corrompu (recompute sélectif incomplet, etc.).
        # On force alors les 3 contraintes à leurs valeurs cibles et un
        # recompute intermédiaire AVANT d'entrer dans la logique d'ordre.
        _incoherent = False
        for _old, _new in [(r_arbre_old, r_arbre),
                           (r_gorge_old, r_gorge),
                           (r_alesage_old, r_alesage)]:
            if _old and _old > 1e-6 and abs(_new - _old) / _old > 0.50:
                _incoherent = True
                break
        if _incoherent:
            print("[ORing modif GORGE] état incohérent détecté (écart > 50%) "
                  "→ reset forcé puis logique pas-à-pas")
            # Appliquer directement les cibles sans ordre — le solveur ne peut
            # pas être plus incohérent qu'il ne l'est déjà.
            _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
            _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
            _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
            _recompute_intermediaire()
            # Relire les valeurs après le reset
            r_arbre_old   = _lire_rayon_courant('RayonArbre')
            r_gorge_old   = _lire_rayon_courant('RayonGorge')
            r_alesage_old = _lire_rayon_courant('RayonAlesage')

        # ── Contraintes neutres (ordre indifférent) ───────────────────────────
        _set_contraintes_neutres()
        sketch_gorge.solve()
        # Après un reset incoherent, les neutres peuvent avoir changé (ex. changement
        # de série) : forcer un recompute intermédiaire pour propager avant la séquence
        # radiale. Sans ça, le recompute final doit tout gérer d'un coup et peut échouer.
        if _incoherent:
            _recompute_intermediaire()

        # ── Contraintes radiales : ordre selon le sens de variation ───────────
        #
        # Invariant du solveur 2D FreeCAD :
        #   gorge ARBRE   : RayonGorge < RayonArbre < RayonAlesage
        #   gorge ALÉSAGE : RayonArbre < RayonAlesage < RayonGorge
        #
        # Si on GROSSIT (nouvelle valeur > ancienne) :
        #   ARBRE   → appliquer d'abord les grands rayons (RayonAlesage → RayonArbre → RayonGorge)
        #   ALÉSAGE → appliquer d'abord les grands rayons (RayonGorge → RayonAlesage → RayonArbre)
        #
        # Si on DIMINUE (nouvelle valeur < ancienne) :
        #   ARBRE   → appliquer d'abord les petits rayons (RayonGorge → RayonArbre → RayonAlesage)
        #   ALÉSAGE → appliquer d'abord les petits rayons (RayonArbre → RayonAlesage → RayonGorge)
        #
        # Un recompute intermédiaire après chaque étape valide l'état et évite
        # les conflits transitoires même pour de grandes variations (ex. 40 → 20 mm).

        if position == 'arbre':
            grossit = r_arbre > r_arbre_old
            if grossit:
                # Étape 1 : élargir l'alésage (borne extérieure)
                _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                _recompute_intermediaire()
                # Étape 2 : élargir l'arbre
                _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                _recompute_intermediaire()
                # Étape 3 : reculer le fond de gorge
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
            else:
                # Étape 1 : avancer le fond de gorge (borne intérieure)
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                # Étape 2 : réduire l'arbre
                _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                _recompute_intermediaire()
                # Étape 3 : réduire l'alésage
                _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)

        else:  # alésage
            # Invariant : RayonArbre < RayonAlesage < RayonGorge
            grossit = r_alesage > r_alesage_old
            print(f"[ORing modif GORGE] alésage {'grossit' if grossit else 'diminue'} : "
                  f"r_arbre {r_arbre_old:.4f}→{r_arbre:.4f}  "
                  f"r_alesage {r_alesage_old:.4f}→{r_alesage:.4f}  "
                  f"r_gorge {r_gorge_old:.4f}→{r_gorge:.4f}")
            if grossit:
                # Étape 1 : avancer le fond de gorge vers l'extérieur
                print("[ORing modif GORGE] étape 1/3 : RayonGorge")
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                # Étape 2 : élargir l'alésage
                print("[ORing modif GORGE] étape 2/3 : RayonAlesage")
                _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                _recompute_intermediaire()
                # Étape 3 : élargir l'arbre (référence intérieure)
                print("[ORing modif GORGE] étape 3/3 : RayonArbre")
                _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
            else:
                # Étape 1 : réduire l'arbre (borne intérieure)
                print("[ORing modif GORGE] étape 1/3 : RayonArbre")
                _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                _recompute_intermediaire()
                # Étape 2 : réduire l'alésage
                print("[ORing modif GORGE] étape 2/3 : RayonAlesage")
                _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                _recompute_intermediaire()
                # Étape 3 : rapprocher le fond de gorge
                print("[ORing modif GORGE] étape 3/3 : RayonGorge")
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)

        # ── Recompute final ───────────────────────────────────────────────────
        import time as _t
        _t0_recompute = _t.time()
        sketch_gorge.solve()
        sketch_gorge.touch()
        for feat in features_liees:
            feat.touch()
        if body_gorge_obj is not None:
            body_gorge_obj.touch()
        # Recompute global obligatoire : le Groove et le Mirrored
        # doivent se propager depuis le sketch. Un recompute sélectif
        # [body_gorge_obj] ne propage pas aux features en aval.
        doc.recompute()
        print(f"[ORing modif GORGE]   recompute() effectué  "
              f"(sens={'agrandissement' if (grossit if position=='arbre' else grossit) else 'rétrécissement'})  "
              f"durée={_t.time()-_t0_recompute:.2f}s")

        # Mémoriser pour éviter le fallback aux prochaines modifications
        if not nom_sketch_gorge:
            meta_existante['sketch_gorge_name'] = sketch_gorge.Name


    # ── Tore 3D : supprimer l'ancien body et le recréer ────────────────────
    # Les tentatives de mise à jour des contraintes in-place ne propagent pas
    # correctement jusqu'à la Revolution. La solution fiable est la recréation.
    nom_body_oring = meta_existante.get('body_oring_name', '')
    body_oring_old = doc.getObject(nom_body_oring) if nom_body_oring else None

    if body_oring_old is None:
        # Fallback : chercher dans le Group du Part
        if part is not None:
            for child in getattr(part, 'Group', []):
                if (child.TypeId == 'PartDesign::Body'
                        and child.Label.startswith('ORing')):
                    body_oring_old = child
                    print(f"[ORing modif] Body ORing trouvé dans Part.Group : "
                          f"'{child.Name}'")
                    break

    # Conserver le nom et le label pour la recréation
    nom_body_conserve   = body_oring_old.Name  if body_oring_old else 'ORing'
    label_body_conserve = body_oring_old.Label if body_oring_old else 'ORing'
    print(f"[ORing modif] body_oring_old={nom_body_conserve!r}  part={part.Name if part else None}")

    # Récupérer le LCS depuis les métadonnées
    # Priorité : Name (unique dans le doc) > Label (peut être dupliqué entre bodies)
    lcs_name  = meta_existante.get('lcs_name', '')
    lcs_label = meta_existante.get('lcs_label', '')
    lcs = None

    # Tentative 1 : par Name FreeCAD (déterministe)
    if lcs_name:
        lcs = doc.getObject(lcs_name)
        if lcs is not None:
            print(f"[ORing modif] LCS trouvé par Name '{lcs_name}'")

    # Tentative 2 : par Label, mais contraint au body qui porte la gorge
    if lcs is None:
        body_gorge_label = meta_existante.get('body_gorge_label', '')
        from .utils import lister_lcs as _lister_lcs
        for obj in doc.Objects:
            if (obj.TypeId == 'PartDesign::Body'
                    and obj.Label == body_gorge_label):
                for _lcs in _lister_lcs(obj):
                    if _lcs.Label == lcs_label:
                        lcs = _lcs
                        print(f"[ORing modif] LCS trouvé par Label '{lcs_label}' "
                              f"dans body '{body_gorge_label}'")
                        break
            if lcs:
                break

    print(f"[ORing modif] LCS cherché name='{lcs_name}' label='{lcs_label}'  "
          f"trouvé={lcs.Name if lcs else 'AUCUN'}")

    if lcs is None:
        print(f"[ORing modif] AVERT : LCS '{lcs_label}' introuvable — tore non recréé")
        doc.recompute()
        return

    import time as _t
    _t0_tore = _t.time()
    body_oring_new = None

    # ── Fast path : mise à jour in-place du tore (évite suppression/recréation)
    if body_oring_old is not None:
        _inplace_ok = _maj_tore_inplace(doc, body_oring_old, r, position)
        if _inplace_ok:
            body_oring_new = body_oring_old
            meta_existante['body_oring_name'] = body_oring_old.Name
            print(f"[ORing modif] Tore mis à jour in-place : '{body_oring_old.Name}'  "
                  f"total tore : {_t.time()-_t0_tore:.2f}s")

    # ── Fallback : suppression + recréation ────────────────────────────────
    if body_oring_new is None:
        print(f"[ORing modif] Tore : suppression + recréation")
        if body_oring_old is not None:
            noms_a_supprimer = [child.Name
                                for child in getattr(body_oring_old, 'Group', [])]
            noms_a_supprimer.append(body_oring_old.Name)
            print(f"[ORing modif] Suppression : {noms_a_supprimer}")
            if part is not None:
                try:
                    part.removeObject(body_oring_old)
                except Exception:
                    pass
            for nom in noms_a_supprimer:
                try:
                    obj = doc.getObject(nom)
                    if obj is not None:
                        doc.removeObject(nom)
                        print(f"[ORing modif] '{nom}' supprimé")
                except Exception as e:
                    print(f"[ORing modif] '{nom}' : {e}")
            doc.recompute()

        try:
            from .oring_3d import generer_oring_3d
            body_oring_new = generer_oring_3d(
                doc        = doc,
                resultat   = r,
                lcs        = lcs,
                position   = position,
                nom_body   = label_body_conserve,
                part_oring = part,
            )
            print(f"[ORing modif] body_oring_new '{body_oring_new.Name}' "
                  f"créé dans Part '{part.Label if part else 'aucun'}'")
            for feat in getattr(body_oring_new, 'Group', []):
                if feat.TypeId == 'Sketcher::SketchObject':
                    try:
                        feat.ViewObject.Visibility = False
                    except Exception:
                        pass
            meta_existante['body_oring_name'] = body_oring_new.Name
            print(f"[ORing modif] Body ORing recréé : '{body_oring_new.Name}'"
                  f"  total tore : {_t.time()-_t0_tore:.2f}s")
        except Exception as e_rec:
            print(f"[ORing modif] AVERT : recréation body oring échouée : {e_rec}")
            body_oring_new = None

    # Couleur appliquée par _on_appliquer après le dernier recompute du flux.


# =============================================================================
# GENERATION FREECAD : MASQUAGE DES SKETCHES
# =============================================================================

def _masquer_sketches(doc, body_gorge, body_oring=None):
    """
    Masque tous les sketches des bodies gorge et joint torique.

    Utilise feat.ViewObject.Visibility directement (idiome FreeCAD fiable),
    sans passer par Gui.ActiveDocument.getObject() qui peut retourner None.
    """
    bodies = [b for b in (body_gorge, body_oring) if b is not None]
    masques = []
    for body in bodies:
        grp = getattr(body, 'Group', None) or []
        for feat in grp:
            if feat.TypeId == 'Sketcher::SketchObject':
                try:
                    feat.ViewObject.Visibility = False
                    masques.append(feat.Label)
                except Exception as e:
                    print(f"[ORing] masquage '{feat.Label}' impossible : {e}")

    if masques:
        print(f"[ORing] Sketches masqués : {', '.join(masques)}")


# =============================================================================
# GENERATION FREECAD : RAINURE + SYMETRIE
# =============================================================================

def _appliquer_rainure_et_symetrie(doc, body, sketch, lcs, position: str):
    """
    A partir du sketch de demi-gorge (profil de X=-b/2 a X=0) :

    Systeme de coordonnees (MapMode ObjectZX sur LCS) :
      sketch H_Axis (X) → LCS Z = axe de la piece (axial)
      sketch V_Axis (Y) → LCS X = direction radiale
      Revolution autour de H_Axis → revolution autour de LCS Z ✓

    1. PartDesign::Groove  — revolution 360 deg autour de H_Axis (= LCS Z)
       Cree la demi-gorge (profil de Z=-b/2 a Z=0 du LCS)

    2. PartDesign::Plane   — plan median de la gorge = plan XY du LCS (Z=0)
       Cree comme feature datum attache au LCS en mode ObjectXY

    3. PartDesign::Mirrored — symetrie par le plan XY du LCS
       Complete la gorge (ajoute Z=0 a Z=+b/2)
       Resultat : gorge complete centree sur Z=0 du LCS
    """
    import FreeCAD as App

    # ── 1. Groove ─────────────────────────────────────────────────────────────
    groove = body.newObject('PartDesign::Groove', 'GorgeORing')
    groove.Profile       = sketch
    groove.Angle         = 360.0
    groove.ReferenceAxis = (sketch, ['H_Axis'])
    groove.Midplane      = False
    groove.Reversed      = False
    doc.recompute()   # requis avant Mirrored (évalue la forme Groove)

    # ── 2. Plan median ────────────────────────────────────────────────────────
    # Pas de recompute intermédiaire : PlanMedian est attaché au LCS (pas au
    # Groove), FreeCAD peut résoudre sans recompute supplémentaire ici.
    plan_median = body.newObject('PartDesign::Plane', 'PlanMedianGorge')
    plan_median.AttachmentSupport = [(lcs, '')]
    plan_median.MapMode           = 'ObjectXY'
    plan_median.AttachmentOffset  = App.Placement()
    plan_median.Visibility        = False

    # ── 3. Mirrored ───────────────────────────────────────────────────────────
    mirrored = body.newObject('PartDesign::Mirrored', 'GorgeORing_Sym')
    mirrored.Originals   = [groove]
    mirrored.MirrorPlane = (plan_median, [''])

    # Définir Mirrored comme Tip : c'est la dernière opération active.
    body.Tip = mirrored
    doc.recompute()   # recompute final unique (PlanMedian + Mirrored + Tip)


def _trouver_plan_xy(doc, body):
    """Retourne le plan XY_Plane de l'origine du body ou du document."""
    if body and hasattr(body, 'Origin') and body.Origin:
        for feat in body.Origin.OriginFeatures:
            if feat.TypeId == 'App::Plane' and 'XY' in feat.Name.upper():
                return feat
    for obj in doc.Objects:
        if obj.TypeId == 'App::Origin':
            for feat in obj.OriginFeatures:
                if feat.TypeId == 'App::Plane' and 'XY' in feat.Name.upper():
                    return feat
    return None


# =============================================================================
# MISE A JOUR D'UN PARAMETRE DANS UN BODY FREECAD
# =============================================================================

# Préfixes des sketches créés par la macro ORing — exclus de la recherche
# Préfixes des sketches créés par la macro ORing.
# _mettre_a_jour_parametre les exclut pour ne modifier que les sketches
# utilisateur (paramètres pièce), jamais les sketches de gorge/joint.
_ORING_SKETCH_PREFIXES = ('GorgeArbre', 'GorgeAlesage', 'SketchORing')


def mettre_a_jour_parametre(body, nom_parametre: str,
                              valeur_mm: float) -> tuple:
    """
    Met a jour le parametre nomme 'nom_parametre' dans un Body :
    - d'abord les sketches (contraintes nommees), en excluant les sketches ORing
    - ensuite les spreadsheets (alias de cellules)

    Retourne (True, '') si succes, (False, message_erreur) sinon.
    """
    try:
        import FreeCAD as App
        for obj in body.Group:
            # ── Sketches (contraintes nommées) ────────────────────────────
            if obj.TypeId == 'Sketcher::SketchObject':
                # Exclure les sketches de gorge/joint créés par ORing
                if any(obj.Name.startswith(p) for p in _ORING_SKETCH_PREFIXES):
                    continue
                for i, c in enumerate(obj.Constraints):
                    if c.Name == nom_parametre:
                        obj.setDatum(
                            i,
                            App.Units.Quantity(f'{valeur_mm:.6f} mm')
                        )
                        return True, ''
            # ── Spreadsheets (alias de cellules) ─────────────────────────
            elif obj.TypeId == 'Spreadsheet::Sheet':
                try:
                    for cell_addr in obj.getContents():
                        alias = obj.getAlias(cell_addr)
                        if alias == nom_parametre:
                            obj.set(cell_addr, str(valeur_mm))
                            return True, ''
                except Exception:
                    pass
        return False, (
            f"Parametre '{nom_parametre}' introuvable dans les sketches "
            f"du body '{body.Label}'."
        )
    except Exception as e:
        return False, str(e)


# =============================================================================
# FONCTIONS PUBLIQUES POUR L'OBSERVATEUR
# =============================================================================

def appliquer_couleur_apres_recompute(doc, part, meta: dict) -> None:
    """
    Applique la couleur matériau au body ORing d'un Part.
    Appelée par l'observateur après une mise à jour automatique.
    """
    try:
        from .oring_3d import appliquer_couleur_materiau
        from .metadata import lire_metadonnees
        _meta = meta if meta else lire_metadonnees(part)
        nom_body = _meta.get('body_oring_name', '')
        body_col = doc.getObject(nom_body) if nom_body else None
        if body_col is None:
            for child in getattr(part, 'Group', []):
                if (child.TypeId == 'PartDesign::Body'
                        and child.Label.startswith('ORing')):
                    body_col = child
                    break
        if body_col is not None:
            mat = _meta.get('materiau', '')
            appliquer_couleur_materiau(body_col, mat)
    except Exception as e:
        print(f"[ORing couleur] AVERT : {e}")


# Alias pour compatibilité interne
_mettre_a_jour_parametre = mettre_a_jour_parametre


# =============================================================================
# POINT D'ENTREE
# =============================================================================

def lancer_dialogue():
    """
    Point d'entrée de la macro.

    Étape 1b : vérifie qu'au moins un body valide existe avant d'ouvrir
    le dialogue principal. Si aucun body ne satisfait les critères
    (LCS + paramètre nommé), affiche un message d'instruction et se ferme
    sans modifier le document.
    """
    if not FREECAD_DISPONIBLE:
        print("[ORing] FreeCAD non disponible — dialogue non affiche")
        return None

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])

    # ── Étape 1b : validation au démarrage ───────────────────────────────────
    try:
        doc = get_document_actif()
    except RuntimeError:
        # Aucun document ouvert — on laisse DialogueORing gérer ce cas
        doc = None

    if doc is not None and not doc_a_bodies_valides(doc):
        QtWidgets.QMessageBox.information(
            None,
            "ORing — Prérequis non satisfaits",
            _MSG_PREREQUIS
        )
        return None
    # ─────────────────────────────────────────────────────────────────────────

    # Recolorer les joints existants (créés avant l'ajout de la palette couleurs)
    try:
        from .oring_3d   import appliquer_couleur_materiau
        from .metadata   import lister_parts_oring, lire_metadonnees
        for _part in lister_parts_oring(doc):
            _meta = lire_metadonnees(_part)
            _mat  = _meta.get('materiau', '')
            _nom  = _meta.get('body_oring_name', '')
            if _nom:
                _body = doc.getObject(_nom)
                if _body is not None:
                    appliquer_couleur_materiau(_body, _mat)
    except Exception:
        pass

    dlg = DialogueORing(parent=Gui.getMainWindow())
    dlg._onglet_initial()   # bascule sur onglet 3 si dérive détectée
    dlg.exec_()
    return dlg.get_resultat()


# =============================================================================
# TEST AUTONOME (hors FreeCAD)
# =============================================================================
if __name__ == '__main__':
    print("=== Test module dialogue.py (hors FreeCAD) ===\n")
    print(f"FreeCAD disponible : {FREECAD_DISPONIBLE}")

    if not FREECAD_DISPONIBLE:
        print(f"liste_materiaux() : {liste_materiaux()}")
        print(f"STANDARDS         : {STANDARDS}")
        print()
        from .calcul import calculer_gorge, afficher_synthese
        r = calculer_gorge(
            diametre_piece_mm=80.0,
            position='arbre',
            type_montage='statique',
            materiau='NBR',
            pression_bar=50,
            temperature_C=60,
            fluide='huiles_minerales',
            standard='ISO_3601',
        )
        afficher_synthese(r)
    else:
        lancer_dialogue()
