"""Usage:
    python -m skrapkin.cli discover --area Houston --country US --category toys -o seeds.csv
    python -m skrapkin.cli scrape seeds.csv -o leads.csv --country US
    python -m skrapkin.cli audit leads.csv -n 50 -o audit.csv      # then fill in is_legit (y/n)
    python -m skrapkin.cli audit audit.csv --score                 # prints precision

    # with MongoDB (see docker-compose.yml) and a Hunter key in HUNTER_API_KEY:
    python -m skrapkin.cli scrape seeds.csv --save-db --state Texas
    python -m skrapkin.cli verify --preview                        # free: shows what would be checked
    python -m skrapkin.cli verify --yes                            # spends Hunter credits
    python -m skrapkin.cli export verified -o verified.csv
"""

import argparse
import csv
import random
import sys
from urllib.parse import urlparse

from . import config
from .discover import CATEGORIES, discover
from .extract import (contact_links, extract_emails, extract_name, extract_phones,
                      filter_free_mail, same_site_emails)
from .fetcher import Fetcher
from .validate import (chain_domains, confidence, is_aggregator, is_junk_email, is_non_buyer, mx_status,
                       normalize_phone, registered_domain)

SEED_FIELDS = ["category", "business", "website", "phone", "email", "city", "brand"]
MAX_SCRAPED_PHONES = 3
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
LEAD_FIELDS = ["category", "business", "website", "emails", "phones", "city", "confidence", "source_pages"]


def scrape_site(fetcher, url, max_pages, include_personal, any_domain=False):
    html = fetcher.get(url)
    if html is None:
        return None
    pages, htmls = [url], [html]
    for link in contact_links(html, url)[: max_pages - 1]:
        page = fetcher.get(link)
        if page is not None:
            pages.append(link)
            htmls.append(page)
    emails, phones = set(), []
    for h in htmls:
        emails.update(extract_emails(h, include_personal))
        phones.extend(p for p in extract_phones(h) if p not in phones)
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


def cmd_discover(args, log=print):
    leads = discover(args.area, args.category, args.country)
    seen, rows = set(), []
    for lead in leads:
        key = (lead["business"].lower(), lead["website"].lower())
        if key not in seen and (lead["website"] or lead["phone"] or lead["email"]):
            seen.add(key)
            rows.append(lead)
    limit = getattr(args, "limit", None)
    if limit and len(rows) > limit:
        # Businesses with a website can yield emails, so keep those first.
        rows = sorted(rows, key=lambda r: not r["website"])[:limit]
        log(f"Found more than {limit} businesses; checking the first {limit}.")
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SEED_FIELDS)
        w.writeheader()
        w.writerows(rows)
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


