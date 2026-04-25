# -*- coding: utf-8 -*-
"""
PrerequisHelper — Dialogue d'aide multi-pages pour les prérequis ORing.
Respecte le thème Qt (clair/sombre) — aucune couleur de fond ni de texte
codée en dur sur les widgets courants. Seuls les éléments d'accent
(badges, points de navigation, barres tip) gardent leurs couleurs.
"""

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    _PYSIDE = 2
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    _PYSIDE = 6


# ---------------------------------------------------------------------------
# Détection thème
# ---------------------------------------------------------------------------
def _is_dark(widget=None):
    """True si le thème courant est sombre (luminosité fond < 128)."""
    try:
        app = QtWidgets.QApplication.instance()
        if app:
            bg = app.palette().color(QtGui.QPalette.Window)
            return bg.lightness() < 128
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Accents par page — deux palettes (clair / sombre)
# ---------------------------------------------------------------------------
_ACCENTS_LIGHT = [
    {"badge_bg": "#E6F1FB", "badge_fg": "#185FA5",
     "dot": "#378ADD", "accent": "#378ADD", "sep": "#e0e0e0"},
    {"badge_bg": "#E1F5EE", "badge_fg": "#0F6E56",
     "dot": "#1D9E75", "accent": "#1D9E75", "sep": "#e0e0e0"},
    {"badge_bg": "#FAEEDA", "badge_fg": "#854F0B",
     "dot": "#BA7517", "accent": "#BA7517", "sep": "#e0e0e0"},
    {"badge_bg": "#FAECE7", "badge_fg": "#993C1D",
     "dot": "#D85A30", "accent": "#D85A30", "sep": "#e0e0e0"},
    {"badge_bg": "#EEEDFE", "badge_fg": "#3C3489",
     "dot": "#7F77DD", "accent": "#7F77DD", "sep": "#e0e0e0"},
]
_ACCENTS_DARK = [
    {"badge_bg": "#1A2E40", "badge_fg": "#7BB8E8",
     "dot": "#7BB8E8", "accent": "#7BB8E8", "sep": "#444444"},
    {"badge_bg": "#0E2A1E", "badge_fg": "#5DC9A0",
     "dot": "#5DC9A0", "accent": "#5DC9A0", "sep": "#444444"},
    {"badge_bg": "#2E2010", "badge_fg": "#E8A94A",
     "dot": "#E8A94A", "accent": "#E8A94A", "sep": "#444444"},
    {"badge_bg": "#2E1410", "badge_fg": "#E87B5A",
     "dot": "#E87B5A", "accent": "#E87B5A", "sep": "#444444"},
    {"badge_bg": "#1E1A40", "badge_fg": "#A09AE8",
     "dot": "#A09AE8", "accent": "#A09AE8", "sep": "#444444"},
]

