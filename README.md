# ORing — O-Ring and Groove Macro for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/lgpl-2.1)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-1.0+-orange.svg)](https://www.freecad.org)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-2.1-green.svg)]()

A parametric FreeCAD macro for designing, inserting, and managing O-ring groove assemblies according to international standards.

**Supported standards:** ISO 3601 · DIN 3771 · JIS B2401 · METRIC  
**Author:** Yves Guillou · **Version:** 2.1 · **License:** LGPL v2.1

---
# ORing — Release Notes v2.2

**Date:** April 2026  
**Compatibility:** FreeCAD 1.0+ · Python 3.x · PySide2

---

## What's New

### 🌐 Internationalisation (i18n)

The macro is now fully internationalised. English becomes the reference language in the source code; French remains available as the first translation.

**Automatic language detection** (priority order):
1. FreeCAD preferences (`BaseApp/Preferences/General → Language`)
2. Qt system locale
3. Python locale / environment variables
4. Fallback: English

**Force a language:** create the file `ORing/lang.txt` containing the ISO code on the first line (e.g. `fr`, `en`). If the file is absent or empty → auto-detection.

**Add a new language:** create `ORing/locales/de.json` (copy of `en.json` with translated values) and `ORing/locales/helper_de.json` (copy of `helper_en.json`). No code changes required.

**Delivered files:**

| File | Content |
|---|---|
| `modules/i18n.py` | Translation engine — language detection, JSON loading, `tr()` function |
| `locales/en.json` | 243 English keys (reference) |
| `locales/fr.json` | 317 French keys |
| `locales/helper_en.json` | 5-page getting started guide — English |
| `locales/helper_fr.json` | 5-page getting started guide — French |

---

### 🖱️ Direct open in edit mode

If an O-Ring seal is selected in the 3D view **before** launching the macro, the dialog opens directly on tab 2 with the seal parameters pre-filled in edit mode — without going through tab 3.

Equivalent to: tab 3 → select → click Edit, but in a single action.

Detection works whether the selected object is the ORing container `Part` or any sub-object it contains (Body, Sketch, etc.).

---

### 🔆 Seal highlight during modification

When a seal enters edit mode, it is **highlighted** in the FreeCAD 3D view via `Gui.Selection`. The highlight is maintained throughout the modification and automatically removed when the dialog is closed or edit mode is cancelled.

---

### ❓ Integrated getting started guide

A **`? Help`** button is added at the bottom left of the main dialog. It opens a multi-page guide explaining the prerequisites and how the macro works.

**5 pages:**
1. FreeCAD document structure
2. Mandatory named parameters
3. Local Coordinate System (LCS)
4. Technical service data (table)
5. Final checklist before launch

The guide respects the FreeCAD theme (light / dark) and is fully translated via `helper_en.json` / `helper_fr.json`.

---

## Bug Fixes

| Issue | Fix |
|---|---|
| Material displayed in English in French mode | Import of the i18n module at call time (not at import) — works around the Python cache timing issue |
| `KeyError: 'Joint'` in `_maj_synthese` | `_synth_vals` keys made stable in English, independent of the active language |
| Fluid names not translated | Internal keys in `materiaux.json` migrated to English; `en.json` and `fr.json` cover all fluids |
| Material field still in English | `_nom_mat()`: imports the i18n module at each call rather than binding at import time |
| Modules not reloaded between launches | `prerequis_helper` and `helper_i18n` added to the Python cache purge list in `ORing.py` |

---

## New file structure

```
ORing/
├── lang.txt                     ← optional: force language (e.g. "fr")
├── locales/
│   ├── en.json                  ← English reference
│   ├── fr.json                  ← French translations
│   ├── helper_en.json           ← getting started guide — English
│   └── helper_fr.json           ← getting started guide — French
└── modules/
    ├── i18n.py                  ← i18n engine
    ├── helper_i18n.py           ← structured JSON loader for the guide
    └── prerequis_helper.py      ← multi-page getting started dialog
```

---

## Migrating from v2.1

1. Copy the new files into the `ORing/` folder
2. Replace `ORing.py`, `modules/dialogue.py`, `modules/i18n.py`
3. Replace `data/materiaux.json` (fluid keys migrated to English)
4. No changes required to `joints_standards.json` and `parametres_calcul.json`

> **Note:** `lang.txt` is not required — the language is auto-detected from FreeCAD preferences. Create it only to force a specific language or during development.


- **Standards-compliant groove sizing** — depth, width and fillets per ISO 3601, DIN 3771, JIS B2401 and METRIC
- **Automatic FreeCAD geometry** — groove sketch, PartDesign Groove and Mirrored operations
- **3D torus body** — oblong cross-section preserving O-ring volume at installation, updated in-place
- **4 installation types** — static, dynamic translation, dynamic rotation, face seal
- **Groove on shaft and groove in bore** configurations
- **Parametric drift detection** — automatically detects dimension changes and updates linked assemblies
- **UUID-based identification** — immutable identifier per assembly, rename-proof
- **Material color coding** — NBR, FKM, EPDM, VMQ, FFKM, PTFE with distinct 3D colors
- **ISO 286-1 fit system** — optional H/g and H/f clearance modes
- **Automatic TNP recovery** — dress-up features (Chamfer, Fillet, Draft) suspended before groove recompute and reactivated after
- **TechDraw synchronization** — all drawing pages refreshed automatically on dialog close
- **Active body restoration** — main part body restored as active on close (fixes post-macro PartDesign dialogs)

