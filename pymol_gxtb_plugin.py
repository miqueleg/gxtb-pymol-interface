# -*- coding: utf-8 -*-
"""
PyMOL g-xTB Runner - public v1.0.1

A PyMOL Qt plugin for launching xTB/g-xTB/GFN-FF calculations, viewing
optimization/NEB/Sella trajectories, plotting energies, visualizing Hessian
normal modes, and running a practical IRC-like ± downhill workflow from an
imaginary mode.

Main features
-------------
- Native xTB/g-xTB/GFN0/GFN1/GFN2/GFN-FF single points, optimizations,
  gradients, Hessians, MD/metadynamics, xTB path jobs, and GSM preparation.
- PyMOL selection-based frozen atoms.
- Real-time trajectory loading and energy plotting.
- Hessian frequency table and vibration viewer.
- ASE/Sella TS optimization through a dedicated Python virtual environment.
- ASE NEB from explicit reactant/product structures.
- IRC-like ± downhill workflow from a selected imaginary mode.

Notes
-----
The IRC ± workflow is an approximate exploratory workflow: it displaces along
the selected normal mode and optimizes both downhill sides. It is not a strict
mass-weighted IRC integrator.
"""

"""
PyMOL g-xTB / xTB Runner Plugin v12 - rebuilt and sanity-checked

Main features
- Qt-only GUI, no tkinter and no matplotlib dependency
- Clean main dialog + separate Advanced Options dialog
- Remembers xTB path and advanced settings in ~/.pymol_gxtb_plugin.json
- Supports documented xTB calculation types
- Adds GFN-FF method and initial Hessian/vibration visualization only:
    sp (--scc), opt (--opt), path (--path final.xyz), grad, hess, ohess,
    md, omd, metaopt, metadyn
- GSM support is preparation / external execution only; GSM is not treated as native xTB
- Freeze atoms from a PyMOL selection by converting it to 1-based XYZ indices
- Loads optimization/path trajectories as explicit multi-state PyMOL objects
- Enforces sticks + spheres + sphere_scale 0.2 after trajectory loads
- Pure-Qt energy plot with current-frame marker and kcal/mol readout
"""

import json
import os
import platform
import re
import subprocess
import sys
import shutil
import tempfile
import time
from pathlib import Path

from pymol import cmd
from pymol.Qt import QtCore, QtGui, QtWidgets

PLUGIN_NAME = "PyMOL g-xTB Runner"
PLUGIN_VERSION = "1.0.1"
CONFIG_PATH = Path.home() / ".pymol_gxtb_plugin.json"
HARTREE_TO_KCAL_MOL = 627.509474


# ----------------------------- PyMOL plugin entry -----------------------------

def __init_plugin__(app=None):
    from pymol.plugins import addmenuitemqt
    addmenuitemqt(PLUGIN_NAME, run_plugin_gui)


_DIALOG = None


def run_plugin_gui():
    global _DIALOG
    _DIALOG = GxTBDialog()
    _DIALOG.show()


# ----------------------------- small utilities --------------------------------

def load_config():
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[g-xTB plugin] Could not read config: {exc}")
    return {}


def save_config(data):
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        print(f"[g-xTB plugin] Could not save config: {exc}")


def sanitize_name(name):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_")
    return name or "gxtb"


def safe_obj_exists(name):
    try:
        return bool(name) and name in cmd.get_object_list()
    except Exception:
        return False


def split_atom_list(text):
    return (text or "").replace(" ", "").strip()


def is_xyz_like(path):
    try:
        with open(path, "r", errors="ignore") as fh:
            first = fh.readline().strip()
        int(first)
        return True
    except Exception:
        return False


def read_multixyz_frames(path):
    """Return [(natoms, comment, xyz_block), ...] from XYZ/multi-XYZ."""
    frames = []
    try:
        lines = Path(path).read_text(errors="ignore").splitlines()
    except Exception:
        return frames

    i = 0
    while i < len(lines):
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        try:
            nat = int(lines[i].strip())
        except Exception:
            i += 1
            continue
        if i + 1 >= len(lines):
            break
        end = i + 2 + nat
        if end > len(lines):
            break
        comment = lines[i + 1].rstrip()
        atom_lines = lines[i + 2:end]
        if len(atom_lines) != nat:
            break
        block = "\n".join([str(nat), comment] + atom_lines) + "\n"
        frames.append((nat, comment, block))
        i = end
    return frames


