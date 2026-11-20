"""SmashNight-Setup.exe — one-file installer built by build_release.py.

Carries SmashNight-win64.zip inside.  Three steps in one small window:

1. options — shows the install folder and asks whether to create a
   Desktop and a Start-menu shortcut (both ticked);
2. progress — extracts the zip to %LOCALAPPDATA%\\Programs\\SmashNight,
   keeping any existing state files (profiles, caches, token), so it
   doubles as a manual updater;
3. finish — says where the app went and which shortcuts were made, with
   "Open folder" and a "Start Smash Night now" tick box.

The Desktop / Start-menu folders come from the shell (SHGetFolderPath),
not from ~\\Desktop: with OneDrive backup on, the real Desktop is
...\\OneDrive\\Desktop and a shortcut written to ~\\Desktop is invisible.
"""
import ctypes
import os
import subprocess
import sys
import threading
import traceback
import zipfile

ZIP_NAME = "SmashNight-win64.zip"
EXE_NAME = "Smash Night.exe"
CREATE_NO_WINDOW = 0x08000000
CSIDL_PROGRAMS = 0x0002
CSIDL_DESKTOPDIRECTORY = 0x0010


def bundled_zip():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, ZIP_NAME)


def install_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "Programs", "SmashNight")


def shell_folder(csidl, fallback):
    """The user's real shell folder (follows OneDrive / relocated
    Desktops); *fallback* when the shell can't say."""
    try:
        buf = ctypes.create_unicode_buffer(520)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 \
                and buf.value:
            return buf.value
    except Exception:
        pass
    return fallback


def desktop_dir():
    return shell_folder(CSIDL_DESKTOPDIRECTORY,
                        os.path.join(os.path.expanduser("~"), "Desktop"))


def programs_dir():
    return shell_folder(CSIDL_PROGRAMS, os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows",
        "Start Menu", "Programs"))


def make_shortcut(lnk, target, workdir, icon):
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
                    "$s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
                    "$s.IconLocation = '%s'; $s.Description = 'Smash Night'; $s.Save()"
                    % (lnk.replace("'", "''"), target.replace("'", "''"),
                       workdir.replace("'", "''"), icon.replace("'", "''"))],
                   creationflags=CREATE_NO_WINDOW, timeout=60)
    return os.path.isfile(lnk)


def run_install(status, done, want_desktop, want_startmenu):
    """Extract and create the chosen shortcuts.  done(error, made) where
    *made* lists the shortcut places that now exist ("Desktop", …)."""
    made = []
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
        for want, label, folder in ((want_desktop, "Desktop", desktop_dir()),
                                    (want_startmenu, "Start menu", programs_dir())):
            if not want:
                continue
            try:
                os.makedirs(folder, exist_ok=True)
                if make_shortcut(os.path.join(folder, "Smash Night.lnk"),
                                 exe, dest, icon):
                    made.append(label)
            except Exception:
                pass                      # a missing shortcut is not fatal
        done(None, made)
    except Exception:
        done(traceback.format_exc(), made)


def launch_app():
    dest = install_dir()
    subprocess.Popen([os.path.join(dest, EXE_NAME)], cwd=dest, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)


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
    FONT = "Segoe UI"
    frame = tk.Frame(root, padx=24, pady=18)
    frame.pack()
    head = tk.Frame(frame)
    head.pack(anchor="w")
    try:
        emblem = tk.PhotoImage(file=os.path.join(
            getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
            "icons8-super-smash-bros-48.png"))
        lbl = tk.Label(head, image=emblem)
        lbl.image = emblem                # keep a reference
        lbl.pack(side="left", padx=(0, 10))
    except Exception:
        pass
    tk.Label(head, text="Smash Night", font=(FONT, 16, "bold")).pack(side="left")
    tk.Label(frame, text="Installs to:", font=(FONT, 9), fg="#555").pack(
        anchor="w", pady=(4, 0))
    tk.Label(frame, text=install_dir(), font=(FONT, 9)).pack(anchor="w")
    # Fixed-width spacer so the window is the same size on every step.
    tk.Frame(frame, width=440, height=1).pack(pady=(10, 0))
    body = tk.Frame(frame)
    body.pack(fill="x")
    buttons = tk.Frame(frame)
    buttons.pack(fill="x", pady=(16, 0))

    def clear():
        for area in (body, buttons):
            for w in area.winfo_children():
                w.destroy()

    want_desktop = tk.BooleanVar(value=True)
    want_startmenu = tk.BooleanVar(value=True)
    start_now = tk.BooleanVar(value=True)
    busy = {"on": False}

    def on_close():
        if not busy["on"]:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    def show_options():
        clear()
        tk.Checkbutton(body, text="Put a shortcut on my Desktop",
                       variable=want_desktop, font=(FONT, 10)).pack(anchor="w")
        tk.Checkbutton(body, text="Add Smash Night to the Start menu",
                       variable=want_startmenu, font=(FONT, 10)).pack(anchor="w")
        if os.path.isfile(os.path.join(install_dir(), EXE_NAME)):
            tk.Label(body, text="Already installed — this updates it and keeps "
                                "your profiles and settings.",
                     font=(FONT, 9), fg="#555").pack(anchor="w", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
        b = ttk.Button(buttons, text="Install", command=show_progress)
        b.pack(side="right", padx=(0, 8))
        b.focus_set()
        root.bind("<Return>", lambda e: show_progress())

    def show_progress():
        root.unbind("<Return>")
        clear()
        busy["on"] = True
        var = tk.StringVar(value="Preparing…")
        tk.Label(body, textvariable=var, font=(FONT, 10)).pack(anchor="w")
        bar = ttk.Progressbar(body, length=440, mode="determinate", maximum=1.0)
        bar.pack(pady=(6, 0))

        def status(text, frac):
            root.after(0, lambda: (var.set(text), bar.configure(value=frac)))

        def done(err, made):
            root.after(0, lambda: show_finish(err, made))

        threading.Thread(target=run_install,
                         args=(status, done, want_desktop.get(),
                               want_startmenu.get()), daemon=True).start()

    def show_finish(err, made):
        busy["on"] = False
        clear()
        if err:
            messagebox.showerror("Smash Night Setup",
                                 "Installation failed:\n\n" + err[-1200:])
            root.destroy()
            return
        tk.Label(body, text="Smash Night is installed.",
                 font=(FONT, 11, "bold")).pack(anchor="w")
        if made:
            where = "Open it from: " + " or the ".join(
                "your Desktop" if m == "Desktop" else m for m in made) + "."
        else:
            where = ("No shortcut was created — open the folder above and "
                     "run Smash Night.exe.")
        tk.Label(body, text=where, font=(FONT, 10), wraplength=440,
                 justify="left").pack(anchor="w", pady=(4, 8))
        tk.Checkbutton(body, text="Start Smash Night now", variable=start_now,
                       font=(FONT, 10)).pack(anchor="w")

        def finish():
            if start_now.get():
                try:
                    launch_app()
                except Exception as e:
                    messagebox.showerror("Smash Night Setup",
                                         f"Could not start Smash Night:\n{e}")
            root.destroy()

        b = ttk.Button(buttons, text="Finish", command=finish)
        b.pack(side="right")
        ttk.Button(buttons, text="Open folder",
                   command=lambda: os.startfile(install_dir())).pack(
            side="right", padx=(0, 8))
        b.focus_set()
        root.bind("<Return>", lambda e: finish())
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    show_options()
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
