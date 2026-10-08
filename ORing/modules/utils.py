# Chemin : modules/utils.py
# Auteur  : Yves Guillou
# Licence : LGPL
# Date    : 03-2026
# Chemin : modules/utils.py
# -*- coding: utf-8 -*-
"""
ORing/modules/utils.py
Fonctions utilitaires partagées — lecture paramètres FreeCAD, gestion Body/LCS,
messages d'erreur, helpers géométriques.
Nécessite FreeCAD (sauf les fonctions marquées # SANS FREECAD).

─── Étape 1a (mars 2026) ────────────────────────────────────────────────────
Ajout de trois fonctions de filtrage :
  lister_bodies_valides_gorge()  — bodies avec LCS + paramètre nommé
  lister_bodies_valides_comp()   — bodies avec paramètre nommé (hors exclusion)
  doc_a_bodies_valides()         — test rapide pour la validation démarrage (1b)
─────────────────────────────────────────────────────────────────────────────
"""

import math

from .i18n import tr
from .oring_debug import print  # noqa: A004 — masquage partage, voir oring_debug.py
from builtins import print as _print_reel  # canal non masque, voir completer_documents_partiels()

# Import FreeCAD conditionnel — permet les tests partiels hors FreeCAD
try:
    import FreeCAD as App
    import FreeCADGui as Gui
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets
    FREECAD_DISPONIBLE = True
except ImportError:
    FREECAD_DISPONIBLE = False


# =============================================================================
# MESSAGES ET DIALOGUES
# =============================================================================

def message_erreur(titre: str, texte: str) -> None:
    """Affiche une boîte d'erreur Qt ou imprime en console selon le contexte."""
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.critical(None, titre, texte)
    else:
        print(f"[ERREUR] {titre} : {texte}")


def message_avertissement(titre: str, texte: str) -> None:
    """Affiche une boîte d'avertissement Qt ou imprime en console."""
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.warning(None, titre, texte)
    else:
        print(f"[AVERT.] {titre} : {texte}")


def message_info(titre: str, texte: str, parent=None) -> None:
    """Affiche une boîte d'information Qt ou imprime en console.

    parent : widget Qt parent — si fourni, la boîte est centrée sur ce widget.
    """
    if FREECAD_DISPONIBLE:
        QtWidgets.QMessageBox.information(parent, titre, texte)
    else:
        print(f"[INFO]  {titre} : {texte}")


# =============================================================================
# ACCÈS AU DOCUMENT FREECAD
# =============================================================================

