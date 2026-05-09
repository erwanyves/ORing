# Chemin : modules/dialogue.py
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

from .i18n import tr


def _nom_mat(m: dict) -> str:
    """Retourne le nom complet du matériau dans la langue courante.
    Importe le MODULE i18n à chaque appel (pas la fonction) pour garantir
    l'accès à _translations courant, sans dépendance de timing."""
    try:
        from . import i18n as _i18n_mod
        return _i18n_mod.tr(m.get('nom_complet', ''))
    except Exception:
        return m.get('nom_complet', '')

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

_MSG_PREREQUIS = tr(
    "To use this macro, your document must contain:\n\n"
    "  • At least one Body to receive the groove\n"
    "    → This body must have a LCS (for sketch attachment)\n"
    "      and a named parameter defining the diameter or radius.\n\n"
    "  • At least one complementary Body\n"
    "    → This body must have a named parameter defining\n"
    "      the diameter or radius.\n\n"
    "The macro will close.\n"
    "Please prepare your bodies and restart."
)


# =============================================================================
# LIBELLES SELON POSITION
# =============================================================================

def _libelles_position(position: str) -> tuple:
    if position == 'arbre':
        return (
            tr("Groove body = SHAFT  ← sketch generated HERE"),
            tr("Complementary part = BORE  (reference diameter)"),
        )
    else:
        return (
            tr("Groove body = BORE  ← sketch generated HERE"),
            tr("Complementary part = SHAFT  (reference diameter)"),
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
                       tr("Select ISO mode\nto display the diagram"))
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
        layout.addRow(tr("Body:"), self.combo_body)

        self.combo_param = QtWidgets.QComboBox()
        self.combo_param.addItem(tr("— select —"), None)
        layout.addRow(tr("Parameter Ø:"), self.combo_param)

        self.radio_diametre = QtWidgets.QRadioButton(tr("Diameter"))
        self.radio_rayon    = QtWidgets.QRadioButton(tr("Radius"))
        self.radio_diametre.setChecked(True)
        grp = QtWidgets.QButtonGroup(self)
        grp.addButton(self.radio_diametre)
        grp.addButton(self.radio_rayon)
        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.radio_diametre)
        hl.addWidget(self.radio_rayon)
        layout.addRow(tr("The parameter is a:"), hl)

        self.label_valeur = QtWidgets.QLabel("—")
        layout.addRow(tr("Read value:"), self.label_valeur)

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
        self.combo_body.addItem(tr("— select —"), None)
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
        self.combo_param.addItem(tr("— select —"), None)
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

    def _auto_radio_depuis_nom(self, nom: str, forcer: bool = False):
        """
        Suggère la position du radio Diamètre/Rayon selon le préfixe du
        paramètre sélectionné :
          - Nom commençant par R ou r → Rayon
          - Nom commençant par D ou d → Diamètre
          - Autre préfixe → aucun changement

        Le radio reste toujours librement modifiable par l'utilisateur.
        La suggestion n'est appliquée que si :
          - forcer=True (ex. première sélection du combo), ou
          - le radio est dans sa valeur par défaut (Diamètre) et l'utilisateur
            n'a pas encore interagi avec lui.

        Bloque les signaux pour ne pas déclencher de recalcul prématuré.
        """
        if not nom:
            return
        premier = nom[0].lower()
        if premier not in ('r', 'd'):
            return  # Préfixe non reconnu → laisser l'utilisateur choisir

        # Ne suggérer que si le radio est sur sa valeur par défaut (Diamètre)
        # ou si la suggestion est explicitement forcée.
        # Cela préserve tout choix manuel de l'utilisateur.
        if not forcer:
            # Si le radio est déjà sur Rayon (valeur non-défaut), l'utilisateur
            # l'a peut-être positionné intentionnellement → ne pas écraser.
            if self.radio_rayon.isChecked() and premier == 'd':
                return  # L'utilisateur a choisi Rayon manuellement → respecter

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

    def _on_param_change(self, _=None):
        nom  = self.combo_param.currentData()
        body = self.combo_body.currentData()
        if nom and body:
            # Suggérer rayon/diamètre selon le préfixe du nom (#R/D)
            # forcer=True car c'est l'utilisateur qui vient de changer le
            # paramètre — on suggère la valeur la plus probable.
            # L'utilisateur peut corriger librement après.
            self._auto_radio_depuis_nom(nom, forcer=True)
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
        self.setWindowTitle(tr("ORing — O-Ring Groove Sizing"))
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
        tabs.addTab(w1, tr("1 · Context / Material"))

        # — Onglet 2 : Pièces + Joint/Gorge + synthèse résultats ───────
        w2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(w2)
        v2.setSpacing(6)
        v2.addWidget(self._section_pieces())
        v2.addWidget(self._section_joint())
        v2.addWidget(self._section_synthese())   # (A) résultats de gorge
        # (B) Analyse tolérances IT — désactivée temporairement
        v2.addStretch()
        tabs.addTab(w2, tr("2 · Parts / Seal / Results"))

        # — Onglet 3 : Joints existants ────────────────────────────────
        w3 = QtWidgets.QWidget()
        v3 = QtWidgets.QVBoxLayout(w3)
        v3.setSpacing(6)
        v3.addWidget(self._section_joints_existants())   # (B) tableau
        tabs.addTab(w3, tr("3 · Existing seals"))
        # Rafraîchir noms matériaux (tr() garanti actif après event loop)
        QtCore.QTimer.singleShot(50, self._rafraichir_noms_materiaux)

        # Rafraîchir l'onglet 3 à l'activation
        tabs.currentChanged.connect(self._on_tab_change)

        # ── Boutons (hors onglets) ────────────────────────────────────────
        bl = QtWidgets.QHBoxLayout()
        # Bouton aide — texte simple, compatible tous thèmes FreeCAD
        self.btn_aide = QtWidgets.QPushButton(tr("? Help"))
        self.btn_aide.setToolTip(tr("Help — Getting Started Guide"))
        self.btn_aide.clicked.connect(self._ouvrir_aide)
        self.btn_appliquer = QtWidgets.QPushButton(tr("Apply in FreeCAD"))
        self.btn_fermer    = QtWidgets.QPushButton(tr("Close"))
        self.btn_appliquer.setEnabled(False)

        self.btn_appliquer.clicked.connect(self._on_appliquer)
        self.btn_fermer.clicked.connect(self.reject)
        bl.addWidget(self.btn_aide)
        bl.addStretch()
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
        grp = QtWidgets.QGroupBox(tr("Calculation results"))
        grid = QtWidgets.QGridLayout(grp)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 6, 8, 6)

        def _lbl_val():
            """Label valeur : gras, agrandit si nécessaire."""
            lbl = QtWidgets.QLabel("—")
            lbl.setMinimumWidth(240)
            return lbl

        # Tuples (clé_stable_EN, label_traduit, tooltip_traduit)
        # La clé stable EN est utilisée pour _synth_vals → pas de KeyError quelle que soit la langue
        etiquettes = [
            ("Seal",       tr("Seal"),          tr("Selected seal (standard / series / d2)")),
            ("d1",         tr("d1"),             tr("Inner diameter + stretch")),
            ("Groove",     tr("Groove"),         tr("Groove depth h and width b")),
            ("Squeeze",    tr("Squeeze"),        tr("Actual squeeze and fill ratio")),
            ("Ø bottom",   tr("\u00d8 bottom"), tr("Groove bottom diameter")),
            ("Extrusion",  tr("Extrusion"),      tr("Extrusion risk")),
        ]
        self._synth_vals = {}
        for row, (key, label, tip) in enumerate(etiquettes):
            lbl_e = QtWidgets.QLabel(label + " :")
            lbl_e.setStyleSheet("font-size: 9pt;")
            lbl_e.setToolTip(tip)
            lbl_v = _lbl_val()
            grid.addWidget(lbl_e, row, 0)
            grid.addWidget(lbl_v, row, 1)
            self._synth_vals[key] = lbl_v   # clé stable EN

        # Séparateur horizontal
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        grid.addWidget(sep, len(etiquettes), 0, 1, 2)

        # Ligne statut
        self.lbl_synth_statut = QtWidgets.QLabel(tr("Awaiting calculation\u2026"))
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
            self._synth_vals["Seal"].setText(txt_joint)
            self._synth_vals["Seal"].setStyleSheet("")
        else:
            self._synth_vals["Seal"].setText("—")

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
            self._synth_vals["Groove"].setText(
                f"h = {r.h:.3f} mm   b = {r.b:.3f} mm"
            )
            self._synth_vals["Groove"].setStyleSheet("")
        else:
            self._synth_vals["Groove"].setText("—")

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
            self._synth_vals["Ø bottom"].setText(
                f"{r.rayon_gorge * 2:.4f} mm"
            )
        else:
            self._synth_vals["Ø bottom"].setText("—")

        # ── Extrusion ──
        if r.risque_extrusion:
            txt_ext = str(r.risque_extrusion)
            if r.bague_antiextrusion:
                txt_ext += "   " + tr("\u26a0 ANTI-EXTRUSION RING REQUIRED")
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
            self.lbl_synth_statut.setText(tr("\u2713  VALID"))
            self.lbl_synth_statut.setStyleSheet(
                "font-weight: bold; font-size: 10pt; color: #1a7a1a;"
            )
        else:
            self.lbl_synth_statut.setText(tr("\u2717  INVALID \u2014 see alerts"))
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
        grp = QtWidgets.QGroupBox(tr("O-Ring seals in this document"))
        vl  = QtWidgets.QVBoxLayout(grp)
        vl.setSpacing(6)

        # Barre de contrôle
        hl = QtWidgets.QHBoxLayout()
        self.lbl_joints_nb = QtWidgets.QLabel(tr("No seal found."))
        self.lbl_joints_nb.setStyleSheet("font-style: italic;")

        # Filtre position
        self.combo_filtre_position = QtWidgets.QComboBox()
        self.combo_filtre_position.addItem(tr("All"),    "")
        self.combo_filtre_position.addItem(tr("Shaft"),   "arbre")
        self.combo_filtre_position.addItem(tr("Bore"), "alesage")
        self.combo_filtre_position.setFixedWidth(90)
        self.combo_filtre_position.setToolTip(tr("Filter by groove position"))
        self.combo_filtre_position.currentIndexChanged.connect(
            self._on_filtre_position_change
        )

        self.btn_refresh_joints = QtWidgets.QPushButton(tr("↻  Refresh"))
        self.btn_refresh_joints.setFixedWidth(110)
        self.btn_refresh_joints.clicked.connect(self._rafraichir_joints_existants)
        self.btn_recalibrer_couleurs = QtWidgets.QPushButton(tr("🎨  Colors"))
        self.btn_recalibrer_couleurs.setFixedWidth(110)
        self.btn_recalibrer_couleurs.setToolTip(tr(
            "Re-color all seals by material.\n"
            "Useful if colors are incorrect or missing."
        ))
        self.btn_recalibrer_couleurs.clicked.connect(self._on_recalibrer_couleurs)
        self.btn_modifier_joint = QtWidgets.QPushButton(tr("✎  Edit"))
        self.btn_modifier_joint.setFixedWidth(110)
        self.btn_modifier_joint.setEnabled(False)
        self.btn_modifier_joint.setToolTip(tr(
            "Pre-fill the dialog with the selected seal parameters\n"
            "to modify and regenerate the groove.\n"
            "Double-click on a row has the same effect."
        ))
        self.btn_modifier_joint.clicked.connect(self._on_clic_modifier)
        hl.addWidget(self.lbl_joints_nb)
        hl.addStretch()
        hl.addWidget(QtWidgets.QLabel(tr("Position:")))
        hl.addWidget(self.combo_filtre_position)
        hl.addWidget(self.btn_modifier_joint)
        hl.addWidget(self.btn_recalibrer_couleurs)
        hl.addWidget(self.btn_refresh_joints)
        vl.addLayout(hl)

        # Tableau
        COLONNES = [
            "", tr("Position"), tr("LCS"), tr("Groove body"),
            tr("Std / Series"), tr("d2 (mm)"), tr("d1 (mm)"),
            tr("h (mm)"), tr("b (mm)"), tr("Squeeze %"), tr("Fill %"),
            tr("\u0394 drift")
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
            tr("\u26a0 = the complementary part diameter has changed since insertion "
            "\u2014 click Edit to recalculate automatically.")
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
            self.lbl_joints_nb.setText(tr("No active FreeCAD document."))
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
                tr("Refresh error: {err}\n(see FreeCAD console)", err=_e_raf)
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
                    tr("Drift detected: \u0394 {delta:.3f} mm\n"
                    "The complementary part diameter has changed\n"
                    "since insertion. Click Edit to recalculate.",
                    delta=delta)
                )
            else:
                icone_txt = "✓"
                icone_color = QtGui.QColor(20, 140, 20)
                tooltip_icone = tr("Dimensions consistent with metadata.")

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
            self.lbl_joints_nb.setText(tr("No O-Ring seal inserted in this document."))
            if hasattr(self, '_tabs'):
                self._tabs.setTabText(2, tr("3 · Existing seals"))
                try:
                    self._tabs.tabBar().setTabTextColor(2, QtGui.QColor())
                except Exception:
                    pass
        elif nb == 1:
            msg = tr("1 O-Ring seal found.")
            if nb_derives:
                msg += "  " + tr("\u26a0 Drift detected \u2014 click Edit to recalculate.")
            self.lbl_joints_nb.setText(msg)
        else:
            msg = tr("{n} O-Ring seals found.", n=nb)
            if nb_derives:
                msg += "  " + tr("\u26a0 {nd} drift(s) detected \u2014 click Edit to recalculate.", nd=nb_derives)
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
                titre = tr("3 · Existing seals") + f"  \u26a0 {nb_derives}"
                # Colorer l'onglet en orange pour attirer l'attention
                self._tabs.setTabText(2, titre)
                try:
                    bar = self._tabs.tabBar()
                    bar.setTabTextColor(2, QtGui.QColor(200, 80, 0))
                except Exception:
                    pass
            else:
                self._tabs.setTabText(2, tr("3 · Existing seals"))
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
tr("{shown} / {total} seal(s) shown \u2014 filter: {filt}", shown=nb_visibles, total=total, filt=filtre)
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



    # ------------------------------------------------------------------
    # Highlight du joint en cours de modification
    # ------------------------------------------------------------------

    def _debut_highlight(self, part, meta: dict):
        """
        Met en surbrillance le joint ORing en cours de modification.

        Cible le body ORing (le tore 3D visible) plutôt que le Part
        conteneur, pour que la surbrillance soit visuellement évidente
        dans la vue 3D.

        La surbrillance est maintenue jusqu'à l'appel de _fin_highlight().
        """
        self._highlighted_obj_name = ''
        self._highlighted_doc_name = ''

        if not FREECAD_DISPONIBLE or self._doc is None:
            return
        try:
            # Cibler le body ORing (tore 3D) si disponible
            body_name = meta.get('body_oring_name', '')
            target = None
            if body_name:
                target = self._doc.getObject(body_name)
            # Fallback : le Part conteneur
            if target is None:
                target = part

            self._highlighted_obj_name = target.Name
            self._highlighted_doc_name = self._doc.Name

            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self._doc.Name, target.Name)
            print(f"[ORing] Highlight activé : {target.Label}")
        except Exception as e:
            print(f"[ORing] _debut_highlight AVERT : {e}")

    def _fin_highlight(self):
        """
        Retire la surbrillance du joint ORing.
        Appelée à la fermeture du dialogue et à l'annulation du mode modification.
        """
        if not FREECAD_DISPONIBLE:
            return
        try:
            if getattr(self, '_highlighted_obj_name', ''):
                Gui.Selection.clearSelection()
                self._highlighted_obj_name = ''
                self._highlighted_doc_name = ''
                print("[ORing] Highlight désactivé")
        except Exception as e:
            print(f"[ORing] _fin_highlight AVERT : {e}")


    def _ouvrir_aide(self):
        """Ouvre le guide de démarrage (PrerequisHelper)."""
        try:
            from .prerequis_helper import PrerequisHelper
            from .helper_i18n import merge_helper_translations, make_tr

            # Construire un dict de traductions dédié au helper
            # en chargeant helper_<lang>.json sans dépendre de i18n.make_tr
            from . import i18n as _i18n_mod
            lang = _i18n_mod.get_lang()

            import json, os
            _locales = os.path.normpath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '..', 'locales')
            )
            translations = {}
            # Charger helper_<lang>.json, fallback helper_en.json
            for candidate in (lang, 'en'):
                path = os.path.join(_locales, f'helper_{candidate}.json')
                if os.path.isfile(path):
                    with open(path, 'r', encoding='utf-8') as _f:
                        translations.update(json.load(_f))
                    break

            tr_helper = make_tr(translations)
            dlg = PrerequisHelper(tr=tr_helper, parent=self)
            dlg.exec_()
        except Exception as e:
            print(f"[ORing] _ouvrir_aide ERREUR : {e}")
            import traceback; traceback.print_exc()
            try:
                QtWidgets.QMessageBox.warning(
                    self, "ORing — Aide",
                    f"Impossible d'ouvrir le guide :\n{e}"
                )
            except Exception:
                pass

    def _ouvrir_depuis_selection(self, part):
        """
        Ouvre directement le dialogue en mode modification sur l'onglet 2
        pour le joint ORing ``part``.

        Équivalent à : onglet 3 → sélectionner le joint → clic Modifier.
        Appelée depuis lancer_dialogue() quand un joint est sélectionné
        avant le lancement de la macro.
        """
        try:
            from .metadata import lire_metadonnees, verifier_derives
        except ImportError:
            return

        meta = lire_metadonnees(part)
        if not meta:
            print(f"[ORing] _ouvrir_depuis_selection : métadonnées introuvables pour {part.Name}")
            return

        # Initialiser la référence AVANT prefill (requis par _get_diametre_calcul)
        self._part_en_modification = part
        self._d_comp_ref_modif = float(meta.get('d_comp_ref_mm', 0.0))

        # Vérifier dérive
        try:
            infos_derives = verifier_derives(self._doc)
            derive_info = next(
                (d for d in infos_derives if d['part'].Name == part.Name), None
            )
            if derive_info and derive_info.get('derive'):
                meta_maj = self._recalculer_apres_derive(part, meta, derive_info)
                if meta_maj is None:
                    self._part_en_modification = None
                    self._d_comp_ref_modif = 0.0
                    return
                meta = meta_maj
                self._d_comp_ref_modif = float(
                    meta.get('d_comp_ref_mm', self._d_comp_ref_modif)
                )
        except Exception as e:
            print(f"[ORing] _ouvrir_depuis_selection dérive AVERT : {e}")

        # Même séquence que _on_clic_modifier
        try:
            self.table_joints.deverrouiller()
        except Exception:
            pass
        self._meta_en_cours = meta   # pour _debut_highlight dans _entrer_mode_modification
        self._prefill_depuis_meta(meta)
        self._entrer_mode_modification(part, meta)
        self._tabs.setCurrentIndex(1)   # onglet 2 (index 1)
        print(f"[ORing] Ouverture directe en mode modification : {part.Label}")

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
        self._meta_en_cours = meta   # pour _debut_highlight dans _entrer_mode_modification
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
                    tr("\u26a0  Drift detected: reference \u00d8 = {ref:.3f} mm "
                    "\u2192 current value = {cur:.3f} mm  (\u0394 {delta:+.3f} mm)\n"
                    "   The calculation uses the reference diameter from insertion. "
                    "Recreate the seal to use the new value.",
                    ref=self._d_comp_ref_modif, cur=d_courant, delta=delta)
                )

        # ── Mettre le joint en surbrillance ──────────────────────────────
        # Récupérer meta depuis les attributs déjà stockés si dispo
        try:
            _meta_hl = getattr(self, '_meta_en_cours', None)
            if _meta_hl is None:
                from .metadata import lire_metadonnees
                _meta_hl = lire_metadonnees(part) or {}
            self._debut_highlight(part, _meta_hl)
        except Exception as _e_hl:
            print(f"[ORing] highlight dans _entrer AVERT : {_e_hl}")

        # ── Verrouiller les widgets non-modifiables ───────────────────────
        self._appliquer_verrous_modification(verrouiller=True)

        # ── Titre et bouton Appliquer ─────────────────────────────────────
        self.setWindowTitle(
            tr("ORing — Edit: {body}  ·  LCS {lcs}", body=body_label, lcs=lcs_label)
        )
        self.btn_appliquer.setText(tr("Update"))
        self.btn_appliquer.setEnabled(True)
        self.btn_appliquer.setStyleSheet(
            "QPushButton { background-color: #1a5276; color: white; font-weight: bold; }"
        )
        # ── Bouton Annuler modification ───────────────────────────────────
        if not hasattr(self, 'btn_annuler_modif'):
            self.btn_annuler_modif = QtWidgets.QPushButton(tr("✕  Cancel edit"))
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
                tr("ORing \u2014 Reference diameter drift"),
                derive_msg
            )

    def _maj_joints_lies(self, body_modifie_label: str,
                         dlg_progression=None):
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

        # Capturer le résultat du joint modifié AVANT d'entrer dans la boucle.
        # self._resultat peut être écrasé lors d'un recalcul intermédiaire ;
        # on fige ici la référence pour que tous les joints liés puissent
        # utiliser les mêmes dimensions garanties valides.
        _r_joint_modifie = self._resultat

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

        # Suivi des joints dont le standard a dû être changé faute de solution
        # dans le standard d'origine. Chaque entrée est un dict :
        #   { 'label', 'std_avant', 'serie_avant', 'std_apres', 'serie_apres' }
        # La liste est retournée en fin de méthode et consommée par _travail_lourd
        # pour afficher une alerte récapitulative à l'utilisateur.
        _changements_standard = []

        # Pré-calculer le nombre de joints qui seront effectivement traités
        # (ceux qui partagent le body modifié) pour afficher 1/N puis 2/N
        def _partage_body(meta_d):
            _bm = ''
            for _o in doc.Objects:
                if (_o.TypeId == 'PartDesign::Body'
                        and _o.Label == body_modifie_label):
                    _bm = _o.Name
                    break
            if _bm:
                return _bm in (meta_d.get('body_gorge_name',''),
                               meta_d.get('body_comp_name',''))
            return (meta_d.get('body_gorge_label') == body_modifie_label
                    or meta_d.get('body_comp_label')  == body_modifie_label)

        _n_total_joints = sum(1 for _d in derives if _partage_body(_d['meta']))
        _n_joint_courant = 0  # incrémenté au début de chaque joint traité

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
            _n_joint_courant += 1
            _label_joint = getattr(part, 'Label', part.Name)
            print(f"[ORing lies]   Mise à jour automatique : '{part.Name}' "
                  f"(uuid={getattr(part, 'uuid_joint', '?')})")

            # Mettre à jour le texte du dialogue de progression
            if dlg_progression is not None:
                try:
                    from PySide2.QtWidgets import QApplication
                    from PySide2.QtCore    import QEventLoop
                    dlg_progression.setText(tr(
                        "Updating linked seals...\n\nSeal {n}/{total}: {label}",
                        n=_n_joint_courant, total=_n_total_joints, label=_label_joint)
                    )
                    QApplication.processEvents(
                        QEventLoop.ExcludeUserInputEvents
                        | QEventLoop.ExcludeSocketNotifiers)
                except Exception:
                    pass

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
                # Gorge dans l'alésage : d_gorge_new = Ø alésage (inchangé),
                # d_comp_new = Ø arbre (mis à jour).
                # Le jeu réel a changé si l'arbre a changé → le recalculer
                # pour que calculer_gorge dérive le bon D_arbre.
                d_alesage_calc = d_gorge_new
                _jeu_reel = (d_gorge_new - d_comp_new) / 2.0
                if _jeu_reel >= 0.0:
                    # Jeu positif : l'arbre est plus petit que l'alésage (normal)
                    jeu_mm = round(_jeu_reel, 4)
                    print(f"[ORing lies]   jeu recalculé pour gorge alésage : {jeu_mm:.4f} mm "
                          f"(Ø_al={d_gorge_new:.3f}  Ø_arbre={d_comp_new:.3f})")
                else:
                    # Jeu négatif : incohérence (arbre > alésage) — garder le jeu stocké
                    print(f"[ORing lies]   AVERT jeu négatif ({_jeu_reel:.4f}) — "
                          f"jeu stocké conservé ({jeu_mm:.4f})")

            print(f"[ORing lies]   d_gorge={d_gorge_new:.3f}  d_alesage_calc={d_alesage_calc:.3f}  "
                  f"d_comp={d_comp_new:.3f}  jeu={jeu_mm:.4f}")

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
                    _std        = meta.get('standard', '')
                    _serie_orig = meta.get('serie', '')
                    print(f"[ORing lies]   série '{_serie_orig}' inadaptée au nouveau Ø "
                          f"→ tentative avec les caractéristiques du joint modifié")

                    # Fallback : utiliser directement les caractéristiques du joint
                    # modifié.  Le joint lié partage le même body → même diamètre
                    # de référence → les valeurs (d2, h, b, squeeze) du joint modifié
                    # sont garanties correctes et cohérentes pour cet assemblage.
                    if (_r_joint_modifie is not None
                            and _r_joint_modifie.valide
                            and _r_joint_modifie.squeeze_pct is not None
                            and 5.0 <= float(_r_joint_modifie.squeeze_pct) <= 35.0):
                        r_new = _r_joint_modifie
                        print(f"[ORing lies]   \u2713 caractéristiques du joint modifié adoptées : "
                              f"d2={float(r_new.d2):.2f}mm  "
                              f"sq={float(r_new.squeeze_pct):.1f}%")

                        # Tracker tout changement de série ou de standard
                        _std_apres   = str(r_new.standard) if hasattr(r_new, 'standard') else _std
                        _serie_apres = str(r_new.serie)    if hasattr(r_new, 'serie')    else ''
                        if _std_apres != _std or _serie_apres != _serie_orig:
                            _changements_standard.append({
                                'label':       getattr(part, 'Label', part.Name),
                                'std_avant':   _std,
                                'serie_avant': _serie_orig,
                                'std_apres':   _std_apres,
                                'serie_apres': _serie_apres,
                            })
                            print(f"[ORing lies]   \u26a0 série/standard changé(s) : "
                                  f"{_std}\u00b7{_serie_orig} "
                                  f"\u2192 {_std_apres}\u00b7{_serie_apres}")
                    else:
                        # Dernier recours : Auto (serie='').
                        # Ne devrait survenir que si self._resultat n'est pas
                        # disponible (annulation en cours de session, etc.).
                        print(f"[ORing lies]   résultat joint modifié non disponible "
                              f"→ Auto (dernier recours)")
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
                meta_new['jeu_radial_mm']    = jeu_mm                    # jeu recalculé si bore joint
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

            # Rafraîchissement visuel après chaque joint lié
            # → l'utilisateur voit la progression en 3D
            #
            # Gui.updateGui() seul ne suffit pas : _travail_lourd tourne dans
            # le thread Qt principal, Qt ne peut repeindre qu'entre deux appels
            # à la boucle d'événements.
            # processEvents(ExcludeUserInputEvents) vide la file de peinture/
            # timers SANS traiter les événements souris/clavier → pas de réentrance.
            try:
                import FreeCADGui as _Gui
                _Gui.updateGui()
            except Exception:
                pass
            try:
                from PySide2.QtWidgets import QApplication
                from PySide2.QtCore    import QEventLoop
                QApplication.processEvents(
                    QEventLoop.ExcludeUserInputEvents
                    | QEventLoop.ExcludeSocketNotifiers)
            except Exception:
                pass

        # Commit de la transaction
        try:
            doc.commitTransaction()
        except Exception:
            pass
        _n_std = len(_changements_standard)
        print(f"[ORing lies] TOTAL : {_time.time()-_t_total:.2f}s pour {len(derives)} joint(s)"
              + (f"  —  {_n_std} changement(s) de standard" if _n_std else ""))
        return _changements_standard

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
        self._fin_highlight()   # retirer la surbrillance du joint
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
        self.setWindowTitle(tr("ORing — O-Ring Groove Sizing"))
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
        grp = QtWidgets.QGroupBox(tr("Context"))
        f = QtWidgets.QFormLayout(grp)
        f.setVerticalSpacing(8)

        # Ligne 1 : position + pression côte à côte
        hl1 = QtWidgets.QHBoxLayout()
        self.combo_position = QtWidgets.QComboBox()
        self.combo_position.addItem(tr("Groove on shaft"),    "arbre")
        self.combo_position.addItem(tr("Groove in bore"), "alesage")
        self.spin_pression = QtWidgets.QDoubleSpinBox()
        self.spin_pression.setRange(0, 2000)
        self.spin_pression.setSuffix(" bar")
        self.spin_pression.setDecimals(1)
        hl1.addWidget(self.combo_position, 2)
        hl1.addWidget(QtWidgets.QLabel(tr("  Max pressure:")), 0)
        hl1.addWidget(self.spin_pression, 1)
        f.addRow(tr("Groove position:"), hl1)

        # Ligne 2 : plan esquisse + température côte à côte
        hl2 = QtWidgets.QHBoxLayout()
        self.combo_plan = QtWidgets.QComboBox()
        self.combo_plan.addItem(tr("XZ plane  (Z = part axis)"), "XZ")
        self.combo_plan.addItem(tr("YZ plane  (Z = part axis)"), "YZ")
        self.spin_temperature = QtWidgets.QDoubleSpinBox()
        self.spin_temperature.setRange(-200, 350)
        self.spin_temperature.setSuffix(" °C")
        self.spin_temperature.setValue(20.0)
        self.spin_temperature.setDecimals(0)
        hl2.addWidget(self.combo_plan, 2)
        hl2.addWidget(QtWidgets.QLabel(tr("  Max temp.:")), 0)
        hl2.addWidget(self.spin_temperature, 1)
        f.addRow(tr("Sketch plane:"), hl2)

        # Ligne 3 : type de montage
        self.combo_montage = QtWidgets.QComboBox()
        self.combo_montage.addItem(tr("Static"),                "statique")
        self.combo_montage.addItem(tr("Dynamic — translation"), "dynamique_translation")
        self.combo_montage.addItem(tr("Dynamic — rotation"),    "dynamique_rotation")
        f.addRow(tr("Installation type:"), self.combo_montage)

        # Ligne 4 : fluide (indicatif)
        self.edit_fluide = QtWidgets.QLineEdit()
        self.edit_fluide.setPlaceholderText(tr("e.g. mineral_oils  (indicative, checks material compatibility)"))
        f.addRow(tr("Fluid:"), self.edit_fluide)

        self.combo_position.currentIndexChanged.connect(self._on_position_change)
        # Recalcul auto quand conditions changent
        self.spin_pression.valueChanged.connect(self._on_recalcul_si_resultat)
        self.spin_temperature.valueChanged.connect(self._on_recalcul_si_resultat)
        self.edit_fluide.editingFinished.connect(self._on_recalcul_si_resultat)
        return grp

    # ------------------------------------------------------------------
    # Section Matériau
    # ------------------------------------------------------------------

    def _rafraichir_noms_materiaux(self):
        """
        Met à jour les textes du combo matériau avec les traductions courantes.
        Appelée via QTimer.singleShot(0) après démarrage de l'event loop,
        quand tr() est garanti opérationnel.
        """
        try:
            combo = self.combo_materiau
            current_data = combo.currentData()
            combo.blockSignals(True)
            for i in range(combo.count()):
                abrev = combo.itemData(i)
                if abrev:
                    from .materiaux import get_materiau
                    m = get_materiau(abrev)
                    combo.setItemText(i, f"{abrev} — {_nom_mat(m)}")
            # Restaurer la sélection courante
            for i in range(combo.count()):
                if combo.itemData(i) == current_data:
                    combo.setCurrentIndex(i)
                    break
            combo.blockSignals(False)
        except Exception as e:
            print(f"[ORing] _rafraichir_noms_materiaux AVERT : {e}")

    def _section_materiau(self):
        grp = QtWidgets.QGroupBox(tr("Material"))
        layout = QtWidgets.QVBoxLayout(grp)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.combo_materiau = QtWidgets.QComboBox()
        for abrev in liste_materiaux():
            m = get_materiau(abrev)
            self.combo_materiau.addItem(f"{abrev} — {_nom_mat(m)}", abrev)
        # Mémoriser pour rafraîchissement éventuel si la langue change
        self._combo_materiau_populated = True
        form.addRow(tr("Material:"), self.combo_materiau)

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
            tr("T  : {min_C}\u00b0C ... {max_C}\u00b0C", min_C=t["min_C"], max_C=t["max_C"]),
            tr("P  max : {p} bar", p=m["pression_max_bar"]),
            tr("Hardness: {shore} Shore A  (std: {std_hardness})",
            shore=("/".join(str(x) for x in m["durete_shore_A"])
                  if isinstance(m["durete_shore_A"], list)
                  else m["durete_shore_A"]),
            std_hardness=m["durete_standard"]),
            "",
            tr("Compatible   : ") + ", ".join(tr(f) for f in m["compatibilite"][:5]) +
            (" ..." if len(m["compatibilite"]) > 5 else ""),
            tr("Incompatible : ") + ", ".join(tr(f) for f in m["incompatibilite"][:4]) +
            (" ..." if len(m["incompatibilite"]) > 4 else ""),
        ]
        self.text_materiau_info.setPlainText("\n".join(lignes))
        self._on_recalcul_si_resultat()

    # ------------------------------------------------------------------
    # Section Joint / Gorge
    # ------------------------------------------------------------------
    def _section_joint(self):
        grp = QtWidgets.QGroupBox(tr("Seal / Groove"))
        f = QtWidgets.QFormLayout(grp)
        f.setVerticalSpacing(8)

        # Ligne 1 : Standard + Série + D1 (3 combos sur une ligne)
        hl_std = QtWidgets.QHBoxLayout()
        self.combo_standard = QtWidgets.QComboBox()
        for std in STANDARDS:
            self.combo_standard.addItem(std, std)
        self.combo_serie = QtWidgets.QComboBox()
        self.combo_serie.addItem(tr("Auto"), "")
        hl_std.addWidget(self.combo_standard, 2)
        hl_std.addWidget(QtWidgets.QLabel(tr("  Series (d2):")), 0)
        hl_std.addWidget(self.combo_serie, 3)
        f.addRow(tr("Standard:"), hl_std)
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
        self.spin_squeeze.setToolTip(tr(
            "0 = automatic target value based on installation type\n"
            "Any value > 0 disables automatic mode."
        ))
        self.lbl_squeeze_info = QtWidgets.QLabel()
        self.lbl_squeeze_info.setWordWrap(True)
        hl_sq.addWidget(self.spin_squeeze, 0)
        hl_sq.addWidget(self.lbl_squeeze_info, 1)
        f.addRow(tr("Target squeeze:"), hl_sq)
        self.spin_squeeze.valueChanged.connect(self._on_squeeze_info_change)
        self.combo_montage.currentIndexChanged.connect(self._on_squeeze_info_change)
        # Recalcul automatique quand montage ou squeeze changent (si résultat déjà présent)
        self.spin_squeeze.valueChanged.connect(self._on_recalcul_si_resultat)
        self.combo_montage.currentIndexChanged.connect(self._on_recalcul_si_resultat)
        self._on_squeeze_info_change()

        # Ligne 3 : désignation joint calculée (mise à jour par _on_calculer)
        self.lbl_joint_designation = QtWidgets.QLabel("—")
        self.lbl_joint_designation.setStyleSheet("QLabel { font-weight: bold; }")
        f.addRow(tr("Selected seal:"), self.lbl_joint_designation)

        # Ligne 4 : dimensions gorge calculées
        self.lbl_joint_dims = QtWidgets.QLabel("—")
        f.addRow(tr("Groove dimensions:"), self.lbl_joint_dims)

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

        # Garantie : l'item sélectionné ne doit jamais être un item grisé.
        # Si l'index courant pointe sur un item disabled, chercher le prochain
        # item enabled (en commençant par Auto=0).
        _idx_cur = self.combo_serie.currentIndex()
        _cur_item = model.item(_idx_cur)
        if _cur_item and not _cur_item.isEnabled():
            # Chercher le premier item enabled
            for i in range(model.rowCount()):
                _it = model.item(i)
                if _it and _it.isEnabled():
                    self.combo_serie.setCurrentIndex(i)
                    break

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
            self.lbl_squeeze_info.setText(tr(
                "\u27f3  Auto: {cible:.1f} %   "
                "(recommended range: {pmin}\u2013{pmax} %)",
                cible=cible, pmin=pmin, pmax=pmax))
            self.lbl_squeeze_info.setStyleSheet(
                "QLabel { color: #888888; font-style: italic; }"
            )
        else:
            # ── Mode manuel ───────────────────────────────────────────
            hors_plage = (val < pmin or val > pmax)
            if hors_plage:
                self.lbl_squeeze_info.setText(tr(
                    "\u270e  Manual \u2014  recommended: {pmin}\u2013{pmax} %  "
                    "\u26a0 out of range",
                    pmin=pmin, pmax=pmax))
                self.lbl_squeeze_info.setStyleSheet(
                    "QLabel { color: #cc6600; font-weight: bold; }"
                )
            else:
                self.lbl_squeeze_info.setText(tr(
                    "\u270e  Manual \u2014  recommended: {pmin}\u2013{pmax} %",
                    pmin=pmin, pmax=pmax))
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
        grp = QtWidgets.QGroupBox(tr("FreeCAD Parts"))
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
            grp_lcs = QtWidgets.QGroupBox(tr("LCS  (groove mid-plane)"))
            lcs_layout = QtWidgets.QFormLayout(grp_lcs)
            self.combo_lcs = QtWidgets.QComboBox()
            self.combo_lcs.addItem(tr("— select —"), None)
            lcs_layout.addRow(tr("LCS:"), self.combo_lcs)
            note_lcs = QtWidgets.QLabel(tr("LCS XZ plane = part Z axis."))
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
            lbl_ref = QtWidgets.QLabel(tr("(Reference dimension for calculation)"))
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
            self.lbl_d_comp_modif = QtWidgets.QLabel(tr("New complementary part Ø:"))
            self.lbl_d_comp_modif.setVisible(False)
            self.spin_d_comp_modif = QtWidgets.QDoubleSpinBox()
            self.spin_d_comp_modif.setRange(0.1, 5000.0)
            self.spin_d_comp_modif.setSuffix(" mm")
            self.spin_d_comp_modif.setDecimals(3)
            self.spin_d_comp_modif.setVisible(False)
            self.spin_d_comp_modif.setToolTip(tr(
                "Target diameter of the complementary part.\n"
                "In edit mode: recalculates the groove\n"
                "AND updates the complementary part parameter."
            ))
            jeu_form.addRow(self.lbl_d_comp_modif, self.spin_d_comp_modif)
            self.spin_d_comp_modif.valueChanged.connect(self._on_dims_change)

            # ── Mode jeu : Manuel / ISO H/g / ISO H/f ─────────────────
            hl_mode = QtWidgets.QHBoxLayout()
            self.combo_mode_jeu = QtWidgets.QComboBox()
            self.combo_mode_jeu.addItem(tr("Manual"),  "manuel")
            self.combo_mode_jeu.addItem("ISO H/g", "g")
            self.combo_mode_jeu.addItem("ISO H/f", "f")
            self.combo_mode_jeu.setToolTip(tr(
                "Manual: direct radial clearance entry.\n"
                "ISO H/g: guaranteed clearance fit (e.g. H7/g6).\n"
                "ISO H/f: loose clearance fit (e.g. H8/f7).\n"
                "In ISO mode, the calculated minimum clearance is used automatically."
            ))
            self.lbl_grade_arbre = QtWidgets.QLabel(tr("Shaft grade:"))
            self.combo_grade_arbre = QtWidgets.QComboBox()
            for _g in (6, 7, 8, 9):
                self.combo_grade_arbre.addItem(f"IT{_g}", _g)
            self.combo_grade_arbre.setCurrentIndex(1)   # IT7 par défaut
            self.combo_grade_arbre.setToolTip(tr(
                "Shaft IT grade.\nThe bore H takes grade + 1 automatically."
            ))
            self.lbl_designation_iso = QtWidgets.QLabel("")
            self.lbl_designation_iso.setStyleSheet("font-weight: bold; color: #335599;")
            hl_mode.addWidget(self.combo_mode_jeu)
            hl_mode.addWidget(self.lbl_grade_arbre)
            hl_mode.addWidget(self.combo_grade_arbre)
            hl_mode.addWidget(self.lbl_designation_iso)
            hl_mode.addStretch()
            jeu_form.addRow(tr("Clearance mode:"), hl_mode)

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
            self.spin_jeu.setToolTip(tr(
                "Radial clearance between shaft and bore.\n"
                "Shaft groove   : D_shaft = D_bore - 2 × clearance\n"
                "Bore groove    : D_bore  = D_shaft + 2 × clearance\n"
                "(Disabled in ISO mode \u2014 value calculated automatically.)"
            ))
            jeu_form.addRow(tr("Radial clearance:"), self.spin_jeu)

            self.label_d_principale_derive = QtWidgets.QLabel("—")
            self.label_d_principale_derive.setStyleSheet("font-weight: bold;")
            jeu_form.addRow(tr("\u21d2 D main part:"), self.label_d_principale_derive)
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
            outer.addWidget(QtWidgets.QLabel(tr(
                "No active FreeCAD document.\n"
                "Use the manual diameter in the Seal / Groove section."
            )))

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
        self.combo_lcs.addItem(tr("— select —"), None)
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
            # Utiliser lister_lcs_libres (centralisé, même logique que
            # lister_bodies_valides_gorge) pour garantir la cohérence
            from .utils import lister_lcs_libres as _lcs_libres_fn
            lcs_libres = _lcs_libres_fn(body_principal, self._doc)
            # En mode modification, réinclure le LCS du joint modifié
            # (il est "occupé" mais on peut le modifier)
            if self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees
                    m = lire_metadonnees(self._part_en_modification)
                    lcs_modif_label = m.get('lcs_label', '')
                    if lcs_modif_label:
                        deja_presents = {l.Label for l in lcs_libres}
                        for lcs in lcs_list:
                            if (lcs.Label == lcs_modif_label
                                    and lcs.Label not in deja_presents):
                                lcs_libres.append(lcs)
                                break
                except Exception:
                    pass
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
                self.lbl_designation_iso.setText(tr("(enter \u00d8 first)"))
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
    def _on_calculer(self, _force=False):
        """Calcul principal — protégé par debounce QTimer (100ms).

        Les signaux Qt (valueChanged, currentIndexChanged) déclenchent
        _on_calculer plusieurs fois de suite lors d'une mise à jour groupée
        de l'UI. Le QTimer regroupe ces appels en un seul calcul effectif
        50ms après le dernier signal reçu.
        _force=True : contourner le debounce (appel direct, ex. Appliquer).
        """
        if not _force:
            # Annuler le timer précédent et le relancer — seul le dernier
            # déclenchement (après 50ms de silence) lance le vrai calcul.
            if not hasattr(self, '_timer_calcul'):
                from PySide2.QtCore import QTimer
                self._timer_calcul = QTimer(self)
                self._timer_calcul.setSingleShot(True)
                self._timer_calcul.timeout.connect(lambda: self._on_calculer(_force=True))
            self._timer_calcul.start(50)
            return

        if self._calcul_en_cours:
            return
        self._calcul_en_cours = True
        try:
            self._on_calculer_interne()
        finally:
            self._calcul_en_cours = False

    def _on_calculer_interne(self):
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
            tr("  Seal  : {std} / series {series}", std=r.standard, series=r.serie),
            f"  d1 = {r.d1} mm   d2 = {r.d2} mm"
            + (f"   [{r.code_joint}]" if r.code_joint else ""),
            tr("  Stretch ({label}): {st:.2f} %", label=label_d, st=r.stretch_pct),
            "-" * 54,
            tr("  Groove : h = {h:.3f} mm   b = {b:.3f} mm", h=r.h, b=r.b),
            tr("  Squeeze: {sq:.1f} %   Fill: {fill:.1f} %", sq=r.squeeze_pct, fill=r.fill_pct),
            tr("  \u00d8 groove bottom: {d:.1f} mm", d=r.rayon_gorge * 2),
            "-" * 54,
            tr("  Extrusion: {risk}", risk=r.risque_extrusion)
            + ("  " + tr("RING REQUIRED") if r.bague_antiextrusion else ""),
        ]
        if r.alertes:
            lignes += ["-" * 54, tr("  ALERTS:")]
            for a in r.alertes:
                lignes.append(f"    - {a}")
        if r.avertissements:
            lignes += ["-" * 54, tr("  Warnings:")]
            for a in r.avertissements:
                lignes.append(f"    - {a}")
        lignes += [
            "=" * 54,
            (tr("  OK VALID") if r.valide else tr("  INVALID \u2014 see alerts")),
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
                tr("Complementary part diameter not set.\n"
                "Select the body and parameter in the Parts tab,\n"
                "or enter the diameter manually.")
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
                    tr("ORing — Existing seal"),
                    tr("A seal already exists at this location:\n\n"
                    "  Part   : {body}\n  LCS    : {lcs}\n"
                    "  Seal   : {std} / {series}  d2 = {d2:.2f} mm\n"
                    "  Squeeze: {sq_target:.1f} %  (actual: {sq_real:.1f} %)\n"
                    "  Groove : h = {h:.3f} mm  b = {b:.3f} mm\n\n"
                    "  \u2192 Existing part: \u00ab {name} \u00bb\n\n"
                    "Delete the existing assembly before inserting a new one.",
                    body=m.get("body_gorge_label","?"), lcs=m.get("lcs_label","?"),
                    std=m.get("standard","?"), series=m.get("serie","?"),
                    d2=m.get("d2_mm",0.0), sq_target=m.get("squeeze_cible_pct",0.0),
                    sq_real=m.get("squeeze_reel_pct",0.0),
                    h=m.get("h_mm",0.0), b=m.get("b_mm",0.0), name=nom_existant)
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
            # Ignorée si seul le matériau change (fast-path détecté plus bas).
            # On pré-détecte ici pour conditionner la section 0.
            _meta_preflight = {}
            if self._part_en_modification is not None:
                try:
                    from .metadata import lire_metadonnees as _lmn_pre
                    _meta_preflight = _lmn_pre(self._part_en_modification)
                except Exception:
                    pass
            _d_princ_ref = float(_meta_preflight.get('d_gorge_ref_mm', -1.0))
            _skip_section0 = (
                self._part_en_modification is not None
                and _d_princ_ref >= 0.0
                and abs(d_princ - _d_princ_ref) < 0.001
                and (_meta_preflight.get('standard','') ==
                     (self.combo_standard.currentData() or ''))
                and (_meta_preflight.get('serie','') ==
                     (self.combo_serie.currentData() or ''))
                and abs(float(_meta_preflight.get('jeu_radial_mm', -1.0)) - jeu) < 0.001
            )
            if not _skip_section0 and hasattr(self, 'widget_piece_principale'):
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
                            tr("ORing — Parameter not updated"),
                            tr("Cannot modify '{param}':\n{msg}\n\n"
                            "Insertion continues with the current diameter.",
                            param=nom_param, msg=msg)
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
                                    tr("ORing — Complementary part parameter not updated"),
                                    tr("Cannot modify '{param}' on body '{body}':\n{msg}\n\n"
                                    "The groove is recalculated with the new diameter\n"
                                    "but the complementary body was not modified.",
                                    param=_param_comp, body=_body_comp_label, msg=_msg)
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
                from .metadata import lire_metadonnees
                meta_existante = lire_metadonnees(self._part_en_modification)

                # ── Fast-path : seul le matériau a changé ─────────────────────
                # Si toutes les dimensions sont identiques aux métadonnées stockées
                # et que seul le matériau diffère, on met à jour uniquement la
                # couleur et les métadonnées — gorge et tore ne sont pas retouchés.
                _mat_ancien  = meta_existante.get('materiau', '')
                _mat_nouveau = self.combo_materiau.currentData() or ''
                _d2_ancien   = float(meta_existante.get('d2_mm', 0.0))
                _d2_nouveau  = float(self._resultat.d2) if (
                    self._resultat and self._resultat.d2) else 0.0
                _sq_ancien   = float(meta_existante.get('squeeze_cible_pct', 0.0))
                _sq_nouveau  = float(self.spin_squeeze.value())
                _jeu_ancien  = float(meta_existante.get('jeu_radial_mm', 0.0))
                _jeu_nouveau = float(jeu)
                _std_ancien  = meta_existante.get('standard', '')
                _std_nouveau = self.combo_standard.currentData() or ''
                _serie_ancienne = meta_existante.get('serie', '')
                _serie_nouvelle = self.combo_serie.currentData() or ''

                _seul_materiau = (
                    _mat_ancien  != _mat_nouveau          # matériau a changé
                    and abs(_d2_nouveau - _d2_ancien) < 0.001  # d2 identique
                    and abs(_sq_nouveau - _sq_ancien) < 0.01   # squeeze identique
                    and abs(_jeu_nouveau - _jeu_ancien) < 0.001 # jeu identique
                    and _std_nouveau == _std_ancien             # même standard
                    and _serie_nouvelle == _serie_ancienne      # même série
                    and abs(d_princ - float(meta_existante.get('d_gorge_ref_mm', d_princ))) < 0.001
                )

                if _seul_materiau:
                    print(f"[ORing] Fast-path matériau seul : "
                          f"'{_mat_ancien}' → '{_mat_nouveau}'")
                    # Mettre à jour uniquement la couleur du tore
                    body_oring_nom = meta_existante.get('body_oring_name', '')
                    body_oring = (self._doc.getObject(body_oring_nom)
                                  if body_oring_nom else None)
                    if body_oring is None:
                        for _child in getattr(self._part_en_modification, 'Group', []):
                            if (_child.TypeId == 'PartDesign::Body'
                                    and _child.Label.startswith('ORing')):
                                body_oring = _child
                                break
                    if body_oring is not None:
                        from .oring_3d import appliquer_couleur_materiau
                        appliquer_couleur_materiau(body_oring, _mat_nouveau)
                    # Mettre à jour uniquement les métadonnées matériau
                    from .metadata import ecrire_metadonnees
                    _meta_new = dict(meta_existante)
                    _meta_new['materiau'] = _mat_nouveau
                    _meta_new['type_montage'] = (self.combo_montage.currentData()
                                                  or meta_existante.get('type_montage', ''))
                    _meta_new['pression_bar'] = float(self.spin_pression.value())
                    _meta_new['temperature_C'] = float(self.spin_temperature.value())
                    ecrire_metadonnees(self._part_en_modification, _meta_new)
                    sketch_nom = meta_existante.get('sketch_gorge_name', '')
                    sketch     = self._doc.getObject(sketch_nom) if sketch_nom else None
                    # Sauter tout le reste du flux (gorge, tore, paramètres pièce)
                    # en allant directement au post-traitement
                    _fast_path_materiau = True
                else:
                    _fast_path_materiau = False

                if not _fast_path_materiau:
                    # Forcer un recalcul avec les valeurs UI courantes
                    self._on_calculer(_force=True)
                    if not self._resultat or not self._resultat.valide:
                        message_erreur(tr("ORing — Recalculation"),
                            tr("Recalculation with the new diameter failed or produced\n"
                            "an invalid result. Check the parameters.")
                            + "\n\n" + ('\n'.join(self._resultat.alertes) if self._resultat else '')
                        )
                        return
                    # Capturer AVANT ecrire_metadonnees
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
                msg_titre = tr("ORing — Edit applied")
                # Vérifier si des erreurs TNP persistent
                _tnp_warn = ''
                try:
                    from .metadata import lire_metadonnees as _lmn2
                    _m2 = _lmn2(self._part_en_modification)
                    _tnp_feats = _m2.get('_tnp_erreurs', [])
                    if _tnp_feats:
                        _tnp_warn = (
                            f"\n\n⚠  Références d'arêtes perdues (TNP) :\n"
                            f"   {', '.join(_tnp_feats)}\n"
                            f"   → Corriger manuellement dans FreeCAD."
                        )
                except Exception:
                    pass
                msg_corps = (
                    tr("Groove and 3D seal updated successfully.\n\n"
                    "  Standard / Series: {std} / {series}\n"
                    "  d2 = {d2:.2f} mm  h = {h:.3f} mm  b = {b:.3f} mm\n"
                    "  Actual squeeze: {sq:.1f} %  Fill: {fill:.1f} %\n\n"
                    "  D main part          : {d_princ:.3f} mm\n"
                    "  D complementary part : {d_compl:.3f} mm\n"
                    "  Radial clearance     : {jeu:.3f} mm",
                    std=self.combo_standard.currentData(),
                    series=self.combo_serie.currentData() or tr("Auto"),
                    d2=float(self._resultat.d2),
                    h=float(self._resultat.h), b=float(self._resultat.b),
                    sq=float(self._resultat.squeeze_pct),
                    fill=float(self._resultat.fill_pct),
                    d_princ=d_princ, d_compl=d_compl, jeu=jeu)
                    + _tnp_warn
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
                msg_corps = tr(
                    "Groove generated successfully!\n\n"
                    "D main part          : {d_princ:.3f} mm\n"
                    "D complementary part : {d_compl:.3f} mm\n"
                    "Radial clearance     : {jeu:.3f} mm",
                    d_princ=d_princ, d_compl=d_compl, jeu=jeu
                )

            # FIX #8 : mémoriser le choix diam/rayon pour les prochaines insertions
            try:
                if hasattr(self, 'widget_piece_principale'):
                    self._dernier_radio_rayon = (
                        self.widget_piece_principale.radio_rayon.isChecked()
                    )
                # Mémoriser le label du body gorge pour restaurer le body
                # actif à la fermeture du dialogue
                _body_sel = self.widget_piece_principale.combo_body.currentData()
                if _body_sel:
                    self._dernier_body_gorge_label = _body_sel
            except Exception:
                pass

            # ── Couleur matériau (synchrone — visible avant le message) ──────
            self._on_recalibrer_couleurs()

            # ── Afficher le message IMMÉDIATEMENT ────────────────────────────
            # Les tâches lourdes (_maj_joints_lies, _onglet_initial) sont
            # différées via QTimer pour ne pas bloquer l'affichage.
            message_info(msg_titre, msg_corps, parent=self)

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
                    _dlg_attente.setWindowTitle(tr("ORing \u2014 Update in progress"))
                    _dlg_attente.setText(tr(
                        "Updating linked seals...\n"
                        "Please wait."
                    ))
                    _dlg_attente.setStandardButtons(QtWidgets.QMessageBox.NoButton)
                    _dlg_attente.setModal(True)
                    _dlg_attente.show()
                except Exception:
                    _dlg_attente = None

                def _travail_lourd():
                    _std_changes = []
                    try:
                        _std_changes = self._maj_joints_lies(
                            _body_label_pour_lies,
                            dlg_progression=_dlg_attente) or []
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

                    # ── Alerte changements de série / standard ────────────────
                    # Affiché après _onglet_initial pour que le tableau soit déjà
                    # rafraîchi quand l'utilisateur lit le message.
                    if _std_changes:
                        _lignes = []
                        for _ch in _std_changes:
                            _lignes.append(
                                f"\u2022 {_ch['label']} :\n"
                                f"   {_ch['std_avant']} \u00b7 {_ch['serie_avant']}"
                                f"  \u2192  {_ch['std_apres']} \u00b7 {_ch['serie_apres']}"
                            )
                        _msg_std = (
                            "\u26a0  Lors de la mise à jour automatique des joints liés,\n"
                            "la série d'origine n'offrait aucune solution adaptée.\n"
                            "Les joints suivants ont été mis à jour avec les\n"
                            "caractéristiques du joint modifié :\n\n"
                            + "\n\n".join(_lignes)
                            + "\n\nVérifiez la compatibilité de ces joints\n"
                              "avec votre assemblage avant utilisation."
                        )
                        QtWidgets.QMessageBox.warning(
                            self,
                            "ORing \u2014 Changement de série / standard",
                            _msg_std,
                        )

                # 50 ms laisse le temps à Qt de rendre le dialogue
                QtCore.QTimer.singleShot(50, _travail_lourd)

            QtCore.QTimer.singleShot(0, _post_confirmation)

        except Exception:
            import traceback
            message_erreur(tr("ORing — Generation error"), traceback.format_exc())

    @staticmethod
    def _restaurer_body_actif(doc, body_label=None):
        """Restaure le body gorge comme body actif dans FreeCAD après fermeture
        du dialogue. Sans cette restauration, FreeCAD laisse le body ORing
        (ou aucun body) actif, ce qui empêche les opérations PartDesign
        suivantes (Fillet, Chamfer…) de s'afficher correctement.
        """
        try:
            import FreeCADGui as Gui
            if not (hasattr(Gui, 'ActiveDocument') and Gui.ActiveDocument):
                return
            view = Gui.ActiveDocument.ActiveView
            # Chercher le body gorge par label
            body_gorge = None
            if body_label:
                for obj in doc.Objects:
                    if (obj.TypeId == 'PartDesign::Body'
                            and obj.Label == body_label):
                        body_gorge = obj
                        break
            # Désactiver tout body ORing actif et activer le body gorge
            view.setActiveObject('pdbody', body_gorge)
            if body_gorge:
                print(f"[ORing] Body actif restauré : '{body_gorge.Label}'")
            else:
                view.setActiveObject('pdbody', None)
                print("[ORing] Body actif réinitialisé (aucun body gorge trouvé)")
        except Exception as _e:
            print(f"[ORing] Restauration body actif : {_e}")

    @staticmethod
    def _maj_techdraw(doc):
        """Rafraîchit toutes les pages TechDraw du document.
        Appelé uniquement à la fermeture du dialogue pour ne pas ralentir
        les recomputes intermédiaires de la macro.
        """
        try:
            pages = [obj for obj in doc.Objects
                     if getattr(obj, 'TypeId', '') == 'TechDraw::DrawPage']
            if not pages:
                return
            for page in pages:
                try:
                    page.touch()
                except Exception:
                    pass
            doc.recompute()
            print(f"[ORing] TechDraw : {len(pages)} page(s) mises à jour")
        except Exception as e:
            print(f"[ORing] TechDraw maj : {e}")

    def _get_body_gorge_label(self):
        """Retourne le label du body gorge à restaurer comme body actif.
        Priorité :
          1. _dernier_body_gorge_label (mis à jour après chaque Appliquer)
          2. body_gorge_label stocké dans les métadonnées du Part en cours de modification
          3. Première ligne de l'onglet 3 (joints existants)
        """
        label = getattr(self, '_dernier_body_gorge_label', None)
        if label:
            return label
        # Fallback : lire depuis les métadonnées du dernier Part modifié
        try:
            from .metadata import lire_metadonnees
            part = getattr(self, '_part_en_modification', None)
            if part is None and hasattr(self, 'table_joints'):
                # Prendre le premier Part de la liste
                from .metadata import lister_parts_oring
                parts = lister_parts_oring(self._doc)
                if parts:
                    part = parts[0]
            if part is not None:
                meta = lire_metadonnees(part)
                lbl = meta.get('body_gorge_label', '')
                if lbl:
                    return lbl
        except Exception:
            pass
        return None

    def closeEvent(self, event):
        """Restaure exactement l'état visuel d'origine avant fermeture."""
        self._fin_highlight()   # retirer la surbrillance du joint
        _restaurer_snapshot(self._doc)
        if hasattr(self, 'table_joints'):
            self.table_joints._locked_row = -1
            self.table_joints._hover_row  = -1
        # Restaurer le body gorge comme body actif AVANT TechDraw
        self._restaurer_body_actif(self._doc, self._get_body_gorge_label())
        self._maj_techdraw(self._doc)
        super().closeEvent(event)

    def reject(self):
        """Fermeture par Échap ou bouton Fermer."""
        self._fin_highlight()   # retirer la surbrillance du joint
        _restaurer_snapshot(self._doc)
        self._restaurer_body_actif(self._doc, self._get_body_gorge_label())
        self._maj_techdraw(self._doc)
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


# =============================================================================
# Utilitaires : silence des logs FreeCAD pendant les recomputes
# =============================================================================

def _silence_propertlylinks():
    """Désactive temporairement les messages <PropertyLinks> du moteur FreeCAD.
    FreeCAD.setLogLevel ne couvre pas ce canal — on redirige le rapport
    en interceptant FreeCAD.Console.PrintLog.
    """
    try:
        import FreeCAD as _FC
        # Méthode 1 : setLogLevel (couvre certains canaux)
        try:
            _FC.setLogLevel('PropertyLinks', 0)
        except Exception:
            pass
        # Méthode 2 : observer Console pour filtrer PropertyLinks
        class _NullObserver:
            def __init__(self):
                self._orig = None
            def send(self, msg):
                pass  # absorber
        # Stocker l'observer pour restauration
        _silence_propertlylinks._observer = _NullObserver()
        try:
            _FC.Console.AttachObserver(_silence_propertlylinks._observer)
        except Exception:
            pass
    except Exception:
        pass


def _restore_propertylinks():
    """Restaure le niveau de log <PropertyLinks> à sa valeur par défaut."""
    try:
        import FreeCAD as _FC
        try:
            _FC.setLogLevel('PropertyLinks', 3)
        except Exception:
            pass
        obs = getattr(_silence_propertlylinks, '_observer', None)
        if obs is not None:
            try:
                _FC.Console.DetachObserver(obs)
            except Exception:
                pass
            _silence_propertlylinks._observer = None
    except Exception:
        pass


# =============================================================================
# TNP — Snapshot et restauration des arêtes d'habillage
# =============================================================================

def _est_en_erreur(obj):
    """Retourne True si une feature FreeCAD est dans un état Invalid ou Error."""
    _state = getattr(obj, 'State', [])
    if isinstance(_state, (list, tuple)):
        return any('Invalid' in str(s) or 'Error' in str(s) for s in _state)
    return 'Invalid' in str(_state) or 'Error' in str(_state)


#: Types de features d'habillage susceptibles de perdre leurs références TNP
# Features dont les références topologiques (arêtes, faces, sommets) peuvent
# être invalidées lors d'un recompute de gorge. Elles sont suspendues avant
# le recompute et réactivées après sur une géométrie stable.
#
# Catégorie 1 — Habillage (référencent des arêtes via Base)
_TYPES_HABILLAGE = frozenset({
    'PartDesign::Chamfer',
    'PartDesign::Fillet',
    'PartDesign::Draft',
    'PartDesign::RoundedCorners',
    'PartDesign::Thickness',
    'PartDesign::Hole',          # Plan d'accroche par face
})

# Catégorie 2 — Géométries de référence (plans/axes/points auxiliaires)
# référencent des faces ou arêtes via MapPathParameter / Support
_TYPES_DATUM = frozenset({
    'PartDesign::Plane',
    'PartDesign::Line',
    'PartDesign::Point',
    'PartDesign::CoordinateSystem',
    'Part::Datum',
})

# Catégorie 3 — Sketches avec attachement face/arête
# (MapMode != Origin implique un Support = (feat, ['FaceN']) ou ['EdgeN'])
_TYPES_SKETCH_ATTACHE = frozenset({
    'Sketcher::SketchObject',
})

# Modes d'attachement qui impliquent une référence topologique instable
_MAPMODES_STABLES = frozenset({
    'Deactivated',   # pas d'attachement
    'Origin',        # plan absolu
    'ObjectXY', 'ObjectXZ', 'ObjectYZ',   # plan d'un LCS/origin
    'ObjectX', 'ObjectY', 'ObjectZ',       # axe d'un LCS/origin
    '',
})


def _empreinte_arete(edge):
    """
    Calcule une empreinte géométrique d'une arête pour identification
    après changement de topologie.

    Retourne un dict avec les clés stables :
      - 'com'    : centre de masse (x, y, z) arrondi à 3 décimales
      - 'length' : longueur arrondie à 3 décimales
      - 'type'   : 'Circle' | 'Line' | 'Other'
      - 'radius' : rayon (si Circle), arrondi à 3 décimales
      - 'axis'   : direction de l'axe (si Circle), arrondi à 3 décimales
    """
    import math
    try:
        com = edge.CenterOfMass
        com_r = (round(com.x, 3), round(com.y, 3), round(com.z, 3))
        length = round(edge.Length, 3)
        curve = edge.Curve
        curve_type = type(curve).__name__

        result = {'com': com_r, 'length': length, 'type': curve_type}

        if curve_type == 'Circle':
            result['radius'] = round(curve.Radius, 3)
            ax = curve.Axis
            result['axis'] = (round(ax.x, 3), round(ax.y, 3), round(ax.z, 3))
        elif curve_type == 'Line':
            p1 = edge.firstVertex().Point
            p2 = edge.lastVertex().Point
            result['p1'] = (round(p1.x, 3), round(p1.y, 3), round(p1.z, 3))
            result['p2'] = (round(p2.x, 3), round(p2.y, 3), round(p2.z, 3))

        return result
    except Exception:
        return None


def _empreintes_compatibles(e1, e2, tol=0.5):
    """
    Compare deux empreintes d'arêtes. Retourne (score, True/False).
    score = 0..100, True si correspondance probable.
    tol = tolérance en mm sur les positions.
    """
    if e1 is None or e2 is None:
        return 0, False
    if e1['type'] != e2['type']:
        return 0, False

    def dist3(a, b):
        import math
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    score = 0
    # Centre de masse proche
    d_com = dist3(e1['com'], e2['com'])
    if d_com > tol * 10:
        return 0, False
    score += max(0, 40 - int(d_com / tol * 10))

    # Longueur proche
    dl = abs(e1['length'] - e2['length'])
    if dl > tol * 5:
        return score, False
    score += max(0, 30 - int(dl / tol * 6))

    if e1['type'] == 'Circle':
        dr = abs(e1.get('radius', 0) - e2.get('radius', 0))
        if dr > tol:
            return score, False
        score += max(0, 30 - int(dr / tol * 15))
    elif e1['type'] == 'Line':
        d1 = dist3(e1.get('p1', (0, 0, 0)), e2.get('p1', (0, 0, 0)))
        d2 = dist3(e1.get('p2', (0, 0, 0)), e2.get('p2', (0, 0, 0)))
        if min(d1, d2) > tol * 5:
            return score, False
        score += max(0, 30 - int(min(d1, d2) / tol * 6))
    else:
        score += 15

    return score, score >= 30


def _empreinte_subshape(obj, ref_name):
    """
    Calcule une empreinte géométrique pour une sous-forme (Face ou Edge)
    identifiée par son nom ('FaceN' ou 'EdgeN') dans la Shape de obj.
    Retourne un dict avec type, com, surface/longueur, normal (si face).
    """
    try:
        if ref_name.startswith('Face'):
            idx = int(ref_name.replace('Face', '')) - 1
            face = obj.Shape.Faces[idx]
            com  = face.CenterOfMass
            try:
                norm = face.normalAt(0, 0)
                normal = (round(norm.x, 3), round(norm.y, 3), round(norm.z, 3))
            except Exception:
                normal = None
            return {
                'type':    'Face',
                'ref':     ref_name,
                'com':     (round(com.x, 3), round(com.y, 3), round(com.z, 3)),
                'area':    round(face.Area, 3),
                'normal':  normal,
            }
        elif ref_name.startswith('Edge'):
            idx = int(ref_name.replace('Edge', '')) - 1
            edge = obj.Shape.Edges[idx]
            return _empreinte_arete(edge)
        elif ref_name.startswith('Vertex'):
            idx = int(ref_name.replace('Vertex', '')) - 1
            v   = obj.Shape.Vertexes[idx]
            p   = v.Point
            return {
                'type': 'Vertex',
                'ref':  ref_name,
                'com':  (round(p.x, 3), round(p.y, 3), round(p.z, 3)),
            }
    except Exception:
        pass
    return None


def _empreinte_subshape_compatible(e1, e2, tol=0.5):
    """Compare deux empreintes de sous-formes (Face/Edge/Vertex)."""
    if e1 is None or e2 is None:
        return 0, False
    if e1.get('type') != e2.get('type'):
        return 0, False
    t = e1['type']
    if t == 'Face':
        # Centre de masse proche
        import math
        d = math.sqrt(sum((a-b)**2 for a,b in zip(e1['com'], e2['com'])))
        if d > tol * 20:
            return 0, False
        score = max(0, 40 - int(d / tol * 4))
        # Aire proche
        da = abs(e1.get('area', 0) - e2.get('area', 0))
        if da > e1.get('area', 1) * 0.5:
            return score, False
        score += max(0, 30 - int(da / max(e1.get('area', 1), 1e-6) * 60))
        # Normale proche
        if e1.get('normal') and e2.get('normal'):
            dn = math.sqrt(sum((a-b)**2 for a,b in
                               zip(e1['normal'], e2['normal'])))
            score += max(0, 30 - int(dn * 30))
        return score, score >= 30
    elif t in ('Edge', 'Circle', 'Line', 'Other'):
        return _empreintes_compatibles(e1, e2, tol)
    elif t == 'Vertex':
        import math
        d = math.sqrt(sum((a-b)**2 for a,b in zip(e1['com'], e2['com'])))
        score = max(0, 100 - int(d / tol * 20))
        return score, score >= 40
    return 0, False


def _lire_references_tnp(obj):
    """
    Lit toutes les références topologiques d'un objet FreeCAD
    susceptibles d'être invalidées par le TNP.

    Retourne une liste de dicts :
      {'prop': nom_propriété, 'base_feat': objet_source,
       'refs': [{'nom': 'Face7', 'empreinte': {...}}, ...]}
    """
    resultats = []
    tipo = getattr(obj, 'TypeId', '')

    # ── Habillage : propriété Base = (feat, ['Edge5', ...]) ───────────────
    if tipo in _TYPES_HABILLAGE:
        base_prop = getattr(obj, 'Base', None)
        if isinstance(base_prop, (list, tuple)) and len(base_prop) == 2:
            base_feat, ref_names = base_prop
            if hasattr(base_feat, 'Shape') and base_feat.Shape is not None:
                refs = []
                for rname in ref_names:
                    refs.append({'nom': rname,
                                 'empreinte': _empreinte_subshape(base_feat, rname)})
                if refs:
                    resultats.append({
                        'prop': 'Base',
                        'base_feat': base_feat,
                        'refs': refs,
                    })

    # ── Datum et sketches : propriété MapPathParameter / Support ──────────
    elif tipo in _TYPES_DATUM or tipo in _TYPES_SKETCH_ATTACHE:
        # Vérifier si l'attachement est stable (plans d'origin/LCS)
        map_mode = getattr(obj, 'MapMode', '')
        if map_mode in _MAPMODES_STABLES:
            return []  # Attachement stable → pas de TNP

        # Lire le Support = (feat, ['FaceN']) ou MapPathParameter
        for prop_name in ('Support', 'MapPathParameter', 'AttachmentSupport'):
            prop = getattr(obj, prop_name, None)
            if prop is None:
                continue
            # Support peut être une liste de tuples [(feat, ['Face7']), ...]
            # ou un simple tuple (feat, ['Face7'])
            if isinstance(prop, (list, tuple)) and len(prop) > 0:
                pairs = prop if isinstance(prop[0], (list, tuple)) else [prop]
                for pair in pairs:
                    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                        continue
                    base_feat, ref_names = pair
                    if not (hasattr(base_feat, 'Shape')
                            and base_feat.Shape is not None):
                        continue
                    refs = []
                    for rname in (ref_names or []):
                        refs.append({'nom': rname,
                                     'empreinte': _empreinte_subshape(
                                         base_feat, rname)})
                    if refs:
                        resultats.append({
                            'prop': prop_name,
                            'base_feat': base_feat,
                            'refs': refs,
                        })
                break  # prendre la première propriété trouvée

    return resultats


def _suspendre_habillage(body):
    """
    Protège TOUTES les features du body dont les références topologiques
    pourraient être invalidées lors d'un recompute de gorge :

      - Habillage (Chamfer, Fillet, Draft, Thickness, Hole)
        → suspendues (Suppressed=True)
      - Datum (Plan, Axe, Point, LCS auxiliaires) avec attachement face/arête
        → détachées (MapMode → 'Deactivated')
      - Sketches avec attachement face/arête (MapMode non stable)
        → détachés (MapMode → 'Deactivated')

    Retourne la liste des objets protégés avec leur état de restauration.
    """
    suspendues = []
    for obj in getattr(body, 'Group', []):
        tipo = getattr(obj, 'TypeId', '')

        # ── Exclure les sketches de gorge ORing (ne jamais les toucher) ────
        if tipo in _TYPES_SKETCH_ATTACHE:
            label = getattr(obj, 'Label', '')
            if (label.startswith('GorgeArbre_') or
                    label.startswith('GorgeAlesage_') or
                    label.startswith('SketchORing')):
                continue

        try:
            refs = _lire_references_tnp(obj)
            if not refs:
                continue  # Pas de référence TNP → ignorer

            # ── Habillage : suspension (Suppressed) ───────────────────────
            if tipo in _TYPES_HABILLAGE:
                if not hasattr(obj, 'Suppressed'):
                    continue
                deja_suspendu = bool(obj.Suppressed)
                if not deja_suspendu:
                    obj.Suppressed = True
                noms = [r['nom'] for grp in refs for r in grp['refs']]
                print(f"[ORing TNP] Suspension '{obj.Label}' "
                      f"({tipo.split('::')[1]}) → {noms}")
                suspendues.append({
                    'feature':        obj,
                    'mode':           'suppressed',
                    'refs_groupes':   refs,
                    'base_prop':      getattr(obj, 'Base', None),
                    'edges':          refs[0]['refs'] if refs else [],
                    'deja_suspendue': deja_suspendu,
                })

            # ── Datum / Sketch : détachement (MapMode) ───────────────────
            elif tipo in _TYPES_DATUM or tipo in _TYPES_SKETCH_ATTACHE:
                map_mode_ancien = getattr(obj, 'MapMode', 'Deactivated')
                obj.MapMode = 'Deactivated'
                noms = [r['nom'] for grp in refs for r in grp['refs']]
                type_court = tipo.split('::')[1]
                print(f"[ORing TNP] Détachement '{obj.Label}' "
                      f"({type_court}, MapMode={map_mode_ancien}) → {noms}")
                suspendues.append({
                    'feature':      obj,
                    'mode':         'detached',
                    'map_mode_old': map_mode_ancien,
                    'refs_groupes': refs,
                    'deja_suspendue': False,
                })

        except Exception as _e:
            print(f"[ORing TNP] Protection '{getattr(obj,'Label','')}' : {_e}")

    return suspendues


def _snapshot_habillage(body):
    """Alias conservé pour compatibilité — délègue à _suspendre_habillage."""
    return _suspendre_habillage(body)


def _remappe_refs(feat, refs_groupes, prop_name, new_shape):
    """
    Tente de remapper les références topologiques d'un objet via empreinte
    géométrique. Retourne True si réussi.
    """
    candidats = []
    for i, f in enumerate(new_shape.Faces):
        candidats.append({'nom': f'Face{i+1}',
                          'empreinte': _empreinte_subshape_fake_face(f, i)})
    for i, e in enumerate(new_shape.Edges):
        candidats.append({'nom': f'Edge{i+1}',
                          'empreinte': _empreinte_arete(e)})
    for i, v in enumerate(new_shape.Vertexes):
        p = v.Point
        candidats.append({'nom': f'Vertex{i+1}', 'empreinte': {
            'type': 'Vertex',
            'com': (round(p.x,3), round(p.y,3), round(p.z,3))}})

    nouveaux_groupes = []
    for grp in refs_groupes:
        base_feat = grp['base_feat']
        nouveaux_noms = []
        for ref_snap in grp['refs']:
            emp_ref = ref_snap.get('empreinte')
            if emp_ref is None:
                nouveaux_noms.append(ref_snap['nom'])
                continue
            meilleur_score, meilleur_nom = -1, None
            for cand in candidats:
                score, ok = _empreinte_subshape_compatible(
                    emp_ref, cand['empreinte'])
                if ok and score > meilleur_score:
                    meilleur_score, meilleur_nom = score, cand['nom']
            if meilleur_nom:
                print(f"[ORing TNP]   {ref_snap['nom']} → {meilleur_nom} "
                      f"(score={meilleur_score})")
                nouveaux_noms.append(meilleur_nom)
            else:
                print(f"[ORing TNP]   {ref_snap['nom']} → pas de correspondance")
                nouveaux_noms.append(ref_snap['nom'])
        nouveaux_groupes.append((base_feat, nouveaux_noms))

    try:
        if prop_name == 'Base':
            bf, noms = nouveaux_groupes[0]
            feat.Base = (bf, noms)
        elif prop_name in ('Support', 'AttachmentSupport', 'MapPathParameter'):
            if len(nouveaux_groupes) == 1:
                setattr(feat, prop_name, nouveaux_groupes[0])
            else:
                setattr(feat, prop_name, nouveaux_groupes)
        feat.touch()
        return True
    except Exception as _e:
        print(f"[ORing TNP]   setattr({prop_name}) : {_e}")
        return False


def _empreinte_subshape_fake_face(face, idx):
    """Empreinte géométrique pour une face."""
    try:
        com = face.CenterOfMass
        try:
            norm = face.normalAt(0, 0)
            normal = (round(norm.x, 3), round(norm.y, 3), round(norm.z, 3))
        except Exception:
            normal = None
        return {
            'type':   'Face',
            'ref':    f'Face{idx+1}',
            'com':    (round(com.x, 3), round(com.y, 3), round(com.z, 3)),
            'area':   round(face.Area, 3),
            'normal': normal,
        }
    except Exception:
        return None


def _restaurer_habillage(doc, body, suspendues):
    """
    Restaure toutes les features protégées par _suspendre_habillage.

    Modes :
      - 'suppressed' : habillage (Chamfer, Fillet, Draft, Hole…)
        → Suppressed=False + recompute, fallback remapping géométrique.
      - 'detached' : datum / sketch détaché (MapMode)
        → MapMode restauré + recompute, fallback remapping Support.
    """
    if not suspendues:
        return []

    _encore_erreur = []

    for snap in suspendues:
        feat           = snap['feature']
        mode           = snap.get('mode', 'suppressed')
        deja_suspendue = snap.get('deja_suspendue', False)

        if deja_suspendue:
            continue

        # ── MODE 'suppressed' : habillage ──────────────────────────────────
        if mode == 'suppressed':
            try:
                feat.Suppressed = False
                feat.touch()
                doc.recompute()
            except Exception as _e:
                print(f"[ORing TNP] Réactivation '{feat.Label}' : {_e}")
                _encore_erreur.append(feat.Label)
                continue

            if not _est_en_erreur(feat):
                print(f"[ORing TNP] ✓ '{feat.Label}' réactivé (TNP fix natif)")
                continue

            print(f"[ORing TNP] '{feat.Label}' toujours en erreur "
                  f"→ remapping géométrique")
            refs_groupes = snap.get('refs_groupes', [])
            _ok = False
            for grp in refs_groupes:
                base_feat = grp.get('base_feat')
                new_shape = getattr(base_feat, 'Shape', None)
                if new_shape is None:
                    continue
                _ok = _remappe_refs(feat, [grp], grp.get('prop', 'Base'),
                                    new_shape)
                if _ok:
                    feat.touch()
                    doc.recompute()
                    break

            if _ok and not _est_en_erreur(feat):
                print(f"[ORing TNP] ✓ '{feat.Label}' restauré par remapping")
            else:
                print(f"[ORing TNP] ⚠ '{feat.Label}' non récupéré → resuspendu")
                try:
                    feat.Suppressed = True
                    doc.recompute()
                except Exception:
                    pass
                _encore_erreur.append(feat.Label)

        # ── MODE 'detached' : datum / sketch ───────────────────────────────
        elif mode == 'detached':
            map_mode_old = snap.get('map_mode_old', 'FlatFace')
            try:
                feat.MapMode = map_mode_old
                feat.touch()
                doc.recompute()
            except Exception as _e:
                print(f"[ORing TNP] Réattachement '{feat.Label}' : {_e}")
                _encore_erreur.append(feat.Label)
                continue

            if not _est_en_erreur(feat):
                print(f"[ORing TNP] ✓ '{feat.Label}' réattaché "
                      f"(MapMode={map_mode_old})")
                continue

            print(f"[ORing TNP] '{feat.Label}' toujours en erreur "
                  f"→ remapping Support")
            refs_groupes = snap.get('refs_groupes', [])
            _ok = False
            for grp in refs_groupes:
                base_feat = grp.get('base_feat')
                new_shape = getattr(base_feat, 'Shape', None)
                if new_shape is None:
                    continue
                prop_used = grp.get('prop', 'Support')
                _ok = _remappe_refs(feat, [grp], prop_used, new_shape)
                if _ok:
                    feat.MapMode = map_mode_old
                    feat.touch()
                    doc.recompute()
                    break

            if _ok and not _est_en_erreur(feat):
                print(f"[ORing TNP] ✓ '{feat.Label}' restauré par remapping")
            else:
                print(f"[ORing TNP] ⚠ '{feat.Label}' non récupéré "
                      f"(MapMode=Deactivated)")
                try:
                    feat.MapMode = 'Deactivated'
                    doc.recompute()
                except Exception:
                    pass
                _encore_erreur.append(feat.Label)

    return _encore_erreur


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

        # ── Suspension TNP : suspendre les features d'habillage AVANT recompute ──
        # Cela évite qu'elles ne plantent sur des arêtes invalides pendant
        # la modification de gorge. Elles seront réactivées après, sur
        # une géométrie stable.
        _tnp_suspendues = _suspendre_habillage(body_gorge_obj) if body_gorge_obj else []
        if _tnp_suspendues:
            _silence_propertlylinks()
            doc.recompute()  # Valider la suspension avant de modifier la gorge
            _restore_propertylinks()

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
            """Contraintes non-radiales sûres (filets, dépouille) : applicables
            avant les radiales car elles ne dépendent pas des rayons.
            NOTE : demiLargeurGorge N'EST PAS appliquée ici — elle est appliquée
            dans _set_contrainte_largeur() APRÈS les radiales, car pour de grands
            changements de diamètre (ex. Ø60→Ø30) la nouvelle largeur est
            incompatible avec les anciens rayons et le solveur la rejette.
            """
            _set_contrainte(sketch_gorge, 'FilletHautGorge',  f_haut)
            _set_contrainte(sketch_gorge, 'FilletFondGorge',  f_fond)
            _set_contrainte(sketch_gorge, 'depouille',        depouille_deg, en_degres=True)

        def _set_contrainte_largeur():
            """Applique demiLargeurGorge (et demiLargeur pour gorge arbre) APRÈS
            que les rayons sont stables. Le solveur accepte alors la nouvelle
            largeur sans conflit topologique."""
            for _idx, _c in enumerate(sketch_gorge.Constraints):
                if _c.Name.startswith('demiLargeur') and not _c.Name.startswith('demiLargeurG'):
                    try:
                        import FreeCAD as _FC
                        sketch_gorge.setDatum(_idx, _FC.Units.Quantity(f'{round(b2 * 0.5, 4)} mm'))
                    except Exception as _e:
                        print(f"[ORing modif] setDatum 'demiLargeur' EXCEPTION : {_e}")
                    break
            _set_contrainte(sketch_gorge, 'demiLargeurGorge', b2)

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
                  "→ reset ordonné par paliers")
            # Pour les grands changements, appliquer dans l'ordre qui respecte
            # l'invariant du solveur à chaque étape :
            #   gorge ARBRE   : RayonGorge < RayonArbre < RayonAlesage
            #   gorge ALÉSAGE : RayonArbre < RayonAlesage < RayonGorge
            #
            # RÉDUCTION (nouvelle < ancienne) :
            #   ARBRE   → RayonGorge d'abord (intérieur), puis RayonArbre, puis RayonAlesage
            #   ALÉSAGE → RayonArbre d'abord, puis RayonAlesage, puis RayonGorge
            # AGRANDISSEMENT :
            #   ARBRE   → RayonAlesage d'abord (extérieur), puis RayonArbre, puis RayonGorge
            #   ALÉSAGE → RayonGorge d'abord, puis RayonAlesage, puis RayonArbre
            #
            # On détermine le sens sur la valeur la plus représentative (RayonArbre/Alesage)
            if position == 'arbre':
                _grossit_reset = r_arbre > r_arbre_old
                if _grossit_reset:
                    _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                    _recompute_intermediaire()
                    _set_contrainte_largeur()
                else:
                    _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                    _recompute_intermediaire()
                    _set_contrainte_largeur()
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                    _recompute_intermediaire()
            else:
                _grossit_reset = r_alesage > r_alesage_old
                if _grossit_reset:
                    _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                    _recompute_intermediaire()
                    _set_contrainte_largeur()
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                    _recompute_intermediaire()
                else:
                    _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                    _recompute_intermediaire()
                    _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                    _recompute_intermediaire()
                    _set_contrainte_largeur()
                    _recompute_intermediaire()
            # Relire les valeurs après le reset (les radiales sont déjà aux cibles)
            r_arbre_old   = _lire_rayon_courant('RayonArbre')
            r_gorge_old   = _lire_rayon_courant('RayonGorge')
            r_alesage_old = _lire_rayon_courant('RayonAlesage')

        # ── Contraintes neutres (ordre indifférent) ───────────────────────────
        _set_contraintes_neutres()
        sketch_gorge.solve()
        # Après un reset incoherent, les radiales ET la largeur sont déjà
        # appliquées dans le reset. On applique seulement les neutres ici.
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

        # Si le reset incoherent a déjà mis les rayons aux cibles,
        # la séquence radiale ci-dessous sera un no-op (toutes les valeurs
        # sont déjà égales aux cibles). On la garde pour valider l'état final.
        if position == 'arbre':
            grossit = r_arbre > r_arbre_old
            if grossit:
                # Étape 1 : élargir l'alésage (borne extérieure)
                _set_contrainte(sketch_gorge, 'RayonAlesage', r_alesage)
                _recompute_intermediaire()
                # Étape 2 : élargir l'arbre
                _set_contrainte(sketch_gorge, 'RayonArbre',   r_arbre)
                _recompute_intermediaire()
                # Étape 3 : reculer le fond de gorge + largeur
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                _set_contrainte_largeur()
            else:
                # Étape 1 : avancer le fond de gorge + largeur
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                _set_contrainte_largeur()
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
                # Étape 1 : avancer le fond de gorge vers l'extérieur + largeur
                print("[ORing modif GORGE] étape 1/3 : RayonGorge")
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                _set_contrainte_largeur()
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
                # Étape 3 : rapprocher le fond de gorge + largeur
                print("[ORing modif GORGE] étape 3/3 : RayonGorge")
                _set_contrainte(sketch_gorge, 'RayonGorge',   r_gorge)
                _recompute_intermediaire()
                _set_contrainte_largeur()

        # ── Recompute final ───────────────────────────────────────────────────
        # La largeur (demiLargeurGorge) a déjà été appliquée dans la séquence
        # ordonnée ci-dessus, après que les rayons sont stables.
        import time as _t
        _t0_recompute = _t.time()
        sketch_gorge.solve()
        sketch_gorge.touch()
        for feat in features_liees:
            feat.touch()
        if body_gorge_obj is not None:
            body_gorge_obj.touch()
        _silence_propertlylinks()
        doc.recompute()
        _restore_propertylinks()
        print(f"[ORing modif GORGE]   recompute() effectué  "
              f"(sens={'agrandissement' if (grossit if position=='arbre' else grossit) else 'rétrécissement'})  "
              f"durée={_t.time()-_t0_recompute:.2f}s")
        # Rafraîchir la vue après le recompute gorge.
        try:
            import FreeCADGui as _Gui
            _Gui.updateGui()
        except Exception:
            pass

        # ── TNP recovery : remapping géométrique des arêtes d'habillage ────────
        # Stratégie :
        #   1. Passe 1 : simple touch + recompute (FreeCAD TNP fix auto)
        #   2. Passe 2 : si encore en erreur → remapping géométrique par empreinte
        #      (centre de masse, longueur, rayon) comparée au snapshot pré-recompute
        if body_gorge_obj is not None:
            # Réactivation des features suspendues sur géométrie stable
            # + fallback remapping géométrique si la réactivation échoue
            _encore_erreur = _restaurer_habillage(
                doc, body_gorge_obj, _tnp_suspendues)

            if _encore_erreur:
                print(f"[ORing TNP] ⚠ {len(_encore_erreur)} feature(s) non récupérée(s) "
                      f"(resuspendues — correction manuelle requise) : "
                      f"{_encore_erreur}")
                meta_existante['_tnp_erreurs'] = _encore_erreur
            else:
                if _tnp_suspendues:
                    print(f"[ORing TNP] ✓ {len(_tnp_suspendues)} feature(s) "
                          f"réactivée(s) avec succès")
                meta_existante.pop('_tnp_erreurs', None)

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
            # Rafraîchir la vue après mise à jour du tore.
            try:
                import FreeCADGui as _Gui
                _Gui.updateGui()
            except Exception:
                pass

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
            # Rafraîchir la vue après recréation du tore.
            try:
                import FreeCADGui as _Gui
                _Gui.updateGui()
            except Exception:
                pass
        except Exception as e_rec:
            print(f"[ORing modif] AVERT : recréation body oring échouée : {e_rec}")
            body_oring_new = None

    # Couleur appliquée par _on_appliquer après le dernier recompute du flux.

    # Restaurer le niveau de log PropertyLinks (silencié en début de fonction)
    _restore_propertylinks()


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

def _fermer_taches_actives():
    """
    Détecte uniquement les tâches de mesure (Measurement) qui provoquent
    un plantage connu à l'ouverture de la macro ORing, et propose de les
    fermer. Les autres tâches (Sketch en édition, etc.) sont ignorées.

    Retourne True si la voie est libre, False si l'utilisateur refuse.
    """
    # Mots-clés identifiant les tâches de mesure FreeCAD
    _MOTS_MESURE = ('measure', 'Measure', 'measurement', 'Measurement',
                    'MeasureDistance', 'MeasureAngle', 'MeasureRadius',
                    'MeasureArea', 'MeasureLinear', 'CmdMeasure')
    try:
        import FreeCADGui as _Gui
        ctrl = getattr(_Gui, 'Control', None)
        if ctrl is None:
            return True
        active = ctrl.activeDialog()
        if active is None:
            return True
        # Vérifier si c'est une tâche de mesure
        nom = type(active).__name__
        if not any(m in nom for m in _MOTS_MESURE):
            return True   # Autre type de tâche → laisser passer
        # C'est une tâche de mesure → proposer de la fermer
        reponse = QtWidgets.QMessageBox.question(
            None,
            "ORing — Mesure active",
            "Un outil de mesure FreeCAD est ouvert.\n\n"
            "Cela provoquerait un plantage à l'ouverture de la macro.\n\n"
            "Voulez-vous fermer l'outil de mesure et continuer ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes
        )
        if reponse != QtWidgets.QMessageBox.Yes:
            return False
        try:
            ctrl.closeDialog()
            QtWidgets.QApplication.processEvents()
        except Exception as _e:
            print(f"[ORing] Fermeture mesure : {_e}")
        return True
    except Exception as _e:
        print(f"[ORing] Verification taches : {_e}")
        return True   # En cas d'erreur, toujours laisser passer


# =============================================================================
# DIALOGUE ERREUR PRÉREQUIS
# =============================================================================

def _ouvrir_guide_prerequis(parent=None):
    """
    Ouvre le guide de démarrage en mode autonome (avant le dialogue principal).
    Réplique de DialogueORing._ouvrir_aide(), sans dépendance à self.
    """
    try:
        from .prerequis_helper import PrerequisHelper
        from .helper_i18n import make_tr
        from . import i18n as _i18n_mod
        import json as _json
        import os as _os

        lang = _i18n_mod.get_lang()
        _locales = _os.path.normpath(
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          '..', 'locales')
        )
        translations = {}
        for candidate in (lang, 'en'):
            path = _os.path.join(_locales, f'helper_{candidate}.json')
            if _os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as _f:
                    translations.update(_json.load(_f))
                break

        tr_helper = make_tr(translations)
        dlg = PrerequisHelper(tr=tr_helper, parent=parent)
        dlg.exec_()

    except Exception as _e:
        print(f"[ORing] _ouvrir_guide_prerequis ERREUR : {_e}")
        import traceback; traceback.print_exc()


