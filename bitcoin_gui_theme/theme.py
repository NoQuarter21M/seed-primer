"""
theme.py — canonical palettes + corrected theming engine.
Stdlib only (tkinter). No network, no disk writes.
"""

import tkinter as tk

__version__ = "1.1.0"

# ---------------------------------------------------------------------------
# Canonical palettes
# Source of truth: entropy-mixer-fusion-seeder/gui/mixer_gui.py, extended with
# gauge_* keys used by wallet-factory. Any GUI-specific colors should be added
# here (in BOTH themes) rather than redefined per-project.
# ---------------------------------------------------------------------------

THEMES = {
    "dark": dict(
        bg="#121212", fg="#e8e8e8", fg2="#b0b0b0", fg3="#8c8c8c",
        entry_bg="#242424", track="#333333", marker="#cccccc",
        pass_color="#66d17a", fail_color="#ff6f61", warn="#ffab91",
        accent="#4a9eff",
        zone_green="#66d17a", zone_orange="#ffb84d",
        zone_red="#ff6f61", zone_yg="#c5e17a",
        gauge_bg="#2a2a2a", gauge_fill="#4a9eff",
        gauge_warn="#ffb84d", gauge_crit="#ff6f61",
    ),
    "light": dict(
        bg="#f4f3ef", fg="#1a1a1a", fg2="#5a5a5a", fg3="#7a7a7a",
        entry_bg="#ffffff", track="#e5e5e5", marker="#333333",
        pass_color="#2e7d32", fail_color="#c0392b", warn="#a83232",
        accent="#1565c0",
        zone_green="#2e7d32", zone_orange="#e08e0b",
        zone_red="#c0392b", zone_yg="#8aa624",
        gauge_bg="#dddddd", gauge_fill="#1565c0",
        gauge_warn="#e08e0b", gauge_crit="#c0392b",
    ),
}

# Palette keys whose value, when found on a Label's fg, means "this color was
# chosen deliberately — do not flatten it to the default fg during recolor".
_ACCENT_KEYS = ("fg2", "fg3", "pass_color", "fail_color", "warn", "accent",
                "zone_green", "zone_orange", "zone_red", "zone_yg")


def _accent_color_set():
    """All accent color strings across BOTH themes, lowercased.
    Including both themes means a label keeps its 'keep_fg' status across a
    theme toggle even before the screen is rebuilt."""
    s = set()
    for th in THEMES.values():
        for k in _ACCENT_KEYS:
            s.add(str(th[k]).lower())
    return s

# ---------------------------------------------------------------------------
# Themed widget constructors
# Prefer these over raw tk.Label/Button/Entry when a widget needs a specific
# accent color — they tag the widget so recolor() preserves the choice.
# ---------------------------------------------------------------------------

def themed_label(parent, text, theme=None, fg=None, **kw):
    """Create a Label. If `fg` is given (an accent), tag it _keep_fg so the
    recolor pass preserves it instead of flattening to the default fg.
    If `fg` is omitted, the label uses the primary fg and follows the theme."""
    if fg is not None:
        lbl = tk.Label(parent, text=text, fg=fg, **kw)
        lbl._keep_fg = True
    else:
        c = THEMES[theme] if theme else None
        lbl = tk.Label(parent, text=text,
                       fg=c["fg"] if c else None, **kw)
    return lbl


def themed_button(parent, text, theme=None, accent=False, fill=None, **kw):
    """Create a Button. Set accent=True (or pass fill=<color>) for a solid
    colored button (e.g. Start/Stop) that recolor() will leave alone."""
    btn = tk.Button(parent, text=text, relief=kw.pop("relief", "flat"), **kw)
    if fill is not None:
        btn.configure(bg=fill, fg="#ffffff",
                      activebackground=fill, activeforeground="#ffffff")
        btn._no_theme = True
    elif accent:
        btn._no_theme = True
    return btn


def themed_entry(parent, theme=None, **kw):
    c = THEMES[theme] if theme else None
    e = tk.Entry(parent, relief=kw.pop("relief", "flat"), **kw)
    if c:
        e.configure(bg=c["entry_bg"], fg=c["fg"], insertbackground=c["fg"])
    return e

# ---------------------------------------------------------------------------
# Recolor engine (corrected)
# ---------------------------------------------------------------------------

def tag_custom_labels(widget):
    """Walk the tree and tag any Label whose current fg matches a theme accent
    color, so recolor() preserves it. Call this BEFORE recolor() when a screen
    was built with raw tk.Label(..., fg=c["accent"]) instead of themed_label().
    Idempotent."""
    accents = _accent_color_set()
    if widget.winfo_class() == "Label":
        try:
            if str(widget.cget("fg")).lower() in accents:
                widget._keep_fg = True
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        tag_custom_labels(child)


