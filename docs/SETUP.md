# SKrapkin: complete setup guide

This guide takes you from **a computer with nothing installed** to **a working SKrapkin that has found and
verified its first leads**. It assumes no technical background. Every command is explained, every screen is shown,
and the problems people usually hit have their own section at the end.

> [!IMPORTANT]
> SKrapkin is a **research tool**. Before you use it on real businesses, read the
> [disclaimer and responsible-use notes](../README.md#disclaimer-and-responsible-use) in the README. You are
> responsible for how you use it.

**What has been tested.** Every command and every piece of sample output in this guide was run from a brand-new
clone of the repository on **Linux (Fedora)**. The **Windows and macOS** steps (installing Docker Desktop, using
PowerShell) are written from standard, well-documented behaviour of those tools but have **not** been run by the
author. The **MongoDB Atlas** steps are also written from MongoDB's standard flow and untested. Where a step is in
that category, it is marked *(not tested)*. If one of them is wrong for you, see
[Getting help](#13-getting-help).

---

## Contents

1. [What you are setting up](#1-what-you-are-setting-up)
2. [What you need before you start](#2-what-you-need-before-you-start)
3. [Choose your route](#3-choose-your-route)
4. [Route A: Docker, step by step (recommended)](#4-route-a-docker-step-by-step-recommended)
5. [A tour of the screens](#5-a-tour-of-the-screens)
6. [Your first search](#6-your-first-search)
7. [Verifying emails with Hunter.io](#7-verifying-emails-with-hunterio)
8. [Everyday use: stop, start, update, back up, uninstall](#8-everyday-use)
9. [Route B: run with Python instead of Docker](#9-route-b-run-with-python-instead-of-docker)
10. [Check that everything works](#10-check-that-everything-works)
11. [Troubleshooting](#11-troubleshooting)
12. [Glossary](#12-glossary)
13. [Getting help](#13-getting-help)
14. [Appendix: settings, files, commands](#14-appendix)

---

## 1. What you are setting up

SKrapkin has three parts. Understanding them makes everything else easier.

```
 your web browser  ──►  SKrapkin web app  ──►  MongoDB database
 (http://localhost:8080)  (finds leads,        (stores leads, verified
                           shows results)        emails, search history)
                               │
                               └──► the internet: OpenStreetMap (finds businesses),
                                    business websites (contact details),
                                    Hunter.io (checks emails, optional, paid)
```

- **The web app** is what you click on. It runs on **your own computer**, not on the internet.
- **MongoDB** is the database that remembers everything between sessions.
- **Docker** (Route A) packages both so you do not have to install or configure either by hand. One command
  starts everything.

**What it costs.** SKrapkin, Docker, and MongoDB are free. Hunter.io (the email verifier) is optional and has its
own plans; it has a free tier with a small monthly allowance, so check [hunter.io/pricing](https://hunter.io/pricing).
Everything except verification works without any account.

**How long it takes** (one time):

| Stage | Typical time |
|---|---|
| Install Docker | 10 to 20 minutes |
| Download and build SKrapkin (first start only) | 3 to 15 minutes, depending on your internet speed (about 1 GB is downloaded) |
| First search of 20 businesses | 1 to 10 minutes, depending on your internet speed |

---

## 2. What you need before you start

| Requirement | Details |
|---|---|
| **Computer** | Windows 10/11 (64-bit), macOS 12 or newer (Intel or Apple silicon), or 64-bit Linux. |
| **Memory** | 8 GB recommended. 4 GB is the minimum; Docker Desktop on Windows and macOS uses about 2 GB by itself. |
| **Disk space** | About 5 GB free for Docker, the downloaded images, and your data. |
| **Internet** | Any connection works. A slow one (under 2 Mbit/s) makes searches take noticeably longer; it does not stop them working. |
| **Free ports** | **8080** (the web app) and **27017** (the database) must not already be in use. If they are, you can change them: see [Settings you might change](#settings-you-might-change). |
| **Permission to install software** | Installing Docker needs administrator rights. |
| **A text editor** | Notepad (Windows), TextEdit (macOS), or nano (Linux) is enough. |

**Accounts.** None are required to get started. Later you may want a free **Hunter.io** account (to verify emails)
and, for Route B only, optionally a free **MongoDB Atlas** account.

---

## 3. Choose your route

| | **Route A: Docker** | **Route B: Python** |
|---|---|---|
| Best for | Almost everyone | People who already use Python, or who cannot install Docker |
| What you install | Docker (and Git, optionally) | Python, plus a database (Docker, Atlas, or MongoDB itself) |
| Steps | Fewest | More |
| Starts with | `docker compose up` | `python -m skrapkin.web` |
| Includes the database | Yes, automatically | No: you provide one |

**If in doubt, choose Route A.** The rest of this guide covers Route A in detail, then Route B.

---

## 4. Route A: Docker, step by step (recommended)

### Step 1. Install Docker

**What Docker is.** A program that runs other programs in sealed boxes ("containers") so they work the same on every
computer. You install Docker once and never touch the details.

#### Windows *(not tested)*

1. Go to **docker.com/products/docker-desktop** and download **Docker Desktop for Windows**.
2. Run the installer. Leave **Use WSL 2** ticked when asked.
3. Restart your computer when prompted.
4. Open **Docker Desktop** from the Start menu and accept the terms. Wait until the bottom left shows
   **Engine running** (the whale icon stops animating). This can take a minute.
5. If Docker says WSL needs installing or updating, open **PowerShell as administrator** (Start menu, type
   *PowerShell*, right-click, *Run as administrator*) and run:
   ```powershell
   wsl --install
   ```
   Then restart and open Docker Desktop again.
6. If Docker complains that **virtualization is disabled**, it has to be turned on in your computer's BIOS/UEFI
   settings (look for "Intel VT-x", "AMD-V", or "SVM"). The steps differ by manufacturer; search for your computer
   model plus "enable virtualization".
7. Recommended: in Docker Desktop, open **Settings, General** and tick **Start Docker Desktop when you sign in to
   Windows**, so SKrapkin comes back after a reboot.

#### macOS *(not tested)*

1. Find out your chip: Apple menu, **About This Mac**. It says either *Apple M1/M2/M3...* or *Intel*.
2. Go to **docker.com/products/docker-desktop** and download the version for your chip.
3. Open the downloaded `.dmg` and drag **Docker** into **Applications**.
4. Open **Docker** from Applications. Approve the permission prompts (it asks for your password once).
5. Wait until Docker says **Engine running**.
6. Recommended: **Settings, General**, tick **Start Docker Desktop when you sign in to your computer**.

#### Linux

Docker publishes official instructions for every distribution: **docs.docker.com/engine/install/**. Follow the page
for your distribution (Ubuntu, Debian, Fedora, and others), including the "Docker Compose plugin". Docker also
provides a one-line convenience script that works on most distributions:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

Then make Docker start automatically, and let your own user run it without `sudo`:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

**Log out and log back in** (or restart) so the group change takes effect. Without this you will see
*permission denied* errors later.

#### Check that Docker works (all systems)

Open a terminal (see Step 3 if you have never done this) and run these three commands, one at a time:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

You should see version numbers for the first two, and the third should print a message starting with
**Hello from Docker!** If any of them fails, go to [Troubleshooting](#11-troubleshooting) before continuing.

> `docker compose` (with a space) is the current command. Very old installs used `docker-compose` (with a
> hyphen). SKrapkin needs the space version, which comes with every current Docker install.

### Step 2. Install Git (optional but recommended)

**Git** downloads the SKrapkin code and makes updating it easy. If you would rather not install it, skip to the ZIP
option in Step 4.

- **Windows:** download from **git-scm.com** and run the installer; the default choices are fine.
- **macOS:** open Terminal and run `git --version`. If Git is missing, macOS offers to install the developer tools;
  accept. (Alternatively install from git-scm.com.)
- **Linux:** `sudo apt install git` (Ubuntu/Debian) or `sudo dnf install git` (Fedora).

Check it with `git --version`.

### Step 3. Open a terminal

A **terminal** is a window where you type commands. You will type or paste a few; nothing here is dangerous if you
copy the commands exactly.

| System | How to open it |
|---|---|
| Windows | Start menu, type **PowerShell**, press Enter. (Windows Terminal also works.) |
| macOS | Press **Cmd + Space**, type **Terminal**, press Enter. |
| Linux | Press **Ctrl + Alt + T**, or find *Terminal* in your applications. |

Tips for people new to terminals:

- Commands are shown in grey boxes. Type or paste one line, then press **Enter**.
- **Pasting:** Windows PowerShell: right-click in the window. macOS: **Cmd + V**. Linux: **Ctrl + Shift + V**.
- `cd folder-name` moves into a folder. `cd ..` goes up one level.
- Lines starting with `#` inside a command box are comments for you to read; you can leave them out.
- If a command seems to hang, wait: downloads and builds print nothing for a while.
- **Ctrl + C** stops a running command.

### Step 4. Get the SKrapkin code

First choose where it will live. Your home folder is fine:

```bash
cd ~
```

(On Windows PowerShell `cd ~` also goes to your user folder.)

**With Git (recommended):**

```bash
git clone https://github.com/Trytan6bz/leads-scrapper.git
cd leads-scrapper
```

**Without Git (ZIP):** open **github.com/Trytan6bz/leads-scrapper** in your browser, click the green **Code** button,
choose **Download ZIP**, and unzip it. In your terminal, `cd` into the unzipped folder (it is called
`leads-scrapper-main`). You will not be able to use `git pull` to update later; you would download a fresh ZIP.

Check you are in the right place by listing the files:

```bash
ls            # Windows PowerShell: dir
```

You should see `docker-compose.yml`, `Dockerfile`, `README.md`, and a folder called `skrapkin`.

### Step 5. Create your settings file (`.env`)

SKrapkin reads its private settings, mainly the database password, from a small file named **`.env`**. This is the
one step where you must make a choice, so read it carefully.

**5a. Make a copy of the template.**

macOS and Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

> **The file name starts with a dot.** Files like that are hidden on macOS and Linux file managers. That is normal;
> the terminal can still see and use them. On Windows make sure it did not get named `.env.txt` (see
> [Troubleshooting](#11-troubleshooting)).

**5b. Choose a password for the database.** It protects your stored leads. It only ever needs to be typed into this
file, so make it long and random rather than memorable.

**The rule: use letters and digits only.** No spaces, and none of `@ : / # ? % & =`, because the password is placed
inside a web address and those characters break it.

Easy ways to generate one:

macOS and Linux:

```bash
openssl rand -hex 16
```

This prints something like `3f9a1c0b7d2e48a69c5b1e0d7a4f2c83`. Copy it.

Windows PowerShell *(not tested)*:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})
```

Or simply type 20 or more random letters and digits yourself.

**5c. Put the password in the file.** Open `.env` in a text editor:

| System | Command |
|---|---|
| Windows | `notepad .env` |
| macOS | `open -e .env` |
| Linux | `nano .env` (save with **Ctrl + O**, **Enter**; exit with **Ctrl + X**) |

You will see this near the top:

```
MONGO_PASSWORD=change-me
```

Replace `change-me` with your password, so it looks like this (use *your own* value, not this one):

```
MONGO_PASSWORD=3f9a1c0b7d2e48a69c5b1e0d7a4f2c83
```

Save the file and close the editor. **Do not leave the placeholder `change-me` in place.** It would work, but it is a
password everyone knows.

**5d. Everything else in the file is optional.** You can ignore the rest for now. For reference:

| Line (remove the `#` to use it) | What it does |
|---|---|
| `MONGO_USER=skrapkin` | The database user name. Rarely needs changing. |
| `MONGO_PORT=27017` | The port the database listens on. Change it if 27017 is already used. |
| `WEB_PORT=8080` | The port for the web app. Change it if 8080 is already used. |
| `HUNTER_API_KEY=...` | Your Hunter.io key, if you prefer to keep it here instead of pasting it into the app. |
| `SKRAPKIN_WEB_PASSWORD=...` | Adds a sign-in prompt to the web app. Only needed to share it on a network. |
| `SKRAPKIN_ALLOWED_HOSTS=...` | Extra addresses allowed to reach the app. Only needed to share it on a network. |

**Keep `.env` private.** Never email it, paste it into a chat, or upload it to GitHub. The repository is set up to
ignore it, so normal use cannot upload it by accident.

### Step 6. Start SKrapkin

One command builds and starts everything:

```bash
docker compose up -d --build --wait
```

What the parts mean: `up` starts the services; `-d` ("detached") keeps them running in the background so you can
close the terminal; `--build` builds the app from the code; `--wait` makes the command wait until everything reports
healthy, so when it finishes the app is ready.

**The first time, this is slow.** Docker downloads the database and Python images and installs the app's
components. Expect 3 to 15 minutes, and long stretches with little output. That is normal. Later starts take a few
seconds because everything is already downloaded.

When it finishes you should see lines ending like this:

```
 Container skrapkin-mongo-1  Healthy
 Container skrapkin-web-1  Healthy
```

(The exact names can differ slightly if you changed the folder name.)

If you see an error instead, find it here:

| What you see | What it means and what to do |
|---|---|
| `required variable MONGO_PASSWORD is missing a value: Set MONGO_PASSWORD in .env (copy .env.example)` | Step 5 was skipped or the file is in the wrong place. The `.env` file must sit **next to** `docker-compose.yml`. Check with `ls -a` (macOS/Linux) or `dir -Force` (PowerShell). |
| `Bind for 127.0.0.1:8080 failed: port is already allocated` | Something else is using port 8080 (perhaps another copy of SKrapkin). Add `WEB_PORT=8081` to `.env` and run the command again. Then open `http://localhost:8081` instead. Same idea for the database with `MONGO_PORT`. |
| `Cannot connect to the Docker daemon` or `error during connect` | Docker is not running. Open Docker Desktop and wait for **Engine running**, or on Linux run `sudo systemctl start docker`. |
| `permission denied while trying to connect to the Docker daemon socket` (Linux) | Your user is not in the `docker` group. Do Step 1's `usermod` command and log out and in again. |

### Step 7. Check that it is running

```bash
docker compose ps
```

You should see two services, both with **(healthy)** in the STATUS column (the real output has a few more columns than
shown here):

```
NAME               IMAGE            SERVICE   STATUS                  PORTS
skrapkin-mongo-1   mongo:7          mongo     Up 28 seconds (healthy)   127.0.0.1:27017->27017/tcp
skrapkin-web-1     skrapkin-web     web       Up 22 seconds (healthy)   127.0.0.1:8080->8080/tcp
```

The `127.0.0.1:` at the start of the PORTS column is important: it means these are reachable **only from your own
computer**, not from anyone else on your network.

To read what the app is saying:

```bash
docker compose logs web
```

A healthy start looks like:

```
Running in a container: docker-compose.yml publishes it on this computer only.
SKrapkin web interface: http://localhost:8080
... INFO waitress: Serving on http://0.0.0.0:8080
```

### Step 8. Open the app

Open your web browser and go to:

**http://localhost:8080**

(If you changed `WEB_PORT`, use that number instead of 8080.)

At the top right are two status badges. You want the first to say **Database: connected**. The second, **Hunter**,
will say **no key** until you add one in [section 7](#7-verifying-emails-with-hunterio); that is expected.

You are now set up. The next two sections tour the screens and walk through a first search.

---

## 5. A tour of the screens

The interface has five tabs across the top. (The screenshots use fictional businesses.)

### Find leads

![The Find leads form](images/01-find-form.png)

This is where you search. From top to bottom:

- **Type of business:** building materials and contractors, clothing retailers, or toy and gift shops.
- **Country, Region, City or area:** where to look. Country is required. **Region** (a state, province, or similar) and
  **City or area** are optional but strongly recommended; see [Your first search](#6-your-first-search).
- **Max businesses to check:** how many businesses to look at in this search (up to 1,000). This is businesses
  *checked*, not leads *found*: roughly 60% of them become leads.
- **Keep leads that have:** how strict to be. *Must have an email address* is a good default. *Any contact* also keeps
  businesses where only a phone number was found.

The right-hand card has the options:

- **Include Gmail / Yahoo / Outlook addresses:** keep free-webmail addresses (many small businesses use them).
- **Include big chains and franchises:** off by default, because chains rarely make good leads.
- **Save leads to the database:** keep results permanently (needed for the Leads, Verify, and Verified tabs).
- **Only new businesses:** skip businesses checked on earlier searches, so repeat searches find *new* ones.
- **Verify new emails with Hunter when finished:** automatically verifies afterwards (uses Hunter credits).
- **Thorough:** read every contact page even after finding an email. Slower; finds extra addresses.
- **Sites checked at once:** how many websites are visited in parallel (default 8). Each site is still fetched
  gently, one page at a time.

![Find leads results](images/02-find-results.png)

While a search runs, results appear in the table as they are found, a progress bar fills, and **Stop** ends the
search early (you keep what was found). When it finishes, **Download CSV** gives you a spreadsheet file.

### Leads

![The Leads tab](images/03-leads.png)

Every lead you have saved. Search as you type, filter by type, country, region, or email status, click a column
heading to sort, tick rows to copy their emails or delete them, and **Export CSV** to download. The coloured chips
under *Emails* show each address and its status: green is verified, grey has not been checked yet.

### Verify emails

![Verify emails: preview](images/04-verify-preview.png)

Where you connect your Hunter.io key and verify emails. **Preview (free)** shows exactly what would happen: green
**Check with Hunter** rows would be sent to Hunter; grey **Skip** rows are filtered out for free, each with the
reason (webmail, unlikely to be real, looks auto-generated, already checked). Nothing is spent until you click
**Verify now**, and that asks you to confirm first:

![The confirmation dialog](images/05-verify-confirm.png)

### Verified results

![Verified results](images/06-verified.png)

The final product: only the emails Hunter confirmed as valid. Search, filter, **Copy all emails**, remove entries,
or **Export CSV**.

### Settings

![Settings](images/07-settings.png)

The database connection (set automatically when you use Docker) and the **Search history**: how many businesses
have been checked, with a button to forget them.

---

## 6. Your first search

Do a **small** first search so you can see how it works without a long wait.

1. Open the **Find leads** tab.
2. **Type of business:** *Clothing & fashion retailers* (any type is fine).
3. **Country:** pick one you know. Choose somewhere well mapped, such as a country in Europe or North America, for
   your first try.
4. **Region:** pick a region (for example a state or province). **Do not leave it on "Entire country"** the first time.
5. **City or area:** type a city in that region. This narrows the search and makes it much faster.
6. **Max businesses to check:** set **20**.
7. **Keep leads that have:** *Must have an email address*.
8. Leave the options as they are and click **Find leads**.

**What happens:**

- First the status says it is searching OpenStreetMap, with a counter of elapsed seconds. This step can take from a
  few seconds to a couple of minutes.
- Then the progress bar starts moving as websites are visited, and leads appear in the table one by one.
- A search of 20 businesses typically takes 1 to 3 minutes on a fast connection and several minutes on a slow one.
- You can press **Stop** at any time; you keep whatever was found.

**What the results mean:**

| Column | Meaning |
|---|---|
| **Confidence: high** | An email on the business's own website domain was found. The best kind. |
| **Confidence: medium** | An email on another domain (for example Gmail). |
| **Confidence: low** | Only a phone number was found. |

Expect about 6 in 10 businesses to become leads, and roughly 4 or 5 in 10 to have an email. If you get fewer, the
area may simply be thinly mapped; see [Troubleshooting](#11-troubleshooting).

**Next:** open the **Leads** tab to see what was saved, and click **Download CSV** on the Find leads tab to get a
spreadsheet.

**Searching again.** Run the same search a second time with **Only new businesses** ticked. SKrapkin tells you how
many already-checked businesses it skipped, and works through new ones. Repeat until it says there is nothing new,
then try a different region, city, or type. The full details, including timings for large searches, are in the
README section [Collecting a lot of leads](../README.md#collecting-a-lot-of-leads).

---

## 7. Verifying emails with Hunter.io

Finding an email on a website does not prove the mailbox exists. **Hunter.io** checks this for you, at a cost per
check. SKrapkin is designed to spend as little as possible: it filters out emails that are almost certainly not real
*before* anything is sent.

This step is **optional**. Without it you still have all your leads and their emails; they are just not checked.

### 7a. Get a Hunter.io key

1. Create an account at **hunter.io** and sign in.
2. Open **hunter.io/api-keys** and copy your API key (a long string of letters and digits).
3. Look at your plan's allowance on Hunter's site, so you know how many checks you have.

### 7b. Give SKrapkin the key

1. Open the **Verify emails** tab.
2. Paste the key into **API key** and click **Save & test**.
3. The test is **free** and uses no credits. If it works you will see something like *Key works and is saved. Plan:
   Starter, 438 of 500 verifications left.* The badge at the top changes to **Hunter: key saved**.
4. If instead it says **Hunter rejected this key**, copy the key again carefully (no spaces).

Where the key is kept: on Docker, in a private volume on your computer; in your browser it is never shown again.
You can also put `HUNTER_API_KEY=your-key` in `.env` instead, which is the preferred method for permanent setups.
After editing `.env`, run `docker compose up -d --wait` to apply it.

### 7c. Set cost controls

On the right, **Keep costs down**:

- **Only send emails that score at least:** SKrapkin scores every email from 0 to 100 for how likely it is to be a
  real business mailbox. 60 is the default. Raise it to spend less (and miss a few real ones); lower it to
  spend more.
- **Never use more than this many Hunter lookups in one run:** a hard cap. **For your very first run, set this to 3 to
  5** so you can see the whole process while spending almost nothing. Click **Save settings**.

### 7d. Preview, then verify

1. Click **Preview (free)**. Read the table: green rows would be sent, grey rows are skipped with a reason.
2. Click **Verify now**. A dialog tells you exactly how many Hunter checks it will use. Click to confirm.
3. Watch the progress. When it finishes you get a summary such as *Checked 3 with Hunter: 3 valid, 0 invalid...*
4. Open **Verified results**. Only emails Hunter confirmed as valid are there.

Running **Verify now** again straight away does nothing and costs nothing: results are remembered for 30 days.

**What the statuses mean** (seen on the Leads tab):

| Status | Meaning |
|---|---|
| `valid` | Hunter confirmed the mailbox exists. These go to Verified results. |
| `invalid` | The mailbox does not exist or cannot receive mail. |
| `accept_all` | The mail server accepts every address, so a check proves nothing. Treat as risky. |
| `webmail` | A free-mail address (Gmail, Yahoo...). A mailbox check cannot confirm these, so they are never sent. |
| `filtered` | Skipped for free as unlikely to be real. |
| `unchecked` | Not looked at yet. |
| `unknown` | Hunter could not decide; it is tried again next time. |

When you are comfortable, raise the cap and verify the rest.

---

## 8. Everyday use

All of these are run in a terminal **inside the SKrapkin folder** (the one with `docker-compose.yml`).

### Stop and start

```bash
docker compose stop            # pause everything; your data is kept
docker compose start           # resume
docker compose up -d --wait    # start (also recreates anything missing)
```

If you restart your computer, SKrapkin comes back by itself as long as Docker starts (that is why Step 1 suggested
turning on *Start Docker Desktop when you sign in*). If it does not, open Docker and run `docker compose up -d --wait`.

### See what is happening

```bash
docker compose ps              # status
docker compose logs -f web     # live app log (Ctrl+C to leave)
```

### Update to a newer version

```bash
git pull
docker compose up -d --build --wait
```

Then reload the web page with **Ctrl + Shift + R** (**Cmd + Shift + R** on macOS) so your browser picks up the new
page code. Your data is untouched by updates. If you used the ZIP download, download a fresh ZIP, copy your `.env`
file into the new folder, and run the second command there.

### Back up your data

Do this before big changes, and now and then. It creates a file, `skrapkin-backup.archive`, in the current folder:

macOS and Linux:

```bash
set -a; . ./.env; set +a
docker compose exec -T mongo mongodump --username skrapkin --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin --db skrapkin --archive=/tmp/skrapkin-backup.archive --gzip
docker compose cp mongo:/tmp/skrapkin-backup.archive ./skrapkin-backup.archive
```

Windows PowerShell *(not tested)*: first read your password from `.env` into a variable, then run the same two
commands on one line each:

```powershell
$pw = (Select-String -Path .env -Pattern '^MONGO_PASSWORD=').Line.Split('=',2)[1]
docker compose exec -T mongo mongodump --username skrapkin --password $pw --authenticationDatabase admin --db skrapkin --archive=/tmp/skrapkin-backup.archive --gzip
docker compose cp mongo:/tmp/skrapkin-backup.archive ./skrapkin-backup.archive
```

(If you changed `MONGO_USER` in `.env`, use that name instead of `skrapkin` after `--username`.)

Copy the `.archive` file somewhere safe. It contains your leads, so protect it like your `.env`.

### Restore from a backup

This **replaces** the current data with the backup:

```bash
set -a; . ./.env; set +a
docker compose cp ./skrapkin-backup.archive mongo:/tmp/skrapkin-backup.archive
docker compose exec -T mongo mongorestore --username skrapkin --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin --archive=/tmp/skrapkin-backup.archive --gzip --drop
```

### Move to another computer

1. Make a backup (above) and copy the `.archive` file and your `.env` file to the new computer.
2. On the new computer, do Steps 1 to 6 (put the copied `.env` in place of creating a new one).
3. Restore the backup into the new installation.

### Stop SKrapkin and keep the data, or remove everything

```bash
docker compose down            # removes the containers; your data is KEPT in Docker volumes
docker compose down -v         # removes the containers AND DELETES ALL YOUR DATA. Cannot be undone.
```

### Uninstall completely

1. `docker compose down -v` (this deletes your data; make a backup first if you want it).
2. Delete the `leads-scrapper` folder.
3. Optionally free disk space: `docker image rm mongo:7` and remove the SKrapkin image shown by `docker images`.
4. Optionally uninstall Docker Desktop like any other program.

---

## 9. Route B: run with Python instead of Docker

Use this if you cannot or do not want to install Docker for the app itself. You will need:

1. **Python** 3.10 or newer.
2. **A MongoDB database** (three ways below).
3. The SKrapkin code ([Step 4](#step-4-get-the-skrapkin-code) above).

### B1. Install Python

- **Windows:** download from **python.org/downloads**. On the first installer screen **tick "Add python.exe to PATH"**,
  then *Install Now*. Check with `py --version`.
- **macOS:** download from python.org, or `brew install python` if you use Homebrew. Check with `python3 --version`.
- **Linux:** `sudo apt install python3 python3-venv python3-pip` (Ubuntu/Debian) or `sudo dnf install python3` (Fedora).

### B2. Install SKrapkin's components

Inside the SKrapkin folder, create a private Python environment and install into it. (An environment keeps these
components separate from the rest of your computer.)

macOS and Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell *(not tested)*:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run the activate script ("running scripts is disabled"), run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, and try again.

After activating, your prompt starts with `(.venv)`. **You must activate it again in every new terminal** before
running SKrapkin (`source .venv/bin/activate` or `.venv\Scripts\Activate.ps1`). The install takes about a minute.

### B3. Provide a database

Pick **one**.

**Option 1: use Docker for the database only (easiest).** Do Step 1 and Step 5 above, then:

```bash
docker compose up -d --wait mongo
```

Your database address is:

```
mongodb://skrapkin:YOUR_PASSWORD@localhost:27017/?authSource=admin
```

(Replace `YOUR_PASSWORD` with the value in your `.env`.)

**Option 2: MongoDB Atlas, free and in the cloud** *(not tested)*. Useful if several people should share one database.

1. Create an account at **mongodb.com/atlas** and create a **free (M0)** cluster.
2. Under **Database Access**, add a database user with a password. Use letters and digits only, or you will have to
   URL-encode special characters in the address.
3. Under **Network Access**, allow your computer's IP address. (Allowing "anywhere" works but is less safe.)
4. Click **Connect** on your cluster, choose **Drivers**, and copy the connection string. It looks like
   `mongodb+srv://user:<password>@cluster0.xxxxx.mongodb.net/`.
5. Replace `<password>` with the user's password.

**Option 3: install MongoDB yourself.** Install **MongoDB Community Edition** from mongodb.com/try/download/community.
The default address `mongodb://localhost:27017` then works with no password if you have not enabled authentication.

### B4. Tell SKrapkin where the database is

Either paste the address into the app's **Settings** tab after starting it, or set it before starting:

macOS and Linux:

```bash
export SKRAPKIN_MONGO_URI="mongodb://skrapkin:YOUR_PASSWORD@localhost:27017/?authSource=admin"
```

Windows PowerShell:

```powershell
$env:SKRAPKIN_MONGO_URI = "mongodb://skrapkin:YOUR_PASSWORD@localhost:27017/?authSource=admin"
```

These last only for that terminal window. The Settings-tab method is remembered permanently.

### B5. Run it

Pick any of the three ways in:

```bash
python -m skrapkin.web          # web interface at http://localhost:8080
python run_gui.py               # desktop window (needs Tk, see below)
python -m skrapkin.cli --help   # command line
```

The web interface prints `SKrapkin web interface: http://localhost:8080`; open that address. Press **Ctrl + C** in the
terminal to stop it. Everything in sections 5 to 7 applies identically.

**The desktop window needs Tk.** It is included with the python.org installers for Windows and macOS. On Debian or
Ubuntu run `sudo apt install python3-tk`; on Fedora run `sudo dnf install python3-tkinter`.

**Where things are kept.** Settings: `~/.skrapkin/config.json`. A saved Hunter key: your operating system's keychain
(Windows Credential Manager, macOS Keychain, or Linux Secret Service) when available, otherwise a private file in
`~/.skrapkin`. Search result CSVs: `~/Documents/SKrapkin`.

**Command-line example** (the same search as in section 6, without a browser):

```bash
python -m skrapkin.cli discover --country DE --region Bayern --place München --category clothing --limit 20 -o seeds.csv
python -m skrapkin.cli scrape seeds.csv -o leads.csv --save-db
python -m skrapkin.cli verify --preview
```

---

## 10. Check that everything works

Work through this list after setup. Each line says what you should see.

| # | Check | Expected |
|---|---|---|
| 1 | `docker --version` | A version number. |
| 2 | `docker compose ps` | Two services, both `(healthy)`. (Route A) |
| 3 | Open `http://localhost:8080` | The SKrapkin page loads. |
| 4 | The top-right badge | **Database: connected** |
| 5 | Find leads: country list | A long list of countries; picking one fills **Region**. |
| 6 | A 20-business search | Leads appear and a CSV can be downloaded. |
| 7 | **Leads** tab | The same leads, with their emails. |
| 8 | **Settings, Search history** | A count that matches the businesses checked. |
| 9 | Repeat the search | It reports skipped, already-checked businesses and finds new ones. |
| 10 | **Verify emails, Save & test** with your key | Shows your plan and remaining checks. (Optional) |
| 11 | **Preview (free)** | A table of Check and Skip rows; nothing is spent. |
| 12 | `docker compose down`, then `docker compose up -d --wait` | Your leads are still there. |

If a line fails, find the matching symptom in the next section.

---

## 11. Troubleshooting

Find your symptom, then follow the fix. To see what the app itself reports, run `docker compose logs web`.

### Setting up Docker

| Symptom | Cause and fix |
|---|---|
| `docker: command not found` / `'docker' is not recognized` | Docker is not installed, or the terminal was opened before installing. Finish Step 1, then open a **new** terminal. |
| `Cannot connect to the Docker daemon` | Docker is not running. Start Docker Desktop and wait for **Engine running**. On Linux: `sudo systemctl start docker`. |
| `permission denied ... docker.sock` (Linux) | Run `sudo usermod -aG docker $USER`, then **log out and back in**. |
| Docker Desktop will not start on Windows | Run `wsl --install` in an administrator PowerShell and restart. Make sure virtualization is enabled in the BIOS. |
| `docker compose` says *unknown command* | You have an old Docker. Update Docker so that `docker compose version` works. |
| Docker is very slow or the computer struggles | Close other programs. In Docker Desktop, **Settings, Resources**, make sure at least 2 GB of memory is allowed. |

### Starting SKrapkin

| Symptom | Cause and fix |
|---|---|
| `required variable MONGO_PASSWORD is missing a value` | There is no `.env` file, or it is not beside `docker-compose.yml`, or the `MONGO_PASSWORD=` line is empty or commented out. Redo Step 5. |
| `.env` is "not found" on Windows even though you made it | It was saved as `.env.txt`. In PowerShell run `Get-ChildItem -Force` to see the real names. Rename it: `Rename-Item .env.txt .env`. Use `notepad .env` to edit, and when saving make sure it does not add `.txt`. |
| `port is already allocated` | Another program uses port 8080 or 27017. Add `WEB_PORT=8081` and/or `MONGO_PORT=27018` to `.env`, then run `docker compose up -d --build --wait`. Browse to the new port. |
| The first start takes a very long time | It is downloading about 1 GB. On a slow connection this can take 15 minutes or more. Let it finish. |
| Build fails with network or certificate errors | Often a company proxy or firewall. Try another network, or configure Docker's proxy settings. |
| `docker compose up` finishes but the page will not load | Wait 10 to 20 seconds and check `docker compose ps` shows `(healthy)`. That is why the guide uses `--wait`. |
| One service keeps restarting | Run `docker compose logs mongo` and `docker compose logs web` and read the last lines; see [Getting help](#13-getting-help). |

### Using the app

| Symptom | Cause and fix |
|---|---|
| Badge says **Database: not connected** | Check `docker compose ps` shows `skrapkin-mongo-1 (healthy)`. If the database container is missing, run `docker compose up -d --wait`. Your data is in a volume and is kept. |
| The page looks old or a button is missing after an update | Hard refresh: **Ctrl + Shift + R** (**Cmd + Shift + R** on macOS). |
| Page says *This address isn't allowed* (HTTP 421) | You opened it by a name other than `localhost` (for example your computer's name). Use `http://localhost:8080`, or add the name to `SKRAPKIN_ALLOWED_HOSTS`. |
| Search sits on "Still waiting for OpenStreetMap" | Large areas take time on the free OpenStreetMap server. Press **Stop** and pick a smaller region or a city. |
| *That area is too large* message | The area was too big for the free server. Choose a region or a city. Whole-country searches of large countries will always fail this way. |
| *Couldn't get an answer from OpenStreetMap* | Its free servers are busy. Wait a minute and try again. |
| Search finds few or no businesses | The area may be thinly mapped (coverage varies a lot by country). Try a larger region, a different type, or a better-mapped country. With **Only new businesses** ticked, "nothing new" can also mean you have already checked everything there. |
| Many sites "skipped (blocked by robots.txt or unreachable)" | Some sites forbid automated visits, and SKrapkin respects that, or they are simply offline. This is normal. |
| Leads have no emails | Many small businesses publish only a phone number or a contact form. Try *Thorough* mode, or a bigger sample. |
| Searches are slow | Speed is mostly limited by your internet connection and by slow websites. See [Collecting a lot of leads](../README.md#collecting-a-lot-of-leads). |
| *Hunter rejected this key* | Re-copy the key from hunter.io/api-keys with no spaces. |
| Verification stops early | You hit your **Never use more than** cap, or your Hunter allowance ran out. Raise the cap, or check your Hunter plan. |
| *Another task is still running* | Only one search or verification runs at a time. Wait for it, or press **Stop**. |
| Closed the browser tab mid-search | The search keeps running on its own. Reopen the page and it reattaches. |

### Route B (Python)

| Symptom | Cause and fix |
|---|---|
| `python: command not found` | On macOS and Linux use `python3`. On Windows use `py`. |
| `No module named ...` | The environment is not active. Activate it (`source .venv/bin/activate` or `.venv\Scripts\Activate.ps1`) and run `pip install -r requirements.txt` again. |
| `No module named '_tkinter'` | Install Tk (see B5), or use the web interface instead. |
| `Couldn't reach the database` | The database address is wrong or MongoDB is not running. Check `docker compose ps`, and that the password in the address matches `.env`. |
| Atlas connection fails | Your IP is not allowed under **Network Access**, or the password has special characters that need URL-encoding. Use a password of letters and digits. |

---

## 12. Glossary

| Term | Plain meaning |
|---|---|
| **Terminal / command line** | A window where you type instructions instead of clicking. |
| **Docker** | A program that runs other programs in sealed boxes so they behave the same everywhere. |
| **Container** | One of those boxes. SKrapkin uses two: the app and the database. |
| **Image** | The packaged template a container is made from. Downloaded once. |
| **Volume** | A place where Docker keeps data so it survives when containers are removed. Your leads live in one. |
| **Docker Compose** | The tool that starts all of SKrapkin's containers from one file (`docker-compose.yml`). |
| **`.env` file** | A small private settings file, such as your database password. |
| **localhost** | "This computer." `http://localhost:8080` is a web address that only works on your own machine. |
| **Port** | A numbered door a program listens on, like 8080 or 27017. Two programs cannot share one. |
| **MongoDB** | The database SKrapkin stores everything in. |
| **OpenStreetMap** | A free, community-built world map. SKrapkin uses it to find businesses. |
| **Hunter.io** | A paid service that checks whether an email address really exists. |
| **robots.txt** | A file on a website saying which parts automated programs may visit. SKrapkin obeys it. |
| **Lead** | A business with at least some contact details. |
| **Verified email** | An email Hunter confirmed is real. |
| **Region** | A state, province, or similar area inside a country. |
| **CSV** | A simple spreadsheet file that opens in Excel or Google Sheets. |

---

## 13. Getting help

If something goes wrong:

1. Look for your symptom in [Troubleshooting](#11-troubleshooting).
2. Collect the facts below, which are what anyone helping you will ask for:
   ```bash
   docker --version
   docker compose version
   docker compose ps
   docker compose logs --tail 60 web
   docker compose logs --tail 30 mongo
   ```
3. **Before sharing anything, remove your passwords and keys.** Never post your `.env` file. The logs normally do not
   contain passwords, but check.
4. Open an issue at **github.com/Trytan6bz/leads-scrapper/issues** describing what you did, what you expected, and
   what happened, with the output above.

---

## 14. Appendix

### Settings you might change

Put these in `.env` (remove the `#` at the start of the line) and run `docker compose up -d --build --wait`.

| Setting | Default | When to change it |
|---|---|---|
| `MONGO_PASSWORD` | (you set it) | Required. |
| `MONGO_USER` | `skrapkin` | Rarely. |
| `MONGO_PORT` | `27017` | Port already in use. |
| `WEB_PORT` | `8080` | Port already in use. |
| `HUNTER_API_KEY` | none | To keep your Hunter key in `.env`. |
| `SKRAPKIN_WEB_PASSWORD` | none | To require a sign-in (team use). |
| `SKRAPKIN_ALLOWED_HOSTS` | none | To open the app by a name other than `localhost` (team use). |

Other settings (sites checked at once, output folder, and so on) are listed in the README's
[Configuration](../README.md#configuration) section.

### Where things live

| What | Where (Route A, Docker) |
|---|---|
| Your leads, verified emails, search history | Docker volume `skrapkin_mongo-data` |
| Settings and a Hunter key saved in the app | Docker volume `skrapkin_skrapkin-config` |
| Search result CSV files | Docker volume `skrapkin_skrapkin-data` (download them from the page) |
| Your passwords | The `.env` file in the SKrapkin folder |

(If you renamed the SKrapkin folder, the volume names start with the new folder name instead of `skrapkin_`.
`docker volume ls` lists them.)

### Command cheat sheet

Run inside the SKrapkin folder.

| Task | Command |
|---|---|
| Start (and build) | `docker compose up -d --build --wait` |
| Status | `docker compose ps` |
| Live app log | `docker compose logs -f web` |
| Stop (keep data) | `docker compose stop` |
| Start again | `docker compose start` |
| Update | `git pull` then `docker compose up -d --build --wait` |
| Remove containers (keep data) | `docker compose down` |
| Remove everything including data | `docker compose down -v` |
| Run only the database (for Route B) | `docker compose up -d --wait mongo` |
| Run the command-line tool in Docker | `docker compose run --rm skrapkin --help` (create a `data` folder first with `mkdir data`) |

### Safety summary

- By default SKrapkin and its database answer **only on your own computer** (`127.0.0.1`). Nobody else on your
  network can reach them.
- Your leads are contact data about real people and businesses. Keep backups and your `.env` private, and delete data
  you no longer need.
- If you ever share SKrapkin with a team, read the README section
  [Sharing it with a team](../README.md#sharing-it-with-a-team) first. Set a password and use HTTPS.