class _DialoguePrerequisErreur(QtWidgets.QDialog):
    """
    Fenêtre d'erreur affichée quand le document ne satisfait pas les
    prérequis de la macro (LCS + paramètre nommé).

    Internationalisée via tr(). Propose un bouton « Ouvrir le guide »
    qui lance PrerequisHelper avant de fermer la fenêtre d'erreur.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ouvrir_guide = False
        self.setWindowTitle(tr("ORing — Prerequisites not met"))
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        self._construire()

    def _construire(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 16)

        # ── Ligne icône + titre ───────────────────────────────────────────
        titre_row = QtWidgets.QHBoxLayout()
        icone = QtWidgets.QLabel()
        icone.setPixmap(
            self.style()
            .standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning)
            .pixmap(32, 32)
        )
        titre_row.addWidget(icone)
        titre_lbl = QtWidgets.QLabel(
            f"<b>{tr('ORing — Prerequisites not met')}</b>"
        )
        titre_lbl.setTextFormat(QtCore.Qt.RichText)
        titre_row.addWidget(titre_lbl, 1)
        layout.addLayout(titre_row)

        # ── Séparateur ────────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addWidget(sep)

        # ── Corps du message ──────────────────────────────────────────────
        msg = QtWidgets.QLabel(_MSG_PREREQUIS)
        msg.setWordWrap(True)
        msg.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(msg)

        layout.addStretch()

        # ── Boutons ───────────────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        btn_guide = QtWidgets.QPushButton(tr("? Open guide"))
        btn_guide.clicked.connect(self._on_guide)
        btn_row.addWidget(btn_guide)

        btn_fermer = QtWidgets.QPushButton(tr("Close"))
        btn_fermer.setDefault(True)
        btn_fermer.clicked.connect(self.accept)
        btn_row.addWidget(btn_fermer)

        layout.addLayout(btn_row)
        self.setMinimumWidth(480)

    def _on_guide(self):
        """Mémorise la demande d'ouverture du guide et ferme ce dialogue."""
        self.ouvrir_guide = True
        self.accept()


