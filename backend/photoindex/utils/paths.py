"""Windows path normalization for source roots.

Accepted forms:
  C:\\Photos                -> local
  Z:\\family\\photos         -> mapped (network drive letter cannot be detected reliably,
                               so any non-C/system drive letter is still 'local' unless UNC;
                               we classify by shape: drive letter = local/mapped lookalike)
  \\\\nas-server\\homes\\... -> unc
  //nas-server/homes/...     -> unc (forward-slash form, converted)

Normalization rules (stored in sources.root_path — used for reconnect-on-re-add):
  - backslashes canonical
  - drive letter upper-cased
  - trailing slash removed
  - UNC prefix kept as \\\\server\\share\\...
"""
from __future__ import annotations

import os
import re


def normalize_root(raw: str) -> str:
    p = raw.strip().strip('"').replace("/", "\\")
    # collapse duplicate backslashes except the UNC leading pair
    if p.startswith("\\\\"):
        body = re.sub(r"\\+", r"\\", p[2:])
        p = "\\\\" + body
    else:
        p = re.sub(r"\\+", r"\\", p)
    p = p.rstrip("\\")
    if re.match(r"^[a-zA-Z]:", p):
        p = p[0].upper() + p[1:]
    return p


def classify_path(normalized: str) -> str:
    """Return path_type: unc | mapped | local."""
    if normalized.startswith("\\\\"):
        return "unc"
    if re.match(r"^[A-Z]:", normalized):
        drive = normalized[0]
        # Heuristic: treat non-system letters commonly used for shares as mapped
        # only if os reports them as remote; fall back to 'local'.
        try:
            import ctypes

            DRIVE_REMOTE = 4
            dtype = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}:\\")
            if dtype == DRIVE_REMOTE:
                return "mapped"
        except Exception:
            pass
        return "local"
    return "local"


def to_relative(full_path: str, root: str) -> str:
    """Relative path with forward slashes (stable key across scans)."""
    rel = os.path.relpath(full_path, root)
    return rel.replace("\\", "/")
