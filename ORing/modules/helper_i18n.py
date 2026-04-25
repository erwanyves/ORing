# -*- coding: utf-8 -*-
"""
helper_i18n.py — Intégration des clés du helper dans le système i18n global.

Ce module fournit deux utilitaires :

1. merge_helper_translations(translations: dict, lang: str) -> dict
   Fusionne les clés "helper.*" du fichier helper_<lang>.json
   dans le dict de traductions déjà chargé par le système i18n
   principal. À appeler au démarrage, après le chargement des
   locales principales.

2. make_tr(translations: dict) -> callable
   Retourne une fonction tr(key) compatible avec PrerequisHelper,
   qui navigue dans le dict par notation pointée et renvoie la
   clé elle-même si absente (fallback sans exception).

Convention de nommage des fichiers :
    locales/helper_fr.json
    locales/helper_en.json
    ...

Ces fichiers ne contiennent que la section "helper".
"""

import json
import os


def _locale_dir():
    """Chemin du répertoire locales, relatif à ce fichier."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")


def merge_helper_translations(translations: dict, lang: str) -> dict:
    """
    Fusionne les clés "helper.*" du fichier helper_<lang>.json
    dans le dict *translations* (modifié en place et renvoyé).

    Si le fichier de la langue demandée est absent, tente "fr"
    comme langue de repli, puis abandonne silencieusement.

    Parameters
    ----------
    translations : dict
        Dict de traductions déjà chargé (section racine).
    lang : str
        Code langue à deux lettres, ex. "fr", "en".

    Returns
    -------
    dict
        Le dict *translations* augmenté de la clé "helper".
    """
    for candidate in (lang, "fr"):
        path = os.path.join(_locale_dir(), f"helper_{candidate}.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                translations.update(data)
                return translations
            except (json.JSONDecodeError, OSError):
                pass
    return translations


def make_tr(translations: dict):
    """
    Fabrique et renvoie une fonction tr(key) qui :
    - accepte une clé en notation pointée (ex. "helper.pages.0.title")
    - navigue récursivement dans *translations*
    - renvoie la valeur finale (str, list, dict selon le cas)
    - renvoie la clé telle quelle si le chemin est absent

    Parameters
    ----------
    translations : dict
        Dict de traductions fusionné (résultat de merge_helper_translations).

    Returns
    -------
    callable
    """
    def tr(key: str):
        parts = key.split(".")
        node = translations
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError):
                    return key
            else:
                return key
        return node if node != translations else key

    return tr