def recolor(widget, theme):
    """Recursively apply `theme` colors to widget and all descendants.

    Corrected behavior vs. the original inline copies:
      * Label ALWAYS gets a foreground (default fg) unless tagged _keep_fg,
        so labels never render dark-on-dark.
      * Button/Label honor _no_theme / _keep_fg tags to preserve accents.
      * Legacy `no_theme` (no underscore, used by older GUIs) is also honored.
    """
    def _skip(w):
        return getattr(w, "_no_theme", False) or getattr(w, "no_theme", False)
    c   = THEMES[theme]
    cls = widget.winfo_class()
    try:
        if cls in ("Frame", "Labelframe"):
            widget.configure(bg=c["bg"])
            if cls == "Labelframe":
                widget.configure(fg=c["fg"])
        elif cls == "Canvas":
            # Only theme the canvas bg if it isn't a gauge track (gauges set
            # their own bg to gauge_bg and redraw themselves).
            if not _skip(widget):
                widget.configure(bg=c["bg"])
        elif cls == "Label":
            widget.configure(bg=c["bg"])
            if not getattr(widget, "_keep_fg", False):
                widget.configure(fg=c["fg"])
        elif cls == "Button":
            if not _skip(widget):
                widget.configure(bg=c["entry_bg"], fg=c["fg"],
                    activebackground=c["entry_bg"], activeforeground=c["fg"])
        elif cls == "Entry":
            widget.configure(bg=c["entry_bg"], fg=c["fg"],
                             insertbackground=c["fg"])
            try:
                widget.configure(readonlybackground=c["entry_bg"])
            except tk.TclError:
                pass
        elif cls in ("Radiobutton", "Checkbutton"):
            widget.configure(bg=c["bg"], fg=c["fg"],
                selectcolor=c["entry_bg"],
                activebackground=c["bg"], activeforeground=c["fg"])
        elif cls == "Spinbox":
            widget.configure(bg=c["entry_bg"], fg=c["fg"])
        elif cls == "Text":
            widget.configure(bg=c["entry_bg"], fg=c["fg2"],
                             insertbackground=c["fg"])
        elif cls == "Menubutton":
            widget.configure(bg=c["entry_bg"], fg=c["fg"],
                activebackground=c["entry_bg"], activeforeground=c["fg"])
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        recolor(child, theme)


def apply_theme(root, theme, container=None, header=None, header_labels_fg=None):
    """Apply a theme to a whole window.

    root:    the tk root/Toplevel — its bg is set.
    theme:   'dark' or 'light'.
    container: main content frame — tagged + recolored recursively.
    header:  optional header frame — recolored; its Labels use header_labels_fg
             (default fg3) so the header caption stays muted.
    """
    c = THEMES[theme]
    root.configure(bg=c["bg"])
    if header is not None:
        header.configure(bg=c["bg"])
        hfg = header_labels_fg or c["fg3"]
        for w in header.winfo_children():
            try:
                if w.winfo_class() == "Label":
                    w.configure(bg=c["bg"], fg=hfg)
                else:
                    recolor(w, theme)
            except tk.TclError:
                pass
    if container is not None:
        container.configure(bg=c["bg"])
        tag_custom_labels(container)
        recolor(container, theme)

# ---------------------------------------------------------------------------
# ThemeManager — optional convenience wrapper
# ---------------------------------------------------------------------------

class ThemeManager:
    """Holds current theme + wired references, provides toggle + apply.

        tm = ThemeManager(root, initial="dark")
        tm.bind(header=hdr, container=body, rebuild=self.show_current_screen)
        tm.apply()
        ...
        tm.toggle()   # flips theme, rebuilds screen, reapplies
    """

    def __init__(self, root, initial="dark"):
        self.root      = root
        self.theme     = initial if initial in THEMES else "dark"
        self._header   = None
        self._container= None
        self._rebuild  = None
        self._hdr_fg   = None
        self._btn      = None

    def bind(self, header=None, container=None, rebuild=None,
             header_labels_fg=None, toggle_button=None):
        if header is not None:    self._header    = header
        if container is not None: self._container = container
        if rebuild is not None:   self._rebuild   = rebuild
        if header_labels_fg is not None: self._hdr_fg = header_labels_fg
        if toggle_button is not None:    self._btn   = toggle_button
        return self

    def C(self):
        return THEMES[self.theme]

    def apply(self):
        apply_theme(self.root, self.theme,
                    container=self._container, header=self._header,
                    header_labels_fg=self._hdr_fg)
        if self._btn is not None:
            try:
                self._btn.config(
                    text="Light mode" if self.theme == "dark" else "Dark mode")
            except tk.TclError:
                pass

    def toggle(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        if self._rebuild:
            self._rebuild()
        self.apply()


# ---------------------------------------------------------------------------
# Workspace helper
# ---------------------------------------------------------------------------

def raise_to_active_workspace(root, topmost_ms=600):
    """Move `root` to the currently-active workspace (via wmctrl), then lift
    and briefly set topmost so it surfaces where the user is working.
    No-op if wmctrl is unavailable. Never pins to a hardcoded workspace."""
    import subprocess as _sp
    try:
        wid = hex(root.winfo_id())
        out = _sp.run(["wmctrl", "-d"], capture_output=True, text=True, timeout=2)
        cur = None
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "*":
                cur = parts[0]
                break
        if cur is not None:
            _sp.run(["wmctrl", "-i", "-r", wid, "-t", cur], timeout=2)
    except Exception:
        pass
    try:
        root.lift()
        root.attributes("-topmost", True)
        root.after(topmost_ms, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass
