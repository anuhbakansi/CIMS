"""
CRIME INVESTIGATION MANAGEMENT SYSTEM (CIMS)
=============================================
Run with:  streamlit run app.py

Libraries (plus the Python standard library, e.g. sqlite3 for storage):
  * Streamlit   -> the user interface: login, sidebar, forms, tables, tabs, uploads, downloads
  * Pandas      -> all case data: SQL -> DataFrames, filtering, grouping, monthly time series, CSV export
  * NumPy       -> numerical work: clearance rate, resolution times, moving average, trend slope, ageing
  * Matplotlib  -> every chart on the dashboard
  * google-genai (official Google Gen AI SDK) -> Gemini-powered investigation assistant

The Gemini API key is NEVER hard-coded or typed into the page: it comes from
Streamlit secrets (.streamlit/secrets.toml) or an environment variable.

Sections:  1 CONFIG  2 DATABASE  3 LOGIN  4 GEMINI ENGINE  5 AI FEATURES
           6 CHARTS  7 PAGES  8 MAIN
"""

import hmac
import io
import json
import os
import re
import sqlite3
import time
import zipfile
from contextlib import closing
from datetime import date, datetime, timedelta
from html import unescape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

# =============================================================================
# 1. CONFIG & STYLING
# =============================================================================
APP_NAME = "Crime Investigation Management System"
DB_FILE = "cims.db"
DEFAULT_MODEL = "gemini-2.5-flash"

st.set_page_config(page_title="CIMS - Investigation Management", page_icon="🕵️", layout="wide")

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:
    st.error("The Google Gen AI SDK is not installed. Run `pip install -r requirements.txt` and restart.")
    st.stop()

STATUSES = ["Open", "Under Investigation", "Suspended", "Solved", "Closed"]
RESOLVED = ["Solved", "Closed"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]
CRIME_TYPES = ["Theft", "Burglary", "Robbery", "Assault", "Fraud", "Cybercrime", "Vandalism",
               "Homicide", "Drug Offense", "Missing Person", "Arson", "Other"]
ROLES = ["Suspect", "Person of Interest", "Victim", "Witness", "Informant"]
EVIDENCE_TYPES = ["Physical", "Digital", "Document", "Biological", "Weapon", "Photograph / Video", "Other"]
EVIDENCE_STATUS = ["Collected", "In Analysis", "In Storage", "Submitted to Court", "Returned", "Destroyed"]
COLORS = {"navy": "#1e3a8a", "blue": "#2563eb", "sky": "#0ea5e9", "teal": "#14b8a6", "amber": "#f59e0b",
          "red": "#ef4444", "green": "#22c55e", "slate": "#64748b", "violet": "#7c3aed"}
