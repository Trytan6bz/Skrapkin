"""GUI-facing job runner: discover then scrape, with no UI dependencies."""

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .cli import cmd_discover, cmd_scrape
from .db import Database
from .discover import US_STATES
from .hunter import HunterClient
from .verifier import build_plan, run_plan

CATEGORY_LABELS = {
    "Building materials & contractors": "building",
    "Clothing & fashion retailers": "clothing",
    "Toy & gift shops": "toys",
}
CONFIDENCE_LABELS = {
    "Any contact (email or phone)": "low",
    "Must have an email address": "medium",
    "Must have an email on the business's own website": "high",
}


def default_output_dir():
    return Path.home() / "Documents" / "SKrapkin"


@dataclass
class Settings:
    category: str            # a CATEGORIES key: building / clothing / toys
    area: str                # a US state name from US_STATES
    country: str = "US"
    output_dir: Path = None
    exclude_personal: bool = False
    keep_chains: bool = False
    min_confidence: str = "low"
    delay: float = 2.0
    max_pages: int = 4
    max_businesses: int = 100


def validate(s):
    """Return a plain-language problem with the settings, or None."""
    if s.area not in US_STATES:
        return "Please choose a state."
    if s.max_businesses < 1:
        return "The number of businesses to check must be at least 1."
    if not s.output_dir:
        return "Please choose a folder to save the results in."
    return None


def output_paths(s, today=None):
    slug = re.sub(r"[^a-z0-9]+", "-", s.area.lower()).strip("-")
    stamp = (today or date.today()).isoformat()
    base = Path(s.output_dir) / f"{s.category}_{slug}_{stamp}"
    return base.with_name(base.name + "_businesses.csv"), base.with_name(base.name + "_leads.csv")


def run_pipeline(s, log, progress, should_stop, db=None, on_lead=None):
    """Find businesses, then collect their contacts. Returns (leads_csv_path, lead_count).

    Each lead is saved to `db` (when given) as soon as it is found, and passed to `on_lead`.
    """
    Path(s.output_dir).mkdir(parents=True, exist_ok=True)
    seeds_path, leads_path = output_paths(s)

    log(f"Searching for {s.category} businesses in {s.area}...")
    found = cmd_discover(
        argparse.Namespace(area=s.area, country=s.country, category=s.category,
                           output=str(seeds_path), limit=s.max_businesses),
        log=log)
    if not found:
        log("No businesses found. Try a different state or category.")
        return None, 0

    search = {"state": s.area, "category": s.category}

    def handle_lead(lead):
        if db is not None:
            db.upsert_lead(lead, search)
        if on_lead:
            on_lead(lead)

    log("Collecting contact details (this can take several minutes)...")
    count = cmd_scrape(
        argparse.Namespace(seeds=str(seeds_path), output=str(leads_path), delay=s.delay,
                           max_pages=s.max_pages, exclude_personal=s.exclude_personal,
                           any_domain=False, country=s.country,
                           min_confidence=s.min_confidence, keep_chains=s.keep_chains),
        log=log, progress=progress, should_stop=should_stop, on_lead=handle_lead)
    return leads_path, count


def connect_db(cfg):
    """Open and index the database; raises if it can't be reached."""
    db = Database(cfg.mongo_uri, cfg.db_name)
    try:
        db.connect()
    except Exception:
        db.close()
        raise
    return db


def run_verification(db, cfg, api_key, log, progress, should_stop, plan=None):
    """Check the key, then verify only the emails that survive local filtering.

    Returns (account, plan, stats). Raises InvalidKey if Hunter rejects the key.
    """
    client = HunterClient(api_key)
    account = client.account()  # free call: validates the key and reads the remaining balance
    log(f"Hunter {account['plan'] or 'account'}: {account['remaining']} verifications remaining.")
    plan = plan or build_plan(db, cfg)
    log(plan.summary())
    stats = run_plan(db, client, plan, cfg, log=log, progress=progress, should_stop=should_stop,
                     budget=account["remaining"])
    return account, plan, stats
