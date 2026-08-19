#!/usr/bin/env python3
"""
entropy_mix_gui.py

Card + Dice Entropy Generator -- tkinter GUI.

Runs fully offline. No network code. No disk writes of entropy or
mnemonic data. No clipboard use. Standard library only (tkinter,
hashlib, math) -- no pip installs required.

DISCLAIMER: This tool is not certified by NIST and makes no compliance
claims. It implements a curated subset of NIST SP 800-22 statistical
tests, adapted for short inputs, for indicative purposes only.
Verify offline operation before use. Not responsible for loss of funds.
MIT License -- provided as-is.
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox

import entropy_mix_core as core

# Optional entropy quality estimator (entropy-bruteforce project).
# Imported lazily so the GUI works even if the file is not present.
try:
    import sys as _sys, pathlib as _pl
    _est_path = _pl.Path(__file__).parent.parent / "entropy-bruteforce"
    if str(_est_path) not in _sys.path:
        _sys.path.insert(0, str(_est_path))
    from entropy_estimator import estimate as _entropy_estimate, render_report as _render_report
    _ESTIMATOR_AVAILABLE = True
except Exception:
    _ESTIMATOR_AVAILABLE = False

# Optional RP2350 (Pico 2) hardware TRNG source. Imported lazily so the
# GUI works identically whether or not the device is plugged in.
try:
    import pico_trng_source as _pico
    _PICO_MODULE_AVAILABLE = True
except Exception:
    _PICO_MODULE_AVAILABLE = False

WORDLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordlist_english.txt")

SUITS = [("Spades", "S", "\u2660"), ("Hearts", "H", "\u2665"),
         ("Diamonds", "D", "\u2666"), ("Clubs", "C", "\u2663")]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# Cards are always eggshell-white "card faces" regardless of theme -- a
# card looks like a card whether the app is in light or dark mode. Suit
# colors are correspondingly fixed too (not theme-dependent), since the
# background they sit on never changes.
EGGSHELL = "#f0ead6"
EGGSHELL_USED = "#d9d3c0"
SUIT_COLOR = {"S": "#141414", "C": "#141414", "H": "#a8342a", "D": "#a8342a"}

# Dark palette follows Material Design's dark-theme guidance (near-black
# #121212 surface, high-contrast off-white text, elevated surfaces one
# step lighter than the page background) rather than an ad hoc scheme,
# for known-good legibility. Light palette is a warm off-white, softened
# from pure black/white for eye comfort.
# THEMES sourced from vendored shared module
# (NoQuarter21M/bitcoin-gui-theme) — single palette source of truth.
from bitcoin_gui_theme import THEMES


class EntropyGenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Entropy Mixer")
        self.root.geometry("1250x880")
        self.root.minsize(1150, 720)

        self.theme = "dark"
        self.current_phase_fn = None

        # session state (memory only -- never written to disk)
        self.mode = None
        self.shuffle_count = None
        self.dice_quality = None
        self.target_bits = None
        self.cards_needed = None
        self.shuffle_loss_bits = None

        # persisted across screen rebuilds (theme toggle, network toggle)
        self.network = "mainnet"
        self._settings_mode = "256"
        self._settings_shuffle = 10
        self._settings_dice = "consumer"
        self._passphrase_text = ""
        self._qr_size = 25
        self._qr_visible = False
        self._run_estimator = False   # toggled in settings
        self._pico_enabled = False     # persist across screen rebuilds
        self._pico_port = None         # confirmed port from scan
        self._pico_scan_result = None  # (ok, msg) from last scan

        self.card_seq = []
        self.dice_seq = []
        self.dnd_throws = []          # list of (d4,d6,d8,d10,d12,d20) tuples
        self.card_buttons = {}

        self.header = tk.Frame(root)
        self.header.pack(fill="x")
        self.header_label = tk.Label(
            self.header, text="Runs offline. Does not store or transmit data. Use at your own risk.",
            font=("TkDefaultFont", 11))
        self.header_label.pack(side="left", padx=(14, 0), pady=6)
        self.theme_btn = tk.Button(self.header, text="Light mode", command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=14, pady=4)

        self.container = tk.Frame(root)
        self.container.pack(fill="both", expand=True, padx=14, pady=8)

        # Auto-mask on focus loss: only active during Step 4.
        # When the window loses focus, all revealed sensitive fields
        # snap back to masked state without user action.
        self._in_hash_phase = False
        self.root.bind("<FocusOut>", self._on_focus_out)

        self.show_settings_screen()
        self.apply_theme()

    def C(self):
        return THEMES[self.theme]

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.config(text="Light mode" if self.theme == "dark" else "Dark mode")
        if self.current_phase_fn:
            self.current_phase_fn()
        self.apply_theme()

    def apply_theme(self):
        c = self.C()
        self.root.configure(bg=c["bg"])
        self.header.configure(bg=c["bg"])
        self.header_label.configure(bg=c["bg"], fg=c["fg3"])
        self.theme_btn.configure(bg=c["entry_bg"], fg=c["fg"])
        self.container.configure(bg=c["bg"])
        self._recolor(self.container)

    def _recolor(self, widget):
        """Recursively apply the current theme's colors to every
        container/control created by the phase builders. Card buttons
        are excluded (tagged no_theme=True at creation) since they are
        always eggshell-white with fixed suit colors, independent of
        theme. PASS/FAIL and warning labels keep their semantic colors
        (set at creation from self.C(), already theme-correct since
        each screen is fully rebuilt on toggle) but still get their
        background themed here."""
        c = self.C()
        cls = widget.winfo_class()
        try:
            if cls in ("Frame", "Labelframe"):
                widget.configure(bg=c["bg"])
                if cls == "Labelframe":
                    widget.configure(fg=c["fg"])
            elif cls == "Canvas":
                widget.configure(bg=c["bg"])
            elif cls == "Label":
                widget.configure(bg=c["bg"])
            elif cls == "Button":
                if not getattr(widget, "no_theme", False):
                    widget.configure(bg=c["entry_bg"], fg=c["fg"],
                                      activebackground=c["entry_bg"], activeforeground=c["fg"])
            elif cls == "Entry":
                widget.configure(bg=c["entry_bg"], fg=c["fg"], insertbackground=c["fg"])
                try:
                    widget.configure(readonlybackground=c["entry_bg"])
                except tk.TclError:
                    pass
            elif cls == "Radiobutton":
                widget.configure(bg=c["bg"], fg=c["fg"], selectcolor=c["entry_bg"],
                                  activebackground=c["bg"], activeforeground=c["fg"])
            elif cls == "Checkbutton":
                # Background/selectcolor follow the theme, but the
                # foreground is left alone -- the STOP-tier override
                # checkbox is deliberately warning-colored and shouldn't
                # be reset to ordinary body text color on a theme toggle.
                widget.configure(bg=c["bg"], selectcolor=c["entry_bg"],
                                  activebackground=c["bg"])
            elif cls == "Spinbox":
                widget.configure(bg=c["entry_bg"], fg=c["fg"])
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._recolor(child)

    def clear_container(self):
        # Unbind any container-level handlers a previous screen may have
        # attached (e.g. settings' resize-driven wraplength updater) --
        # self.container itself persists across screens and is never
        # destroyed, only its children are, so a stale handler here would
        # otherwise keep firing on resize and reference already-destroyed
        # widgets from whatever screen was last shown before this one.
        self.container.unbind("<Configure>")
        for w in self.container.winfo_children():
            w.destroy()
        self._in_hash_phase = False

    def _on_focus_out(self, event):
        """Auto-mask all sensitive fields when the window loses focus.
        Only active during Step 4 -- no-op on all other screens."""
        if not self._in_hash_phase:
            return
        # Only trigger on the root window losing focus, not on internal
        # widget-to-widget transitions within the same app (which also
        # fire FocusOut events on child widgets).
        if event.widget == self.root:
            self._mask_all_sensitive()

    def _mask_all_sensitive(self):
        """Snap all revealed sensitive fields back to masked state."""
        if hasattr(self, "_word_buttons"):
            for i, btn in enumerate(self._word_buttons):
                btn.config(text=f"{i+1}. ****")
        if hasattr(self, "entropy_var") and hasattr(self, "_entropy_visible"):
            self._entropy_visible = False
            self.entropy_var.set("SHA-256 whitened entropy: **** (click to reveal)")
        if hasattr(self, "seed_var") and hasattr(self, "_seed_visible"):
            self._seed_visible = False
            self.seed_var.set("Wallet seed: **** (click to reveal)")

    @staticmethod
    def _block_copy(widget):
        """Unbind all clipboard-extraction events on a widget.
        Covers keyboard shortcuts and X11 middle-click paste."""
        for seq in ("<Control-c>", "<Control-C>",
                    "<Control-Insert>", "<Shift-Insert>",
                    "<Button-2>", "<B2-Motion>"):
            widget.bind(seq, lambda e: "break")

    # ------------------------------------------------------------------
    # Phase 0: settings
    # ------------------------------------------------------------------

    def show_settings_screen(self):
        self.current_phase_fn = self.show_settings_screen
        self.clear_container()
        c = self.C()
        f = self.container

        # Two-column responsive grid instead of a single left-anchored
        # stack -- columns share available width equally via weight=1,
        # so this scales with the window rather than assuming one fixed
        # size. Works whether the window is at its minsize or maximized
        # on a much larger display.
        f.grid_columnconfigure(0, weight=1, uniform="settings_col")
        f.grid_columnconfigure(1, weight=1, uniform="settings_col")

        tk.Label(f, text="Settings", font=("TkDefaultFont", 18, "bold"),
                 fg=c["fg"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

        # ---- Left panel: seed length + dice quality ----
        left_panel = tk.LabelFrame(f, text="Seed & Dice", font=("TkDefaultFont", 11, "bold"))
        left_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(0, 14))

        tk.Label(left_panel, text="Entropy source & seed length:",
                 fg=c["fg"], font=("TkDefaultFont", 11)).pack(anchor="w", padx=12, pady=(10, 2))
        self.mode_var = tk.StringVar(value=self._settings_mode)
        mode_col = tk.Frame(left_panel)
        mode_col.pack(anchor="w", padx=12, pady=(0, 6))

        def _mode_changed():
            self._settings_mode = self.mode_var.get()
            _update_mode_advisory()
            # Show/hide shuffle panel depending on whether mode uses cards
            uses_cards = self._settings_mode in ("128", "256")
            right_panel.grid() if uses_cards else right_panel.grid_remove()

        tk.Label(mode_col, text="Cards:", fg=c["fg"],
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 2))
        tk.Radiobutton(mode_col, text="12 words (128 bits) \u2014 27 cards only",
                       variable=self.mode_var, value="128",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")
        tk.Radiobutton(mode_col, text="24 words (256 bits) \u2014 52 cards + D6 top-up",
                       variable=self.mode_var, value="256",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")

        tk.Label(mode_col, text="D6 dice only:", fg=c["fg"],
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 2))
        tk.Radiobutton(mode_col, text="12 words (128 bits) \u2014 60 rolls min (12 groups of 5)",
                       variable=self.mode_var, value="d6_128",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")
        tk.Radiobutton(mode_col, text="24 words (256 bits) \u2014 120 rolls min (24 groups of 5)",
                       variable=self.mode_var, value="d6_256",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")

        tk.Label(mode_col, text="DnD dice set (D4/D6/D8/D10/D12/D20):",
                 fg=c["fg"], font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 2))
        tk.Radiobutton(mode_col, text="12 words (128 bits) \u2014 10 throws min",
                       variable=self.mode_var, value="dnd_128",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")
        tk.Radiobutton(mode_col, text="24 words (256 bits) \u2014 20 throws min",
                       variable=self.mode_var, value="dnd_256",
                       font=("TkDefaultFont", 10),
                       command=_mode_changed).pack(anchor="w")

        self._mode_advisory = tk.Label(mode_col, fg=c["fg3"],
                                        font=("TkDefaultFont", 9), justify="left")
        self._mode_advisory.pack(anchor="w", pady=(6, 0), fill="x")

        def _update_mode_advisory():
            m = self.mode_var.get()
            if m == "128":
                txt = ("27 cards alone clear 128 bits after shuffle-quality deduction. "
                       "No dice phase needed.")
            elif m == "256":
                txt = ("A deck is capped at ~216 discounted bits. Dice contribute the "
                       "remaining ~40 bits from an independent physical source.")
            elif m == "d6_128":
                txt = ("Roll 5 D6 dice at a time. 60 rolls (12 groups) minimum to clear "
                       "128 bits with consumer-grade dice discount.")
            elif m == "d6_256":
                txt = ("Roll 5 D6 dice at a time. 120 rolls (24 groups) minimum to clear "
                       "256 bits with consumer-grade dice discount.")
            elif m == "dnd_128":
                txt = ("Full DnD set: D4/D6/D8/D10/D12/D20 in fixed order per throw. "
                       "10 throws minimum (~138 discounted bits).")
            elif m == "dnd_256":
                txt = ("Full DnD set: D4/D6/D8/D10/D12/D20 in fixed order per throw. "
                       "20 throws minimum (~277 discounted bits).")
            else:
                txt = ""
            self._mode_advisory.config(text=txt)

        _update_mode_advisory()

        tk.Label(left_panel, text="Dice quality:", fg=c["fg"],
                 font=("TkDefaultFont", 11)).pack(anchor="w", padx=12, pady=(4, 2))
        self.dice_quality_var = tk.StringVar(value=self._settings_dice)
        dice_col = tk.Frame(left_panel)
        dice_col.pack(anchor="w", padx=12, pady=(0, 14))
        tk.Radiobutton(dice_col, text="Consumer dice", variable=self.dice_quality_var, value="consumer",
                        font=("TkDefaultFont", 10),
                        command=lambda: setattr(self, "_settings_dice", self.dice_quality_var.get())).pack(anchor="w")
        tk.Radiobutton(dice_col, text="Precision/casino-grade dice", variable=self.dice_quality_var, value="precision",
                        font=("TkDefaultFont", 10),
                        command=lambda: setattr(self, "_settings_dice", self.dice_quality_var.get())).pack(anchor="w")

        # ---- Right panel: shuffle count ----
        right_panel = tk.LabelFrame(f, text="Shuffle Count", font=("TkDefaultFont", 11, "bold"))
        right_panel.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(0, 14))

        tk.Label(right_panel, text="How many times did you riffle-shuffle the deck?", fg=c["fg"],
                 font=("TkDefaultFont", 11), justify="left").pack(anchor="w", padx=12, pady=(10, 4))
        self.shuffle_var = tk.IntVar(value=self._settings_shuffle)
        tk.Spinbox(right_panel, from_=0, to=50, textvariable=self.shuffle_var, width=6,
                   font=("TkDefaultFont", 11),
                   command=lambda: setattr(self, "_settings_shuffle", self.shuffle_var.get())).pack(anchor="w", padx=12, pady=(0, 8))
        shuffle_advisory = tk.Label(
            right_panel,
            text="Fewer than 7 shuffles will be blocked (Bayer-Diaconis mixing theory "
                 "shows a riffle-shuffled deck is still far from uniform below 7 "
                 "shuffles). 10+ recommended.",
            fg=c["fg3"], font=("TkDefaultFont", 10), justify="left")
        shuffle_advisory.pack(anchor="w", padx=12, pady=(0, 12), fill="x")

        # ---- Full-width advisory + button ----
        deck_advisory = tk.Label(
            f,
            text="Advisory: avoid using a fresh-from-box deck. Factory order survives "
                 "low shuffle counts. Use a deck that has already seen normal shuffling, "
                 "or shuffle extra times to break factory order.",
            fg=c["fg3"], font=("TkDefaultFont", 10), justify="left")
        deck_advisory.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # ---- Pico TRNG panel ----
        pico_frame = tk.LabelFrame(f, text="Pico 2 TRNG (RP2350) \u2014 hardware entropy injection",
                                   font=("TkDefaultFont", 11, "bold"))
        pico_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        if not _PICO_MODULE_AVAILABLE:
            tk.Label(pico_frame,
                     text="\u26a0  pico_trng_source.py not available -- Pico TRNG disabled.",
                     fg=c["warn"], font=("TkDefaultFont", 10)).pack(anchor="w", padx=12, pady=(6, 6))
        else:
            pico_top = tk.Frame(pico_frame)
            pico_top.pack(fill="x", padx=12, pady=(8, 4))

            self._pico_enable_var = tk.BooleanVar(value=self._pico_enabled)
            tk.Checkbutton(
                pico_top,
                text="Inject Pico 2 TRNG into raw entropy before whitening (recommended when Pico is connected)",
                variable=self._pico_enable_var,
                command=lambda: setattr(self, "_pico_enabled", self._pico_enable_var.get()),
                fg=c["fg"], bg=c["bg"], selectcolor=c["bg"],
                font=("TkDefaultFont", 10), anchor="w", justify="left",
            ).pack(side="left")

            # Status row: port + health indicator
            pico_status_row = tk.Frame(pico_frame)
            pico_status_row.pack(fill="x", padx=12, pady=(0, 4))

            self._pico_status_var = tk.StringVar(value="Not scanned yet")
            self._pico_status_lbl = tk.Label(
                pico_status_row, textvariable=self._pico_status_var,
                font=("TkDefaultFont", 10), fg=c["fg3"], anchor="w", justify="left",
                wraplength=800)
            self._pico_status_lbl.pack(side="left", fill="x", expand=True)

            def _scan_pico():
                self._pico_status_var.set("Scanning ports\u2026")
                self._pico_status_lbl.config(fg=c["fg3"])
                pico_frame.update_idletasks()
                import threading
                def _worker():
                    ok_port, msg, chunk = _pico.find_pico()
                    def _update():
                        if ok_port:
                            self._pico_port = ok_port
                            self._pico_scan_result = (True, msg)
                            self._pico_enable_var.set(True)
                            self._pico_enabled = True
                            self._pico_status_var.set(f"\u2713 {msg}")
                            self._pico_status_lbl.config(fg=c["pass_color"])
                        else:
                            self._pico_port = None
                            self._pico_scan_result = (False, msg)
                            self._pico_status_var.set(f"\u2718 {msg}")
                            self._pico_status_lbl.config(fg=c["fail_color"])
                    pico_frame.after(0, _update)
                threading.Thread(target=_worker, daemon=True).start()

            scan_btn = tk.Button(pico_status_row, text="Scan for Pico",
                                  command=_scan_pico, font=("TkDefaultFont", 10))
            scan_btn.pack(side="right", padx=(8, 0))

            # Restore last scan result if available
            if self._pico_scan_result is not None:
                ok, msg = self._pico_scan_result
                self._pico_status_var.set(f"\u2713 {msg}" if ok else f"\u2718 {msg}")
                self._pico_status_lbl.config(
                    fg=c["pass_color"] if ok else c["fail_color"])

            tk.Label(pico_frame,
                     text="The Pico's qualified TRNG output (NIST SP 800-90B, 7.466 bits/byte) "
                          "is XOR'd into the raw card/dice bit string before SHA-256 whitening. "
                          "XOR independence property: if either source is uniform, the combined "
                          "output is uniform -- this can only help, never hurt.",
                     fg=c["fg3"], font=("TkDefaultFont", 9),
                     wraplength=1000, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # ---- Entropy estimator toggle ----
        est_frame = tk.LabelFrame(f, text="Entropy Quality Estimator",
                                  font=("TkDefaultFont", 11, "bold"))
        est_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self._estimator_var = tk.BooleanVar(value=self._run_estimator)
        est_chk = tk.Checkbutton(
            est_frame,
            text="Run entropy quality report after seed reveal  "
                 "(adds monobit, runs, chi-square, autocorrelation, Shannon entropy, "
                 "and SP 800-90B min-entropy tests on the whitened entropy bytes)",
            variable=self._estimator_var,
            command=lambda: setattr(self, "_run_estimator", self._estimator_var.get()),
            fg=c["fg"], bg=c["bg"], selectcolor=c["bg"],
            font=("TkDefaultFont", 10), anchor="w", justify="left", wraplength=860)
        est_chk.pack(anchor="w", padx=12, pady=(6, 4))
        if not _ESTIMATOR_AVAILABLE:
            tk.Label(est_frame,
                     text="\u26a0  entropy_estimator.py not found in ../entropy-bruteforce/ — "
                          "toggle has no effect until the file is present.",
                     fg=c["warn"], font=("TkDefaultFont", 9),
                     wraplength=860, justify="left").pack(anchor="w", padx=12, pady=(0, 6))
        else:
            tk.Label(est_frame,
                     text="Pure stdlib. Runs in a background thread; report appears as a "
                          "collapsible panel below the mnemonic. No entropy bytes are logged.",
                     fg=c["fg3"], font=("TkDefaultFont", 9),
                     wraplength=860, justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        tk.Button(f, text="Continue \u2192", font=("TkDefaultFont", 12, "bold"),
                  command=self.apply_settings).grid(row=5, column=0, columnspan=2, sticky="w")

        # Responsive wraplength: recomputed on resize so descriptive text
        # re-wraps correctly whether the window is at its minimum size or
        # stretched wide on a larger display, instead of a hardcoded pixel
        # value that only looks right at one specific window size.
        def _update_wraplengths(event=None):
            panel_width = max(right_panel.winfo_width() - 24, 200)
            shuffle_advisory.config(wraplength=panel_width)
            left_width = max(left_panel.winfo_width() - 24, 200)
            self._mode_advisory.config(wraplength=left_width)
            full_width = max(f.winfo_width() - 4, 200)
            deck_advisory.config(wraplength=full_width)

        right_panel.bind("<Configure>", _update_wraplengths)
        f.bind("<Configure>", _update_wraplengths)
        f.update_idletasks()
        _update_wraplengths()

        self._recolor(f)

    def apply_settings(self):
        self._settings_mode = self.mode_var.get()
        self._settings_shuffle = self.shuffle_var.get()
        self._settings_dice = self.dice_quality_var.get()

        if core.is_dice_only_mode(self._settings_mode):
            blocked, loss_bits, msg = False, 0.0, ""
        else:
            blocked, loss_bits, msg = core.shuffle_status(self._settings_shuffle)
        if blocked:
            messagebox.showerror("Re-shuffle required", msg)
            return

        self.mode = self._settings_mode
        self.shuffle_count = self._settings_shuffle
        self.dice_quality = self._settings_dice
        self.target_bits = core.target_bits_for_mode(self.mode)
        self.cards_needed = core.cards_needed_for_mode(self.mode)
        self.shuffle_loss_bits = loss_bits

        self.card_seq = []
        self.dice_seq = []
        self.dnd_throws = []

        if loss_bits >= 10 and not core.is_dice_only_mode(self.mode):
            messagebox.showwarning("Entropy loss estimated", msg)

        if core.is_d6_mode(self.mode):
            self.show_d6_phase()
        elif core.is_dnd_mode(self.mode):
            self.show_dnd_phase()
        else:
            self.show_card_phase()

    # ------------------------------------------------------------------
    # Discounted bit counter (shared by card + dice phases)
    # ------------------------------------------------------------------

    def discounted_bits_so_far(self):
        bits = 0.0
        for i in range(len(self.card_seq)):
            bits += core.card_draw_bits(i)
        for _ in self.dice_seq:
            bits += core.dice_roll_bits(self.dice_quality)
        for _ in self.dnd_throws:
            bits += core.dnd_throw_bits(self.dice_quality)
        return max(0.0, bits - self.shuffle_loss_bits)

    def update_gauge(self, canvas, label_var):
        c = self.C()
        discounted = self.discounted_bits_so_far()
        fraction = discounted / self.target_bits if self.target_bits else 0
        zone = core.zone_for_fraction(fraction)
        zone_color = {"red": c["zone_red"], "orange": c["zone_orange"],
                      "yellow-green": c["zone_yg"], "green": c["zone_green"]}[zone]

        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        canvas.create_rectangle(0, 0, w, h, fill=c["track"], outline="")
        fill_w = min(w, int(w * fraction))
        canvas.create_rectangle(0, 0, fill_w, h, fill=zone_color, outline="")
        for marker_frac in (0.5, 0.85, 1.0):
            x = int(w * marker_frac)
            canvas.create_line(x, 0, x, h, fill=c["marker"], width=1)

        label_var.set(f"{discounted:.1f} / {self.target_bits} bits (discounted estimate) \u2014 zone: {zone}")

    # ------------------------------------------------------------------
    # Phase 1: cards
    # ------------------------------------------------------------------

    def show_card_phase(self):
        self.current_phase_fn = self.show_card_phase
        self.clear_container()
        c = self.C()
        f = self.container
        self.card_buttons = {}

        top = tk.Frame(f)
        top.pack(fill="x", pady=(0, 4))
        header_txt = f"Step 1 \u2014 draw {self.cards_needed} cards in shuffle order"
        if self.mode == "128":
            header_txt += " (any cards \u2014 draw order is what matters)"
        tk.Label(top, text=header_txt, fg=c["fg"],
                 font=("TkDefaultFont", 15, "bold")).pack(side="left")

        if self.mode == "128":
            cards_note = (
                "27 cards are required. 27 draws contribute ~132 discounted bits of "
                "card permutation entropy -- enough to clear the 128-bit target after "
                "shuffle-quality deduction, with no dice needed. Draw any 27 cards in "
                "the order they come off the shuffled deck; draw order is the entropy "
                "source, not which specific cards are drawn."
            )
        else:
            cards_note = (
                "All 52 cards are required (the full deck). A single deck is "
                "mathematically capped at ~216 discounted bits -- about 40 bits short "
                "of the 256-bit target. The dice phase fills that gap from an "
                "independent physical source. Draw all 52 cards in shuffle order before "
                "proceeding to dice."
            )
        tk.Label(f, text=cards_note, fg=c["fg3"], font=("TkDefaultFont", 10),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 8))

        self.card_gauge_label = tk.StringVar()
        gauge_canvas = tk.Canvas(f, width=900, height=16, highlightthickness=0)
        gauge_canvas.pack(anchor="w", pady=(0, 2))
        tk.Label(f, textvariable=self.card_gauge_label, fg=c["fg"], font=("TkDefaultFont", 11)).pack(anchor="w", pady=(0, 2))
        tk.Label(f, text=f"Shuffle-quality deduction applied upfront: {self.shuffle_loss_bits:.1f} bits "
                          f"({self.shuffle_count} shuffles, Bayer-Diaconis bound)",
                 fg=c["fg3"], font=("TkDefaultFont", 10)).pack(anchor="w", pady=(0, 8))
        self._card_gauge_canvas = gauge_canvas

        grid = tk.Frame(f)
        grid.pack(fill="x")
        for suit_name, suit_key, suit_icon in SUITS:
            row_frame = tk.Frame(grid)
            row_frame.pack(anchor="w", pady=2)
            tk.Label(row_frame, text=suit_name, width=10, anchor="w", fg=c["fg"],
                     font=("TkDefaultFont", 11, "bold")).pack(side="left")
            suit_color = SUIT_COLOR[suit_key]
            for rank in RANKS:
                card_id = f"{rank}{suit_key}"
                btn = tk.Button(row_frame, text=f"{rank}{suit_icon}", width=5,
                                 bg=EGGSHELL, fg=suit_color,
                                 activebackground=EGGSHELL, activeforeground=suit_color,
                                 disabledforeground=suit_color,
                                 font=("TkDefaultFont", 12, "bold"),
                                 command=lambda cid=card_id: self.click_card(cid))
                btn.no_theme = True
                btn.pack(side="left", padx=1)
                self.card_buttons[card_id] = btn

        self.card_seq_label = tk.StringVar(value="(no cards drawn yet)")
        tk.Label(f, textvariable=self.card_seq_label, wraplength=900, justify="left",
                 font=("TkDefaultFont", 11), fg=c["fg2"]).pack(anchor="w", pady=(10, 10))

        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w")
        tk.Button(btn_row, text="\u2190 Back to settings", command=self.show_settings_screen).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Undo last", command=self.undo_card).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Reset", command=self.reset_cards).pack(side="left", padx=(0, 6))
        next_phase = self.show_analysis_phase if self.mode == "128" else self.show_dice_phase
        next_label = "Continue to analysis \u2192" if self.mode == "128" else "Continue to dice \u2192"
        self.card_continue_btn = tk.Button(btn_row, text=next_label,
                                            command=next_phase, state="disabled")
        self.card_continue_btn.pack(side="left")

        self.refresh_card_ui()
        self._recolor(f)

    def click_card(self, card_id):
        if self.card_seq.count(card_id) >= 1:
            return
        self.card_seq.append(card_id)
        self.refresh_card_ui()

    def undo_card(self):
        if not self.card_seq:
            return
        self.card_seq.pop()
        self.refresh_card_ui()

    def reset_cards(self):
        self.card_seq = []
        self.refresh_card_ui()

    def refresh_card_ui(self):
        self.update_gauge(self._card_gauge_canvas, self.card_gauge_label)
        if self.card_seq:
            self.card_seq_label.set(" ".join(self.card_seq))
        else:
            self.card_seq_label.set("(no cards drawn yet)")
        self.card_continue_btn.config(state=("normal" if len(self.card_seq) >= self.cards_needed else "disabled"))
        full = len(self.card_seq) >= self.cards_needed
        for cid, btn in self.card_buttons.items():
            if cid in self.card_seq:
                btn.config(state="disabled", relief="sunken", bg=EGGSHELL_USED)
            elif full:
                btn.config(state="disabled", relief="raised", bg=EGGSHELL)
            else:
                btn.config(state="normal", relief="raised", bg=EGGSHELL)

    # ------------------------------------------------------------------
    # Phase 2: dice
    # ------------------------------------------------------------------

    def show_dice_phase(self):
        self.current_phase_fn = self.show_dice_phase
        self.clear_container()
        c = self.C()
        f = self.container

        top = tk.Frame(f)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text="Step 2 \u2014 roll a D6, click the face value", fg=c["fg"],
                 font=("TkDefaultFont", 15, "bold")).pack(side="left")

        tk.Label(f,
                 text=f"Minimum {core.DICE_MIN_ROLLS} rolls required regardless of the entropy gauge. "
                      f"This minimum exists so all five dice statistical tests run with meaningful "
                      f"power -- below {core.DICE_MIN_ROLLS} rolls, one or more tests lack sufficient "
                      f"data and will be skipped entirely, leaving gaps in pattern detection. "
                      f"The entropy gauge may reach 100%% before {core.DICE_MIN_ROLLS} rolls; "
                      f"continue rolling until the minimum is met.",
                 fg=c["fg3"], font=("TkDefaultFont", 10),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 4))

        tk.Label(f,
                 text="Enter each roll exactly as it lands -- do not adjust results to avoid "
                      "repeating values, favor middle numbers (3, 4), or create sequences that "
                      "look random to you. Most common human biases are detected automatically. "
                      "However, a mild preference for middle values may not always be flagged -- "
                      "this is a known limitation at 20 rolls on a 6-faced die, and the safest "
                      "input is whatever comes directly off the die without editing.",
                 fg=c["warn"], font=("TkDefaultFont", 10),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 8))

        self.dice_gauge_label = tk.StringVar()
        gauge_canvas = tk.Canvas(f, width=900, height=16, highlightthickness=0)
        gauge_canvas.pack(anchor="w", pady=(0, 2))
        tk.Label(f, textvariable=self.dice_gauge_label, fg=c["fg"], font=("TkDefaultFont", 11)).pack(anchor="w", pady=(0, 4))
        self._dice_gauge_canvas = gauge_canvas

        # Roll counter — shows n / DICE_MIN_ROLLS, turns green once minimum met
        self.dice_count_var = tk.StringVar()
        self.dice_count_label = tk.Label(f, textvariable=self.dice_count_var,
                                          font=("TkDefaultFont", 11, "bold"), fg=c["fg"])
        self.dice_count_label.pack(anchor="w", pady=(0, 8))

        dice_row = tk.Frame(f)
        dice_row.pack(anchor="w", pady=(0, 10))
        self.dice_buttons = []
        for val in range(1, 7):
            btn = tk.Button(dice_row, text=str(val), width=5, height=2,
                             command=lambda v=val: self.click_die(v))
            btn.pack(side="left", padx=3)
            self.dice_buttons.append(btn)

        self.dice_log_label = tk.StringVar(value="(no rolls yet)")
        tk.Label(f, textvariable=self.dice_log_label, wraplength=900, justify="left",
                 font=("TkDefaultFont", 11), fg=c["fg2"]).pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w")
        tk.Button(btn_row, text="Undo last", command=self.undo_die).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="\u2190 Back to cards", command=self.show_card_phase).pack(side="left", padx=(0, 6))
        self.dice_continue_btn = tk.Button(btn_row, text="Continue to analysis \u2192",
                                            command=self.show_analysis_phase, state="disabled")
        self.dice_continue_btn.pack(side="left")

        self.refresh_dice_ui()
        self._recolor(f)

    def click_die(self, val):
        self.dice_seq.append(val)
        self.refresh_dice_ui()

    def undo_die(self):
        if self.dice_seq:
            self.dice_seq.pop()
        self.refresh_dice_ui()

    def refresh_dice_ui(self):
        c = self.C()
        self.update_gauge(self._dice_gauge_canvas, self.dice_gauge_label)
        n = len(self.dice_seq)
        self.dice_log_label.set(" ".join(str(d) for d in self.dice_seq) if self.dice_seq else "(no rolls yet)")
        fraction = self.discounted_bits_so_far() / self.target_bits if self.target_bits else 0
        gauge_met = fraction >= 1.0
        minimum_met = n >= core.DICE_MIN_ROLLS
        can_continue = gauge_met and minimum_met

        # Roll counter: red while below minimum, green once met
        if minimum_met:
            self.dice_count_var.set(f"Rolls: {n} \u2014 minimum met \u2713")
            self.dice_count_label.config(fg=c["pass_color"])
        else:
            remaining = core.DICE_MIN_ROLLS - n
            self.dice_count_var.set(f"Rolls: {n} / {core.DICE_MIN_ROLLS} minimum  ({remaining} more needed)")
            self.dice_count_label.config(fg=c["fail_color"])

        self.dice_continue_btn.config(state=("normal" if can_continue else "disabled"))
        for btn in self.dice_buttons:
            btn.config(state=("disabled" if can_continue else "normal"))

    # ------------------------------------------------------------------
    # Phase 2b: D6-only dice phase
    # ------------------------------------------------------------------

    def show_d6_phase(self):
        self.current_phase_fn = self.show_d6_phase
        self.clear_container()
        c = self.C()
        f = self.container

        # Dice-per-throw: persisted so changing it mid-session doesn't reset state
        if not hasattr(self, '_d6_dice_per_throw'):
            self._d6_dice_per_throw = 5

        min_groups = core.d6_min_groups(self.mode)

        tk.Label(f, text="D6 Dice \u2014 click each face value after rolling",
                 fg=c["fg"], font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 4))

        # Dice-per-throw selector
        sel_row = tk.Frame(f)
        sel_row.pack(anchor="w", pady=(0, 6))
        tk.Label(sel_row, text="Dice per throw:", fg=c["fg"],
                 font=("TkDefaultFont", 11)).pack(side="left", padx=(0, 8))
        self._d6_dpt_var = tk.IntVar(value=self._d6_dice_per_throw)
        for n in range(1, 13):
            rb = tk.Radiobutton(sel_row, text=str(n), variable=self._d6_dpt_var, value=n,
                                font=("TkDefaultFont", 10),
                                command=self._d6_on_dpt_change)
            rb.pack(side="left", padx=2)

        self._d6_desc_var = tk.StringVar()
        tk.Label(f, textvariable=self._d6_desc_var, fg=c["fg3"],
                 font=("TkDefaultFont", 10),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 6))

        # Entropy gauge
        self.d6_gauge_label = tk.StringVar()
        gauge_canvas = tk.Canvas(f, width=900, height=16, highlightthickness=0)
        gauge_canvas.pack(anchor="w", pady=(0, 2))
        tk.Label(f, textvariable=self.d6_gauge_label, fg=c["fg"],
                 font=("TkDefaultFont", 11)).pack(anchor="w", pady=(0, 4))
        self._d6_gauge_canvas = gauge_canvas

        # Progress tracker
        self._d6_progress_var = tk.StringVar()
        self._d6_progress_lbl = tk.Label(f, textvariable=self._d6_progress_var,
                                          font=("TkDefaultFont", 11, "bold"), fg=c["fg"])
        self._d6_progress_lbl.pack(anchor="w", pady=(0, 8))

        # Die canvas frame — rebuilt dynamically when dpt changes
        self._d6_canvas_frame = tk.Frame(f)
        self._d6_canvas_frame.pack(anchor="w", pady=(0, 6))
        self._d6_die_canvases = []

        # Face value buttons
        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w", pady=(0, 8))
        self._d6_face_btns = []
        for val in range(1, 7):
            btn = tk.Button(btn_row, text=str(val), width=6, height=2,
                             font=("TkDefaultFont", 14, "bold"),
                             command=lambda v=val: self._d6_click(v))
            btn.pack(side="left", padx=4)
            self._d6_face_btns.append(btn)

        # Group log
        self._d6_log_var = tk.StringVar(value="(no rolls yet)")
        tk.Label(f, text="Completed groups:", fg=c["fg"],
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        tk.Label(f, textvariable=self._d6_log_var, wraplength=1020, justify="left",
                 font=("TkFixedFont", 11), fg=c["fg2"]).pack(anchor="w", pady=(0, 10))

        nav = tk.Frame(f)
        nav.pack(anchor="w")
        tk.Button(nav, text="\u2190 Back to settings",
                  command=self.show_settings_screen).pack(side="left", padx=(0, 6))
        tk.Button(nav, text="Undo last group",
                  command=self._d6_undo_group).pack(side="left", padx=(0, 6))
        tk.Button(nav, text="Undo last roll",
                  command=self._d6_undo_roll).pack(side="left", padx=(0, 6))
        self._d6_continue_btn = tk.Button(
            nav, text="Continue to analysis \u2192",
            command=self.show_analysis_phase, state="disabled")
        self._d6_continue_btn.pack(side="left")

        # Current in-progress group
        self._d6_current_group = []
        self._d6_rebuild_canvases()
        self._refresh_d6_ui()
        self._recolor(f)

    def _d6_on_dpt_change(self):
        """User changed dice-per-throw. Commit any in-progress group first."""
        new_dpt = self._d6_dpt_var.get()
        if self._d6_current_group:
            # Discard the partial group — user changed group size mid-group
            self._d6_current_group = []
        self._d6_dice_per_throw = new_dpt
        self._d6_rebuild_canvases()
        self._refresh_d6_ui()

    def _d6_rebuild_canvases(self):
        """Rebuild die canvas widgets to match current dice-per-throw."""
        c = self.C()
        for w in self._d6_canvas_frame.winfo_children():
            w.destroy()
        self._d6_die_canvases = []
        dpt = self._d6_dice_per_throw
        for i in range(dpt):
            cv = tk.Canvas(self._d6_canvas_frame, width=70, height=70,
                           highlightthickness=1, highlightbackground=c["fg3"])
            cv.pack(side="left", padx=4)
            self._d6_die_canvases.append(cv)

    def _draw_d6_pip(self, cv, value, bg, fg):
        """Draw a D6 face on a canvas with pips."""
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        cv.configure(bg=bg)
        # Rounded-rect die face
        r = 10
        cv.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=bg, outline=fg)
        cv.create_arc(w-2*r, 0, w, 2*r, start=0, extent=90, fill=bg, outline=fg)
        cv.create_arc(0, h-2*r, 2*r, h, start=180, extent=90, fill=bg, outline=fg)
        cv.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=bg, outline=fg)
        cv.create_rectangle(r, 0, w-r, h, fill=bg, outline="")
        cv.create_rectangle(0, r, w, h-r, fill=bg, outline="")
        cv.create_rectangle(r, r, w-r, h-r, fill=bg, outline="")
        # Outline
        cv.create_line(r, 0, w-r, 0, fill=fg)
        cv.create_line(r, h, w-r, h, fill=fg)
        cv.create_line(0, r, 0, h-r, fill=fg)
        cv.create_line(w, r, w, h-r, fill=fg)
        # Pip positions for faces 1-6
        pip_map = {
            1: [(0.5, 0.5)],
            2: [(0.25, 0.25), (0.75, 0.75)],
            3: [(0.25, 0.25), (0.5, 0.5), (0.75, 0.75)],
            4: [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)],
            5: [(0.25, 0.25), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75), (0.75, 0.75)],
            6: [(0.25, 0.2), (0.75, 0.2), (0.25, 0.5), (0.75, 0.5), (0.25, 0.8), (0.75, 0.8)],
        }
        pr = 5
        for (px, py) in pip_map.get(value, []):
            x, y = int(px * w), int(py * h)
            cv.create_oval(x-pr, y-pr, x+pr, y+pr, fill=fg, outline="")

    def _refresh_d6_ui(self):
        c = self.C()
        self.update_gauge(self._d6_gauge_canvas, self.d6_gauge_label)
        dpt = self._d6_dice_per_throw
        min_groups = core.d6_min_groups(self.mode)
        min_rolls = min_groups * dpt
        completed_groups = len(self.dice_seq) // dpt
        remaining_groups = max(0, min_groups - completed_groups)
        total_rolls = len(self.dice_seq) + len(self._d6_current_group)
        current_in_group = len(self._d6_current_group)

        # Update description text
        self._d6_desc_var.set(
            f"Rolling {dpt} dice per throw. Minimum {min_groups} groups "
            f"({min_rolls} rolls) required. Enter rolls exactly as they land.")

        # Progress tracker
        gauge_met = self.discounted_bits_so_far() >= self.target_bits
        minimum_met = completed_groups >= min_groups
        if minimum_met and gauge_met:
            self._d6_progress_var.set(
                f"Groups complete: {completed_groups}/{min_groups} \u2713  "
                f"Rolls: {len(self.dice_seq)}  \u2014  minimum met, entropy target reached")
            self._d6_progress_lbl.config(fg=c["pass_color"])
        else:
            self._d6_progress_var.set(
                f"Groups complete: {completed_groups}/{min_groups}  "
                f"({remaining_groups} remaining)  \u2014  "
                f"Rolls in current group: {current_in_group}/{dpt}  \u2014  "
                f"Total rolls: {total_rolls}")
            self._d6_progress_lbl.config(fg=c["fg"])

        # Draw dice canvases for current group
        die_bg = "#f0ead6"
        die_fg = "#141414"
        empty_bg = c["entry_bg"]
        for i, cv in enumerate(self._d6_die_canvases):
            if i < len(self._d6_current_group):
                self._draw_d6_pip(cv, self._d6_current_group[i], die_bg, die_fg)
            else:
                cv.delete("all")
                cv.configure(bg=empty_bg)
                cv.create_text(35, 35, text="?", font=("TkDefaultFont", 20, "bold"),
                               fill=c["fg3"])

        # Group log
        if self.dice_seq:
            groups = []
            seq = self.dice_seq[:]
            while seq:
                grp = seq[:dpt]
                seq = seq[dpt:]
                groups.append("[" + " ".join(str(x) for x in grp) + "]")
            self._d6_log_var.set("  ".join(groups))
        else:
            self._d6_log_var.set("(no rolls yet)")

        # Button states
        can_continue = minimum_met and gauge_met and len(self._d6_current_group) == 0
        self._d6_continue_btn.config(state="normal" if can_continue else "disabled")
        group_full = len(self._d6_current_group) >= dpt
        for btn in self._d6_face_btns:
            btn.config(state="disabled" if group_full else "normal")

    def _d6_click(self, val):
        dpt = self._d6_dice_per_throw
        if len(self._d6_current_group) >= dpt:
            return
        self._d6_current_group.append(val)
        if len(self._d6_current_group) == dpt:
            self.dice_seq.extend(self._d6_current_group)
            self._d6_current_group = []
        self._refresh_d6_ui()

    def _d6_undo_roll(self):
        dpt = self._d6_dice_per_throw
        if self._d6_current_group:
            self._d6_current_group.pop()
        elif self.dice_seq:
            self._d6_current_group = list(self.dice_seq[-dpt:])
            self.dice_seq = self.dice_seq[:-dpt]
            self._d6_current_group.pop()
        self._refresh_d6_ui()

    def _d6_undo_group(self):
        dpt = self._d6_dice_per_throw
        self._d6_current_group = []
        if self.dice_seq:
            self.dice_seq = self.dice_seq[:-dpt]
        self._refresh_d6_ui()

    # ------------------------------------------------------------------
    # Phase 2c: DnD dice phase
    # ------------------------------------------------------------------

    def show_dnd_phase(self):
        self.current_phase_fn = self.show_dnd_phase
        self.clear_container()
        c = self.C()
        f = self.container

        min_throws = core.dnd_min_throws(self.mode)

        tk.Label(f, text="DnD Dice \u2014 D4 / D6 / D8 / D10 / D12 / D20",
                 fg=c["fg"], font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text=f"Minimum {min_throws} complete throws required. Each throw: click one "
                      f"face value per die column in order (D4 first, D20 last). All 6 must "
                      f"be selected before the throw is committed. D10 face shows 0 (enter as 0).",
                 fg=c["fg3"], font=("TkDefaultFont", 10),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 6))

        # Entropy gauge
        self.dnd_gauge_label = tk.StringVar()
        gauge_canvas = tk.Canvas(f, width=900, height=16, highlightthickness=0)
        gauge_canvas.pack(anchor="w", pady=(0, 2))
        tk.Label(f, textvariable=self.dnd_gauge_label, fg=c["fg"],
                 font=("TkDefaultFont", 11)).pack(anchor="w", pady=(0, 4))
        self._dnd_gauge_canvas = gauge_canvas

        # Progress tracker
        self._dnd_progress_var = tk.StringVar()
        self._dnd_progress_lbl = tk.Label(f, textvariable=self._dnd_progress_var,
                                           font=("TkDefaultFont", 11, "bold"), fg=c["fg"])
        self._dnd_progress_lbl.pack(anchor="w", pady=(0, 8))

        # Die columns: each column = one die, rows = face value buttons
        # Staging row: one selected value per column (highlighted when chosen)
        die_frame = tk.Frame(f)
        die_frame.pack(anchor="w", pady=(0, 6))

        self._dnd_staging = [None] * 6   # None = not yet chosen for this throw
        self._dnd_col_btns = []           # list of lists
        self._dnd_col_canvases = []       # die graphic per column
        self._dnd_col_sel_labels = []     # selected value label per column

        die_shapes = ["D4", "D6", "D8", "D10", "D12", "D20"]

        for col, (die_name, die_sides) in enumerate(core.DND_DICE):
            col_frame = tk.Frame(die_frame, relief="groove", bd=1)
            col_frame.grid(row=0, column=col, padx=4, sticky="n")

            # Die name header
            tk.Label(col_frame, text=die_name, fg=c["fg"],
                     font=("TkDefaultFont", 11, "bold"), width=7).pack(pady=(4, 0))

            # Die graphic canvas
            cv = tk.Canvas(col_frame, width=60, height=60, highlightthickness=0)
            cv.pack(pady=(2, 2))
            self._dnd_col_canvases.append(cv)

            # Selected value label
            sel_var = tk.StringVar(value="\u2014")
            sel_lbl = tk.Label(col_frame, textvariable=sel_var,
                               font=("TkDefaultFont", 12, "bold"),
                               fg=c["zone_green"], width=5)
            sel_lbl.pack(pady=(0, 4))
            self._dnd_col_sel_labels.append((sel_var, sel_lbl))

            # Face value buttons — D20 splits into two side-by-side sub-columns
            # (faces 1-10 left, 11-20 right) to avoid excessive column height.
            faces = list(range(1, die_sides + 1))
            btns = []
            if die_name == "D20":
                sub_row = tk.Frame(col_frame)
                sub_row.pack(padx=2, pady=(0, 4))
                left_col = tk.Frame(sub_row)
                left_col.pack(side="left", padx=1)
                right_col = tk.Frame(sub_row)
                right_col.pack(side="left", padx=1)
                for face in faces:
                    label = str(face)
                    parent = left_col if face <= 10 else right_col
                    btn = tk.Button(parent, text=label, width=4,
                                     font=("TkDefaultFont", 9),
                                     command=lambda v=face, c2=col: self._dnd_click(c2, v))
                    btn.pack(pady=1)
                    btns.append(btn)
            else:
                btn_col_frame = tk.Frame(col_frame)
                btn_col_frame.pack(padx=2, pady=(0, 4))
                for face in faces:
                    label = "0" if (die_name == "D10" and face == 10) else str(face)
                    btn = tk.Button(btn_col_frame, text=label, width=5,
                                     font=("TkDefaultFont", 9),
                                     command=lambda v=face, c2=col: self._dnd_click(c2, v))
                    btn.pack(pady=1)
                    btns.append(btn)
            self._dnd_col_btns.append(btns)

        # Throw log
        tk.Label(f, text="Completed throws:", fg=c["fg"],
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(6, 0))
        self._dnd_log_var = tk.StringVar(value="(no throws yet)")
        tk.Label(f, textvariable=self._dnd_log_var, wraplength=1020, justify="left",
                 font=("TkFixedFont", 11), fg=c["fg2"]).pack(anchor="w", pady=(0, 10))

        nav = tk.Frame(f)
        nav.pack(anchor="w")
        tk.Button(nav, text="\u2190 Back to settings",
                  command=self.show_settings_screen).pack(side="left", padx=(0, 6))
        tk.Button(nav, text="Undo last throw",
                  command=self._dnd_undo_throw).pack(side="left", padx=(0, 6))
        tk.Button(nav, text="Clear in-progress throw",
                  command=self._dnd_clear_staging).pack(side="left", padx=(0, 6))
        self._dnd_continue_btn = tk.Button(
            nav, text="Continue to analysis \u2192",
            command=self.show_analysis_phase, state="disabled")
        self._dnd_continue_btn.pack(side="left")

        self._refresh_dnd_ui()
        self._recolor(f)

    def _draw_dnd_die(self, cv, die_name, value, selected):
        """Draw a DnD die shape on canvas with face value inside."""
        c = self.C()
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        bg = "#f0ead6" if selected else c["entry_bg"]
        fg_text = "#141414" if selected else c["fg3"]
        fg_line = "#141414" if selected else c["fg3"]
        cv.configure(bg=c["bg"])
        cx, cy = w // 2, h // 2
        s = min(w, h) // 2 - 4

        import math as _math

        def poly(n, radius, offset_angle=0):
            pts = []
            for i in range(n):
                a = _math.radians(offset_angle + i * 360 / n)
                pts += [cx + radius * _math.sin(a), cy - radius * _math.cos(a)]
            return pts

        if die_name == "D4":
            pts = poly(3, s, 0)
            cv.create_polygon(pts, fill=bg, outline=fg_line, width=2)
        elif die_name == "D6":
            cv.create_rectangle(cx-s, cy-s, cx+s, cy+s, fill=bg, outline=fg_line, width=2)
        elif die_name == "D8":
            pts = poly(4, s, 0)
            cv.create_polygon(pts, fill=bg, outline=fg_line, width=2)
        elif die_name == "D10":
            # Elongated diamond
            cv.create_polygon([cx, cy-s, cx+int(s*0.7), cy, cx, cy+s, cx-int(s*0.7), cy],
                               fill=bg, outline=fg_line, width=2)
        elif die_name == "D12":
            pts = poly(5, s, 0)
            cv.create_polygon(pts, fill=bg, outline=fg_line, width=2)
        elif die_name == "D20":
            pts = poly(6, s, 0)
            cv.create_polygon(pts, fill=bg, outline=fg_line, width=2)

        label = ("0" if (die_name == "D10" and value == 10) else (str(value) if value else "?"))
        cv.create_text(cx, cy, text=label,
                       font=("TkDefaultFont", 13, "bold"), fill=fg_text)

    def _refresh_dnd_ui(self):
        c = self.C()
        self.update_gauge(self._dnd_gauge_canvas, self.dnd_gauge_label)
        min_throws = core.dnd_min_throws(self.mode)
        completed = len(self.dnd_throws)
        remaining = max(0, min_throws - completed)
        staging_count = sum(1 for v in self._dnd_staging if v is not None)

        # Progress tracker
        gauge_met = self.discounted_bits_so_far() >= self.target_bits
        minimum_met = completed >= min_throws
        if minimum_met and gauge_met:
            self._dnd_progress_var.set(
                f"Throws complete: {completed}/{min_throws} \u2713  "
                f"\u2014  minimum met, entropy target reached")
            self._dnd_progress_lbl.config(fg=c["pass_color"])
        else:
            self._dnd_progress_var.set(
                f"Throws complete: {completed}/{min_throws}  "
                f"({remaining} remaining)  \u2014  "
                f"Current throw: {staging_count}/6 dice selected")
            self._dnd_progress_lbl.config(fg=c["fg"])

        # Update die graphics and selected value labels
        for col, (die_name, die_sides) in enumerate(core.DND_DICE):
            val = self._dnd_staging[col]
            selected = val is not None
            self._draw_dnd_die(self._dnd_col_canvases[col], die_name,
                               val if selected else None, selected)
            sel_var, sel_lbl = self._dnd_col_sel_labels[col]
            if selected:
                label = "0" if (die_name == "D10" and val == 10) else str(val)
                sel_var.set(label)
                sel_lbl.config(fg=c["zone_green"])
            else:
                sel_var.set("\u2014")
                sel_lbl.config(fg=c["fg3"])
            # Disable column buttons once a value is selected for this throw
            for btn in self._dnd_col_btns[col]:
                btn.config(state="disabled" if selected else "normal")

        # Throw log
        if self.dnd_throws:
            lines = []
            for i, t in enumerate(self.dnd_throws):
                lines.append(f"[{i+1}] " + "  ".join(
                    ("0" if (core.DND_DICE[j][0] == "D10" and v == 10) else str(v))
                    for j, v in enumerate(t)))
            self._dnd_log_var.set("  ".join(lines))
        else:
            self._dnd_log_var.set("(no throws yet)")

        # Continue button
        can_continue = minimum_met and gauge_met and all(v is None for v in self._dnd_staging)
        self._dnd_continue_btn.config(state="normal" if can_continue else "disabled")

    def _dnd_click(self, col, val):
        if self._dnd_staging[col] is not None:
            return  # already selected for this throw
        self._dnd_staging[col] = val
        # Auto-commit when all 6 dice selected
        if all(v is not None for v in self._dnd_staging):
            self.dnd_throws.append(tuple(self._dnd_staging))
            self._dnd_staging = [None] * 6
        self._refresh_dnd_ui()

    def _dnd_clear_staging(self):
        self._dnd_staging = [None] * 6
        self._refresh_dnd_ui()

    def _dnd_undo_throw(self):
        self._dnd_staging = [None] * 6
        if self.dnd_throws:
            self.dnd_throws.pop()
        self._refresh_dnd_ui()

    # ------------------------------------------------------------------
    # Phase 3: symbol-level statistical analysis
    # ------------------------------------------------------------------

    def show_analysis_phase(self):
        self.current_phase_fn = self.show_analysis_phase
        self.clear_container()
        c = self.C()
        f = self.container

        tk.Label(f, text="Step 3 \u2014 statistical analysis (raw physical draws)", fg=c["fg"],
                 font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="Symbol-level tests on the raw card/dice draws, adapted from "
                          "NIST SP 800-22 concepts. Tests run on the physical symbols, not "
                          "the encoded bits, to avoid encoding artifacts. Not a compliance "
                          "claim -- results are indicative, not certifying, especially at "
                          "this input length.",
                 fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=900, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="PASS means no test here caught a problem -- it does not mean the "
                          "input is random. A deliberately patterned sequence can pass every "
                          "test below. These checks catch realistic mistakes (fatigue, "
                          "under-shuffling, accidental patterns), not a determined adversary.",
                 fg=c["warn"], font=("TkDefaultFont", 10, "bold"), wraplength=900, justify="left").pack(anchor="w", pady=(0, 10))

        self.raw_bits = core.raw_entropy_bits(
            self.card_seq, self.dice_seq,
            self.dnd_throws if self.dnd_throws else None)
        results = core.run_symbol_tests(
            self.card_seq, self.dice_seq,
            self.dnd_throws if self.dnd_throws else None)
        tier = core.compute_overall_tier(results)

        tier_colors = {
            "stop": c["fail_color"],
            "caution": c["zone_orange"],
            "limited": c["zone_yg"],
            "full": c["pass_color"],
        }
        tier_frame = tk.Frame(f, bg=c["bg"])
        tier_frame.pack(fill="x", pady=(0, 4))
        tk.Label(tier_frame, text=tier["label"], fg=tier_colors[tier["tier"]],
                 font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        tk.Label(tier_frame, text=tier["reason"], fg=c["fg2"],
                 font=("TkDefaultFont", 10), wraplength=900, justify="left").pack(anchor="w")

        if tier["tier"] in ("stop", "caution"):
            tk.Label(f, text="This is normal and expected. Roughly 1 in 5 perfectly good "
                              "draws gets flagged here \u2014 the tests are deliberately tuned to "
                              "over-warn rather than under-warn, because re-shuffling costs "
                              "you two minutes while a weak seed can cost you everything in "
                              "the wallet, permanently. A flag does not mean you did anything "
                              "wrong. Re-shuffle, re-roll, and start over.",
                     fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=900,
                     justify="left").pack(anchor="w", pady=(0, 10))
        else:
            tk.Label(f, text="Note: roughly 1 in 5 perfectly good draws does get flagged by "
                              "these tests \u2014 they're deliberately tuned to over-warn, since "
                              "re-shuffling is cheap and a weak seed is not. A clean result "
                              "here means nothing was detected, not that randomness is proven.",
                     fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=900,
                     justify="left").pack(anchor="w", pady=(0, 10))

        n_skipped = tier["n_skipped"]
        if n_skipped > 0:
            skipped_names = [r["name"] for r in results if r["level"] == "skipped"]
            tk.Label(f, text=f"{n_skipped} test(s) marked n/a below due to insufficient data "
                              f"(shown as \"n/a\" in the table). In 12-word (128-bit) mode, "
                              f"fewer dice rolls are needed to reach the entropy target, which "
                              f"means some dice tests don't have enough data to produce a "
                              f"meaningful result. This is a real limitation, not a cosmetic "
                              f"one \u2014 those specific checks genuinely did not run.",
                     fg=c["zone_orange"], font=("TkDefaultFont", 10),
                     wraplength=900, justify="left").pack(anchor="w", pady=(0, 10))

        table = tk.Frame(f)
        table.pack(fill="x", pady=(0, 12))
        level_display = {
            "pass": ("PASS", c["pass_color"]),
            "borderline": ("NEAR", c["zone_orange"]),
            "flag": ("FLAG", c["fail_color"]),
            "skipped": ("n/a", c["fg3"]),
        }
        for r in results:
            row = tk.Frame(table)
            row.pack(fill="x", pady=2)
            status, color = level_display[r["level"]]
            tk.Label(row, text=status, fg=color, font=("TkDefaultFont", 11, "bold"), width=5).pack(side="left")
            tk.Label(row, text=r["name"], width=24, anchor="w", fg=c["fg"]).pack(side="left")
            if "expected" in r and r.get("statistic") is not None:
                stat_text = f"obs {r['statistic']} / exp \u2248{r['expected']} (flag>{r['critical']})"
            else:
                stat_text = f"stat: {r['statistic']}"
            tk.Label(row, text=stat_text, width=26, anchor="w",
                     fg=c["fg2"]).pack(side="left")
            tk.Label(row, text=r["note"], anchor="w", fg=c["fg3"],
                     font=("TkDefaultFont", 10), wraplength=440, justify="left").pack(side="left")

        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w")
        if core.is_d6_mode(self.mode):
            back_cmd = self.show_d6_phase
            back_lbl = "\u2190 Back to D6 dice"
        elif core.is_dnd_mode(self.mode):
            back_cmd = self.show_dnd_phase
            back_lbl = "\u2190 Back to DnD dice"
        elif self.mode == "128":
            back_cmd = self.show_card_phase
            back_lbl = "\u2190 Back to cards"
        else:
            back_cmd = self.show_dice_phase
            back_lbl = "\u2190 Back to dice"
        tk.Button(btn_row, text=back_lbl, command=back_cmd).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Start over (re-shuffle)", command=self.restart).pack(side="left", padx=(0, 6))
        # On a STOP tier the continue button is disabled outright rather
        # than merely discouraged -- the whole point of the asymmetric
        # risk posture is that a flagged draw shouldn't be one careless
        # click away from becoming a real wallet. An explicit override
        # is offered separately (below) so the user has to make a
        # deliberate, informed choice rather than clicking past a
        # warning by reflex.
        continue_btn = tk.Button(btn_row, text="Continue to hashing \u2192",
                                  command=self.show_hash_phase)
        continue_btn.pack(side="left")
        if tier["tier"] == "stop":
            continue_btn.config(state="disabled")
            override_row = tk.Frame(f, bg=c["bg"])
            override_row.pack(anchor="w", pady=(10, 0))
            self._override_var = tk.BooleanVar(value=False)

            def _on_override():
                continue_btn.config(state=("normal" if self._override_var.get() else "disabled"))

            tk.Checkbutton(override_row,
                            text="I understand the tests flagged this draw and I choose to continue anyway",
                            variable=self._override_var, command=_on_override,
                            fg=c["warn"], bg=c["bg"], selectcolor=c["entry_bg"],
                            activebackground=c["bg"], activeforeground=c["warn"],
                            font=("TkDefaultFont", 10)).pack(anchor="w")
        self._recolor(f)

    # ------------------------------------------------------------------
    # Phase 4 + 5: hashing, mnemonic, master fingerprint, xpub/ypub/zpub/tpub
    # ------------------------------------------------------------------

    def show_hash_phase(self):
        self.current_phase_fn = self.show_hash_phase
        self.clear_container()
        self._in_hash_phase = True
        c = self.C()

        # Scrollable wrapper -- this screen has grown substantially
        # (master fingerprint, network toggle, 4 xpub standards) and may
        # not fit every screen without scrolling.
        canvas = tk.Canvas(self.container, highlightthickness=0, bg=c["bg"])
        vsb = tk.Scrollbar(self.container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        f = tk.Frame(canvas, bg=c["bg"])
        canvas_window = canvas.create_window((0, 0), window=f, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        f.bind("<Configure>", _on_configure)

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        tk.Label(f, text="Step 4 \u2014 hashing, mnemonic, and key derivation", fg=c["fg"],
                 font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 4))

        tk.Label(f,
                 text="\u26a0  Values on this screen are displayed for verification against "
                      "a second tool only. They cannot be copied or pasted. This app cannot "
                      "prevent OS-level screenshots -- ensure you are in a private physical "
                      "environment before revealing any value. All revealed fields "
                      "automatically re-mask when this window loses focus.",
                 fg=c["warn"], font=("TkDefaultFont", 10, "bold"),
                 wraplength=1020, justify="left").pack(anchor="w", pady=(0, 10))

        try:
            wl_hash = core.wordlist_sha256(WORDLIST_PATH)
            wordlist = core.load_wordlist(WORDLIST_PATH)
        except Exception as e:
            messagebox.showerror("Wordlist error", f"Failed to load wordlist: {e}")
            return

        tk.Label(f, text=f"Wordlist SHA-256: {wl_hash}", font=("TkDefaultFont", 10),
                 fg=c["fg3"]).pack(anchor="w", pady=(0, 10))

        # ---- Pico TRNG pre-whitening injection ----
        # Uses port and enabled flag confirmed during settings scan.
        # XOR happens before SHA-256 whitening -- see settings panel for rationale.
        pico_mixed = False
        raw_bits_to_use = self.raw_bits

        pico_ready = (_PICO_MODULE_AVAILABLE and
                      self._pico_enabled and
                      self._pico_port is not None)

        if pico_ready:
            try:
                raw_byte_len = (len(self.raw_bits) + 7) // 8
                pico_bytes = _pico.get_trng_bytes(raw_byte_len, port=self._pico_port)
                raw_int = int(self.raw_bits, 2)
                raw_byte_val = raw_int.to_bytes(raw_byte_len, "big")
                xored = core.xor_mix_external_source(raw_byte_val, pico_bytes)
                xored_bits = bin(int.from_bytes(xored, "big"))[2:].zfill(raw_byte_len * 8)
                raw_bits_to_use = xored_bits[:len(self.raw_bits)]
                pico_mixed = True
            except Exception as e:
                messagebox.showwarning(
                    "Pico TRNG error",
                    f"Could not read Pico TRNG at {self._pico_port}:\n{e}\n\n"
                    f"Proceeding with card/dice entropy only.")

        if _PICO_MODULE_AVAILABLE:
            if pico_mixed:
                status_text = f"\u2713 Pico TRNG XOR'd into raw bits before whitening ({self._pico_port})"
                status_color = c["pass_color"]
            elif self._pico_enabled and self._pico_port is None:
                status_text = "\u26a0 Pico enabled in settings but no port found -- not mixed in"
                status_color = c["warn"]
            elif not self._pico_enabled:
                status_text = "Pico TRNG not enabled (configure in settings)"
                status_color = c["fg3"]
            else:
                status_text = "Pico TRNG not mixed in"
                status_color = c["fg3"]
            tk.Label(f, text=status_text, font=("TkDefaultFont", 10),
                     fg=status_color).pack(anchor="w", pady=(0, 6))

        entropy_bytes = core.whiten_entropy(raw_bits_to_use, self.target_bits)
        mnemonic = core.entropy_to_mnemonic(entropy_bytes, wordlist)
        self._mnemonic = mnemonic
        self._entropy_hex = entropy_bytes.hex()
        self._checksum_bits = core.bip39_checksum_bits(entropy_bytes)

        # Masked by default -- raw entropy deterministically maps to the
        # mnemonic via the same public algorithm above, so showing it
        # unmasked would defeat the mnemonic's own masking entirely.
        entropy_row = tk.Frame(f, bg=c["bg"])
        entropy_row.pack(anchor="w", pady=(0, 4), fill="x")
        self.entropy_var = tk.StringVar(value="SHA-256 whitened entropy: **** (click to reveal)")
        self._entropy_visible = False
        entropy_lbl = tk.Label(entropy_row, textvariable=self.entropy_var,
                                font=("TkDefaultFont", 11), fg=c["fg"], wraplength=1020, justify="left")
        entropy_lbl.pack(side="left")
        self._entropy_label = entropy_lbl
        tk.Button(entropy_row, text="Show/Hide", command=self._toggle_entropy).pack(side="left", padx=(8, 0))
        tk.Label(f, text="(checksum bits shown alongside entropy above when revealed)",
                 font=("TkDefaultFont", 10), fg=c["fg3"]).pack(anchor="w", pady=(0, 14))
        tk.Label(f, text=f"Mnemonic ({len(mnemonic)} words) \u2014 click each word to reveal it:",
                 font=("TkDefaultFont", 12, "bold"), fg=c["fg"]).pack(anchor="w", pady=(0, 6))

        word_grid = tk.Frame(f, bg=c["bg"])
        word_grid.pack(anchor="w", pady=(0, 4))
        cols = 4
        rows = -(-len(mnemonic) // cols)
        self._word_buttons = []
        for i, word in enumerate(mnemonic):
            col, r = divmod(i, rows)
            btn = tk.Button(word_grid, text=f"{i+1}. ****", width=16, anchor="w")
            btn.grid(row=r, column=col, padx=2, pady=2)
            btn.config(command=lambda b=btn, w=word, idx=i: self._toggle_word(b, w, idx))
            self._word_buttons.append(btn)

        tk.Button(f, text="Mask all words", command=self._mask_all_words).pack(anchor="w", pady=(0, 14))

        # ---- CompactSeedQR (SeedSigner format) -- masked by default for privacy ----
        qr_frame = tk.LabelFrame(f, text="CompactSeedQR (SeedSigner-compatible, encodes raw entropy directly)")
        qr_frame.pack(fill="x", pady=(0, 10))
        tk.Label(qr_frame,
                 text="Hidden by default. The checksum word is implicit and recomputed on "
                      "scan, so only the raw entropy is encoded -- not the mnemonic text.",
                 fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=880, justify="left").pack(anchor="w", padx=8, pady=(6, 4))

        qr_controls = tk.Frame(qr_frame, bg=c["bg"])
        qr_controls.pack(anchor="w", padx=8, pady=(0, 6))
        self.qr_size_var = tk.StringVar(value=str(self._qr_size))
        tk.Radiobutton(qr_controls, text="25\u00d725", variable=self.qr_size_var, value="25",
                        command=self._on_qr_size_change).pack(side="left")
        tk.Radiobutton(qr_controls, text="29\u00d729", variable=self.qr_size_var, value="29",
                        command=self._on_qr_size_change).pack(side="left", padx=(0, 12))
        self.qr_toggle_btn = tk.Button(qr_controls, text="Show QR" if not self._qr_visible else "Hide QR",
                                        command=self._toggle_qr_visibility)
        self.qr_toggle_btn.pack(side="left")
        self.qr_level_var = tk.StringVar(value="")
        tk.Label(qr_controls, textvariable=self.qr_level_var, fg=c["fg3"],
                 font=("TkDefaultFont", 10)).pack(side="left", padx=(10, 0))

        self.qr_canvas = tk.Canvas(qr_frame, highlightthickness=0, bg=c["bg"])
        self.qr_canvas.pack(anchor="w", padx=8, pady=(0, 8))
        self._qr_entropy_bytes = entropy_bytes
        self._redraw_qr()

        # ---- Master fingerprint + wallet seed (auto-computed, no click needed) ----
        # Fingerprint is meant to be shared (used in wallet descriptors), shown
        # unmasked like every wallet does. The seed itself is full spending-
        # capable key material -- masked by default, matching the mnemonic/QR.
        fp_frame = tk.LabelFrame(f, text="Master key (identifies this seed -- same for every derivation path below)")
        fp_frame.pack(fill="x", pady=(0, 10))
        self.root_fp_var = tk.StringVar()
        self._seed_hex = ""
        self._seed_tag = ""
        self._seed_visible = False
        self.seed_var = tk.StringVar(value="Wallet seed: **** (click to reveal)")
        tk.Label(fp_frame, textvariable=self.root_fp_var, font=("TkFixedFont", 12, "bold"),
                 fg=c["fg"]).pack(anchor="w", padx=8, pady=(6, 2))
        seed_row = tk.Frame(fp_frame, bg=c["bg"])
        seed_row.pack(anchor="w", padx=8, pady=(0, 8), fill="x")
        tk.Label(seed_row, textvariable=self.seed_var, font=("TkFixedFont", 10),
                 fg=c["fg2"], wraplength=1020, justify="left").pack(side="left")
        tk.Button(seed_row, text="Show/Hide", command=self._toggle_seed).pack(side="left", padx=(8, 0))

        # ---- Network + passphrase controls ----
        controls = tk.Frame(f, bg=c["bg"])
        controls.pack(fill="x", pady=(0, 10))

        net_frame = tk.LabelFrame(controls, text="Network")
        net_frame.pack(side="left", padx=(0, 10), anchor="n")
        self.network_var = tk.StringVar(value=self.network)
        tk.Radiobutton(net_frame, text="Mainnet", variable=self.network_var, value="mainnet",
                        command=self._on_network_change).pack(anchor="w", padx=8)
        tk.Radiobutton(net_frame, text="Testnet", variable=self.network_var, value="testnet",
                        command=self._on_network_change).pack(anchor="w", padx=8, pady=(0, 4))

        pp_frame = tk.LabelFrame(controls, text="Optional BIP-39 passphrase")
        pp_frame.pack(side="left", fill="x", expand=True, anchor="n")
        tk.Label(pp_frame,
                 text="Does not change the mnemonic words or checksum above -- only the "
                      "seed, master fingerprint, and every xpub/ypub/zpub/tpub below. Press "
                      "\"Derive\" after changing it to update all values.",
                 fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=880, justify="left").pack(anchor="w", padx=8, pady=(4, 4))
        self.passphrase_var = tk.StringVar(value=self._passphrase_text)
        pp_row = tk.Frame(pp_frame, bg=c["bg"])
        pp_row.pack(anchor="w", padx=8, pady=(0, 8))
        pp_entry = tk.Entry(pp_row, textvariable=self.passphrase_var, show="*", width=36)
        pp_entry.pack(side="left", padx=(0, 6))
        self._block_copy(pp_entry)
        tk.Button(pp_row, text="Derive / update all values", command=self._derive_and_refresh).pack(side="left")

        # ---- Extended pubkeys: Legacy / Nested SegWit / Native SegWit / Taproot ----
        xpub_frame = tk.LabelFrame(f, text="Account extended public keys (per BIP-44/49/84/86, SLIP-132)")
        xpub_frame.pack(fill="x", pady=(0, 10))
        self.xpub_name_vars = []
        self.xpub_path_vars = []
        self.xpub_str_vars = []
        for _ in range(4):
            row = tk.Frame(xpub_frame, bg=c["bg"])
            row.pack(fill="x", padx=8, pady=4)
            name_var = tk.StringVar()
            path_var = tk.StringVar()
            str_var = tk.StringVar()
            tk.Label(row, textvariable=name_var, font=("TkDefaultFont", 11, "bold"),
                     fg=c["fg"], anchor="w", width=26).pack(side="left")
            tk.Label(row, textvariable=path_var, font=("TkFixedFont", 11),
                     fg=c["fg2"], anchor="w", width=16).pack(side="left")
            e = tk.Entry(row, textvariable=str_var, font=("TkFixedFont", 11), width=70,
                         state="readonly", readonlybackground=c["entry_bg"], fg=c["fg"])
            e.pack(side="left", fill="x", expand=True, padx=(6, 0))
            self._block_copy(e)
            # Also block text selection entirely on these fields --
            # selection alone doesn't copy but removes the visual cue
            # that copy might be possible.
            e.bind("<Button-1>", lambda ev: "break")
            e.bind("<B1-Motion>", lambda ev: "break")
            self.xpub_name_vars.append(name_var)
            self.xpub_path_vars.append(path_var)
            self.xpub_str_vars.append(str_var)

        tk.Label(f, text="Compatible with SeedSigner's Xpub export screens and Sparrow's "
                          "\"Export Xpub\" / cosigner-add flow. Values are displayed for "
                          "visual cross-check against an independent tool only -- "
                          "copy/paste is intentionally disabled on this screen.",
                 fg=c["fg3"], font=("TkDefaultFont", 10), wraplength=1120, justify="left").pack(anchor="w", pady=(0, 10))

        tk.Label(f, text="This tool is not certified by NIST and makes no compliance claims. "
                          "Verify offline operation before use. Not responsible for loss of funds. "
                          "MIT License \u2014 open source, provided as-is.",
                 fg=c["warn"], font=("TkDefaultFont", 10), wraplength=1120, justify="left").pack(anchor="w", pady=(10, 6))

        # ---- Entropy Quality Estimator panel (shown only when toggle is on) ----
        # Runs on the RAW card/dice bit stream BEFORE SHA-256 whitening.
        # raw_bits is a binary string of 6-bit card symbols + 3-bit dice symbols.
        # Converting to bytes gives the estimator the actual source material to
        # test, not the conditioned output — SHA-256 would pass every test trivially.
        if self._run_estimator and _ESTIMATOR_AVAILABLE:
            self._est_outer = tk.LabelFrame(f, text="Entropy Quality Report (pre-whitening source)")
            self._est_outer.pack(fill="x", pady=(0, 10))
            self._est_status_var = tk.StringVar(value="Running entropy quality tests on raw card/dice stream…")
            tk.Label(self._est_outer, textvariable=self._est_status_var,
                     fg=c["fg2"], font=("TkDefaultFont", 10),
                     wraplength=1020, justify="left").pack(anchor="w", padx=8, pady=(6, 2))
            self._est_detail_frame = tk.Frame(self._est_outer, bg=c["bg"])
            self._est_detail_frame.pack(fill="x", padx=8, pady=(0, 6))
            self._est_report_text = tk.StringVar(value="")
            self._est_expanded = False
            self._est_toggle_btn = tk.Button(
                self._est_outer, text="Show detail ▼",
                command=self._toggle_est_detail, state="disabled")
            self._est_toggle_btn.pack(anchor="w", padx=8, pady=(0, 6))

            # Convert raw bit string → bytes for the estimator.
            # Use raw_bits_to_use (post-Pico-XOR if applied) so the
            # quality report reflects the actual pre-whitening input.
            raw_str = raw_bits_to_use
            pad = (8 - len(raw_str) % 8) % 8
            raw_bytes_for_est = int(raw_str + "0" * pad, 2).to_bytes(
                (len(raw_str) + pad) // 8, "big")

            import threading as _threading
            import math as _math

            # For dice-only modes the byte-level estimator is unreliable:
            # the 3-bit D6 encoding packs into bytes with structural bias
            # (only 6 of 8 bit patterns used per 3-bit group), and at the
            # roll counts used here the MCV min-entropy test either skips
            # (n < 1000 bytes) or returns pessimistic estimates dominated
            # by the encoding geometry rather than the physical randomness.
            # The correct sufficiency metric for D6-only is direct:
            #   source_entropy = n_rolls * log2(6)
            # Similarly for DnD: source_entropy = n_throws * log2(product of sides)
            # These are computed here and override the estimator's byte-level check.
            _dice_only_entropy = None
            _dice_only_label   = None
            if core.is_d6_mode(self.mode):
                n_rolls = len(self.dice_seq)
                _dice_only_entropy = n_rolls * _math.log2(6)
                _dice_only_label = (f"n_rolls({n_rolls}) × log₂(6) = "
                                    f"{_dice_only_entropy:.1f} bits (theoretical D6 entropy)")
            elif core.is_dnd_mode(self.mode):
                n_throws = len(self.dnd_throws)
                bits_per_throw = _math.log2(4*6*8*10*12*20)
                _dice_only_entropy = n_throws * bits_per_throw
                _dice_only_label = (f"n_throws({n_throws}) × log₂(460800) = "
                                    f"{_dice_only_entropy:.1f} bits (theoretical DnD entropy)")

            def _est_worker(rb=raw_bytes_for_est, tgt=self.target_bits,
                            doe=_dice_only_entropy, dol=_dice_only_label):
                try:
                    report = _entropy_estimate(rb, source_label="card-dice-raw")
                    txt = _render_report(report, verbose=True)
                    verdict = report["verdict_label"]
                    eff = report["effective_bits"]
                    theo = report["theoretical_bits"]

                    # Sufficiency check: does pre-whitening source entropy
                    # meet the seed's claimed target?
                    # Dice-only modes: use theoretical formula, not byte-level estimator.
                    # Card modes: use min-entropy if available, fall back to effective_bits.
                    if doe is not None:
                        source_entropy = doe
                        metric_label   = dol
                    else:
                        min_h_result = next(
                            (t for t in report["tests"]
                             if t["name"].startswith("Min-entropy")
                             and t["statistic"] is not None), None)
                        n_bytes = report["n_bytes"]
                        if min_h_result:
                            source_entropy = min_h_result["statistic"] * n_bytes
                            metric_label = (f"H_min({min_h_result['statistic']:.4f} "
                                            f"bits/byte) × {n_bytes} bytes")
                        else:
                            source_entropy = eff
                            metric_label = f"effective bits estimate ({eff})"

                    sufficient = source_entropy >= tgt
                    shortfall  = max(0.0, tgt - source_entropy)

                    summary = (f"{verdict}  |  {eff}/{theo} effective bits  |  "
                               f"{report['n_flag']} flag  {report['n_borderline']} warn  "
                               f"{report['n_skipped']} skipped")
                    self.root.after(0, lambda: self._est_done(
                        summary, txt, sufficient, source_entropy, tgt,
                        shortfall, metric_label))
                except Exception as e:
                    self.root.after(0, lambda: self._est_status_var.set(f"Estimator error: {e}"))
            _threading.Thread(target=_est_worker, daemon=True).start()

        btn_row = tk.Frame(f, bg=c["bg"])
        btn_row.pack(anchor="w", pady=(0, 10))
        tk.Button(btn_row, text="\u2190 Back to analysis", command=self.show_analysis_phase).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Start over", command=self.restart).pack(side="left")

        self._derive_and_refresh()
        self._recolor(f)

    def _toggle_word(self, btn, word, idx):
        """Reveal on first click, re-mask on second click."""
        if btn["text"].endswith("****"):
            btn.config(text=f"{idx+1}. {word}")
        else:
            btn.config(text=f"{idx+1}. ****")

    def _est_done(self, summary: str, detail_text: str,
                  sufficient: bool = True, source_entropy: float = 0.0,
                  target: int = 256, shortfall: float = 0.0,
                  metric_label: str = ""):
        """Called on main thread when the estimator background thread finishes."""
        c = self.C()
        self._est_status_var.set(summary)
        self._est_report_text.set(detail_text)
        self._est_toggle_btn.config(state="normal")

        # Sufficiency banner — inserted between status label and toggle button.
        # Packed before the toggle button; widget insertion order controls position.
        if sufficient:
            banner_text = (
                f"✓  SOURCE ENTROPY SUFFICIENT  —  "
                f"{source_entropy:.1f} bits estimated ≥ {target}-bit target  "
                f"({metric_label}). "
                f"SHA-256 whitening output genuinely contains the claimed entropy.")
            banner_fg = c.get("pass_color", "#4caf50")
        else:
            banner_text = (
                f"✗  SOURCE ENTROPY SHORTFALL  —  "
                f"{source_entropy:.1f} bits estimated < {target}-bit target  "
                f"(shortfall: {shortfall:.1f} bits, {metric_label}). "
                f"The {target}-bit seed phrase overstates actual security. "
                f"Extend your card/dice draws before trusting this seed with funds.")
            banner_fg = c.get("fail_color", "#f44336")

        banner = tk.Label(
            self._est_outer,
            text=banner_text,
            fg=banner_fg,
            bg=c["bg"],
            font=("TkDefaultFont", 10, "bold"),
            wraplength=1020,
            justify="left",
            anchor="w")
        # Insert before toggle button (pack order: status → banner → detail_frame → toggle)
        banner.pack(anchor="w", padx=8, pady=(2, 6),
                    before=self._est_toggle_btn)
        self._recolor(self._est_outer)

    def _toggle_est_detail(self):
        """Expand / collapse the full report text."""
        c = self.C()
        if self._est_expanded:
            for w in self._est_detail_frame.winfo_children():
                w.destroy()
            self._est_toggle_btn.config(text="Show detail ▼")
            self._est_expanded = False
        else:
            txt = self._est_report_text.get()
            lbl = tk.Label(self._est_detail_frame, text=txt,
                           font=("TkFixedFont", 9), fg=c["fg2"], bg=c["bg"],
                           justify="left", anchor="w", wraplength=1020)
            lbl.pack(anchor="w", fill="x")
            self._est_toggle_btn.config(text="Hide detail ▲")
            self._est_expanded = True
        self._recolor(self._est_detail_frame)

    def _mask_all_words(self):
        for i, btn in enumerate(self._word_buttons):
            btn.config(text=f"{i+1}. ****")

    def _toggle_entropy(self):
        self._entropy_visible = not self._entropy_visible
        if self._entropy_visible:
            self.entropy_var.set(
                f"SHA-256 whitened entropy: {self._entropy_hex}\n"
                f"BIP-39 checksum bits (separate SHA-256 call): {self._checksum_bits}"
            )
        else:
            self.entropy_var.set("SHA-256 whitened entropy: **** (click to reveal)")

    def _toggle_qr_visibility(self):
        self._qr_visible = not self._qr_visible
        self.qr_toggle_btn.config(text="Hide QR" if self._qr_visible else "Show QR")
        self._redraw_qr()

    def _on_qr_size_change(self):
        self._qr_size = int(self.qr_size_var.get())
        self._redraw_qr()

    def _redraw_qr(self):
        c = self.C()
        canvas = self.qr_canvas
        canvas.delete("all")

        if not self._qr_visible:
            side = 180
            canvas.config(width=side, height=side)
            canvas.create_rectangle(0, 0, side, side, fill=c["entry_bg"], outline=c["fg3"])
            canvas.create_text(side / 2, side / 2, fill=c["fg3"], width=side - 20,
                                justify="center", font=("TkDefaultFont", 11),
                                text="QR hidden for privacy\nclick \"Show QR\" to reveal")
            self.qr_level_var.set("")
            return

        try:
            matrix, level = core.build_compact_seedqr_matrix(self._qr_entropy_bytes, self._qr_size)
        except Exception as e:
            side = 260
            canvas.config(width=side, height=60)
            canvas.create_text(10, 30, anchor="w", fill=c["fail_color"],
                                font=("TkDefaultFont", 11), width=side - 20,
                                text=f"QR generation error: {e}")
            self.qr_level_var.set("")
            return

        module_px = 8
        quiet = 4
        size = self._qr_size
        total = (size + 2 * quiet) * module_px
        canvas.config(width=total, height=total)
        canvas.create_rectangle(0, 0, total, total, fill="white", outline="")
        for r, row in enumerate(matrix):
            for col, val in enumerate(row):
                if val:
                    x0 = (quiet + col) * module_px
                    y0 = (quiet + r) * module_px
                    canvas.create_rectangle(x0, y0, x0 + module_px, y0 + module_px,
                                             fill="black", outline="")
        self.qr_level_var.set(f"Error correction: {level.upper()} ({size}x{size}, "
                               f"{len(self._qr_entropy_bytes)} bytes encoded)")

    def _on_network_change(self):
        self.network = self.network_var.get()
        self._derive_and_refresh()

    def _derive_and_refresh(self):
        passphrase = self.passphrase_var.get()
        self._passphrase_text = passphrase
        seed = core.mnemonic_to_seed(self._mnemonic, passphrase)

        fingerprint = core.bip32_master_fingerprint(seed)
        self.root_fp_var.set(f"Master fingerprint (m): {fingerprint}")
        self._seed_hex = seed.hex()
        self._seed_tag = "with passphrase" if passphrase else "no passphrase"
        self._refresh_seed_display()

        xpubs = core.all_account_xpubs(seed, self.network)
        for i, x in enumerate(xpubs):
            self.xpub_name_vars[i].set(x["name"])
            self.xpub_path_vars[i].set(x["path"])
            self.xpub_str_vars[i].set(x["xpub"])

    def _refresh_seed_display(self):
        if self._seed_visible:
            self.seed_var.set(
                f"BIP-39 wallet seed ({self._seed_tag}, PBKDF2-HMAC-SHA512): {self._seed_hex}"
            )
        else:
            self.seed_var.set("Wallet seed: **** (click to reveal)")

    def _toggle_seed(self):
        self._seed_visible = not self._seed_visible
        self._refresh_seed_display()

    def restart(self):
        self.card_seq = []
        self.dice_seq = []
        self.dnd_throws = []
        self._d6_dice_per_throw = 5
        # Clear all persisted session state, not just cards/dice -- a
        # stale passphrase silently carrying over into a NEW seed's
        # derivation would be a real footgun, and "hidden by default"
        # for the QR should hold for every new session, not just the
        # first one.
        self._passphrase_text = ""
        self._qr_visible = False
        self.network = "mainnet"
        self._mnemonic = None
        self._qr_entropy_bytes = None
        self._entropy_hex = ""
        self._checksum_bits = ""
        self._seed_hex = ""
        self._seed_tag = ""
        self.show_settings_screen()
        self.apply_theme()


def main():
    if not os.path.exists(WORDLIST_PATH):
        print(f"ERROR: wordlist not found at {WORDLIST_PATH}", file=sys.stderr)
        sys.exit(1)
    root = tk.Tk()
    EntropyGenApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
