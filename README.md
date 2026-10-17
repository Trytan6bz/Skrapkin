<p align="center">
  <img src="assets/banner.svg" alt="SKrapkin: a kraken scraping the surface of the globe" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-7df9ff?style=flat-square"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-7df9ff?style=flat-square">
  <img alt="249 countries" src="https://img.shields.io/badge/coverage-249%20countries-7df9ff?style=flat-square">
  <img alt="MongoDB" src="https://img.shields.io/badge/database-MongoDB-7df9ff?style=flat-square">
  <img alt="Docker Compose" src="https://img.shields.io/badge/docker-compose-7df9ff?style=flat-square">
  <img alt="Research use" src="https://img.shields.io/badge/purpose-research-b45ced?style=flat-square">
</p>

# SKrapkin

SKrapkin finds **publicly listed business contact details anywhere in the world** for B2B marketing research,
scores them, and verifies only the emails that are likely to be real, so you spend as few paid verification
credits as possible.

It is built for a specific job: a marketplace owner who wants to reach **businesses that buy in bulk**
(contractors and building suppliers, clothing retailers, toy and gift shops, and similar) and needs a clean list
of contacts without paying to verify every junk address a scraper turns up.

```bash
cp .env.example .env     # set MONGO_PASSWORD
docker compose up -d --build
# open http://localhost:8080
```

