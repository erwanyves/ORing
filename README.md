# ORing — O-ring groove macro for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-1.0%2B-orange.svg)](https://www.freecad.org)
[![Version](https://img.shields.io/badge/version-3.0-green.svg)](#version-history)

A parametric FreeCAD macro that sizes an O-ring groove from the standards, cuts it into your part and adds the O-ring itself as a 3D body. Every assembly stays editable afterwards.

**Author:** Yves Guillou · **Version:** 3.0 · **License:** LGPL v2.1

---

## Features

- **Groove sizing from the standards.** Depth, width and fillets are computed from the cord diameter. The result reports squeeze, groove fill and stretch, with warnings when a value leaves its recommended range.
- **Generated FreeCAD geometry.** The macro creates the groove sketch, the PartDesign Groove and a 3D O-ring body with an oblong cross-section that keeps the installed volume.
- **Configurations.** Groove on shaft or in bore. Static, dynamic translation and dynamic rotation installations.
- **Linked assemblies.** Works from an assembly that links its parts from other files (`App::Link`). The groove is written into the part's own document. A partially loaded linked document is completed before anything is written.
- **One undo step.** A whole insertion or modification is a single Ctrl+Z, across every document it touched.
- **Edit afterwards.** Tab 3 lists every O-ring in the document. Selecting an O-ring, or a circular edge of one, before launching opens it directly in edit mode.
- **Drift detection.** If a diameter changed since insertion, including in a sketch, the macro flags the O-ring and proposes to recompute it.
- **LCS assistant.** Select a circular edge and launch: the macro offers to create the local coordinate system it needs.
- **Material colours** for NBR, FKM, EPDM, VMQ, FFKM and PTFE.
- **Five interface languages:** English, French, German, Spanish and Italian.

---

## Requirements

- FreeCAD **1.0 or later** (developed and tested on 1.1), with the PartDesign and Sketcher workbenches
- No external dependency: Python and Qt (PySide2 or PySide6) ship with FreeCAD

---

## Installation

1. Download or clone this repository.
2. Copy `ORing.py` and the `ORing/` folder into your FreeCAD macro directory. To find it, open the menu **Macro → Macros…**: the directory is shown there.

```
Macro/
├── ORing.py          ← entry point, the file you run
└── ORing/
    ├── data/         ← O-ring catalogues, materials, calculation settings (JSON)
    ├── locales/      ← interface languages and the built-in guide
    ├── modules/      ← macro code
    └── lang.txt      ← optional: force the interface language
```

3. Run it from **Macro → Macros… → ORing.py → Execute**, or add it to a toolbar (**Tools → Customize → Macros**).

---

## Preparing your document

**Body that will carry the groove (shaft or bore):**

- a **local coordinate system** (`PartDesign::CoordinateSystem`). Its Z axis is the revolution axis and its XZ plane is the groove mid-plane. The macro can create it for you from a circular edge.
- a **named parameter** for the diameter or radius: a named sketch constraint or a spreadsheet alias.

**Mating body:** a named parameter for its diameter or radius.

A parameter whose name starts with `D`/`d` is read as a diameter, one starting with `R`/`r` as a radius. Any other name asks you which it is.

The **? Help** button in the dialog opens a five-page guide to these prerequisites.

---

## Quick start

1. Open the document with your shaft and bore bodies.
2. Run the macro.
3. **Tab 1:** groove position (shaft or bore), pressure, temperature and installation type.
4. **Tab 2:** bodies, parameters, LCS, standard and series, material, then **Calculate**.
5. Check the results (squeeze, fill, warnings), then **Apply in FreeCAD**.

The macro creates this structure:

```
App::Part  "Equipped Shaft"
├── PartDesign::Body  "Shaft"       ← your body, its diameter parameter updated
└── App::Part  "OJ-…"               ← one container per O-ring
    └── PartDesign::Body  "ORing"   ← 3D O-ring
```

---

## O-ring catalogues

The cord diameters come from `ORing/data/joints_standards.json`. Each standard declares **where its dimensions come from and how they were checked**:

| Standard | Series | Cord diameters (mm) | Check level |
|---|---|---|---|
| AS 568 | A000–A400 | 1.78 · 2.62 · 3.53 · 5.33 · 6.99 | proven: taken from a supplier catalogue |
| ISO 3601 | S1–S5 | 1.78 · 2.62 · 3.53 · 5.33 · 6.99 | proven: taken from a supplier catalogue |
| R series (Le Joint Français) | 12 series | 1.00 to 6.99 | proven: taken from a supplier catalogue |
| JIS B 2401, P series | P_S1–P_S5 | 1.9 · 2.4 · 3.5 · 5.7 · 8.4 | corroborated: four independent sources agree |
| DIN 3771 | D1–D5 | 1.80 · 2.65 · 3.55 · 5.30 · 7.00 | corroborated: two independent sources agree |
| METRIC | M1–M9 | 1.0 to 7.0 | **not checked**: a generic metric range, not a published standard |

**Always check that the O-ring you choose is available from your supplier**, especially in the METRIC range.

Recommended squeeze ranges used by the calculation:

| Installation | Range | Target |
|---|---|---|
| Static | 15–30 % | 22 % |
| Dynamic translation | 10–20 % | 15 % |
| Dynamic rotation | 5–15 % | 10 % |

---

## Language

The language follows FreeCAD's preference, then the system language, and falls back to English. To force a language, write its two-letter code (`en`, `fr`, `de`, `es`, `it`) on a line of `ORing/lang.txt`.

---

## Documentation

- [User guide (English)](docs/Guide_Macro_ORing_EN.docx)
- [Guide utilisateur (français)](docs/Guide_Macro_ORing_FR.docx)

The guides were written for version 2. The workflow is unchanged, but they do not cover the version 3 additions: linked assemblies, the LCS assistant and single-step undo.

---

## Version history

**3.0** (October 2026)
- Linked assemblies: insertion, editing and colours through `App::Link`. Partially loaded documents are completed before writing.
- One undo step per operation, across all the documents involved.
- Opens in edit mode from a selected O-ring or one of its edges. LCS assistant from a circular edge.
- Drift detection extended to sketch edits. Per-O-ring verdict in tab 3.
- Catalogues: AS 568, ISO 3601 and JIS B 2401 rebuilt. DIN 3771 series D4 corrected from 5.00 to 5.30 mm and D5 aligned with the standard. Each standard now declares where its dimensions come from.
- Interface in five languages.

**2.x** (2026): internationalisation (English and French), built-in guide, in-place O-ring update, automatic recovery of dress-up features after a groove recompute.

---

## License

Licensed under the **GNU Lesser General Public License v2.1**. See [LICENSE](LICENSE).

## Contributing

Bug reports and pull requests are welcome. Please open an issue first to discuss significant changes.
