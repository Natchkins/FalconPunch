"""Build "Smash Night.exe" (the in-process host, see launcher.py) with
PyInstaller.  Run via build_exe.bat, or directly:

    .venv\\Scripts\\python.exe build_exe.py

The whole stdlib is bundled on purpose: a Store-installed Python keeps
its compiled modules under C:\\Program Files\\WindowsApps, which no other
process may load, and a half-bundled package (ctypes without
ctypes.util) shadows the base install's copy and broke PyOpenGL.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(tempfile.gettempdir(), "smash_night_build")
SKIP = {"antigravity", "this", "idlelib", "turtledemo", "__phello__",
        "__hello__", "_tkinter", "tkinter.tix"}


def main():
    os.chdir(HERE)
    os.makedirs(WORK, exist_ok=True)
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                               "pyinstaller"])
        import PyInstaller.__main__ as pyi
    hidden = [f"--hidden-import={m}" for m in sorted(sys.stdlib_module_names)
              if m not in SKIP and not m.startswith("_test")]
    pyi.run([
        "--clean", "--noconfirm", "--onefile", "--noconsole",
        "--name", "Smash Night",
        "--icon", os.path.join(HERE, "smash_night.ico"),
        "--distpath", HERE,
        "--workpath", WORK,
        "--specpath", WORK,
        *hidden,
        os.path.join(HERE, "launcher.py"),
    ])
    out = os.path.join(HERE, "Smash Night.exe")
    print(f"Built {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
