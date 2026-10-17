"""Desktop window for non-technical users. Logic lives in jobs.py, db.py and verifier.py;
this file is layout and threading only."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config, jobs
from . import regions as geo
from .gui_widgets import DataTable, copy_to_clipboard
from .hunter import HunterClient, HunterError, InvalidKey
from .verifier import build_plan

STATUS_FILTERS = {
    "Any status": None,
    "Verified (valid)": "valid",
    "Not checked yet": "unchecked",
    "Invalid": "invalid",
    "Accept-all (risky)": "accept_all",
    "Webmail (can't be confirmed)": "webmail",
    "Skipped: unlikely real": "filtered",
    "Unknown": "unknown",
}
DB_HELP = (
    "Leads and verified emails are stored in MongoDB.\n\n"
    "• Local: install MongoDB Community Edition on this computer and keep the default address "
    "(mongodb://localhost:27017).\n"
    "• Cloud: create a free cluster at mongodb.com/atlas and paste its connection string "
    "(mongodb+srv://...) here. Your whole team can then share one database."
)


COUNTRY_NAMES = [c["name"] for c in geo.countries()]
COUNTRY_BY_NAME = {c["name"]: c["code"] for c in geo.countries()}
ENTIRE_COUNTRY = "Entire country (sample)"


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def email_summary(lead):
    return "; ".join(f"{e['address']} ({e['status']})" for e in lead.get("emails", []))


def debounce(widget, state, delay, fn):
    if state.get("job"):
        widget.after_cancel(state["job"])
    state["job"] = widget.after(delay, fn)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SKrapkin")
        self.geometry("1000x720")
        self.minsize(820, 600)
        self.report_callback_exception = lambda exc, val, tb: self.show_error(val)
        self.cfg = config.Config.load()
        self.db = None
        self.events = queue.Queue()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.find_tab = FindTab(self)
        self.leads_tab = LeadsTab(self)
        self.verify_tab = VerifyTab(self)
        self.verified_tab = VerifiedTab(self)
        self.settings_tab = SettingsTab(self)
        for tab, title in ((self.find_tab, "Find Leads"), (self.leads_tab, "Leads"),
                           (self.verify_tab, "Verify Emails"), (self.verified_tab, "Verified Results"),
                           (self.settings_tab, "Settings")):
            self.nb.add(tab, text=title)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        self.db_status = ttk.Label(self, text="Database: connecting...", anchor="w")
        self.db_status.pack(fill="x", padx=12, pady=4)
        self.after(100, self._drain)
        self.connect_db()

    # threading ----------------------------------------------------------

    def post(self, fn):
        """Queue a callable to run on the UI thread. Safe to call from any thread."""
        self.events.put(fn)

    def run_bg(self, fn, ok=None, err=None):
        def work():
            try:
                result = fn()
            except Exception as e:
                self.post(lambda e=e: (err or self.show_error)(e))
                return
            if ok:
                self.post(lambda: ok(result))
        threading.Thread(target=work, daemon=True).start()

    def _drain(self):
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def show_error(self, error):
        messagebox.showerror("SKrapkin", f"Something went wrong: {error}")

    # database -----------------------------------------------------------

    def connect_db(self, on_result=None):
        self.db_status.config(text="Database: connecting...")

        def ok(db):
            if self.db:
                self.db.close()
            self.db = db
            self.db_status.config(text=f"Database: connected ({self.cfg.db_name})")
            self.refresh_data()
            if on_result:
                on_result(None)

        def fail(error):
            self.db = None
            self.db_status.config(text="Database: not connected. Find Leads still saves CSV files; "
                                       "open Settings to connect MongoDB.")
            if on_result:
                on_result(error)

        self.run_bg(lambda: jobs.connect_db(self.cfg), ok=ok, err=fail)

    def require_db(self):
        if self.db is None:
            messagebox.showwarning("Database not connected",
                                   "Connect to MongoDB first (Settings tab).")
            return False
        return True

    def refresh_data(self):
        self.leads_tab.refresh()
        self.verified_tab.refresh()

    def _tab_changed(self, _event):
        tab = self.nametowidget(self.nb.select())
        if hasattr(tab, "on_show"):
            tab.on_show()


class Filters(ttk.Frame):
    """Search box plus category/country/region/status dropdowns that re-run a query as you type."""

    def __init__(self, parent, on_change, with_status=False):
        super().__init__(parent)
        self.on_change, self._debounce = on_change, {}
        ttk.Label(self, text="Search").pack(side="left")
        self.text = ttk.Entry(self, width=26)
        self.text.pack(side="left", padx=(4, 10))
        self.text.bind("<KeyRelease>", lambda e: debounce(self, self._debounce, 300, on_change))
        self.category = self._combo(["All types"] + list(jobs.CATEGORY_LABELS), 24)
        self.country = self._combo(["All countries"] + COUNTRY_NAMES, 20)
        self.country.bind("<<ComboboxSelected>>", lambda e: self._country_changed())
        self.region = self._combo(["All regions"], 18)
        self.status = self._combo(list(STATUS_FILTERS), 24) if with_status else None

    def _country_changed(self):
        code = COUNTRY_BY_NAME.get(self.country.get())
        names = [r["name"] for r in geo.regions(code)] if code else []
        self.region.config(values=["All regions"] + names)
        self.region.current(0)
        self.on_change()

    def _combo(self, values, width):
        box = ttk.Combobox(self, state="readonly", values=values, width=width)
        box.current(0)
        box.pack(side="left", padx=4)
        box.bind("<<ComboboxSelected>>", lambda e: self.on_change())
        return box

    def query(self):
        category = jobs.CATEGORY_LABELS.get(self.category.get())
        country = COUNTRY_BY_NAME.get(self.country.get())
        region = self.region.get() if self.region.get() != "All regions" else None
        status = STATUS_FILTERS.get(self.status.get()) if self.status else None
        return self.text.get(), category, country, region, status


# ------------------------------------------------------------------------------------------------
class FindTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.nb)
        self.app = app
        self.stop_flag = threading.Event()
        self.results_path = None
        self.found = self.with_email = 0
        pad = {"padx": 10, "pady": 4}

        form = ttk.LabelFrame(self, text="1. What are you looking for?")
        form.pack(fill="x", padx=10, pady=(10, 4))
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Type of business").grid(row=0, column=0, sticky="w", **pad)
        self.category = ttk.Combobox(form, state="readonly", values=list(jobs.CATEGORY_LABELS))
        self.category.current(0)
        self.category.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(form, text="Country").grid(row=1, column=0, sticky="w", **pad)
        self.country = ttk.Combobox(form, state="readonly", values=COUNTRY_NAMES)
        self.country.set("United States")
        self.country.bind("<<ComboboxSelected>>", lambda e: self._country_changed())
        self.country.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(form, text="Region").grid(row=2, column=0, sticky="w", **pad)
        self.region = ttk.Combobox(form, state="readonly")
        self.region.grid(row=2, column=1, sticky="ew", **pad)
        self._country_changed()
        ttk.Label(form, text="City or area (optional)").grid(row=3, column=0, sticky="w", **pad)
        self.place = ttk.Entry(form)
        self.place.grid(row=3, column=1, sticky="ew", **pad)
        ttk.Label(form, text="Max businesses to check").grid(row=4, column=0, sticky="w", **pad)
        self.max_businesses = ttk.Spinbox(form, from_=10, to=1000, increment=10, width=8)
        self.max_businesses.set(100)
        self.max_businesses.grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(form, text="Save CSV in").grid(row=5, column=0, sticky="w", **pad)
        row = ttk.Frame(form)
        row.grid(row=5, column=1, sticky="ew", **pad)
        row.columnconfigure(0, weight=1)
        self.folder = ttk.Entry(row)
        self.folder.insert(0, str(jobs.default_output_dir()))
        self.folder.grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Browse...", command=self._browse).grid(row=0, column=1, padx=(6, 0))

        opts = ttk.LabelFrame(self, text="2. Options")
        opts.pack(fill="x", padx=10, pady=4)
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="Keep leads that have").grid(row=0, column=0, sticky="w", **pad)
        self.confidence = ttk.Combobox(opts, state="readonly", values=list(jobs.CONFIDENCE_LABELS))
        self.confidence.current(1)
        self.confidence.grid(row=0, column=1, sticky="ew", **pad)
        self.personal = tk.BooleanVar(value=True)
        self.chains = tk.BooleanVar(value=False)
        self.save_db = tk.BooleanVar(value=app.cfg.save_to_database)
        self.verify_after = tk.BooleanVar(value=app.cfg.verify_after_search)
        for i, (text, var) in enumerate((
                ("Include Gmail / Yahoo / Outlook addresses", self.personal),
                ("Include big chains and franchises", self.chains),
                ("Save leads to the database", self.save_db),
                ("Verify new emails with Hunter when the search finishes (uses credits)", self.verify_after))):
            ttk.Checkbutton(opts, text=text, variable=var).grid(row=i + 1, column=0, columnspan=2,
                                                                sticky="w", **pad)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=10, pady=6)
        self.start_btn = ttk.Button(actions, text="Find leads", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_flag.set, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(actions, text="Open CSV", state="disabled",
                                   command=lambda: open_path(self.results_path))
        self.open_btn.pack(side="right")
        self.counter = ttk.Label(actions, text="")
        self.counter.pack(side="left", padx=14)

        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", padx=10)
        self.status = ttk.Label(self, text="Ready.")
        self.status.pack(anchor="w", padx=10, pady=(2, 4))
        self.table = DataTable(self, [("business", "Business", 220), ("website", "Website", 220),
                                      ("emails", "Emails", 260), ("phones", "Phones", 140),
                                      ("confidence", "Confidence", 80)], height=7,
                               on_double_click=self._open_site)
        self.table.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    def _country_changed(self):
        code = COUNTRY_BY_NAME.get(self.country.get())
        names = [r["name"] for r in geo.regions(code)] if code else []
        self.region.config(values=[ENTIRE_COUNTRY] + names)
        self.region.set(ENTIRE_COUNTRY)

    def _browse(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if chosen:
            self.folder.delete(0, "end")
            self.folder.insert(0, chosen)

    def _open_site(self):
        for lead in self.table.selected():
            if lead.get("website"):
                webbrowser.open(lead["website"])

    def _max(self):
        try:
            return int(self.max_businesses.get())
        except ValueError:
            return 0

    def _settings(self):
        return jobs.Settings(
            category=jobs.CATEGORY_LABELS[self.category.get()],
            country=COUNTRY_BY_NAME.get(self.country.get(), ""),
            region="" if self.region.get() == ENTIRE_COUNTRY else self.region.get(),
            place=self.place.get(), max_businesses=self._max(),
            output_dir=Path(self.folder.get()) if self.folder.get().strip() else None,
            exclude_personal=not self.personal.get(), keep_chains=self.chains.get(),
            min_confidence=jobs.CONFIDENCE_LABELS[self.confidence.get()])

    def start(self):
        settings = self._settings()
        problem = jobs.validate(settings)
        if problem:
            messagebox.showwarning("Check your entries", problem)
            return
        db = self.app.db if self.save_db.get() else None
        if self.save_db.get() and db is None and not messagebox.askyesno(
                "Database not connected",
                "The database isn't connected, so leads will only be saved to the CSV file.\n\nContinue?"):
            return
        self.app.cfg.save_to_database = self.save_db.get()
        self.app.cfg.verify_after_search = self.verify_after.get()
        self.app.cfg.save()
        self.stop_flag.clear()
        self.results_path = None
        self.found = self.with_email = 0
        self.table.clear()
        self.counter.config(text="")
        self.open_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.bar.config(value=0)
        self.status.config(text="Working...")
        threading.Thread(target=self._work, args=(settings, db), daemon=True).start()

    def _work(self, settings, db):
        app = self.app
        try:
            path, count = jobs.run_pipeline(
                settings,
                log=lambda m: app.post(lambda: self.status.config(text=m[:140])),
                progress=lambda d, t: app.post(lambda: self._progress(d, t)),
                should_stop=self.stop_flag.is_set, db=db,
                on_lead=lambda lead: app.post(lambda: self._on_lead(lead)))
            app.post(lambda: self._finish(path, count, db is not None))
        except RuntimeError:
            app.post(lambda: self._fail("Couldn't reach the business database (OpenStreetMap). "
                                        "Check your internet connection and try again in a minute."))
        except Exception as e:
            app.post(lambda: self._fail(f"Something went wrong: {e}"))

    def _progress(self, done, total):
        self.bar.config(maximum=max(total, 1), value=done)
        self.status.config(text=f"Checked {done} of {total} businesses")

    def _on_lead(self, lead):
        self.found += 1
        self.with_email += bool(lead.get("emails"))
        self.counter.config(text=f"{self.found} leads · {self.with_email} with an email")
        self.table.add_row(f"lead{self.found}", (lead["business"], lead["website"], lead["emails"],
                                                  lead["phones"], lead["confidence"]), lead, at_top=True)

    def _reset(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _fail(self, message):
        self._reset()
        self.status.config(text="Stopped with an error.")
        messagebox.showerror("SKrapkin", message)

    def _finish(self, path, count, saved):
        self._reset()
        if not (path and count):
            self.status.config(text="Done: no leads found.")
            return
        self.results_path = path
        self.open_btn.config(state="normal")
        self.status.config(text=f"Done: {count} leads" + (" saved to the database and" if saved else "")
                                + f" written to {Path(path).name}")
        self.app.refresh_data()
        if saved and self.verify_after.get():
            self.app.nb.select(self.app.verify_tab)
            self.app.verify_tab.start(auto=True)


# ------------------------------------------------------------------------------------------------
class LeadsTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.nb)
        self.app = app
        self.filters = Filters(self, self.refresh, with_status=True)
        self.filters.pack(fill="x", padx=10, pady=8)
        self.table = DataTable(
            self, [("business", "Business", 200), ("country", "Country", 110), ("region", "Region", 100), ("city", "City", 90),
                   ("website", "Website", 190), ("emails", "Emails (status)", 320),
                   ("phones", "Phones", 130), ("confidence", "Confidence", 80)],
            menu_items=[("Copy email addresses", self._copy_emails), ("Open website", self._open_site),
                        ("Delete selected leads", self._delete)],
            on_double_click=self._open_site)
        self.table.pack(fill="both", expand=True, padx=10)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        self.count = ttk.Label(bar, text="")
        self.count.pack(side="left")
        ttk.Button(bar, text="Export CSV", command=lambda: self.table.export_csv("leads.csv")).pack(side="right")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right", padx=6)

    def on_show(self):
        self.refresh()

    def refresh(self):
        if not self.app.db:
            self.count.config(text="Connect the database in Settings to see saved leads.")
            return
        text, category, country, region, status = self.filters.query()
        db = self.app.db

        def show(leads):
            rows = []
            for lead in leads:
                if status and not any(e["status"] == status for e in lead.get("emails", [])):
                    continue
                rows.append((lead["key"], (lead.get("business", ""), geo.country_name(lead.get("country", "")) if lead.get("country") else "",
                                           lead.get("region", ""), lead.get("city", ""),
                                           lead.get("website", ""), email_summary(lead),
                                           "; ".join(lead.get("phones", [])), lead.get("confidence", "")),
                             lead, ""))
            self.table.set_rows(rows)
            stats = db.stats()
            self.count.config(text=f"Showing {len(rows)} leads  ·  {stats['leads']} saved in total, "
                                   f"{stats['verified']} verified emails")

        self.app.run_bg(lambda: db.list_leads(text, category, country, region), ok=show)

    def _copy_emails(self):
        addresses = [e["address"] for lead in self.table.selected() for e in lead.get("emails", [])]
        copy_to_clipboard(self, "\n".join(addresses))

    def _open_site(self):
        for lead in self.table.selected():
            if lead.get("website"):
                webbrowser.open(lead["website"])

    def _delete(self):
        keys = [lead["key"] for lead in self.table.selected()]
        if keys and messagebox.askyesno("Delete leads", f"Delete {len(keys)} selected leads? "
                                        "Verified emails already filed stay in Verified Results."):
            self.app.run_bg(lambda: self.app.db.delete_leads(keys), ok=lambda n: self.refresh())


# ------------------------------------------------------------------------------------------------
class VerifyTab(ttk.Frame):
    DECISION_TAGS = {"check": {"foreground": "#0a7d33"}, "skip": {"foreground": "#777777"}}

    def __init__(self, app):
        super().__init__(app.nb)
        self.app = app
        self.stop_flag = threading.Event()
        self.plan = None
        pad = {"padx": 8, "pady": 4}

        key_box = ttk.LabelFrame(self, text="1. Hunter.io account")
        key_box.pack(fill="x", padx=10, pady=(10, 4))
        key_box.columnconfigure(1, weight=1)
        ttk.Label(key_box, text="API key").grid(row=0, column=0, sticky="w", **pad)
        self.key = ttk.Entry(key_box, show="•")
        self.key.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(key_box, text="Save & test", command=self.save_key).grid(row=0, column=2, **pad)
        ttk.Button(key_box, text="Remove key", command=self.remove_key).grid(row=0, column=3, **pad)
        self.key_status = ttk.Label(key_box, text="", wraplength=860, justify="left")
        self.key_status.grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        link = ttk.Label(key_box, text="Find your key at hunter.io/api-keys", foreground="#1a5fb4", cursor="hand2")
        link.grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        link.bind("<Button-1>", lambda e: webbrowser.open("https://hunter.io/api-keys"))

        save_box = ttk.LabelFrame(self, text="2. Keep costs down")
        save_box.pack(fill="x", padx=10, pady=4)
        ttk.Label(save_box, text="Only send emails that score at least").grid(row=0, column=0, sticky="w", **pad)
        self.threshold = ttk.Spinbox(save_box, from_=0, to=100, increment=5, width=6)
        self.threshold.set(app.cfg.min_likelihood)
        self.threshold.grid(row=0, column=1, **pad)
        ttk.Label(save_box, text="out of 100 (higher = fewer lookups, fewer wasted credits)").grid(
            row=0, column=2, sticky="w")
        ttk.Label(save_box, text="Never use more than").grid(row=1, column=0, sticky="w", **pad)
        self.budget = ttk.Spinbox(save_box, from_=1, to=10000, increment=10, width=6)
        self.budget.set(app.cfg.max_credits_per_run)
        self.budget.grid(row=1, column=1, **pad)
        ttk.Label(save_box, text="Hunter lookups in one run").grid(row=1, column=2, sticky="w")
        ttk.Label(save_box, text="Emails that are clearly fake, on dead domains, webmail, or already checked "
                                 "are skipped for free.", foreground="#555555").grid(
            row=2, column=0, columnspan=3, sticky="w", **pad)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=10, pady=6)
        self.preview_btn = ttk.Button(actions, text="Preview (free)", command=self.preview)
        self.preview_btn.pack(side="left")
        self.verify_btn = ttk.Button(actions, text="Verify now", command=self.start)
        self.verify_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_flag.set, state="disabled")
        self.stop_btn.pack(side="left")
        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", padx=10)
        self.summary = ttk.Label(self, text="Preview shows exactly which emails would be sent to Hunter.",
                                 wraplength=900, justify="left")
        self.summary.pack(anchor="w", padx=10, pady=4)
        self.table = DataTable(self, [("decision", "Decision", 260), ("email", "Email", 220),
                                      ("business", "Business", 200), ("score", "Score", 60)],
                               height=8, tags=self.DECISION_TAGS)
        self.table.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.refresh_key_status()

    def on_show(self):
        self.refresh_key_status()

    # key management -----------------------------------------------------

    def refresh_key_status(self):
        have = bool(config.get_hunter_key())
        self.key_status.config(text="A key is saved on this computer." if have else
                               "No key saved yet. Verification is disabled until you add one.")

    def save_key(self):
        typed = self.key.get().strip() or config.get_hunter_key()
        if not typed:
            messagebox.showwarning("Hunter.io", "Paste your Hunter API key first.")
            return
        self.key_status.config(text="Testing key (this check is free)...")

        def test():
            return HunterClient(typed).account()

        def ok(account):
            where = config.set_hunter_key(typed)
            self.key.delete(0, "end")
            place = "your system keychain" if where == "keychain" else "a private file in your user folder"
            self.key_status.config(text=f"Key works and is saved in {place}. Plan: {account['plan'] or 'n/a'}, "
                                        f"{account['remaining']} of {account['available']} verifications left.")

        def fail(error):
            msg = "Hunter rejected this key. Check that you copied it completely." if isinstance(error, InvalidKey) \
                else f"Couldn't check the key: {error}"
            self.key_status.config(text=msg)

        self.app.run_bg(test, ok=ok, err=fail)

    def remove_key(self):
        config.clear_hunter_key()
        self.key.delete(0, "end")
        self.refresh_key_status()

    # preview and run ----------------------------------------------------

    def _apply_settings(self):
        try:
            self.app.cfg.min_likelihood = max(0, min(100, int(self.threshold.get())))
            self.app.cfg.max_credits_per_run = max(1, int(self.budget.get()))
        except ValueError:
            messagebox.showwarning("Check your entries", "The score and the lookup limit must be whole numbers.")
            return False
        self.app.cfg.save()
        return True

    def preview(self, then=None):
        if not self.app.require_db() or not self._apply_settings():
            return
        self.summary.config(text="Checking which emails are worth a lookup...")
        db, cfg = self.app.db, self.app.cfg

        def show(plan):
            self.plan = plan
            rows = [(f"c{i}", ("✔ Check with Hunter", c.address, c.business, c.likelihood), None, "check")
                    for i, c in enumerate(plan.to_check[:cfg.max_credits_per_run])]
            rows += [(f"o{i}", (f"Over this run's limit of {cfg.max_credits_per_run}", c.address, c.business,
                                c.likelihood), None, "skip")
                     for i, c in enumerate(plan.to_check[cfg.max_credits_per_run:])]
            rows += [(f"f{i}", (f"Skip: {why}", c.address, c.business, c.likelihood), None, "skip")
                     for i, (c, why) in enumerate(plan.filtered)]
            rows += [(f"w{i}", ("Skip: webmail can't be confirmed", c.address, c.business, c.likelihood),
                      None, "skip") for i, c in enumerate(plan.webmail)]
            rows += [(f"h{i}", (f"Skip: already checked ({s['status']})", c.address, c.business, c.likelihood),
                      None, "skip") for i, (c, s) in enumerate(plan.cached)]
            rows += [(f"a{i}", ("Skip: this domain accepts any address", c.address, c.business, c.likelihood),
                      None, "skip") for i, c in enumerate(plan.inferred)]
            self.table.set_rows(rows)
            n = min(len(plan.to_check), cfg.max_credits_per_run)
            self.summary.config(text=f"{n} emails would use Hunter credits. " + plan.summary())
            if then:
                then(plan, n)

        self.app.run_bg(lambda: build_plan(db, cfg), ok=show)

    def start(self, auto=False):
        if not config.get_hunter_key():
            messagebox.showwarning("Hunter.io", "Add and test your Hunter API key first.")
            return
        if not self.app.require_db() or not self._apply_settings():
            return
        if auto:
            self._run(None)
            return

        def confirm(plan, n):
            if n == 0:
                messagebox.showinfo("Nothing to verify", "No new emails need a Hunter lookup.")
            elif messagebox.askokcancel("Use Hunter credits?", f"This will check {n} emails with Hunter and "
                                        f"use up to {n} of your verification credits.\n\n"
                                        f"{plan.saved} other emails are skipped for free."):
                self._run(plan)

        self.preview(then=confirm)

    def _busy(self, busy):
        for button in (self.preview_btn, self.verify_btn):
            button.config(state="disabled" if busy else "normal")
        self.stop_btn.config(state="normal" if busy else "disabled")

    def _run(self, plan):
        app, db, cfg, key = self.app, self.app.db, self.app.cfg, config.get_hunter_key()
        self.stop_flag.clear()
        self._busy(True)
        self.bar.config(value=0)
        self.summary.config(text="Verifying...")

        def work():
            try:
                result = jobs.run_verification(
                    db, cfg, key,
                    log=lambda m: app.post(lambda: self.summary.config(text=m[:200])),
                    progress=lambda d, t: app.post(lambda: self.bar.config(maximum=max(t, 1), value=d)),
                    should_stop=self.stop_flag.is_set, plan=plan)
                app.post(lambda: self._finished(*result))
            except InvalidKey:
                app.post(lambda: self._failed("Hunter rejected your API key. Re-enter it above."))
            except HunterError as e:
                app.post(lambda: self._failed(str(e)))
            except Exception as e:
                app.post(lambda: self._failed(f"Something went wrong: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, message):
        self._busy(False)
        self.summary.config(text=message)
        messagebox.showerror("Verification stopped", message)

    def _finished(self, account, plan, stats):
        self._busy(False)
        left = account["remaining"] - stats["checked"]
        text = (f"Checked {stats['checked']} with Hunter: {stats['valid']} valid, {stats['invalid']} invalid, "
                f"{stats['accept_all']} accept-all, {stats['unknown']} unknown. "
                f"Skipped {stats['skipped_free']} for free. About {left} Hunter verifications left.")
        if stats["left_unchecked"]:
            text += f" {stats['left_unchecked']} emails are waiting for the next run."
        if stats["stopped"]:
            text += f" Stopped: {stats['stopped']}."
        self.summary.config(text=text)
        self.table.clear()
        self.app.refresh_data()


# ------------------------------------------------------------------------------------------------
class VerifiedTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.nb)
        self.app = app
        self.filters = Filters(self, self.refresh)
        self.filters.pack(fill="x", padx=10, pady=8)
        self.table = DataTable(
            self, [("email", "Email", 240), ("business", "Business", 200), ("country", "Country", 110),
                   ("region", "Region", 100), ("city", "City", 90), ("website", "Website", 190), ("phones", "Phones", 130),
                   ("score", "Score", 55), ("verified", "Verified", 130)],
            menu_items=[("Copy email addresses", self._copy_selected), ("Open website", self._open_site),
                        ("Remove from verified list", self._delete)],
            on_double_click=self._open_site)
        self.table.pack(fill="both", expand=True, padx=10)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        self.count = ttk.Label(bar, text="")
        self.count.pack(side="left")
        ttk.Button(bar, text="Export CSV", command=lambda: self.table.export_csv("verified_emails.csv")).pack(side="right")
        ttk.Button(bar, text="Copy all emails", command=self._copy_all).pack(side="right", padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")

    def on_show(self):
        self.refresh()

    def refresh(self):
        if not self.app.db:
            self.count.config(text="Connect the database in Settings to see verified emails.")
            return
        text, category, country, region, _ = self.filters.query()

        def show(docs):
            self.table.set_rows([
                (d["_id"], (d["email"], d.get("business", ""),
                            geo.country_name(d.get("country", "")) if d.get("country") else "",
                            d.get("region", ""), d.get("city", ""),
                            d.get("website", ""), "; ".join(d.get("phones", [])), d.get("score", ""),
                            d["verified_at"].strftime("%Y-%m-%d %H:%M")), d, "") for d in docs])
            self.count.config(text=f"{len(docs)} verified emails")

        self.app.run_bg(lambda: self.app.db.list_verified(text, category, country, region), ok=show)

    def _copy_selected(self):
        copy_to_clipboard(self, "\n".join(d["email"] for d in self.table.selected()))

    def _copy_all(self):
        emails = [row[0] for row in self.table.all_values()]
        copy_to_clipboard(self, "\n".join(emails))
        self.count.config(text=f"Copied {len(emails)} emails to the clipboard.")

    def _open_site(self):
        for doc in self.table.selected():
            if doc.get("website"):
                webbrowser.open(doc["website"])

    def _delete(self):
        addresses = [d["email"] for d in self.table.selected()]
        if addresses and messagebox.askyesno("Remove", f"Remove {len(addresses)} emails from the verified list?"):
            self.app.run_bg(lambda: self.app.db.delete_verified(addresses), ok=lambda n: self.refresh())


# ------------------------------------------------------------------------------------------------
class SettingsTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.nb)
        self.app = app
        pad = {"padx": 10, "pady": 5}
        box = ttk.LabelFrame(self, text="Database (MongoDB)")
        box.pack(fill="x", padx=10, pady=10)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Connection address").grid(row=0, column=0, sticky="w", **pad)
        self.uri = ttk.Entry(box, show="•")
        self.uri.insert(0, app.cfg.mongo_uri)
        self.uri.grid(row=0, column=1, sticky="ew", **pad)
        self.show = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Show", variable=self.show,
                        command=lambda: self.uri.config(show="" if self.show.get() else "•")).grid(row=0, column=2, **pad)
        ttk.Label(box, text="Database name").grid(row=1, column=0, sticky="w", **pad)
        self.name = ttk.Entry(box, width=24)
        self.name.insert(0, app.cfg.db_name)
        self.name.grid(row=1, column=1, sticky="w", **pad)
        ttk.Button(box, text="Save & connect", command=self.save).grid(row=2, column=1, sticky="w", **pad)
        self.result = ttk.Label(box, text="", wraplength=800, justify="left")
        self.result.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(self, text=DB_HELP, wraplength=900, justify="left", foreground="#555555").pack(
            anchor="w", padx=20, pady=6)

    def save(self):
        self.app.cfg.mongo_uri = self.uri.get().strip() or config.DEFAULT_MONGO_URI
        self.app.cfg.db_name = self.name.get().strip() or "skrapkin"
        self.app.cfg.save()
        self.result.config(text="Connecting...")

        def done(error):
            self.result.config(text="Connected." if error is None else
                               "Couldn't connect. Check the address, that MongoDB is running, and that your "
                               f"network allows it.\n({type(error).__name__})")

        self.app.connect_db(on_result=done)


def main():
    App().mainloop()