_BADGE_IMP_LIGHT = {
    "critique" : "background:#FAECE7; color:#993C1D;",
    "important": "background:#FAEEDA; color:#854F0B;",
    "utile"    : "background:#E1F5EE; color:#0F6E56;",
}
_BADGE_IMP_DARK = {
    "critique" : "background:#3A1810; color:#E87B5A;",
    "important": "background:#2E2010; color:#E8A94A;",
    "utile"    : "background:#0E2A1E; color:#5DC9A0;",
}


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------
class PrerequisHelper(QtWidgets.QDialog):

    def __init__(self, tr, parent=None):
        super().__init__(parent)
        self._tr          = tr
        self._cur         = 0
        self._pages_data  = self._load_pages()
        self._dot_buttons = []
        self._dark        = _is_dark()
        self._setup_ui()
        self._render()

    # ------------------------------------------------------------------ data
    def _load_pages(self):
        pages = []
        i = 0
        while True:
            key_title = f"helper.pages.{i}.title"
            title = self._tr(key_title)
            if title == key_title:
                break
            page = {
                "badge"   : self._tr(f"helper.pages.{i}.badge"),
                "title"   : title,
                "subtitle": self._tr(f"helper.pages.{i}.subtitle"),
                "type"    : self._tr(f"helper.pages.{i}.type"),
                "idx"     : i,
            }
            items = []
            j = 0
            while True:
                k = f"helper.pages.{i}.items.{j}"
                v = self._tr(k)
                if v == k: break
                items.append(v); j += 1
            if items: page["items"] = items

            headers = []
            j = 0
            while True:
                k = f"helper.pages.{i}.headers.{j}"
                v = self._tr(k)
                if v == k: break
                headers.append(v); j += 1
            if headers: page["headers"] = headers

            rows = []
            r = 0
            while True:
                row = []; c = 0
                while True:
                    k = f"helper.pages.{i}.rows.{r}.{c}"
                    v = self._tr(k)
                    if v == k: break
                    row.append({"text": v.split("|",1)[0],
                                "style": v.split("|",1)[1]}
                               if "|" in v else v)
                    c += 1
                if not row: break
                rows.append(row); r += 1
            if rows: page["rows"] = rows

            tip_key = f"helper.pages.{i}.tip"
            tip_val = self._tr(tip_key)
            if tip_val != tip_key: page["tip"] = tip_val

            pages.append(page); i += 1
        return pages

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        dark = self._dark
        # Lire les couleurs réelles de la palette (fonctionne sur tous les thèmes)
        app = QtWidgets.QApplication.instance()
        pal = app.palette() if app else self.palette()
        _win_bg  = pal.color(QtGui.QPalette.Window).name()       # fond fenêtre
        _base_bg = pal.color(QtGui.QPalette.Base).name()         # fond widgets
        _win_fg  = pal.color(QtGui.QPalette.WindowText).name()   # texte
        prog_bg  = pal.color(QtGui.QPalette.Mid).name()
        # Séparateur : légèrement plus clair/foncé que le fond
        _win_color = pal.color(QtGui.QPalette.Window)
        if dark:
            prog_sep = _win_color.lighter(140).name()
        else:
            prog_sep = _win_color.darker(115).name()

        self.setWindowTitle(self._tr("helper.title"))
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(0)

        # En-tête — pas de color forcée, hérite de la palette
        hdr = QtWidgets.QHBoxLayout()
        lc  = QtWidgets.QVBoxLayout(); lc.setSpacing(2)

        lbl_h = QtWidgets.QLabel(self._tr("helper.title"))
        lbl_h.setStyleSheet("font-size:13px; font-weight:bold;")   # pas de color

        lbl_s = QtWidgets.QLabel(self._tr("helper.app_subtitle"))
        lbl_s.setStyleSheet("font-size:11px;")                      # pas de color

        lc.addWidget(lbl_h); lc.addWidget(lbl_s)

        self._lbl_counter = QtWidgets.QLabel()
        self._lbl_counter.setStyleSheet("font-size:11px;")
        align_r = (QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                   if _PYSIDE == 2
                   else QtCore.Qt.AlignmentFlag.AlignRight |
                        QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._lbl_counter.setAlignment(align_r)

        hdr.addLayout(lc); hdr.addStretch(); hdr.addWidget(self._lbl_counter)
        root.addLayout(hdr)
        root.addSpacing(10)

        # Barre de progression
        self._progress = QtWidgets.QProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, len(self._pages_data))
        self._progress.setStyleSheet(
            f"QProgressBar{{border:none;background:{prog_bg};border-radius:2px;}}"
            "QProgressBar::chunk{background:#378ADD;border-radius:2px;}"
        )
        root.addWidget(self._progress); root.addSpacing(12)

        # Stack — fond palette + enfants transparents
        self._stack = QtWidgets.QStackedWidget()
        # Stocker la couleur de fond pour les pages
        self._win_bg  = _win_bg
        self._win_pal = pal   # palette complète pour les widgets enfants

        # Utiliser un QFrame pour la bordure — QStackedWidget sans stylesheet
        # pour éviter les cascades de fond blanc indésirables
        _frame = QtWidgets.QFrame()
        _frame.setStyleSheet(
            f"QFrame#stackFrame{{border:1px solid {prog_sep};border-radius:8px;}}"
        )
        _frame.setObjectName("stackFrame")
        _fl = QtWidgets.QVBoxLayout(_frame)
        _fl.setContentsMargins(0, 0, 0, 0)

        self._stack = QtWidgets.QStackedWidget()
        # Aucun stylesheet sur le stack — fond géré par QPalette sur chaque page
        _fl.addWidget(self._stack)

        for page_data in self._pages_data:
            self._stack.addWidget(self._build_page_widget(page_data))
        root.addWidget(_frame, 1); root.addSpacing(12)

        # Navigation
        nav = QtWidgets.QHBoxLayout()
        self._btn_prev = QtWidgets.QPushButton(self._tr("helper.prev"))
        self._btn_prev.setFixedWidth(120)
        self._btn_prev.clicked.connect(lambda: self._navigate(-1))

        dot_row = QtWidgets.QHBoxLayout(); dot_row.setSpacing(6)
        for i in range(len(self._pages_data)):
            dot = QtWidgets.QPushButton()
            dot.setFixedSize(8, 8)
            dot.clicked.connect(lambda *a, idx=i: self._go_to(idx))
            dot_row.addWidget(dot)
            self._dot_buttons.append(dot)

        self._btn_next = QtWidgets.QPushButton(self._tr("helper.next"))
        self._btn_next.setFixedWidth(120)
        self._btn_next.clicked.connect(lambda: self._navigate(1))

        nav.addWidget(self._btn_prev)
        nav.addStretch()
        nav.addLayout(dot_row)
        nav.addStretch()
        nav.addWidget(self._btn_next)
        root.addLayout(nav); root.addSpacing(8)

        # Fermer
        close_row = QtWidgets.QHBoxLayout()
        btn_close = QtWidgets.QPushButton(self._tr("helper.close"))
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        close_row.addStretch(); close_row.addWidget(btn_close)
        root.addLayout(close_row)

    # ---------------------------------------------------------------- pages
    def _build_page_widget(self, page_data):
        dark = self._dark
        idx  = page_data["idx"] % len(_ACCENTS_LIGHT)
        acc  = _ACCENTS_DARK[idx] if dark else _ACCENTS_LIGHT[idx]

        widget = QtWidgets.QWidget()
        # Fond via QPalette — indépendant du système CSS, fiable sur tous thèmes
        _p = QtGui.QPalette(self._win_pal)
        _win_color = self._win_pal.color(QtGui.QPalette.Window)
        _p.setColor(QtGui.QPalette.Window,      _win_color)
        _p.setColor(QtGui.QPalette.Base,        _win_color)
        _p.setColor(QtGui.QPalette.AlternateBase, _win_color)
        widget.setPalette(_p)
        widget.setAutoFillBackground(True)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(0)

        # Badge coloré (accent) — fond + texte explicites intentionnels
        badge = QtWidgets.QLabel(page_data["badge"])
        badge.setStyleSheet(
            f"font-size:11px; font-weight:500; padding:2px 10px;"
            f"border-radius:10px;"
            f"background:{acc['badge_bg']}; color:{acc['badge_fg']};"
        )
        badge.setFixedHeight(20)

        # Titres — pas de color, héritage palette
        pg_title = QtWidgets.QLabel(page_data["title"])
        pg_title.setStyleSheet("font-size:14px; font-weight:bold;")
        pg_title.setWordWrap(True)

        pg_sub = QtWidgets.QLabel(page_data["subtitle"])
        pg_sub.setStyleSheet("font-size:11px;")
        pg_sub.setWordWrap(True)

        layout.addWidget(badge)
        layout.addSpacing(6)
        layout.addWidget(pg_title)
        layout.addWidget(pg_sub)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet(f"color:{acc['sep']};")
        layout.addSpacing(8); layout.addWidget(sep); layout.addSpacing(8)

        ptype = page_data.get("type", "rows")
        if ptype == "checklist":
            self._fill_checklist(layout, page_data, acc)
        elif ptype == "rows":
            self._fill_rows(layout, page_data, acc)
        elif ptype == "table":
            self._fill_table(layout, page_data, dark)

        if "tip" in page_data:
            layout.addSpacing(10)
            layout.addWidget(self._make_tip(page_data["tip"], acc["accent"], dark))

        return widget

    def _fill_checklist(self, layout, page_data, acc):
        """Checklist = bullets colorés (pas de cases à cocher)."""
        self._fill_rows(layout, page_data, acc)

    def _fill_rows(self, layout, page_data, acc):
        align_top = (QtCore.Qt.AlignTop if _PYSIDE == 2
                     else QtCore.Qt.AlignmentFlag.AlignTop)
        items = page_data.get("items", [])
        for i, text in enumerate(items):
            row = QtWidgets.QHBoxLayout()
            row.setAlignment(align_top)
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color:{acc['dot']}; font-size:8px; margin-top:4px;")
            dot.setFixedWidth(14)
            dot.setAlignment(align_top)
            lbl = QtWidgets.QLabel(text)
            # Pas de color — hérite de la palette
            lbl.setStyleSheet("font-size:13px; background-color:transparent;")
            lbl.setWordWrap(True)
            lbl.setTextFormat(QtCore.Qt.RichText)
            row.addWidget(dot); row.addWidget(lbl, 1)
            layout.addLayout(row)
            if i < len(items) - 1:
                sep = QtWidgets.QFrame()
                sep.setFrameShape(QtWidgets.QFrame.HLine)
                # Séparateur subtil relatif au fond
                sep_c = acc["sep"]
                sep.setStyleSheet(
                    f"QFrame{{border:none; background-color:{sep_c};}}"
                )
                sep.setFixedHeight(1)
                layout.addSpacing(3)
                layout.addWidget(sep)
                layout.addSpacing(3)

    def _fill_table(self, layout, page_data, dark):
        headers = page_data.get("headers", [])
        rows    = page_data.get("rows",    [])
        if not headers or not rows: return

        badge_imp = _BADGE_IMP_DARK if dark else _BADGE_IMP_LIGHT

        table = QtWidgets.QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        # Appliquer la même palette que la page parente
        _tp = QtGui.QPalette(self._win_pal)
        _wc = self._win_pal.color(QtGui.QPalette.Window)
        _tp.setColor(QtGui.QPalette.Base,        _wc)
        _tp.setColor(QtGui.QPalette.AlternateBase, _wc)
        table.setPalette(_tp)
        table.setAutoFillBackground(True)
        table.setStyleSheet("font-size:12px;")
        hh = table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(
            0, (QtWidgets.QHeaderView.Stretch if _PYSIDE == 2
                else QtWidgets.QHeaderView.ResizeMode.Stretch)
        )
        for r_idx, row_data in enumerate(rows):
            table.setRowHeight(r_idx, 32)
            for c_idx, cell in enumerate(row_data):
                if isinstance(cell, dict):
                    lbl = QtWidgets.QLabel(cell.get("text", ""))
                    skey = cell.get("style", "utile").lower()
                    lbl.setStyleSheet(
                        f"font-size:11px; font-weight:500;"
                        f"padding:2px 8px; border-radius:10px;"
                        f"{badge_imp.get(skey, '')} margin:4px;"
                    )
                    lbl.setAlignment(QtCore.Qt.AlignCenter)
                    table.setCellWidget(r_idx, c_idx, lbl)
                else:
                    item = QtWidgets.QTableWidgetItem(str(cell))
                    item.setTextAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
                    table.setItem(r_idx, c_idx, item)
        table.resizeColumnsToContents()

        # Ajuster la hauteur pour éviter la scrollbar verticale
        header_h = table.horizontalHeader().height()
        rows_h   = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(header_h + rows_h + 4)
        table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        layout.addWidget(table)

    def _make_tip(self, text, accent, dark):
        """
        Rendu identique aux items normaux : aucun fond, barre verticale
        colorée à gauche. Hérite exactement du même rendu que les autres lignes.
        """
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(8)

        # Barre colorée verticale (3 px)
        bar = QtWidgets.QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background-color:{accent}; border:none;")
        row.addWidget(bar)

        # Label — même style transparent que les items rows
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet("font-size:12px; background-color:transparent;")
        lbl.setWordWrap(True)
        lbl.setTextFormat(QtCore.Qt.RichText)
        row.addWidget(lbl, 1)

        return container

    def _render(self):
        dark = self._dark
        n    = len(self._pages_data)
        self._stack.setCurrentIndex(self._cur)
        self._progress.setValue(self._cur + 1)

        tpl = self._tr("helper.page_of")
        self._lbl_counter.setText(tpl.format(cur=self._cur + 1, total=n))

        self._btn_prev.setEnabled(self._cur > 0)
        last = (self._cur == n - 1)
        self._btn_next.setEnabled(not last)
        self._btn_next.setText(
            self._tr("helper.finish") if last else self._tr("helper.next")
        )

        accents = _ACCENTS_DARK if dark else _ACCENTS_LIGHT
        inactive = "#666" if dark else "#ccc"
        for i, dot in enumerate(self._dot_buttons):
            active = (i == self._cur)
            color  = accents[i % len(accents)]["accent"] if active else inactive
            dot.setStyleSheet(
                f"border-radius:4px; background:{color}; border:none;"
            )

    def _navigate(self, direction):
        n = len(self._pages_data)
        self._cur = max(0, min(n - 1, self._cur + direction))
        self._render()

    def _go_to(self, index):
        self._cur = index
        self._render()
