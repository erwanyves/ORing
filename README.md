# ORing — O-Ring and Groove Macro for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/lgpl-2.1)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-1.0+-orange.svg)](https://www.freecad.org)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-2.1-green.svg)]()

A parametric FreeCAD macro for designing, inserting, and managing O-ring groove assemblies according to international standards.

**Supported standards:** ISO 3601 · DIN 3771 · JIS B2401 · METRIC  
**Author:** Yves Guillou · **Version:** 2.1 · **License:** LGPL v2.1

---

## Features

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
