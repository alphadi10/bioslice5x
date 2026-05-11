"""Minimal Tkinter GUI wrapping the BioSlice5X CLI.

The GUI is intentionally thin — see ADR-003 for the file-picker-only
design (no inline recipe editor in v0.1.0). It exposes:

- Input mesh picker (STL/OBJ).
- Profile selector: shipped profiles (open5x_prusa, open5x_voron,
  hypothetical_3axis) or "load from file...".
- Recipe file picker (YAML).
- Output path picker, defaulting to `<mesh-basename>.gcode`.
- "Slice" button.
- Output panel: text-appending log + a final stress-report summary.
- "Open output folder" button on completion.
- File > Quit, Help > About menu.

Launch with `bioslice5x-gui` after install, or `python -m bioslice5x.gui`.
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from bioslice5x import __version__
from bioslice5x.profile.loader import _library_dir as _profile_library_dir

if TYPE_CHECKING:
    pass


SHIPPED_PROFILES = ["open5x_prusa", "open5x_voron", "hypothetical_3axis"]


class BioSlice5XApp(tk.Tk):
    """Top-level Tk window for BioSlice5X.

    The window is non-modal; the slice runs on a background thread so the
    UI stays responsive. The Tk event loop polls a queue of log messages
    from the slicer thread and appends them to the output panel.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title(f"BioSlice5X {__version__}")
        self.geometry("720x560")
        self.minsize(640, 480)

        self._mesh_var = tk.StringVar()
        self._profile_var = tk.StringVar(value=SHIPPED_PROFILES[0])
        self._recipe_var = tk.StringVar()
        self._output_var = tk.StringVar()

        self._build_menus()
        self._build_widgets()

    def _build_menus(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About BioSlice5X", command=self._show_about)
        help_menu.add_command(label="Documentation", command=self._open_docs)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, **pad)

        # Row 0: input mesh
        ttk.Label(frame, text="Input mesh:").grid(row=0, column=0, sticky=tk.W, **pad)
        ttk.Entry(frame, textvariable=self._mesh_var, width=60).grid(
            row=0, column=1, sticky=tk.EW, **pad
        )
        ttk.Button(frame, text="Browse…", command=self._pick_mesh).grid(row=0, column=2, **pad)

        # Row 1: profile
        ttk.Label(frame, text="Machine profile:").grid(row=1, column=0, sticky=tk.W, **pad)
        profile_combo = ttk.Combobox(
            frame,
            textvariable=self._profile_var,
            values=[*SHIPPED_PROFILES, "(load from file…)"],
            state="readonly",
            width=58,
        )
        profile_combo.grid(row=1, column=1, sticky=tk.EW, **pad)
        profile_combo.bind("<<ComboboxSelected>>", self._on_profile_changed)

        # Row 2: recipe
        ttk.Label(frame, text="Recipe (YAML):").grid(row=2, column=0, sticky=tk.W, **pad)
        ttk.Entry(frame, textvariable=self._recipe_var, width=60).grid(
            row=2, column=1, sticky=tk.EW, **pad
        )
        ttk.Button(frame, text="Browse…", command=self._pick_recipe).grid(row=2, column=2, **pad)

        # Row 3: output
        ttk.Label(frame, text="Output G-code:").grid(row=3, column=0, sticky=tk.W, **pad)
        ttk.Entry(frame, textvariable=self._output_var, width=60).grid(
            row=3, column=1, sticky=tk.EW, **pad
        )
        ttk.Button(frame, text="Browse…", command=self._pick_output).grid(row=3, column=2, **pad)

        # Row 4: action buttons
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, **pad)
        self._slice_button = ttk.Button(button_frame, text="Slice", command=self._on_slice)
        self._slice_button.pack(side=tk.LEFT, padx=4)
        self._open_folder_button = ttk.Button(
            button_frame,
            text="Open output folder",
            command=self._open_output_folder,
            state=tk.DISABLED,
        )
        self._open_folder_button.pack(side=tk.LEFT, padx=4)

        # Row 5: output log (scrollable)
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW, **pad)
        frame.rowconfigure(5, weight=1)
        frame.columnconfigure(1, weight=1)
        self._log = tk.Text(log_frame, wrap=tk.WORD, height=18, state=tk.DISABLED)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self._log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.config(yscrollcommand=scroll.set)

    # ---- mesh / recipe / output pickers ----

    def _pick_mesh(self) -> None:
        path = filedialog.askopenfilename(
            title="Select mesh (STL or OBJ)",
            filetypes=[("STL files", "*.stl"), ("OBJ files", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self._mesh_var.set(path)
            # Default output path next to the mesh.
            if not self._output_var.get():
                stem = Path(path).with_suffix(".gcode")
                self._output_var.set(str(stem))

    def _pick_recipe(self) -> None:
        path = filedialog.askopenfilename(
            title="Select recipe YAML",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            self._recipe_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save G-code as",
            defaultextension=".gcode",
            filetypes=[("G-code", "*.gcode"), ("All files", "*.*")],
        )
        if path:
            self._output_var.set(path)

    def _on_profile_changed(self, _event: object) -> None:
        if self._profile_var.get() == "(load from file…)":
            path = filedialog.askopenfilename(
                title="Select profile YAML",
                filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
                initialdir=str(_profile_library_dir()),
            )
            if path:
                self._profile_var.set(path)
            else:
                self._profile_var.set(SHIPPED_PROFILES[0])

    # ---- slicing ----

    def _on_slice(self) -> None:
        mesh = self._mesh_var.get().strip()
        profile = self._profile_var.get().strip()
        recipe = self._recipe_var.get().strip()
        output = self._output_var.get().strip()
        if not (mesh and profile and recipe and output):
            messagebox.showerror(
                "Missing inputs",
                "Please fill in every field: mesh, profile, recipe, output path.",
            )
            return
        if not Path(mesh).is_file():
            messagebox.showerror("Mesh not found", f"No file at: {mesh}")
            return
        if not Path(recipe).is_file():
            messagebox.showerror("Recipe not found", f"No file at: {recipe}")
            return
        self._slice_button.config(state=tk.DISABLED)
        self._open_folder_button.config(state=tk.DISABLED)
        self._append_log(f"Slicing {Path(mesh).name} with {profile} + {Path(recipe).name}…\n")
        thread = threading.Thread(
            target=self._run_slice,
            args=(mesh, profile, recipe, output),
            daemon=True,
        )
        thread.start()

    def _run_slice(self, mesh: str, profile: str, recipe: str, output: str) -> None:
        try:
            from bioslice5x import Slicer, load_mesh, load_profile, load_recipe

            self.after(0, self._append_log, "Loading profile…\n")
            prof = load_profile(profile)
            self.after(0, self._append_log, "Loading recipe…\n")
            rec = load_recipe(recipe)
            self.after(0, self._append_log, "Loading mesh…\n")
            m = load_mesh(mesh)
            self.after(0, self._append_log, "Slicing…\n")
            slicer = Slicer(profile=prof, recipe=rec)
            result = slicer.slice(m)
            result.write_gcode(output)
            self.after(
                0,
                self._append_log,
                (
                    f"Wrote {output}\n"
                    f"  {len(result.moves)} moves, "
                    f"max wall shear {result.stress_report.max_observed_pa():.1f} Pa, "
                    f"estimated time {result.estimated_seconds:.0f} s\n"
                ),
            )
            self.after(0, lambda: self._open_folder_button.config(state=tk.NORMAL))
        except Exception as exc:
            self.after(0, self._append_log, f"\nERROR: {type(exc).__name__}: {exc}\n")
        finally:
            self.after(0, lambda: self._slice_button.config(state=tk.NORMAL))

    def _append_log(self, text: str) -> None:
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _open_output_folder(self) -> None:
        path = self._output_var.get().strip()
        if not path:
            return
        folder = Path(path).parent
        if sys.platform == "darwin":
            os.system(f"open {folder!s}")
        elif sys.platform == "win32":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            os.system(f"xdg-open {folder!s}")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About BioSlice5X",
            (
                f"BioSlice5X {__version__}\n"
                "Open-source 5-axis slicer for syringe-based bioprinting.\n\n"
                "MIT licensed. https://github.com/bioslice5x/bioslice5x\n\n"
                "Calibration disclaimer: shipped bioink, cell, and bath values "
                "are uncalibrated literature defaults. Validate against your "
                "lab's empirical data before publication-grade work."
            ),
        )

    def _open_docs(self) -> None:
        webbrowser.open("https://github.com/bioslice5x/bioslice5x#readme")


def main(argv: list[str] | None = None) -> int:
    """Launch the GUI. Returns 0 on clean exit."""
    app = BioSlice5XApp()
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
