"""Build the friend-facing release of Smash Night.

    .venv\\Scripts\\python.exe build_release.py

Produces, under release/:

* ``SmashNight-win64.zip``  — a self-contained folder: Smash Night.exe,
  _internal/ (Python + every dependency), smash_night.py and the
  resource folders it needs (sounds, photos, payloads, rcm_tools,
  smash_mods, switch_setup, assets, …).  Unzip anywhere, run the exe.
  State files (profiles, caches, token) are written next to the exe,
  exactly like the git checkout.
* ``SmashNight-Setup.exe`` — a one-file installer wrapping that zip:
  extracts to %LOCALAPPDATA%\\Programs\\SmashNight, creates Desktop +
  Start-menu shortcuts, launches.  Re-running it over an existing install
  keeps the user's state.

The in-app updater (smash_night.py, "⬆ Update") downloads the zip asset of
the newest GitHub release and copies it over the install, so both the zip
and the installer must stay in every release (see release.py).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "release")
WORK = os.path.join(tempfile.gettempdir(), "smash_night_release")
ZIP_NAME = "SmashNight-win64.zip"
SETUP_NAME = "SmashNight-Setup.exe"
APP_NAME = "Smash Night"

# Shipped next to the exe (the app resolves all of these from SCRIPT_DIR,
# the folder smash_night.py lives in).  Missing optional ones are skipped.
RESOURCES = [
    "smash_night.py", "fat32_format.py", "smash_night.ico",
    "vanilla_arc_paths.txt.gz", "README.md", "LICENSE",
    "sounds", "photos", "assets", "payloads", "rcm_tools", "smash_mods",
    "switch_setup", "ultimate_tex_cli", "tools",
    os.path.join("ssbh_render", "target", "release", "ssbh_render.exe"),
]
# Never shipped even if inside a shipped folder.
PRUNE = {"__pycache__", "unused", ".git", "downloads"}
# Paths (relative to the checkout) left out of the release: TegraRcmGUI
# extras the app never calls — third-party payloads (SX Loader, ReiNX,
# biskeydump), memloader / shofel2 helpers, the GUI's own log and presets.
# Same list .gitignore keeps out of the repository.  TegraRcmSmash.exe,
# its DLLs and the APX driver installer stay.
_RCM = os.path.join("rcm_tools", "TegraRcmGUI_v2.6_portable")
EXCLUDE = {os.path.normcase(os.path.join(_RCM, n)) for n in (
    "favorites", "tools", "favorites.conf", "presets.conf", "out.log")}


def _ignore(d, names):
    rel = os.path.relpath(d, HERE)
    return [n for n in names if n in PRUNE
            or os.path.normcase(os.path.normpath(os.path.join(rel, n))) in EXCLUDE]

# Third-party packages the app imports; PyInstaller's hooks collect numpy /
# scipy / PIL properly only when the analysis *sees* an import, and the
# rest need their data files (pyrender shaders, trimesh resources).
COLLECT_ALL = ["pyrender", "pyglet", "OpenGL", "trimesh", "ssbh_data_py",
               "rarfile", "py7zr", "pybcj", "pyppmd", "inflate64",
               "multivolumefile", "brotli", "freetype", "networkx",
               "certifi", "charset_normalizer", "idna", "urllib3",
               "requests", "psutil", "texttable", "six"]
SEEN_IMPORTS = ["numpy", "scipy", "PIL", "PIL.ImageTk", "pyrender", "pyglet",
                "OpenGL", "OpenGL.GL", "trimesh", "ssbh_data_py", "requests",
                "rarfile", "py7zr", "psutil", "networkx"]
STDLIB_SKIP = {"antigravity", "this", "idlelib", "turtledemo", "__phello__",
               "__hello__", "_tkinter", "tkinter.tix",
               # Unix-only; PyInstaller logs an ERROR for each on Windows
               "_curses", "_curses_panel", "_dbm", "_gdbm", "_posixshmem",
               "_posixsubprocess", "_scproxy", "curses", "dbm.gnu",
               "dbm.ndbm", "fcntl", "grp", "nis", "ossaudiodev", "posix",
               "pwd", "readline", "resource", "spwd", "syslog", "termios",
               "tty", "pty", "crypt", "_crypt"}


def app_version():
    src = open(os.path.join(HERE, "smash_night.py"), encoding="utf-8").read()
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        sys.exit("APP_VERSION not found in smash_night.py")
    return m.group(1)


def pyinstaller():
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                               "pyinstaller"])
        import PyInstaller.__main__ as pyi
    return pyi


def write_entry():
    """release_entry.py: launcher.main plus imports of every third-party
    package, so PyInstaller's analysis applies the right hooks."""
    path = os.path.join(WORK, "release_entry.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("import sys, os\n")
        f.write(f"sys.path.insert(0, {HERE!r})\n")
        f.write("from launcher import main\n\n\n")
        f.write("def _deps():  # never called; seen by PyInstaller\n")
        for m in SEEN_IMPORTS:
            f.write(f"    import {m}  # noqa\n")
        f.write("\n\nif __name__ == '__main__':\n    sys.exit(main())\n")
    return path


def build_app(version):
    pyi = pyinstaller()
    dist = os.path.join(WORK, "dist")
    shutil.rmtree(dist, ignore_errors=True)
    hidden = [f"--hidden-import={m}" for m in sorted(sys.stdlib_module_names)
              if m not in STDLIB_SKIP and not m.startswith("_test")]
    collect = [f"--collect-all={m}" for m in COLLECT_ALL]
    entry = write_entry()
    pyi.run([
        "--clean", "--noconfirm", "--onedir", "--noconsole",
        "--name", APP_NAME,
        "--icon", os.path.join(HERE, "smash_night.ico"),
        "--distpath", dist,
        "--workpath", os.path.join(WORK, "build"),
        "--specpath", WORK,
        "--paths", HERE,
        *hidden, *collect,
        entry,
    ])
    app_dir = os.path.join(dist, APP_NAME)
    # Resources next to the exe (SCRIPT_DIR for the app).
    for rel in RESOURCES:
        src = os.path.join(HERE, rel)
        dst = os.path.join(app_dir, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore)
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    with open(os.path.join(app_dir, "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(version + "\n")
    return app_dir


def make_zip(app_dir):
    os.makedirs(OUT, exist_ok=True)
    zpath = os.path.join(OUT, ZIP_NAME)
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(app_dir):
            dirs[:] = [d for d in dirs if d not in PRUNE]
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.join("SmashNight", os.path.relpath(full, app_dir))
                zf.write(full, arc)
    return zpath


def build_installer(zpath):
    pyi = pyinstaller()
    dist = os.path.join(WORK, "dist_setup")
    shutil.rmtree(dist, ignore_errors=True)
    pyi.run([
        "--clean", "--noconfirm", "--onefile", "--noconsole",
        "--name", SETUP_NAME[:-4],
        "--icon", os.path.join(HERE, "smash_night.ico"),
        "--add-data", f"{zpath}{os.pathsep}.",
        "--distpath", dist,
        "--workpath", os.path.join(WORK, "build_setup"),
        "--specpath", WORK,
        os.path.join(HERE, "installer.py"),
    ])
    out = os.path.join(OUT, SETUP_NAME)
    shutil.copy2(os.path.join(dist, SETUP_NAME), out)
    return out


def main():
    os.chdir(HERE)
    os.makedirs(WORK, exist_ok=True)
    version = app_version()
    print(f"== Building Smash Night v{version}")
    app_dir = build_app(version)
    zpath = make_zip(app_dir)
    print(f"== {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")
    setup = build_installer(zpath)
    print(f"== {setup} ({os.path.getsize(setup) / 1e6:.1f} MB)")
    print("== done")


if __name__ == "__main__":
    main()
