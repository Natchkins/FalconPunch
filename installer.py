"""SmashNight-Setup.exe — one-file installer built by build_release.py.

Carries SmashNight-win64.zip inside; extracts it to
%LOCALAPPDATA%\\Programs\\SmashNight (keeping any existing state files —
profiles, caches, token — so it doubles as a manual updater), creates a
Desktop and a Start-menu shortcut, and launches the app.
"""
import os
import subprocess
import sys
import threading
import traceback
import zipfile

ZIP_NAME = "SmashNight-win64.zip"
EXE_NAME = "Smash Night.exe"
CREATE_NO_WINDOW = 0x08000000


def bundled_zip():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, ZIP_NAME)


def install_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "Programs", "SmashNight")


def make_shortcut(lnk, target, workdir, icon):
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
                    "$s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
                    "$s.IconLocation = '%s'; $s.Description = 'Smash Night'; $s.Save()"
                    % (lnk.replace("'", "''"), target.replace("'", "''"),
                       workdir.replace("'", "''"), icon.replace("'", "''"))],
                   creationflags=CREATE_NO_WINDOW, timeout=60)


def run_install(status, done):
    try:
        zpath = bundled_zip()
        dest = install_dir()
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            members = zf.infolist()
            total = len(members) or 1
            for i, m in enumerate(members, 1):
                rel = m.filename.split("/", 1)[1] if "/" in m.filename else m.filename
                if not rel:
                    continue
                target = os.path.join(dest, *rel.split("/"))
                if m.is_dir():
                    os.makedirs(target, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(m) as src, open(target, "wb") as out:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                if i % 50 == 0 or i == total:
                    status(f"Installing… {i * 100 // total}%", i / total)
        exe = os.path.join(dest, EXE_NAME)
        icon = os.path.join(dest, "smash_night.ico")
        status("Creating shortcuts…", 1.0)
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft",
                                "Windows", "Start Menu", "Programs")
        for folder in (desktop, programs):
            if os.path.isdir(folder):
                make_shortcut(os.path.join(folder, "Smash Night.lnk"), exe, dest, icon)
        status("Done — starting Smash Night.", 1.0)
        subprocess.Popen([exe], cwd=dest, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS
                         | subprocess.CREATE_NEW_PROCESS_GROUP)
        done(None)
    except Exception:
        done(traceback.format_exc())


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    root.title("Smash Night Setup")
    root.resizable(False, False)
    try:
        root.iconbitmap(default=os.path.join(
            getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
            "smash_night.ico"))
    except Exception:
        pass
    frame = tk.Frame(root, padx=24, pady=18)
    frame.pack()
    tk.Label(frame, text="Smash Night", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    tk.Label(frame, text=f"Installing to {install_dir()}",
             font=("Segoe UI", 9), fg="#555").pack(anchor="w", pady=(0, 10))
    var = tk.StringVar(value="Preparing…")
    tk.Label(frame, textvariable=var, font=("Segoe UI", 10)).pack(anchor="w")
    bar = ttk.Progressbar(frame, length=360, mode="determinate", maximum=1.0)
    bar.pack(pady=(6, 0))
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def status(text, frac):
        root.after(0, lambda: (var.set(text), bar.configure(value=frac)))

    def done(err):
        def _fin():
            if err:
                messagebox.showerror("Smash Night Setup",
                                     "Installation failed:\n\n" + err[-1200:])
            root.after(800, root.destroy)
        root.after(0, _fin)

    threading.Thread(target=run_install, args=(status, done), daemon=True).start()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