def extract_energy_from_xyz_comment(comment):
    if not comment:
        return None
    patterns = [
        r"(?:energy|total\s+energy|etot|E)\s*[=:]?\s*(-?\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)",
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, comment, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
    return None


def parse_stdout_energy(line):
    patterns = [
        r"total\s+energy\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        r"TOTAL\s+ENERGY\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        r"energy:\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
    ]
    if "energy" not in line.lower():
        return None
    for pat in patterns:
        m = re.search(pat, line, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


# ----------------------------- settings container -----------------------------

class AdvancedOptions:
    def __init__(self):
        self.solvent_model = "none"      # none, alpb, gbsa, gbe
        self.solvent_name = ""
        self.use_etemp = False
        self.etemp = 300.0
        self.iterations = 250
        self.acc = 1.0
        self.opt_level = "normal"
        self.cycles = 250
        self.dynamic_rebond = False

        # Hessian stability guardrails. xTB Hessians can occasionally segfault
        # on some binaries/platforms after writing partial frequency output.
        # Default is balanced: controlled xTB OpenMP parallelism, no nested BLAS threads.
        self.hess_mode = "auto_retry_balanced_safe"  # fast, balanced4, strong8, safe1, auto_retry_balanced_safe
        self.hess_stack_size_mb = 512

        # Optional ASE/Sella TS optimization backend.
        self.ase_python = ""
        self.ase_venv_dir = str(Path.home() / ".pymol_gxtb_ase_sella_venv")
        self.ase_auto_install_python = True
        self.ase_pip_packages = "numpy scipy ase sella"
        self.ts_fmax = 0.05
        self.ts_steps = 100
        self.ts_internal = True
        self.ts_order = 1
        self.ts_hessian_initial_threads = 1
        self.ts_live_update_interval = 0.8

        self.fixed_atoms = ""
        self.fixed_elements = ""
        self.freeze_selection = ""
        self.distance_constraints = ""
        self.angle_constraints = ""
        self.dihedral_constraints = ""

        self.path_start_selection = ""
        self.path_final_selection = ""
        self.path_images = 8
        self.path_preview = True
        self.path_include_endpoints = True
        # ASE NEB options: separate from xTB --path/GSM.
        self.neb_images = 7
        self.neb_fmax = 0.05
        self.neb_steps = 200
        self.neb_k = 0.10
        self.neb_climb = True
        self.neb_interpolate = "idpp"  # idpp or linear

        self.md_block = (
            "$md\n"
            "   temp=298.15 # K\n"
            "   time=10.0   # ps\n"
            "   dump=50.0   # fs\n"
            "   step=1.0    # fs\n"
            "   velo=false\n"
            "   nvt=true\n"
            "   hmass=4\n"
            "   shake=2\n"
            "   sccacc=2.0\n"
            "$end"
        )
        self.metadyn_snapshots = 20
        self.metadyn_block = (
            "$metadyn\n"
            "   save=10\n"
            "   kpush=1.0\n"
            "   alp=0.2\n"
            "   # atoms: 1-10\n"
            "$end"
        )
        self.path_block = (
            "$path\n"
            "   nrun=1\n"
            "   npoint=25\n"
            "   anopt=10\n"
            "   kpush=0.003\n"
            "   kpull=-0.015\n"
            "   ppull=0.05\n"
            "   alp=1.2\n"
            "$end"
        )

        self.gsm_executable = "gsm.orca"
        self.gsm_inpfileq = (
            "# Example DE-GSM input template. Adjust for your GSM build.\n"
            "# The plugin writes scratch/initial0000.xyz as start.xyz + end.xyz.\n"
            "# Keep atom order identical in reactant and product.\n\n"
            "------------ QCHEM Scratch Info ------------------------\n"
            "$QCSCRATCH/\n"
            "------------ String Info -------------------------------\n"
            "SM_TYPE                 DE_GSM\n"
            "RESTART                 0\n"
            "MAX_OPT_ITERS           100\n"
            "STEP_OPT_ITERS          30\n"
            "CONV_TOL                0.0005\n"
            "ADD_NODE_TOL            0.1\n"
            "SCALING                 1.0\n"
            "SSM_DQMAX               0.8\n"
            "GROWTH_DIRECTION        0\n"
            "INT_THRESH              2.0\n"
            "MIN_SPACING             5.0\n"
            "BOND_FRAGMENTS          1\n"
            "INITIAL_OPT             0\n"
            "FINAL_OPT               0\n"
            "PRODUCT_LIMIT           100.0\n"
            "TS_FINAL_TYPE           0\n"
            "NNODES                  9\n"
            "------------ ORCA Info ---------------------------------\n"
            "ORCA_EXE                ograd\n"
            "ORCA_LOT                XTB\n"
            "ORCA_NPROCS             1\n"
            "ORCA_MEM                1000"
        )

        self.raw_xcontrol = ""
        self.flags = {k: False for k in ["molden", "wbo", "dipole", "pop", "lmo", "fod", "esp", "stm"]}

    def to_dict(self):
        return dict(self.__dict__)

    def from_dict(self, data):
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if key == "flags" and isinstance(value, dict):
                self.flags.update(value)
            elif hasattr(self, key):
                setattr(self, key, value)
        # backward compatibility aliases from older plugin versions
        if data.get("neb_final_selection") and not self.path_final_selection:
            self.path_final_selection = data.get("neb_final_selection", "")
        if data.get("neb_images") and not data.get("path_images"):
            self.path_images = int(data.get("neb_images"))
        # backward compatibility from v16 checkbox
        if "hess_safe_mode" in data and "hess_mode" not in data:
            self.hess_mode = "safe1" if data.get("hess_safe_mode") else "balanced4"


# ----------------------------- Advanced dialog --------------------------------

class AdvancedOptionsDialog(QtWidgets.QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = options
        self.setWindowTitle("g-xTB More Options")
        self.resize(760, 780)

        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs)

        self._build_general_tab()
        self._build_constraints_tab()
        self._build_path_gsm_tab()
        self._build_blocks_tab()
        self._build_ase_sella_tab()
        self._build_properties_tab()
        self._build_raw_tab()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Cancel |
            QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        outer.addWidget(buttons)

    def _object_and_selection_names(self):
        names = []
        try:
            names.extend(cmd.get_object_list())
            names.extend(cmd.get_names("selections"))
        except Exception:
            pass
        result = []
        for name in names:
            if name and name not in result:
                result.append(name)
        return result

    def _build_general_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        self.tabs.addTab(w, "General")

        self.solvent_model = QtWidgets.QComboBox()
        self.solvent_model.addItems(["none", "alpb", "gbsa", "gbe"])
        self.solvent_model.setCurrentText(str(self.options.solvent_model))
        self.solvent_name = QtWidgets.QLineEdit(str(self.options.solvent_name))

        self.use_etemp = QtWidgets.QCheckBox("Use electronic temperature --etemp")
        self.use_etemp.setChecked(bool(self.options.use_etemp))
        self.etemp = QtWidgets.QDoubleSpinBox()
        self.etemp.setRange(0.0, 100000.0)
        self.etemp.setDecimals(2)
        self.etemp.setValue(float(self.options.etemp))

        self.iterations = QtWidgets.QSpinBox()
        self.iterations.setRange(0, 100000)
        self.iterations.setValue(int(self.options.iterations))
        self.acc = QtWidgets.QDoubleSpinBox()
        self.acc.setRange(0.001, 100.0)
        self.acc.setDecimals(3)
        self.acc.setValue(float(self.options.acc))

        self.opt_level = QtWidgets.QComboBox()
        self.opt_level.addItems(["normal", "crude", "sloppy", "loose", "tight", "vtight", "extreme"])
        self.opt_level.setCurrentText(str(self.options.opt_level))
        self.cycles = QtWidgets.QSpinBox()
        self.cycles.setRange(0, 100000)
        self.cycles.setValue(int(self.options.cycles))

        self.dynamic_rebond = QtWidgets.QCheckBox("Try trajectory rebonding after reload (experimental)")
        self.dynamic_rebond.setChecked(bool(self.options.dynamic_rebond))

        self.hess_mode = QtWidgets.QComboBox()
        self.hess_mode.addItems([
            "auto_retry_balanced_safe",
            "balanced4",
            "strong8",
            "fast",
            "safe1",
        ])
        self.hess_mode.setCurrentText(str(getattr(self.options, "hess_mode", "auto_retry_balanced_safe")))
        self.hess_stack_size_mb = QtWidgets.QSpinBox()
        self.hess_stack_size_mb.setRange(64, 8192)
        self.hess_stack_size_mb.setValue(int(getattr(self.options, "hess_stack_size_mb", 512)))

        r = 0
        grid.addWidget(QtWidgets.QLabel("Solvent model"), r, 0)
        grid.addWidget(self.solvent_model, r, 1)
        grid.addWidget(QtWidgets.QLabel("Solvent name"), r, 2)
        grid.addWidget(self.solvent_name, r, 3)
        r += 1
        grid.addWidget(self.use_etemp, r, 0, 1, 2)
        grid.addWidget(self.etemp, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("SCC iterations --iterations"), r, 0)
        grid.addWidget(self.iterations, r, 1)
        grid.addWidget(QtWidgets.QLabel("SCC accuracy --acc"), r, 2)
        grid.addWidget(self.acc, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Opt level --opt"), r, 0)
        grid.addWidget(self.opt_level, r, 1)
        grid.addWidget(QtWidgets.QLabel("Opt cycles --cycles"), r, 2)
        grid.addWidget(self.cycles, r, 3)
        r += 1
        grid.addWidget(self.dynamic_rebond, r, 0, 1, 4)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Hessian mode"), r, 0)
        grid.addWidget(self.hess_mode, r, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("OMP stack / MB"), r, 3)
        grid.addWidget(self.hess_stack_size_mb, r, 4)

    def _build_constraints_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        self.tabs.addTab(w, "Constraints")

        self.fixed_atoms = QtWidgets.QLineEdit(str(self.options.fixed_atoms))
        self.fixed_elements = QtWidgets.QLineEdit(str(self.options.fixed_elements))

        self.freeze_selection = QtWidgets.QComboBox()
        self.refresh_freeze_btn = QtWidgets.QPushButton("Refresh selections")
        self.refresh_freeze_btn.clicked.connect(self.refresh_freeze_selections)
        self.refresh_freeze_selections()
        idx = self.freeze_selection.findText(str(self.options.freeze_selection))
        if idx >= 0:
            self.freeze_selection.setCurrentIndex(idx)

        self.distance_constraints = QtWidgets.QPlainTextEdit(str(self.options.distance_constraints))
        self.angle_constraints = QtWidgets.QPlainTextEdit(str(self.options.angle_constraints))
        self.dihedral_constraints = QtWidgets.QPlainTextEdit(str(self.options.dihedral_constraints))

        r = 0
        grid.addWidget(QtWidgets.QLabel("Fixed atoms, 1-based: 1,2,8-10"), r, 0)
        grid.addWidget(self.fixed_atoms, r, 1)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Fixed elements: C,H"), r, 0)
        grid.addWidget(self.fixed_elements, r, 1)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Freeze PyMOL selection as fixed atoms"), r, 0)
        grid.addWidget(self.freeze_selection, r, 1)
        grid.addWidget(self.refresh_freeze_btn, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Distance constraints, one per line: i j value [force]"), r, 0, 1, 3)
        r += 1
        grid.addWidget(self.distance_constraints, r, 0, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Angle constraints, one per line: i j k value [force]"), r, 0, 1, 3)
        r += 1
        grid.addWidget(self.angle_constraints, r, 0, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Dihedral constraints, one per line: i j k l value [force]"), r, 0, 1, 3)
        r += 1
        grid.addWidget(self.dihedral_constraints, r, 0, 1, 3)

    def refresh_freeze_selections(self):
        current = self.freeze_selection.currentText() if hasattr(self, "freeze_selection") else ""
        self.freeze_selection.clear()
        self.freeze_selection.addItem("")
        try:
            for name in cmd.get_names("selections"):
                self.freeze_selection.addItem(name)
        except Exception:
            pass
        idx = self.freeze_selection.findText(current)
        if idx >= 0:
            self.freeze_selection.setCurrentIndex(idx)

    def _build_path_gsm_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        self.tabs.addTab(w, "Path / GSM")

        self.path_start_selection = QtWidgets.QComboBox()
        self.path_final_selection = QtWidgets.QComboBox()
        self.refresh_path_btn = QtWidgets.QPushButton("Refresh objects/selections")
        self.refresh_path_btn.clicked.connect(self.refresh_path_selections)
        self.refresh_path_selections()

        idx = self.path_start_selection.findText(str(self.options.path_start_selection))
        if idx >= 0:
            self.path_start_selection.setCurrentIndex(idx)
        idx = self.path_final_selection.findText(str(self.options.path_final_selection))
        if idx >= 0:
            self.path_final_selection.setCurrentIndex(idx)

        self.path_images = QtWidgets.QSpinBox()
        self.path_images.setRange(2, 200)
        self.path_images.setValue(int(self.options.path_images))
        self.path_preview = QtWidgets.QCheckBox("Also write linear interpolated preview path")
        self.path_preview.setChecked(bool(self.options.path_preview))
        self.path_include_endpoints = QtWidgets.QCheckBox("Preview includes start and final endpoints")
        self.path_include_endpoints.setChecked(bool(self.options.path_include_endpoints))

        self.neb_images = QtWidgets.QSpinBox()
        self.neb_images.setRange(3, 64)
        self.neb_images.setValue(int(getattr(self.options, "neb_images", 7)))

        self.neb_fmax = QtWidgets.QDoubleSpinBox()
        self.neb_fmax.setRange(0.001, 1.0)
        self.neb_fmax.setDecimals(4)
        self.neb_fmax.setValue(float(getattr(self.options, "neb_fmax", 0.05)))

        self.neb_steps = QtWidgets.QSpinBox()
        self.neb_steps.setRange(1, 10000)
        self.neb_steps.setValue(int(getattr(self.options, "neb_steps", 200)))

        self.neb_k = QtWidgets.QDoubleSpinBox()
        self.neb_k.setRange(0.001, 10.0)
        self.neb_k.setDecimals(3)
        self.neb_k.setValue(float(getattr(self.options, "neb_k", 0.10)))

        self.neb_climb = QtWidgets.QCheckBox("ASE NEB climbing image")
        self.neb_climb.setChecked(bool(getattr(self.options, "neb_climb", True)))

        self.neb_interpolate = QtWidgets.QComboBox()
        self.neb_interpolate.addItems(["idpp", "linear"])
        self.neb_interpolate.setCurrentText(str(getattr(self.options, "neb_interpolate", "idpp")))

        self.metadyn_snapshots = QtWidgets.QSpinBox()
        self.metadyn_snapshots.setRange(1, 100000)
        self.metadyn_snapshots.setValue(int(self.options.metadyn_snapshots))

        self.gsm_executable = QtWidgets.QLineEdit(str(self.options.gsm_executable))

        r = 0
        grid.addWidget(QtWidgets.QLabel("Start/reactant object or selection"), r, 0)
        grid.addWidget(self.path_start_selection, r, 1)
        grid.addWidget(self.refresh_path_btn, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Final/product object or selection"), r, 0)
        grid.addWidget(self.path_final_selection, r, 1)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Preview images / GSM initial nodes"), r, 0)
        grid.addWidget(self.path_images, r, 1)
        r += 1
        grid.addWidget(self.path_preview, r, 0, 1, 3)
        r += 1
        grid.addWidget(self.path_include_endpoints, r, 0, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("ASE NEB images, including endpoints"), r, 0)
        grid.addWidget(self.neb_images, r, 1)
        grid.addWidget(self.neb_climb, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("ASE NEB fmax / eV Å⁻¹"), r, 0)
        grid.addWidget(self.neb_fmax, r, 1)
        grid.addWidget(QtWidgets.QLabel("Max steps"), r, 2)
        grid.addWidget(self.neb_steps, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("NEB spring k"), r, 0)
        grid.addWidget(self.neb_k, r, 1)
        grid.addWidget(QtWidgets.QLabel("Interpolation"), r, 2)
        grid.addWidget(self.neb_interpolate, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Metadynamics snapshots for calc = metadyn"), r, 0)
        grid.addWidget(self.metadyn_snapshots, r, 1)
        r += 1
        grid.addWidget(QtWidgets.QLabel("External GSM executable"), r, 0)
        grid.addWidget(self.gsm_executable, r, 1)
        r += 1
        note = QtWidgets.QLabel(
            "calc=path uses xTB: start.xyz --path final.xyz.  "
            "calc=neb_ase uses ASE NEB with explicit Start/reactant and Final/product structures and frozen atoms.  "
            "calc=gsm_prepare writes GSM files only.  calc=gsm_run prepares files and launches the external GSM executable.  "
            "Start/final structures must have the same atom count and atom order."
        )
        note.setWordWrap(True)
        grid.addWidget(note, r, 0, 1, 3)

    def refresh_path_selections(self):
        current_start = self.path_start_selection.currentText() if hasattr(self, "path_start_selection") else ""
        current_final = self.path_final_selection.currentText() if hasattr(self, "path_final_selection") else ""
        names = self._object_and_selection_names()
        for box in (self.path_start_selection, self.path_final_selection):
            box.clear()
            box.addItem("")
            for name in names:
                box.addItem(name)
        for box, current in ((self.path_start_selection, current_start), (self.path_final_selection, current_final)):
            idx = box.findText(current)
            if idx >= 0:
                box.setCurrentIndex(idx)

    def _build_blocks_tab(self):
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        self.tabs.addTab(w, "Dynamics / Path input")
        layout.addWidget(QtWidgets.QLabel("$md block, used by md / omd / metadyn"))
        self.md_block = QtWidgets.QPlainTextEdit(str(self.options.md_block))
        layout.addWidget(self.md_block)
        layout.addWidget(QtWidgets.QLabel("$metadyn block, used by metadyn"))
        self.metadyn_block = QtWidgets.QPlainTextEdit(str(self.options.metadyn_block))
        layout.addWidget(self.metadyn_block)
        layout.addWidget(QtWidgets.QLabel("$path block, used by path"))
        self.path_block = QtWidgets.QPlainTextEdit(str(self.options.path_block))
        layout.addWidget(self.path_block)

    def _build_ase_sella_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        self.tabs.addTab(w, "ASE / Sella TS")

        self.ase_python = QtWidgets.QLineEdit(str(getattr(self.options, "ase_python", "")))
        self.ase_python.setPlaceholderText("Optional: /path/to/python3.12, C:\\...\\python.exe, or py -3.12")

        self.ase_venv_dir = QtWidgets.QLineEdit(str(getattr(self.options, "ase_venv_dir", str(Path.home() / ".pymol_gxtb_ase_sella_venv"))))
        self.ase_venv_dir.setPlaceholderText("Virtual environment folder for ASE/Sella")

        self.ase_auto_install_python = QtWidgets.QCheckBox("Auto-install Python 3.12 if no compatible ASE/Sella Python is found")
        self.ase_auto_install_python.setChecked(bool(getattr(self.options, "ase_auto_install_python", True)))

        self.ase_pip_packages = QtWidgets.QLineEdit(str(getattr(self.options, "ase_pip_packages", "numpy scipy ase sella")))

        self.ts_fmax = QtWidgets.QDoubleSpinBox()
        self.ts_fmax.setRange(0.001, 1.0)
        self.ts_fmax.setDecimals(4)
        self.ts_fmax.setValue(float(getattr(self.options, "ts_fmax", 0.05)))

        self.ts_steps = QtWidgets.QSpinBox()
        self.ts_steps.setRange(1, 10000)
        self.ts_steps.setValue(int(getattr(self.options, "ts_steps", 100)))

        self.ts_order = QtWidgets.QSpinBox()
        self.ts_order.setRange(1, 3)
        self.ts_order.setValue(int(getattr(self.options, "ts_order", 1)))

        self.ts_internal = QtWidgets.QCheckBox("Use Sella internal coordinates")
        self.ts_internal.setChecked(bool(getattr(self.options, "ts_internal", True)))

        self.ts_hessian_initial_threads = QtWidgets.QSpinBox()
        self.ts_hessian_initial_threads.setRange(1, 32)
        self.ts_hessian_initial_threads.setValue(int(getattr(self.options, "ts_hessian_initial_threads", 1)))

        self.ts_live_update_interval = QtWidgets.QDoubleSpinBox()
        self.ts_live_update_interval.setRange(0.2, 10.0)
        self.ts_live_update_interval.setDecimals(2)
        self.ts_live_update_interval.setValue(float(getattr(self.options, "ts_live_update_interval", 0.8)))

        note = QtWidgets.QLabel(
            "TS optimization is experimental and uses an external ASE/Sella driver. "
            "The driver calls the selected xTB/g-xTB executable with --grad at each step. "
            "Initial Hessian-related work is kept single-threaded by default."
        )
        note.setWordWrap(True)

        r = 0
        grid.addWidget(QtWidgets.QLabel("Base Python 3.10–3.12 executable"), r, 0)
        grid.addWidget(self.ase_python, r, 1, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("ASE/Sella virtualenv folder"), r, 0)
        grid.addWidget(self.ase_venv_dir, r, 1, 1, 3)
        r += 1
        grid.addWidget(self.ase_auto_install_python, r, 0, 1, 4)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Pip packages to install"), r, 0)
        grid.addWidget(self.ase_pip_packages, r, 1, 1, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Sella fmax / eV Å⁻¹"), r, 0)
        grid.addWidget(self.ts_fmax, r, 1)
        grid.addWidget(QtWidgets.QLabel("Max TS steps"), r, 2)
        grid.addWidget(self.ts_steps, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Saddle order"), r, 0)
        grid.addWidget(self.ts_order, r, 1)
        grid.addWidget(self.ts_internal, r, 2, 1, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Initial Hessian / TS threads"), r, 0)
        grid.addWidget(self.ts_hessian_initial_threads, r, 1)
        grid.addWidget(QtWidgets.QLabel("Live update interval / s"), r, 2)
        grid.addWidget(self.ts_live_update_interval, r, 3)
        r += 1
        grid.addWidget(note, r, 0, 1, 4)

    def _build_properties_tab(self):
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        self.tabs.addTab(w, "Properties")
        self.flag_boxes = {}
        labels = [("molden", "--molden"), ("wbo", "--wbo"), ("dipole", "--dipole"), ("pop", "--pop"),
                  ("lmo", "--lmo"), ("fod", "--fod"), ("esp", "--esp"), ("stm", "--stm")]
        for i, (key, label) in enumerate(labels):
            box = QtWidgets.QCheckBox(label)
            box.setChecked(bool(self.options.flags.get(key, False)))
            self.flag_boxes[key] = box
            grid.addWidget(box, i // 2, i % 2)

    def _build_raw_tab(self):
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        self.tabs.addTab(w, "Raw xcontrol / GSM")
        layout.addWidget(QtWidgets.QLabel("Raw xcontrol additions/overrides"))
        self.raw_xcontrol = QtWidgets.QPlainTextEdit(str(self.options.raw_xcontrol))
        layout.addWidget(self.raw_xcontrol)
        layout.addWidget(QtWidgets.QLabel("GSM inpfileq template"))
        self.gsm_inpfileq = QtWidgets.QPlainTextEdit(str(self.options.gsm_inpfileq))
        layout.addWidget(self.gsm_inpfileq)

    def restore_defaults(self):
        self.options = AdvancedOptions()
        self.close()
        # Reopen a fresh dialog. Simpler and safer than individually resetting every widget.
        new_dialog = AdvancedOptionsDialog(self.options, self.parent())
        if new_dialog.exec():
            self.options = new_dialog.options
            super().accept()

    def accept(self):
        self.options.solvent_model = self.solvent_model.currentText()
        self.options.solvent_name = self.solvent_name.text().strip()
        self.options.use_etemp = self.use_etemp.isChecked()
        self.options.etemp = self.etemp.value()
        self.options.iterations = self.iterations.value()
        self.options.acc = self.acc.value()
        self.options.opt_level = self.opt_level.currentText()
        self.options.cycles = self.cycles.value()
        self.options.dynamic_rebond = self.dynamic_rebond.isChecked()
        self.options.hess_mode = self.hess_mode.currentText()
        self.options.hess_stack_size_mb = self.hess_stack_size_mb.value()

        self.options.fixed_atoms = self.fixed_atoms.text().strip()
        self.options.fixed_elements = self.fixed_elements.text().strip()
        self.options.freeze_selection = self.freeze_selection.currentText().strip()
        self.options.distance_constraints = self.distance_constraints.toPlainText()
        self.options.angle_constraints = self.angle_constraints.toPlainText()
        self.options.dihedral_constraints = self.dihedral_constraints.toPlainText()

        self.options.path_start_selection = self.path_start_selection.currentText().strip()
        self.options.path_final_selection = self.path_final_selection.currentText().strip()
        self.options.path_images = self.path_images.value()
        self.options.path_preview = self.path_preview.isChecked()
        self.options.path_include_endpoints = self.path_include_endpoints.isChecked()
        if hasattr(self, "neb_images"):
            self.options.neb_images = self.neb_images.value()
            self.options.neb_fmax = self.neb_fmax.value()
            self.options.neb_steps = self.neb_steps.value()
            self.options.neb_k = self.neb_k.value()
            self.options.neb_climb = self.neb_climb.isChecked()
            self.options.neb_interpolate = self.neb_interpolate.currentText()
        self.options.metadyn_snapshots = self.metadyn_snapshots.value()
        self.options.gsm_executable = self.gsm_executable.text().strip() or "gsm.orca"

        self.options.md_block = self.md_block.toPlainText()
        self.options.metadyn_block = self.metadyn_block.toPlainText()
        self.options.path_block = self.path_block.toPlainText()
        self.options.raw_xcontrol = self.raw_xcontrol.toPlainText()
        self.options.gsm_inpfileq = self.gsm_inpfileq.toPlainText()

        if hasattr(self, "ase_pip_packages"):
            self.options.ase_python = self.ase_python.text().strip()
            self.options.ase_venv_dir = self.ase_venv_dir.text().strip() or str(Path.home() / ".pymol_gxtb_ase_sella_venv")
            self.options.ase_auto_install_python = self.ase_auto_install_python.isChecked()
            self.options.ase_pip_packages = self.ase_pip_packages.text().strip() or "numpy scipy ase sella"
            self.options.ts_fmax = self.ts_fmax.value()
            self.options.ts_steps = self.ts_steps.value()
            self.options.ts_order = self.ts_order.value()
            self.options.ts_internal = self.ts_internal.isChecked()
            self.options.ts_hessian_initial_threads = self.ts_hessian_initial_threads.value()
            self.options.ts_live_update_interval = self.ts_live_update_interval.value()

        for key, box in self.flag_boxes.items():
            self.options.flags[key] = box.isChecked()
        super().accept()


# ----------------------------- Energy plot widget -----------------------------

class EnergyPlotWidget(QtWidgets.QWidget):
    frame_requested = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.energies = []
        self.current_frame = None
        self.setMinimumHeight(230)

    def set_energies(self, energies):
        self.energies = list(energies or [])
        self.update()

    def set_current_frame(self, frame):
        self.current_frame = int(frame) if frame else None
        self.update()

    def _plot_rect(self):
        return QtCore.QRectF(58, 18, max(10, self.width() - 78), max(10, self.height() - 55))

    def _bounds(self):
        if not self.energies:
            return 1, 1, 0.0, 1.0
        ymin, ymax = min(self.energies), max(self.energies)
        if abs(ymax - ymin) < 1e-12:
            ymin -= 1e-6
            ymax += 1e-6
        return 1, len(self.energies), ymin, ymax

    def _to_point(self, i, e):
        rect = self._plot_rect()
        xmin, xmax, ymin, ymax = self._bounds()
        x = rect.left() + 0.5 * rect.width() if xmax == xmin else rect.left() + (i - xmin) / (xmax - xmin) * rect.width()
        y = rect.bottom() - (e - ymin) / (ymax - ymin) * rect.height()
        return QtCore.QPointF(x, y)

    def mousePressEvent(self, event):
        if not self.energies:
            return
        x = event.position().x() if hasattr(event, "position") else event.x()
        rect = self._plot_rect()
        xmin, xmax, *_ = self._bounds()
        if xmax == xmin:
            frame = 1
        else:
            frame = int(round(xmin + (x - rect.left()) / max(1e-9, rect.width()) * (xmax - xmin)))
        frame = max(1, min(len(self.energies), frame))
        self.frame_requested.emit(frame)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self._plot_rect()
        painter.fillRect(self.rect(), self.palette().window())
        painter.setPen(QtGui.QPen(self.palette().text().color(), 1))
        painter.drawRect(rect)
        painter.drawText(8, 16, "Energy / Eh")
        painter.drawText(int(rect.center().x()) - 35, self.height() - 8, "Frame / step")
        if not self.energies:
            painter.drawText(rect, QtCore.Qt.AlignCenter, "Energy plot will appear during the calculation")
            painter.end()
            return

        xmin, xmax, ymin, ymax = self._bounds()
        painter.drawText(8, int(rect.top()) + 8, f"{ymax:.6f}")
        painter.drawText(8, int(rect.bottom()), f"{ymin:.6f}")
        painter.drawText(int(rect.left()), self.height() - 30, str(xmin))
        painter.drawText(int(rect.right()) - 30, self.height() - 30, str(xmax))

        pts = [self._to_point(i + 1, e) for i, e in enumerate(self.energies)]
        painter.setPen(QtGui.QPen(self.palette().text().color(), 2))
        for a, b in zip(pts[:-1], pts[1:]):
            painter.drawLine(a, b)
        painter.setBrush(self.palette().text().color())
        for p in pts:
            painter.drawEllipse(p, 2.2, 2.2)

        if self.current_frame and 1 <= self.current_frame <= len(self.energies):
            e = self.energies[self.current_frame - 1]
            rel_first = (e - self.energies[0]) * HARTREE_TO_KCAL_MOL
            rel_min = (e - min(self.energies)) * HARTREE_TO_KCAL_MOL
            p = pts[self.current_frame - 1]
            painter.setPen(QtGui.QPen(QtGui.QColor(220, 30, 30), 2))
            painter.setBrush(QtGui.QColor(220, 30, 30))
            painter.drawEllipse(p, 6.5, 6.5)
            label = f"frame {self.current_frame} | E={e:.8f} Eh | ΔE(first)={rel_first:.2f} kcal/mol | ΔE(min)={rel_min:.2f} kcal/mol"
            metrics = painter.fontMetrics()
            box_w = min(metrics.horizontalAdvance(label) + 18, int(rect.width()) - 8)
            box_h = metrics.height() + 10
            box_x, box_y = int(rect.left()) + 6, int(rect.top()) + 6
            painter.setPen(QtGui.QPen(QtGui.QColor(220, 30, 30), 1))
            painter.setBrush(QtGui.QColor(255, 255, 255, 225))
            painter.drawRoundedRect(box_x, box_y, box_w, box_h, 5, 5)
            painter.setPen(QtGui.QColor(30, 30, 30))
            painter.drawText(box_x + 6, box_y + box_h - 7, metrics.elidedText(label, QtCore.Qt.ElideRight, box_w - 12))
        painter.end()




# ----------------------------- Vibrations --------------------------------------

class VibrationMode:
    def __init__(self, index, frequency, displacements, source=""):
        self.index = int(index)
        self.frequency = float(frequency)
        self.displacements = displacements
        self.source = source


_FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def _to_float_token(token):
    return float(str(token).replace("D", "E").replace("d", "e"))


def _find_floats(text):
    return [_to_float_token(x) for x in re.findall(_FLOAT_RE, text)]



def read_xyz_geometry(path):
    """Read first XYZ frame; return list of {symbol,x,y,z}."""
    frames = read_multixyz_frames(path)
    if not frames:
        return []
    nat, comment, block = frames[0]
    lines = block.splitlines()[2:2 + nat]
    atoms = []
    for line in lines:
        toks = line.split()
        if len(toks) >= 4:
            try:
                atoms.append({
                    "symbol": toks[0],
                    "x": float(toks[1]),
                    "y": float(toks[2]),
                    "z": float(toks[3]),
                })
            except Exception:
                pass
    return atoms


def parse_xtb_g98_modes(path):
    """
    Parse normal modes from xTB's Gaussian-style g98.out.

    Expected blocks look like:
      Frequencies -- ...
      Red. masses -- ...
      Frc consts  -- ...
      IR Inten    -- ...
       Atom  AN      X      Y      Z        X      Y      Z ...
         1   6    dx dy dz ...
    """
    modes = []
    if not path or not os.path.exists(path):
        return modes

    try:
        lines = Path(path).read_text(errors="ignore").splitlines()
    except Exception:
        return modes

    i = 0
    mode_counter = 1
    nlines = len(lines)
    while i < nlines:
        line = lines[i]
        if "Frequencies --" not in line:
            i += 1
            continue

        try:
            freqs = _find_floats(line.split("--", 1)[1])
        except Exception:
            freqs = []
        if not freqs:
            i += 1
            continue

        nm = len(freqs)
        header = None
        j = i + 1
        while j < nlines:
            if re.search(r"^\s*Atom\s+AN\s+", lines[j]):
                header = j
                break
            if "Frequencies --" in lines[j]:
                break
            j += 1

        if header is None:
            i += 1
            continue

        disp = [[] for _ in range(nm)]
        k = header + 1
        while k < nlines:
            row = lines[k].split()
            if len(row) < 2 + 3 * nm:
                break
            try:
                int(row[0])
                int(row[1])
                vals = [_to_float_token(x) for x in row[2:2 + 3 * nm]]
            except Exception:
                break

            for m in range(nm):
                disp[m].append((vals[3*m], vals[3*m + 1], vals[3*m + 2]))
            k += 1

        for m, f in enumerate(freqs):
            if disp[m]:
                modes.append(VibrationMode(mode_counter, f, disp[m], source=os.path.basename(path)))
                mode_counter += 1

        i = k

    return modes


def parse_xtb_vibspectrum_frequencies(path):
    """
    Fallback parser for xTB vibspectrum. This usually provides frequencies but not
    normal-mode vectors, so it cannot drive visualization by itself.
    """
    freqs = []
    if not path or not os.path.exists(path):
        return freqs
    try:
        for line in Path(path).read_text(errors="ignore").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            nums = re.findall(_FLOAT_RE, line)
            if nums:
                # In common xTB vibspectrum format, the frequency is one of the first columns.
                # Prefer the second numeric token if present, otherwise first.
                val = _to_float_token(nums[1] if len(nums) > 1 else nums[0])
                if abs(val) > 1e-8:
                    freqs.append(val)
    except Exception:
        pass
    return freqs


def find_hessian_modes(workdir):
    """
    Return (modes, source_message). g98.out is preferred because it has displacements.
    """
    candidates = [
        os.path.join(workdir, "g98.out"),
        os.path.join(workdir, "gaussian.out"),
    ]
    for path in candidates:
        modes = parse_xtb_g98_modes(path)
        if modes:
            return modes, f"Loaded {len(modes)} modes from {os.path.basename(path)}."

    vib = os.path.join(workdir, "vibspectrum")
    freqs = parse_xtb_vibspectrum_frequencies(vib)
    if freqs:
        return [], f"Found {len(freqs)} frequencies in vibspectrum, but no normal-mode vectors for visualization. Enable/inspect g98.out output."

    return [], "No normal modes found. Expected g98.out with Gaussian-style normal coordinates."


def write_vibration_xyz(atoms, mode, path, amplitude=0.7, nframes=21):
    """
    Write a back-and-forth multi-XYZ vibration animation for one normal mode.

    xTB/Gaussian-style normal mode vectors may be tiny, mass-weighted, or normalized
    differently depending on the build. For visualization, normalize the selected mode
    by its maximum displacement so amplitude is in approximate Angstrom units. This
    prevents a valid mode from looking static in PyMOL.
    """
    if not atoms:
        raise ValueError("No base geometry available for vibration.")
    if not mode.displacements or len(mode.displacements) != len(atoms):
        raise ValueError(f"Mode atom count mismatch: geometry={len(atoms)}, mode={len(mode.displacements)}")

    nframes = max(5, int(nframes))
    if nframes % 2 == 0:
        nframes += 1

    import math

    max_norm = 0.0
    for dx, dy, dz in mode.displacements:
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if norm > max_norm:
            max_norm = norm

    if max_norm < 1e-14:
        raise ValueError(
            f"Mode {mode.index} has near-zero displacement vectors. "
            "The frequency table was parsed, but no usable normal coordinates were found."
        )

    scale = float(amplitude) / max_norm

    with open(path, "w") as fh:
        for i in range(nframes):
            phase = math.sin(2.0 * math.pi * i / max(1, nframes - 1))
            fh.write(f"{len(atoms)}\n")
            fh.write(
                f"mode {mode.index} freq={mode.frequency:.4f} cm^-1 "
                f"frame={i+1}/{nframes} phase={phase:.6f} "
                f"visual_amp={amplitude:.4f} max_raw_disp={max_norm:.6e}\n"
            )
            for atom, d in zip(atoms, mode.displacements):
                x = atom["x"] + scale * phase * d[0]
                y = atom["y"] + scale * phase * d[1]
                z = atom["z"] + scale * phase * d[2]
                fh.write(f"{atom['symbol']:2s} {x: .10f} {y: .10f} {z: .10f}\n")



def write_displaced_mode_xyz(atoms, mode, path, displacement=0.15, sign=1.0):
    """
    Write a single XYZ geometry displaced along a normalized normal mode.
    displacement is approximate Angstrom displacement of the largest-moving atom.
    """
    if not atoms:
        raise ValueError("No base geometry available.")
    if not mode.displacements or len(mode.displacements) != len(atoms):
        raise ValueError(f"Mode atom count mismatch: geometry={len(atoms)}, mode={len(mode.displacements)}")

    import math
    max_norm = 0.0
    for dx, dy, dz in mode.displacements:
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        max_norm = max(max_norm, norm)
    if max_norm < 1e-14:
        raise ValueError("Selected mode has near-zero displacement vectors.")

    scale = float(displacement) * float(sign) / max_norm

    with open(path, "w") as fh:
        fh.write(f"{len(atoms)}\n")
        fh.write(f"IRC-like displacement mode={mode.index} freq={mode.frequency:.4f} sign={sign} disp={displacement}\n")
        for atom, d in zip(atoms, mode.displacements):
            x = atom["x"] + scale * d[0]
            y = atom["y"] + scale * d[1]
            z = atom["z"] + scale * d[2]
            fh.write(f"{atom['symbol']:2s} {x: .10f} {y: .10f} {z: .10f}\n")


def write_single_xyz_from_atoms(atoms, path, comment="structure"):
    with open(path, "w") as fh:
        fh.write(f"{len(atoms)}\n{comment}\n")
        for atom in atoms:
            fh.write(f"{atom['symbol']:2s} {atom['x']: .10f} {atom['y']: .10f} {atom['z']: .10f}\n")


def multixyz_blocks_from_frames(frames):
    return [block for _, _, block in frames]


def frame_energy_or_none(comment):
    return extract_energy_from_xyz_comment(comment)




def xyz_block_atoms(block):
    """Parse a single XYZ block into [(element, x, y, z), ...]."""
    lines = block.splitlines()
    if len(lines) < 2:
        return []
    try:
        nat = int(lines[0].strip())
    except Exception:
        return []
    atoms = []
    for line in lines[2:2 + nat]:
        toks = line.split()
        if len(toks) >= 4:
            try:
                atoms.append((toks[0], float(toks[1]), float(toks[2]), float(toks[3])))
            except Exception:
                pass
    return atoms


def write_multimodel_pdb_from_xyz_frames(frames, path):
    """
    Write a multi-model PDB from XYZ frames. PyMOL handles MODEL/ENDMDL PDB
    files more reliably as trajectory states than repeated XYZ load(state=N)
    on some builds.
    """
    with open(path, "w") as fh:
        for model_idx, (_, comment, block) in enumerate(frames, start=1):
            atoms = xyz_block_atoms(block)
            fh.write(f"MODEL     {model_idx:4d}\n")
            if comment:
                safe_comment = comment[:70].replace("\n", " ")
                fh.write(f"REMARK {safe_comment}\n")
            for atom_idx, (elem, x, y, z) in enumerate(atoms, start=1):
                elem2 = (elem.strip() or "X")[:2].rjust(2)
                name = (elem.strip() or "X")[:4].rjust(4)
                fh.write(
                    f"HETATM{atom_idx:5d} {name} UNK A{1:4d}    "
                    f"{x:8.3f}{y:8.3f}{z:8.3f}"
                    f"{1.00:6.2f}{0.00:6.2f}          {elem2}\n"
                )
            fh.write("ENDMDL\n")
        fh.write("END\n")


# ----------------------------- Main dialog ------------------------------------

class GxTBDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("g-xTB Runner")
        self.resize(660, 720)
        self.config = load_config()
        self.options = AdvancedOptions()
        self.options.from_dict(self.config.get("advanced_options", {}))
        self.worker = None
        self.traj_object = None
        self.last_job_dir = None

        outer = QtWidgets.QVBoxLayout(self)
        main = QtWidgets.QGroupBox("Calculation")
        grid = QtWidgets.QGridLayout(main)
        outer.addWidget(main)

        self.object_box = QtWidgets.QComboBox()
        self.refresh_objects()
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_objects)

        self.charge_box = QtWidgets.QSpinBox()
        self.charge_box.setRange(-99, 99)
        self.mult_box = QtWidgets.QSpinBox()
        self.mult_box.setRange(1, 99)
        self.mult_box.setValue(1)

        self.method_box = QtWidgets.QComboBox()
        self.method_box.addItems(["gxtb", "gfn2", "gfn1", "gfn0", "gfnff", "none/custom"])
        self.calc_box = QtWidgets.QComboBox()
        self.calc_box.addItems(["sp", "opt", "ts_sella", "neb_ase", "path", "gsm_prepare", "gsm_run", "grad", "hess", "md", "omd", "metaopt", "metadyn"])

        self.xtb_path = QtWidgets.QLineEdit(self.config.get("xtb_path", "xtb"))
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_xtb)

        r = 0
        grid.addWidget(QtWidgets.QLabel("Input object / selection"), r, 0)
        grid.addWidget(self.object_box, r, 1)
        grid.addWidget(refresh_btn, r, 2)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Charge"), r, 0)
        grid.addWidget(self.charge_box, r, 1)
        grid.addWidget(QtWidgets.QLabel("Multiplicity"), r, 2)
        grid.addWidget(self.mult_box, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("Method"), r, 0)
        grid.addWidget(self.method_box, r, 1)
        grid.addWidget(QtWidgets.QLabel("Calculation"), r, 2)
        grid.addWidget(self.calc_box, r, 3)
        r += 1
        grid.addWidget(QtWidgets.QLabel("xTB executable"), r, 0)
        grid.addWidget(self.xtb_path, r, 1, 1, 2)
        grid.addWidget(browse_btn, r, 3)

        buttons = QtWidgets.QHBoxLayout()
        outer.addLayout(buttons)
        self.more_btn = QtWidgets.QPushButton("More options...")
        self.more_btn.clicked.connect(self.open_more_options)
        buttons.addWidget(self.more_btn)

        self.install_deps_btn = QtWidgets.QPushButton("Install ASE/Sella deps")
        self.install_deps_btn.clicked.connect(self.install_ase_sella_dependencies)
        buttons.addWidget(self.install_deps_btn)

        buttons.addStretch()
        self.run_btn = QtWidgets.QPushButton("Run calculation")
        self.run_btn.clicked.connect(self.start_job)
        buttons.addWidget(self.run_btn)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_job)
        buttons.addWidget(self.stop_btn)
        self.print_dir_btn = QtWidgets.QPushButton("Print job folder")
        self.print_dir_btn.clicked.connect(self.print_job_folder)
        buttons.addWidget(self.print_dir_btn)

        self.status = QtWidgets.QLabel("Ready.")
        outer.addWidget(self.status)
        self.plot = EnergyPlotWidget()
        self.plot.frame_requested.connect(self.set_pymol_frame)
        outer.addWidget(self.plot)
        self.energy_readout = QtWidgets.QLabel("Energy readout: no frame selected.")
        self.energy_readout.setWordWrap(True)
        outer.addWidget(self.energy_readout)

        self.vib_group = QtWidgets.QGroupBox("Vibrations / frequencies")
        self.vib_group.setCheckable(True)
        self.vib_group.setChecked(False)
        vib_layout = QtWidgets.QVBoxLayout(self.vib_group)

        self.vib_table = QtWidgets.QTableWidget(0, 3)
        self.vib_table.setHorizontalHeaderLabels(["Mode", "Frequency / cm⁻¹", "Source"])
        self.vib_table.horizontalHeader().setStretchLastSection(True)
        self.vib_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.vib_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.vib_table.itemSelectionChanged.connect(self.on_vibration_selection_changed)
        vib_layout.addWidget(self.vib_table)

        vib_controls = QtWidgets.QHBoxLayout()
        vib_layout.addLayout(vib_controls)
        vib_controls.addWidget(QtWidgets.QLabel("Amplitude"))
        self.vib_amp = QtWidgets.QDoubleSpinBox()
        self.vib_amp.setRange(0.01, 10.0)
        self.vib_amp.setDecimals(2)
        self.vib_amp.setValue(0.40)
        vib_controls.addWidget(self.vib_amp)
        vib_controls.addWidget(QtWidgets.QLabel("Frames"))
        self.vib_frames = QtWidgets.QSpinBox()
        self.vib_frames.setRange(5, 101)
        self.vib_frames.setValue(21)
        vib_controls.addWidget(self.vib_frames)
        self.vib_show_btn = QtWidgets.QPushButton("Show selected vibration")
        self.vib_show_btn.clicked.connect(self.show_selected_vibration)
        vib_controls.addWidget(self.vib_show_btn)

        vib_controls.addWidget(QtWidgets.QLabel("IRC disp / Å"))
        self.irc_disp = QtWidgets.QDoubleSpinBox()
        self.irc_disp.setRange(0.01, 2.0)
        self.irc_disp.setDecimals(3)
        self.irc_disp.setValue(0.15)
        vib_controls.addWidget(self.irc_disp)

        self.irc_btn = QtWidgets.QPushButton("Run IRC ±")
        self.irc_btn.clicked.connect(self.run_irc_from_selected_mode)
        vib_controls.addWidget(self.irc_btn)

        vib_controls.addStretch()

        self.vib_status = QtWidgets.QLabel("Run a Hessian calculation to populate frequencies.")
        self.vib_status.setWordWrap(True)
        vib_layout.addWidget(self.vib_status)

        outer.addWidget(self.vib_group)
        self.vibration_modes = []
        self.vibration_base_atoms = []
        self.vibration_object = None

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        outer.addWidget(self.log)

        self.frame_timer = QtCore.QTimer(self)
        self.frame_timer.timeout.connect(self.poll_current_frame)
        self.frame_timer.start(500)

    def refresh_objects(self):
        current = self.object_box.currentText() if hasattr(self, "object_box") else ""
        names = []
        try:
            names.extend(cmd.get_object_list())
            names.extend(cmd.get_names("selections"))
        except Exception:
            pass
        seen = []
        for name in names:
            if name and name not in seen:
                seen.append(name)
        self.object_box.clear()
        self.object_box.addItems(seen)
        idx = self.object_box.findText(current)
        if idx >= 0:
            self.object_box.setCurrentIndex(idx)

    def browse_xtb(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select xTB executable")
        if path:
            self.xtb_path.setText(path)
            self.persist_settings()

    def open_more_options(self):
        dlg = AdvancedOptionsDialog(self.options, self)
        if dlg.exec():
            self.options = dlg.options
            self.persist_settings()
            self.append_log("Advanced options updated.")

    def persist_settings(self):
        self.config["xtb_path"] = self.xtb_path.text().strip() or "xtb"
        self.config["advanced_options"] = self.options.to_dict()
        save_config(self.config)

    def append_log(self, text):
        self.log.appendPlainText(str(text).rstrip())

    def print_job_folder(self):
        if self.last_job_dir:
            self.append_log(f"Job folder: {self.last_job_dir}")
            print(f"[g-xTB plugin] Job folder: {self.last_job_dir}")

    def discover_ase_python(self):
        """
        Prefer Python 3.10–3.12 for Sella/SciPy wheels.

        Cross-platform behavior:
        - macOS/Linux: try python3.12, python3.11, python3.10, python3
        - Windows: try py -3.12/-3.11/-3.10, then python.exe/python
        - fallback: PyMOL Python only if it is 3.10–3.12
        """
        configured = str(getattr(self.options, "ase_python", "")).strip()
        if configured:
            return configured

        def check_cmd(cmd):
            try:
                out = subprocess.check_output(
                    cmd + ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                    text=True,
                    stderr=subprocess.STDOUT,
                ).strip()
                major, minor = [int(x) for x in out.split(".")[:2]]
                if major == 3 and 10 <= minor <= 12:
                    return cmd
            except Exception:
                return None
            return None

        system = platform.system().lower()
        candidates = []

        if system == "windows":
            # Windows launcher, if available
            for ver in ["3.12", "3.11", "3.10"]:
                if shutil.which("py"):
                    candidates.append(["py", f"-{ver}"])
            for exe in ["python.exe", "python", "python3.exe", "python3"]:
                found = shutil.which(exe)
                if found:
                    candidates.append([found])
        else:
            for exe in ["python3.12", "python3.11", "python3.10", "python3", "python"]:
                found = shutil.which(exe)
                if found:
                    candidates.append([found])

        for cmd in candidates:
            ok = check_cmd(cmd)
            if ok:
                # Return as a shell-free command string. For py -3.12 we preserve both tokens
                # by joining with a separator understood by ase_python_command().
                return " ".join(ok)

        if sys.version_info.major == 3 and 10 <= sys.version_info.minor <= 12:
            return sys.executable
        return ""

    def ase_venv_python_path(self):
        venv = Path(str(getattr(self.options, "ase_venv_dir", str(Path.home() / ".pymol_gxtb_ase_sella_venv")))).expanduser()
        if platform.system().lower() == "windows":
            return venv / "Scripts" / "python.exe"
        return venv / "bin" / "python"

    def ase_base_python_command(self):
        value = str(getattr(self.options, "ase_python", "")).strip() or self.discover_ase_python()
        if not value:
            return []
        if value.lower().startswith("py -"):
            return value.split()
        return [value]

    def ase_python_command(self):
        """
        Return Python command for running ASE/Sella. Prefer the dedicated venv.
        """
        venv_py = self.ase_venv_python_path()
        if venv_py.exists():
            return [str(venv_py)]
        return self.ase_base_python_command()

    def ase_sella_import_check_command(self):
        pycmd = self.ase_python_command()
        if not pycmd:
            return []
        return pycmd + ["-c", "import ase, sella, numpy, scipy; print('ASE/Sella import check OK')"]

    def python_bootstrap_commands(self):
        """
        Return OS-aware commands to install Python 3.12 if no compatible Python exists.

        This is best-effort:
        - macOS: uses Homebrew if brew exists
        - Windows: uses winget if winget exists
        - Linux: we do not attempt distro package installs automatically because package
          names and privileges vary too much; user should install python3.12 manually.
        """
        system = platform.system().lower()

        if system == "darwin":
            brew = shutil.which("brew")
            if brew:
                return [[brew, "install", "python@3.12"]], (
                    "Installing Python 3.12 with Homebrew. If Homebrew asks for permissions, "
                    "run the printed command in Terminal."
                )
            return [], (
                "Homebrew was not found. Install Homebrew or Python 3.12 manually, then set "
                "the ASE/Sella Python path in More options → ASE / Sella TS."
            )

        if system == "windows":
            winget = shutil.which("winget")
            if winget:
                return [[winget, "install", "--id", "Python.Python.3.12", "-e", "--source", "winget"]], (
                    "Installing Python 3.12 with winget. A Windows permissions/UAC prompt may appear."
                )
            return [], (
                "winget was not found. Install Python 3.12 from python.org or Microsoft Store, "
                "then set the ASE/Sella Python path in More options → ASE / Sella TS."
            )

        return [], (
            "Automatic Python installation is not attempted on this OS. Install Python 3.10–3.12 "
            "with your system package manager or conda, then set the ASE/Sella Python path."
        )

    def refresh_ase_python_after_bootstrap(self):
        # Clear empty setting and re-detect. If user manually set a path, keep it.
        if not str(getattr(self.options, "ase_python", "")).strip():
            detected = self.discover_ase_python()
            if detected:
                self.options.ase_python = detected
                self.persist_settings()
                self.append_log(f"[Dependencies] Detected ASE/Sella Python after bootstrap: {detected}")
                return True
        return bool(str(getattr(self.options, "ase_python", "")).strip())

    def install_ase_sella_dependencies(self):
        """
        Create a dedicated ASE/Sella virtual environment and install dependencies.

        Windows-specific robustness:
        - create venv using the discovered base Python / py launcher
        - run ensurepip inside the venv when available
        - install binary scientific stack first: numpy, scipy, ase
        - install Sella separately, with fallback strategies
        """
        self.persist_settings()

        base_pycmd = self.ase_base_python_command()
        commands = []
        bootstrap_requested = False

        if not base_pycmd:
            if bool(getattr(self.options, "ase_auto_install_python", True)):
                bootstrap_cmds, bootstrap_msg = self.python_bootstrap_commands()
                self.append_log("[Dependencies] " + bootstrap_msg)
                if bootstrap_cmds:
                    bootstrap_requested = True
                    commands.extend(bootstrap_cmds)
                else:
                    QtWidgets.QMessageBox.warning(self, "ASE/Sella Python", bootstrap_msg)
                    return
            else:
                msg = (
                    "Could not find a suitable Python 3.10–3.12 for ASE/Sella. "
                    "Install Python 3.12, then enter its executable path in "
                    "More options → ASE / Sella TS. On Windows you can use 'py -3.12' "
                    "or the full path to python.exe."
                )
                self.append_log("[Dependencies] " + msg)
                QtWidgets.QMessageBox.warning(self, "ASE/Sella dependencies", msg)
                return

        if base_pycmd:
            self.options.ase_python = " ".join(base_pycmd) if base_pycmd[0].lower() == "py" else base_pycmd[0]
            self.persist_settings()

            venv_dir = Path(str(getattr(self.options, "ase_venv_dir", str(Path.home() / ".pymol_gxtb_ase_sella_venv")))).expanduser()
            venv_py = self.ase_venv_python_path()

            commands.extend([
                base_pycmd + ["-m", "venv", str(venv_dir)],
                {"optional": [str(venv_py), "-m", "ensurepip", "--upgrade"]},
                [str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
                [str(venv_py), "-m", "pip", "install", "--upgrade", "--only-binary=:all:", "numpy", "scipy", "ase"],
                {
                    "try_any": [
                        [str(venv_py), "-m", "pip", "install", "--upgrade", "--only-binary=:all:", "sella"],
                        [str(venv_py), "-m", "pip", "install", "--upgrade", "--no-deps", "--no-build-isolation", "sella"],
                        [str(venv_py), "-m", "pip", "install", "--upgrade", "sella"],
                    ],
                    "label": "Install Sella",
                },
                [str(venv_py), "-c", "import ase, sella, numpy, scipy; print('ASE/Sella import check OK')"],
            ])

            self.append_log("[Dependencies] Creating/using dedicated ASE/Sella virtual environment:")
            self.append_log(f"[Dependencies] venv: {venv_dir}")
            self.append_log("[Dependencies] Windows strategy: install numpy/scipy/ase from wheels first, then install Sella separately with fallbacks.")
            for c in commands:
                self.append_log("[Dependencies] " + DependencyInstallerWorker.command_to_text(c))
            self.append_log("[Dependencies] This avoids Homebrew/PEP 668 system-Python restrictions and avoids compiling SciPy from source on Windows.")
        else:
            self.append_log("[Dependencies] Python bootstrap will run first. After it completes, dependency installation will continue if Python is detected.")

        self.install_deps_btn.setEnabled(False)
        self.dep_worker = DependencyInstallerWorker(commands, bootstrap_only=bootstrap_requested and not base_pycmd)
        self.dep_worker.log_line.connect(self.append_log)
        self.dep_worker.finished_ok.connect(self.on_dependency_install_finished)
        self.dep_worker.start()

    def on_dependency_install_finished(self, ok, message):
        self.install_deps_btn.setEnabled(True)
        self.append_log("[Dependencies] " + message)

        # If this was a Python bootstrap-only step, try to detect the new Python and
        # continue with dependency installation.
        if ok and getattr(self.dep_worker, "bootstrap_only", False):
            if self.refresh_ase_python_after_bootstrap():
                self.append_log("[Dependencies] Python bootstrap completed; continuing with ASE/Sella package installation.")
                self.install_ase_sella_dependencies()
                return
            msg = (
                message + "\n\nPython may have installed successfully, but it was not detected in PATH yet. "
                "Restart PyMOL, or enter the new Python path manually in More options → ASE / Sella TS."
            )
            QtWidgets.QMessageBox.information(self, "ASE/Sella Python", msg)
            return

        if ok:
            QtWidgets.QMessageBox.information(self, "ASE/Sella dependencies", message)
        else:
            QtWidgets.QMessageBox.warning(self, "ASE/Sella dependencies", message)

    def method_flag_args(self):
        method = self.method_box.currentText()
        if method == "gxtb":
            return ["--gxtb"]
        if method == "gfn2":
            return ["--gfn2"]
        if method == "gfn1":
            return ["--gfn1"]
        if method == "gfn0":
            return ["--gfn0"]
        if method == "gfnff":
            return ["--gfnff"]
        return []


    # ------------------------ geometry and input writers -----------------------

    def _model_atoms(self, selection):
        model = cmd.get_model(selection)
        atoms = []
        for a in model.atom:
            symbol = (a.symbol or a.name or "X").strip()
            atoms.append({"symbol": symbol, "x": float(a.coord[0]), "y": float(a.coord[1]), "z": float(a.coord[2]), "model": a.model, "index": a.index})
        return atoms

    def write_xyz_from_selection(self, selection, path, comment="PyMOL export"):
        atoms = self._model_atoms(selection)
        if not atoms:
            raise ValueError(f"Selection '{selection}' has no atoms.")
        with open(path, "w") as fh:
            fh.write(f"{len(atoms)}\n{comment}\n")
            for a in atoms:
                fh.write(f"{a['symbol']:2s} {a['x']: .10f} {a['y']: .10f} {a['z']: .10f}\n")
        return atoms

    def write_interpolated_path(self, start_sel, final_sel, path, nimages, include_endpoints=True):
        start_atoms = self._model_atoms(start_sel)
        final_atoms = self._model_atoms(final_sel)
        if len(start_atoms) != len(final_atoms):
            raise ValueError(f"Path/GSM requires same atom count: start={len(start_atoms)}, final={len(final_atoms)}.")
        for i, (a, b) in enumerate(zip(start_atoms, final_atoms), 1):
            if a["symbol"].upper() != b["symbol"].upper():
                raise ValueError(f"Atom order mismatch at atom {i}: start={a['symbol']} final={b['symbol']}.")
        nimages = max(2, int(nimages))
        if include_endpoints:
            tvals = [i / max(1, nimages - 1) for i in range(nimages)]
        else:
            tvals = [(i + 1) / (nimages + 1) for i in range(nimages)]
        with open(path, "w") as fh:
            for frame, t in enumerate(tvals, 1):
                fh.write(f"{len(start_atoms)}\nPath preview image {frame}/{len(tvals)} t={t:.8f}\n")
                for a, b in zip(start_atoms, final_atoms):
                    x = (1 - t) * a["x"] + t * b["x"]
                    y = (1 - t) * a["y"] + t * b["y"]
                    z = (1 - t) * a["z"] + t * b["z"]
                    fh.write(f"{a['symbol']:2s} {x: .10f} {y: .10f} {z: .10f}\n")
        return len(tvals)

    def compute_freeze_indices(self, input_selection, freeze_selection):
        if not freeze_selection:
            return []
        try:
            input_atoms = self._model_atoms(input_selection)
            frozen = cmd.get_model(f"({input_selection}) and ({freeze_selection})")
            frozen_keys = {(a.model, a.index) for a in frozen.atom}
            indices = [i for i, a in enumerate(input_atoms, 1) if (a["model"], a["index"]) in frozen_keys]
        except Exception as exc:
            self.append_log(f"[Freeze warning] Could not process selection '{freeze_selection}': {exc}")
            return []
        if indices:
            preview = ",".join(map(str, indices[:30])) + ("..." if len(indices) > 30 else "")
            self.append_log(f"[Freeze] {freeze_selection}: {len(indices)} atoms -> {preview}")
        else:
            self.append_log(f"[Freeze warning] Selection '{freeze_selection}' has no atoms inside '{input_selection}'.")
        return indices

    def build_xcontrol(self, path, calc, freeze_indices=None):
        parts = []
        fixed_atoms = split_atom_list(self.options.fixed_atoms)
        fixed_elements = self.options.fixed_elements.strip()
        atom_entries = []
        if fixed_atoms:
            atom_entries.append(fixed_atoms)
        if freeze_indices:
            atom_entries.append(",".join(map(str, freeze_indices)))
        if atom_entries or fixed_elements:
            parts.append("$fix")
            if atom_entries:
                parts.append(" atoms: " + ",".join(atom_entries))
            if fixed_elements:
                parts.append(" elements: " + fixed_elements)
            parts.append("$end")

        constraints = []
        for line in self.options.distance_constraints.splitlines():
            toks = line.split()
            if len(toks) >= 3 and not line.strip().startswith("#"):
                constraints.append(" distance: " + ", ".join(toks[:4]))
        for line in self.options.angle_constraints.splitlines():
            toks = line.split()
            if len(toks) >= 4 and not line.strip().startswith("#"):
                constraints.append(" angle: " + ", ".join(toks[:5]))
        for line in self.options.dihedral_constraints.splitlines():
            toks = line.split()
            if len(toks) >= 5 and not line.strip().startswith("#"):
                constraints.append(" dihedral: " + ", ".join(toks[:6]))
        if constraints:
            parts.append("$constrain")
            parts.extend(constraints)
            parts.append("$end")

        if calc in ("md", "omd", "metadyn") and self.options.md_block.strip():
            parts.append(self.options.md_block.strip())
        if calc == "metadyn" and self.options.metadyn_block.strip():
            parts.append(self.options.metadyn_block.strip())
        if calc == "path" and self.options.path_block.strip():
            parts.append(self.options.path_block.strip())
        if self.options.raw_xcontrol.strip():
            parts.append(self.options.raw_xcontrol.strip())

        if not parts:
            return None
        Path(path).write_text("\n".join(parts) + "\n")
        return path

    def prepare_gsm_files(self, workdir, start_sel, final_sel):
        scratch = os.path.join(workdir, "scratch")
        os.makedirs(scratch, exist_ok=True)
        start_xyz = os.path.join(workdir, "start.xyz")
        end_xyz = os.path.join(workdir, "end.xyz")
        initial = os.path.join(scratch, "initial0000.xyz")
        self.write_xyz_from_selection(start_sel, start_xyz, "GSM reactant from PyMOL")
        self.write_xyz_from_selection(final_sel, end_xyz, "GSM product from PyMOL")
        # validate atom order
        self.write_interpolated_path(start_sel, final_sel, os.path.join(workdir, "gsm_linear_preview.xyz"), self.options.path_images, True)
        with open(initial, "w") as out:
            out.write(Path(start_xyz).read_text())
            out.write(Path(end_xyz).read_text())
        Path(os.path.join(workdir, "inpfileq")).write_text(self.options.gsm_inpfileq.strip() + "\n")
        ograd = os.path.join(workdir, "ograd")
        xtb_exec = self.xtb_path.text().strip() or "xtb"
        Path(ograd).write_text(f"#!/bin/sh\n# Placeholder GSM gradient wrapper. Edit for your GSM build.\n{xtb_exec} \"$@\" --grad\n")
        try:
            os.chmod(ograd, 0o755)
        except Exception:
            pass
        # Windows helper for users adapting GSM manually.
        Path(os.path.join(workdir, "ograd.bat")).write_text(f"@echo off\nREM Placeholder GSM gradient wrapper. Edit for your GSM build.\n{xtb_exec} %* --grad\n")
        self.append_log(f"[GSM] Prepared files in {workdir}. Check inpfileq/ograd before production runs.")

    # ------------------------ command construction/run ------------------------

    def build_command(self, xyz_file, workdir, calc, final_xyz=None, freeze_indices=None):
        if calc == "gsm_prepare":
            return None
        if calc == "gsm_run":
            return [self.options.gsm_executable, "1"]

        xtb_exec = self.xtb_path.text().strip() or "xtb"
        method = self.method_box.currentText()
        cmdline = [xtb_exec, xyz_file]
        if method == "gxtb":
            cmdline.append("--gxtb")
        elif method == "gfn2":
            cmdline.append("--gfn2")
        elif method == "gfn1":
            cmdline.append("--gfn1")
        elif method == "gfn0":
            cmdline.append("--gfn0")
        elif method == "gfnff":
            cmdline.append("--gfnff")

        cmdline += ["--chrg", str(self.charge_box.value()), "--uhf", str(self.mult_box.value() - 1)]

        # g-xTB currently may not have ALPB/GBSA parameters for all solvents/methods. Avoid known crash.
        if self.options.solvent_model != "none" and self.options.solvent_name:
            if method == "gxtb":
                self.append_log("[Solvent warning] Skipping implicit solvent with gxtb to avoid missing ALPB/GBSA parameter crash.")
            else:
                cmdline += [f"--{self.options.solvent_model}", self.options.solvent_name]

        if self.options.use_etemp:
            cmdline += ["--etemp", str(float(self.options.etemp))]
        if int(self.options.iterations) > 0:
            cmdline += ["--iterations", str(int(self.options.iterations))]
        if abs(float(self.options.acc) - 1.0) > 1e-9:
            cmdline += ["--acc", str(float(self.options.acc))]

        if calc == "sp":
            cmdline.append("--scc")
        elif calc == "opt":
            cmdline += ["--opt", self.options.opt_level]
            if int(self.options.cycles) > 0:
                cmdline += ["--cycles", str(int(self.options.cycles))]
        elif calc == "path":
            if not final_xyz:
                raise ValueError("calc=path requires a final/product selection in More options → Path / GSM.")
            cmdline += ["--path", final_xyz]
        elif calc == "grad":
            cmdline.append("--grad")
        elif calc == "hess":
            cmdline.append("--hess")
            if method == "gfnff":
                self.append_log("[Hessian warning] GFN-FF Hessians are known to be less robust in some xTB builds; Safe mode may be needed if this crashes.")

            hmode = getattr(self.options, "hess_mode", "auto_retry_balanced_safe")
            if hmode == "balanced4" or hmode == "auto_retry_balanced_safe":
                cmdline += ["--parallel", "4"]
            elif hmode == "strong8":
                cmdline += ["--parallel", "8"]
            elif hmode == "safe1":
                cmdline += ["--parallel", "1"]
            elif hmode == "fast":
                # No explicit --parallel; let xTB decide from environment/defaults.
                pass
        elif calc == "ohess":
            cmdline.append("--ohess")
        elif calc == "md":
            cmdline.append("--md")
        elif calc == "omd":
            cmdline.append("--omd")
        elif calc == "metaopt":
            cmdline.append("--metaopt")
        elif calc == "metadyn":
            cmdline += ["--metadyn", str(int(self.options.metadyn_snapshots))]
        else:
            raise ValueError(f"Unsupported calculation type: {calc}")

        if method == "gfnff" and any(self.options.flags.get(k, False) for k in ["molden", "wbo", "dipole", "pop", "lmo", "fod", "esp", "stm"]):
            self.append_log("[GFN-FF warning] Electronic property flags are generally not meaningful for GFN-FF and may be ignored by xTB.")
        for key, flag in {"molden":"--molden", "wbo":"--wbo", "dipole":"--dipole", "pop":"--pop", "lmo":"--lmo", "fod":"--fod", "esp":"--esp", "stm":"--stm"}.items():
            if self.options.flags.get(key, False):
                cmdline.append(flag)

        xcontrol = self.build_xcontrol(os.path.join(workdir, "xcontrol"), calc, freeze_indices)
        if xcontrol:
            cmdline += ["--input", xcontrol]
        return cmdline

    def hessian_env_for_mode(self, mode):
        """
        Return environment for Hessian mode.
        - fast: no environment override
        - balanced4/strong8/auto: controlled xTB OMP threads, BLAS threads pinned to 1
        - safe1: serial fallback
        """
        if mode == "fast":
            return None

        env = os.environ.copy()
        stack_mb = int(getattr(self.options, "hess_stack_size_mb", 512))

        if mode == "strong8":
            omp_threads = "8"
        elif mode == "safe1":
            omp_threads = "1"
        else:
            omp_threads = "4"

        env["OMP_NUM_THREADS"] = omp_threads
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["VECLIB_MAXIMUM_THREADS"] = "1"
        env["OMP_STACKSIZE"] = f"{stack_mb}M"
        return env

    def describe_hessian_mode(self, mode):
        if mode == "fast":
            return "Fast: xTB/default parallelism, no BLAS pinning."
        if mode == "balanced4":
            return "Balanced: --parallel 4, OMP_NUM_THREADS=4, BLAS threads=1."
        if mode == "strong8":
            return "Strong: --parallel 8, OMP_NUM_THREADS=8, BLAS threads=1."
        if mode == "safe1":
            return "Safe: --parallel 1, OMP_NUM_THREADS=1, BLAS threads=1."
        if mode == "auto_retry_balanced_safe":
            return "Auto retry: first Balanced/4, then Safe/1 if xTB segfaults."
        return str(mode)

    def write_sella_ts_driver(self, workdir, xyz_file, freeze_indices):
        driver = os.path.join(workdir, "run_sella_ts.py")
        method_args = self.method_flag_args()

        solvent_args = []
        if self.options.solvent_model != "none" and self.options.solvent_name and self.method_box.currentText() != "gxtb":
            solvent_args = [f"--{self.options.solvent_model}", self.options.solvent_name]

        extra_args = []
        if self.options.use_etemp:
            extra_args += ["--etemp", str(float(self.options.etemp))]
        if int(self.options.iterations) > 0:
            extra_args += ["--iterations", str(int(self.options.iterations))]
        if abs(float(self.options.acc) - 1.0) > 1e-9:
            extra_args += ["--acc", str(float(self.options.acc))]

        xcontrol_path = self.build_xcontrol(os.path.join(workdir, "xcontrol_ts"), "grad", freeze_indices)
        input_args = ["--input", xcontrol_path] if xcontrol_path else []

        replacements = {
            "__XTB_EXEC__": repr(self.xtb_path.text().strip() or "xtb"),
            "__METHOD_ARGS__": repr(method_args),
            "__SOLVENT_ARGS__": repr(solvent_args),
            "__EXTRA_ARGS__": repr(extra_args),
            "__INPUT_ARGS__": repr(input_args),
            "__CHARGE__": repr(str(self.charge_box.value())),
            "__UHF__": repr(str(self.mult_box.value() - 1)),
            "__WORKDIR__": repr(workdir),
            "__XYZ_FILE__": repr(xyz_file),
            "__FROZEN__": repr([int(i) - 1 for i in freeze_indices]),
            "__TS_THREADS__": repr(str(int(getattr(self.options, "ts_hessian_initial_threads", 1)))),
            "__TS_ORDER__": repr(int(getattr(self.options, "ts_order", 1))),
            "__TS_INTERNAL__": repr(bool(getattr(self.options, "ts_internal", True))),
            "__TS_FMAX__": repr(float(getattr(self.options, "ts_fmax", 0.05))),
            "__TS_STEPS__": repr(int(getattr(self.options, "ts_steps", 100))),
        }

        template = """
#!/usr/bin/env python3
import os
import platform
import re
import subprocess
from pathlib import Path

import numpy as np
from ase.io import read, write
from ase.calculators.calculator import Calculator, all_changes
from ase.constraints import FixAtoms

try:
    from sella import Sella
except Exception as exc:
    raise SystemExit("Could not import sella. Use the plugin button 'Install ASE/Sella deps'. Original error: " + str(exc))

EV_PER_HARTREE = 27.211386245988
EV_PER_HARTREE_PER_BOHR_TO_EV_PER_ANG = 51.4220674763259

XTB = __XTB_EXEC__
if not os.path.isabs(XTB):
    resolved_xtb = shutil.which(XTB)
    if resolved_xtb:
        XTB = resolved_xtb
METHOD_ARGS = __METHOD_ARGS__
SOLVENT_ARGS = __SOLVENT_ARGS__
EXTRA_ARGS = __EXTRA_ARGS__
INPUT_ARGS = __INPUT_ARGS__
CHARGE_ARGS = ["--chrg", __CHARGE__, "--uhf", __UHF__]
WORKDIR = Path(__WORKDIR__)
XYZ_FILE = __XYZ_FILE__
TRAJ_XYZ = WORKDIR / "sella_ts_traj.xyz"
LOG_FILE = WORKDIR / "sella_ts.log"
FINAL_XYZ = WORKDIR / "sella_ts_final.xyz"
ENERGY_TABLE = WORKDIR / "sella_ts_energies.tsv"
FROZEN = __FROZEN__
TS_THREADS = __TS_THREADS__

float_re = re.compile(r"[-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[EeDd][-+]?\\d+)?")

def floats(text):
    return [float(x.replace("D", "E").replace("d", "e")) for x in float_re.findall(text)]

def parse_energy(text):
    patterns = [
        r"TOTAL ENERGY\\s+(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
        r"total energy\\s+(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
        r"energy\\s*[:=]\\s*(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1).replace("D", "E").replace("d", "e"))
    vals = floats(text)
    return vals[0] if vals else None

def parse_gradient_file(path, natoms):
    txt = Path(path).read_text(errors="ignore")
    triples = []
    for line in txt.splitlines():
        vals = floats(line)
        if len(vals) == 3:
            triples.append(vals)
        elif len(vals) >= 4:
            triples.append(vals[-3:])
    if len(triples) < natoms:
        raise RuntimeError("Could not parse enough gradient triples from xTB gradient file.")
    return np.array(triples[-natoms:], dtype=float)

class ExternalXTBGrad(Calculator):
    implemented_properties = ["energy", "forces"]

    def __init__(self):
        super().__init__()
        self.counter = 0

    def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        self.counter += 1
        stepdir = WORKDIR / ("ase_xtb_step_%05d" % self.counter)
        stepdir.mkdir(exist_ok=True)
        xyz = stepdir / "geom.xyz"
        write(str(xyz), atoms)

        cmd = [XTB, str(xyz)] + METHOD_ARGS + CHARGE_ARGS + SOLVENT_ARGS + EXTRA_ARGS + INPUT_ARGS + ["--grad"]
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = TS_THREADS
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["VECLIB_MAXIMUM_THREADS"] = "1"
        env["OMP_STACKSIZE"] = "512M"

        proc = subprocess.run(cmd, cwd=str(stepdir), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        (stepdir / "xtb.out").write_text(proc.stdout)
        if proc.returncode != 0:
            raise RuntimeError("xTB --grad failed at ASE/Sella step %d with code %s\\n%s" % (self.counter, proc.returncode, proc.stdout[-4000:]))

        eh = parse_energy(proc.stdout)
        if eh is None:
            raise RuntimeError("Could not parse xTB energy at ASE/Sella step %d" % self.counter)

        grad_path = stepdir / "gradient"
        if not grad_path.exists():
            candidates = list(stepdir.glob("*grad*"))
            if candidates:
                grad_path = candidates[0]
            else:
                raise RuntimeError("xTB did not write a gradient file at ASE/Sella step %d" % self.counter)

        grad_ha_bohr = parse_gradient_file(grad_path, len(atoms))
        forces = -grad_ha_bohr * EV_PER_HARTREE_PER_BOHR_TO_EV_PER_ANG

        self.results["energy"] = eh * EV_PER_HARTREE
        self.results["forces"] = forces

        # Do not append trajectory here: Sella may call the calculator multiple times
        # per optimizer step. The attached callback below writes one clean frame per
        # accepted optimizer step.


atoms = read(XYZ_FILE)
if FROZEN:
    atoms.set_constraint(FixAtoms(indices=FROZEN))
atoms.calc = ExternalXTBGrad()

# Reset clean output files.
for p in [TRAJ_XYZ, ENERGY_TABLE, FINAL_XYZ]:
    try:
        if Path(p).exists():
            Path(p).unlink()
    except Exception:
        pass

def append_ts_frame(label, step_index):
    try:
        e_ev = atoms.get_potential_energy()
        e_eh = e_ev / EV_PER_HARTREE
    except Exception:
        e_ev = None
        e_eh = None

    with open(TRAJ_XYZ, "a") as fh:
        fh.write("%d\\n" % len(atoms))
        if e_eh is None:
            fh.write("%s step=%d\\n" % (label, step_index))
        else:
            fh.write("%s step=%d E_eV=%.10f E_Eh=%.10f\\n" % (label, step_index, e_ev, e_eh))
        for sym, pos in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
            fh.write("%-2s % .10f % .10f % .10f\\n" % (sym, pos[0], pos[1], pos[2]))

    if e_eh is not None:
        header = not ENERGY_TABLE.exists()
        with open(ENERGY_TABLE, "a") as tab:
            if header:
                tab.write("step\tE_Eh\tE_eV\tlabel\\n")
            tab.write("%d\t%.12f\t%.10f\t%s\\n" % (step_index, e_eh, e_ev, label))
        print("Sella TS", label, "step", step_index, "E_Eh=", "%.12f" % e_eh, flush=True)
    else:
        print("Sella TS", label, "step", step_index, "energy unavailable", flush=True)

with open(LOG_FILE, "w") as log:
    log.write("Starting Sella TS optimization\\n")
    log.write("Method args: %r\\n" % METHOD_ARGS)
    log.write("Frozen ASE zero-based indices: %r\\n" % FROZEN)
    log.write("Sella internal coordinates: %r\\n" % (__TS_INTERNAL__,))

step_counter = {"n": 0}
append_ts_frame("Sella_initial", 0)

dyn = Sella(
    atoms,
    order=__TS_ORDER__,
    internal=__TS_INTERNAL__,
    trajectory=str(WORKDIR / "sella_ts.traj"),
    logfile=str(LOG_FILE),
)

def sella_step_callback():
    step_counter["n"] += 1
    append_ts_frame("Sella_step", step_counter["n"])

dyn.attach(sella_step_callback, interval=1)
converged = dyn.run(fmax=__TS_FMAX__, steps=__TS_STEPS__)
print("Sella TS converged:", bool(converged), "accepted_steps:", step_counter["n"], flush=True)

write(str(FINAL_XYZ), atoms)
# Always append a final frame. This guarantees at least initial+final even if
# Sella exits immediately because the initial guess is already stationary.
append_ts_frame("Sella_final", step_counter["n"] + 1)
print("Wrote Sella TS trajectory:", TRAJ_XYZ, flush=True)
print("Wrote Sella TS final geometry:", FINAL_XYZ, flush=True)
"""
        script = template
        for key, value in replacements.items():
            script = script.replace(key, value)
        Path(driver).write_text(script.lstrip())
        os.chmod(driver, 0o755)
        return driver

    def write_ase_neb_driver(self, workdir, start_xyz, final_xyz, freeze_indices):
        """
        Write a robust ASE NEB driver.

        Key points:
        - endpoints are fixed endpoints, not optimized by NEB
        - only interior images receive calculators during NEB optimization
        - final PyMOL trajectory is only the final optimized band
        - full optimizer trace is written separately for debugging
        """
        driver = os.path.join(workdir, "run_ase_neb.py")
        method_args = self.method_flag_args()

        solvent_args = []
        if self.options.solvent_model != "none" and self.options.solvent_name and self.method_box.currentText() != "gxtb":
            solvent_args = [f"--{self.options.solvent_model}", self.options.solvent_name]

        extra_args = []
        if self.options.use_etemp:
            extra_args += ["--etemp", str(float(self.options.etemp))]
        if int(self.options.iterations) > 0:
            extra_args += ["--iterations", str(int(self.options.iterations))]
        if abs(float(self.options.acc) - 1.0) > 1e-9:
            extra_args += ["--acc", str(float(self.options.acc))]

        xcontrol_path = self.build_xcontrol(os.path.join(workdir, "xcontrol_neb"), "grad", freeze_indices)
        input_args = ["--input", xcontrol_path] if xcontrol_path else []

        repl = {
            "__XTB_EXEC__": repr(self.xtb_path.text().strip() or "xtb"),
            "__METHOD_ARGS__": repr(method_args),
            "__SOLVENT_ARGS__": repr(solvent_args),
            "__EXTRA_ARGS__": repr(extra_args),
            "__INPUT_ARGS__": repr(input_args),
            "__CHARGE__": repr(str(self.charge_box.value())),
            "__UHF__": repr(str(self.mult_box.value() - 1)),
            "__WORKDIR__": repr(workdir),
            "__START_XYZ__": repr(start_xyz),
            "__FINAL_XYZ__": repr(final_xyz),
            "__FROZEN__": repr([int(i) - 1 for i in freeze_indices]),
            "__NIMAGES__": repr(int(getattr(self.options, "neb_images", 7))),
            "__FMAX__": repr(float(getattr(self.options, "neb_fmax", 0.05))),
            "__STEPS__": repr(int(getattr(self.options, "neb_steps", 200))),
            "__K__": repr(float(getattr(self.options, "neb_k", 0.10))),
            "__CLIMB__": repr(bool(getattr(self.options, "neb_climb", True))),
            "__INTERP__": repr(str(getattr(self.options, "neb_interpolate", "idpp"))),
        }

        template = """
#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from ase.io import read
from ase.mep import NEB
from ase.optimize import FIRE
from ase.calculators.calculator import Calculator, all_changes
from ase.constraints import FixAtoms

EV_PER_HARTREE = 27.211386245988
EV_PER_HARTREE_PER_BOHR_TO_EV_PER_ANG = 51.4220674763259
HARTREE_TO_KCAL = 627.509474

XTB = __XTB_EXEC__
if not os.path.isabs(XTB):
    resolved = shutil.which(XTB)
    if resolved:
        XTB = resolved

METHOD_ARGS = __METHOD_ARGS__
SOLVENT_ARGS = __SOLVENT_ARGS__
EXTRA_ARGS = __EXTRA_ARGS__
INPUT_ARGS = __INPUT_ARGS__
CHARGE_ARGS = ["--chrg", __CHARGE__, "--uhf", __UHF__]
WORKDIR = Path(__WORKDIR__)
START_XYZ = __START_XYZ__
FINAL_XYZ = __FINAL_XYZ__
FROZEN = __FROZEN__
NIMAGES = max(3, int(__NIMAGES__))
FMAX = __FMAX__
STEPS = __STEPS__
K = __K__
CLIMB = __CLIMB__
INTERP = __INTERP__

FULL_TRAJ_XYZ = WORKDIR / "ase_neb_full_trajectory.xyz"
TRAJ_XYZ = WORKDIR / "ase_neb_traj.xyz"
FINAL_PATH = WORKDIR / "ase_neb_final_path.xyz"
TS_GUESS_XYZ = WORKDIR / "ase_neb_ts_guess.xyz"
ENERGY_TABLE = WORKDIR / "ase_neb_final_energies.tsv"

float_re = re.compile(r"[-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[EeDd][-+]?\\d+)?")

def floats(text):
    return [float(x.replace("D", "E").replace("d", "e")) for x in float_re.findall(text)]

def parse_energy(text):
    patterns = [
        r"TOTAL ENERGY\\s+(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
        r"total energy\\s+(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
        r"energy\\s*[:=]\\s*(-?\\d+\\.\\d+(?:[EeDd][-+]?\\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1).replace("D", "E").replace("d", "e"))
    vals = floats(text)
    return vals[0] if vals else None

def parse_gradient_file(path, natoms):
    txt = Path(path).read_text(errors="ignore")
    triples = []
    for line in txt.splitlines():
        vals = floats(line)
        if len(vals) == 3:
            triples.append(vals)
        elif len(vals) >= 4:
            triples.append(vals[-3:])
    if len(triples) < natoms:
        raise RuntimeError("Could not parse enough gradient triples from xTB gradient file.")
    return np.array(triples[-natoms:], dtype=float)

def write_xyz(path, images, label, energies=None):
    with open(path, "a") as fh:
        for i, atoms in enumerate(images):
            e = None if energies is None else energies[i]
            fh.write("%d\\n" % len(atoms))
            if e is None:
                fh.write("%s image=%d\\n" % (label, i))
            else:
                fh.write("%s image=%d E_Eh=%.12f\\n" % (label, i, e))
            for sym, pos in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
                fh.write("%-2s % .10f % .10f % .10f\\n" % (sym, pos[0], pos[1], pos[2]))

def write_single(path, atoms, comment):
    with open(path, "w") as fh:
        fh.write("%d\\n%s\\n" % (len(atoms), comment))
        for sym, pos in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
            fh.write("%-2s % .10f % .10f % .10f\\n" % (sym, pos[0], pos[1], pos[2]))

class XTBGrad(Calculator):
    implemented_properties = ["energy", "forces"]

    def __init__(self, image_id):
        super().__init__()
        self.image_id = image_id
        self.counter = 0
        self.last_eh = None

    def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        self.counter += 1
        stepdir = WORKDIR / ("neb_img_%03d_step_%05d" % (self.image_id, self.counter))
        stepdir.mkdir(exist_ok=True)
        xyz = stepdir / "geom.xyz"
        write_single(xyz, atoms, "image %d step %d" % (self.image_id, self.counter))

        cmd = [XTB, str(xyz)] + METHOD_ARGS + CHARGE_ARGS + SOLVENT_ARGS + EXTRA_ARGS + INPUT_ARGS + ["--grad"]
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "1"
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["VECLIB_MAXIMUM_THREADS"] = "1"
        env["OMP_STACKSIZE"] = "512M"

        proc = subprocess.run(cmd, cwd=str(stepdir), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        (stepdir / "xtb.out").write_text(proc.stdout)
        if proc.returncode != 0:
            raise RuntimeError("xTB --grad failed for NEB image %d with code %s\\n%s" % (self.image_id, proc.returncode, proc.stdout[-4000:]))

        eh = parse_energy(proc.stdout)
        if eh is None:
            raise RuntimeError("Could not parse xTB energy for NEB image %d" % self.image_id)

        grad_path = stepdir / "gradient"
        if not grad_path.exists():
            candidates = list(stepdir.glob("*grad*"))
            if candidates:
                grad_path = candidates[0]
            else:
                raise RuntimeError("xTB did not write gradient file for NEB image %d" % self.image_id)

        grad_ha_bohr = parse_gradient_file(grad_path, len(atoms))
        self.last_eh = eh
        self.results["energy"] = eh * EV_PER_HARTREE
        self.results["forces"] = -grad_ha_bohr * EV_PER_HARTREE_PER_BOHR_TO_EV_PER_ANG

def energy_eh(atoms, image_id):
    if atoms.calc is None:
        atoms.calc = XTBGrad(image_id)
    return atoms.get_potential_energy() / EV_PER_HARTREE

for p in [FULL_TRAJ_XYZ, TRAJ_XYZ, FINAL_PATH, TS_GUESS_XYZ, ENERGY_TABLE]:
    if p.exists():
        p.unlink()

initial = read(START_XYZ)
final = read(FINAL_XYZ)

if len(initial) != len(final):
    raise SystemExit("NEB requires same atom count for start and product.")
if initial.get_chemical_symbols() != final.get_chemical_symbols():
    raise SystemExit("NEB requires same atom order and elements for start and product.")

endpoint_rmsd = float(np.sqrt(np.mean((initial.get_positions() - final.get_positions()) ** 2)))
print("ASE NEB endpoint Cartesian RMSD:", "%.6f" % endpoint_rmsd, flush=True)
if endpoint_rmsd < 1.0e-5:
    raise SystemExit("ASE NEB start and product geometries are essentially identical.")

images = [initial]
for _ in range(NIMAGES - 2):
    images.append(initial.copy())
images.append(final)

if FROZEN:
    for img in images:
        img.set_constraint(FixAtoms(indices=FROZEN))

neb = NEB(images, k=K, climb=CLIMB, method="improvedtangent")
neb.interpolate(method=INTERP if INTERP in ("idpp", "linear") else "idpp", apply_constraint=True)
print("ASE NEB interpolation:", INTERP, "apply_constraint=True", "frozen_atoms=", len(FROZEN), flush=True)

# Only interior images are optimized by NEB.
for i, img in enumerate(images[1:-1], start=1):
    img.calc = XTBGrad(i)

# Endpoints need energies for plotting, but are not optimized.
initial.calc = XTBGrad(0)
final.calc = XTBGrad(NIMAGES - 1)

write_xyz(FULL_TRAJ_XYZ, images, "initial_neb")

step_counter = {"n": 0}
def save_current():
    step_counter["n"] += 1
    # Save every optimizer step to debug file only.
    write_xyz(FULL_TRAJ_XYZ, images, "neb_step_%d" % step_counter["n"])
    if step_counter["n"] == 1 or step_counter["n"] % 5 == 0:
        try:
            ens = [energy_eh(img, i) for i, img in enumerate(images)]
            rel = [(e - min(ens)) * HARTREE_TO_KCAL for e in ens]
            print("ASE NEB step", step_counter["n"], "relative kcal/mol:", ["%.2f" % x for x in rel], flush=True)
        except Exception as exc:
            print("ASE NEB step", step_counter["n"], "energy print failed:", exc, flush=True)

opt = FIRE(neb, logfile=str(WORKDIR / "ase_neb.log"))
opt.attach(save_current, interval=1)
opt.run(fmax=FMAX, steps=STEPS)

final_energies = [energy_eh(img, i) for i, img in enumerate(images)]

# PyMOL display file: final band only.
write_xyz(TRAJ_XYZ, images, "final_neb", final_energies)
write_xyz(FINAL_PATH, images, "final_neb", final_energies)

valid = [(i, e) for i, e in enumerate(final_energies) if e is not None]
min_e = min(e for _, e in valid)

with open(ENERGY_TABLE, "w") as tab:
    tab.write("image\\tE_Eh\\tdE_kcal_mol\\trole\\n")
    for i, e in valid:
        role = "endpoint" if i == 0 or i == len(images) - 1 else "interior"
        tab.write("%d\\t%.12f\\t%.6f\\t%s\\n" % (i, e, (e - min_e) * HARTREE_TO_KCAL, role))

interior = [(i, e) for i, e in valid if 0 < i < len(images) - 1]
print("ASE NEB final band images:", len(images), flush=True)
print("ASE NEB final image energies relative to minimum:", flush=True)
for i, e in valid:
    role = "endpoint" if i == 0 or i == len(images) - 1 else "interior"
    print("  image", i, role, "E_Eh=", "%.12f" % e, "dE_kcal_mol=", "%.3f" % ((e - min_e) * HARTREE_TO_KCAL), flush=True)

if interior:
    ts_i, ts_e = max(interior, key=lambda item: item[1])
    write_single(
        TS_GUESS_XYZ,
        images[ts_i],
        "ASE_NEB_TS_guess interior_image=%d E_Eh=%.12f dE_kcal_mol=%.6f" % (ts_i, ts_e, (ts_e - min_e) * HARTREE_TO_KCAL),
    )
    print("ASE NEB highest-energy interior TS guess image:", ts_i, "E_Eh=", "%.12f" % ts_e, "dE_kcal_mol=", "%.3f" % ((ts_e - min_e) * HARTREE_TO_KCAL), flush=True)
    print("Wrote ASE NEB TS guess:", TS_GUESS_XYZ, flush=True)
else:
    print("WARNING: no interior NEB images were available; cannot define TS guess.", flush=True)

print("Wrote ASE NEB final-band trajectory:", TRAJ_XYZ, flush=True)
print("Full optimizer trace kept at:", FULL_TRAJ_XYZ, flush=True)
"""
        script = template
        for k, v in repl.items():
            script = script.replace(k, v)
        Path(driver).write_text(script.lstrip())
        os.chmod(driver, 0o755)
        return driver

    def start_job(self):
        obj = self.object_box.currentText().strip()
        if not obj:
            QtWidgets.QMessageBox.warning(self, "g-xTB", "No object or selection selected.")
            return
        calc = self.calc_box.currentText()
        workdir = tempfile.mkdtemp(prefix="pymol_gxtb_")
        self.last_job_dir = workdir
        xyz_file = os.path.join(workdir, "input.xyz")
        final_xyz = os.path.join(workdir, "final.xyz")

        try:
            start_sel = self.options.path_start_selection or obj
            final_sel = self.options.path_final_selection
            if calc in ("path", "neb_ase"):
                if not final_sel:
                    raise ValueError("Path/NEB calculation requires a final/product object in More options → Path / GSM.")
                if calc == "neb_ase":
                    # For NEB, requiring explicit start/final avoids silently doing PROD→PROD
                    # when the main selected object happens to be the product.
                    if not self.options.path_start_selection:
                        raise ValueError("ASE NEB requires explicit Start/reactant selection in More options → Path / GSM.")
                    if sanitize_name(start_sel) == sanitize_name(final_sel):
                        raise ValueError("ASE NEB start/reactant and final/product selections appear to be the same.")
                self.write_xyz_from_selection(start_sel, xyz_file, "Reactant/start from PyMOL")
                self.write_xyz_from_selection(final_sel, final_xyz, "Product/final from PyMOL")
                if calc == "path" and self.options.path_preview:
                    preview = os.path.join(workdir, "interpolated_path_preview.xyz")
                    n = self.write_interpolated_path(start_sel, final_sel, preview, self.options.path_images, self.options.path_include_endpoints)
                    self.append_log(f"[Path] Wrote preview path with {n} frames: {preview}")
            elif calc in ("gsm_prepare", "gsm_run"):
                if not final_sel:
                    raise ValueError("GSM requires a final/product object in More options → Path / GSM.")
                self.write_xyz_from_selection(start_sel, xyz_file, "GSM reactant from PyMOL")
                self.prepare_gsm_files(workdir, start_sel, final_sel)
            elif calc == "ts_sella":
                self.write_xyz_from_selection(obj, xyz_file, "ASE/Sella TS initial structure from PyMOL")
            else:
                self.write_xyz_from_selection(obj, xyz_file, "PyMOL export")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "g-xTB", f"Could not prepare input geometry:\n{exc}")
            return

        freeze_indices = self.compute_freeze_indices(obj, self.options.freeze_selection)
        try:
            if calc == "ts_sella":
                driver = self.write_sella_ts_driver(workdir, xyz_file, freeze_indices)
                ase_python_cmd = self.ase_python_command()
                if not ase_python_cmd:
                    raise ValueError("No suitable Python 3.10–3.12 found for ASE/Sella. Use 'Install ASE/Sella deps' or set ASE Python in More options.")
                cmdline = ase_python_cmd + [driver]
            elif calc == "neb_ase":
                driver = self.write_ase_neb_driver(workdir, xyz_file, final_xyz, freeze_indices)
                ase_python_cmd = self.ase_python_command()
                if not ase_python_cmd:
                    raise ValueError("No suitable Python 3.10–3.12 found for ASE/NEB. Use 'Install ASE/Sella deps' or set ASE Python in More options.")
                cmdline = ase_python_cmd + [driver]
            else:
                cmdline = self.build_command(xyz_file, workdir, calc, final_xyz if os.path.exists(final_xyz) else None, freeze_indices)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "g-xTB", f"Could not build command:\n{exc}")
            return

        self.persist_settings()
        self.log.clear()
        self.append_log("Working directory: " + workdir)
        if calc == "gsm_prepare":
            self.status.setText(f"GSM files prepared: {workdir}")
            self.append_log("[GSM] Files prepared; no external program launched.")
            return
        self.append_log("Command: " + " ".join(map(str, cmdline)))
        if calc == "neb_ase":
            self.append_log(f"[ASE NEB] Start/reactant: {start_sel}")
            self.append_log(f"[ASE NEB] Final/product: {final_sel}")
            self.append_log("[ASE NEB] PyMOL movie/plot will use only the final optimized NEB band.")
            self.append_log("[ASE NEB] Full optimizer trace is saved as ase_neb_full_trajectory.xyz in the job folder.")
            self.append_log("[ASE NEB] TS guess will be selected from interior images only, never endpoints.")
        Path(os.path.join(workdir, "run_job.sh")).write_text("#!/bin/sh\ncd " + repr(workdir) + "\n" + " ".join(map(repr, cmdline)) + "\n")
        # Also write a Windows batch helper for portability.
        try:
            bat_lines = ["@echo off", f"cd /d {workdir}"]
            import subprocess as _sp
            bat_lines.append(_sp.list2cmdline([str(x) for x in cmdline]))
            Path(os.path.join(workdir, "run_job.bat")).write_text("\n".join(bat_lines) + "\n")
        except Exception:
            pass

        if calc == "neb_ase":
            self.traj_object = f"{sanitize_name(start_sel or obj)}_to_{sanitize_name(final_sel or 'PROD')}_ASE_NEB"
        elif calc == "ts_sella":
            self.traj_object = f"{sanitize_name(obj)}_Sella_TS_traj"
        else:
            self.traj_object = f"{sanitize_name(obj)}_gxtb_traj"
        # Remove stale trajectory object from previous jobs with the same input name.
        # This avoids carrying old state/movie metadata into a new longer TS/optimization run.
        try:
            if safe_obj_exists(self.traj_object):
                cmd.delete(self.traj_object)
            cmd.mset("1")
        except Exception:
            pass
        self.status.setText("Running...")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.plot.set_energies([])
        self.plot.set_current_frame(None)
        self.energy_readout.setText("Energy readout: no frame selected.")
        self.vibration_modes = []
        self.vibration_base_atoms = []
        self.vib_table.setRowCount(0)
        self.vib_status.setText("Run a Hessian calculation to populate frequencies.")

        worker_env = None
        retry_cmdline = None
        retry_env = None
        if calc == "hess":
            hmode = getattr(self.options, "hess_mode", "auto_retry_balanced_safe")
            worker_env = self.hessian_env_for_mode(hmode)
            self.append_log("[Hessian mode] " + self.describe_hessian_mode(hmode))

            if worker_env:
                self.append_log(
                    "[Hessian environment] "
                    f"OMP_NUM_THREADS={worker_env.get('OMP_NUM_THREADS')}, "
                    f"OPENBLAS_NUM_THREADS={worker_env.get('OPENBLAS_NUM_THREADS')}, "
                    f"OMP_STACKSIZE={worker_env.get('OMP_STACKSIZE')}"
                )

            if hmode == "auto_retry_balanced_safe":
                retry_cmdline = list(cmdline)
                # Replace an existing --parallel N with --parallel 1.
                if "--parallel" in retry_cmdline:
                    try:
                        idx = retry_cmdline.index("--parallel")
                        retry_cmdline[idx + 1] = "1"
                    except Exception:
                        retry_cmdline += ["--parallel", "1"]
                else:
                    retry_cmdline += ["--parallel", "1"]

                retry_env = self.hessian_env_for_mode("safe1")

        self.worker = XTBWorker(
            cmdline,
            workdir,
            self.traj_object,
            self.options.dynamic_rebond,
            env=worker_env,
            calc_type=calc,
            retry_command=retry_cmdline,
            retry_env=retry_env,
        )
        self.worker.log_line.connect(self.append_log)
        self.worker.energy_update.connect(self.plot.set_energies)
        self.worker.trajectory_update.connect(self.on_trajectory_update)
        self.worker.partial_vibration_check.connect(self.on_partial_vibration_check)
        self.worker.finished_ok.connect(self.on_job_finished)
        self.worker.start()

    def stop_job(self):
        if self.worker:
            self.worker.stop()

    def apply_representation(self, obj_name):
        try:
            if not safe_obj_exists(obj_name):
                return
            cmd.hide("everything", obj_name)
            try:
                cmd.rebond(obj_name)
            except Exception:
                pass
            cmd.show("sticks", obj_name)
            cmd.show("spheres", obj_name)
            cmd.set("sphere_scale", 0.2, obj_name)
            cmd.set("sphere_scale", 0.2)
            cmd.set("stick_radius", 0.12, obj_name)
            cmd.refresh()
        except Exception as exc:
            self.append_log(f"[Representation warning] {exc}")

    def sync_pymol_movie_to_states(self, obj_name, nstates, frame=None):
        """
        PyMOL's movie frame range can remain from a previous object, for example
        a 21-frame vibration. Explicitly reset mset to the current trajectory
        length so the user can scrub all states.
        """
        try:
            nstates = int(nstates)
            if nstates < 1:
                return
            cmd.mset(f"1 -{nstates}")
            cmd.set("all_states", 0)
            # Do not set object-specific "state"; that freezes the object on one state.
            cmd.frame(int(frame or nstates))
            cmd.refresh()
        except Exception as exc:
            self.append_log(f"[Movie sync warning] {exc}")

    def on_trajectory_update(self, obj_name, nstates):
        self.traj_object = obj_name
        self.apply_representation(obj_name)
        self.sync_pymol_movie_to_states(obj_name, nstates, frame=nstates)
        self.status.setText(f"Running... loaded {nstates} trajectory states.")

    def on_partial_vibration_check(self, workdir, message):
        self.append_log("[Vibration] " + message)
        try:
            self.load_vibrations_from_job(workdir)
            if self.vibration_modes:
                self.append_log("[Vibration] Partial normal-mode output was parsed despite the xTB crash.")
            else:
                self.append_log(
                    "[Hessian advice] No usable g98.out/vibration vectors were produced before the crash. "
                    "The auto-retry will use Safe/serial mode if enabled. If it still fails, try: "
                    "smaller system, looser SCC accuracy, no constraints, or a different xTB/g-xTB binary."
                )
        except Exception as exc:
            self.append_log(f"[Vibration warning] Partial parse failed: {exc}")

    def on_job_finished(self, ok, message):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(message)
        if self.traj_object:
            self.apply_representation(self.traj_object)
            try:
                if safe_obj_exists(self.traj_object):
                    self.sync_pymol_movie_to_states(self.traj_object, int(cmd.count_states(self.traj_object)), frame=int(cmd.count_states(self.traj_object)))
            except Exception as exc:
                self.append_log(f"[Movie sync warning] {exc}")

        # If this was a Hessian/frequency calculation, parse normal modes and populate
        # the vibration viewer. This is additive and does not affect normal optimization/path jobs.
        try:
            if ok and self.calc_box.currentText() == "hess" and self.last_job_dir:
                self.load_vibrations_from_job(self.last_job_dir)
        except Exception as exc:
            self.append_log(f"[Vibration warning] Could not parse vibrations: {exc}")

        # For Sella TS, print the trajectory energy table if available.
        try:
            if self.calc_box.currentText() == "ts_sella" and self.last_job_dir:
                table = os.path.join(self.last_job_dir, "sella_ts_energies.tsv")
                if os.path.exists(table):
                    self.append_log("[Sella TS] Energy table:")
                    for line in Path(table).read_text(errors="ignore").splitlines()[:80]:
                        self.append_log("[Sella TS] " + line)
        except Exception as exc:
            self.append_log(f"[Sella TS warning] Could not read energy table: {exc}")

        # For ASE NEB, load the highest-energy final-band image as a separate TS guess object.
        try:
            if self.calc_box.currentText() == "neb_ase" and self.last_job_dir:
                ts_guess = os.path.join(self.last_job_dir, "ase_neb_ts_guess.xyz")
                if os.path.exists(ts_guess) and os.path.getsize(ts_guess) > 0:
                    obj_name = sanitize_name((self.traj_object or "ASE_NEB") + "_TS_guess")
                    if safe_obj_exists(obj_name):
                        cmd.delete(obj_name)
                    cmd.load(ts_guess, obj_name, format="xyz", quiet=1)
                    cmd.hide("everything", obj_name)
                    try:
                        cmd.rebond(obj_name)
                    except Exception:
                        pass
                    cmd.show("sticks", obj_name)
                    cmd.show("spheres", obj_name)
                    cmd.set("sphere_scale", 0.2, obj_name)
                    cmd.set("stick_radius", 0.12, obj_name)
                    self.append_log(f"[ASE NEB] Loaded highest-energy image as TS guess object: {obj_name}")
                table = os.path.join(self.last_job_dir, "ase_neb_final_energies.tsv")
                if os.path.exists(table):
                    try:
                        self.append_log("[ASE NEB] Final image energy table:")
                        for line in Path(table).read_text(errors="ignore").splitlines()[:50]:
                            self.append_log("[ASE NEB] " + line)
                    except Exception:
                        pass
        except Exception as exc:
            self.append_log(f"[ASE NEB warning] Could not load TS guess object: {exc}")

    def load_vibrations_from_job(self, workdir):
        modes, message = find_hessian_modes(workdir)
        self.vibration_modes = modes
        self.vib_table.setRowCount(0)

        # Use input.xyz as the base geometry. For frequency jobs the user normally runs
        # Hessian on the optimized object they selected in PyMOL.
        atoms = read_xyz_geometry(os.path.join(workdir, "input.xyz"))
        self.vibration_base_atoms = atoms

        for row, mode in enumerate(modes):
            self.vib_table.insertRow(row)
            self.vib_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(mode.index)))
            self.vib_table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{mode.frequency:.4f}"))
            self.vib_table.setItem(row, 2, QtWidgets.QTableWidgetItem(mode.source))

        if modes:
            imag = [m for m in modes if m.frequency < 0.0]
            extra = f" Imaginary modes: {len(imag)}." if imag else ""
            self.vib_status.setText(message + extra + " Select a row and click 'Show selected vibration'.")
            self.vib_group.setChecked(True)
            self.vib_table.selectRow(0)
            self.append_log("[Vibration] " + message + extra)
        else:
            self.vib_status.setText(message)
            self.append_log("[Vibration] " + message)

    def selected_vibration_mode(self):
        rows = self.vib_table.selectionModel().selectedRows() if self.vib_table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self.vibration_modes):
            return self.vibration_modes[row]
        return None

    def on_vibration_selection_changed(self):
        mode = self.selected_vibration_mode()
        if mode:
            self.vib_status.setText(
                f"Selected mode {mode.index}: {mode.frequency:.4f} cm⁻¹. "
                "Click 'Show selected vibration' to load/refresh the PyMOL animation."
            )

    def show_selected_vibration(self):
        mode = self.selected_vibration_mode()
        if not mode:
            self.vib_status.setText("No vibration mode selected.")
            return
        if not self.last_job_dir:
            self.vib_status.setText("No job directory available.")
            return
        try:
            atoms = self.vibration_base_atoms or read_xyz_geometry(os.path.join(self.last_job_dir, "input.xyz"))
            if not atoms:
                raise ValueError("Could not read base geometry from input.xyz.")

            vib_dir = os.path.join(self.last_job_dir, "_pymol_vibrations")
            os.makedirs(vib_dir, exist_ok=True)
            vib_xyz = os.path.join(vib_dir, f"mode_{mode.index:04d}.xyz")
            write_vibration_xyz(
                atoms,
                mode,
                vib_xyz,
                amplitude=float(self.vib_amp.value()),
                nframes=int(self.vib_frames.value()),
            )

            base = sanitize_name(self.object_box.currentText().strip() or "vibration")
            obj_name = f"{base}_mode_{mode.index:04d}_{mode.frequency:.0f}cm"
            obj_name = sanitize_name(obj_name)

            if safe_obj_exists(obj_name):
                cmd.delete(obj_name)
            cmd.load(vib_xyz, obj_name, state=0, format="xyz", finish=1, discrete=0, quiet=1, multiplex=0)
            nstates_loaded = int(cmd.count_states(obj_name))
            cmd.hide("everything", obj_name)
            try:
                cmd.rebond(obj_name)
            except Exception:
                pass
            cmd.show("sticks", obj_name)
            cmd.show("spheres", obj_name)
            cmd.set("sphere_scale", 0.2, obj_name)
            cmd.set("stick_radius", 0.12, obj_name)
            cmd.mset(f"1 -{nstates_loaded}")
            cmd.set("all_states", 0)
            cmd.frame(1)
            cmd.refresh()

            self.vibration_object = obj_name
            self.vib_status.setText(
                f"Loaded vibration object '{obj_name}' with {nstates_loaded} states "
                f"for mode {mode.index} ({mode.frequency:.4f} cm⁻¹). "
                "Press Play in PyMOL or scrub states to see the vibration."
            )
            self.append_log(f"[Vibration] Loaded {obj_name} from {vib_xyz}")

        except Exception as exc:
            self.vib_status.setText(f"Could not show vibration: {exc}")
            self.append_log(f"[Vibration warning] {exc}")


    def build_irc_opt_command(self, xyz_file, workdir, freeze_indices=None):
        """
        Build xTB optimization command for one IRC-like downhill branch.
        This reuses the selected method/settings but always performs an optimization.
        """
        xtb_exec = self.xtb_path.text().strip() or "xtb"
        cmdline = [xtb_exec, xyz_file] + self.method_flag_args()
        cmdline += ["--chrg", str(self.charge_box.value()), "--uhf", str(self.mult_box.value() - 1)]

        method = self.method_box.currentText()
        if self.options.solvent_model != "none" and self.options.solvent_name:
            if method == "gxtb":
                self.append_log("[IRC solvent warning] Skipping implicit solvent with gxtb to avoid missing ALPB/GBSA parameter crash.")
            else:
                cmdline += [f"--{self.options.solvent_model}", self.options.solvent_name]

        if self.options.use_etemp:
            cmdline += ["--etemp", str(float(self.options.etemp))]
        if int(self.options.iterations) > 0:
            cmdline += ["--iterations", str(int(self.options.iterations))]
        if abs(float(self.options.acc) - 1.0) > 1e-9:
            cmdline += ["--acc", str(float(self.options.acc))]

        cmdline += ["--opt", self.options.opt_level]
        if int(self.options.cycles) > 0:
            cmdline += ["--cycles", str(int(self.options.cycles))]

        xcontrol = self.build_xcontrol(os.path.join(workdir, "xcontrol"), "opt", freeze_indices)
        if xcontrol:
            cmdline += ["--input", xcontrol]
        return cmdline

    def run_irc_from_selected_mode(self):
        mode = self.selected_vibration_mode()
        if not mode:
            self.vib_status.setText("Select an imaginary/low-frequency mode first.")
            return
        if not self.last_job_dir:
            self.vib_status.setText("No Hessian job directory available.")
            return

        try:
            atoms = self.vibration_base_atoms or read_xyz_geometry(os.path.join(self.last_job_dir, "input.xyz"))
            if not atoms:
                raise ValueError("Could not read TS/base geometry from input.xyz.")

            if mode.frequency >= 0:
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "IRC from non-imaginary mode?",
                    f"Selected mode {mode.index} has positive frequency {mode.frequency:.2f} cm⁻¹. "
                    "IRC is normally started from an imaginary mode. Continue anyway?",
                )
                if reply != QtWidgets.QMessageBox.Yes:
                    return

            workdir = tempfile.mkdtemp(prefix="pymol_gxtb_irc_")
            self.last_job_dir = workdir

            ts_xyz = os.path.join(workdir, "ts.xyz")
            minus_xyz = os.path.join(workdir, "minus_start.xyz")
            plus_xyz = os.path.join(workdir, "plus_start.xyz")
            write_single_xyz_from_atoms(atoms, ts_xyz, f"TS/base mode={mode.index} freq={mode.frequency:.4f}")
            write_displaced_mode_xyz(atoms, mode, minus_xyz, displacement=float(self.irc_disp.value()), sign=-1.0)
            write_displaced_mode_xyz(atoms, mode, plus_xyz, displacement=float(self.irc_disp.value()), sign=+1.0)

            obj = self.object_box.currentText().strip()
            freeze_indices = self.compute_freeze_indices(obj, self.options.freeze_selection)

            minus_dir = os.path.join(workdir, "minus")
            plus_dir = os.path.join(workdir, "plus")
            os.makedirs(minus_dir, exist_ok=True)
            os.makedirs(plus_dir, exist_ok=True)

            minus_cmd = self.build_irc_opt_command(minus_xyz, minus_dir, freeze_indices)
            plus_cmd = self.build_irc_opt_command(plus_xyz, plus_dir, freeze_indices)

            self.traj_object = f"{sanitize_name(obj or 'TS')}_irc_mode_{mode.index}"
            if safe_obj_exists(self.traj_object):
                try:
                    cmd.delete(self.traj_object)
                except Exception:
                    pass

            self.log.clear()
            self.append_log("IRC-like working directory: " + workdir)
            self.append_log("Minus command: " + " ".join(map(str, minus_cmd)))
            self.append_log("Plus command: " + " ".join(map(str, plus_cmd)))
            self.append_log("[IRC] This is an IRC-like workflow: displace ± imaginary mode, optimize both downhill sides, then combine the path.")
            self.status.setText("Running IRC-like ± downhill optimizations...")
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.irc_btn.setEnabled(False)
            self.plot.set_energies([])
            self.plot.set_current_frame(None)
            self.energy_readout.setText("Energy readout: IRC running.")

            self.irc_worker = IRCWorker(
                minus_cmd=minus_cmd,
                plus_cmd=plus_cmd,
                workdir=workdir,
                minus_dir=minus_dir,
                plus_dir=plus_dir,
                ts_xyz=ts_xyz,
                traj_object=self.traj_object,
                dynamic_rebond=self.options.dynamic_rebond,
            )
            self.irc_worker.log_line.connect(self.append_log)
            self.irc_worker.energy_update.connect(self.plot.set_energies)
            self.irc_worker.trajectory_update.connect(self.on_trajectory_update)
            self.irc_worker.finished_ok.connect(self.on_irc_finished)
            self.worker = self.irc_worker
            self.irc_worker.start()

        except Exception as exc:
            self.vib_status.setText(f"Could not start IRC: {exc}")
            self.append_log(f"[IRC warning] {exc}")

    def on_irc_finished(self, ok, message):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.irc_btn.setEnabled(True)
        self.status.setText(message)
        self.vib_status.setText(message)
        if self.traj_object and safe_obj_exists(self.traj_object):
            self.apply_representation(self.traj_object)
            try:
                nstates = int(cmd.count_states(self.traj_object))
                self.sync_pymol_movie_to_states(self.traj_object, nstates, frame=nstates)
            except Exception:
                pass


    def set_pymol_frame(self, frame):
        try:
            cmd.frame(int(frame))
            self.plot.set_current_frame(int(frame))
            self.update_energy_readout(int(frame))
        except Exception as exc:
            self.append_log(f"[Frame warning] {exc}")

    def poll_current_frame(self):
        if not self.traj_object or not safe_obj_exists(self.traj_object):
            return
        try:
            frame = int(cmd.get("state"))
        except Exception:
            try:
                frame = int(cmd.get_state())
            except Exception:
                return
        self.plot.set_current_frame(frame)
        self.update_energy_readout(frame)

    def update_energy_readout(self, frame):
        energies = self.plot.energies
        if not energies or not frame or frame < 1 or frame > len(energies):
            self.energy_readout.setText("Energy readout: no energy available for current frame.")
            return
        e = energies[frame - 1]
        rel_first = (e - energies[0]) * HARTREE_TO_KCAL_MOL
        rel_min = (e - min(energies)) * HARTREE_TO_KCAL_MOL
        self.energy_readout.setText(f"Frame {frame}: E = {e:.8f} Eh | ΔE vs first = {rel_first:.2f} kcal/mol | ΔE vs minimum = {rel_min:.2f} kcal/mol")


# ----------------------------- Dependency installer ----------------------------

class DependencyInstallerWorker(QtCore.QThread):
    log_line = QtCore.Signal(str)
    finished_ok = QtCore.Signal(bool, str)

    def __init__(self, command, bootstrap_only=False):
        super().__init__()
        # command may be a single command, a list of commands, or command specs:
        # {"optional": cmd}
        # {"try_any": [cmd1, cmd2, ...], "label": "..."}
        self.command = command
        self.bootstrap_only = bootstrap_only

    @staticmethod
    def command_to_text(command):
        if isinstance(command, dict):
            if "optional" in command:
                return "(optional) " + " ".join(map(str, command["optional"]))
            if "try_any" in command:
                label = command.get("label", "fallback command group")
                return label + ": " + " OR ".join(" ".join(map(str, c)) for c in command["try_any"])
            return str(command)
        return " ".join(map(str, command))

    def _run_plain_command(self, command):
        self.log_line.emit("[Dependencies] " + " ".join(map(str, command)))
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            self.log_line.emit(line.rstrip())
        return proc.wait()

    def run(self):
        try:
            commands = self.command
            if commands and isinstance(commands[0], str):
                commands = [commands]

            for idx, spec in enumerate(commands, start=1):
                self.log_line.emit(f"[Dependencies] Running step {idx}/{len(commands)}")

                if isinstance(spec, dict) and "optional" in spec:
                    rc = self._run_plain_command(spec["optional"])
                    if rc != 0:
                        self.log_line.emit(f"[Dependencies] Optional step failed with code {rc}; continuing.")
                    continue

                if isinstance(spec, dict) and "try_any" in spec:
                    label = spec.get("label", "fallback command group")
                    last_rc = None
                    for attempt_no, command in enumerate(spec["try_any"], start=1):
                        self.log_line.emit(f"[Dependencies] {label}: attempt {attempt_no}/{len(spec['try_any'])}")
                        last_rc = self._run_plain_command(command)
                        if last_rc == 0:
                            self.log_line.emit(f"[Dependencies] {label}: succeeded on attempt {attempt_no}.")
                            break
                    else:
                        self.finished_ok.emit(False, f"{label} failed; last exit code {last_rc}.")
                        return
                    continue

                rc = self._run_plain_command(spec)
                if rc != 0:
                    self.finished_ok.emit(False, f"Dependency install step {idx} exited with code {rc}.")
                    return

            self.finished_ok.emit(True, "ASE/Sella dependencies installed and import check passed.")
        except Exception as exc:
            self.finished_ok.emit(False, f"Dependency install failed: {exc}")


# ----------------------------- Worker thread ----------------------------------

class IRCWorker(QtCore.QThread):
    log_line = QtCore.Signal(str)
    energy_update = QtCore.Signal(list)
    trajectory_update = QtCore.Signal(str, int)
    finished_ok = QtCore.Signal(bool, str)

    def __init__(self, minus_cmd, plus_cmd, workdir, minus_dir, plus_dir, ts_xyz, traj_object, dynamic_rebond=False):
        super().__init__()
        self.minus_cmd = minus_cmd
        self.plus_cmd = plus_cmd
        self.workdir = workdir
        self.minus_dir = minus_dir
        self.plus_dir = plus_dir
        self.ts_xyz = ts_xyz
        self.traj_object = traj_object
        self.dynamic_rebond = dynamic_rebond
        self._stop = False
        self.proc = None

    def stop(self):
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def run_command(self, command, cwd, label):
        self.log_line.emit(f"[IRC] Running {label} branch...")
        self.proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        stdout_lines = []
        for line in self.proc.stdout:
            if self._stop:
                self.stop()
                break
            stdout_lines.append(line)
            self.log_line.emit(line.rstrip())
        rc = self.proc.wait()
        Path(os.path.join(cwd, "branch.out")).write_text("".join(stdout_lines))
        return rc

    def branch_trajectory(self, branch_dir):
        for name in ["xtbopt.log", "xtbopt.xyz", "xtb.trj"]:
            p = os.path.join(branch_dir, name)
            if os.path.exists(p) and os.path.getsize(p) > 0 and is_xyz_like(p):
                frames = read_multixyz_frames(p)
                if frames:
                    return frames
        # fallback: final optimized geometry
        p = os.path.join(branch_dir, "xtbopt.xyz")
        if os.path.exists(p):
            return read_multixyz_frames(p)
        return []

    def load_combined(self, frames, energies):
        frame_dir = os.path.join(self.workdir, "_pymol_irc_frames")
        os.makedirs(frame_dir, exist_ok=True)
        if safe_obj_exists(self.traj_object):
            try:
                cmd.delete(self.traj_object)
            except Exception:
                pass

        for state, (_, _, block) in enumerate(frames, start=1):
            frame_path = os.path.join(frame_dir, f"irc_frame_{state:05d}.xyz")
            Path(frame_path).write_text(block)
            cmd.load(frame_path, self.traj_object, state=state, format="xyz", finish=1, discrete=0, quiet=1, multiplex=0)

        if safe_obj_exists(self.traj_object):
            cmd.hide("everything", self.traj_object)
            if self.dynamic_rebond:
                try:
                    cmd.rebond(self.traj_object)
                except Exception:
                    pass
            cmd.show("sticks", self.traj_object)
            cmd.show("spheres", self.traj_object)
            cmd.set("sphere_scale", 0.2, self.traj_object)
            cmd.set("stick_radius", 0.12, self.traj_object)
            nstates = int(cmd.count_states(self.traj_object))
            cmd.mset(f"1 -{nstates}")
            cmd.set("all_states", 0)
            cmd.frame(nstates)
            cmd.refresh()
            self.energy_update.emit(energies)
            self.trajectory_update.emit(self.traj_object, nstates)

    def run(self):
        try:
            rc_minus = self.run_command(self.minus_cmd, self.minus_dir, "minus")
            if self._stop:
                self.finished_ok.emit(False, "IRC stopped.")
                return
            rc_plus = self.run_command(self.plus_cmd, self.plus_dir, "plus")
            if self._stop:
                self.finished_ok.emit(False, "IRC stopped.")
                return

            minus_frames = self.branch_trajectory(self.minus_dir)
            plus_frames = self.branch_trajectory(self.plus_dir)
            ts_frames = read_multixyz_frames(self.ts_xyz)

            if not minus_frames and not plus_frames:
                self.finished_ok.emit(False, "IRC branches finished but no trajectories were found.")
                return

            # Reaction coordinate order: minus minimum -> ... -> TS -> ... -> plus minimum.
            combined = []
            combined.extend(list(reversed(minus_frames)))
            if ts_frames:
                combined.extend(ts_frames[:1])
            combined.extend(plus_frames)

            # Energies are plotted relative to the maximum available energy, which should
            # usually be near the TS. Missing energies are omitted from the plot marker but
            # object states remain visible.
            energies = []
            for _, comment, _ in combined:
                e = frame_energy_or_none(comment)
                if e is not None:
                    energies.append(e)

            combined_path = os.path.join(self.workdir, "irc_combined.xyz")
            with open(combined_path, "w") as fh:
                for _, _, block in combined:
                    fh.write(block)
            self.log_line.emit(f"[IRC] Combined path written: {combined_path}")

            if energies:
                self.energy_update.emit(energies)
            else:
                self.log_line.emit("[IRC warning] No energies found in trajectory comments; object will load without energy plot values.")

            self.load_combined(combined, energies)
            if rc_minus == 0 and rc_plus == 0:
                self.finished_ok.emit(True, f"IRC-like ± optimizations finished. Job folder: {self.workdir}")
            else:
                self.finished_ok.emit(False, f"IRC finished with branch exit codes minus={rc_minus}, plus={rc_plus}. Job folder: {self.workdir}")

        except Exception as exc:
            self.finished_ok.emit(False, f"IRC runtime error: {exc}")


class XTBWorker(QtCore.QThread):
    log_line = QtCore.Signal(str)
    energy_update = QtCore.Signal(list)
    trajectory_update = QtCore.Signal(str, int)
    finished_ok = QtCore.Signal(bool, str)
    partial_vibration_check = QtCore.Signal(str, str)

    def __init__(self, command, workdir, traj_object, dynamic_rebond=False, env=None, calc_type="", retry_command=None, retry_env=None):
        super().__init__()
        self.command = command
        self.workdir = workdir
        self.traj_object = traj_object
        self.dynamic_rebond = dynamic_rebond
        self.env = env
        self.calc_type = calc_type
        self.retry_command = retry_command
        self.retry_env = retry_env
        self.proc = None
        self._stop = False
        self.energies = []
        self.last_mtime = 0.0
        self.last_size = -1
        self.loaded_frame_count = 0
        self.active_traj_path = None
        self.frame_dir = os.path.join(self.workdir, "_pymol_frames")

    def stop(self):
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def trajectory_candidates(self):
        # Prefer true trajectory files before final single-geometry files.
        # xTB often writes xtbopt.xyz as the final optimized structure, while
        # xtbopt.log contains the multi-XYZ optimization history.
        return [
            os.path.join(self.workdir, "ase_neb_traj.xyz"),
            os.path.join(self.workdir, "mode_rc_scan.xyz"),
            os.path.join(self.workdir, "sella_ts_traj.xyz"),
            os.path.join(self.workdir, "xtbopt.log"),
            os.path.join(self.workdir, "xtb.trj"),
            os.path.join(self.workdir, "xtbpath.log"),
            os.path.join(self.workdir, "xtbpath.xyz"),
            os.path.join(self.workdir, "xtbopt.xyz"),
        ]

    def _run_subprocess_once(self, command, env, label=""):
        try:
            self.proc = subprocess.Popen(command, cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        except Exception as exc:
            return None, f"Could not launch calculation{label}: {exc}"

        last_poll = 0.0
        try:
            for line in self.proc.stdout:
                if self._stop:
                    break
                self.log_line.emit(line.rstrip())
                e = parse_stdout_energy(line)
                if e is not None and (not self.energies or abs(e - self.energies[-1]) > 1e-12):
                    self.energies.append(e)
                    self.energy_update.emit(self.energies)
                now = time.time()
                if now - last_poll > 0.8:
                    self.try_load_trajectory()
                    last_poll = now
            if self._stop:
                self.stop()
            rc = self.proc.wait()
            self.try_load_trajectory(final=True)
            return rc, None
        except Exception as exc:
            return None, f"Runtime error{label}: {exc}"

    def run(self):
        rc, error = self._run_subprocess_once(self.command, self.env, "")
        if error:
            self.finished_ok.emit(False, error)
            return

        if self._stop:
            self.finished_ok.emit(False, "Stopped.")
            return

        if rc == 0:
            self.finished_ok.emit(True, f"Finished. Job folder: {self.workdir}")
            return

        # For Hessian segfaults, optionally retry once with safer serial settings.
        if self.calc_type == "hess":
            if rc == -11:
                self.log_line.emit("[Hessian crash] xTB ended with SIGSEGV (-11). This is an xTB/binary-level crash, not a PyMOL plugin exception.")
            elif rc == -6:
                self.log_line.emit("[Hessian crash] xTB ended with SIGABRT (-6). This is an xTB/binary-level abort, not a PyMOL plugin exception.")
            self.partial_vibration_check.emit(self.workdir, f"Calculation exited with code {rc}; checking for partial Hessian/frequency output.")

            if rc in (-11, -6) and self.retry_command is not None:
                self.log_line.emit("[Hessian auto-retry] Retrying with Safe/serial Hessian mode: --parallel 1, OMP_NUM_THREADS=1, BLAS threads=1.")
                self.command = self.retry_command
                rc2, error2 = self._run_subprocess_once(self.retry_command, self.retry_env, " during safe Hessian retry")
                if error2:
                    self.finished_ok.emit(False, error2)
                    return
                self.partial_vibration_check.emit(self.workdir, f"Safe retry exited with code {rc2}; checking for Hessian/frequency output.")
                if self._stop:
                    self.finished_ok.emit(False, "Stopped.")
                elif rc2 == 0:
                    self.finished_ok.emit(True, f"Finished after safe Hessian retry. Job folder: {self.workdir}")
                else:
                    self.finished_ok.emit(False, f"Calculation exited with code {rc}; safe retry exited with code {rc2}. Job folder: {self.workdir}")
                return

        self.finished_ok.emit(False, f"Calculation exited with code {rc}. Job folder: {self.workdir}")


    def _rebuild_multistate_object(self, frames):
        """
        Deterministically rebuild a PyMOL multi-state object from all frames.

        This uses a multi-model PDB intermediate instead of repeated XYZ
        cmd.load(..., state=N). Some PyMOL builds display repeated XYZ-loaded
        states as if every state had the final coordinates. MODEL/ENDMDL PDB
        loading is much more reliable for state scrolling.
        """
        frame_dir = os.path.join(self.workdir, "_pymol_frames")
        os.makedirs(frame_dir, exist_ok=True)

        if safe_obj_exists(self.traj_object):
            try:
                cmd.delete(self.traj_object)
            except Exception:
                pass

        pdb_path = os.path.join(frame_dir, "trajectory_multistate.pdb")
        write_multimodel_pdb_from_xyz_frames(frames, pdb_path)

        cmd.load(
            pdb_path,
            self.traj_object,
            state=0,
            format="pdb",
            finish=1,
            discrete=0,
            quiet=1,
            multiplex=0,
        )

        if not safe_obj_exists(self.traj_object):
            raise RuntimeError(f"PyMOL did not create trajectory object {self.traj_object}")

        self.loaded_frame_count = len(frames)
        self._apply_traj_representation()
        nstates = int(cmd.count_states(self.traj_object))

        # If PyMOL unexpectedly collapsed the multi-model PDB, fall back to XYZ-per-state.
        if nstates < len(frames):
            try:
                cmd.delete(self.traj_object)
            except Exception:
                pass
            for state, (_, _, block) in enumerate(frames, start=1):
                frame_path = os.path.join(frame_dir, f"frame_{state:05d}.xyz")
                with open(frame_path, "w") as fh:
                    fh.write(block)
                cmd.load(frame_path, self.traj_object, state=state, format="xyz", finish=1, discrete=1, quiet=1, multiplex=0)
            self._apply_traj_representation()
            nstates = int(cmd.count_states(self.traj_object))

        try:
            cmd.mset(f"1 -{nstates}")
            cmd.set("all_states", 0)
            # Do not set object-specific "state"; that freezes the object on one state.
            cmd.frame(nstates)
        except Exception:
            pass
        cmd.refresh()
        self.trajectory_update.emit(self.traj_object, nstates)


    def try_load_trajectory(self, final=False):
        """
        Robust trajectory loader.

        Previous versions appended states incrementally. On some PyMOL builds this can
        produce an object with the correct state count but every state visually equal
        to the last frame. This version always rebuilds the object from the full
        multi-XYZ trajectory when the file changes, making opt/ts_sella/NEB states
        reliable.
        """
        candidates = []
        for path in self.trajectory_candidates():
            if os.path.exists(path) and os.path.getsize(path) > 0 and is_xyz_like(path):
                frames_here = read_multixyz_frames(path)
                if frames_here:
                    candidates.append((len(frames_here), path, frames_here))
        if not candidates:
            return

        candidates.sort(key=lambda item: item[0], reverse=True)
        nframes_candidate, traj, frames = candidates[0]

        # Do not replace a long trajectory with a final single-frame file.
        if self.loaded_frame_count > 1 and nframes_candidate < self.loaded_frame_count:
            self.log_line.emit(
                f"[Trajectory] Preserving existing {self.loaded_frame_count}-state trajectory; "
                f"ignoring shorter final file {os.path.basename(traj)} with {nframes_candidate} frame(s)."
            )
            if safe_obj_exists(self.traj_object):
                self._apply_traj_representation()
                try:
                    self.trajectory_update.emit(self.traj_object, int(cmd.count_states(self.traj_object)))
                except Exception:
                    pass
            return

        try:
            mtime, size = os.path.getmtime(traj), os.path.getsize(traj)
        except OSError:
            return

        if not final and mtime == self.last_mtime and size == self.last_size and nframes_candidate == self.loaded_frame_count:
            return

        self.last_mtime, self.last_size = mtime, size
        self.active_traj_path = traj

        energies = []
        for _, comment, _ in frames:
            e = extract_energy_from_xyz_comment(comment)
            if e is not None:
                energies.append(e)
        if energies:
            self.energies = energies
            self.energy_update.emit(self.energies)

        try:
            self._rebuild_multistate_object(frames)
        except Exception as exc:
            self.log_line.emit(f"[Trajectory load warning] {exc}")

    def _apply_traj_representation(self):
        """Apply a stable sticks+spheres representation to the trajectory object."""
        try:
            if not safe_obj_exists(self.traj_object):
                return

            cmd.hide("everything", self.traj_object)

            # PyMOL bonds are object-level, not state-specific. Rebonding may help sticks
            # but cannot represent different topology per frame.
            if self.dynamic_rebond:
                try:
                    cmd.rebond(self.traj_object)
                except Exception:
                    pass

            cmd.show("sticks", self.traj_object)
            cmd.show("spheres", self.traj_object)
            cmd.set("sphere_scale", 0.2, self.traj_object)
            cmd.set("sphere_scale", 0.2)
            cmd.set("stick_radius", 0.12, self.traj_object)
        except Exception as exc:
            self.log_line.emit(f"[Trajectory representation warning] {exc}")

