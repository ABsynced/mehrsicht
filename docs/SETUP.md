# Mehrsicht — step-by-step setup guide

> Back to the [project overview](../README.md).

A news site that shows how left, centre and right outlets report the same story,
with AI framing analysis, inline fact-checks, a Bundestag / EU Parliament
coalition calculator and automatic social-media images. It updates itself every 6 hours.

---

## How it works (one picture in words)

```
RSS feeds ──► pipeline/fetch.py      download headlines + teasers
          ──► pipeline/cluster.py    group articles about the same event (AI via Groq / Cerebras)
          ──► pipeline/analyze.py    summary, framing per side, parties (AI via Groq / Cerebras)
          ──► pipeline/images.py     free photo from Wikimedia Commons + credit
          ──► pipeline/factcheck.py  published fact-checks (Google Fact Check API)
          ──► data/edition_de.json, data/edition_eu.json
          ──► sharecards/render.py   PNG images for Instagram / LinkedIn
          ──► site_builder/build.py  finished website in site/
          ──► GitHub Pages           online, every 6 hours (.github/workflows/update.yml)
```

## Folder map

| Folder / file | What it is |
|---|---|
| `config/sources_de.yaml`, `sources_eu.yaml` | Which outlets are read, and their **provisional** left/centre/right rating |
| `config/parliament_*.json` | Seat numbers for the parliament diagram |
| `config/topics.yaml` | Topics, fallback illustrations, photo search words, party keywords |
| `pipeline/` | The Python program that collects and analyses news |
| `site_builder/templates/` | The HTML pages (Jinja templates) |
| `site_builder/static/` | CSS, JavaScript, self-hosted fonts |
| `sharecards/` | Social-media image templates + renderer |
| `fixtures/` | Invented demo data for offline mode ("Medium A", "Medium B", …) |
| `tests/` | Automatic tests |
| `.env.example` | Template for your secret keys |

---

## Step 1 — Check Python

Open a terminal (Windows: press the Windows key, type `PowerShell`, Enter. Mac: `Terminal`).

```bash
python --version          # Windows
python3 --version         # Mac / Linux
```

Expected output: `Python 3.11.x` or newer. If you get an error, install Python from
https://www.python.org/downloads/ (Windows: tick **"Add python.exe to PATH"** in the installer).

## Step 2 — Open the project folder in the terminal

Download the project (`git clone https://github.com/ABsynced/mehrsicht.git`) and go into the folder:

```bash
cd mehrsicht
```

## Step 3 — Install everything (once)

Windows PowerShell:
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Mac / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

`.venv` is a private box for this project's libraries. You will see `(.venv)` at the start of
the terminal line while it is active. Every new terminal: run the `Activate` / `source` line again.

> Windows error "running scripts is disabled"? Run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and answer `Y`.

## Step 4 — Run the demo (no internet, no API key)

```bash
python fixtures/make_fixtures.py
python -m pipeline.run --offline
python -m sharecards.render
python -m site_builder.build
python -m pytest -q
```

What you should see (shortened):
```
INFO    Gespeichert: data/edition_de.json (8 Geschichten)   ← 8 demo stories found
INFO    Gespeichert: data/edition_eu.json (5 Geschichten)
43 Share-Kacheln erzeugt in data/share                      ← social images
Ausgabe DE: Startseite + 8 Geschichten
Fertig: …/mehrsicht/site
26 passed                                                   ← all tests OK
```

Open the site: double-click `site/index.html`, or better, start a small local server:
```bash
python -m http.server 8000 --directory site
```
then open http://localhost:8000 in your browser. Stop the server with `Ctrl + C`.

The yellow bar at the top says "Demo-Modus": all outlets and fact-checks are invented.

## Step 5 — Run it with real news and free AI (Groq + Cerebras)

The AI runs on two **free** services (open-source model gpt-oss, no credit card).
Groq is used first; when its daily budget is used up, Cerebras takes over automatically.