---

## Requirements

- **FreeCAD 1.0 or later** with PartDesign and Sketcher workbenches  
  *(The TNP fix in FreeCAD 1.0 is required for correct parametric updates and dress-up feature recovery)*
- Python 3.x (bundled with FreeCAD)
- PySide2 (bundled with FreeCAD)

> **Note:** FreeCAD versions earlier than 1.0 are not supported.

---

## Installation

1. Download or clone this repository
2. Copy the `ORing/` folder and `ORing.py` into your FreeCAD Macro directory  
   *(Menu → Tools → Open Macro Directory)*

```
Macro/
├── ORing.py              ← macro entry point
└── ORing/
    ├── data/
    │   ├── joints_standards.json
    │   ├── materiaux.json
    │   └── parametres_calcul.json
    └── modules/
        ├── calcul.py
        ├── dialogue.py
        ├── joints.py
        ├── materiaux.py
        ├── metadata.py
        ├── oring_3d.py
        ├── sketch_arbre.py
        ├── sketch_alesage.py
        └── utils.py
```

3. Run via **Menu → Macro → Macros... → ORing → Execute**

---

## Document prerequisites

**Body carrying the groove (shaft or bore body)**
- At least one **LCS** (`PartDesign::CoordinateSystem`) — Z-axis = revolution axis, XZ plane = groove mid-plane
- At least one **named parameter** (sketch constraint or Spreadsheet alias) for the diameter or radius

**Complementary body**
- At least one named parameter for the mating diameter or radius

### Parameter naming convention

| First letter | Interpreted as |
|---|---|
| `R` or `r` | Radius |
| `D` or `d` | Diameter |
| Other | Manual selection required |

---

## Quick start

1. Open your FreeCAD document with shaft and bore bodies
2. Run the macro
3. **Tab 1** — select position, pressure, temperature, installation type
4. **Tab 2** — select bodies, parameters, LCS, series, material → **Calculate**
5. Review results (squeeze %, fill %, alerts) → **Apply in FreeCAD**

On close, the macro automatically:
- Restores the groove body as the active FreeCAD body
- Refreshes all TechDraw pages

---

## Modifying an existing assembly

**Tab 3** → double-click any row → modification mode.

| Change | Behavior |
|---|---|
| Series only | Groove and torus updated in-place (~0.3s) |
| Diameter | Both part parameters updated; linked assemblies auto-updated with 3D progress feedback |
| Groove-in-bore linked assembly | Radial clearance recalculated dynamically from current diameters |

### Automatic TNP recovery

When a groove is modified, dress-up features (Chamfer, Fillet, Draft) are automatically:
1. **Suspended** before the groove recompute → no crash on invalidated edges
2. **Reactivated** on stable geometry → FreeCAD 1.0 TNP fix remaps edge references
3. If reactivation fails → **geometric fingerprint remapping** (centre of mass, length, radius)
4. If remapping fails → feature **re-suspended** and flagged **⚠** in the result message

---

## Structure generated in FreeCAD

```
App::Part  "Equipped Shaft"
├── PartDesign::Body  "Shaft"       ← existing body (parameter updated)
└── App::Part  "OJ-20260316-xxxx"   ← O-ring container (one per groove)
    └── PartDesign::Body  "ORing"   ← 3D torus body
```

---

## Supported standards and series

| Standard | Series | d2 values (mm) |
|---|---|---|
| ISO 3601 | S1, S2, S3, S4 | 1.78, 2.62, 3.53, 5.33 |
| DIN 3771 | D1–D6 | 1.5 – 8.0 |
| JIS B2401 | P, G, V, S | 1.9 – 8.4 |
| METRIC | M1–M10+ | 1.0 – 10.0 |

## Recommended squeeze ranges

| Installation type | Range | Typical |
|---|---|---|
| Static | 15 – 30 % | 18 – 25 % |
| Dynamic translation | 10 – 20 % | 12 – 18 % |
| Dynamic rotation | 5 – 15 % | ≤ 10 – 12 % |

---

## What's new in v2.1

- **In-place torus update** — no delete/recreate; ~0.3s per O-ring vs 1–4s previously
- **Calculation debounce** — 50ms QTimer groups cascading Qt signals; one calculation per user action
- **Automatic TNP recovery** — dress-up features suspended/reactivated around groove recompute with geometric fingerprint fallback
- **Groove-in-bore clearance fix** — radial clearance dynamically recalculated when shaft diameter changes
- **Active body restoration** — groove body restored as active on close (fixes Fillet/Chamfer dialog issue)
- **TechDraw auto-sync** — all drawing pages refreshed on dialog close
- **3D progress feedback** — `Gui.updateGui()` after each linked assembly update
- **Centered result dialog** — success message centered on the sizing window
- **Auto Highlight**  — when an ORing is selected for modification, it stays highlighted for a better visual control
- **i18n**  — two first languages implemented: en-fr

---

## Documentation

- 📄 [User guide (English)](docs/Guide_Macro_ORing_EN.docx)
- 📄 [Guide utilisateur (Français)](docs/Guide_Macro_ORing.docx)

---

## License

Licensed under the **GNU Lesser General Public License v2.1**.  
See the [LICENSE](LICENSE) file for details.

---

## Contributing

Bug reports and pull requests are welcome. Please open an issue first to discuss significant changes.
