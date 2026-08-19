"""
bitcoin_gui_theme — shared tkinter theme for NoQuarter21M Bitcoin GUIs.

Single source of truth for the dark/light palettes and the theming engine
used across entropy-mixer, audio-entropy-mixer, wallet-factory, etc.

The canonical palette is lifted from entropy-mixer-fusion-seeder's
mixer_gui.py (the reference GUI). The recolor engine here is the CORRECTED
version: unlike the original inline copies, it sets foreground on Labels so
they never render dark-on-dark, while preserving intentionally accent-colored
labels via a `_keep_fg` tag.

Usage
-----
    import tkinter as tk
    from bitcoin_gui_theme import THEMES, ThemeManager, themed_label

    class MyApp:
        def __init__(self, root):
            self.root = root
            self.theme = ThemeManager(root, initial="dark")
            self.header = tk.Frame(root); self.header.pack(fill="x")
            self.container = tk.Frame(root); self.container.pack(fill="both", expand=True)
            self.theme.bind(header=self.header, container=self.container,
                            rebuild=self.build_current_screen)
            self.build_current_screen()
            self.theme.apply()

        def build_current_screen(self):
            c = self.theme.C()
            themed_label(self.container, "Hello", fg=c["accent"]).pack()

Palette keys
------------
    bg, fg, fg2, fg3        surfaces + text (primary/secondary/tertiary)
    entry_bg, track, marker inputs, slider tracks, slider markers
    pass_color, fail_color  green / red status
    warn, accent            amber / blue accents
    zone_green, zone_orange, zone_red, zone_yg   gauge tier colors
    gauge_bg, gauge_fill, gauge_warn, gauge_crit progress gauges
"""

from .theme import (
    THEMES,
    ThemeManager,
    apply_theme,
    recolor,
    tag_custom_labels,
    themed_label,
    themed_button,
    themed_entry,
    raise_to_active_workspace,
    __version__,
)

__all__ = [
    "THEMES",
    "ThemeManager",
    "apply_theme",
    "recolor",
    "tag_custom_labels",
    "themed_label",
    "themed_button",
    "themed_entry",
    "raise_to_active_workspace",
    "__version__",
]