1. **Groq** (with a q — not X's "Grok"): https://console.groq.com → sign up → **API Keys →
   Create API Key** → name `mehrsicht` → copy the key (starts with `gsk_`). Shown only once.
2. **Cerebras**: https://cloud.cerebras.ai → sign up → **API Keys** → create/copy the key
   (starts with `csk-`).
3. Copy the settings template and open it:
   ```bash
   cp .env.example .env          # Mac / Linux
   copy .env.example .env        # Windows
   notepad .env                  # Windows: opens it in Notepad
   ```
4. Paste the keys right after `GROQ_API_KEY=` and `CEREBRAS_API_KEY=` (no spaces). Check that the
   line `LLM_PROVIDER=groq,cerebras` is there. Save, close.
5. Check the keys (keys are never printed):
   ```bash
   python -m pipeline.check_ai          # are the keys found?
   python -m pipeline.check_ai --live   # does each service answer? (1 tiny request each)
   ```
6. Run the live pipeline (without `--offline`). This takes about 5–15 minutes, because it pauses
   between AI requests to stay inside the free per-minute limits:
   ```bash
   python -m pipeline.run
   python -m sharecards.render
   python -m site_builder.build
   ```
   The first line should say `KI aktiv: groq · openai/gpt-oss-120b → cerebras · gpt-oss-120b`.
   At the end: `KI-Nutzung: groq: 40 Anfragen / 90000 Tokens` (free daily budget: Groq ~200,000
   tokens per model, Cerebras ~1,000,000 tokens).
   The log shows how many headlines each outlet delivered, e.g. `spiegel  42 Meldungen`.
   A line like `WARNING Feed taz nicht erreichbar` means that outlet changed its RSS address:
   find the new one on their website and update `config/sources_de.yaml`.

Optional: a free Google Fact Check Tools key (Google Cloud Console → enable "Fact Check Tools API"
→ Credentials → API key) goes after `FACTCHECK_API_KEY=` in `.env`.

## Step 6 — Put it online with GitHub (free)

1. On https://github.com/new create a repository named `mehrsicht` (Public).
2. In the project folder:
   ```bash
   git init
   git add .
   git commit -m "Mehrsicht: erste Version"
   git branch -M main
   git remote add origin https://github.com/ABsynced/mehrsicht.git
   git push -u origin main
   ```
   (`.env` is NOT uploaded — it is listed in `.gitignore`. Never upload your key.)
3. On GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   `GROQ_API_KEY` and `CEREBRAS_API_KEY` = your keys (optional: `FACTCHECK_API_KEY`,
   `NEWSLETTER_FORM_ACTION`).
   Then the **Variables** tab → `SITE_URL` = `https://absynced.github.io/mehrsicht`.
4. **Settings → Pages → Source: GitHub Actions**.
5. **Actions** tab → "Nachrichten aktualisieren" → **Run workflow**. After ~5 minutes the site is at
   `https://absynced.github.io/mehrsicht`. From then on it updates itself every 6 hours
   (4 runs a day stays well inside the free daily limits of both services).

### Free AI: what happens at the limits?
- Per-minute limit: the program waits and tries again.
- Groq's daily limit: it switches to **Cerebras** automatically.
- Both used up: the rest of that run continues **without AI** (real news, simple rules); the next run
  uses AI again. The site never breaks.
- With both keys, the 25 biggest stories per edition get the full AI analysis (only Groq: 10).
  Setting: `AI_MAX_STORIES`.
- Want a different AI later? Change `LLM_PROVIDER` in `.env`, e.g. `groq,cerebras,ollama`
  (adds your own PC as a third backup) or `anthropic` (Claude, paid). Nothing else has to change.

---

## Pages on the website

| Page | What it shows |
|---|---|
| Start (`index.html`) | Top-story carousel, news list, sidebar with daily briefing, fact-check radar and Bundestag/EU-Parliament calculator, news list with **"Weitere Geschichten laden"** |
| Story (`geschichte/…`) | Links/Mitte/Rechts summaries, **Bias-Vergleich**, fact-checks, all articles with tabs, search and sort, coverage details, outlet bubbles by lean, ownership, who reported first, related stories and topics, share/copy/save/hide |
| Topic (`thema/…`) | "Nachrichten zu X", follow button, top 3 stories, outlets that cover it most, media bias, related topics |
| Themen, Für dich | All topics to follow; your followed topics, saved and hidden stories (stored only in your browser) |

The **trending bar** at the top ranks entities by: number of outlets × e^(−hours/24), over the last 72 hours.
Stories are kept for 7 days in `data/archive_de.json` / `data/archive_eu.json`, so they keep their link and the AI does not analyse them twice.
Optional in `.env`: `CONTACT_EMAIL=you@example.com` makes the "Fehler melden" and "Quelle vorschlagen" links open an e-mail.

## Fact-checks

Fact-checks come from real fact-checking newsrooms listed in `config/factcheckers.yaml`
(CORRECTIV, tagesschau Faktenfinder, Mimikama via RSS; with a free Google key also dpa, AFP, BR24 and more).
Stories that a fact-checker has checked are picked first. All checks appear on the page **Faktenchecks**.
For many more checks: get a free key at https://console.cloud.google.com → APIs → enable "Fact Check Tools API"
→ Credentials → API key, then put `FACTCHECK_API_KEY=...` in `.env`.

## Before you show it publicly — checklist

- [ ] **Outlet ratings**: replace the provisional `lean` values in `config/sources_*.yaml` with values
      backed by a published study, and name that study on the Methode page.
- [ ] **Impressum** (`site_builder/templates/impressum.html`): German sites must show a name and
      address. Use a c/o address service if you don't want your home address online.
- [ ] **Datenschutz**: finish the draft (hosting, newsletter provider). A generator like eRecht24 helps.
- [ ] **Newsletter**: create a free Brevo (or MailerLite) account, make a signup form with
      double opt-in, and put its form URL in `NEWSLETTER_FORM_ACTION`.
- [ ] **EU seat numbers** in `config/parliament_eu.json` (they change over time).
- [ ] Ask your university's free legal advice service to look over images, outlet ratings and
      fact-check display. This is not legal advice.

## Costs

Everything is free: GitHub Pages and Actions (public repository), Groq and Cerebras free tiers, Wikimedia Commons,
Google Fact Check Tools. Free-tier limits can change; check them in your Groq and Cerebras accounts.

## Photos: local vs. public

| Setting (`IMAGE_SOURCE`) | Photos | Use |
|---|---|---|
| `feed,commons` (default in `.env`) | Real news photos from the outlets' RSS feeds, credited with photographer/agency when the feed names them; Wikimedia as backup | **Only on your own computer** (private use, demos). A blue bar on the site reminds you. |
| `commons` (set in the GitHub workflow) | Free Wikimedia Commons photos with licence credit | Public website |

Every story gets a different photo (a picture is never used twice in one edition).
Press photos belong to agencies like AP, dpa or Reuters: publishing them on a public site can lead
to expensive warning letters (Abmahnungen) in Germany, so never upload a build made with `feed`.

## Good to know

- Outlet left/right percentages are **counted** from outlet ratings, not guessed by AI.
- Verdicts like "FALSCH" only come from published fact-checks; the AI never decides that.
- The site uses no cookies and no tracking, so no cookie banner is needed.
- Fonts are self-hosted (Google Fonts from Google's servers break GDPR in Germany).
- "Unterstützen" is a placeholder page; donations come later.