def cmd_scrape(args, log=print, progress=lambda done, total: None, should_stop=lambda: False,
               on_lead=None):
    db = on_lead_db = None
    if getattr(args, "save_db", False):
        from .jobs import connect_db  # lazy: jobs imports this module
        db = connect_db(config.Config.load())
        search = {"state": getattr(args, "state", "") or "", "category": ""}
        on_lead_db = lambda lead: db.upsert_lead(lead, search)  # noqa: E731
    fetcher = Fetcher(delay=args.delay)
    all_seeds = read_seeds(args.seeds)
    chains = set() if args.keep_chains else chain_domains(all_seeds)
    seen, rows, dropped = set(), [], {"non_buyer": 0, "chain": 0, "aggregator": 0, "no_contact": 0, "low_confidence": 0}
    for i, seed in enumerate(all_seeds):
        if should_stop():
            log("Stopped early; saving what was found so far.")
            break
        progress(i, len(all_seeds))
        site = seed.get("website", "").strip()
        if is_non_buyer(seed.get("business")):
            dropped["non_buyer"] += 1
            continue
        if not args.keep_chains and (seed.get("brand") or (site and registered_domain(site) in chains)):
            dropped["chain"] += 1
            continue
        if site and is_aggregator(site):
            site = ""  # keep the OSM phone/email but don't crawl a social/listing page
            dropped["aggregator"] += 1
        osm_emails = filter_free_mail(
            {e.strip().lower() for e in seed.get("email", "").split(";") if e.strip()},
            not args.exclude_personal)
        osm_phones = {p.strip() for p in seed.get("phone", "").split(";") if p.strip()}
        result = None
        if site:
            url = site if site.startswith("http") else "https://" + site
            domain = urlparse(url).netloc
            if domain in seen:
                continue
            seen.add(domain)
            result = scrape_site(fetcher, url, args.max_pages, not args.exclude_personal, args.any_domain)
            if result is None:
                log(f"skipped {url} (blocked by robots.txt or unreachable)")
        emails, own_domain = clean_emails(osm_emails | (result["emails"] if result else set()), site)
        phones = clean_phones(osm_phones | (result["phones"] if result else set()), args.country)
        level = confidence(emails, phones, own_domain)
        if not level:
            dropped["no_contact"] += 1
            continue
        if CONFIDENCE_RANK[level] < CONFIDENCE_RANK[args.min_confidence]:
            dropped["low_confidence"] += 1
            continue
        rows.append({
            "category": seed.get("category", ""),
            "business": seed.get("business") or (result["name"] if result else ""),
            "website": site,
            "emails": "; ".join(sorted(emails)),
            "phones": "; ".join(sorted(phones)),
            "city": seed.get("city", ""),
            "confidence": level,
            "source_pages": "; ".join(result["pages"]) if result else "openstreetmap",
        })
        log(f"[{level}] {rows[-1]['business'] or site}: {rows[-1]['emails'] or rows[-1]['phones']}")
        if on_lead or on_lead_db:
            sources = {e: "site" if result and e in result["emails"] else "osm" for e in emails}
            lead = {**rows[-1], "email_sources": sources}
            for callback in (on_lead_db, on_lead):
                if callback:
                    callback(lead)

    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
        w.writeheader()
        w.writerows(rows)
    progress(len(all_seeds), len(all_seeds))
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
        w.writerows(sample)
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
        header = ["email", "business", "state", "city", "website", "phones", "score", "verified_at"]
        rows = [[d["email"], d.get("business", ""), d.get("state", ""), d.get("city", ""), d.get("website", ""),
                 "; ".join(d.get("phones", [])), d.get("score", ""), d["verified_at"].isoformat()]
                for d in db.list_verified(limit=0)]
    else:
        header = ["business", "state", "city", "website", "emails", "phones", "confidence"]
        rows = [[d.get("business", ""), d.get("state", ""), d.get("city", ""), d.get("website", ""),
                 "; ".join(f"{e['address']} ({e['status']})" for e in d.get("emails", [])),
                 "; ".join(d.get("phones", [])), d.get("confidence", "")] for d in db.list_leads(limit=0)]
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    log(f"wrote {len(rows)} {args.what} rows to {args.output}")
    return len(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description="Collect public business contact info for B2B marketing.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="find businesses in an area by category (OpenStreetMap)")
    d.add_argument("--area", required=True, help="city or region name, e.g. Houston")
    d.add_argument("--country", help="2-letter country code to disambiguate, e.g. US")
    d.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    d.add_argument("-o", "--output", default="seeds.csv")
    d.add_argument("--limit", type=int, help="check at most this many businesses")
    d.set_defaults(func=cmd_discover)

    s = sub.add_parser("scrape", help="collect contacts from business websites")
    s.add_argument("seeds", help="seeds CSV from 'discover', or a text file of URLs")
    s.add_argument("-o", "--output", default="leads.csv")
    s.add_argument("--delay", type=float, default=2.0, help="seconds between requests to one domain")
    s.add_argument("--max-pages", type=int, default=4, help="pages to fetch per site")
    s.add_argument("--exclude-personal", action="store_true", help="drop gmail/yahoo/outlook/etc. addresses")
    s.add_argument("--any-domain", action="store_true",
                   help="keep emails on other domains (default: only the business's own domain)")
    s.add_argument("--country", default="US", help="2-letter region used to validate phone numbers")
    s.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low",
                   help="drop leads below this level (high=own-domain email, medium=other email, low=phone only)")
    s.add_argument("--keep-chains", action="store_true",
                   help="keep chains/franchises (OSM brand tag, or a domain seen 3+ times in the seeds)")
    s.add_argument("--save-db", action="store_true", help="also save leads to MongoDB (SKRAPKIN_MONGO_URI)")
    s.add_argument("--state", default="", help="label for saved leads, e.g. Texas (used with --save-db)")
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
    args.func(args)


if __name__ == "__main__":
    main()
