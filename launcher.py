"""Smash Night.exe — PyInstaller-built host for smash_night.py.

Two builds share this file:

* **dev host** (build_exe.py, onefile, ~18 MB): sits in the git checkout
  next to ``.venv``.  Runs setup.bat when the venv is missing or on an
  unsupported Python, then runs smash_night.py in its own process with the
  venv's site-packages on sys.path.
* **release** (build_release.py, onedir, zipped / wrapped in
  SmashNight-Setup.exe): ``_internal/`` next to the exe holds Python and
  every dependency, no venv at all.  Detected by that folder.

Why an in-process host and not just a launcher: the taskbar button's icon
comes from the *process executable*.  A venv's pythonw.exe is a stub that
starts the real (Store / python.org) pythonw as a child process, so a
window it opens is owned by pythonw3.12.exe and gets the Python snake on
the taskbar no matter what icon the window carries.  Hosting the app in
this exe makes the window ours, and our icon is the Smash emblem.

The dev host bundles python312.dll and the *whole* stdlib (see
build_exe.py): a Store-installed Python keeps its compiled modules under
WindowsApps, which no other process may load, and a half-bundled package
(ctypes without ctypes.util) shadows the base copy.  Pure-.py stdlib
modules are read from the base install; the app's own packages come from
the venv.

Interpreter-style arguments (-m pip …, -c …) are delegated to the venv's
python.exe (dev) so the app can call sys.executable for pip and helper
processes; a leading smash_night.py argument (the app re-exec'ing itself)
is ignored.
"""
import ctypes
import os
import runpy
import subprocess
import sys
import traceback

APP = "smash_night.py"
CREATE_NO_WINDOW = 0x08000000


def _pyinstaller_deps():
    """Never called.  PyInstaller scans these imports and bundles the
    stdlib extension modules (and Tcl/Tk) into the exe."""
    import _asyncio, _bz2, _ctypes, _decimal, _elementtree, _hashlib  # noqa
    import _lzma, _multiprocessing, _overlapped, _queue, _socket  # noqa
    import _sqlite3, _ssl, _tkinter, _uuid, _zoneinfo, pyexpat  # noqa
    import select, unicodedata, winsound  # noqa
    import tkinter, tkinter.ttk, tkinter.scrolledtext, tkinter.messagebox  # noqa
    import tkinter.simpledialog, tkinter.filedialog  # noqa
    import ssl, socket, sqlite3, hashlib, json, zipfile, tempfile  # noqa
    import threading, urllib.request, http.client, email, xml.etree.ElementTree  # noqa
    import decimal, zoneinfo, uuid, bz2, lzma, queue, multiprocessing  # noqa


def _msg(text, title="Smash Night", flags=0x10):
    ctypes.windll.user32.MessageBoxW(0, text, title, flags)


def _ensure_venv(here):
    py = os.path.join(here, ".venv", "Scripts", "python.exe")
    pyw = os.path.join(here, ".venv", "Scripts", "pythonw.exe")
    need_setup = not os.path.isfile(pyw)
    if not need_setup:
        try:
            r = subprocess.run(
                [py, "-c", "import sys; sys.exit(0 if (3,10) <= "
                           "sys.version_info[:2] <= (3,12) else 1)"],
                creationflags=CREATE_NO_WINDOW, timeout=30)
            need_setup = r.returncode != 0
        except Exception:
            need_setup = True
    if need_setup:
        if not os.path.isfile(os.path.join(here, "setup.bat")):
            _msg("No .venv and no setup.bat — cannot set up the environment.")
            return None
        r = subprocess.run(["cmd.exe", "/c", "setup.bat"], cwd=here)
        if r.returncode != 0 or not os.path.isfile(pyw):
            _msg("setup.bat failed — see its output.")
            return None
    return py


def _base_prefix(py):
    r = subprocess.run([py, "-c", "import sys; print(sys.base_prefix)"],
                       capture_output=True, text=True, timeout=30,
                       creationflags=CREATE_NO_WINDOW)
    return r.stdout.strip()


def is_release_install(here):
    """True for the zipped / installed release: Python and every
    dependency live in _internal/ next to the exe, there is no venv."""
    return (getattr(sys, "frozen", False)
            and os.path.isdir(os.path.join(here, "_internal"))
            and not os.path.isdir(os.path.join(here, ".venv")))


def main():
    here = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    os.chdir(here)
    app_path = os.path.join(here, APP)
    if not os.path.isfile(app_path):
        _msg(f"{APP} not found next to this launcher:\n{here}")
        return 1

    args = sys.argv[1:]
    app_call = bool(args) and os.path.basename(args[0]).lower() == APP
    if app_call:
        args = args[1:]                      # the app re-exec'ing itself
    # "-m pip …" / "-c …" are interpreter calls; "smash_night.py --view-model
    # <dir>" is the app starting a second copy of itself (the 3D viewer) and
    # its dashed arguments belong to the app.
    interp_call = bool(args) and args[0].startswith("-") and not app_call

    release = is_release_install(here)
    if release:
        if interp_call:
            # No interpreter to delegate to; everything is bundled.
            return 0
        sys.path.insert(0, here)
    else:
        py = _ensure_venv(here)
        if not py:
            return 1
        if interp_call:
            # Interpreter-style call (pip, -c, …): hand it to the real python.
            return subprocess.call([py] + args, cwd=here)
        base = _base_prefix(py)
        venv_site = os.path.join(here, ".venv", "Lib", "site-packages")
        # Search order: the app folder, then PyInstaller's bundle (the
        # stdlib extension modules + Tcl/Tk travel in there), then the
        # venv's packages, then the base install's pure-Python stdlib.
        # The base install's DLLs folder is deliberately *not* on the
        # path: a Store Python's compiled modules can't be loaded from
        # WindowsApps by this process.
        sys.path = [here] + sys.path + [venv_site, os.path.join(base, "Lib")]
        sys.prefix = os.path.join(here, ".venv")
        sys.exec_prefix = sys.prefix
        sys.base_prefix = sys.base_exec_prefix = base

    try:
        sys.argv = [app_path] + args
        runpy.run_path(app_path, run_name="__main__")
        return 0
    except SystemExit as e:
        return int(e.code or 0) if isinstance(e.code, int) or e.code is None else 1
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(os.path.join(here, "launcher_error.log"), "w",
                      encoding="utf-8") as f:
                f.write(tb)
        except OSError:
            pass
        _msg("Smash Night failed to start:\n\n" + tb[-1500:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
