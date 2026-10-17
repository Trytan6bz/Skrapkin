"""Usage:
    python -m skrapkin.cli discover --country US --region Texas --category toys -o seeds.csv
    python -m skrapkin.cli discover --country NG --region Lagos --place Ikeja --category clothing -o seeds.csv
    python -m skrapkin.cli scrape seeds.csv -o leads.csv
    python -m skrapkin.cli audit leads.csv -n 50 -o audit.csv      # then fill in is_legit (y/n)
    python -m skrapkin.cli audit audit.csv --score                 # prints precision

    # with MongoDB (see docker-compose.yml) and a Hunter key in HUNTER_API_KEY:
    python -m skrapkin.cli scrape seeds.csv --save-db
    python -m skrapkin.cli verify --preview                        # free: shows what would be checked
    python -m skrapkin.cli verify --yes                            # spends Hunter credits
    python -m skrapkin.cli export verified -o verified.csv
"""

import argparse
import csv
import os
import random
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import urlparse

from . import config
from . import regions as geo
from .discover import CATEGORIES, DiscoveryError, discover, resolve_region
from .csvsafe import safe_row
from .extract import (contact_links, extract_emails, extract_name, extract_phones,
                      filter_free_mail, same_site_emails)
from .fetcher import Fetcher
from .validate import (chain_domains, confidence, is_aggregator, is_junk_email, is_non_buyer, mx_status,
                       normalize_phone, registered_domain, site_key)

SEED_FIELDS = ["category", "business", "website", "phone", "email", "city", "brand", "country", "region"]
MAX_SCRAPED_PHONES = 3
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
LEAD_FIELDS = ["category", "business", "website", "emails", "phones", "city", "country", "region", "confidence",
               "source_pages"]


def scrape_site(fetcher, url, max_pages, include_personal, any_domain=False, region="US",
                should_stop=lambda: False, stop_at_email=False):
    """Fetch a site's homepage and its contact-like pages and pull out emails and phones.

    With stop_at_email, further pages are skipped as soon as an email on the business's own domain has been
    found: one good address is enough for outreach, and every page saved is bandwidth and time saved.
    """
    html = fetcher.get(url)
    if html is None:
        return None
    pages, emails, phones = [url], set(), []
    site = registered_domain(url)

    def absorb(page_html):
        emails.update(extract_emails(page_html, include_personal))
        phones.extend(p for p in extract_phones(page_html, region) if p not in phones)

    def found_enough():
        return stop_at_email and any(any_domain or registered_domain(e.split("@")[1]) == site for e in emails)

    absorb(html)
    for link in contact_links(html, url)[: max_pages - 1]:
        if should_stop() or found_enough():
            break
        page = fetcher.get(link)
        if page is not None:
            pages.append(link)
            absorb(page)
    emails = emails if any_domain else same_site_emails(emails, url)
    # Many numbers on a site usually means branches or partners, not this business.
    return {"name": extract_name(html), "emails": emails, "phones": set(phones[:MAX_SCRAPED_PHONES]),
            "pages": pages}


