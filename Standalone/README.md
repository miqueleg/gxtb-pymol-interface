# PyMOL g-xTB Runner — Standalone Docker Desktop Release

This is the standalone desktop version of **PyMOL g-xTB Runner**.

It runs PyMOL, g-xTB, ASE, Sella, NumPy/SciPy, and the plugin inside Docker. Users do **not** need to install PyMOL, Python packages, ASE, Sella, or xTB manually.

The graphical PyMOL session opens in a web browser through noVNC:

```text
http://localhost:6080/vnc.html
```

## Download the correct package

| Operating system | File |
|---|---|
| macOS | `PyMOL-gxTB-Runner-macOS.tar.gz` |
| Windows | `PyMOL-gxTB-Runner-Windows.zip` |
| Linux, optional | `PyMOL-gxTB-Runner-Linux.tar.gz` |

For GitHub releases, upload the macOS and Windows packages as separate release assets.

---

## What is included

The Docker image built by the launcher includes:

- open-source PyMOL
- PyMOL g-xTB Runner plugin
- g-xTB 2.0.1-capable binary at `/usr/local/bin/gxtb-xtb`
- xTB fallback from conda-forge
- ASE
- Sella
- NumPy
- SciPy
- matplotlib
- noVNC browser desktop

The plugin’s old **Install ASE/Sella deps** button has been removed from this container version because ASE and Sella are installed during the Docker image build.

---

# macOS installation

## 1. Install Docker Desktop

Download Docker Desktop from:

```text
https://www.docker.com/products/docker-desktop/
```

Install it like a normal Mac application.

Then open Docker Desktop and wait until it says Docker is running.

## 2. Download and extract the macOS package

Download:

```text
PyMOL-gxTB-Runner-macOS.tar.gz
```

Double-click it to extract.

## 3. Start the program

Open the extracted folder and double-click:

```text
Start PyMOL g-xTB Runner.app
```

If macOS blocks it:

1. Right-click `Start PyMOL g-xTB Runner.app`
2. Will be blocked. Go to settings -> Privacy and Security -> Security -> allow Execution
3. Right-Click `Start PyMOL g-xTB Runner.app` again after permission is given.

## 4. Wait for the first build

The first launch builds the Docker image locally. This can take several minutes.

Later launches are faster.

## 5. Use PyMOL in the browser

The launcher opens:

```text
http://localhost:6080/vnc.html
```

The PyMOL g-xTB Runner plugin should open automatically after pressing `Connect`

If it does not, check the PyMOL menu or type this in the PyMOL command line:

```text
gxtb_runner
```

## macOS work folder

Your working folder is:

```text
~/pymol-gxtb-work
```

Inside the container/PyMOL it appears as:

```text
/work
```

Put input structures there if you want them visible inside the container.

---

# Windows installation

## 1. Install Docker Desktop

Download Docker Desktop from:

```text
https://www.docker.com/products/docker-desktop/
```

During installation, allow Docker to use WSL2 if asked.

After installation, open Docker Desktop and wait until it says Docker is running.

## 2. Download and extract the Windows package

Download:

```text
PyMOL-gxTB-Runner-Windows.zip
```

Right-click and choose **Extract All...**

## 3. Start the program

Open the extracted folder and double-click:

```text
Start-Windows.bat
```
If it does not execute or gets blocked, right-click and -> Run as Administrator

A terminal window opens. Keep it open while using the program.

## 4. Wait for the first build

The first launch builds the Docker image locally. This can take several minutes.

Later launches are faster.

## 5. Use PyMOL in the browser

The launcher opens:

```text
http://localhost:6080/vnc.html
```

The PyMOL g-xTB Runner plugin should open automatically.

If it does not, check the PyMOL menu or type this in the PyMOL command line:

```text
gxtb_runner
```

## Windows work folder

Your working folder is:

```text
C:\Users\<your-user>\pymol-gxtb-work
```

Inside the container/PyMOL it appears as:

```text
/work
```

Put input structures there if you want them visible inside the container.

---

# Important notes

## First launch can be slow

The first launch downloads and builds the scientific environment. This can take several minutes depending on your internet connection and computer.

## Docker image tag

This release uses:

```text
pymol-gxtb-runner:v10
```

This avoids accidentally reusing older broken images tagged as `pymol-gxtb-runner:local`.

## Reset / rebuild

If you want to force a clean rebuild:

### macOS/Linux

```bash
docker rmi pymol-gxtb-runner:v10
```

Then start the app again.

### Windows PowerShell

```powershell
docker rmi pymol-gxtb-runner:v10
```

Then double-click `Start-Windows.bat` again.

## If Docker is not running

Open Docker Desktop manually and wait until it is fully running.

Then launch PyMOL g-xTB Runner again.

## If the browser does not open

Open this manually:

```text
http://localhost:6080/vnc.html
```

## If the plugin window does not open

In the PyMOL command line, type:

```text
gxtb_runner
```

The plugin is explicitly loaded at PyMOL startup with:

```text
pymol -r /opt/pymol-gxtb-runner/load_plugin.py
```

---

# Developer notes

The Docker image is built as:

```text
linux/amd64
```

because the bundled g-xTB binary is the Linux x86_64 binary.

The launcher passes:

```text
--platform linux/amd64
```

to Docker build and run.

The bundled g-xTB binary path inside the container is:

```text
/usr/local/bin/gxtb-xtb
```

The plugin sets the xTB path to this binary by default via:

```text
PYMOL_GXTB_XTB_PATH=/usr/local/bin/gxtb-xtb
```

Sella is installed during the Docker build using:

```text
pip install --no-build-isolation sella
```

after installing its build/runtime dependencies through conda and `build-essential` through apt.

---

# Files in this release

```text
PyMOL-gxTB-Runner-macOS.tar.gz
PyMOL-gxTB-Runner-Windows.zip
README.md
SHA256SUMS.txt
```

Optional:

```text
PyMOL-gxTB-Runner-Linux.tar.gz
```
