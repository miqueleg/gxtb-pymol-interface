# PyMOL g-xTB Runner

**PyMOL g-xTB Runner** is a Qt-based PyMOL plugin for launching and visualizing xTB/g-xTB calculations directly from the PyMOL interface.

It is designed for fast exploratory modeling of QM regions, reaction paths, transition-state guesses, frequencies, vibrations, NEB paths, and IRC-like downhill products/reactants.

> Public version: **1.0.1**

---

## Main features

- Run xTB calculations directly from PyMOL.
- Supported methods:
  - `gxtb`
  - `gfn2`
  - `gfn1`
  - `gfn0`
  - `gfnff`
  - custom/no method flag
- Supported native xTB calculation types:
  - single point
  - optimization
  - gradient
  - Hessian/frequency
  - MD
  - metadynamics
  - xTB path jobs
  - GSM file preparation
- Optional ASE workflows:
  - Sella TS optimization
  - ASE NEB
- Real-time trajectory visualization in PyMOL.
- Energy plot during and after calculations.
- Energy readout in Hartree and relative kcal/mol.
- PyMOL selection-based frozen atoms.
- Hessian frequency table.
- Vibration animation from normal modes.
- IRC-like `Run IRC ±` workflow from a selected imaginary mode.
- macOS and Windows-aware ASE/Sella virtual environment installer.

---

## Important scientific note

The **Run IRC ±** button implements a practical **IRC-like downhill workflow**, not a strict formal IRC integrator.

It does:

1. Take the current TS/frequency geometry.
2. Take the selected normal mode, usually the imaginary frequency.
3. Displace the structure in the `+` and `−` directions along that mode.
4. Optimize both displaced structures downhill.
5. Combine the two branches into:

```text
reactant-side minimum → TS region → product-side minimum
```

This is very useful for fast reaction exploration and validation, but it is not the same as a rigorous mass-weighted IRC integration as implemented in major quantum chemistry packages.

---

## What does the amplitude value mean?

In the vibration/IRC panel, **Amplitude** controls how far atoms are displaced along a selected normal mode for visualization and related mode-following workflows.

The plugin normalizes the selected normal-mode displacement vector so that the largest-moving atom moves approximately by the amplitude value in Å.

For example:

```text
Amplitude = 0.40
```

means the largest-moving atom in the vibration animation is displaced by roughly **0.40 Å** from the reference geometry at maximum phase.

### When to change amplitude

Use the default value, typically `0.40 Å`, for normal visualization.

Increase it when:

- the vibration looks too small to see,
- the imaginary mode is visually unclear,
- you want to identify which bond is forming/breaking more easily.

Decrease it when:

- the animation looks unrealistic,
- atoms overlap,
- bonds appear to fly apart,
- you are using the displacement as a starting point for IRC-like optimization and want a gentler perturbation.

Suggested values:

| Use case | Suggested amplitude |
|---|---:|
| Visualizing normal modes | `0.30–0.70 Å` |
| Gentle IRC-like displacement | `0.05–0.20 Å` |
| Very floppy protein/QM-region modes | `0.10–0.30 Å` |
| Making a mode obvious for teaching/figures | `0.50–1.00 Å` |

For reaction exploration, smaller values are usually safer.

---

## Requirements

### Required

- PyMOL with Qt interface
- xTB executable available somewhere on your system

### Optional but recommended

For `ts_sella` and `neb_ase`:

- Python 3.10, 3.11, or 3.12
- ASE
- Sella
- NumPy
- SciPy

The plugin can create a dedicated virtual environment for these packages.

---

## Installation

### 1. Install xTB / g-xTB

Install an xTB executable that supports the methods you want, including the new `--gxtb` flag if you want to use g-xTB.

Make sure you know the path to the executable, for example:

```bash
/opt/homebrew/bin/xtb
```

or on Windows:

```text
C:\path\to\xtb.exe
```

### 2. Install the plugin

Copy:

```text
pymol_gxtb_plugin.py
```

to your PyMOL startup folder.

#### macOS / Linux

```bash
mkdir -p ~/.pymol/startup
cp pymol_gxtb_plugin.py ~/.pymol/startup/
```

#### Windows

Copy the file to your PyMOL startup directory, commonly:

```text
C:\Users\<your_user>\.pymol\startup\
```

Then restart PyMOL.

You should see:

```text
Plugin → PyMOL g-xTB Runner
```

