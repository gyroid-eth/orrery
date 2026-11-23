"""Choose a folder with Windows' own folder dialog.

A web page cannot learn a folder's full path, so the host, which runs on
the same desktop, opens the dialog itself. Tk 8.6 shows the Explorer-style
dialog (IFileDialog with FOS_PICKFOLDERS) on Windows. All Tk calls stay in
the one worker thread that runs pick_folder, which is what Tk requires.
"""
from __future__ import annotations

import os


def pick_folder(initial: str | None = None, title: str = "作業フォルダを選ぶ") -> str | None:
    """Block until a folder is chosen; None when the dialog is cancelled."""
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    try:
        root.withdraw()
        # The host has no window of its own: an owner that stays on top keeps
        # the dialog from opening behind the browser.
        root.attributes("-topmost", True)
        root.update()
        start = initial if initial and os.path.isdir(initial) else None
        chosen = filedialog.askdirectory(parent=root, initialdir=start, title=title, mustexist=True)
    finally:
        root.destroy()
    return os.path.normpath(chosen) if chosen else None