def get_document_actif():
    """
    Retourne le document FreeCAD actif.
    Lève RuntimeError si aucun document n'est ouvert.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError(tr("FreeCAD not available"))
    doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError(tr("Active document not found"))
    return doc


def get_selection() -> list:
    """Retourne la liste des objets actuellement sélectionnés dans FreeCAD."""
    if not FREECAD_DISPONIBLE:
        return []
    return Gui.Selection.getSelection()


# =============================================================================
# BODY ET OBJETS
# =============================================================================

# Types de conteneurs "lien" de FreeCAD. Dans un assemblage multi-fichiers
# (atelier Assembly de FreeCAD 1.x), le document actif ne contient AUCUN
# PartDesign::Body : chaque composant y est un App::Link vers un Body vivant
# dans son propre .FCStd. Toute logique qui filtre doc.Objects sur
# 'PartDesign::Body' est donc aveugle a ces assemblages.
# (Diagnostic du 06/09/2026, spec claude/spec_support_liens_assemblage.md.)
_TYPES_LIENS = ('App::Link', 'App::LinkElement', 'App::LinkGroup')


def resoudre_objet_reel(obj):
    """
    Remonte une chaine de liens (App::Link / App::LinkElement /
    App::LinkGroup) jusqu'a l'objet reel qu'elle designe, dans son propre
    document. Retourne `obj` tel quel si ce n'est pas un lien, ou None si
    le lien est vide / non resolu.

    Point de depart de tout le support des liens : dans un assemblage
    multi-fichiers, l'objet reel vit dans un AUTRE document que le lien.
    """
    if not FREECAD_DISPONIBLE or obj is None:
        return obj
    if getattr(obj, 'TypeId', '') not in _TYPES_LIENS:
        return obj
    try:
        reel = obj.getLinkedObject(True)   # True = remontee recursive
    except Exception:
        return None
    if reel is None or reel is obj:
        return None
    return reel


def documents_du_perimetre(doc=None) -> list:
    """
    Retourne les documents FreeCAD constituant le PERIMETRE de `doc` :
    `doc` lui-meme, puis les documents sources atteints par ses App::Link /
    App::LinkElement / App::LinkGroup. Dedoublonne, ordre stable, `doc`
    toujours en tete.

    Depuis l'Etape A du support des liens (06/09/2026), les joints ORing d'un
    composant lie sont crees dans le document SOURCE du composant. Toute
    fonction qui balayait `doc.Objects` pour retrouver un joint, un LCS ou un
    sketch doit donc balayer le perimetre.

    En mono-document (aucun lien), le perimetre se reduit a [doc] : les
    fonctions appelantes gardent exactement leur comportement historique.

    Volontairement limite aux documents deja OUVERTS : un document source non
    charge n'est pas ouvert par cette fonction (effet de bord inacceptable
    pour une simple lecture).
    """
    if not FREECAD_DISPONIBLE:
        return []
    if doc is None:
        doc = get_document_actif()
    if doc is None:
        return []

    docs = [doc]
    vus = {doc.Name}
    try:
        for obj in doc.Objects:
            if getattr(obj, 'TypeId', '') not in _TYPES_LIENS:
                continue
            reel = resoudre_objet_reel(obj)
            if reel is None:
                continue
            try:
                d = reel.Document
            except Exception:
                continue
            if d is not None and d.Name not in vus:
                vus.add(d.Name)
                docs.append(d)
    except Exception as e:
        print(f"[ORing] documents_du_perimetre AVERT : {e}")
    return docs


# =============================================================================
# DOCUMENTS CHARGES PARTIELLEMENT
# =============================================================================
#
# Quand un assemblage lie un document, FreeCAD peut ne le charger que
# PARTIELLEMENT -- juste ce qu'il faut pour afficher les instances. Dans cet
# etat, il le dit lui-meme dans la vue Rapport :
#
#   DocumentObject.cpp(910): Changes to partial loaded document will not be saved
#   Document.cpp(2642):      Please reload partial document ... for recomputation
#
# ... et il ne plaisante pas. 13/09/2026, mesure sur le fichier de
# l'utilisateur : une modification de joint (tore 2,62 -> 4,00) rapportee
# reussie de bout en bout par la macro -- chaque setDatum rendant la valeur
# demandee, le tore reconstruit, les metadonnees posees -- et le fichier,
# rouvert seul, portant toujours 2,62. PERTE SILENCIEUSE.
#
# Aucun controle interne ne pouvait la voir : la valeur EST posee, en memoire.
# Seul le disque savait. C'est la classe E du memorandum dans sa forme
# symetrique : le moteur parle, et c'est la macro qui n'ecoute pas.
#
# Deux mesures fondent le correctif, faites dans la session de l'utilisateur :
#   doc.Partial                    -> True  (la detection existe)
#   App.openDocument(doc.FileName) -> Partial passe a False, meme objet
#                                     document, rien de perdu
#
# D'ou le choix : COMPLETER plutot qu'avertir. Le memorandum SS5 le dit --
# avant de construire une explication, chercher la regle qui la rend inutile.
# FreeCAD avertissait deja, et cela n'a pas suffi.


def document_partiel(doc) -> bool:
    """Vrai si `doc` est charge partiellement (ecritures NON enregistrees).

    `Partial` est un attribut de App::Document. `getattr` avec repli : une
    version de FreeCAD qui ne l'exposerait pas doit degrader vers « complet »,
    jamais bloquer la macro sur une propriete absente.
    """
    if doc is None:
        return False
    try:
        return bool(getattr(doc, 'Partial', False))
    except Exception:
        return False


def completer_documents_partiels(doc=None) -> dict:
    """Charge entierement les documents du perimetre restes partiels.

    Rend ``{'completes': [noms], 'echecs': [noms], 'partiels_restants':
    [noms]}``. **Ne leve jamais** : un echec de completion se declare, il ne
    fait pas tomber la macro -- l'appelant decide alors de refuser d'ecrire.

    Rien de nouveau n'est ouvert : `documents_du_perimetre()` ne rend que des
    documents DEJA ouverts ; un document partiel est deja la, simplement
    incomplet.

    Le document actif est **releve avant et restitue apres** :
    `App.openDocument()` sur un fichier deja ouvert peut changer le document
    actif, et tout le reste de la macro est enracine dessus.
    """
    resultat = {'completes': [], 'echecs': [], 'partiels_restants': []}
    if not FREECAD_DISPONIBLE:
        return resultat

    try:
        actif_avant = App.ActiveDocument
    except Exception:
        actif_avant = None

    try:
        docs = documents_du_perimetre(doc)
    except Exception as erreur:
        print('[ORing partiel] AVERT perimetre : %s' % erreur)
        return resultat

    for d in docs:
        if not document_partiel(d):
            continue
        nom = getattr(d, 'Name', '?')
        chemin = getattr(d, 'FileName', '') or ''
        if not chemin:
            # Document partiel sans fichier : rien a rouvrir.
            print("[ORing partiel] AVERT '%s' partiel sans FileName" % nom)
            resultat['echecs'].append(nom)
            resultat['partiels_restants'].append(nom)
            continue
        try:
            App.openDocument(chemin)
        except Exception as erreur:
            print("[ORing partiel] AVERT echec completion '%s' : %s"
                  % (nom, erreur))
            resultat['echecs'].append(nom)

        # Relire l'etat : c'est la mesure qui fait foi, pas l'absence
        # d'exception. openDocument() peut rendre la main sans avoir complete.
        try:
            d2 = App.getDocument(nom)
        except Exception:
            d2 = None
        if d2 is not None and not document_partiel(d2):
            resultat['completes'].append(nom)
            # Ce n'est pas une trace de mise au point mais une ACTION faite
            # sur les documents de l'utilisateur : il doit la voir, quel que
            # soit le masquage de print() ET quelle que soit la configuration
            # de sa vue Rapport.
            #
            # DEUX canaux, volontairement (13/09/2026) :
            #   - `_print_reel` : le print() natif, court-circuitant le
            #     masquage du module. C'est le canal dont on SAIT qu'il
            #     arrive chez l'utilisateur -- toutes les traces qu'il nous a
            #     collees dans la journee passaient par la ;
            #   - `App.Console.PrintMessage` : le canal propre de FreeCAD,
            #     mais dont l'affichage depend d'une case a cocher de la vue
            #     Rapport (« Normal messages ») que je ne peux pas verifier.
            #
            # Poser le message sur le seul second canal l'a rendu invisible
            # une premiere fois. Un message qu'on n'est pas sur de faire
            # arriver ne vaut pas mieux que pas de message du tout.
            _texte_complete = (
                "[ORing] Document '%s' complete : il etait charge "
                "partiellement, vos modifications y seront desormais "
                "enregistrees." % nom)
            try:
                _print_reel(_texte_complete)
            except Exception:
                pass
            try:
                App.Console.PrintMessage(_texte_complete + "\n")
            except Exception:
                pass
        else:
            resultat['partiels_restants'].append(nom)
            if nom not in resultat['echecs']:
                resultat['echecs'].append(nom)

    # Restituer le document actif.
    if actif_avant is not None:
        try:
            App.setActiveDocument(actif_avant.Name)
            App.ActiveDocument = actif_avant
        except Exception:
            pass

    return resultat


def documents_partiels_du_perimetre(doc=None) -> list:
    """Noms des documents du perimetre encore charges partiellement.

    Controle a faire **juste avant d'ecrire** : la completion du lancement
    peut avoir echoue, et l'utilisateur peut avoir ferme puis rouvert un
    fichier entre-temps.
    """
    if not FREECAD_DISPONIBLE:
        return []
    try:
        return [getattr(d, 'Name', '?') for d in documents_du_perimetre(doc)
                if document_partiel(d)]
    except Exception as erreur:
        print('[ORing partiel] AVERT controle : %s' % erreur)
        return []


# =============================================================================
# ADRESSAGE D'UNE SELECTION A TRAVERS LES LIENS
# =============================================================================
#
# `documents_du_perimetre()` ci-dessus resout la question « OU vit l'objet ».
# Celle-ci resout la question suivante, qui n'avait jamais ete posee :
# « COMMENT le designer dans la vue 3D ».
#
# Defaut etabli par mesure le 13/09/2026, dans la session de l'utilisateur :
#
#   addSelection('doc_source', 'ORing')                      -> rien ne s'allume
#   addSelection(actif, 'Assembly', 'Piston_.…ORing.')       -> le tore s'allume
#
# La vue 3D d'un assemblage n'affiche pas les objets sources : elle affiche les
# INSTANCES atteintes par les App::Link. Un `addSelection(doc, nom)` selectionne
# donc bien quelque chose -- dans un document qui n'est pas a l'ecran.
#
# C'est la RECIPROQUE du chemin de sous-objet decrit au SS4.3 de
# mecanismes_partages.md : celui-la LIT un chemin rendu par la selection pour en
# tirer un placement monde ; celui-ci le CONSTRUIT pour aller eclairer un objet.
#
# Le correctif du 06/09/2026 avait vu que la CIBLE vivait dans le document
# source et l'avait corrige -- sans voir que l'ADRESSAGE etait reste
# mono-document. Classe C du memorandum.

_PROFONDEUR_MAX_CHEMIN = 8


def _meme_objet(a, b) -> bool:
    """Identite d'un objet de document, valable ENTRE documents.

    `is` ne suffit pas : `getSubObject()` peut rendre un enveloppement Python
    distinct pour le meme objet C++. `Name` seul ne suffit pas non plus -- il
    n'identifie que DANS un document (regle 6 de mecanismes_partages.md) :
    deux composants portant chacun leur premier joint ont des Parts de meme
    Name. C'est le COUPLE (document, Name) qui identifie.
    """
    if a is None or b is None:
        return False
    if a is b:
        return True
    try:
        return (a.Name == b.Name
                and getattr(getattr(a, 'Document', None), 'Name', None)
                    == getattr(getattr(b, 'Document', None), 'Name', None))
    except Exception:
        return False


def chemin_selection(cible, doc=None):
    """Rend de quoi eclairer `cible` dans la vue 3D de `doc`.

    Retourne le triplet ``(nom_document, nom_objet_tete, sous_chemin)`` tel que

        Gui.Selection.addSelection(nom_document, nom_objet_tete,
                                   sous_chemin + sous_element)

    designe `cible` dans la vue. Retourne ``None`` si elle n'est pas
    atteignable depuis `doc` -- l'appelant retombe alors sur l'adressage
    historique (cf. `selectionner()`).

    **Non-regression mono-document** : quand la cible vit dans le document
    affiche, la fonction rend ``(doc.Name, cible.Name, '')``, c'est-a-dire
    exactement l'appel d'avant ce correctif. Cela se LIT sur la garde
    ci-dessous ; ce n'est pas une propriete a deduire du parcours.

    Parcours **en largeur** : rend le chemin le plus court, donc un resultat
    deterministe quand un objet est atteignable par plusieurs chaines de
    liens. Un meme objet source instancie deux fois est rendu sous la
    premiere instance rencontree -- les deux sont des designations valides.

    **Ne leve jamais** : un objet a moitie resolu fait sauter son rameau, pas
    la recherche. Une aide visuelle ne doit pas empecher un dialogue de
    s'ouvrir.
    """
    if not FREECAD_DISPONIBLE or cible is None:
        return None
    if doc is None:
        doc = get_document_actif()
    if doc is None:
        return None

    # --- Mono-document : l'adressage historique, tel quel ------------------
    try:
        doc_cible = getattr(cible, 'Document', None)
        if doc_cible is doc or (doc_cible is not None
                                and doc_cible.Name == doc.Name):
            return (doc.Name, cible.Name, '')
    except Exception:
        pass

    # --- Assemblage : construire le chemin ---------------------------------
    try:
        racines = list(getattr(doc, 'RootObjects', None) or doc.Objects)
    except Exception:
        return None

    def _cle(obj):
        return (getattr(getattr(obj, 'Document', None), 'Name', ''),
                getattr(obj, 'Name', ''))

    file_attente = []
    vus = set()
    for racine in racines:
        try:
            cle = _cle(racine)
        except Exception:
            continue
        if not cle[1] or cle in vus:
            continue
        vus.add(cle)
        file_attente.append((racine, racine.Name, '', 0))

    while file_attente:
        obj, tete, chemin, profondeur = file_attente.pop(0)
        if profondeur >= _PROFONDEUR_MAX_CHEMIN:
            continue
        try:
            sous_noms = obj.getSubObjects() or ()
        except Exception:
            continue
        for sous in sous_noms:
            try:
                enfant = obj.getSubObject(sous, 1)
            except Exception:
                continue
            if enfant is None or not getattr(enfant, 'Name', ''):
                continue
            nouveau = chemin + sous
            if _meme_objet(enfant, cible):
                return (doc.Name, tete, nouveau)
            cle = _cle(enfant)
            if cle in vus:
                continue
            vus.add(cle)
            file_attente.append((enfant, tete, nouveau, profondeur + 1))

    return None


def selectionner(cible, doc=None, sous_element: str = '') -> bool:
    """Eclaire `cible` dans la vue 3D, liens compris. Rend True si le chemin
    a pu etre construit, False sinon.

    Le booleen n'est pas decoratif : une valeur de retour qui pilote une
    decision ne doit jamais etre un `return` nu (piege SS3 du memorandum).

    En cas d'echec, **l'adressage historique est tout de meme tente**. Il
    n'eclaire rien dans un assemblage lie, mais il n'a jamais rien casse non
    plus -- et une aide visuelle ne doit pas devenir une source d'erreur.
    """
    if not FREECAD_DISPONIBLE or cible is None:
        return False
    args = chemin_selection(cible, doc)
    try:
        if args is None:
            doc_cible = getattr(cible, 'Document', None)
            if doc_cible is None:
                return False
            if sous_element:
                Gui.Selection.addSelection(doc_cible.Name, cible.Name,
                                           sous_element)
            else:
                Gui.Selection.addSelection(doc_cible.Name, cible.Name)
            return False
        nom_doc, tete, chemin = args
        if chemin or sous_element:
            Gui.Selection.addSelection(nom_doc, tete, chemin + sous_element)
        else:
            Gui.Selection.addSelection(nom_doc, tete)
        return True
    except Exception as erreur:
        print("[ORing] selectionner AVERT : %s" % erreur)
        return False


def lister_bodies(doc=None, inclure_liens: bool = True) -> list:
    """
    Retourne la liste des PartDesign::Body accessibles depuis `doc` :

    - les Body du document lui-meme (comportement historique) ;
    - avec inclure_liens=True (defaut), les Body designes par les
      App::Link / App::LinkElement / App::LinkGroup du document. Ceux-la
      vivent dans LEUR document source, pas dans `doc`.

    Correctif du 06/09/2026 : dans un assemblage multi-fichiers, `doc` ne
    contient AUCUN Body. Sans ce parcours des liens, les combos « piece
    portant la gorge » et « piece complementaire » restaient vides et aucun
    joint ne pouvait etre insere (symptome rapporte par l'utilisateur).

    Un composant deja equipe est un lien vers le conteneur App::Part
    « ... equipe » cree par un joint precedent : on descend d'un niveau pour
    y retrouver les Body (les corps ORing generes sont ecartes plus loin par
    _est_body_oring(), comme pour le cas mono-document).

    Dedoublonnage par (document, nom) : un meme Body reference par deux liens
    n'apparait qu'UNE fois -- la gorge etant creee dans le document source,
    elle est de toute facon partagee par toutes les instances. Ordre stable :
    Body locaux d'abord, puis Body lies dans l'ordre des liens du document.
    """
    if not FREECAD_DISPONIBLE:
        return []
    if doc is None:
        doc = get_document_actif()
    if doc is None:
        return []

    resultat = []
    vus = set()

    def _ajouter(b):
        if b is None or getattr(b, 'TypeId', '') != 'PartDesign::Body':
            return
        try:
            cle = (b.Document.Name, b.Name)
        except Exception:
            return
        if cle in vus:
            return
        vus.add(cle)
        resultat.append(b)

    try:
        for obj in doc.Objects:
            if getattr(obj, 'TypeId', '') == 'PartDesign::Body':
                _ajouter(obj)
    except Exception as e:
        print(f"[ORing] lister_bodies AVERT : {e}")
        return resultat

    if not inclure_liens:
        return resultat

    try:
        for obj in doc.Objects:
            if getattr(obj, 'TypeId', '') not in _TYPES_LIENS:
                continue
            reel = resoudre_objet_reel(obj)
            if reel is None:
                continue
            type_reel = getattr(reel, 'TypeId', '')
            if type_reel == 'PartDesign::Body':
                _ajouter(reel)
            elif type_reel == 'App::Part':
                for enfant in getattr(reel, 'Group', []):
                    _ajouter(enfant)
    except Exception as e:
        print(f"[ORing] lister_bodies (liens) AVERT : {e}")

    return resultat


def get_body_selectionne() -> object | None:
    """
    Retourne le premier Body sélectionné, ou None.
    Cherche d'abord dans la sélection active, sinon retourne None.
    """
    if not FREECAD_DISPONIBLE:
        return None
    sel = get_selection()
    for obj in sel:
        if obj.TypeId == 'PartDesign::Body':
            return obj
        # L'objet peut être une feature dans un body
        if hasattr(obj, 'getParent'):
            parent = obj.getParent()
            if parent and parent.TypeId == 'PartDesign::Body':
                return parent
    return None


def lister_lcs(body) -> list:
    """
    Retourne la liste des LCS (Local Coordinate System / PartDesign::CoordinateSystem)
    contenus dans un Body.
    """
    if not FREECAD_DISPONIBLE or body is None:
        return []
    lcs_list = []
    for obj in body.Group:
        if obj.TypeId in ('PartDesign::CoordinateSystem',
                          'App::LocalCoordSys',
                          'PartDesign::Point'):
            lcs_list.append(obj)
    return lcs_list


# =============================================================================
# FILTRAGE DES BODIES (étape 1a)
# =============================================================================

def lister_lcs_libres(body, doc=None) -> list:
    """
    Retourne la liste des LCS du body qui ne sont pas encore occupés
    par un joint ORing existant dans le document.

    Un LCS est considéré "occupé" si ses métadonnées dans un Part ORing
    référencent ce LCS (par label) pour ce body.
    """
    tous = lister_lcs(body)
    if not tous:
        return []
    if not FREECAD_DISPONIBLE or doc is None:
        # Sans doc, impossible de vérifier — retourner tous les LCS
        return tous
    try:
        # Collecter les labels LCS déjà utilisés pour ce body
        from .metadata import lister_parts_oring, lire_metadonnees
        deja_pris = set()
        body_name  = getattr(body, 'Name', '')
        body_label = getattr(body, 'Label', '')
        # Les joints d'un composant lié vivent dans SON document, pas dans
        # celui de l'assemblage (06/09/2026) : balayer les deux, dédoublonnés.
        # En mono-document, body.Document EST doc — un seul balayage.
        docs_a_balayer = [doc]
        doc_body = getattr(body, 'Document', None)
        if doc_body is not None and doc_body is not doc:
            docs_a_balayer.append(doc_body)
        parts_oring = []
        for _d in docs_a_balayer:
            for _p in lister_parts_oring(_d):
                if _p not in parts_oring:
                    parts_oring.append(_p)
        for part in parts_oring:
            try:
                m = lire_metadonnees(part)
                # Vérifier que ce joint appartient bien à ce body
                if (m.get('body_gorge_name') == body_name
                        or m.get('body_gorge_label') == body_label):
                    lcs_lbl = m.get('lcs_label', '')
                    if lcs_lbl:
                        deja_pris.add(lcs_lbl)
            except Exception:
                pass
        return [lcs for lcs in tous if lcs.Label not in deja_pris]
    except Exception:
        return tous   # En cas d'erreur, retourner tous (pas de faux-négatif)


def lister_bodies_valides_gorge(doc=None) -> list:
    """
    Retourne les bodies utilisables comme pièce portant la GORGE.

    Critères :
      1. Au moins 1 LCS LIBRE (non déjà occupé par un joint ORing existant)
      2. Au moins 1 paramètre nommé (contrainte sketch ou alias spreadsheet)
         excluant les paramètres internes de gorge ORing

    Ces deux conditions garantissent que la macro peut :
      1. Accrocher le sketch au plan XZ d'un LCS disponible
      2. Mettre à jour le diamètre de la pièce via le paramètre nommé

    Un body dont tous les LCS sont déjà utilisés par des joints existants
    n'est PAS proposé (le combo LCS serait vide et la création impossible).
    """
    bodies = lister_bodies(doc)
    resultat = []
    for b in bodies:
        if _est_body_oring(b):
            continue  # exclure les corps ORing générés par la macro
        # Vérifier LCS libres (pas juste LCS existants)
        if not lister_lcs_libres(b, doc):
            continue
        # Vérifier paramètres nommés (hors paramètres internes de gorge)
        if not lister_parametres_body(b):
            continue
        resultat.append(b)
    return resultat


def lister_bodies_valides_comp(doc=None, exclure=None) -> list:
    """
    Retourne les bodies utilisables comme pièce COMPLÉMENTAIRE.

    Critères :
      - au moins 1 paramètre nommé (diamètre ou rayon de la pièce)
      - ne pas être le body déjà sélectionné pour la gorge (exclure)

    Paramètre exclure : objet Body à exclure (None = aucune exclusion).
    """
    bodies = lister_bodies(doc)
    resultat = []
    for b in bodies:
        if exclure is not None and b is exclure:
            continue
        if _est_body_oring(b):
            continue  # exclure les corps ORing générés par la macro (#5)
        if lister_parametres_body(b):
            resultat.append(b)
    return resultat


def doc_a_bodies_valides(doc=None) -> bool:
    """
    Retourne True si le document contient au moins un body apte à recevoir
    une gorge (LCS + paramètre nommé).

    Utilisé par la validation au démarrage (étape 1b) : si False, la macro
    affiche un message d'instruction et se ferme sans modifier le document.
    """
    return len(lister_bodies_valides_gorge(doc)) > 0


# =============================================================================
# PARAMÈTRES NOMMÉS FREECAD
# =============================================================================

# =============================================================================
# FILTRES D'EXCLUSION
# =============================================================================

# Préfixes des noms de contraintes propres aux esquisses de gorge ORing.
# Ces contraintes ne sont PAS des paramètres utilisateur et ne doivent
# pas apparaître dans la liste de sélection du paramètre Ø/R.
# Préfixes des contraintes internes générées par la macro ORing.
# Utilisation en startswith() (insensible à la casse) pour couvrir les
# suffixes numériques que FreeCAD ajoute en cas de doublons : RayonGorge1, etc.
_PREFIXES_CONTRAINTES_GORGE = (
    'rayongorge', 'rayonarbre', 'rayonalesage',
    'fillethautgorge', 'filletfondgorge',
    'depouille', 'demilargeur', 'demilargeurgorge', 'largeurgorge',
)


def _est_contrainte_gorge(nom: str) -> bool:
    """Retourne True si le nom de contrainte appartient aux esquisses de gorge ORing."""
    n = nom.lower().strip()
    return any(n.startswith(p) for p in _PREFIXES_CONTRAINTES_GORGE)


def _est_body_oring(body) -> bool:
    """
    Retourne True si le body est un corps ORing généré par la macro
    (Label commence par 'ORing' OU appartient à un Part dont le Name
    commence par 'ORing_').
    Ces bodies ne doivent pas apparaître dans les listes de sélection.
    """
    if body is None:
        return False
    # Critère 1 : Label du body
    if getattr(body, 'Label', '').startswith('ORing'):
        return True
    # Critère 2 : parent App::Part avec Name commençant par 'ORing_'
    for parent in getattr(body, 'InList', []):
        if (getattr(parent, 'TypeId', '') == 'App::Part'
                and getattr(parent, 'Name', '').startswith('ORing_')):
            return True
    return False


# Types de contraintes dimensionnelles Sketcher
_TYPES_DIMENSIONNELS = {
    'DistanceX', 'DistanceY', 'Distance',
    'Radius', 'Diameter', 'Angle',
}


def lister_parametres_body(body) -> dict:
    """
    Retourne un dictionnaire {nom: valeur_mm} des paramètres nommés
    d'un Body.

    Cherche dans :
    1. Les contraintes nommées de tous les Sketches du body
       (types dimensionnels : DistanceX, DistanceY, Distance, Radius,
        Diameter, Angle)
    2. Les Spreadsheets attachés au body (alias de cellules)
    """
    if not FREECAD_DISPONIBLE or body is None:
        return {}

    params = {}

    for obj in body.Group:

        # ── Sketches ──────────────────────────────────────────────────────
        if obj.TypeId == 'Sketcher::SketchObject':
            try:
                for c in obj.Constraints:
                    # Garder uniquement les contraintes nommées dimensionnelles
                    # Exclure les contraintes internes des esquisses de gorge (#4)
                    if (c.Name
                            and c.Name.strip()
                            and c.Type in _TYPES_DIMENSIONNELS
                            and not _est_contrainte_gorge(c.Name)):
                        # Ne pas écraser un param déjà trouvé dans un autre sketch
                        if c.Name not in params:
                            params[c.Name] = c.Value  # valeur en mm (unités internes)
            except Exception:
                pass  # sketch non initialisé ou corrompu — on passe

        # ── Spreadsheets ──────────────────────────────────────────────────
        elif obj.TypeId == 'Spreadsheet::Sheet':
            try:
                # getContents() renvoie la liste des cellules utilisées
                for cell_addr in obj.getContents():
                    alias = obj.getAlias(cell_addr)
                    if alias:
                        try:
                            val = obj.get(alias)  # lecture par alias
                            if isinstance(val, (int, float)):
                                if alias not in params:
                                    params[alias] = float(val)
                        except Exception:
                            pass
            except Exception:
                pass

    return params


def get_valeur_parametre(body, nom_param: str) -> float | None:
    """
    Retourne la valeur (en mm) d'un paramètre nommé dans un Body.
    Retourne None si le paramètre est introuvable.
    """
    params = lister_parametres_body(body)
    return params.get(nom_param, None)


def set_valeur_parametre(body, nom_param: str, valeur_mm: float) -> bool:
    """
    Met à jour la valeur d'un paramètre nommé dans un Body.
    Cherche d'abord dans les Sketches, puis dans les Spreadsheets.
    Retourne True si la mise à jour a réussi.
    """
    if not FREECAD_DISPONIBLE or body is None:
        return False


    doc = body.Document

    for obj in body.Group:

        # Sketch — contraintes nommées
        if obj.TypeId == 'Sketcher::SketchObject':
            try:
                for i, c in enumerate(obj.Constraints):
                    if c.Name == nom_param:
                        obj.setDatum(i, App.Units.Quantity(f'{valeur_mm} mm'))
                        doc.recompute()
                        return True
            except Exception:
                pass

        # Spreadsheet
        elif obj.TypeId == 'Spreadsheet::Sheet':
            try:
                for cell_addr in obj.getContents():
                    alias = obj.getAlias(cell_addr)
                    if alias == nom_param:
                        obj.set(cell_addr, str(valeur_mm))
                        doc.recompute()
                        return True
            except Exception:
                pass

    return False


# =============================================================================
# GÉOMÉTRIE — PLACEMENT ET LCS  # SANS FREECAD (calculs purs)
# =============================================================================

def rayon_vers_diametre(rayon_mm: float) -> float:
    """Convertit un rayon en diamètre."""
    return rayon_mm * 2.0


def diametre_vers_rayon(diametre_mm: float) -> float:
    """Convertit un diamètre en rayon."""
    return diametre_mm / 2.0


def volume_joint_torique(d1_mm: float, d2_mm: float) -> float:
    """
    Calcule le volume d'un joint torique (mm³).
    V = pi² x (d2/2)² x (d1 + d2) / 2
    """  # SANS FREECAD
    r_corde = d2_mm / 2.0
    r_moyen = (d1_mm + d2_mm) / 2.0
    return math.pi ** 2 * r_corde ** 2 * r_moyen


def dimensions_oblong(d1_mm: float, d2_mm: float,
                      position: str = 'arbre') -> dict:
    """
    Calcule les dimensions de la section oblong du joint torique
    pour la représentation 3D dans FreeCAD.
    Retourne la section au repos (non comprimée).
    """  # SANS FREECAD
    return {
        'largeur'   : d2_mm,
        'hauteur'   : d2_mm,
        'rayon_bout': d2_mm / 2.0,
    }


def placement_plan_median(rayon_piece_mm: float,
                           demi_largeur_gorge_mm: float,
                           position: str = 'arbre') -> dict:
    """
    Calcule le placement du plan médian de la gorge.
    """  # SANS FREECAD
    return {
        'rayon_moyen_gorge': rayon_piece_mm,
        'demi_largeur'     : demi_largeur_gorge_mm,
        'position'         : position,
    }


# =============================================================================
# HELPERS SKETCH FREECAD
# =============================================================================

def creer_sketch_sur_plan(body, plan_nom: str = 'XZ_Plane',
                           nom_sketch: str = 'Sketch'):
    """
    Crée un nouveau Sketch dans un Body, attaché au plan indiqué.
    Retourne l'objet Sketch.
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError(tr("FreeCAD not available"))

    import Sketcher

    sketch = body.newObject('Sketcher::SketchObject', nom_sketch)
    sketch.MapMode = 'FlatFace'

    # Chercher le plan dans les features d'origine du body
    plan = None
    for obj in body.Document.Objects:
        if obj.TypeId == 'App::Origin':
            for feat in obj.OriginFeatures:
                if feat.TypeId == 'App::Plane' and plan_nom in feat.Name:
                    plan = feat
                    break
    if plan is None:
        raise RuntimeError(tr("Plan '{plan}' not found in the document", plan=plan_nom))

    sketch.AttachmentSupport = plan
    sketch.AttachmentOffset  = App.Placement()
    body.Document.recompute()
    return sketch


def recompute_document(doc=None) -> None:
    """Recalcule le document FreeCAD actif."""
    if not FREECAD_DISPONIBLE:
        return
    if doc is None:
        doc = get_document_actif()
    doc.recompute()


# =============================================================================
# DÉTECTION PAR ARÊTE SÉLECTIONNÉE — LCS et paramètre Ø/rayon
# =============================================================================
# Chantier « guide de création » (spec claude/spec_oring_guide_creation_lcs_edge.md,
# 02/09/2026) — mécanismes additifs uniquement : un raccourci, jamais un
# prérequis du flux manuel existant (combo_lcs / combo_param restent la
# référence si rien n'est détecté).

# Types de features "DressUp" PartDesign (congé/chanfrein) : leur propriété
# Base référence les arêtes D'ORIGINE (avant application), pas les arêtes
# arrondies/chanfreinées elles-mêmes. Atelier Part historique
# (Part::Fillet/Part::Chamfer) volontairement non couvert — forme de
# propriété différente, non vérifiée (spec §5 point H).
_TYPES_DRESSUP = ('PartDesign::Fillet', 'PartDesign::Chamfer')

# PartDesign::Groove est l'equivalent soustractif de PartDesign::Revolution
# (meme logique d'axe/profil) -- inclus par robustesse meme si le cas
# remonte par l'utilisateur concerne une Revolution additive (arbre).
_TYPES_REVOLUTION = ('PartDesign::Revolution', 'PartDesign::Groove')

# Tolérance de recoupement géométrique (rayon et distance des centres),
# voir spec §5 point F — largement suffisante pour des cotes mécaniques
# courantes ; à ajuster ici seulement si des cotes plus rapprochées existent.
_TOLERANCE_GEOM_MM = 1e-4

# Primitives cylindriques/coniques sans Sketch pouvant porter une Property
# 'Radius' directement exploitable (repli de dernier recours de
# trouver_parametre_pour_edge). Liste fermée volontairement, plutôt qu'un
# hasattr(obj, 'Radius') générique qui risquerait de matcher une Property
# sans rapport portant le même nom sur un autre type de feature.
_TYPES_PRIMITIVES_CYLINDRIQUES = (
    'Part::Cylinder', 'Part::Cone', 'Part::Sphere',
    'PartDesign::AdditiveCylinder', 'PartDesign::SubtractiveCylinder',
    'PartDesign::AdditiveCone', 'PartDesign::SubtractiveCone',
)


def resoudre_arete_selectionnee():
    """
    Retourne (objet_proprietaire, nom_edge, edge) pour l'arête actuellement
    sélectionnée en vue 3D, ou None si la sélection n'est pas une arête
    circulaire (ou si rien n'est sélectionné).
    """
    if not FREECAD_DISPONIBLE:
        return None
    sel = Gui.Selection.getSelectionEx()
    if not sel or not sel[0].SubElementNames:
        return None
    nom_edge = sel[0].SubElementNames[0]
    if not nom_edge.startswith('Edge'):
        return None
    try:
        edge = sel[0].SubObjects[0]
    except (IndexError, AttributeError):
        return None
    if not (hasattr(edge, 'Curve') and hasattr(edge.Curve, 'Radius')):
        return None   # pas une arête circulaire (ni Circle ni ArcOfCircle)
    return (sel[0].Object, nom_edge, edge)


def resoudre_body_depuis_objet(objet):
    """
    Retourne le PartDesign::Body proprietaire de `objet`, ou None si
    non resolu (ou si le body resolu est un body ORing deja genere
    par la macro -- jamais une piece principale valide).

    Cas courant : objet EST deja le Body (un clic sur un Body en vue
    3D resout directement dessus -- meme constat deja fait pour la
    remontee Fillet/Chamfer, voir _feature_pour_climb()). Repli :
    remontee via getParentGeoFeatureGroup() (API FreeCAD standard)
    si objet est une feature a l'interieur d'un Body.

    Utilise par lancer_dialogue() pour reconnaitre le corps portant
    la gorge quand une arete circulaire est deja selectionnee en vue
    3D avant le lancement de la macro (spec
    claude/spec_oring_guide_creation_lcs_edge.md, §3.4bis, 03/09/2026,
    demande utilisateur).
    """
    if objet is None:
        return None
    body = None
    if getattr(objet, 'TypeId', None) == 'PartDesign::Body':
        body = objet
    else:
        try:
            parent = objet.getParentGeoFeatureGroup()
            if (parent is not None
                    and getattr(parent, 'TypeId', None) == 'PartDesign::Body'):
                body = parent
        except Exception:
            body = None
    if body is None or _est_body_oring(body):
        return None
    return body


def trouver_joint_pour_arete(doc, objet_proprietaire, nom_edge, edge):
    """
    Cherche, parmi les joints ORing existants, celui dont le LCS de gorge
    est attaché à cette même arête circulaire -- comparaison géométrique
    (rayon + centre, tolérance _TOLERANCE_GEOM_MM), pas par nom d'arête
    (robuste à un recalcul qui renommerait les arêtes, même principe que
    _chercher_geometrie_correspondante()).

    Sert à distinguer, quand une arête circulaire est pré-sélectionnée
    avant le lancement de la macro (spec §3.4bis) :
    - "cette gorge existe déjà" (l'arête correspond au LCS d'un joint
      existant) -> ouvrir ce joint en édition, comportement historique
      inchangé ;
    - "nouvelle gorge sur un corps qui en porte déjà d'autres" -> nouveau
      joint assisté, même si le corps porte par ailleurs un ou plusieurs
      autres joints (un même arbre/alésage peut porter plusieurs gorges,
      confirmé utilisateur 03/09/2026).

    Retourne le Part ORing correspondant, ou None si l'arête ne
    correspond à aucun joint existant (corps vierge, ou nouvelle gorge
    sur un corps déjà équipé).
    """
    # CORRECTIF (06/09/2026) : `trouver_objet` etait utilise plus bas sans
    # jamais etre importe -- NameError attrapee par l'appelant, qui journalisait
    # « Detection joint pour arete AVERT : name 'trouver_objet' is not defined »
    # et concluait toujours « aucun joint correspondant ». Defaut PREEXISTANT,
    # verifie identique dans la sauvegarde anterieure au chantier du 06/09.
    from .metadata import (lister_parts_oring, lire_metadonnees,
                           trouver_objet)
    if not FREECAD_DISPONIBLE or doc is None or edge is None:
        return None
    if not (hasattr(edge, 'Curve') and hasattr(edge.Curve, 'Radius')):
        return None
    rayon_cible = edge.Curve.Radius
    centre_cible = edge.Curve.Location
    for part in lister_parts_oring(doc):
        meta = lire_metadonnees(part)
        lcs = trouver_objet(doc, name=meta.get('lcs_name', ''),
                             label=meta.get('lcs_label', ''),
                             type_id='PartDesign::CoordinateSystem')
        if lcs is None:
            continue
        support = getattr(lcs, 'AttachmentSupport', None)
        if not support:
            continue
        try:
            obj_support, sous_elements = support[0]
            nom_edge_support = sous_elements[0]
        except Exception:
            continue
        edge_support = _edge_depuis_nom(obj_support, nom_edge_support)
        if edge_support is None or not hasattr(edge_support, 'Curve'):
            continue
        try:
            if (abs(edge_support.Curve.Radius - rayon_cible) <= _TOLERANCE_GEOM_MM
                    and edge_support.Curve.Location.distanceToPoint(centre_cible)
                        <= _TOLERANCE_GEOM_MM):
                return part
        except Exception:
            continue
    return None


def _aretes_avant_dressup(objet, nom_edge):
    """
    Si objet est un PartDesign::Fillet/Chamfer, remonte via sa propriété
    Base vers l'arête (ou les arêtes) d'origine avant congé/chanfrein —
    récursif, pour un enchaînement de plusieurs Fillet/Chamfer.
    Retourne toujours une liste de tuples (objet, nom_edge) — la liste
    [(objet, nom_edge)] telle quelle si objet n'est pas un DressUp.
    """
    if not FREECAD_DISPONIBLE or getattr(objet, 'TypeId', '') not in _TYPES_DRESSUP:
        return [(objet, nom_edge)]
    base = getattr(objet, 'Base', None)
    if not base or len(base) != 2:
        return [(objet, nom_edge)]   # forme inattendue, on s'arrête là
    base_obj, noms_base = base
    resultat = []
    for nom in (noms_base or []):
        resultat.extend(_aretes_avant_dressup(base_obj, nom))
    return resultat or [(objet, nom_edge)]


def _feature_pour_climb(objet_proprietaire, body):
    """
    Détermine la feature à tester pour une remontée Fillet/Chamfer.
    En sélection normale sur un Body (cas courant), sel[0].Object renvoyé
    par resoudre_arete_selectionnee() est le Body lui-même — qui reflète
    la forme de son Tip — pas la feature Fillet/Chamfer en tant que telle.
    C'est donc Tip qu'il faut inspecter dans ce cas. Retourne
    objet_proprietaire tel quel dans les autres cas (sélection directe
    d'une feature, contexte d'édition...).
    """
    if (body is not None
            and getattr(objet_proprietaire, 'TypeId', '') == 'PartDesign::Body'
            and getattr(body, 'Tip', None) is not None):
        return body.Tip
    return objet_proprietaire


def _edge_depuis_nom(objet, nom_edge):
    """Résout un nom d'arête ('Edge12') sur la Shape d'un objet FreeCAD."""
    try:
        return objet.Shape.getElement(nom_edge)
    except Exception:
        return None


def _chercher_geometrie_correspondante(body, edge):
    """
    Cherche, parmi les Sketch du body, une géométrie circulaire (cercle ou
    arc) dont le rayon et le centre — repositionnés dans le repère global
    via sketch.Placement — correspondent à edge, dans la tolérance
    _TOLERANCE_GEOM_MM.
    Retourne la liste des correspondances : [(sketch, idx_geo), ...].
    """
    if not FREECAD_DISPONIBLE or body is None or edge is None:
        return []
    if not (hasattr(edge, 'Curve') and hasattr(edge.Curve, 'Radius')):
        return []   # arête non circulaire (ex. Part.Line) -- rien à chercher
    rayon_cible  = edge.Curve.Radius
    centre_cible = edge.Curve.Location
    candidats = []
    for obj in body.Group:
        if obj.TypeId != 'Sketcher::SketchObject':
            continue
        try:
            geometries = obj.Geometry
        except Exception:
            continue
        for i, geo in enumerate(geometries):
            if not (hasattr(geo, 'Radius') and hasattr(geo, 'Center')):
                continue
            if abs(geo.Radius - rayon_cible) > _TOLERANCE_GEOM_MM:
                continue
            try:
                centre_geo = obj.Placement.multVec(
                    App.Vector(geo.Center.x, geo.Center.y, 0))
                normale_sketch = obj.Placement.Rotation.multVec(
                    App.Vector(0, 0, 1))
            except Exception:
                continue
            # Coaxialite (et non egalite stricte des centres) : une arete
            # issue d'une extrusion (Pad) le long de la normale du Sketch
            # partage l'axe du cercle source mais se trouve decalee le
            # long de cet axe -- ne comparer que l'ecart lateral
            # (perpendiculaire a la normale), pas l'ecart axial complet.
            # Correctif du 03/09/2026 (cas reel remonte par l'utilisateur :
            # detection en echec sur une arete generee par extrusion).
            ecart = centre_cible.sub(centre_geo)
            ecart_axial = ecart.dot(normale_sketch)
            ecart_lateral = App.Vector(
                ecart.x - normale_sketch.x * ecart_axial,
                ecart.y - normale_sketch.y * ecart_axial,
                ecart.z - normale_sketch.z * ecart_axial)
            if ecart_lateral.Length > _TOLERANCE_GEOM_MM:
                continue
            candidats.append((obj, i))
    return candidats


def _chercher_primitive_correspondante(body, edge):
    """
    Cherche, parmi les objets du body sans Sketch (voir
    _TYPES_PRIMITIVES_CYLINDRIQUES), une Property 'Radius' dont la valeur
    correspond à edge.Curve.Radius, dans la tolérance _TOLERANCE_GEOM_MM.
    Retourne la liste des objets correspondants.
    """
    if not FREECAD_DISPONIBLE or body is None or edge is None:
        return []
    rayon_cible = edge.Curve.Radius
    candidats = []
    for obj in body.Group:
        if obj.TypeId not in _TYPES_PRIMITIVES_CYLINDRIQUES:
            continue
        if not hasattr(obj, 'Radius'):
            continue
        try:
            brut = obj.Radius
            valeur = float(brut.Value) if hasattr(brut, 'Value') else float(brut)
        except Exception:
            continue
        if abs(valeur - rayon_cible) <= _TOLERANCE_GEOM_MM:
            candidats.append(obj)
    return candidats


def proposer_nom_parametre(body, prefixe: str) -> str:
    """
    Propose un nom de paramètre unique à l'échelle du Body (préfixe 'R' ou
    'D'), en évitant toute collision avec lister_parametres_body(body).
    Suffixe numérique en cas de collision — même convention que
    'RayonGorge1', déjà utilisée ailleurs dans ce module.
    """
    existants = set(lister_parametres_body(body).keys())
    base = f'{prefixe}Param'
    if base not in existants:
        return base
    n = 1
    while f'{base}{n}' in existants:
        n += 1
    return f'{base}{n}'


def _resoudre_axe_reference(objet_origine):
    """
    Résout l'axe de révolution (ReferenceAxis) d'une PartDesign::Revolution
    ou PartDesign::Groove en (origine_monde, direction_monde) -- ou None si
    non résolu.

    Cas standard couvert : axe H_Axis/V_Axis du sketch de profil lui-même
    (convention déjà utilisée ailleurs dans ce projet, voir
    oring_3d.py/sketch_arbre.py/sketch_alesage.py, et confirmée par
    l'utilisateur le 03/09/2026 comme sa propre convention de cotation).
    Repli générique sur une arête/ligne externe (Curve.Location/.Direction)
    dans les autres cas.
    """
    axe = getattr(objet_origine, 'ReferenceAxis', None)
    if not axe or len(axe) != 2:
        return None
    axe_obj, sous_noms = axe
    if not sous_noms:
        return None
    nom_axe = sous_noms[0]

    profil = getattr(objet_origine, 'Profile', None)
    sketch_profil = profil[0] if isinstance(profil, (tuple, list)) else profil

    if axe_obj is sketch_profil and nom_axe in ('H_Axis', 'V_Axis'):
        direction_locale = (App.Vector(1, 0, 0) if nom_axe == 'H_Axis'
                             else App.Vector(0, 1, 0))
        try:
            origine_monde = sketch_profil.Placement.multVec(App.Vector(0, 0, 0))
            direction_monde = sketch_profil.Placement.Rotation.multVec(direction_locale)
            direction_monde.normalize()
            return (origine_monde, direction_monde)
        except Exception:
            return None

    edge_axe = _edge_depuis_nom(axe_obj, nom_axe)
    if edge_axe is None or not hasattr(edge_axe, 'Curve'):
        return None
    curve = edge_axe.Curve
    if not (hasattr(curve, 'Location') and hasattr(curve, 'Direction')):
        return None
    try:
        direction_monde = App.Vector(curve.Direction)
        direction_monde.normalize()
        return (curve.Location, direction_monde)
    except Exception:
        return None


def _chercher_distance_axe_pour_revolution(objet_origine, edge):
    """
    Repli pour une arête circulaire issue d'une PartDesign::Revolution/
    Groove dont le rayon n'est pas un cercle dessiné dans l'esquisse mais
    dérivé de la distance entre un point/une ligne du profil et l'axe de
    révolution -- cotée, selon la convention confirmée par l'utilisateur
    (03/09/2026), par une contrainte Distance/DistanceX/DistanceY plutôt
    que Radius/Diamètre.

    Vérification géométrique : le centre et l'axe de l'arête testée
    doivent effectivement coïncider avec l'axe de révolution résolu
    (ReferenceAxis) -- pas de correspondance par simple coïncidence de
    valeur si l'arête ne provient même pas de cette révolution-là.

    Limite connue (documentée) : contrairement au cas Radius/Diamètre
    (§3.2), aucune vérification géométrique supplémentaire n'est faite
    point par point sur la contrainte elle-même -- seule sa VALEUR est
    comparée au rayon, parmi les contraintes Distance/DistanceX/DistanceY
    nommées du sketch de profil. En cas d'ambiguïté (plusieurs
    contraintes de même valeur), statut 'ambigu' plus haut -- repli sur
    le flux manuel, jamais de choix silencieux entre plusieurs candidats.

    Retourne la liste des correspondances : [(sketch, idx_contrainte), ...].
    """
    if not FREECAD_DISPONIBLE or objet_origine is None or edge is None:
        return []
    if not (hasattr(edge, 'Curve') and hasattr(edge.Curve, 'Radius')):
        return []

    profil = getattr(objet_origine, 'Profile', None)
    sketch = profil[0] if isinstance(profil, (tuple, list)) else profil
    if sketch is None or getattr(sketch, 'TypeId', '') != 'Sketcher::SketchObject':
        return []

    axe = _resoudre_axe_reference(objet_origine)
    if axe is None:
        return []
    origine_axe, direction_axe = axe

    try:
        vecteur = edge.Curve.Location.sub(origine_axe)
        ecart_axial = vecteur.dot(direction_axe)
        ecart_radial = App.Vector(
            vecteur.x - direction_axe.x * ecart_axial,
            vecteur.y - direction_axe.y * ecart_axial,
            vecteur.z - direction_axe.z * ecart_axial)
        if ecart_radial.Length > _TOLERANCE_GEOM_MM:
            return []
        axe_cercle = App.Vector(edge.Curve.Axis)
        axe_cercle.normalize()
        if 1.0 - abs(axe_cercle.dot(direction_axe)) > 1e-6:
            return []
    except Exception:
        return []

    rayon_cible = edge.Curve.Radius
    candidats = []
    try:
        contraintes = sketch.Constraints
    except Exception:
        return []
    for idx_c, c in enumerate(contraintes):
        if c.Type not in ('Distance', 'DistanceX', 'DistanceY'):
            continue
        if c.Name and _est_contrainte_gorge(c.Name):
            continue
        if abs(c.Value - rayon_cible) <= _TOLERANCE_GEOM_MM:
            candidats.append((sketch, idx_c))
    return candidats


def _chercher_parametre_par_valeur(body, edge):
    """
    Tout dernier repli, le plus générique : recherche parmi TOUS les
    paramètres nommés du Body (lister_parametres_body() -- contraintes
    Radius/Diameter/Distance/DistanceX/DistanceY/Angle de tous les
    Sketch, + alias de Spreadsheet -- la même liste, déjà fiable, qui
    remplit combo_param dans le flux manuel) celui dont la VALEUR
    correspond au rayon de l'arête testée (tolérance _TOLERANCE_GEOM_MM).

    Correctif du 03/09/2026 (troisième test réel, diagnostic ciblé
    exécuté par l'utilisateur sur ses deux cas concrets) : couvre les cas
    où ni la correspondance géométrique directe (3.2, y compris la
    coaxialité) ni la correspondance par axe de révolution (3.2ter)
    n'aboutissent à une contrainte nommée -- par exemple une géométrie de
    Sketch trouvée mais pilotée par autre chose qu'une contrainte
    Radius/Diameter directe (égalité avec une autre géométrie, tangence,
    etc.), ou un sketch de profil de révolution qui ne porte tout
    simplement aucune contrainte Distance/DistanceX/DistanceY.

    Limite assumée (documentée en §6 de la spec) : correspondance par
    VALEUR seule, aucune vérification géométrique -- risque de faux
    positif si un paramètre sans rapport partage la même valeur par
    coïncidence. Ambiguïté (plusieurs paramètres à la même valeur)
    correctement interceptée par l'appelant ('ambigu'), mais une
    coïncidence isolée à un seul paramètre ne l'est pas.

    Retourne la liste des noms de paramètres correspondants.
    """
    if not FREECAD_DISPONIBLE or body is None or edge is None:
        return []
    if not (hasattr(edge, 'Curve') and hasattr(edge.Curve, 'Radius')):
        return []
    rayon_cible = edge.Curve.Radius
    params = lister_parametres_body(body)
    return [nom for nom, val in params.items()
            if abs(val - rayon_cible) <= _TOLERANCE_GEOM_MM]


def trouver_parametre_pour_edge(body, arete_info) -> dict:
    """
    Résout le paramètre Ø/rayon associé à une arête sélectionnée (voir
    resoudre_arete_selectionnee()), en tentant dans l'ordre :
      1. recoupement géométrique direct dans les Sketch du body ;
      2. si échec, remontée à travers un Fillet/Chamfer PartDesign en fin
         d'arbre (_aretes_avant_dressup) puis nouvel essai (avec repli
         Revolution/Groove, 3.2ter, à chaque étape) ;
      3. recoupement sur une primitive sans Sketch (Radius direct) ;
      4. tout dernier repli, par VALEUR seule parmi tous les paramètres
         nommés du Body (_chercher_parametre_par_valeur, 03/09/2026).
    Une géométrie de Sketch trouvée en (1)/(2) mais sans contrainte
    Radius/Diameter directe n'est plus retournée immédiatement -- mise en
    réserve, utilisée seulement si (3) et (4) n'aboutissent pas non plus
    (correctif du 03/09/2026, voir §0 de la spec).

    Lecture seule — ne modifie jamais rien. Retourne un dict :
      {'statut': 'nomme', 'nom': str, 'valeur_mm': float,
       'sketch': obj|None, 'idx_geo': int|None}
          paramètre déjà nommé, prêt à l'usage (combo_param) ; sketch/
          idx_geo fournis pour la surbrillance (3.5) quand connus --
          None pour une correspondance trouvée uniquement par valeur (4).
      {'statut': 'sans_nom', 'sketch': obj, 'idx_geo': int|None,
       'idx_contrainte': int, 'type': 'Radius'|'Diameter'|'Distance'|
       'DistanceX'|'DistanceY', 'nom_propose': str, 'valeur_mm': float}
          géométrie et contrainte trouvées, pas encore nommées — nom
          proposé à afficher dans un champ éditable (spec point C),
          confirmé ensuite via nommer_parametre().
      {'statut': 'geometrie_sans_contrainte', 'sketch': obj, 'idx_geo': int,
       'valeur_mm': float}
          géométrie de sketch trouvée, mais aucune contrainte
          Radius/Diameter ne la pilote, et aucun repli suivant n'a
          abouti non plus (rien à nommer).
      {'statut': 'primitive', 'objet': obj, 'valeur_mm': float}
          trouvé sur une Property Radius de primitive (pas de Sketch,
          pas d'auto-nommage possible — voir §6 de la spec).
      {'statut': 'ambigu', 'candidats': [...]}
          plusieurs correspondances possibles, aucune retenue (spec
          point D — retour au flux manuel).
      {'statut': 'aucun'}
          aucune correspondance, quelle que soit la méthode — retour au
          flux manuel existant.
    """
    if not FREECAD_DISPONIBLE or body is None or arete_info is None:
        return {'statut': 'aucun'}

    objet_proprietaire, nom_edge, edge = arete_info
    feature_climb = _feature_pour_climb(objet_proprietaire, body)
    repli_sans_contrainte = None   # 'geometrie_sans_contrainte' le plus
                                    # récent -- gardé en réserve, voir plus bas

    def _resoudre_sur(edge_a_tester, objet_origine=None):
        nonlocal repli_sans_contrainte
        candidats = _chercher_geometrie_correspondante(body, edge_a_tester)
        if len(candidats) > 1:
            return {'statut': 'ambigu', 'candidats': candidats}
        if len(candidats) == 1:
            sketch, idx_geo = candidats[0]
            try:
                contraintes = sketch.Constraints
            except Exception:
                contraintes = []
            for idx_c, c in enumerate(contraintes):
                if c.Type in ('Radius', 'Diameter') and c.First == idx_geo:
                    if c.Name and c.Name.strip():
                        return {'statut': 'nomme', 'nom': c.Name, 'valeur_mm': c.Value,
                                'sketch': sketch, 'idx_geo': idx_geo}
                    prefixe = 'R' if c.Type == 'Radius' else 'D'
                    return {
                        'statut': 'sans_nom', 'sketch': sketch, 'idx_geo': idx_geo,
                        'idx_contrainte': idx_c, 'type': c.Type,
                        'nom_propose': proposer_nom_parametre(body, prefixe),
                        'valeur_mm': c.Value,
                    }
            # Géométrie trouvée mais aucune contrainte Radius/Diamètre ne
            # la pilote -- gardé en réserve (correctif du 03/09/2026)
            # plutôt que conclu immédiatement : un repli plus générique
            # (valeur seule, tous paramètres du Body) peut encore trouver
            # mieux, voir plus bas.
            if repli_sans_contrainte is None:
                repli_sans_contrainte = {'statut': 'geometrie_sans_contrainte',
                                          'sketch': sketch, 'idx_geo': idx_geo,
                                          'valeur_mm': edge_a_tester.Curve.Radius}
            return None

        # Repli -- rayon dérivé d'une cote Distance/DistanceX/DistanceY
        # depuis l'axe d'une PartDesign::Revolution/Groove (correctif du
        # 03/09/2026 -- cas réel remonté par l'utilisateur, convention de
        # cotation confirmée : la géométrie n'est pas un cercle dessiné,
        # rien à trouver ci-dessus).
        if objet_origine is not None and getattr(objet_origine, 'TypeId', '') in _TYPES_REVOLUTION:
            candidats_rev = _chercher_distance_axe_pour_revolution(objet_origine, edge_a_tester)
            if len(candidats_rev) > 1:
                return {'statut': 'ambigu', 'candidats': candidats_rev}
            if len(candidats_rev) == 1:
                sketch_rev, idx_c = candidats_rev[0]
                c = sketch_rev.Constraints[idx_c]
                if c.Name and c.Name.strip():
                    return {'statut': 'nomme', 'nom': c.Name, 'valeur_mm': c.Value,
                            'sketch': sketch_rev, 'idx_geo': None}
                return {
                    'statut': 'sans_nom', 'sketch': sketch_rev, 'idx_geo': None,
                    'idx_contrainte': idx_c, 'type': c.Type,
                    'nom_propose': proposer_nom_parametre(body, 'R'),
                    'valeur_mm': c.Value,
                }
        return None

    resultat = _resoudre_sur(edge, feature_climb)
    if resultat is not None:
        return resultat

    # Repli — remontée à travers un Fillet/Chamfer PartDesign (spec §3.2bis)
    for objet_origine, nom_edge_origine in _aretes_avant_dressup(feature_climb, nom_edge):
        if objet_origine is feature_climb and nom_edge_origine == nom_edge:
            continue  # identique à l'arête déjà testée ci-dessus
        edge_origine = _edge_depuis_nom(objet_origine, nom_edge_origine)
        if (edge_origine is None or not hasattr(edge_origine, 'Curve')
                or not hasattr(edge_origine.Curve, 'Radius')):
            continue   # arête d'origine non circulaire (ex. Part.Line
                       # sur un Fillet/Chamfer touchant aussi des arêtes
                       # droites) -- pas une candidate valide, voir
                       # correctif crash 'Part.Line' du 03/09/2026
        resultat = _resoudre_sur(edge_origine, objet_origine)
        if resultat is not None:
            return resultat

    # Repli — primitive sans Sketch
    primitives = _chercher_primitive_correspondante(body, edge)
    if len(primitives) > 1:
        return {'statut': 'ambigu', 'candidats': primitives}
    if len(primitives) == 1:
        return {'statut': 'primitive', 'objet': primitives[0],
                'valeur_mm': edge.Curve.Radius}

    # Tout dernier repli — correspondance par valeur uniquement, tous
    # paramètres nommés du Body confondus (correctif du 03/09/2026,
    # troisième test réel -- voir _chercher_parametre_par_valeur()).
    noms_par_valeur = _chercher_parametre_par_valeur(body, edge)
    if len(noms_par_valeur) > 1:
        return {'statut': 'ambigu', 'candidats': noms_par_valeur}
    if len(noms_par_valeur) == 1:
        return {'statut': 'nomme', 'nom': noms_par_valeur[0],
                'valeur_mm': edge.Curve.Radius, 'sketch': None, 'idx_geo': None}

    if repli_sans_contrainte is not None:
        return repli_sans_contrainte

    return {'statut': 'aucun'}


def nommer_parametre(sketch, idx_contrainte: int, nom_valide: str) -> bool:
    """
    Nomme (ou renomme) la contrainte d'index idx_contrainte d'un sketch.
    nom_valide doit avoir été confirmé par l'utilisateur dans le champ
    éditable (spec point C — jamais de renommage silencieux ; cette
    fonction ne fait qu'exécuter la confirmation).
    Retourne True si le renommage a réussi.
    """
    if not FREECAD_DISPONIBLE or sketch is None or not nom_valide:
        return False
    try:
        sketch.renameConstraint(idx_contrainte, nom_valide)
        sketch.Document.recompute()
        return True
    except Exception:
        return False


def nom_lcs_disponible(doc, nom_lcs: str) -> bool:
    """
    True si nom_lcs ne collisionne avec aucun objet existant du document
    (comparaison sur le Label — ce que l'utilisateur voit et saisit).
    Utilisé pour refuser la validation en cas de champ vide ou de
    collision, jamais pour renommer silencieusement (spec point A).
    """
    if not FREECAD_DISPONIBLE or doc is None or not nom_lcs or not nom_lcs.strip():
        return False
    nom_lcs = nom_lcs.strip()
    return not any(getattr(o, 'Label', None) == nom_lcs for o in doc.Objects)


def creer_lcs_sur_arete(body, objet_proprietaire, nom_edge: str,
                         nom_lcs: str, offset_mm: float = 0.0):
    """
    Crée un LCS (PartDesign::CoordinateSystem) dans body, attaché en mode
    concentrique sur l'arête circulaire nom_edge de objet_proprietaire,
    avec un offset le long de son axe (AttachmentOffset) — même mécanisme
    d'attachement que creer_sketch_sur_plan(), avec MapMode='Concentric'
    au lieu de 'FlatFace'.

    nom_lcs doit avoir été validé au préalable via nom_lcs_disponible()
    (spec point A — nom entièrement saisi par l'utilisateur ; cette
    fonction ne revérifie pas la disponibilité du nom).
    """
    if not FREECAD_DISPONIBLE:
        raise RuntimeError(tr("FreeCAD not available"))
    lcs = body.newObject('PartDesign::CoordinateSystem', nom_lcs)
    lcs.Label = nom_lcs
    lcs.MapMode = 'Concentric'
    lcs.AttachmentSupport = [(objet_proprietaire, [nom_edge])]
    lcs.AttachmentOffset = App.Placement(App.Vector(0, 0, offset_mm), App.Rotation())
    body.Document.recompute()
    return lcs


def ajuster_offset_lcs(lcs, offset_mm: float) -> None:
    """
    Met à jour l'offset (axe local Z) d'un LCS déjà créé par
    creer_lcs_sur_arete(), et recalcule — utilisé pour l'aperçu temps réel
    pendant l'ajustement à l'œil (spec point B).
    """
    if not FREECAD_DISPONIBLE or lcs is None:
        return
    lcs.AttachmentOffset = App.Placement(App.Vector(0, 0, offset_mm), App.Rotation())
    lcs.Document.recompute()


# =============================================================================
# RE-ROUTAGE DES LIENS  (Etape B du support des liens, 06/09/2026)
# =============================================================================
# Quand un composant lie recoit son premier joint, un conteneur App::Part
# « ... equipe » est cree dans son document source pour regrouper le corps et
# le joint. Le lien de l'assemblage continue pourtant de pointer sur le seul
# Body : le joint n'apparait donc pas dans l'assemblage. Il faut faire pointer
# le lien sur le conteneur -- manipulation validee manuellement par
# l'utilisateur avant automatisation.
# Voir claude/spec_support_liens_assemblage.md §7.


def liens_vers(obj) -> list:
    """
    Retourne les liens (App::Link / App::LinkElement / App::LinkGroup) qui
    pointent DIRECTEMENT sur `obj`, dans les documents actuellement ouverts.

    Limite assumee : InList ne connait que les documents ouverts. Un
    assemblage ferme pointant sur ce Body ne sera pas re-route -- il restera
    valide (le Body existe toujours dans le conteneur) mais n'affichera pas
    le joint.
    """
    if not FREECAD_DISPONIBLE or obj is None:
        return []
    resultat = []
    try:
        for parent in getattr(obj, 'InList', []):
            if getattr(parent, 'TypeId', '') not in _TYPES_LIENS:
                continue
            try:
                if parent.LinkedObject is obj:
                    resultat.append(parent)
            except Exception:
                continue
    except Exception as e:
        print(f"[ORing liens] liens_vers AVERT : {e}")
    return resultat


def rerouter_lien(lien, nouvelle_cible):
    """
    Fait pointer `lien` sur `nouvelle_cible` et retourne son etat d'origine,
    a repasser a restaurer_lien(). Retourne None si rien n'a ete fait.

    Compensation de placement. Avec LinkTransform=False (cas par defaut),
    LinkPlacement REMPLACE le placement de l'objet lie :

        avant  : monde = LinkPlacement . geometrie
        apres  : monde = LinkPlacement . Placement_ancienne_cible . geometrie

    car le Placement propre de l'ancienne cible s'applique desormais A
    L'INTERIEUR du conteneur. Pour conserver la position exacte :

        LinkPlacement' = LinkPlacement . Placement_ancienne_cible^-1

    Avec LinkTransform=True, le placement de l'objet lie etait deja compose :
    aucune compensation.

    Dans un assemblage de l'atelier Assembly le cas ne se presente pas -- il
    maintient lui-meme des placements identite via ensureIdentityPlacements().
    Cette compensation est un filet de securite pour les assemblages a liens
    construits autrement.
    """
    if not FREECAD_DISPONIBLE or lien is None or nouvelle_cible is None:
        return None
    try:
        ancienne = lien.LinkedObject
    except Exception:
        return None
    if ancienne is None or ancienne is nouvelle_cible:
        return None

    etat = {
        'ancienne_cible': ancienne,
        'LinkPlacement': None,
        # Aspect capture AVANT le changement de cible : le ViewProviderLink
        # perd ShapeAppearance/Transparency en passant d'un Body a un
        # App::Part (mesure le 06/09/2026), donc la couleur du composant dans
        # l'assemblage. Voir _capturer_aspect_lien().
        'aspect': _capturer_aspect_lien(lien),
    }
    try:
        plc_ancien = App.Placement(lien.LinkPlacement)
        etat['LinkPlacement'] = plc_ancien
    except Exception:
        plc_ancien = None

    try:
        lien.LinkedObject = nouvelle_cible
    except Exception as e:
        print(f"[ORing liens] re-routage de '{getattr(lien, 'Label', '?')}' "
              f"impossible : {e}")
        return None

    # Compensation eventuelle
    try:
        if (plc_ancien is not None
                and not getattr(lien, 'LinkTransform', False)):
            plc_cible = getattr(ancienne, 'Placement', None)
            if plc_cible is not None and not _placement_est_identite(plc_cible):
                lien.LinkPlacement = plc_ancien.multiply(plc_cible.inverse())
                print(f"[ORing liens] LinkPlacement compense sur "
                      f"'{lien.Label}' (l'ancienne cible portait un "
                      f"Placement propre non nul)")
    except Exception as e:
        print(f"[ORing liens] compensation LinkPlacement AVERT : {e}")

    # Reposer l'aspect d'origine : sans cela le composant perd sa couleur dans
    # l'assemblage, le ViewProviderLink n'exposant plus ShapeAppearance une
    # fois qu'il pointe un App::Part.
    _restaurer_aspect_lien(lien, etat.get('aspect'))

    print(f"[ORing liens] '{lien.Label}' re-route : "
          f"'{getattr(ancienne, 'Label', '?')}' -> "
          f"'{getattr(nouvelle_cible, 'Label', '?')}'")
    return etat


def _capturer_aspect_lien(lien) -> dict:
    """
    Capture l'aspect d'affichage d'un lien AVANT son re-routage.

    Le Gui::ViewProviderLink change son jeu de proprietes selon le type de
    l'objet lie : pointant un PartDesign::Body il expose `ShapeAppearance` et
    `Transparency` (et porte donc la couleur du composant dans l'assemblage) ;
    pointant un App::Part il ne les expose plus du tout -- mesure le 06/09/2026
    sur le lien 'Alesage', dont le ShapeAppearance
    Material(Diffuse=(0.7255, 0.9725, 0.9843), Transparency=0.0) a disparu au
    profit d'un aspect par defaut.
    """
    aspect = {}
    if not FREECAD_DISPONIBLE or lien is None:
        return aspect
    try:
        vo = lien.ViewObject
    except Exception:
        return aspect
    if vo is None:
        return aspect
    for nom in ('ShapeColor', 'Transparency'):
        try:
            if hasattr(vo, nom):
                aspect[nom] = getattr(vo, nom)
        except Exception:
            pass
    try:
        if hasattr(vo, 'ShapeAppearance'):
            materiaux = list(vo.ShapeAppearance)
            aspect['ShapeAppearance'] = materiaux
            if len(materiaux) == 1:
                m = materiaux[0]
                # UNIQUEMENT le triplet RGB : la 4e composante de DiffuseColor
                # ne suit PAS la meme convention entre ShapeAppearance (1.0
                # pour un materiau opaque) et ShapeMaterial (0.0 pour le meme
                # etat) -- constate le 06/09/2026 sur le meme lien du meme
                # document. La transferer telle quelle faussait la couleur.
                # La transparence est portee par son propre champ.
                _c = tuple(m.DiffuseColor)
                aspect['_uniforme'] = ((_c[0], _c[1], _c[2]),
                                       float(m.Transparency))
    except Exception:
        pass
    return aspect


def _restaurer_aspect_lien(lien, aspect: dict) -> None:
    """
    Repose sur `lien` l'aspect capture avant re-routage.

    Deux voies, dans cet ordre :

    1. `ShapeAppearance` existe encore -> on la reaffecte telle quelle
       (cas d'un rollback vers un Body, ou d'une version de FreeCAD qui
       conserverait la propriete).
    2. Elle a disparu (cas du re-routage vers un App::Part) -> repli sur
       `OverrideMaterial` + `ShapeMaterial`, qui survivent au re-routage et
       sont le mecanisme deja eprouve pour la mise en transparence des liens.
       Uniquement si l'aspect capture etait UNIFORME (une seule entree) : un
       aspect par face ne peut pas etre reproduit par un materiau unique, et
       reappliquer arbitrairement la premiere entree serait pire que le defaut.

    Non bloquant : un echec ici ne doit jamais compromettre le re-routage.
    """
    if not FREECAD_DISPONIBLE or lien is None or not aspect:
        return
    try:
        vo = lien.ViewObject
    except Exception:
        return
    if vo is None:
        return

    if 'ShapeAppearance' in aspect and hasattr(vo, 'ShapeAppearance'):
        try:
            vo.ShapeAppearance = aspect['ShapeAppearance']
            for nom in ('ShapeColor', 'Transparency'):
                if nom in aspect and hasattr(vo, nom):
                    try:
                        setattr(vo, nom, aspect[nom])
                    except Exception:
                        pass
            return
        except Exception:
            pass

    # PAS DE REPLI VIA OverrideMaterial -- retire le 06/09/2026 apres mesure.
    #
    # `OverrideMaterial = True` sur un App::Link impose son ShapeMaterial
    # unique a TOUT le sous-arbre du lien, conteneur « ... equipe » compris,
    # donc aux corps ORing qu'il contient. Le repli ecrasait la couleur matiere
    # des joints -- celle que appliquer_couleur_materiau() venait de poser.
    # Constate par l'utilisateur : « le joint precedemment insere a perdu sa
    # couleur ».
    #
    # C'est structurel, pas une question de valeur transferee : un override
    # pose au niveau du lien ne peut pas coexister avec des couleurs distinctes
    # a l'interieur du composant. On ne reconstitue donc pas l'aspect ici ; on
    # signale la perte, qui doit etre traitee au niveau de la CONCEPTION
    # (couleur portee par le Body dans le document source, ou pas de
    # re-routage du tout) -- voir claude/spec_support_liens_assemblage.md.
    if aspect.get('ShapeAppearance') or aspect.get('ShapeColor') is not None:
        print(f"[ORing liens] '{getattr(lien, 'Label', '?')}' : l'aspect porte "
              f"par le lien n'est pas transferable vers un App::Part "
              f"(FreeCAD retire ShapeAppearance) -- le composant se rend "
              f"desormais avec l'aspect de son Body dans le document source")


def restaurer_lien(lien, etat) -> None:
    """Annule un rerouter_lien() : cible et LinkPlacement d'origine."""
    if not FREECAD_DISPONIBLE or lien is None or not etat:
        return
    try:
        cible = etat.get('ancienne_cible')
        if cible is not None:
            lien.LinkedObject = cible
        plc = etat.get('LinkPlacement')
        if plc is not None:
            lien.LinkPlacement = plc
        _restaurer_aspect_lien(lien, etat.get('aspect'))
    except Exception as e:
        print(f"[ORing liens] restauration AVERT : {e}")


def _placement_est_identite(plc, tol: float = 1e-9) -> bool:
    """True si `plc` est (a la tolerance pres) le placement identite."""
    try:
        return (plc.Base.Length < tol and abs(plc.Rotation.Angle) < tol)
    except Exception:
        return False


def rafraichir_assemblages(documents) -> None:
    """
    Remet les liaisons d'assemblage en coherence apres un re-routage de lien.

    Sequence calquee sur ce que fait l'atelier Assembly lui-meme a la
    validation du dialogue de liaison (JointObject.py::accept()) :
    recompute des documents, puis recompute FORCE de chaque
    Assembly::AssemblyObject -- ce qui declenche Joint.execute() ->
    updateJCSPlacements() et rétablit les liaisons (sans ce recalcul, la
    liaison reste periMee et le composant devient immobile : constate par
    l'utilisateur le 06/09/2026).

    ON N'APPELLE JAMAIS assembly.solve(). Le solveur deplacerait les
    composants le long de leurs degres de liberte restants -- observe sur un
    cas reel : une liaison cylindrique a fait glisser un arbre de 17 mm et
    l'a fait tourner de 186 deg, simplement parce que le dialogue de liaison
    avait ete rouvert. Creer une gorge de joint ne doit pas deplacer un
    composant sous-contraint.
    """
    if not FREECAD_DISPONIBLE or not documents:
        return
    vus = set()
    ordonnes = []
    for d in documents:
        if d is None or d.Name in vus:
            continue
        vus.add(d.Name)
        ordonnes.append(d)

    for d in ordonnes:
        try:
            d.recompute()
        except Exception as e:
            print(f"[ORing liens] recompute '{d.Name}' AVERT : {e}")

    for d in ordonnes:
        try:
            for obj in d.Objects:
                if getattr(obj, 'TypeId', '') == 'Assembly::AssemblyObject':
                    obj.recompute(True)
                    print(f"[ORing liens] liaisons rafraichies : "
                          f"'{obj.Label}' ({d.Name})")
        except Exception as e:
            print(f"[ORing liens] rafraichissement assemblage AVERT : {e}")


def basculer_transparence_body(body, transparence: int):
    """
    Force la transparence d'affichage d'un Body (0-100) et retourne
    l'ancienne valeur, pour restauration ultérieure — utilisé pendant
    l'étape d'ajustement du LCS pour qu'il reste visible dans la matière
    (spec point B). Sans effet si le Body n'a pas de ViewObject.
    """
    if (not FREECAD_DISPONIBLE or body is None
            or not hasattr(body, 'ViewObject') or body.ViewObject is None):
        return None
    ancienne = body.ViewObject.Transparency
    body.ViewObject.Transparency = transparence
    return ancienne


# _TYPES_LIENS est defini en tete de module (section BODY ET OBJETS).


def capturer_aspect_corps(body) -> dict:
    """
    Capture l'aspect d'affichage d'un corps AVANT la creation d'une gorge, avec
    l'inventaire de ses features.

    Ce qu'un PartDesign::Body affiche, c'est son Tip. La creation de la gorge
    ajoute un Mirrored qui devient le nouveau Tip -- un objet NEUF, donc dote
    d'une couleur au hasard quand FreeCAD est regle sur « couleur aleatoire ».
    Le ShapeColor du Body ne bouge pas, mais ce n'est plus lui qu'on voit :
    le composant change de couleur dans son propre fichier (constate le
    06/09/2026 : alesage bleu clair devenu rose, dans l'assemblage comme dans
    alesage.FCStd).

    L'inventaire des features permet de ne reappliquer l'aspect qu'aux
    NOUVELLES, sans toucher a ce qui existait.
    """
    etat = {}
    if not FREECAD_DISPONIBLE or body is None:
        return etat

    # LIRE LE TIP, PAS LE BODY (correctif du 06/09/2026, sur mesure).
    #
    # Ce qu'un PartDesign::Body affiche, c'est son Tip -- et c'est le Tip que
    # FreeCAD colore quand l'utilisateur change l'apparence du corps. Le Body,
    # lui, garde souvent une couleur ancienne. Mesure au demarrage, avant toute
    # action de la macro :
    #
    #     Body : Diffuse=(0.7412, 0.7451, 0.4745)   <- beige, valeur perimee
    #     Tip  : Diffuse=(0.3490, 0.9098, 0.1961)   <- vert, la vraie couleur
    #
    # Capturer le Body revenait donc a capturer une couleur que plus personne
    # ne voyait, puis a l'imposer au nouveau Tip : le correctif cense preserver
    # la couleur etait ce qui la detruisait.
    source = getattr(body, 'Tip', None) or body
    try:
        vo = source.ViewObject
    except Exception:
        return etat
    if vo is None:
        return etat
    etat['_source'] = getattr(source, 'Name', '?')
    for nom in ('ShapeColor', 'Transparency'):
        try:
            if hasattr(vo, nom):
                etat[nom] = getattr(vo, nom)
        except Exception:
            pass
    try:
        if hasattr(vo, 'ShapeAppearance'):
            materiaux = list(vo.ShapeAppearance)
            if len(materiaux) == 1:
                etat['ShapeAppearance'] = materiaux
    except Exception:
        pass
    try:
        etat['features'] = {getattr(f, 'Name', '') for f in getattr(body, 'Group', [])}
    except Exception:
        etat['features'] = set()
    return etat


def restaurer_aspect_corps(body, etat: dict) -> None:
    """
    Reapplique l'aspect capture au Body, a son Tip et a ses features NOUVELLES.

    Meme principe que oring_3d.appliquer_couleur_materiau() pour le tore, qui
    colorie « body + Tip + features » -- c'est precisement ce traitement qui
    manquait au corps porteur, d'ou la couleur aleatoire visible apres creation
    de la gorge.

    Les features presentes AVANT la creation ne sont pas touchees : si elles
    portaient des aspects distincts, ils sont conserves. Seules celles ajoutees
    par la macro recoivent l'aspect du corps.
    """
    if not FREECAD_DISPONIBLE or body is None or not etat:
        return

    anciennes = etat.get('features') or set()
    cibles = [body]
    tip = getattr(body, 'Tip', None)
    if tip is not None and tip not in cibles:
        cibles.append(tip)
    # Types a NE JAMAIS repeindre : esquisses (masquees de toute facon) et
    # surtout DATUMS -- plans, axes, points, reperes. Leur aspect (jaune
    # semi-transparent pour un plan) est leur apparence normale dans FreeCAD.
    # Constate le 06/09/2026 : PlanMedianGorge001 passait de
    # Diffuse=(1.0, 0.8431, 0.0, 0.6) Transp=0.6 a la couleur opaque du corps.
    _TYPES_A_EPARGNER = (
        'Sketcher::SketchObject',
        'PartDesign::Plane', 'PartDesign::Line', 'PartDesign::Point',
        'PartDesign::CoordinateSystem', 'PartDesign::ShapeBinder',
        'PartDesign::SubShapeBinder',
        'App::Plane', 'App::Line', 'App::Point', 'App::Origin',
        'App::LocalCoordinateSystem', 'App::DatumElement',
    )
    try:
        for feat in getattr(body, 'Group', []):
            if getattr(feat, 'Name', '') in anciennes:
                continue          # feature preexistante : on n'y touche pas
            if getattr(feat, 'TypeId', '') in _TYPES_A_EPARGNER:
                continue
            if feat not in cibles:
                cibles.append(feat)
    except Exception:
        pass

    n_ok = 0
    for obj in cibles:
        try:
            vo = obj.ViewObject
            if vo is None:
                continue
            if 'ShapeAppearance' in etat and hasattr(vo, 'ShapeAppearance'):
                try:
                    vo.ShapeAppearance = etat['ShapeAppearance']
                except Exception:
                    pass
            for nom in ('ShapeColor', 'Transparency'):
                if nom in etat and hasattr(vo, nom):
                    try:
                        setattr(vo, nom, etat[nom])
                    except Exception:
                        pass
            n_ok += 1
        except Exception:
            pass
    print(f"[ORing aspect] corps porteur '{getattr(body, 'Label', '?')}' : "
          f"aspect reapplique sur {n_ok}/{len(cibles)} objet(s)")


def capturer_transparence(obj):
    """
    Capture l'etat de transparence d'affichage de `obj` SANS le modifier,
    sous une forme opaque a repasser telle quelle a
    restaurer_transparence(). Retourne None si l'objet n'expose aucun
    mecanisme de transparence exploitable.

    Deux mecanismes selon le type d'objet :

    - objet geometrique classique (PartDesign::Body, Part::Feature...) :
      propriete entiere `ViewObject.Transparency` (0-100) ;
    - App::Link / App::LinkElement / App::LinkGroup : le
      `Gui::ViewProviderLink` n'expose PAS de propriete `Transparency`
      (verifie sur FreeCAD 1.1 build 3, diagnostic du 06/09/2026). La
      seule voie est `OverrideMaterial` + `ShapeMaterial`, dont la
      transparence est un FLOTTANT 0.0-1.0 (et non un entier 0-100).
    """
    if not FREECAD_DISPONIBLE or obj is None:
        return None
    try:
        vo = obj.ViewObject
    except Exception:
        return None
    if vo is None:
        return None

    est_lien = (getattr(obj, 'TypeId', '') in _TYPES_LIENS
                or not hasattr(vo, 'Transparency'))
    if est_lien:
        if not (hasattr(vo, 'ShapeMaterial') and hasattr(vo, 'OverrideMaterial')):
            return None
        try:
            mat = vo.ShapeMaterial
            return {
                'mode': 'link',
                'OverrideMaterial': bool(vo.OverrideMaterial),
                'Transparency': float(mat.Transparency),
                'DiffuseColor': tuple(mat.DiffuseColor),
            }
        except Exception:
            return None
    try:
        return {'mode': 'body', 'Transparency': int(vo.Transparency)}
    except Exception:
        return None


def appliquer_transparence(obj, transparence: int):
    """
    Force la transparence d'affichage de `obj` (0-100) et retourne son etat
    d'origine, a repasser a restaurer_transparence(). Retourne None si
    l'objet n'expose aucun mecanisme de transparence.

    Cas du lien : `ShapeMaterial` renvoie une COPIE de la structure
    materiau -- une mutation en place (`vo.ShapeMaterial.Transparency = x`)
    est silencieusement sans effet, la propriete doit etre REAFFECTEE.
    `OverrideMaterial` est force a True le temps de l'effet, puis remis a
    sa valeur d'origine par restaurer_transparence().

    On agit toujours sur le LIEN, dans le document d'assemblage, jamais sur
    l'objet lie dans son document source : un effet visuel temporaire ne
    doit pas marquer comme modifie le fichier d'un composant, que
    l'utilisateur se verrait alors proposer d'enregistrer a la fermeture.
    """
    etat = capturer_transparence(obj)
    if etat is None:
        return None
    try:
        vo = obj.ViewObject
        if etat['mode'] == 'link':
            valeur = max(0.0, min(1.0, float(transparence) / 100.0))
            mat = vo.ShapeMaterial
            mat.Transparency = valeur
            couleur = tuple(mat.DiffuseColor)
            if len(couleur) == 4:
                # 4e composante = transparence du materiau ; certaines
                # versions s'appuient dessus plutot que sur .Transparency.
                mat.DiffuseColor = (couleur[0], couleur[1], couleur[2], valeur)
            vo.ShapeMaterial = mat          # reaffectation obligatoire
            vo.OverrideMaterial = True
        else:
            vo.Transparency = int(transparence)
        return etat
    except Exception:
        return None


def restaurer_transparence(obj, etat) -> None:
    """
    Restaure exactement l'etat capture par capturer_transparence() /
    appliquer_transparence(). Non bloquant.
    """
    if not FREECAD_DISPONIBLE or obj is None or not etat:
        return
    try:
        vo = obj.ViewObject
        if vo is None:
            return
        if etat.get('mode') == 'link':
            mat = vo.ShapeMaterial
            mat.Transparency = float(etat['Transparency'])
            try:
                mat.DiffuseColor = tuple(etat['DiffuseColor'])
            except Exception:
                pass
            vo.ShapeMaterial = mat
            vo.OverrideMaterial = bool(etat['OverrideMaterial'])
        else:
            vo.Transparency = int(etat['Transparency'])
    except Exception:
        pass


def lister_objets_transparentisables(doc=None) -> list:
    """
    Retourne les objets VISIBLES du document sur lesquels une mise en
    transparence a un sens :

    - les `PartDesign::Body` (assemblage mono-document, comportement
      historique, inchange) ;
    - les liens `App::Link` / `App::LinkElement` / `App::LinkGroup`
      (assemblage multi-fichiers, ou le document actif ne contient aucun
      Body -- ils vivent dans les documents sources).

    Volontairement limite a doc.Objects, sans recursion : dans un
    assemblage de l'atelier Assembly, les liens sont des objets de premier
    niveau du document (confirme par le diagnostic du 06/09/2026), meme
    lorsqu'ils apparaissent dans le Group de l'Assembly::AssemblyObject.
    """
    if not FREECAD_DISPONIBLE:
        return []
    if doc is None:
        doc = get_document_actif()
    if doc is None:
        return []
    resultat = []
    try:
        for obj in doc.Objects:
            type_id = getattr(obj, 'TypeId', '')
            if type_id != 'PartDesign::Body' and type_id not in _TYPES_LIENS:
                continue
            if not getattr(obj, 'Visibility', False):
                continue
            resultat.append(obj)
    except Exception as e:
        print(f"[ORing] Inventaire transparence AVERT : {e}")
    return resultat


def basculer_transparence_document(doc, transparence: int = 85) -> dict:
    """
    Force la transparence d'affichage de TOUS les composants visibles du
    document (Body ET liens, 0-100) et retourne un snapshot
    {nom_objet: etat}, a repasser tel quel a
    restaurer_transparence_document().

    Demande utilisateur du 05/09/2026 (ergonomie de l'assistant de creation
    du LCS depuis une arete) : pendant que le dialogue est ouvert, tous les
    composants passent en transparence pour reperer visuellement le lieu
    d'insertion ; l'aspect d'origine est restaure a la fermeture, quelle
    qu'en soit l'issue. Remplace l'ancien basculer_transparence_body()
    (60 %, corps portant la gorge uniquement) pour cet usage.

    Correctif du 06/09/2026 (Lot 1 du support des liens) : la boucle ne
    filtrait que les `PartDesign::Body` de doc.Objects. Dans un assemblage
    multi-fichiers, doc.Objects n'en contient AUCUN -- le snapshot revenait
    vide, aucune transparence n'etait appliquee, et aucune exception
    n'etait levee (echec silencieux). Les liens sont desormais traites, via
    le mecanisme `OverrideMaterial`/`ShapeMaterial` propre au
    Gui::ViewProviderLink.

    Meme principe que le survol du tableau des joints (hover_ui.py), mais
    avec un snapshot local propre a l'appelant -- aucun etat global partage,
    donc aucune interference possible entre les deux mecanismes.
    """
    snapshot = {}
    if not FREECAD_DISPONIBLE or doc is None:
        return snapshot
    try:
        for obj in lister_objets_transparentisables(doc):
            etat = appliquer_transparence(obj, transparence)
            if etat is not None:
                snapshot[obj.Name] = etat
    except Exception as e:
        print(f"[ORing] Transparence document AVERT : {e}")
    return snapshot


def reappliquer_transparence_document(doc, snapshot: dict,
                                       transparence: int = 85) -> None:
    """
    Re-applique la transparence aux objets deja presents dans `snapshot`,
    SANS toucher au snapshot : l'etat d'origine reste celui capture au
    depart, donc la restauration finale demeure exacte.

    Necessaire parce qu'un recompute du document source reconstruit le rendu
    du Gui::ViewProviderLink dans l'assemblage, qui perd alors l'override de
    materiau (constate le 06/09/2026 : la transparence disparaissait des que
    l'utilisateur changeait la position du LCS, laquelle declenche
    ajuster_offset_lcs() -> lcs.Document.recompute()).

    Pour un lien, on force deux changements de propriete distincts
    (OverrideMaterial False puis True) : reaffecter la meme valeur ne
    garantit pas que FreeCAD marque la propriete comme modifiee, donc ne
    garantit pas le re-rendu.
    """
    if not FREECAD_DISPONIBLE or doc is None or not snapshot:
        return
    for nom, etat in snapshot.items():
        try:
            obj = doc.getObject(nom)
            if obj is None:
                continue
            if etat.get('mode') == 'link':
                try:
                    obj.ViewObject.OverrideMaterial = False
                except Exception:
                    pass
            appliquer_transparence(obj, transparence)
        except Exception:
            pass


def _sous_arbre_contient_joint(obj, profondeur: int = 0,
                               vus=None) -> bool:
    """
    True si `obj` -- ou le sous-arbre qu'il expose -- contient un joint ORing.

    Reconnait aussi bien l'App::Part du joint (Name prefixe ORING_PART_PREFIX,
    porteur de la propriete `oring_version`) que son corps (PartDesign::Body
    de Label commencant par 'ORing'), pour rester robuste si l'un des deux
    manque.
    """
    if obj is None or profondeur > 5:
        return False
    if vus is None:
        vus = set()
    cle = (getattr(getattr(obj, 'Document', None), 'Name', '?'),
           getattr(obj, 'Name', '?'))
    if cle in vus:
        return False
    vus.add(cle)

    nom = getattr(obj, 'Name', '')
    if nom.startswith('ORing_') and hasattr(obj, 'oring_version'):
        return True
    if (getattr(obj, 'TypeId', '') == 'PartDesign::Body'
            and getattr(obj, 'Label', '').startswith('ORing')):
        return True

    try:
        lie = obj.getLinkedObject(True)
    except Exception:
        lie = None
    if lie is not None and lie is not obj:
        if _sous_arbre_contient_joint(lie, profondeur + 1, vus):
            return True

    try:
        for enfant in (getattr(obj, 'Group', None) or []):
            if _sous_arbre_contient_joint(enfant, profondeur + 1, vus):
                return True
    except Exception:
        pass
    return False


def neutraliser_override_materiau(doc) -> int:
    """
    Retire `OverrideMaterial` des liens dont le sous-arbre contient un joint.

    POURQUOI (06/09/2026, signale par l'utilisateur : « les joints sur arbre
    sont passes dans la couleur du corps, mais pas dans l'arbre equipe dans le
    fichier lie ») : `OverrideMaterial = True` sur un App::Link impose son
    `ShapeMaterial` UNIQUE a TOUT son sous-arbre -- conteneur « ... equipe » et
    corps ORing compris. Le joint garde sa couleur dans son document source,
    mais le lien la remplace a l'affichage de l'assemblage.

    C'est structurel : un override pose au niveau du lien ne peut pas coexister
    avec des couleurs distinctes a l'interieur du composant. Meme constat que
    celui ayant fait retirer le repli OverrideMaterial de
    `_restaurer_aspect_lien()`. Des qu'un joint vit dans le sous-arbre d'un
    lien, l'override doit donc tomber ; le composant se rend alors avec
    l'aspect de son Body dans le document source, et le joint avec sa couleur
    matiere.

    Idempotent, non bloquant. Retourne le nombre de liens neutralises.
    """
    if not FREECAD_DISPONIBLE or doc is None:
        return 0
    n = 0
    try:
        for obj in doc.Objects:
            if getattr(obj, 'TypeId', '') not in _TYPES_LIENS:
                continue
            try:
                vo = obj.ViewObject
                if vo is None or not hasattr(vo, 'OverrideMaterial'):
                    continue
                if not bool(vo.OverrideMaterial):
                    continue
                if not _sous_arbre_contient_joint(obj):
                    continue
                vo.OverrideMaterial = False
                n += 1
                print(f"[ORing couleurs] lien '{getattr(obj, 'Label', '?')}' : "
                      f"OverrideMaterial retire -- il imposait un materiau "
                      f"unique a tout le composant, joints compris")
            except Exception:
                pass
    except Exception as e:
        print(f"[ORing couleurs] neutralisation override AVERT : {e}")
    return n


def restaurer_transparence_document(doc, snapshot: dict) -> None:
    """
    Restaure exactement les transparences capturees par
    basculer_transparence_document(). Non bloquant : un objet disparu du
    document (supprime entre-temps) est simplement ignore.
    """
    if not FREECAD_DISPONIBLE or doc is None or not snapshot:
        return
    for nom, etat in snapshot.items():
        try:
            obj = doc.getObject(nom)
            if obj is None:
                continue
            restaurer_transparence(obj, etat)
        except Exception:
            pass


def afficher_lcs_en_surimpression(lcs) -> dict:
    """
    Fait ressortir un LCS pendant l'assistant de creation (demande
    utilisateur du 05/09/2026, « le LCS apparait en surimpression ») :
    rendu visible et dessine AU-DESSUS de la geometrie via la propriete
    d'affichage 'OnTopWhenSelected' combinee a une selection 3D.

    Retourne l'etat d'origine, a repasser a restaurer_affichage_lcs().
    Non bloquant : si la version de FreeCAD n'expose pas cette propriete,
    seule la transparence des corps assure la visibilite du LCS.
    """
    etat = {}
    if not FREECAD_DISPONIBLE or lcs is None:
        return etat
    try:
        vo = lcs.ViewObject
        if vo is None:
            return etat
        try:
            etat['Visibility'] = bool(vo.Visibility)
            vo.Visibility = True
        except Exception:
            pass
        if hasattr(vo, 'OnTopWhenSelected'):
            try:
                etat['OnTopWhenSelected'] = vo.OnTopWhenSelected
                vo.OnTopWhenSelected = 'Enabled'
            except Exception:
                etat.pop('OnTopWhenSelected', None)
        try:
            Gui.Selection.clearSelection()
            # Adressage a travers les liens (13/09/2026) : en mono-document,
            # selectionner() produit exactement l'appel d'avant.
            selectionner(lcs)
            etat['selection'] = True
        except Exception:
            pass
    except Exception as e:
        print(f"[ORing] Surimpression LCS AVERT : {e}")
    return etat


def restaurer_affichage_lcs(lcs, etat: dict) -> None:
    """
    Restaure l'affichage d'un LCS mis en surimpression par
    afficher_lcs_en_surimpression(), et vide la selection 3D posee a cette
    occasion (meme discipline que les correctifs « aretes blanches » des
    03-04/09/2026 : aucune selection residuelle laissee a l'utilisateur).
    """
    if not FREECAD_DISPONIBLE or not etat:
        return
    if lcs is not None:
        try:
            vo = lcs.ViewObject
            if vo is not None:
                if 'OnTopWhenSelected' in etat and hasattr(vo, 'OnTopWhenSelected'):
                    vo.OnTopWhenSelected = etat['OnTopWhenSelected']
                if 'Visibility' in etat:
                    vo.Visibility = etat['Visibility']
        except Exception:
            pass  # LCS deja supprime (annulation) -- rien a restaurer
    if etat.get('selection'):
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass


# Esquisses rendues visibles par rendre_visible_sketch_et_surligner(), avec
# leur etat d'origine. Vide a chaque lancement de la macro : le lanceur purge
# les modules metier de sys.modules (voir ORing.FCMacro).
_visibilite_sketches_avant = []


def restaurer_visibilite_sketches() -> None:
    """Restaure la visibilite des esquisses rendues visibles par la macro.

    BUGFIX (10/09/2026, signale par l'utilisateur) : la detection du
    parametre Ø/rayon rend l'esquisse porteuse visible pour montrer la
    geometrie appariee (spec Sec.3.5) -- aide visuelle utile PENDANT le
    dialogue, mais qui restait affichee apres la fermeture de la macro,
    laissant l'esquisse visible dans la vue 3D sans que rien ne l'explique.

    Depile en ordre inverse : si une meme esquisse a ete enregistree
    plusieurs fois, c'est le premier etat releve qui est finalement
    restaure -- celui d'avant la macro.
    """
    while _visibilite_sketches_avant:
        sketch, etat = _visibilite_sketches_avant.pop()
        try:
            sketch.Visibility = etat
        except Exception as erreur:
            print("[ORing] Restauration visibilite esquisse AVERT : %s" % erreur)


def rendre_visible_sketch_et_surligner(sketch, idx_geo: int = None) -> None:
    """
    Rend un sketch visible et met en surbrillance sa géométrie d'index
    idx_geo (si fourni) dans la vue 3D — spec §3.5, automatique dès qu'une
    détection réussit sur une géométrie de Sketch.

    Le nom de sous-élément ('EdgeN') utilisé pour la surbrillance est
    déduit de idx_geo + 1, une approximation qui peut être inexacte si de
    la géométrie de construction précède cette géométrie dans le Sketch —
    à vérifier en conditions réelles (voir spec §3.5). Non bloquant en cas
    d'échec : seule l'aide visuelle est perdue, comme pour _on_lcs_change().
    """
    if not FREECAD_DISPONIBLE or sketch is None:
        return
    # Relever l'etat AVANT de forcer la visibilite, pour que
    # restaurer_visibilite_sketches() puisse le rendre en fin de macro.
    try:
        _visibilite_sketches_avant.append((sketch, bool(sketch.Visibility)))
    except Exception as erreur:
        print("[ORing] Releve visibilite esquisse AVERT : %s" % erreur)
    sketch.Visibility = True
    if idx_geo is None:
        return
    try:
        Gui.Selection.clearSelection()
        # Adressage a travers les liens (13/09/2026). Le sous-element vient
        # s'ajouter au chemin ; en mono-document le chemin est vide et l'appel
        # est identique a celui d'avant.
        selectionner(sketch, sous_element=f'Edge{idx_geo + 1}')
    except Exception:
        pass  # non bloquant — juste une aide visuelle


# =============================================================================
# TEST AUTONOME (hors FreeCAD)
# =============================================================================
if __name__ == '__main__':
    print("=== Test module utils.py (hors FreeCAD) ===\n")

    print(f"FreeCAD disponible : {FREECAD_DISPONIBLE}")
    print()

    print(f"rayon_vers_diametre(15.0) = {rayon_vers_diametre(15.0)} mm")
    print(f"diametre_vers_rayon(30.0) = {diametre_vers_rayon(30.0)} mm")
    print()

    d1, d2 = 29.87, 3.53
    vol = volume_joint_torique(d1, d2)
    print(f"Volume JT d1={d1} / d2={d2} : {vol:.2f} mm3")
    print()

    obl = dimensions_oblong(d1, d2, 'arbre')
    print(f"Section oblong (au repos) : {obl}")
    print()

    placement = placement_plan_median(15.0, 2.5, 'arbre')
    print(f"Placement plan median : {placement}")
    print()

    message_info("Test", "Message d'information (mode console)")
    message_avertissement("Test", "Avertissement (mode console)")

