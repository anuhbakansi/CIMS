# CIMS
# 🕵️ Crime Investigation Management System (CIMS)

A Streamlit application for managing investigations - cases, people, evidence and timelines - with analytics and a Gemini-powered AI assistant. Built for police-style record keeping, security teams, and criminology students.

> **Important:** this is a prototype for learning and small-team use. Crime records are sensitive. Before using real data read the *Security & privacy* section below.

## Features

| Area | What you can do |
|---|---|
| **Dashboard** | Total/active cases, clearance rate, average days to resolve, high-priority alerts, charts for status, crime type, monthly trend (with moving average and trend line), priority, hotspots, case age and evidence status |
| **Cases** | Register cases, search and filter by status/type/priority, open a case file |
| **Case File** | Edit the case, manage people (suspects, victims, witnesses...), log evidence and update its status, keep an investigation timeline. Status changes and additions are written to the timeline automatically |
| **AI Assistant (Gemini)** | Case summary, formal report draft, suggested next investigative steps, related-case detection, chat about the case file, statement analyzer (finds key facts, timeline, possible inconsistencies, follow-up questions; accepts text, Word, PDF and images) |
| **Reports & Export** | Printable case file (no AI), CSV export of cases, people, evidence and timeline |
| **Data & Settings** | Load fictional sample data, download a database backup, erase all data |

## Libraries and their roles

| Library | Role |
|---|---|
| **Streamlit** | The complete interface: login, sidebar navigation, forms, tables, tabs, uploads and downloads |
| **Pandas** | Reads the database into DataFrames, filters/searches/groups cases, builds the monthly time series, exports CSV |
| **NumPy** | Clearance rate, average resolution time, 3-month moving average, trend slope (`polyfit`), case-age histogram bins, sample-data generation |
| **Matplotlib** | All dashboard charts |
| **google-genai** | Official Google Gen AI SDK used for every AI feature |

The Python standard library supplies `sqlite3` (storage), `hmac` (password check) and `zipfile` (reading `.docx` files).

## Installation

Requires Python 3.9 or newer.

```bash
# 1. (recommended) create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt
```

## Gemini API configuration

The key is never written in the code and never typed into the web page.

1. Go to **https://aistudio.google.com**, sign in and click **Get API key** (a free tier is available).
2. Create the file `.streamlit/secrets.toml` next to `app.py`:

   ```toml
   GEMINI_API_KEY = "paste-your-key-here"

   # optional - require a password to open the app
   APP_PASSWORD = "choose-a-strong-password"

   # optional - choose another Gemini model
   # GEMINI_MODEL = "gemini-2.5-flash"
   ```

   Or use environment variables instead:
   - macOS/Linux: `export GEMINI_API_KEY="your-key"`
   - Windows (PowerShell): `$env:GEMINI_API_KEY="your-key"`

3. Never commit `.streamlit/secrets.toml` or `cims.db` to Git.

Without a key, everything except the AI Assistant still works.

## Run

```bash
streamlit run app.py
```

Open http://localhost:8501. For a quick tour, go to **Data & Settings -> Load fictional sample data**, then explore the Dashboard.

## Typical workflow

1. **Cases -> New case**: register the incident.
2. **Case File**: add people and evidence; add notes to the timeline as the investigation progresses.
3. **AI Assistant**: summarise the file, ask what evidence is outstanding, get suggested next steps, analyse a witness statement, check for related cases, draft the report.
4. **Dashboard**: monitor caseload, clearance rate and hotspots.
5. **Reports & Export**: download the case file or CSV data.

## Security & privacy

- **Passwords/login:** set `APP_PASSWORD` to require a password. It is a single shared password, not per-user accounts or role-based access. For real deployments add proper authentication.
- **Data storage:** data lives unencrypted in the local file `cims.db`. Protect the folder, use disk encryption and take backups (Data & Settings -> Download database backup).
- **AI and privacy:** when you use the AI tools, case text is sent to Google's Gemini API. The *Anonymise* option (on by default) replaces **recorded** person names with codes such as `[SUSPECT-12]` and hides contact details, but it cannot detect names typed inside free text that were never added to the People list. Do not send data you are not permitted to share with a third-party service.
- **AI limits:** AI output can be wrong or incomplete. It is decision support only - not evidence - and every conclusion must be verified by a human investigator. Do not treat suggestions as findings of guilt.
- Follow your organisation's laws and policies on handling criminal-justice information.

## Troubleshooting

- **"No Gemini API key found"** - check the key name `GEMINI_API_KEY`, that `.streamlit/secrets.toml` sits next to `app.py` (in the folder you run `streamlit` from), then restart.
- **"Google rejected the API key"** - create a new key in AI Studio and paste it without quotes or spaces inside the quotes.
- **Rate limit (429)** - the free tier has per-minute limits; wait a minute.
- **"Model not found"** - set a current Gemini model name in the sidebar.
- **ModuleNotFoundError** - run `pip install -r requirements.txt` in the same environment you start Streamlit from.
- **Start fresh** - stop the app and delete `cims.db`, or use *Data & Settings -> Delete ALL data*.
