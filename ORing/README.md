# ORing — O-Ring Groove Macro for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/lgpl-2.1)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-1.0+-orange.svg)](https://www.freecad.org)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org)

A parametric FreeCAD macro for designing, inserting, and managing O-ring groove assemblies according to international standards.

**Supported standards:** ISO 3601 · DIN 3771 · JIS B2401 · METRIC  
**Author:** Yves Guillou · **Version:** 2.0 · **License:** LGPL v2.1

---

## Features

- **Standards-compliant groove sizing** — depth, width and fillets calculated per ISO 3601, DIN 3771, JIS B2401 and METRIC series
- **Automatic FreeCAD geometry** — generates the groove sketch, PartDesign Groove and Mirrored operations
- **3D torus body** — oblong cross-section that preserves the O-ring volume at installation
- **4 installation types** — static, dynamic translation, dynamic rotation, face seal
- **Groove on shaft and groove in bore** configurations
- **Parametric drift detection** — automatically detects when dimensions have changed and updates linked assemblies
- **UUID-based identification** — each assembly has an immutable identifier, rename-proof
- **Material color coding** — NBR, FKM, EPDM, VMQ, FFKM, PTFE with distinct colors in the 3D view
- **ISO 286-1 fit system** — optional H/g and H/f clearance modes replacing manual radial clearance input

---

## Requirements

- **FreeCAD 1.0 or later** with PartDesign and Sketcher workbenches  
  *(The TNP fix in FreeCAD 1.0 is required for correct parametric updates)*
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

For the macro to work, your FreeCAD document must contain:

**Body carrying the groove (shaft or bore body)**
- At least one **LCS** (Local Coordinate System / `PartDesign::CoordinateSystem`)  
  The Z-axis of the LCS defines the revolution axis; its XZ plane is the groove mid-plane
- At least one **named parameter** (sketch constraint or Spreadsheet alias) for the diameter or radius

**Complementary body**
- At least one named parameter for the mating diameter or radius

### Parameter naming convention

The macro auto-detects whether a parameter is a radius or diameter from its first letter:

| First letter | Interpreted as |
|---|---|
| `R` or `r` | Radius |
| `D` or `d` | Diameter |
| Other | Manual selection required |

> Internal groove sketch parameters (`RayonGorge`, `FilletHautGorge`, `depouille`, etc.) are automatically excluded from the selection list.

---

## Quick start

1. Open your FreeCAD document with shaft and bore bodies
2. Run the macro
3. **Tab 1** — select position (groove on shaft / in bore), enter pressure, temperature and installation type
4. **Tab 2** — select bodies, parameters, LCS, series, material → click **Calculate**
5. Review results (squeeze %, fill %, alerts) → click **Apply in FreeCAD**

The macro will:
- Update the shaft/bore diameter parameter
- Generate the groove sketch and PartDesign operations
- Create the 3D torus body
- Group everything in an `App::Part` container

---

## Structure generated in FreeCAD

```
App::Part  "Equipped Shaft"
├── PartDesign::Body  "Shaft"       ← existing body (parameter updated)
└── App::Part  "OJ-20260316-xxxx"   ← O-ring container (one per groove)
    └── PartDesign::Body  "ORing"   ← 3D torus body
```

---

## Modifying an existing assembly

Open the macro on the document → **Tab 3** lists all assemblies.  
Double-click any row to enter modification mode.

**What can be changed:**
- Material, installation type, pressure, temperature
- Standard, series, target squeeze
- Radial clearance / ISO fit mode
- Diameter/Radius radio button (correctable even in modification mode)

**What is locked:**
- Position, LCS, body and parameter selection

When the diameter changes, linked assemblies on the same body are **automatically updated**. The macro preserves the series where possible, searching for the nearest compatible series before falling back to Auto mode.

---

## Drift detection

Every time the dialog opens, the macro compares stored reference diameters against current FreeCAD parameter values. Assemblies with a mismatch > 0.001 mm are flagged as **drifted** (⚠ indicator on Tab 3).

Double-click a drifted assembly → the macro proposes a recalculation with the detected new diameter.

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

## Documentation

- 📄 [User guide (English)](docs/Guide_Macro_ORing_EN.docx)
- 📄 [Guide utilisateur (Français)](docs/Guide_Macro_ORing.docx)

---

## License

This project is licensed under the **GNU Lesser General Public License v2.1**.  
See the [LICENSE](LICENSE) file for details.

---

## Contributing

Bug reports and pull requests are welcome. Please open an issue first to discuss significant changes.
