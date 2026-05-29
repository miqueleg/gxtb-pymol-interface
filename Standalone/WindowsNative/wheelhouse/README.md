# Optional Sella Wheelhouse

Place Windows-compatible Sella wheels and any required dependency wheels here only if the vendored Sella source install cannot be used.

The normal build installs from:

```text
Standalone/WindowsNative/third_party/sella
```

with:

```bat
python -m pip install --no-build-isolation --no-deps Standalone\WindowsNative\third_party\sella
```

This wheelhouse is retained as a fallback mechanism for Windows-specific wheels.
