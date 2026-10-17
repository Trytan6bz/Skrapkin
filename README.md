<p align="center">
  <img src="assets/banner.svg" alt="SKrapkin: a kraken scraping the surface of the globe" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-7df9ff?style=flat-square"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-7df9ff?style=flat-square">
  <img alt="MongoDB" src="https://img.shields.io/badge/database-MongoDB-7df9ff?style=flat-square">
  <img alt="Docker Compose" src="https://img.shields.io/badge/docker-compose-7df9ff?style=flat-square">
  <img alt="Research use" src="https://img.shields.io/badge/purpose-research-b45ced?style=flat-square">
</p>

# SKrapkin

SKrapkin finds **publicly listed business contact details** for B2B marketing research, scores them, and
verifies only the emails that are likely to be real, so you spend as few paid verification credits as possible.

It is built for a specific job: a marketplace owner who wants to reach **businesses that buy in bulk**
(contractors and building suppliers, clothing retailers, toy and gift shops, and similar) and needs a clean list
of contacts without paying to verify every junk address a scraper turns up.

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
- [Using the desktop app](#using-the-desktop-app)
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
| **Discover** | Finds businesses in a US state by category (building materials and contractors, clothing retailers, toy and gift shops) using [OpenStreetMap](https://www.openstreetmap.org) data through the Overpass API. |
| **Scrape** | Visits each business's own website (homepage plus up to three contact, about, team or support pages) and collects public emails and phone numbers. It reads `mailto:` links, visible text, and `name [at] domain [dot] com` style obfuscation. |
| **Clean** | Drops chains and franchises, non-buyers (unions, schools, associations and similar), social and listing pages, placeholder and system addresses, emails on dead domains, and invalid phone numbers. Phone numbers are normalised to E.164, so two formats of the same number count once. |
| **Store** | Saves every lead to **MongoDB** as it is found, merging repeat searches instead of duplicating them. |
| **Filter** | Scores each email locally for how likely it is to be a real, reachable business mailbox. Unlikely ones are never sent to a paid service. |
| **Verify** | Checks the survivors with the **[Hunter.io](https://hunter.io) Email Verifier**. Only emails Hunter reports as `valid` go into the separate **verified results** collection. |
| **Export** | Exports leads or verified emails to CSV (opens correctly in Excel). |

It is a pure **Python** tool: a **desktop app** (Tk window, five tabs) and a **command-line tool**, with the
database running in **Docker Compose**.

### What it deliberately does not do

- It **does not ignore `robots.txt`**. Sites that disallow crawling are skipped. There is no switch to override this.
- It **does not collect individuals' personal contact details**. It targets businesses' published business contacts.
  Personal data about private shoppers is not something a public scraper should gather, and there is no public list
  of "people who buy online" anyway.
- It **does not guess or generate email addresses** (no `first.last@company.com` pattern guessing).
- It **does not verify webmail addresses** (Gmail, Yahoo, Outlook and similar) with a paid service, because a mailbox
  check cannot confirm them. They stay in your leads, marked `webmail`.

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
  service that apply to you and to the sites and services you touch.
- Nothing in this repository is legal advice. If you plan commercial outreach, talk to a qualified lawyer.

**Things you are responsible for checking before you run it or email anyone:**

- **Website terms of service and `robots.txt`.** SKrapkin honours `robots.txt`, but a site's terms may still restrict
  automated access.
- **Anti-spam and privacy law** where you and your recipients are, for example CAN-SPAM (US), GDPR and PECR
  (EU/UK), CASL (Canada). Business email is treated more permissively in some places and far more strictly in
  others. Include a real sender identity, a physical address where required, and a working opt-out, and honour
  opt-outs promptly.
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

Docker Compose runs MongoDB for you, with a password and a localhost-only port, and gives you an optional
containerised command line. This is the easiest way to get a database.

**Requirements:** [Docker](https://docs.docker.com/get-docker/) with Compose v2 (`docker compose version`).

```bash
git clone https://github.com/Trytan6bz/leads-scrapper.git
cd leads-scrapper

# 1. Create your settings file and set a password (letters and digits only)
cp .env.example .env
#    edit .env, or generate a password:  openssl rand -hex 16

# 2. Start the database (bound to 127.0.0.1 only; data persists in a Docker volume)
docker compose up -d
```

**Run the command line inside Docker.** Files are read and written in `./data`:

```bash
docker compose run --rm skrapkin discover --area Ohio --country US --category toys --limit 50 -o seeds.csv
docker compose run --rm skrapkin scrape seeds.csv -o leads.csv --save-db --state Ohio
docker compose run --rm skrapkin verify --preview     # free: shows what would be sent to Hunter
docker compose run --rm skrapkin verify --yes         # spends Hunter credits (needs HUNTER_API_KEY in .env)
docker compose run --rm skrapkin export verified -o verified.csv
```

**Use the desktop app with the Docker database.** Run the app with Python (Option B), open
**Settings**, and enter:

```
mongodb://skrapkin:YOUR_PASSWORD@localhost:27017/?authSource=admin
```

(If you changed `MONGO_USER` or `MONGO_PORT` in `.env`, use those.)

**Linux only, experimental: the window inside Docker.** The `gui` profile shows the desktop window through X11:

```bash
xhost +local:docker
docker compose run --rm gui
```

If no window appears (Wayland setups vary), run the app from source (Option B) instead.

**Housekeeping**

```bash
docker compose ps                  # status
docker compose logs -f mongo       # database logs
docker compose down                # stop; your data is kept
docker compose down -v             # stop AND DELETE all stored leads and verified emails
```

### Option B: Run with Python

**Requirements:** Python 3.10 or newer, and Tk.

- Windows and macOS: Tk is included with the python.org installer.
- Debian/Ubuntu: `sudo apt install python3-tk`
- Fedora: `sudo dnf install python3-tkinter`

```bash
git clone https://github.com/Trytan6bz/leads-scrapper.git
cd leads-scrapper
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_gui.py
```

Then connect a database in the **Settings** tab, either:

- the Docker one from Option A, or
- a free **[MongoDB Atlas](https://www.mongodb.com/atlas)** cluster (paste its `mongodb+srv://...` connection
  string; a whole team can share one), or
- a local [MongoDB Community](https://www.mongodb.com/try/download/community) install (default address
  `mongodb://localhost:27017`).

The app works without a database for finding leads (CSV files only), but the Leads, Verify and Verified Results
tabs need one.

### Connect Hunter.io

1. Create an account at [hunter.io](https://hunter.io) and copy your API key from
   [hunter.io/api-keys](https://hunter.io/api-keys).
2. In the app, open **Verify Emails**, paste the key, and click **Save & test**. The test calls Hunter's free
   account endpoint (no credits used) and shows your plan and remaining verifications.
3. For Docker or headless use, set `HUNTER_API_KEY` in `.env` (or your shell) instead.

**Where the key is stored:** in your operating system's keychain (Windows Credential Manager, macOS Keychain, or the
Linux Secret Service) when one is available. If there isn't one, it falls back to
`~/.skrapkin/secrets.json` with owner-only permissions on Linux and macOS, which is **plaintext**, so protect
that folder. The key is sent in an `X-API-KEY` header, never in a URL.

---

## Using the desktop app

| Tab | What you do there |
|---|---|
| **Find Leads** | Pick a business type and a state, cap how many businesses to check, and choose what to keep. Results appear in a table as they are found. Optionally save to the database and verify automatically afterwards. |
| **Leads** | Browse every saved lead. Search as you type, filter by type, state, or email status, click a heading to sort, right-click to copy emails or open the website, and export to CSV. |
| **Verify Emails** | Save your Hunter key, set your cost controls, then **Preview (free)** to see exactly which emails would be sent and why the rest are skipped. **Verify now** shows how many credits it will use and asks you to confirm. |
| **Verified Results** | The separate list of emails Hunter confirmed as valid. Search, filter, copy all addresses, remove entries, or export to CSV. |
| **Settings** | MongoDB connection and database name. |

---

## Command line reference

Run as `python -m skrapkin.cli <command>` (or `docker compose run --rm skrapkin <command>`).

| Command | Purpose | Key options |
|---|---|---|
| `discover` | Find businesses in an area from OpenStreetMap and write a seeds CSV. | `--area` (state or place), `--country US`, `--category building\|clothing\|toys`, `--limit N`, `-o FILE` |
| `scrape SEEDS` | Collect contacts from the seeds' websites and write a leads CSV. | `--save-db`, `--state NAME`, `--min-confidence low\|medium\|high`, `--exclude-personal`, `--keep-chains`, `--any-domain`, `--delay S`, `--max-pages N`, `--country US` |
| `verify` | Filter stored emails locally, then verify the survivors with Hunter. | `--preview` (free), `--yes`, `--min-likelihood 0-100`, `--max-lookups N` |
| `export {leads,verified}` | Write stored leads or verified emails to CSV. | `-o FILE` |
| `audit FILE` | Sample leads for manual review, then score the reviewed sample to measure real precision. | `-n SIZE`, `--score` |

Example, end to end:

```bash
python -m skrapkin.cli discover --area Texas --country US --category building --limit 100 -o seeds.csv
python -m skrapkin.cli scrape seeds.csv -o leads.csv --save-db --state Texas --min-confidence medium
python -m skrapkin.cli verify --preview
HUNTER_API_KEY=... python -m skrapkin.cli verify --yes
python -m skrapkin.cli export verified -o verified.csv
```

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
| **Webmail rule** | Gmail, Yahoo, Outlook and similar are never sent: a mailbox check cannot confirm them. |
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
| Shared mailbox (`info@`, `sales@`, `orders@`...) | +10 |
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
| `leads` | One document per business: `business`, `website`, `category`, `state`, `city`, `phones`, `confidence`, `source_pages`, timestamps, and an `emails` list of `{address, source, status, likelihood, note}`. |
| `email_checks` | Every Hunter result, keyed by address, so nothing is paid for twice. |
| `verified_emails` | **Only addresses Hunter reported as `valid`**, with the business, location, phones, score, and verification time. This is the list to use for outreach. |

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
| Minimum likelihood score | (Verify tab / `--min-likelihood`) | `60` |
| Max Hunter lookups per run | (Verify tab / `--max-lookups`) | `100` |
| Reuse Hunter results for | config file `recheck_days` | `30` days |
| CSV output folder | (Find Leads tab) | `~/Documents/SKrapkin` |

Docker Compose reads `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_PORT`, and `HUNTER_API_KEY` from `.env`.
Never commit `.env`; it is git-ignored.

---

## Limitations

- **US states only** in the app. The command line accepts any OpenStreetMap area name.
- **Coverage depends on OpenStreetMap.** Many businesses are missing, and few list an email, so most contacts
  come from scraping websites.
- **Some sites will be skipped.** Sites that disallow crawling in `robots.txt`, or that fail to load, produce
  no website contacts. The app falls back to whatever OpenStreetMap lists.
- **No JavaScript rendering.** Contacts that only appear after a script runs are not found.
- **Three categories** are built in (building, clothing, toys). More means adding OSM tag filters in
  `skrapkin/discover.py`.
- **Buyer fit is a guess.** Category tags are the only signal. A one-person handyman and a large supplier look
  alike. Staff emails (`firstname@`) can be less useful than shared mailboxes.
- **Verification is not a guarantee.** A `valid` result is Hunter's assessment at that moment. Mailboxes change,
  and `accept_all` domains cannot be confirmed at all.
- **Docker GUI is Linux/X11 only and experimental.** On Windows and macOS run the app with Python.

---

## Project layout

```
skrapkin/
  discover.py    OpenStreetMap discovery by state and category
  fetcher.py     polite HTTP: robots.txt, per-domain rate limit
  extract.py     emails, phones, names, contact-page links
  validate.py    junk filters, DNS check, phone validation, chain detection
  prefilter.py   local likelihood score (decides what is worth a paid lookup)
  hunter.py      Hunter.io client (Email Verifier + Account)
  verifier.py    verification plan and run
  db.py          MongoDB storage
  config.py      settings and secret storage
  jobs.py        orchestration used by the GUI
  cli.py         command line
  gui.py, gui_widgets.py   desktop app
tests/           pytest suite
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

Tests never call the live Hunter API; they use a fake client that returns Hunter's documented responses.

---

## Contributing

Issues and pull requests are welcome. Please keep the safeguards intact (`robots.txt`, rate limiting, no personal
data collection), add tests for behaviour changes, and run `pytest -q` before opening a PR. By contributing you
agree your work is released under the MIT License.

---

## License and attribution

Released under the **[MIT License](LICENSE)**, so you can use, copy, modify, and distribute it for personal and
commercial purposes, provided the licence and copyright notice are included. The software is provided without
warranty, as described in the [disclaimer](#disclaimer-and-responsible-use) and the licence text.

Business discovery uses data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available
under the Open Database Licence. Email verification uses the [Hunter.io](https://hunter.io) API. The banner
wordmark is set in [Montserrat](https://github.com/JulietaUla/Montserrat) (SIL Open Font License).