def read_seeds(path):
    """Seeds are a CSV with a 'website' column, or a plain list of URLs."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        if path.endswith(".csv"):
            return list(csv.DictReader(f))
        return [{"website": l.strip()} for l in f if l.strip() and not l.startswith("#")]


def cmd_discover(args, log=print, should_stop=lambda: False):
    country = geo.find_country(getattr(args, "country", None))
    if not country:
        raise ValueError("Choose a country (an ISO code like US, NG, GB, or a name like Nigeria).")
    region = resolve_region(country, getattr(args, "region", None))
    place = getattr(args, "place", None) or getattr(args, "area", None) or ""
    limit = getattr(args, "limit", None)
    exclude = getattr(args, "exclude", None)
    if exclude is None and getattr(args, "skip_checked", False):
        from .jobs import connect_db  # lazy: jobs imports this module
        history_db = connect_db(config.Config.load())
        try:
            exclude = history_db.checked_map()
        finally:
            history_db.close()
    exclude = exclude or {}
    # How many of the already-checked businesses belong to this area decides how far past them to look.
    region_name = region["name"] if region else ""
    in_scope = sum(1 for v in exclude.values() if isinstance(v, dict) and v.get("country") == country
                   and (not region_name or v.get("region") == region_name)) if isinstance(exclude, dict) else len(exclude)
    if not region and not place:
        log(f"Searching all of {geo.country_name(country)}; results are limited to a sample. "
            "Pick a region or city for a complete picture.")
    leads = discover(args.category, country, region, place, limit, should_stop=should_stop,
                     on_wait=lambda secs: log(f"Still waiting for OpenStreetMap ({int(secs)}s). "
                                              "Large areas can take a few minutes."),
                     skip=in_scope)
    for lead in leads:
        lead["country"], lead["region"] = country, region["name"] if region else ""
    seen, rows = set(), []
    for lead in leads:
        key = (lead["business"].lower(), lead["website"].lower())
        if key not in seen and (lead["website"] or lead["phone"] or lead["email"]):
            seen.add(key)
            rows.append(lead)
    if exclude:
        fresh = [r for r in rows if site_key(r.get("website"), r.get("phone"), r.get("business")) not in exclude]
        if len(fresh) < len(rows):
            log(f"Skipping {len(rows) - len(fresh)} businesses you've already checked.")
        rows = fresh
    if limit and len(rows) > limit:
        # Businesses with a website can yield emails, so keep those first.
        rows = sorted(rows, key=lambda r: not r["website"])[:limit]
        log(f"Found more than {limit} businesses; checking the first {limit}.")
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SEED_FIELDS)
        w.writeheader()
        w.writerows(safe_row(r) for r in rows)
    with_site = sum(1 for r in rows if r["website"])
    log(f"wrote {len(rows)} businesses to {args.output} ({with_site} with a website)")
    return len(rows)


def clean_emails(emails, site):
    """Drop junk and undeliverable addresses. Returns (kept, any_on_own_domain)."""
    kept = set()
    for e in emails:
        if is_junk_email(e) or mx_status(e.split("@")[1]) == "bad":
            continue
        kept.add(e)
    own = registered_domain(site) if site else None
    return kept, any(own and registered_domain(e.split("@")[1]) == own for e in kept)


def clean_phones(phones, region):
    return {n for p in phones if (n := normalize_phone(p, region))}


DEFAULT_WORKERS = 8
MAX_WORKERS = 32


def worker_count(args):
    n = getattr(args, "workers", None) or int(os.environ.get("SKRAPKIN_WORKERS", DEFAULT_WORKERS))
    return max(1, min(int(n), MAX_WORKERS))


def check_seed(seed, site, args, fetcher, should_stop):
    """All the slow, networked work for one business. Runs on a worker thread and touches no shared state:
    results go back to the main thread, which owns the log, database and CSV."""
    logs = []
    country = seed.get("country") or geo.find_country(getattr(args, "country", None)) or "US"
    osm_emails = filter_free_mail(
        {e.strip().lower() for e in seed.get("email", "").split(";") if e.strip()}, not args.exclude_personal)
    osm_phones = {p.strip() for p in seed.get("phone", "").split(";") if p.strip()}
    result = None
    if site:
        url = site if site.startswith("http") else "https://" + site
        result = scrape_site(fetcher, url, args.max_pages, not args.exclude_personal, args.any_domain,
                             region=country, should_stop=should_stop,
                             stop_at_email=not getattr(args, "thorough", False))
        if result is None:
            logs.append(f"skipped {url} (blocked by robots.txt or unreachable)")
    emails, own_domain = clean_emails(osm_emails | (result["emails"] if result else set()), site)
    phones = clean_phones(osm_phones | (result["phones"] if result else set()), country)
    level = confidence(emails, phones, own_domain)
    if not level:
        return {"outcome": "no_contact", "logs": logs}
    if CONFIDENCE_RANK[level] < CONFIDENCE_RANK[args.min_confidence]:
        return {"outcome": "low_confidence", "logs": logs}
    row = {
        "category": seed.get("category", ""),
        "business": seed.get("business") or (result["name"] if result else ""),
        "website": site,
        "emails": "; ".join(sorted(emails)),
        "phones": "; ".join(sorted(phones)),
        "city": seed.get("city", ""),
        "country": country if seed.get("country") else "",
        "region": seed.get("region") or getattr(args, "region", "") or "",
        "confidence": level,
        "source_pages": "; ".join(result["pages"]) if result else "openstreetmap",
    }
    logs.append(f"[{level}] {row['business'] or site}: {row['emails'] or row['phones']}")
    sources = {e: "site" if result and e in result["emails"] else "osm" for e in emails}
    return {"outcome": "lead", "row": row, "sources": sources, "logs": logs}


def cmd_scrape(args, log=print, progress=lambda done, total: None, should_stop=lambda: False,
               on_lead=None, on_checked=None):
    """Collect contacts for every seed. Sites are checked in parallel, but each site is still fetched one
    page at a time with a delay, and all logging, database writes and CSV output happen on this thread."""
    lead_callbacks, checked_callbacks = [], []
    if getattr(args, "save_db", False):
        from .db import seed_key
        from .jobs import connect_db  # lazy: jobs imports this module
        db = connect_db(config.Config.load())
        lead_callbacks.append(lambda lead: db.upsert_lead(
            lead, {"country": lead.get("country", ""), "region": getattr(args, "region", "") or ""}))
        checked_callbacks.append(lambda seed, outcome: db.mark_checked(seed_key(seed), outcome, {
            "country": seed.get("country", ""), "region": seed.get("region", "") or getattr(args, "region", ""),
            "category": seed.get("category", "")}))
    if on_lead:
        lead_callbacks.append(on_lead)
    if on_checked:
        checked_callbacks.append(on_checked)

    fetcher = Fetcher(delay=args.delay)
    all_seeds = read_seeds(args.seeds)
    total = len(all_seeds)
    chains = set() if args.keep_chains else chain_domains(all_seeds)
    dropped = {"non_buyer": 0, "chain": 0, "aggregator": 0, "no_contact": 0, "low_confidence": 0, "error": 0}
    rows_by_index, done = {}, 0

    # Pass 1 (instant): settle everything that needs no network, and queue the rest.
    work, seen = [], set()
    for i, seed in enumerate(all_seeds):
        site = seed.get("website", "").strip()
        reason = None
        if is_non_buyer(seed.get("business")):
            reason = "non_buyer"
        elif not args.keep_chains and (seed.get("brand") or (site and registered_domain(site) in chains)):
            reason = "chain"
        if reason:
            dropped[reason] += 1
            done += 1
            for cb in checked_callbacks:
                cb(seed, reason)
            continue
        if site and is_aggregator(site):
            site = ""  # keep the OSM phone/email but don't crawl a social/listing page
            dropped["aggregator"] += 1
        if site:
            url = site if site.startswith("http") else "https://" + site
            domain = urlparse(url).netloc
            if domain in seen:      # a second entry for the same site: the first one covers it
                done += 1
                continue
            seen.add(domain)
        work.append((i, seed, site))
    progress(done, total)

    # Pass 2: check the queued sites on worker threads, handling each result as it arrives.
    stopped = False
    pool = ThreadPoolExecutor(max_workers=max(1, min(worker_count(args), len(work) or 1)))
    pending = {pool.submit(check_seed, seed, site, args, fetcher, should_stop): (i, seed) for i, seed, site in work}
    try:
        while pending:
            if should_stop():
                stopped = True
                break
            finished, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for fut in finished:
                i, seed = pending.pop(fut)
                done += 1
                try:
                    res = fut.result()
                except Exception as e:  # one bad site must not sink the run; it is retried next time
                    dropped["error"] += 1
                    log(f"could not check {seed.get('business') or seed.get('website')}: {type(e).__name__}")
                    progress(done, total)
                    continue
                for line in res["logs"]:
                    log(line)
                if res["outcome"] == "lead":
                    rows_by_index[i] = res["row"]
                    lead = {**res["row"], "email_sources": res["sources"]}
                    for cb in lead_callbacks:
                        cb(lead)
                else:
                    dropped[res["outcome"]] += 1
                for cb in checked_callbacks:
                    cb(seed, res["outcome"])
                progress(done, total)
    finally:
        # Workers still mid-site finish on their own and their results are discarded.
        pool.shutdown(wait=False, cancel_futures=True)
    if stopped:
        log("Stopped early; saving what was found so far.")

    rows = [rows_by_index[i] for i in sorted(rows_by_index)]
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
        w.writeheader()
        w.writerows(safe_row(r) for r in rows)
    progress(done, total)
    log(f"wrote {len(rows)} leads to {args.output}; dropped: {dropped}")
    return len(rows)


def cmd_audit(args):
    """Sample leads for manual review, then score the reviewed sample."""
    if args.score:
        with open(args.file, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if r.get("is_legit", "").strip().lower() in ("y", "n")]
        if not rows:
            sys.exit("no reviewed rows: fill the is_legit column with y or n first")
        good = sum(r["is_legit"].strip().lower() == "y" for r in rows)
        print(f"precision: {good}/{len(rows)} = {good / len(rows):.0%}")
        for level in ("high", "medium", "low"):
            sub = [r for r in rows if r.get("confidence") == level]
            if sub:
                g = sum(r["is_legit"].strip().lower() == "y" for r in sub)
                print(f"  {level}: {g}/{len(sub)} = {g / len(sub):.0%}")
        return
    with open(args.file, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    sample = random.Random(args.seed).sample(rows, min(args.n, len(rows)))
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LEAD_FIELDS + ["is_legit"])
        w.writeheader()
        w.writerows(safe_row(r) for r in sample)
    print(f"wrote {len(sample)} sampled leads to {args.output}. Check each (right business? working "
          f"email/phone? would buy in bulk?) and set is_legit to y or n, then run: audit {args.output} --score")


def cmd_verify(args, log=print):
    """Filter locally, then spend Hunter lookups only on emails likely to be real."""
    from .hunter import InvalidKey
    from .jobs import connect_db, run_verification
    from .verifier import build_plan

    cfg = config.Config.load()
    if args.min_likelihood is not None:
        cfg.min_likelihood = args.min_likelihood
    if args.max_lookups is not None:
        cfg.max_credits_per_run = args.max_lookups
    key = config.get_hunter_key()
    if not key and not args.preview:
        sys.exit("No Hunter API key. Set the HUNTER_API_KEY environment variable (or save one in the app).")
    db = connect_db(cfg)
    plan = build_plan(db, cfg)
    n = min(len(plan.to_check), cfg.max_credits_per_run)
    log(plan.summary())
    if args.preview:
        for cand in plan.to_check[:n]:
            log(f"  would check  {cand.address}  (score {cand.likelihood})")
        for cand, why in plan.filtered:
            log(f"  skip         {cand.address}  ({why})")
        return n
    if n == 0:
        log("Nothing to verify.")
        return 0
    if not args.yes and input(f"Use up to {n} Hunter lookups? [y/N] ").strip().lower() != "y":
        log("Cancelled.")
        return 0
    try:
        _, _, stats = run_verification(db, cfg, key, log, lambda d, t: None, lambda: False, plan=plan)
    except InvalidKey:
        sys.exit("Hunter rejected the API key.")
    log(f"checked {stats['checked']}: {stats['valid']} valid, {stats['invalid']} invalid, "
        f"{stats['accept_all']} accept-all, {stats['unknown']} unknown; skipped {stats['skipped_free']} for free; "
        f"{stats['left_unchecked']} left for next run" + (f"; stopped: {stats['stopped']}" if stats["stopped"] else ""))
    return stats["checked"]


def cmd_export(args, log=print):
    from .jobs import connect_db

    db = connect_db(config.Config.load())
    if args.what == "verified":
        header = ["email", "business", "country", "region", "city", "website", "phones", "score", "verified_at"]
        rows = [[d["email"], d.get("business", ""), d.get("country", ""), d.get("region", ""), d.get("city", ""),
                 d.get("website", ""), "; ".join(d.get("phones", [])), d.get("score", ""), d["verified_at"].isoformat()]
                for d in db.list_verified(limit=0)]
    else:
        header = ["business", "country", "region", "city", "website", "emails", "phones", "confidence"]
        rows = [[d.get("business", ""), d.get("country", ""), d.get("region", ""), d.get("city", ""), d.get("website", ""),
                 "; ".join(f"{e['address']} ({e['status']})" for e in d.get("emails", [])),
                 "; ".join(d.get("phones", [])), d.get("confidence", "")] for d in db.list_leads(limit=0)]
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(safe_row(r) for r in rows)
    log(f"wrote {len(rows)} {args.what} rows to {args.output}")
    return len(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description="Collect public business contact info for B2B marketing.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="find businesses in an area by category (OpenStreetMap)")
    d.add_argument("--country", required=True, help="country: an ISO code (US, NG, GB, DE...) or a name")
    d.add_argument("--region", help="state/province/nation within the country: a name (Texas) or ISO 3166-2 code (US-TX)")
    d.add_argument("--place", help="optional city or area name to narrow the search, e.g. Ikeja")
    d.add_argument("--area", dest="place", help=argparse.SUPPRESS)  # older spelling of --place
    d.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    d.add_argument("-o", "--output", default="seeds.csv")
    d.add_argument("--limit", type=int, help="check at most this many businesses")
    d.add_argument("--skip-checked", action="store_true",
                   help="skip businesses already checked on earlier runs, to find new ones (needs the database)")
    d.set_defaults(func=cmd_discover)

    s = sub.add_parser("scrape", help="collect contacts from business websites")
    s.add_argument("seeds", help="seeds CSV from 'discover', or a text file of URLs")
    s.add_argument("-o", "--output", default="leads.csv")
    s.add_argument("--delay", type=float, default=2.0, help="seconds between requests to one domain")
    s.add_argument("--workers", type=int, default=None,
                   help=f"sites to check at once (default {DEFAULT_WORKERS}, max {MAX_WORKERS}); each site is still "
                        "fetched politely, one page at a time")
    s.add_argument("--max-pages", type=int, default=4, help="most pages to fetch per site")
    s.add_argument("--thorough", action="store_true",
                   help="keep fetching contact pages even after an email on the business's own domain is found "
                        "(slower and uses more bandwidth; finds extra addresses)")
    s.add_argument("--exclude-personal", action="store_true", help="drop gmail/yahoo/outlook/etc. addresses")
    s.add_argument("--any-domain", action="store_true",
                   help="keep emails on other domains (default: only the business's own domain)")
    s.add_argument("--country", help="country for validating local phone numbers when the seeds lack one (default US)")
    s.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low",
                   help="drop leads below this level (high=own-domain email, medium=other email, low=phone only)")
    s.add_argument("--keep-chains", action="store_true",
                   help="keep chains/franchises (OSM brand tag, or a domain seen 3+ times in the seeds)")
    s.add_argument("--save-db", action="store_true", help="also save leads to MongoDB (SKRAPKIN_MONGO_URI)")
    s.add_argument("--region", default="", help="region label for saved leads when the seeds lack one")
    s.set_defaults(func=cmd_scrape)

    v = sub.add_parser("verify", help="verify stored emails with Hunter.io (filters unlikely ones first)")
    v.add_argument("--preview", action="store_true", help="show what would be checked; spends nothing")
    v.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    v.add_argument("--min-likelihood", type=int, help="only check emails scoring at least this (0-100)")
    v.add_argument("--max-lookups", type=int, help="cap on Hunter lookups for this run")
    v.set_defaults(func=cmd_verify)

    x = sub.add_parser("export", help="write stored leads or verified emails to a CSV")
    x.add_argument("what", choices=["verified", "leads"])
    x.add_argument("-o", "--output", default="export.csv")
    x.set_defaults(func=cmd_export)

    a = sub.add_parser("audit", help="sample leads for manual review, or score a reviewed sample")
    a.add_argument("file")
    a.add_argument("-n", type=int, default=50, help="sample size")
    a.add_argument("-o", "--output", default="audit.csv")
    a.add_argument("--seed", type=int, default=1)
    a.add_argument("--score", action="store_true", help="compute precision from a reviewed audit file")
    a.set_defaults(func=cmd_audit)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except DiscoveryError as e:
        sys.exit(str(e))
    except ValueError as e:
        p.error(str(e))


if __name__ == "__main__":
    main()
