"""Reusable Tk pieces: a sortable table with a right-click menu and CSV export."""

import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class DataTable(ttk.Frame):
    """Treeview with scrollbars, click-to-sort headers, right-click actions and CSV export.

    columns: [(key, heading, width)]. Rows carry a payload (the source record) so actions can act
    on what was selected without parsing display text.
    """

    def __init__(self, parent, columns, height=10, menu_items=None, on_double_click=None, tags=None):
        super().__init__(parent)
        self.columns = columns
        self.payloads = {}
        self._sort = (None, False)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings",
                                 height=height, selectmode="extended")
        for key, title, width in columns:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor="w")
        for tag, options in (tags or {}).items():
            self.tree.tag_configure(tag, **options)
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.menu = tk.Menu(self, tearoff=0)
        for label, callback in (menu_items or []):
            self.menu.add_command(label=label, command=callback)
        if menu_items:
            for button in ("<Button-3>", "<Button-2>"):  # right-click; middle on macOS trackpads
                self.tree.bind(button, self._popup)
        if on_double_click:
            self.tree.bind("<Double-1>", lambda e: on_double_click())
        self.tree.bind("<Control-a>", lambda e: self.tree.selection_set(self.tree.get_children()) or "break")

    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.payloads.clear()

    def add_row(self, iid, values, payload=None, tag="", at_top=False):
        if self.tree.exists(iid):
            self.tree.item(iid, values=values, tags=(tag,) if tag else ())
        else:
            self.tree.insert("", 0 if at_top else "end", iid=iid, values=values, tags=(tag,) if tag else ())
        self.payloads[iid] = payload

    def set_rows(self, rows):
        """rows: [(iid, values, payload, tag)]"""
        self.clear()
        for iid, values, payload, tag in rows:
            self.add_row(iid, values, payload, tag)

    def count(self):
        return len(self.tree.get_children())

    def selected(self):
        """Payloads of the selected rows."""
        return [self.payloads[i] for i in self.tree.selection() if i in self.payloads]

    def selected_cells(self, key):
        index = [c[0] for c in self.columns].index(key)
        return [self.tree.item(i)["values"][index] for i in self.tree.selection()]

    def all_values(self):
        return [list(self.tree.item(i)["values"]) for i in self.tree.get_children()]

    def sort_by(self, key):
        descending = self._sort == (key, False)
        index = [c[0] for c in self.columns].index(key)

        def sort_key(iid):
            value = str(self.tree.set(iid, key))
            try:
                return (0, float(value), "")
            except ValueError:
                return (1, 0.0, value.lower())

        for pos, iid in enumerate(sorted(self.tree.get_children(), key=sort_key, reverse=descending)):
            self.tree.move(iid, "", pos)
        self._sort = (key, descending)
        arrow = " ▼" if descending else " ▲"
        for k, title, _ in self.columns:
            self.tree.heading(k, text=title + (arrow if k == key else ""))

    def export_csv(self, default_name="export.csv"):
        rows = self.all_values()
        if not rows:
            messagebox.showinfo("Export", "There is nothing to export yet.")
            return None
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default_name,
                                            filetypes=[("CSV (opens in Excel)", "*.csv")])
        if not path:
            return None
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([c[1] for c in self.columns])
            writer.writerows(rows)
        messagebox.showinfo("Export", f"Saved {len(rows)} rows to:\n{path}")
        return path


def copy_to_clipboard(widget, text):
    widget.clipboard_clear()
    widget.clipboard_append(text)
