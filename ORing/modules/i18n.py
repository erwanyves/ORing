# -*- coding: utf-8 -*-
"""
ORing/modules/i18n.py  —  Internationalisation.

Changer la langue : editer ORing/lang.txt  (mettre  en  ou  fr).
Si lang.txt absent → auto-détection.

Les deux fichiers JSON sont toujours chargés :
  en.json  contient : traductions vers l'anglais (fluides, termes techniques)
  fr.json  contient : traductions vers le français
"""

import os
import json
import locale as _locale_mod

# ---------------------------------------------------------------------------
# Chemin du dossier locales
# ---------------------------------------------------------------------------
_LOCALES_DIR: str = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'locales')
)

# ---------------------------------------------------------------------------
# État
# ---------------------------------------------------------------------------
_translations: dict = {}
_lang_code:    str  = 'en'
_ORING_DIR:    str  = ''

print(f"[ORing i18n] Module chargé — LOCALES_DIR = {_LOCALES_DIR}")


# ---------------------------------------------------------------------------
# Chargement JSON
# ---------------------------------------------------------------------------
def _charger(lang: str) -> None:
    """Charge locales/<lang>.json dans _translations."""
    global _translations, _lang_code
    _lang_code = lang

    path = os.path.join(_LOCALES_DIR, f'{lang}.json')

    if not os.path.isfile(path):
        print(f"[ORing i18n] {path} introuvable"
              + (" → fallback en" if lang != 'en' else " (passthrough)"))
        _translations = {}
        if lang != 'en':
            _lang_code = 'en'
        return

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _translations = {k: v for k, v in data.items()
                         if not k.startswith('_') and isinstance(v, str)}
        print(f"[ORing i18n] Langue = {lang}  "
              f"({len(_translations)} entrées — {path})")
    except Exception as e:
        print(f"[ORing i18n] ERREUR lecture {path} : {e} → fallback en")
        _translations = {}
        _lang_code = 'en'


# ---------------------------------------------------------------------------
# Détection automatique
# ---------------------------------------------------------------------------
def _detecter() -> str:
    """Retourne le code ISO 639-1 détecté."""
    _noms = {
        'french': 'fr', 'français': 'fr', 'francais': 'fr',
        'german': 'de', 'deutsch': 'de',
        'spanish': 'es', 'italian': 'it',
        'portuguese': 'pt', 'dutch': 'nl',
        'polish': 'pl', 'russian': 'ru',
    }

    def _code(raw):
        if not raw:
            return ''
        lower = raw.lower().strip()
        if lower in _noms:
            return _noms[lower]
        c = lower.replace('-', '_').split('_')[0]
        return c if (len(c) == 2 and c.isalpha()) else ''

    try:
        import FreeCAD
        raw = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/General"
        ).GetString("Language", "")
        c = _code(raw)
        if c:
            print(f"[ORing i18n] Auto FreeCAD prefs : '{raw}' → '{c}'")
            return c
    except Exception:
        pass

    try:
        from PySide2.QtCore import QLocale
        raw = QLocale.system().name()
        c = _code(raw)
        if c:
            print(f"[ORing i18n] Auto Qt : '{raw}' → '{c}'")
            return c
    except Exception:
        pass

    try:
        raw = _locale_mod.getlocale()[0] or ''
        c = _code(raw)
        if c:
            print(f"[ORing i18n] Auto locale Python : '{raw}' → '{c}'")
            return c
    except Exception:
        pass

    print("[ORing i18n] Auto → fallback 'en'")
    return 'en'


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------
def init(oring_dir: str) -> str:
    """
    Lit ORing/lang.txt et initialise la langue.
    Si absent → auto-détection.
    """
    global _ORING_DIR
    _ORING_DIR = oring_dir

    lang_file = os.path.join(oring_dir, 'lang.txt')
    print(f"[ORing i18n] lang.txt : {lang_file}  "
          f"(existe={os.path.isfile(lang_file)})")

    lang = None

    if os.path.isfile(lang_file):
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                contenu = f.read()
            print(f"[ORing i18n] lang.txt contenu : {repr(contenu)}")
            lignes = [l.strip() for l in contenu.strip().splitlines() if l.strip()]
            if lignes:
                candidate = lignes[0].lower()[:2]
                if candidate.isalpha():
                    lang = candidate
                    print(f"[ORing i18n] Langue lue dans lang.txt : '{lang}'")
                else:
                    print(f"[ORing i18n] lang.txt : code invalide → auto-détection")
            else:
                print(f"[ORing i18n] lang.txt vide → auto-détection")
        except Exception as e:
            print(f"[ORing i18n] lang.txt erreur lecture ({e}) → auto-détection")

    if lang is None:
        # Absent, vide ou illisible → auto-détection système
        lang = _detecter()
    elif lang != 'en':
        # Code lu mais .json absent → anglais
        json_path = os.path.join(_LOCALES_DIR, f'{lang}.json')
        if not os.path.isfile(json_path):
            print(f"[ORing i18n] {lang}.json introuvable → anglais forcé")
            lang = 'en' 

    _charger(lang)
    return _lang_code


# ---------------------------------------------------------------------------
# Traduction
# ---------------------------------------------------------------------------
def tr(text: str, **kwargs) -> str:
    """Traduit text. kwargs = substitutions {nom: valeur}."""
    translated = _translations.get(text, text)
    if kwargs:
        try:
            return translated.format(**kwargs)
        except Exception:
            return translated
    return translated


def get_lang() -> str:
    return _lang_code
