# Third-Party Notices

NeuroCrunch is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)).
The binary distributions bundle the following third-party components, which are
licensed under their own terms:

| Component | License | Notes |
|---|---|---|
| [Qt / PySide6](https://www.qt.io/qt-for-python) | LGPL-3.0 | See the LGPL statement below |
| [pyqtgraph](https://github.com/pyqtgraph/pyqtgraph) | MIT | |
| [NumPy](https://numpy.org) | BSD-3-Clause | |
| [pandas](https://pandas.pydata.org) | BSD-3-Clause | |
| [tifffile](https://github.com/cgohlke/tifffile) | BSD-3-Clause | |
| [read-roi](https://github.com/hadim/read-roi) | BSD-3-Clause | |
| [matplotlib](https://matplotlib.org) | matplotlib license (PSF-based, BSD-compatible) | Bundled DejaVu and STIX fonts carry their own licenses |
| [OpenCV (opencv-python-headless)](https://github.com/opencv/opencv-python) | Apache-2.0 | The wheel bundles additional components; see `LICENSE-3RD-PARTY.txt` inside the `opencv_python_headless` distribution |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | MIT | |
| [Lucide icons](https://lucide.dev) | ISC | Icon SVGs in `assets/icons/`; license text at [assets/icons/lucide/LICENSE](assets/icons/lucide/LICENSE) |
| [Python](https://www.python.org) + standard library | PSF-2.0 | Embedded by the PyInstaller bundle |
| [PyInstaller bootloader](https://pyinstaller.org) | GPL-2.0 with bootloader exception | The exception explicitly permits distributing bundled applications under any license |

The full license text of each bundled Python package is included in its
`*.dist-info` metadata inside the frozen application bundle.

## Qt / PySide6 (LGPL-3.0) statement

NeuroCrunch uses Qt via the official PySide6 bindings under the terms of the
GNU Lesser General Public License version 3 (LGPL-3.0):

- Qt and PySide6 are used **unmodified** and are **dynamically loaded** at
  runtime (shared libraries; no static linking).
- The complete source code of NeuroCrunch, together with build instructions
  (`README.md`, `requirements.txt`, `neurocruncher.spec`), is publicly
  available at <https://github.com/danielzanelli/NeuroCrunch>. This allows any
  user to rebuild the application against a modified or replacement version of
  Qt/PySide6, as required by LGPL-3.0.
- The LGPL-3.0 license text is available at
  <https://www.gnu.org/licenses/lgpl-3.0.html>, and Qt licensing information at
  <https://www.qt.io/licensing/>.
