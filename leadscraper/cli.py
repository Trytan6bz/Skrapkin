"""Usage:
    python -m leadscraper.cli discover --area Houston --country US --category toys -o seeds.csv
    python -m leadscraper.cli scrape seeds.csv -o leads.csv --country US
    python -m leadscraper.cli audit leads.csv -n 50 -o audit.csv      # then fill in is_legit (y/n)
    python -m leadscraper.cli audit audit.csv --score                 # prints precision
"""

import argparse
import csv
import random
import sys
from urllib.parse import urlparse

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


def cmd_scrape(args, log=print, progress=lambda done, total: None, should_stop=lambda: False):
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
    s.set_defaults(func=cmd_scrape)

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