---

## First setup

Open the plugin and set:

```text
xTB path
```

Examples:

```text
/opt/homebrew/bin/xtb
```

or:

```text
C:\path\to\xtb.exe
```

The plugin remembers this path for future sessions.

---

## Basic optimization workflow

1. Load a structure into PyMOL.
2. Open **PyMOL g-xTB Runner**.
3. Select the input object.
4. Choose method:
   - `gxtb`
   - `gfn2`
   - `gfnff`
   - etc.
5. Set charge and multiplicity.
6. Set calculation type:

```text
opt
```

7. Click **Run**.

The plugin writes the input XYZ, launches xTB, loads the optimization trajectory, shows sticks/spheres, plots the energy progression, and preserves the final multi-state object.

---

## Frozen atoms

You can freeze atoms using a PyMOL selection.

Example:

```pymol
select FIX, chain A and not resn LIG
```

Then in the plugin:

1. Click **More options**.
2. Go to **Constraints**.
3. Select the PyMOL selection under:

```text
Freeze PyMOL selection as fixed atoms
```

The plugin converts the PyMOL selection to the correct xTB/ASE atom indices.

Frozen atoms are supported in:

- xTB optimizations,
- xTB Hessian input constraints,
- Sella TS optimization through ASE `FixAtoms`,
- ASE NEB through ASE `FixAtoms`,
- IRC-like branch optimizations.

---

## Hessian and frequency workflow

1. Optimize your structure first.
2. Use the optimized structure as input.
3. Select calculation type:

```text
hess
```

4. Run the calculation.

After the Hessian finishes, the plugin tries to parse normal modes from `g98.out`.

The vibration/frequency panel will show:

- mode number,
- frequency in cm⁻¹,
- source file.

To animate a mode:

1. Select a frequency row.
2. Adjust amplitude if desired.
3. Click:

```text
Show selected vibration
```

A new PyMOL multi-state vibration object is created.

---

## Hessian stability modes

Numerical Hessians can crash in some xTB builds, especially on macOS or with large systems.

In **More options → General**, use:

```text
Hessian mode
```

Recommended:

```text
auto_retry_balanced_safe
```

This tries a balanced calculation first and retries with safer single-thread settings if the xTB binary aborts or segfaults.

For maximum robustness:

```text
safe1
```

This uses one xTB/OpenMP thread and pins BLAS threads to one.

---

## Sella TS optimization

Sella TS optimization uses an external ASE/Sella driver script written by the plugin.

### Setup

Click:

```text
Install ASE/Sella deps
```

The plugin creates a virtual environment, by default:

```text
~/.pymol_gxtb_ase_sella_venv
```

and installs:

```text
numpy scipy ase sella
```

This avoids installing into PyMOL's own Python.

### Running Sella

1. Select a TS guess object.
2. Choose calculation type:

```text
ts_sella
```

3. In **More options → ASE / Sella TS**, set:
   - fmax
   - steps
   - internal/cartesian coordinates
   - saddle order

For constrained protein/QM regions, Cartesian coordinates often behave better. If you see Sella warnings such as:

```text
coords found! Expected ...
```

try turning off:

```text
Use Sella internal coordinates
```

---

## ASE NEB workflow

Use NEB when you have reactant and product structures and want a transition path between them.

### Requirements

Reactant and product must have:

- same atom count,
- same atom order,
- same elements in the same order.

### Steps

1. Load or create two PyMOL objects/selections:
   - `RC`
   - `PROD`

2. In the main plugin window, select:

```text
calc = neb_ase
```

3. Open:

```text
More options → Path / GSM
```

4. Set:

```text
Start/reactant = RC
Final/product = PROD
```

5. Choose NEB settings:
   - images: usually `7–15`
   - fmax: usually `0.05`
   - steps: `200–500`
   - spring k: usually `0.1`
   - climbing image: enabled
   - interpolation: `idpp`

6. Click **Run**.

The plugin writes:

```text
ase_neb_traj.xyz
ase_neb_full_trajectory.xyz
ase_neb_ts_guess.xyz
ase_neb_final_energies.tsv
```

The PyMOL movie uses only the final optimized NEB band. The full optimizer trace is kept separately for debugging.

The highest-energy interior image is loaded as a separate TS guess object.

Recommended next step:

```text
NEB TS guess → ts_sella → hess → IRC ±
```

---

## IRC-like Run IRC ± workflow