> [!IMPORTANT]
> **Research tool. Read the [disclaimer](#disclaimer-and-responsible-use) before you use it.**
> The creator and contributors are not liable for how it is used.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Disclaimer and responsible use](#disclaimer-and-responsible-use)
- [Setup](#setup)
  - [Option A: Docker Compose (recommended)](#option-a-docker-compose-recommended)
  - [Option B: Run with Python](#option-b-run-with-python)
  - [Connect Hunter.io](#connect-hunterio)
- [Using the web interface](#using-the-web-interface)
- [Sharing it with a team](#sharing-it-with-a-team)
- [Command line reference](#command-line-reference)
- [How it keeps verification costs down](#how-it-keeps-verification-costs-down)
- [Data model](#data-model)
- [Configuration](#configuration)
- [Limitations](#limitations)
- [Project layout](#project-layout)
- [Development](#development)
- [Contributing](#contributing)
- [License and attribution](#license-and-attribution)

---

## What it does

| Stage | What happens |
|---|---|
| **Discover** | Finds businesses by category in **any of 249 countries**, optionally narrowed to a region (state, province, nation, prefecture...) and a city or area, using [OpenStreetMap](https://www.openstreetmap.org) data through the Overpass API. Built-in categories: building materials and contractors, clothing retailers, toy and gift shops. |
| **Scrape** | Visits each business's own website (homepage plus up to three contact, about, team or support pages, recognised in about 15 languages) and collects public emails and phone numbers. It reads `mailto:` links, visible text, and `name [at] domain [dot] com` style obfuscation. |
| **Clean** | Drops chains and franchises, non-buyers (unions, schools, associations and similar, in several languages), social and listing pages, placeholder and system addresses, emails on dead domains, and invalid phone numbers. Phone numbers are read in the local format of the country you searched and normalised to E.164, so two formats of the same number count once. |
| **Store** | Saves every lead to **MongoDB** as it is found, merging repeat searches instead of duplicating them. |
| **Filter** | Scores each email locally for how likely it is to be a real, reachable business mailbox. Unlikely ones are never sent to a paid service. |
| **Verify** | Checks the survivors with the **[Hunter.io](https://hunter.io) Email Verifier**. Only emails Hunter reports as `valid` go into the separate **verified results** collection. |
| **Export** | Exports leads or verified emails to CSV (opens correctly in Excel, and safe against formula injection). |

It is a pure **Python** tool with three ways in: a **web interface** (the default with Docker), a **desktop
window**, and a **command line**. The database runs in **Docker Compose**.

### What it deliberately does not do

- It **does not ignore `robots.txt`**. Sites that disallow crawling are skipped. There is no switch to override this.
- It **does not collect individuals' personal contact details**. It targets businesses' published business contacts.
  Personal data about private shoppers is not something a public scraper should gather, and there is no public list
  of "people who buy online" anyway.
- It **does not guess or generate email addresses** (no `first.last@company.com` pattern guessing).
- It **does not verify webmail addresses** (Gmail, Yahoo, Outlook, GMX, Mail.ru and similar) with a paid service,
  because a mailbox check cannot confirm them. They stay in your leads, marked `webmail`.

---

## How it works

```mermaid
flowchart LR
    A["OpenStreetMap<br/>discover businesses"] --> B["Business websites<br/>read contact pages"]
    B --> C["Clean<br/>junk, chains, phones"]
    C --> D[("MongoDB<br/>leads")]
    D --> E{"Likely real?<br/>local score"}
    E -- no --> F["Skipped, free"]
    E -- yes --> G["Hunter.io<br/>email verifier"]
    G --> H[("verified_emails<br/>valid only")]
```

**Confidence levels** on each lead:

| Level | Meaning |
|---|---|
| `high` | A deliverable email on the business's own domain. |
| `medium` | A deliverable email on another domain (for example Gmail). |
| `low` | A phone number only. |

**Politeness:** one request per domain every 2 seconds by default, `robots.txt` honoured, and a descriptive
`User-Agent`.

---

## Disclaimer and responsible use

**SKrapkin was created for research and educational purposes.**

- The creator and every contributor provide this software **"as is", without warranty of any kind**, and are
  **not liable** for any claim, damage, loss, fine, account suspension, or other consequence arising from its use
  or misuse. This notice sits alongside the [MIT License](LICENSE), which governs your rights and the warranty
  disclaimer in full.
- **You alone are responsible** for how you use it and for complying with the laws, regulations, and terms of
  service that apply to you and to the sites and services you touch, in every country you search.
- Nothing in this repository is legal advice. If you plan commercial outreach, talk to a qualified lawyer.

**Things you are responsible for checking before you run it or email anyone:**

- **Website terms of service and `robots.txt`.** SKrapkin honours `robots.txt`, but a site's terms may still restrict
  automated access.
- **Anti-spam and privacy law** where you and your recipients are, for example CAN-SPAM (US), GDPR and PECR
  (EU/UK), CASL (Canada), POPIA (South Africa), NDPA (Nigeria), LGPD (Brazil), and the many others. Business email is
  treated more permissively in some places and far more strictly in others. Include a real sender identity, a
  physical address where required, and a working opt-out, and honour opt-outs promptly.
- **Hunter.io's terms and your plan limits.** Verification uses your own key and your own credits.
- **OpenStreetMap's licence.** OSM data is © OpenStreetMap contributors and available under the
  [ODbL](https://www.openstreetmap.org/copyright). If you publish or share a database derived from it, you must
  give attribution and may need to share alike.
- **Data protection.** Contact lists are personal data in many jurisdictions (a work email often names a person).
  Store them securely, keep only what you need, and delete it when you no longer do.

**Please use it considerately:** keep the default delay, scrape only what you need, and do not point it at sites
that have asked not to be scraped. SKrapkin is not affiliated with Hunter.io, MongoDB, or OpenStreetMap.

---

## Setup

You need three things for the full workflow: **the app**, **a MongoDB database**, and (for verification) **a
Hunter.io API key**. Discovery and scraping work without the database or a Hunter key and write CSV files.

### Option A: Docker Compose (recommended)

One command starts MongoDB (password-protected, localhost-only) and the web interface.

**Requirements:** [Docker](https://docs.docker.com/get-docker/) with Compose v2 (`docker compose version`).

```bash
git clone https://github.com/Trytan6bz/leads-scrapper.git
cd leads-scrapper

# 1. Create your settings file and set a password (letters and digits only)
cp .env.example .env
#    edit .env, or generate a password:  openssl rand -hex 16

# 2. Build and start everything (first run builds the image, so it takes a minute)
docker compose up -d --build
```

Open **http://localhost:8080**. The status pills at the top should read *Database: connected*.
Search results are kept in a Docker volume and downloaded from the page (the **Download CSV** button on the
Find leads tab, and **Export CSV** on the Leads and Verified results tabs).

**Housekeeping**

```bash
docker compose ps                  # status (both services should be "healthy")
docker compose logs -f web         # web interface logs
docker compose down                # stop; your data is kept
docker compose down -v             # stop AND DELETE all stored leads, verified emails, and settings
```

**What runs**

| Service | Purpose | Port (this computer only) |
|---|---|---|
| `mongo` | The database, with a password from `.env`. | `27017` (`MONGO_PORT`) |
| `web` | The web interface. | `8080` (`WEB_PORT`) |
| `skrapkin` | Optional command line (profile `cli`). | none |

**Optional: the command line inside Docker.** Create the data folder first so Docker doesn't create it as root:

```bash
mkdir -p data
docker compose run --rm skrapkin discover --country DE --region Bayern --category clothing --limit 50 -o seeds.csv
docker compose run --rm skrapkin scrape seeds.csv -o leads.csv --save-db
docker compose run --rm skrapkin verify --preview     # free: shows what would be sent to Hunter
docker compose run --rm skrapkin verify --yes         # spends Hunter credits (needs HUNTER_API_KEY in .env)
docker compose run --rm skrapkin export verified -o verified.csv
```

**Use the desktop window with the Docker database.** Run the window with Python (Option B), open **Settings**, and
enter:

```
mongodb://skrapkin:YOUR_PASSWORD@localhost:27017/?authSource=admin
```

(If you changed `MONGO_USER` or `MONGO_PORT` in `.env`, use those.)

### Option B: Run with Python

**Requirements:** Python 3.10 or newer. The desktop window also needs Tk.

```bash
git clone https://github.com/Trytan6bz/leads-scrapper.git
cd leads-scrapper
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then pick an interface:

```bash
python -m skrapkin.web             # web interface at http://localhost:8080
python run_gui.py                  # desktop window (needs Tk, see below)
python -m skrapkin.cli --help      # command line
```

Tk is included with the python.org installers for Windows and macOS. On Debian/Ubuntu run
`sudo apt install python3-tk`; on Fedora run `sudo dnf install python3-tkinter`.

Connect a database in **Settings**, either:

- the Docker one from Option A (`docker compose up -d mongo`, then use the address above), or
- a free **[MongoDB Atlas](https://www.mongodb.com/atlas)** cluster (paste its `mongodb+srv://...` connection
  string; a whole team can share one), or
- a local [MongoDB Community](https://www.mongodb.com/try/download/community) install (default address
  `mongodb://localhost:27017`).

Finding leads works without a database (CSV files only), but the Leads, Verify and Verified Results tabs need one.

### Connect Hunter.io

1. Create an account at [hunter.io](https://hunter.io) and copy your API key from
   [hunter.io/api-keys](https://hunter.io/api-keys).
2. In the app, open **Verify emails**, paste the key, and click **Save & test**. The test calls Hunter's free
   account endpoint (no credits used) and shows your plan and remaining verifications.
3. For Docker or headless use, set `HUNTER_API_KEY` in `.env` (or your shell) instead. This is the preferred way.

**Where a saved key lives:** in your operating system's keychain (Windows Credential Manager, macOS Keychain, or the
Linux Secret Service) when one is available. If there isn't one, as in Docker, it falls back to a file with
owner-only permissions (`~/.skrapkin/secrets.json`, or inside the `skrapkin-config` Docker volume), which is
**plaintext**, so protect it. The key is sent to Hunter in an `X-API-KEY` header, never in a URL.

---

## Using the web interface

| Tab | What you do there |
|---|---|
| **Find leads** | Pick a business type, a **country**, an optional **region**, and an optional **city or area**. Cap how many businesses to check and choose what to keep. Results stream into a table as they are found. Optionally save to the database and verify automatically afterwards. |
| **Leads** | Browse every saved lead. Search as you type, filter by type, country, region, or email status, click a heading to sort, tick rows to copy their emails or delete them, and export to CSV. |
| **Verify emails** | Save your Hunter key, set your cost controls, then **Preview (free)** to see exactly which emails would be sent and why the rest are skipped. **Verify now** shows how many credits it will use and asks you to confirm. |
| **Verified results** | The separate list of emails Hunter confirmed as valid. Search, filter, copy all addresses, remove entries, or export to CSV. |
| **Settings** | MongoDB connection and database name. |

**Choosing where to search.** The region list comes from ISO 3166-2 (US states, Canadian provinces, UK nations,
German Länder, Nigerian states, Indian states, Japanese prefectures, and so on, for every country that defines
them). Use **City or area** to narrow further, for example *Ikeja* inside *Lagos*, or *Manchester* inside
*England*. Leaving the region empty searches the whole country, which returns a **sample**, not everything.

The desktop window (`python run_gui.py`) has the same five tabs and the same options.

---

## Sharing it with a team

By default the web interface answers only on your own computer, and Docker publishes it on `127.0.0.1` only.
It exposes your leads and can spend your Hunter credits, so treat any change to that seriously.

Built-in protections:

- **Host check.** Requests whose `Host` header isn't `localhost`, `127.0.0.1` or `[::1]` are refused (this blocks
  DNS-rebinding attacks). Add hostnames people will use with `SKRAPKIN_ALLOWED_HOSTS`.
- **Cross-site protection.** Every change must carry a custom header that other websites cannot send from a
  visitor's browser.
- **Strict content security policy.** The page loads no external scripts, styles, or fonts, and everything scraped
  from websites is displayed as plain text, never as HTML.
- **Optional password.** Set `SKRAPKIN_WEB_PASSWORD` (and optionally `SKRAPKIN_WEB_USER`, default `skrapkin`) to
  require HTTP Basic sign-in for everything except the health check.

To let colleagues connect over a network:

1. Set a long `SKRAPKIN_WEB_PASSWORD` and the hostname in `SKRAPKIN_ALLOWED_HOSTS` in `.env`.
2. Change the web port mapping in `docker-compose.yml` from `127.0.0.1:${WEB_PORT:-8080}` to `${WEB_PORT:-8080}`.
3. **Put it behind HTTPS** (a reverse proxy such as Caddy or nginx, or a VPN). HTTP Basic sign-in sent over plain
   HTTP is not encrypted. Do not expose it directly to the internet.

Alternatively, point each person's own copy at one shared MongoDB Atlas database.

---

## Command line reference

Run as `python -m skrapkin.cli <command>` (or `docker compose run --rm skrapkin <command>`).

| Command | Purpose | Key options |
|---|---|---|
| `discover` | Find businesses and write a seeds CSV (which records the country and region). | `--country` (required: ISO code like `NG` or a name), `--region` (name or ISO 3166-2 code, e.g. `Lagos` or `NG-LA`), `--place` (city or area), `--category building\|clothing\|toys`, `--limit N`, `-o FILE` |
| `scrape SEEDS` | Collect contacts from the seeds' websites and write a leads CSV. | `--save-db`, `--min-confidence low\|medium\|high`, `--exclude-personal`, `--keep-chains`, `--any-domain`, `--delay S`, `--max-pages N`, `--country` (phone format fallback), `--region` (label fallback) |
| `verify` | Filter stored emails locally, then verify the survivors with Hunter. | `--preview` (free), `--yes`, `--min-likelihood 0-100`, `--max-lookups N` |
| `export {leads,verified}` | Write stored leads or verified emails to CSV. | `-o FILE` |
| `audit FILE` | Sample leads for manual review, then score the reviewed sample to measure real precision. | `-n SIZE`, `--score` |

Examples:

```bash
python -m skrapkin.cli discover --country NG --region Lagos --place Ikeja --category clothing --limit 100 -o seeds.csv
python -m skrapkin.cli discover --country GB --region England --place Manchester --category toys -o seeds.csv
python -m skrapkin.cli scrape seeds.csv -o leads.csv --save-db --min-confidence medium
python -m skrapkin.cli verify --preview
HUNTER_API_KEY=... python -m skrapkin.cli verify --yes
python -m skrapkin.cli export verified -o verified.csv
```

(`--area` still works as an older spelling of `--place`.)

**Measuring accuracy.** There is no way to tell automatically whether a lead is "legitimate", so use `audit`:
sample 50 leads, mark each `y` or `n` by hand (right business? working contact? would they buy in bulk?), then
run `audit --score` for overall and per-confidence precision.

---

## How it keeps verification costs down

Every email goes through free local checks first. Only emails that pass are sent to Hunter.

| Layer | Effect |
|---|---|
| **Junk filter** | Drops invalid formats, placeholders (`name@example.com`), system addresses (`noreply@`), error-tracking addresses, disposable providers, and random-looking names. |
| **Domain check** | Drops addresses on domains that cannot receive mail (a DNS lookup). |
| **Likelihood score** | Scores the rest from 0 to 100 and sends only those at or above your threshold (default **60**). |
| **Webmail rule** | Gmail, Yahoo, Outlook, GMX, Mail.ru, QQ and similar are never sent: a mailbox check cannot confirm them. |
| **Result cache** | Reuses a stored Hunter result for 30 days, so repeat runs cost nothing. `unknown` results are re-checked. |
| **Accept-all rule** | If one address on a domain turns out to accept everything, the other addresses on it are not looked up separately. |
| **Run cap** | Never uses more than your per-run limit (default **100**), and never more than your remaining Hunter balance (read with the free account call). |
| **Best first** | Spends the budget on the highest-scoring emails first. |

**Likelihood score:**

| Signal | Points |
|---|---|
| Base | 40 |
| On the business's own domain | +30 |
| Published by the business in OpenStreetMap | +25 |
| On a different company's domain | −15 |
| Shared mailbox (`info@`, `sales@`, `kontakt@`, `ventas@`, `vendas@`...) | +10 |
| Looks like a person's name (`john.smith@`) | +5 |
| Domain accepts email | +10 |
| Domain check inconclusive | −10 |

An own-domain shared mailbox scores about 90. Another company's domain scores about 45 and is skipped.
**Preview (free)** shows every decision before anything is spent.

---

## Data model

MongoDB, database `skrapkin` by default.

| Collection | Contents |
|---|---|
| `leads` | One document per business: `business`, `website`, `category`, `country` (ISO code), `region`, `city`, `phones`, `confidence`, `source_pages`, timestamps, and an `emails` list of `{address, source, status, likelihood, note}`. |
| `email_checks` | Every Hunter result, keyed by address, so nothing is paid for twice. |
| `verified_emails` | **Only addresses Hunter reported as `valid`**, with the business, country, region, phones, score, and verification time. This is the list to use for outreach. |

**Email statuses** on a lead:

| Status | Meaning |
|---|---|
| `unchecked` | Not yet evaluated. |
| `filtered` | Skipped for free as unlikely to be real (the reason is stored in `note`). |
| `webmail` | A free-mail address; cannot be confirmed by a mailbox check. |
| `valid` | Hunter confirmed it. Also filed in `verified_emails`. |
| `invalid` | Hunter found it undeliverable (or disposable). |
| `accept_all` | The domain accepts any address, so a mailbox check proves nothing. Treat as risky. |
| `unknown` | Hunter could not decide. Re-checked on the next run. |
| `claimed` | The owner asked Hunter to stop processing it (HTTP 451). Never stored as verified. |

---

## Configuration

Settings live in `~/.skrapkin/config.json` (override the folder with `SKRAPKIN_HOME`). Environment variables win
over stored values and are never copied into the keychain or config file.

| Setting | Env var | Default |
|---|---|---|
| MongoDB address | `SKRAPKIN_MONGO_URI` | `mongodb://localhost:27017` |
| Hunter API key | `HUNTER_API_KEY` | none |
| Config folder | `SKRAPKIN_HOME` | `~/.skrapkin` |
| CSV output folder | `SKRAPKIN_OUTPUT_DIR` | `~/Documents/SKrapkin` |
| Web interface address | `SKRAPKIN_WEB_HOST`, `SKRAPKIN_WEB_PORT` | `127.0.0.1`, `8080` |
| Web interface password | `SKRAPKIN_WEB_PASSWORD`, `SKRAPKIN_WEB_USER` | none, `skrapkin` |
| Extra allowed hostnames | `SKRAPKIN_ALLOWED_HOSTS` (comma-separated) | none |
| Minimum likelihood score | (Verify tab / `--min-likelihood`) | `60` |
| Max Hunter lookups per run | (Verify tab / `--max-lookups`) | `100` |
| Reuse Hunter results for | config file `recheck_days` | `30` days |

Docker Compose reads `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_PORT`, `WEB_PORT`, `HUNTER_API_KEY`,
`SKRAPKIN_WEB_PASSWORD`, and `SKRAPKIN_ALLOWED_HOSTS` from `.env`. Never commit `.env`; it is git-ignored.

---

## Limitations

- **Coverage depends on OpenStreetMap, and it varies a lot by country.** It is strong in much of Europe and North
  America and thinner in many other regions. A search in a thinly mapped area can return only a handful of
  businesses (a test search for building businesses in Lagos, Nigeria found one with contact details). Few listings
  include an email, so most contacts come from scraping websites.
- **Searching a whole country returns a sample.** The server returns matches in no particular order and the app
  caps how many it asks for. Pick a region or city for a fuller picture.
- **Regions are first-level ISO 3166-2 divisions.** They are listed by their ISO names (for example
  *Mahārāshtra*). Region matching accepts plain spellings, but a country with no ISO regions only offers whole-country
  and city searches.
- **Some sites will be skipped.** Sites that disallow crawling in `robots.txt`, or that fail to load, produce
  no website contacts. The app falls back to whatever OpenStreetMap lists.
- **No JavaScript rendering.** Contacts that only appear after a script runs are not found.
- **Contact-page detection covers about 15 languages** (English, German, Spanish, Portuguese, Italian, French, Dutch,
  Polish, Russian, Turkish, Chinese, Japanese, Korean, Arabic and a few more). Sites in other languages may yield
  fewer contacts.
- **Three categories** are built in (building, clothing, toys). More means adding OSM tag filters in
  `skrapkin/discover.py`.
- **Buyer fit is a guess.** Category tags are the only signal. A one-person handyman and a large supplier look
  alike. Staff emails (`firstname@`) can be less useful than shared mailboxes.
- **Verification is not a guarantee.** A `valid` result is Hunter's assessment at that moment. Mailboxes change,
  and `accept_all` domains cannot be confirmed at all.
- **Public OpenStreetMap servers are shared and sometimes busy.** The app retries and falls back to a second server,
  and tells you plainly if both are unavailable.

---

## Project layout

```
skrapkin/
  discover.py    OpenStreetMap discovery by country, region and place
  regions.py     countries, ISO 3166-2 regions, safe handling of place names
  data/regions.json   generated country and region data (scripts/build_regions.py)
  fetcher.py     polite HTTP: robots.txt, per-domain rate limit
  extract.py     emails, phones (any country), names, contact-page links
  validate.py    junk filters, DNS check, phone validation, chain detection, public-suffix domains
  prefilter.py   local likelihood score (decides what is worth a paid lookup)
  hunter.py      Hunter.io client (Email Verifier + Account)
  verifier.py    verification plan and run
  db.py          MongoDB storage
  config.py      settings and secret storage
  csvsafe.py     spreadsheet formula-injection protection for CSV output
  jobs.py        orchestration shared by the interfaces
  cli.py         command line
  web/           web interface (Flask API + static page)
  gui.py, gui_widgets.py   desktop window
tests/           pytest suite
scripts/         build_regions.py (refreshes the region data; needs pycountry)
assets/          banner
Dockerfile, docker-compose.yml, .env.example
```

---

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

The database tests also run against a real MongoDB when `SKRAPKIN_TEST_MONGO_URI` is set; otherwise they use an
in-memory fake:

```bash
docker run -d --rm --name skrapkin-test-mongo -p 127.0.0.1:27018:27017 mongo:7
SKRAPKIN_TEST_MONGO_URI=mongodb://127.0.0.1:27018 pytest -q
docker stop skrapkin-test-mongo
```

Tests never call the live Hunter API or the live internet; they use fakes that return the documented responses.
The suite covers the logic, the web API and its security checks, and the CLI. The browser page itself is plain
HTML, CSS and JavaScript with no build step; it has no automated browser tests in this repository.

To refresh the country and region data: `pip install pycountry && python scripts/build_regions.py`.

---

## Contributing

Issues and pull requests are welcome. Please keep the safeguards intact (`robots.txt`, rate limiting, no personal
data collection, the web interface's host check and content security policy), add tests for behaviour changes, and
run `pytest -q` before opening a PR. By contributing you agree your work is released under the MIT License.

---

## License and attribution

Released under the **[MIT License](LICENSE)**, so you can use, copy, modify, and distribute it for personal and
commercial purposes, provided the licence and copyright notice are included. The software is provided without
warranty, as described in the [disclaimer](#disclaimer-and-responsible-use) and the licence text.

Business discovery uses data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available
under the Open Database Licence. Email verification uses the [Hunter.io](https://hunter.io) API. Country and region
names come from [ISO 3166](https://www.iso.org/iso-3166-country-codes.html) via
[pycountry](https://github.com/pycountry/pycountry). The banner wordmark is set in
[Montserrat](https://github.com/JulietaUla/Montserrat) (SIL Open Font License).