PRIORITY_COLORS = {"Critical": COLORS["red"], "High": COLORS["amber"], "Medium": COLORS["sky"], "Low": COLORS["green"]}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
@keyframes fadeUp { from {opacity:0; transform:translateY(12px);} to {opacity:1; transform:translateY(0);} }
@keyframes shimmer { 0%{background-position:0% 50%;} 50%{background-position:100% 50%;} 100%{background-position:0% 50%;} }
.main .block-container { animation: fadeUp .5s ease; padding-top: 1.4rem; max-width: 1250px; }
.hero { background: linear-gradient(120deg,#0f172a,#1e3a8a,#0ea5e9,#0f172a); background-size: 300% 300%;
        animation: shimmer 12s ease infinite; padding: 26px 30px; border-radius: 18px; color: white;
        margin-bottom: 20px; box-shadow: 0 10px 28px rgba(30,58,138,.35); }
.hero h1 { margin: 0; font-size: 2rem; font-weight: 700; color: white; }
.hero p { margin: 6px 0 0; opacity: .9; color: white; }
.card { background: rgba(30,58,138,.06); border: 1px solid rgba(37,99,235,.25); border-radius: 14px;
        padding: 16px 18px; margin-bottom: 12px; transition: transform .2s ease, box-shadow .2s ease; }
.card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(37,99,235,.2); }
.pill { display:inline-block; padding:2px 11px; border-radius:999px; font-size:.75rem; color:white; margin-right:6px; }
div.stButton > button, div.stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {
  background: linear-gradient(90deg,#1e3a8a,#2563eb); color: white; border: 0; border-radius: 10px;
  padding: .5rem 1.2rem; font-weight: 600; transition: all .2s ease; }
div.stButton > button:hover, div.stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover { transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(37,99,235,.4); color: white; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg,#0f172a 0%,#1e3a8a 70%,#0369a1 100%); }
section[data-testid="stSidebar"] * { color: #f1f5f9 !important; }
[data-testid="stMetric"] { background: rgba(37,99,235,.07); border-radius: 12px; padding: 10px 14px;
                           border: 1px solid rgba(37,99,235,.2); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def pill(text, color):
    return f'<span class="pill" style="background:{color}">{text}</span>'


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def officer():
    return (st.session_state.get("officer") or "Officer").strip() or "Officer"


# =============================================================================
# 2. DATABASE  (SQLite via the standard library, analysed with Pandas)
# =============================================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_no TEXT, title TEXT NOT NULL, crime_type TEXT, status TEXT,
  priority TEXT, location TEXT, date_occurred TEXT, description TEXT, assigned_officer TEXT,
  created_at TEXT, closed_at TEXT);
CREATE TABLE IF NOT EXISTS persons (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  name TEXT NOT NULL, role TEXT, age INTEGER, contact TEXT, notes TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  item TEXT NOT NULL, etype TEXT, description TEXT, found_at TEXT, collected_by TEXT, collected_on TEXT,
  storage TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS timeline (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  ts TEXT, author TEXT, entry TEXT NOT NULL);
"""


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(_connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def query(sql, params=()):
    """Run a SELECT and return a Pandas DataFrame."""
    with closing(_connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql, params=()):
    with closing(_connect()) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def cases_df():
    return query("SELECT * FROM cases ORDER BY id DESC")


def get_case(cid):
    df = query("SELECT * FROM cases WHERE id = ?", (int(cid),))
    return df.iloc[0].to_dict() if not df.empty else None


def add_timeline(cid, entry, author=None, ts=None):
    execute("INSERT INTO timeline (case_id, ts, author, entry) VALUES (?,?,?,?)",
            (int(cid), ts or now_str(), author or officer(), entry))


def create_case(title, crime_type, status, priority, location, date_occurred, description, assigned,
                created_at=None, closed_at=None, author=None):
    created_at = created_at or now_str()
    if status in RESOLVED and not closed_at:
        closed_at = now_str()
    cid = execute("INSERT INTO cases (title, crime_type, status, priority, location, date_occurred, description,"
                  " assigned_officer, created_at, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (title, crime_type, status, priority, location, str(date_occurred), description, assigned,
                   created_at, closed_at))
    year = str(date_occurred)[:4] or str(date.today().year)
    execute("UPDATE cases SET case_no = ? WHERE id = ?", (f"CR-{year}-{cid:04d}", cid))
    add_timeline(cid, "Case opened.", author, created_at)
    return cid


def update_case(cid, **fields):
    old = get_case(cid)
    if "status" in fields and fields["status"] != old["status"]:
        fields["closed_at"] = now_str() if fields["status"] in RESOLVED else None
        add_timeline(cid, f"Status changed: {old['status']} -> {fields['status']}.")
    cols = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE cases SET {cols} WHERE id = ?", (*fields.values(), int(cid)))


def persons_df(cid):
    return query("SELECT * FROM persons WHERE case_id = ? ORDER BY id", (int(cid),))


def evidence_df(cid):
    return query("SELECT * FROM evidence WHERE case_id = ? ORDER BY id", (int(cid),))


def timeline_df(cid):
    return query("SELECT * FROM timeline WHERE case_id = ? ORDER BY ts DESC, id DESC", (int(cid),))


SAMPLE_DESC = {
    "Theft": "Reporter states a bicycle and backpack were taken from an unlocked storage area overnight. "
             "No signs of forced entry. A neighbour recalls a person loitering earlier in the evening.",
    "Burglary": "Rear window found broken at a residence while occupants were away. Electronics and jewellery "
                "reported missing. Muddy footprints lead to the back fence.",
    "Robbery": "Victim reports being approached by two individuals near a bus stop who demanded a phone and wallet. "
               "Victim was not injured. Suspects fled on foot heading east.",
    "Assault": "Altercation outside a venue after closing time. One person sustained facial injuries and was taken "
               "to hospital. Several bystanders gave differing accounts of who started the fight.",
    "Fraud": "Elderly resident received calls from someone claiming to be a bank official and transferred funds "
             "to an unknown account. Phone records requested.",
    "Cybercrime": "Company reports unauthorised access to its customer database and a ransom demand by email. "
                  "Server logs show logins from an unfamiliar overseas address.",
    "Vandalism": "Graffiti and broken windows reported at a community centre. CCTV covers only part of the area.",
    "Arson": "Fire at a warehouse after hours. Fire service notes multiple points of origin and a possible "
             "accelerant smell. Alarm system had been disabled earlier that day.",
}
SAMPLE_EVIDENCE = {
    "Theft": [("Bicycle lock fragment", "Physical"), ("Neighbour's doorbell video", "Photograph / Video")],
    "Burglary": [("Footprint cast", "Physical"), ("Broken window glass", "Physical"), ("Photographs of scene", "Photograph / Video")],
    "Robbery": [("Bus stop CCTV footage", "Photograph / Video"), ("Witness sketch", "Document")],
    "Assault": [("Hospital medical report", "Document"), ("Bystander phone video", "Photograph / Video")],
    "Fraud": [("Call detail records", "Digital"), ("Bank transfer receipt", "Document")],
    "Cybercrime": [("Server access logs", "Digital"), ("Ransom email headers", "Digital")],
    "Vandalism": [("Spray paint cans", "Physical"), ("Partial CCTV clip", "Photograph / Video")],
    "Arson": [("Debris samples", "Physical"), ("Alarm system logs", "Digital")],
}
SAMPLE_NAMES = ["Alex Morgan", "Sam Carter", "Jordan Lee", "Riley Brooks", "Casey Nguyen", "Taylor Reed",
                "Jamie Fox", "Drew Patel", "Morgan Ellis", "Avery Stone", "Quinn Harper", "Blake Rivera"]
SAMPLE_LOCATIONS = ["Downtown", "Riverside", "Old Market", "Airport Road", "University District",
                    "Harbor Front", "Northgate", "Hillcrest"]


def load_sample_data():
    """Insert fictional demo cases so the dashboard can be explored immediately."""
    rng = np.random.default_rng(42)
    types = list(SAMPLE_DESC)
    for i in range(26):
        ctype = types[int(rng.integers(len(types)))]
        occurred = date.today() - timedelta(days=int(rng.integers(4, 330)))
        status = str(rng.choice(STATUSES, p=[0.18, 0.30, 0.10, 0.22, 0.20]))
        created = datetime.combine(occurred, datetime.min.time()) + timedelta(days=1, hours=9)
        closed = (created + timedelta(days=int(rng.integers(5, 90)))) if status in RESOLVED else None
        if closed and closed > datetime.now():
            closed = datetime.now()
        loc = SAMPLE_LOCATIONS[int(rng.integers(len(SAMPLE_LOCATIONS)))]
        cid = create_case(f"{ctype} reported in {loc}", ctype, status, str(rng.choice(PRIORITIES, p=[.1, .3, .4, .2])),
                          loc, occurred, SAMPLE_DESC[ctype], str(rng.choice(["Det. Ruiz", "Det. Khan", "Off. Walker"])),
                          created.strftime("%Y-%m-%d %H:%M"), closed.strftime("%Y-%m-%d %H:%M") if closed else None,
                          author="System (sample)")
        for k in range(int(rng.integers(1, 4))):
            role = str(rng.choice(ROLES, p=[.2, .15, .25, .35, .05]))
            name = SAMPLE_NAMES[int(rng.integers(len(SAMPLE_NAMES)))]
            execute("INSERT INTO persons (case_id, name, role, age, contact, notes, added_at) VALUES (?,?,?,?,?,?,?)",
                    (cid, name, role, int(rng.integers(18, 70)), "n/a (sample)",
                     f"Sample record: {role.lower()} in this fictional case.", now_str()))
        for item, etype in SAMPLE_EVIDENCE[ctype]:
            execute("INSERT INTO evidence (case_id, item, etype, description, found_at, collected_by, collected_on,"
                    " storage, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, item, etype, f"{item} recovered during the investigation.", loc, "Forensics Unit",
                     str(occurred), "Evidence Room A", str(rng.choice(EVIDENCE_STATUS[:4]))))
        if status != "Open":
            add_timeline(cid, "Initial scene examination completed and statements taken.", "System (sample)",
                         (created + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"))


# =============================================================================
# 3. LOGIN  (optional - enabled when APP_PASSWORD is configured)
# =============================================================================
def get_secret(name):
    try:
        val = st.secrets.get(name, "")
    except Exception:                               # no secrets.toml
        val = ""
    return str(val or os.environ.get(name, "")).strip()


def check_login():
    """If APP_PASSWORD is set in secrets/env, require it. Otherwise the app is open."""
    password = get_secret("APP_PASSWORD")
    if not password or st.session_state.get("auth_ok"):
        return True
    hero("🕵️ CIMS", "Restricted system - authorised personnel only.")
    with st.form("login"):
        entered = st.text_input("Access password", type="password")
        if st.form_submit_button("Sign in"):
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


# =============================================================================
# 4. GEMINI ENGINE  (official Google Gen AI SDK)
# =============================================================================
class AIError(Exception):
    pass


SYSTEM_PROMPT = (
    "You are an assistant embedded in a crime investigation case-management system used by investigators and "
    "criminology students. You provide decision support only. Base every statement strictly on the case material "
    "provided - never invent facts, names, evidence or legal conclusions. Never declare anyone guilty; use neutral "
    "terms such as 'person of interest' and note presumption of innocence. Clearly flag gaps, uncertainty and "
    "conflicting information. Keep a professional, objective tone.")


def get_api_key():
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = re.sub(r"\s+", "", get_secret(name)).strip("\"'`")
        if val:
            return val
    return ""


def get_model():
    return (st.session_state.get("model") or get_secret("GEMINI_MODEL") or DEFAULT_MODEL).strip()


@st.cache_resource(show_spinner=False)
def _client(api_key):
    return genai.Client(api_key=api_key)


def friendly_error(code, message):
    low = str(message).lower()
    if code in (400, 401, 403) and ("api key" in low or "api_key" in low or code in (401, 403)):
        return "Google rejected the API key. Create a new key at aistudio.google.com and update GEMINI_API_KEY."
    if code == 404:
        return f"Model '{get_model()}' was not found. Change the Model name in the sidebar."
    if code == 429:
        return "Free-tier rate limit reached. Wait a minute and try again."
    if code in (500, 503):
        return "Gemini is busy right now. Please try again shortly."
    return f"Gemini error {code}: {str(message)[:300]}"


def generate(prompt, json_mode=False, temperature=0.3, attachments=None):
    key = get_api_key()
    if not key:
        raise AIError("No Gemini API key found. See setup steps in the README.")
    kwargs = {"system_instruction": SYSTEM_PROMPT, "temperature": temperature}
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    config = genai_types.GenerateContentConfig(**kwargs)
    contents = prompt
    if attachments:
        contents = [genai_types.Part.from_bytes(data=d, mime_type=m) for d, m in attachments] + [prompt]
    for attempt in range(3):
        try:
            resp = _client(key).models.generate_content(model=get_model(), contents=contents, config=config)
            if not resp.text or not resp.text.strip():
                raise AIError("Gemini returned an empty answer (it may have been blocked). Try rephrasing.")
            return resp.text
        except AIError:
            raise
        except genai_errors.APIError as e:
            code = getattr(e, "code", None)
            if code in (429, 500, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise AIError(friendly_error(code, getattr(e, "message", e)))
        except Exception as e:
            raise AIError(f"Could not reach Gemini: {e}")
    raise AIError("Gemini did not respond. Please try again.")


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    end = max(text.rfind("}"), text.rfind("]"))
    if starts and end > min(starts):
        try:
            return json.loads(text[min(starts):end + 1])
        except json.JSONDecodeError:
            pass
    raise AIError("The AI reply was not valid JSON. Please try again.")


def run_ai(label, func):
    try:
        with st.spinner(label):
            return func()
    except AIError as e:
        st.error(str(e))
        return None


def require_ai():
    if get_api_key():
        return True
    st.warning("🔑 Gemini API key not found. The AI assistant needs it (everything else works without it).")
    st.markdown("1. Get a free key at **https://aistudio.google.com** -> *Get API key*.\n"
                "2. Create `.streamlit/secrets.toml` next to `app.py` containing:\n"
                "   ```toml\n   GEMINI_API_KEY = \"paste-your-key-here\"\n   ```\n"
                "   (or set the `GEMINI_API_KEY` environment variable)\n3. Restart the app.")
    return False


# ---- case file -> text (with optional anonymisation) ------------------------
def alias_map():
    """Real person names -> neutral aliases such as [SUSPECT-12]."""
    df = query("SELECT id, name, role FROM persons")
    amap = {}
    for r in df.itertuples():
        amap[r.name.strip()] = f"[{str(r.role).upper().replace(' ', '-')}-{r.id}]"
    return amap


def anonymise(text, amap):
    for name in sorted(amap, key=len, reverse=True):
        if name:
            text = re.sub(re.escape(name), amap[name], text, flags=re.IGNORECASE)
    return text


def case_text(cid, anonymize=False):
    """Full case file as plain text - the context sent to Gemini and used for the printable report."""
    c = get_case(cid)
    amap = alias_map() if anonymize else {}
    lines = [f"CASE {c['case_no']}: {c['title']}", f"Crime type: {c['crime_type']} | Status: {c['status']} | "
             f"Priority: {c['priority']}", f"Location: {c['location']} | Date of incident: {c['date_occurred']}",
             f"Assigned officer: {c['assigned_officer']} | Opened: {c['created_at']}",
             "", "DESCRIPTION:", c["description"] or "(none)", "", "PEOPLE INVOLVED:"]
    p = persons_df(cid)
    for r in p.itertuples():
        name = amap.get(r.name.strip(), r.name) if anonymize else r.name
        contact = "" if anonymize else f" | Contact: {r.contact}"
        lines.append(f"- {name} ({r.role}, age {r.age if pd.notna(r.age) else 'unknown'}){contact} | Notes: {r.notes or '-'}")
    if p.empty:
        lines.append("(none recorded)")
    lines += ["", "EVIDENCE:"]
    e = evidence_df(cid)
    for r in e.itertuples():
        lines.append(f"- {r.item} [{r.etype}] status: {r.status}; found at: {r.found_at}; collected by "
                     f"{r.collected_by} on {r.collected_on}; stored: {r.storage}. {r.description or ''}")
    if e.empty:
        lines.append("(none recorded)")
    lines += ["", "INVESTIGATION TIMELINE (oldest first):"]
    for r in timeline_df(cid).iloc[::-1].itertuples():
        lines.append(f"- {r.ts} [{r.author}] {r.entry}")
    text = "\n".join(lines)
    return anonymise(text, amap) if anonymize else text


# =============================================================================
# 5. AI FEATURES
# =============================================================================
def ai_summary(text):
    return generate("Write a concise briefing (max 250 words) of this case for a supervisor: what happened, "
                    "current status, key evidence, people involved, and the main open questions. Use short "
                    "paragraphs or bullets.\n\n" + text)


def ai_report(text, author):
    return generate("Draft a formal investigation report in Markdown for the case below. Use these sections: "
                    "# Title, ## Case Overview, ## Summary of Incident, ## Persons Involved, ## Evidence Review, "
                    "## Investigation Timeline, ## Analysis & Observations, ## Outstanding Issues, "
                    f"## Recommendations. Prepared by: {author}. Date: {date.today().isoformat()}. "
                    "Only use facts from the case file; write 'Not recorded' where data is missing.\n\n" + text,
                    temperature=0.2)


def ai_leads(text):
    d = parse_json(generate("Suggest 5-8 concrete next investigative steps for this case, ordered by importance. "
                            'Reply with a JSON array: [{"action": str, "priority": "High"|"Medium"|"Low", '
                            '"rationale": str (reference the case facts), "gap_addressed": str}].\n\n' + text,
                            json_mode=True))
    return [x for x in d if isinstance(x, dict) and x.get("action")] if isinstance(d, list) else []


def ai_similar(target, others):
    d = parse_json(generate("Compare the TARGET case with the OTHER cases and identify any that may be related "
                            "(similar modus operandi, location, timing, evidence or people). Only list plausible "
                            'links. Reply with a JSON array: [{"case_no": str, "likelihood": "High"|"Medium"|"Low", '
                            '"shared_factors": [str], "reason": str}]. Return [] if nothing is related.\n\n'
                            f"TARGET:\n{target}\n\nOTHER CASES:\n{others}", json_mode=True))
    return [x for x in d if isinstance(x, dict) and x.get("case_no")] if isinstance(d, list) else []


def ai_ask(text, question, history):
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-6:])
    return generate(f"CASE FILE:\n{text}\n\nPREVIOUS CONVERSATION:\n{convo or '(none)'}\n\nQUESTION: {question}\n\n"
                    "Answer using only the case file. If the answer is not in the file, say so.")


def ai_statement(text, attachments):
    prompt = ("Analyse this witness/suspect statement (provided as text and/or attached files). Reply with JSON: "
              '{"summary": str, "key_facts": [str], "people_mentioned": [str], "timeline": [str], '
              '"possible_inconsistencies": [str], "follow_up_questions": [str]}. Do not speculate beyond the '
              "statement; note ambiguity instead.\n\nSTATEMENT TEXT:\n" + (text[:30000] or "(see attachment)"))
    d = parse_json(generate(prompt, json_mode=True, attachments=attachments or None))
    if not isinstance(d, dict):
        raise AIError("Unexpected reply format. Please try again.")
    for k in ("key_facts", "people_mentioned", "timeline", "possible_inconsistencies", "follow_up_questions"):
        d[k] = [str(x) for x in d.get(k, [])]
    d["summary"] = str(d.get("summary", ""))
    return d


# ---- file upload helpers (statement analyzer) ----
UPLOAD_TYPES = ["txt", "md", "docx", "pdf", "png", "jpg", "jpeg", "webp"]
BINARY_MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "webp": "image/webp"}


def read_upload(name, data):
    """Return (text, attachment). PDFs/images go to Gemini directly; txt/md/docx are read locally."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if ext in ("txt", "md"):
            text = data.decode("utf-8", errors="ignore")
        elif ext == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            text = unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml)))
        elif ext in BINARY_MIME:
            return None, (data, BINARY_MIME[ext])
        else:
            raise ValueError(f"Unsupported file type for '{name}'.")
    except (zipfile.BadZipFile, KeyError):
        raise ValueError(f"'{name}' could not be read (damaged or invalid file).")
    if not text.strip():
        raise ValueError(f"No readable text found in '{name}'.")
    return text.strip(), None


# =============================================================================
# 6. CHARTS  (Matplotlib; numbers prepared with Pandas + NumPy)
# =============================================================================
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.alpha": 0.25, "font.size": 10, "axes.titleweight": "bold"})


def show_fig(fig):
    st.pyplot(fig)
    plt.close(fig)


def chart_status(df):
    counts = df["status"].value_counts().reindex(STATUSES).dropna()
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    cols = [COLORS[c] for c in ("sky", "blue", "amber", "green", "slate")][:len(counts)]
    ax.pie(counts.values, labels=[f"{k} ({int(v)})" for k, v in counts.items()], colors=cols, startangle=90,
           counterclock=False, wedgeprops=dict(width=0.4, edgecolor="white"))
    ax.set_title("Cases by status")
    fig.tight_layout()
    return fig


def chart_types(df):
    counts = df["crime_type"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.barh(counts.index, counts.values, color=COLORS["blue"])
    for i, v in enumerate(counts.values):
        ax.text(v + 0.1, i, str(v), va="center")
    ax.set(title="Cases by crime type", xlabel="Number of cases")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return fig


def monthly_series(df):
    d = pd.to_datetime(df["date_occurred"], errors="coerce").dropna()
    if d.empty:
        return None
    per = d.dt.to_period("M").value_counts().sort_index()
    return per.reindex(pd.period_range(per.index.min(), per.index.max(), freq="M"), fill_value=0)


def chart_monthly(df):
    s = monthly_series(df)
    if s is None:
        return None
    y = s.to_numpy(dtype=float)
    x = np.arange(len(y))
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(x, y, color=COLORS["sky"], alpha=0.8, label="Incidents")
    if len(y) >= 3:                                   # NumPy moving average + trend line
        ma = np.convolve(y, np.ones(3) / 3, mode="valid")
        ax.plot(x[2:], ma, color=COLORS["navy"], linewidth=2.5, label="3-month average")
        slope, icpt = np.polyfit(x, y, 1)
        ax.plot(x, slope * x + icpt, "--", color=COLORS["red"], label=f"Trend ({slope:+.2f}/month)")
    ax.set_xticks(x)
    ax.set_xticklabels([str(p) for p in s.index], rotation=45, ha="right")
    ax.set(title="Incidents per month", ylabel="Cases")
    ax.legend()
    fig.tight_layout()
    return fig


def chart_priority(df):
    counts = df["priority"].value_counts().reindex(PRIORITIES).fillna(0)
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.bar(counts.index, counts.values, color=[PRIORITY_COLORS[p] for p in counts.index])
    for i, v in enumerate(counts.values):
        ax.text(i, v + 0.2, str(int(v)), ha="center")
    ax.set(title="Cases by priority", ylabel="Cases")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def chart_hotspots(df):
    counts = df["location"].fillna("Unknown").value_counts().head(8).sort_values()
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    shade = plt.cm.Blues(np.linspace(0.4, 0.9, len(counts)))
    ax.barh(counts.index, counts.values, color=shade)
    ax.set(title="Crime hotspots (top locations)", xlabel="Number of cases")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return fig


def chart_ageing(open_ages):
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    bins = np.array([0, 7, 30, 90, 180, 10_000])
    counts, _ = np.histogram(open_ages, bins=bins)
    ax.bar(["<1 wk", "1-4 wks", "1-3 mo", "3-6 mo", ">6 mo"], counts,
           color=[COLORS["green"], COLORS["teal"], COLORS["sky"], COLORS["amber"], COLORS["red"]])
    ax.set(title="Age of active cases", ylabel="Cases")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def chart_evidence(ev):
    counts = ev["status"].value_counts().reindex(EVIDENCE_STATUS).dropna()
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.bar(range(len(counts)), counts.values, color=COLORS["violet"])
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels([s.replace(" ", "\n") for s in counts.index], fontsize=8)
    ax.set(title="Evidence by status", ylabel="Items")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


# =============================================================================
# 7. PAGES
# =============================================================================
def open_case(cid):
    """Button callback: remember the case and jump to the Case File page."""
    st.session_state["sel_case"] = int(cid)
    st.session_state["nav"] = "📁 Case File"


def case_label(r):
    return f"{r.case_no} - {r.title}"


def case_picker(page_key):
    df = cases_df()
    if df.empty:
        st.info("No cases yet. Create one on the Cases page, or load sample data in Data & Settings.")
        return None
    ids = df["id"].tolist()
    labels = {r.id: case_label(r) for r in df.itertuples()}
    cur = st.session_state.get("sel_case")
    index = ids.index(cur) if cur in ids else 0
    cid = st.selectbox("Select case", ids, index=index, format_func=labels.get, key=f"pick_{page_key}")
    st.session_state["sel_case"] = cid
    return cid


def page_dashboard():
    hero("📊 Dashboard", "Live overview of caseload, trends and evidence.")
    df = cases_df()
    if df.empty:
        st.info("No data yet. Add a case on the **Cases** page or load fictional sample data in **Data & Settings**.")
        return
    resolved = df["status"].isin(RESOLVED)
    total, n_res = len(df), int(resolved.sum())
    clearance = 100 * n_res / total if total else 0
    created = pd.to_datetime(df["created_at"], errors="coerce")
    closed = pd.to_datetime(df["closed_at"], errors="coerce")
    days = (closed - created).dt.days[resolved].dropna().to_numpy(dtype=float)
    ev = query("SELECT status FROM evidence")
    n_people = int(query("SELECT COUNT(*) AS n FROM persons")["n"][0])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total cases", total)
    c2.metric("Active cases", total - n_res)
    c3.metric("Clearance rate", f"{clearance:.0f}%")
    c4.metric("Avg. days to resolve", f"{np.mean(days):.0f}" if len(days) else "-")
    c5.metric("Evidence items / people", f"{len(ev)} / {n_people}")
    crit = df[(df["priority"].isin(["Critical", "High"])) & (~resolved)]
    if len(crit):
        st.warning(f"⚠️ {len(crit)} high-priority case(s) still active: "
                   + ", ".join(crit["case_no"].head(6).tolist()) + ("..." if len(crit) > 6 else ""))

    a, b = st.columns(2)
    with a:
        show_fig(chart_status(df))
    with b:
        show_fig(chart_types(df))
    fig = chart_monthly(df)
    if fig:
        show_fig(fig)
    a, b = st.columns(2)
    with a:
        show_fig(chart_priority(df))
    with b:
        show_fig(chart_hotspots(df))
    a, b = st.columns(2)
    active_age = (pd.Timestamp.now() - created[~resolved]).dt.days.dropna().to_numpy(dtype=float)
    with a:
        if len(active_age):
            show_fig(chart_ageing(active_age))
    with b:
        if len(ev):
            show_fig(chart_evidence(ev))


def page_cases():
    hero("🗂️ Cases", "Search, filter and register investigations.")
    tab_list, tab_new = st.tabs(["📋 All cases", "➕ New case"])
    with tab_list:
        df = cases_df()
        if df.empty:
            st.info("No cases yet - use the **New case** tab.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            status = c1.multiselect("Status", STATUSES)
            ctype = c2.multiselect("Crime type", sorted(df["crime_type"].dropna().unique()))
            prio = c3.multiselect("Priority", PRIORITIES)
            term = c4.text_input("Search", placeholder="case no, title, location...")
            f = df
            if status:
                f = f[f["status"].isin(status)]
            if ctype:
                f = f[f["crime_type"].isin(ctype)]
            if prio:
                f = f[f["priority"].isin(prio)]
            if term.strip():
                mask = f[["case_no", "title", "location", "description", "assigned_officer"]].fillna("") \
                    .apply(lambda col: col.str.contains(term.strip(), case=False, regex=False)).any(axis=1)
                f = f[mask]
            f = f.assign(_p=f["priority"].map({p: i for i, p in enumerate(PRIORITIES)})).sort_values(["_p", "id"],
                                                                                                    ascending=[True, False])
            st.caption(f"{len(f)} of {len(df)} cases")
            st.dataframe(f[["case_no", "title", "crime_type", "status", "priority", "location", "date_occurred",
                            "assigned_officer"]], use_container_width=True, hide_index=True)
            if len(f):
                ids = f["id"].tolist()
                labels = {r.id: case_label(r) for r in f.itertuples()}
                pick = st.selectbox("Open a case", ids, format_func=labels.get)
                st.button("📂 Open case file", on_click=open_case, args=(pick,))
    with tab_new:
        with st.form("new_case", clear_on_submit=True):
            title = st.text_input("Case title *")
            c1, c2, c3 = st.columns(3)
            ctype = c1.selectbox("Crime type", CRIME_TYPES)
            prio = c2.selectbox("Priority", PRIORITIES, index=2)
            status = c3.selectbox("Status", STATUSES)
            c1, c2, c3 = st.columns(3)
            location = c1.text_input("Location")
            occurred = c2.date_input("Date of incident", value=date.today(), max_value=date.today())
            assigned = c3.text_input("Assigned officer", value=officer())
            desc = st.text_area("Description", height=140)
            if st.form_submit_button("Create case"):
                if len(title.strip()) < 3:
                    st.error("Please enter a case title (at least 3 characters).")
                else:
                    cid = create_case(title.strip(), ctype, status, prio, location.strip(), occurred,
                                      desc.strip(), assigned.strip())
                    st.success(f"Case {get_case(cid)['case_no']} created.")


def page_case_file():
    hero("📁 Case File", "Everything about one investigation.")
    cid = case_picker("file")
    if cid is None:
        return
    c = get_case(cid)
    st.markdown(f"### {c['case_no']} - {c['title']}")
    st.markdown(pill(c["status"], COLORS["blue"]) + pill(c["priority"], PRIORITY_COLORS.get(c["priority"], COLORS["slate"]))
                + pill(c["crime_type"], COLORS["slate"]), unsafe_allow_html=True)
    t1, t2, t3, t4 = st.tabs(["📝 Overview", "👥 People", "🔎 Evidence", "🕒 Timeline"])

    with t1:
        with st.form("edit_case"):
            title = st.text_input("Title", c["title"])
            a, b, d = st.columns(3)
            ctype = a.selectbox("Crime type", CRIME_TYPES, index=CRIME_TYPES.index(c["crime_type"]) if c["crime_type"] in CRIME_TYPES else 0)
            prio = b.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(c["priority"]) if c["priority"] in PRIORITIES else 2)
            status = d.selectbox("Status", STATUSES, index=STATUSES.index(c["status"]) if c["status"] in STATUSES else 0)
            a, b, d = st.columns(3)
            location = a.text_input("Location", c["location"] or "")
            try:
                dv = date.fromisoformat(str(c["date_occurred"])[:10])
            except ValueError:
                dv = date.today()
            occurred = b.date_input("Date of incident", dv, max_value=date.today())
            assigned = d.text_input("Assigned officer", c["assigned_officer"] or "")
            desc = st.text_area("Description", c["description"] or "", height=150)
            if st.form_submit_button("💾 Save changes"):
                if len(title.strip()) < 3:
                    st.error("Title must be at least 3 characters.")
                else:
                    update_case(cid, title=title.strip(), crime_type=ctype, priority=prio, status=status,
                                location=location.strip(), date_occurred=str(occurred), description=desc.strip(),
                                assigned_officer=assigned.strip())
                    st.success("Case updated.")
                    st.rerun()
        with st.expander("⚠️ Delete this case"):
            sure = st.checkbox("I understand this permanently deletes the case with its people, evidence and timeline.")
            if st.button("Delete case", disabled=not sure):
                execute("DELETE FROM cases WHERE id = ?", (int(cid),))
                st.session_state.pop("sel_case", None)
                st.rerun()

    with t2:
        p = persons_df(cid)
        if p.empty:
            st.caption("No people recorded yet.")
        else:
            st.dataframe(p[["id", "name", "role", "age", "contact", "notes", "added_at"]],
                         use_container_width=True, hide_index=True)
        with st.form("add_person", clear_on_submit=True):
            a, b, d = st.columns([2, 1, 1])
            name = a.text_input("Full name *")
            role = b.selectbox("Role", ROLES)
            age = d.number_input("Age (0 = unknown)", 0, 120, 0)
            contact = st.text_input("Contact details")
            notes = st.text_area("Notes / statement summary", height=100)
            if st.form_submit_button("➕ Add person"):
                if len(name.strip()) < 2:
                    st.error("Please enter the person's name.")
                else:
                    execute("INSERT INTO persons (case_id, name, role, age, contact, notes, added_at) VALUES (?,?,?,?,?,?,?)",
                            (int(cid), name.strip(), role, int(age) or None, contact.strip(), notes.strip(), now_str()))
                    add_timeline(cid, f"Person added: {name.strip()} ({role}).")
                    st.rerun()
        if not p.empty:
            rid = st.selectbox("Remove a person", p["id"].tolist(),
                               format_func=lambda i: p.loc[p["id"] == i, "name"].iloc[0])
            if st.button("🗑️ Remove selected person"):
                execute("DELETE FROM persons WHERE id = ?", (int(rid),))
                add_timeline(cid, "A person record was removed.")
                st.rerun()

    with t3:
        e = evidence_df(cid)
        if e.empty:
            st.caption("No evidence recorded yet.")
        else:
            st.dataframe(e[["id", "item", "etype", "status", "found_at", "collected_by", "collected_on", "storage",
                            "description"]], use_container_width=True, hide_index=True)
        with st.form("add_evidence", clear_on_submit=True):
            a, b = st.columns(2)
            item = a.text_input("Evidence item *")
            etype = b.selectbox("Type", EVIDENCE_TYPES)
            a, b, d = st.columns(3)
            found = a.text_input("Where found")
            by = b.text_input("Collected by", value=officer())
            on = d.date_input("Collected on", date.today(), max_value=date.today())
            a, b = st.columns(2)
            storage = a.text_input("Storage location")
            status = b.selectbox("Status", EVIDENCE_STATUS)
            desc = st.text_area("Description", height=80)
            if st.form_submit_button("➕ Log evidence"):
                if len(item.strip()) < 2:
                    st.error("Please name the evidence item.")
                else:
                    execute("INSERT INTO evidence (case_id, item, etype, description, found_at, collected_by,"
                            " collected_on, storage, status) VALUES (?,?,?,?,?,?,?,?,?)",
                            (int(cid), item.strip(), etype, desc.strip(), found.strip(), by.strip(), str(on),
                             storage.strip(), status))
                    add_timeline(cid, f"Evidence logged: {item.strip()} ({etype}).")
                    st.rerun()
        if not e.empty:
            a, b, d = st.columns([2, 1, 1])
            eid = a.selectbox("Update / remove item", e["id"].tolist(),
                              format_func=lambda i: e.loc[e["id"] == i, "item"].iloc[0])
            new_status = b.selectbox("New status", EVIDENCE_STATUS, key="ev_new_status")
            if b.button("Update status"):
                execute("UPDATE evidence SET status = ? WHERE id = ?", (new_status, int(eid)))
                add_timeline(cid, f"Evidence '{e.loc[e['id'] == eid, 'item'].iloc[0]}' status set to {new_status}.")
                st.rerun()
            if d.button("🗑️ Remove item"):
                execute("DELETE FROM evidence WHERE id = ?", (int(eid),))
                add_timeline(cid, "An evidence record was removed.")
                st.rerun()

    with t4:
        with st.form("add_note", clear_on_submit=True):
            note = st.text_area("Add investigation note", height=90)
            if st.form_submit_button("➕ Add to timeline"):
                if len(note.strip()) < 3:
                    st.error("Please write a note.")
                else:
                    add_timeline(cid, note.strip())
                    st.rerun()
        for r in timeline_df(cid).itertuples():
            st.markdown(f"**{r.ts}** · *{r.author}*  \n{r.entry}")
            st.divider()


def page_ai():
    hero("🤖 AI Investigation Assistant", "Gemini-powered decision support - always verify before acting.")
    if not require_ai():
        return
    st.caption("AI output is decision support only. It can be wrong; investigators remain responsible for all "
               "conclusions. Case data is sent to Google's Gemini API when you use these tools.")
    anonymize = st.checkbox("Anonymise person names and hide contact details before sending to Gemini", value=True,
                            help="Replaces recorded names with codes such as [SUSPECT-12]. Names typed inside free "
                                 "text that don't match a recorded person are not detected.")
    cid = case_picker("ai")
    tabs = st.tabs(["📋 Case summary", "📄 Draft report", "🧭 Investigative leads", "🔗 Similar cases",
                    "💬 Ask the case file", "🎙️ Statement analyzer"])

    def need_case():
        if cid is None:
            st.info("Select or create a case first.")
            return True
        return False

    with tabs[0]:
        if not need_case() and st.button("Generate summary"):
            res = run_ai("Reading the case file...", lambda: ai_summary(case_text(cid, anonymize)))
            if res:
                st.session_state[f"sum_{cid}"] = res
        if cid and st.session_state.get(f"sum_{cid}"):
            st.markdown(st.session_state[f"sum_{cid}"])

    with tabs[1]:
        if not need_case() and st.button("Draft investigation report"):
            res = run_ai("Drafting report...", lambda: ai_report(case_text(cid, anonymize), officer()))
            if res:
                st.session_state[f"rep_{cid}"] = res
        rep = cid and st.session_state.get(f"rep_{cid}")
        if rep:
            st.markdown(rep)
            st.download_button("⬇️ Download report (.md)", rep, f"report_{get_case(cid)['case_no']}.md", "text/markdown")
            if anonymize:
                st.info("The draft uses anonymised codes (e.g. [SUSPECT-12]). Replace them with real names before filing.")

    with tabs[2]:
        if not need_case() and st.button("Suggest next steps"):
            res = run_ai("Analysing gaps...", lambda: ai_leads(case_text(cid, anonymize)))
            if res is not None:
                st.session_state[f"leads_{cid}"] = res
        leads = cid and st.session_state.get(f"leads_{cid}")
        if leads:
            st.dataframe(pd.DataFrame(leads).rename(columns=str.title), use_container_width=True, hide_index=True)
            if st.button("Save these leads to the case timeline"):
                add_timeline(cid, "AI-suggested next steps (unverified): " + "; ".join(x["action"] for x in leads),
                             "AI assistant")
                st.success("Saved to timeline.")

    with tabs[3]:
        if not need_case():
            if st.button("Find possibly related cases"):
                others = cases_df()
                others = others[others["id"] != cid]
                if others.empty:
                    st.info("There are no other cases to compare with.")
                else:
                    amap = alias_map() if anonymize else {}
                    blob = "\n".join(anonymise(f"- {r.case_no} | {r.crime_type} | {r.location} | {r.date_occurred} | "
                                               f"{(r.description or '')[:350]}", amap) for r in others.head(60).itertuples())
                    res = run_ai("Comparing cases...", lambda: ai_similar(case_text(cid, anonymize), blob))
                    if res is not None:
                        st.session_state[f"sim_{cid}"] = res
            sim = st.session_state.get(f"sim_{cid}")
            if sim is not None and cid:
                if not sim:
                    st.success("No plausible links found.")
                for s in sim:
                    shared = ", ".join(map(str, s.get("shared_factors", [])))
                    st.markdown(f"**{s['case_no']}** - likelihood: **{s.get('likelihood', '?')}**  \n"
                                f"{s.get('reason', '')}  \n*Shared: {shared or 'n/a'}*")
                    st.divider()

    with tabs[4]:
        if not need_case():
            hist = st.session_state.setdefault(f"chat_{cid}", [])
            for m in hist:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
            with st.form("ask_form", clear_on_submit=True):
                q = st.text_input("Ask a question about this case",
                                  placeholder="e.g. Which evidence is still awaiting analysis?")
                sent = st.form_submit_button("Ask")
            if sent and q.strip():
                ans = run_ai("Thinking...", lambda: ai_ask(case_text(cid, anonymize), q.strip(), hist))
                if ans:
                    hist += [{"role": "user", "content": q.strip()}, {"role": "assistant", "content": ans}]
                    st.rerun()
            if hist and st.button("Clear conversation"):
                st.session_state[f"chat_{cid}"] = []
                st.rerun()

    with tabs[5]:
        text = st.text_area("Paste a statement / interview transcript", height=180, key="stmt_text")
        ups = st.file_uploader("...or upload files (txt, md, docx, pdf, image)", type=UPLOAD_TYPES,
                               accept_multiple_files=True, key="stmt_up")
        texts, atts = [], []
        for up in ups or []:
            try:
                t, a = read_upload(up.name, up.getvalue())
                texts.append(t) if t else atts.append(a)
            except ValueError as e:
                st.error(str(e))
        full = "\n\n".join(x for x in [text.strip()] + texts if x)
        if st.button("Analyse statement"):
            if not full and not atts:
                st.error("Paste a statement or upload a file.")
            else:
                res = run_ai("Analysing statement...", lambda: ai_statement(full, atts))
                if res:
                    st.session_state["stmt_result"] = res
        r = st.session_state.get("stmt_result")
        if r:
            st.markdown("#### Summary")
            st.write(r["summary"])
            for title, key in [("Key facts", "key_facts"), ("People mentioned", "people_mentioned"),
                               ("Timeline of events", "timeline"), ("Possible inconsistencies", "possible_inconsistencies"),
                               ("Suggested follow-up questions", "follow_up_questions")]:
                if r[key]:
                    st.markdown(f"**{title}**")
                    for x in r[key]:
                        st.markdown(f"- {x}")
            if cid and st.button("Save summary to the selected case's timeline"):
                add_timeline(cid, "Statement analysed (AI summary, unverified): " + r["summary"], "AI assistant")
                st.success("Saved.")


def page_reports():
    hero("📑 Reports & Export", "Printable case files and CSV exports.")
    cid = case_picker("reports")
    if cid:
        text = case_text(cid)
        st.markdown("#### Case file report (no AI used)")
        st.code(text, language="text")
        st.download_button("⬇️ Download case file (.txt)", text, f"{get_case(cid)['case_no']}.txt", "text/plain")
    st.markdown("#### Export data (CSV)")
    c1, c2, c3, c4 = st.columns(4)
    for col, label, sql in [(c1, "Cases", "SELECT * FROM cases"), (c2, "People", "SELECT * FROM persons"),
                            (c3, "Evidence", "SELECT * FROM evidence"), (c4, "Timeline", "SELECT * FROM timeline")]:
        df = query(sql)
        col.download_button(f"⬇️ {label} ({len(df)})", df.to_csv(index=False), f"{label.lower()}.csv", "text/csv",
                            disabled=df.empty)


def page_settings():
    hero("⚙️ Data & Settings", "Sample data, backups and configuration status.")
    st.markdown("#### Configuration")
    st.write(f"- Gemini API key: {'✅ loaded from secrets/environment' if get_api_key() else '❌ not found'}")
    st.write(f"- Access password: {'✅ enabled' if get_secret('APP_PASSWORD') else '⚪ not set (app is open)'}")
    st.write(f"- Database file: `{DB_FILE}`")
    st.markdown("#### Sample data")
    st.caption("Adds about 26 fictional cases with people and evidence so you can explore the dashboard.")
    if st.button("Load fictional sample data"):
        load_sample_data()
        st.success("Sample data loaded.")
    st.markdown("#### Backup")
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            st.download_button("⬇️ Download database backup", f.read(), "cims_backup.db", "application/octet-stream")
    with st.expander("⚠️ Delete ALL data"):
        sure = st.checkbox("I understand every case, person, evidence record and timeline entry will be erased.")
        if st.button("Erase everything", disabled=not sure):
            for t in ("timeline", "evidence", "persons", "cases"):
                execute(f"DELETE FROM {t}")
            st.session_state.pop("sel_case", None)
            st.success("All data erased.")


# =============================================================================
# 8. MAIN
# =============================================================================
PAGES = {"📊 Dashboard": page_dashboard, "🗂️ Cases": page_cases, "📁 Case File": page_case_file,
         "🤖 AI Assistant": page_ai, "📑 Reports & Export": page_reports, "⚙️ Data & Settings": page_settings}


def main():
    init_db()
    if not check_login():
        return
    with st.sidebar:
        st.markdown("## 🕵️ CIMS")
        st.caption("Crime Investigation Management")
        st.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
        st.divider()
        st.text_input("Your name (for audit trail)", value="Officer", key="officer")
        st.text_input("Gemini model", value=get_model(), key="model")
        st.caption("🔑 Gemini key loaded" if get_api_key() else "⚠️ No Gemini key (AI tools disabled)")
        if get_secret("APP_PASSWORD") and st.button("Sign out"):
            st.session_state["auth_ok"] = False
            st.rerun()
    try:
        PAGES[st.session_state["nav"]]()
    except Exception as e:                           # last-resort safety net
        st.error(f"Something went wrong: {e}")


if __name__ == "__main__":
    main()