This workflow is accessed through the vibration/frequency panel.

### Steps

1. Obtain a TS or TS guess.
2. Run:

```text
hess
```

3. Select the imaginary frequency in the frequency table.
4. Set IRC displacement amplitude, usually:

```text
0.05–0.20 Å
```

5. Click:

```text
Run IRC ±
```

The plugin will displace the TS along `+` and `−` directions of the selected mode, optimize both downhill branches, combine the two paths into one multi-state object, and plot the energy profile.

---

## Recommended reaction-discovery workflow

```text
1. Optimize RC and PROD
2. Run ASE NEB from RC to PROD
3. Take highest-energy NEB image
4. Run ts_sella
5. Run hess
6. Confirm one imaginary frequency
7. Run IRC ± from the imaginary mode
8. Confirm it connects to RC and PROD
```

---

## Troubleshooting

### PyMOL object has many states but all look identical

This public version uses multi-model PDB loading internally to avoid PyMOL state-freezing issues.

If the object still appears static:

- make sure you are changing global PyMOL frames/states,
- do not manually set object-specific `state`,
- reload the plugin and restart PyMOL.

### Sella gives only one frame

This can happen if Sella immediately converges or fails before accepting steps. The plugin writes at least initial and final frames and prints step energies.

Check:

```text
sella_ts.log
sella_ts_energies.tsv
```

### No imaginary frequency after Sella

Then the optimized structure is not a first-order saddle point at that level of theory.

Try:

- starting from the NEB highest-energy image,
- using Cartesian Sella,
- lowering fmax to `0.02`,
- increasing steps,
- freezing fewer atoms near the reaction coordinate,
- re-running Hessian with identical method/settings.

### Hessian crashes

Try:

```text
Hessian mode = safe1
```

### ASE/Sella installation fails on macOS

Homebrew Python may be externally managed under PEP 668. The plugin creates a virtual environment to avoid this.

If automatic setup fails:

```bash
brew install python@3.12
```

Then set the Python path in:

```text
More options → ASE / Sella TS
```

### Windows ASE/Sella dependency installation

Version 1.0.1 installs the Windows scientific stack in stages:

1. create the virtual environment,
2. run `ensurepip`,
3. install `numpy`, `scipy`, and `ase` from wheels only,
4. install `sella` separately with fallback strategies,
5. run an import check.

This avoids trying to compile SciPy from source. If the installer still fails, install Python 3.12 with:

```powershell
winget install Python.Python.3.12
```

Then restart PyMOL and click **Install ASE/Sella deps** again.

If Python is installed but not detected, set the ASE/Sella Python executable manually in:

```text
More options → ASE / Sella TS
```

Use either:

```text
py -3.12
```

or the full path to `python.exe`.


### ASE/Sella installation fails on Windows

Install Python 3.12 from python.org or with winget:

```powershell
winget install Python.Python.3.12
```

Then either let the plugin auto-detect it, or set:

```text
py -3.12
```

or the full path to `python.exe`.

---

## Files generated in job folders

Common files:

```text
input.xyz
xcontrol
xtbopt.log
xtbopt.xyz
xtb.trj
g98.out
vibspectrum
sella_ts_traj.xyz
sella_ts_final.xyz
sella_ts_energies.tsv
ase_neb_traj.xyz
ase_neb_full_trajectory.xyz
ase_neb_ts_guess.xyz
ase_neb_final_energies.tsv
irc_combined.xyz
```

---

## Limitations

- The IRC ± workflow is approximate, not a strict mass-weighted IRC integrator.
- PyMOL bonds are object-level and not state-specific, so bond formation/breaking may not update perfectly per frame.
- xTB/g-xTB implicit solvent support depends on the method and available parameterization.
- Sella and ASE are optional dependencies and require a compatible Python environment.
- NEB requires matching atom order between reactant and product.

---

## Citation / acknowledgement

If this plugin is useful, please cite the underlying tools used in your workflow:

- xTB / GFN methods
- g-xTB model if used
- ASE if using Sella/NEB workflows
- Sella if using TS optimization

---

## License

MIT License. See `LICENSE`.

---

## Development notes

This is a first public release. Contributions and bug reports are welcome, especially for:

- improved strict IRC integration,
- more robust Hessian parsing,
- better NEB/Sella diagnostics,
- Windows installer testing,
- support for additional xTB/g-xTB output variants.