def lancer_dialogue():
    """
    Point d'entrée de la macro.

    Étape 1a : vérifie qu'aucune tâche FreeCAD n'est ouverte (measurement,
    sketch, etc.) — une tâche active provoque un plantage à l'ouverture.
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

    # ── Étape 1a : vérifier qu'aucune tâche n'est active ─────────────────────
    if not _fermer_taches_actives():
        return None

    # ── Étape 1b : validation au démarrage ───────────────────────────────────
    try:
        doc = get_document_actif()
    except RuntimeError:
        # Aucun document ouvert — on laisse DialogueORing gérer ce cas
        doc = None

    if doc is not None and not doc_a_bodies_valides(doc):
        _dlg_err = _DialoguePrerequisErreur(None)
        _dlg_err.exec_()
        if _dlg_err.ouvrir_guide:
            _ouvrir_guide_prerequis(parent=None)
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

    # ── Dialogue de sélection de langue (mode MANUEL) ────────────────────
    # Appelé ici car Gui.getMainWindow() est disponible et le dialogue
    # apparaît correctement au premier plan.
    try:
        from .i18n import (check_language_mode, _afficher_dialogue_langue,
                           _sauvegarder_langue, setup as _i18n_setup_dlg,
                           _ORING_DIR as _oring_dir_lang, get_lang)
        if _oring_dir_lang:
            _mode_lang = check_language_mode(_oring_dir_lang)
            if _mode_lang == 'manual':
                _mw = Gui.getMainWindow() if FREECAD_DISPONIBLE else None
                _lang_actuel = get_lang()
                _lang_choisi = _afficher_dialogue_langue(
                    _oring_dir_lang, _lang_actuel, parent=_mw
                )
                if _lang_choisi != _lang_actuel:
                    _sauvegarder_langue(_oring_dir_lang, _lang_choisi)
                    _i18n_setup_dlg(_lang_choisi)
                    print(f"[ORing] Langue changée : {_lang_actuel} → {_lang_choisi}")
    except Exception as _e_lang_dlg:
        print(f"[ORing] AVERT sélection langue : {_e_lang_dlg}")

    # ── Détecter si un joint ORing est sélectionné avant le lancement ────
    part_selectionne = None
    try:
        from .metadata import lister_parts_oring
        if doc is not None:
            parts_oring = {p.Name: p for p in lister_parts_oring(doc)}
            if parts_oring:
                for sel_obj in Gui.Selection.getSelection():
                    # Correspondance directe : l'objet sélectionné est un Part ORing
                    if sel_obj.Name in parts_oring:
                        part_selectionne = parts_oring[sel_obj.Name]
                        break
                    # Correspondance indirecte : l'objet est à l'intérieur d'un Part ORing
                    for part in parts_oring.values():
                        try:
                            if sel_obj in part.OutListRecursive:
                                part_selectionne = part
                                break
                        except Exception:
                            pass
                    if part_selectionne:
                        break
    except Exception as _e_sel:
        print(f"[ORing] Détection sélection AVERT : {_e_sel}")

    if part_selectionne:
        print(f"[ORing] Joint pré-sélectionné détecté : {part_selectionne.Label}")

    # ── Créer et afficher le dialogue ─────────────────────────────────────
    dlg = DialogueORing(parent=Gui.getMainWindow())

    if part_selectionne is not None:
        # Ouvrir directement sur l'onglet 2 avec les paramètres du joint
        QtCore.QTimer.singleShot(
            0, lambda p=part_selectionne: dlg._ouvrir_depuis_selection(p)
        )
    else:
        # Comportement normal : onglet 3 si dérive, sinon onglet 1
        dlg._onglet_initial()

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