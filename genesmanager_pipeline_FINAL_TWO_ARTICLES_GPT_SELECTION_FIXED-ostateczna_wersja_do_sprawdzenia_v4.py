# 🧩 ALL-IN-ONE FINAL PIPELINE for GenesManager
# Automatyczne: parsing → wybór → generacja → publikacja

import os
import json
import time
import subprocess
import requests
import shutil
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ─────────────────────────────────────────────
# ⚙️ 1. Konfiguracja
# ─────────────────────────────────────────────
load_dotenv("bot.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

# modele
PRIMARY_MODEL = "gpt-5"       # bez parametru temperature!
FALLBACK_MODEL = "gpt-4o-mini"  # fallback (tu możemy dać temperature)

WP_URL = (os.getenv("WP_URL") or "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
API_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/posts" if WP_URL else ""
AUTH = (WP_USER, WP_APP_PASSWORD) if (WP_USER and WP_APP_PASSWORD) else None

DNI_WSTECZ = 3
CUTOFF_DATE = datetime.today() - timedelta(days=DNI_WSTECZ)
PUBLISHED_TITLES_PATH = Path("published_posts.json")
ARTICLES_JSON_PATH = Path("all_articles_combined.json")
POST_DIR = Path("output_posts")

if PUBLISHED_TITLES_PATH.exists():
    try:
        with PUBLISHED_TITLES_PATH.open("r", encoding="utf-8") as f:
            published_titles = set(json.load(f))
    except Exception:
        published_titles = set()
else:
    published_titles = set()

def save_published_titles(titles):
    with PUBLISHED_TITLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(list(titles)), f, ensure_ascii=False, indent=2)

def is_recent(article_date_str):
    try:
        article_date = datetime.strptime(article_date_str, "%Y-%m-%d")
        return article_date >= CUTOFF_DATE
    except Exception:
        return False

def _safe_title(a):
    return (a.get("title") or a.get("lead") or a.get("url") or "").strip()

def _safe_lead(a):
    return (a.get("lead") or a.get("title") or "").strip()

def _strip_code_fences(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # usuń ```json ... ``` lub ``` ... ```
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _try_parse_indices(s: str, max_n: int):
    """
    Spróbuj sparsować listę indeksów z tekstu s do listy int (1‑indeksowane).
    Dodatkowe bezpieczeństwo na wypadek spacji/nowych linii.
    """
    s = _strip_code_fences(s)
    try:
        data = json.loads(s)
        if isinstance(data, list):
            out = []
            for x in data:
                try:
                    i = int(x)
                    if 1 <= i <= max_n:
                        out.append(i)
                except Exception:
                    continue
            return out
    except Exception:
        pass
    # heurystyka: wyciągnij liczby z nawiasów kwadratowych
    m = re.search(r"\[(.*?)\]", s)
    if m:
        nums = re.findall(r"\d+", m.group(1))
        return [int(x) for x in nums if 1 <= int(x) <= max_n]
    return []

# ─────────────────────────────────────────────
# 🧠 2. Wybór artykułów przez GPT-5 (+ fallback)
# ─────────────────────────────────────────────
def pick_most_relevant_articles(all_articles, n=2, retries=2):
    recent_articles = [a for a in all_articles if is_recent(a.get("date", ""))]

    for a in recent_articles:
        if not (a.get("title") or "").strip():
            a["title"] = _safe_title(a) or f"Aktualność {a.get('source','')} {a.get('date','')}".strip()
        if not (a.get("lead") or "").strip():
            a["lead"] = _safe_lead(a) or a["title"]

    unpub = [a for a in recent_articles if a.get("title", "").strip() not in published_titles]

    if len(unpub) <= n:
        return unpub

    base_prompt = (
        "Jesteś doświadczonym redaktorem medycznym. Spośród poniższych artykułów wybierz dokładnie 2, "
        "które są najważniejsze dla właścicieli i managerów placówek medycznych. "
        "Priorytet: 1) konkursy NFZ, 2) zmiany w przepisach (NFZ, MZ, RCL). "
        "Podaj tylko numery w JSON, np. [1, 4]\n\n"
    )

    listing = ""
    for i, a in enumerate(unpub, 1):
        listing += f"{i}. {a['title']} — {a.get('lead','')}\n"

    messages = [
        {"role": "system", "content": "Jesteś doświadczonym redaktorem medycznym."},
        {"role": "user", "content": base_prompt + listing}
    ]

    def _ask_ai(use_primary=True):
        if client is None:
            raise RuntimeError("Brak klienta OpenAI (OPENAI_API_KEY?)")
        if use_primary:
            # GPT-5 — bez temperature
            resp = client.chat.completions.create(
                model=PRIMARY_MODEL,
                messages=messages
            )
        else:
            # fallback: gpt-4o-mini — możemy użyć niskiej temperatury
            resp = client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=0.2
            )
        return (resp.choices[0].message.content or "").strip()

    print("\n📋 Artykuły kandydujące:", len(unpub))
    for i, a in enumerate(unpub, 1):
        print(f"{i}. {a['title']}")

    for attempt in range(retries):
        try:
            use_primary = (attempt == 0)
            content = _ask_ai(use_primary=use_primary)
            print(f"🔹 Debug GPT response (attempt {attempt+1}): {repr(content)}")
            idxs = _try_parse_indices(content, max_n=len(unpub))
            if idxs:
                chosen = [unpub[i - 1] for i in idxs][:n]
                if chosen:
                    return chosen
        except Exception as e:
            which = PRIMARY_MODEL if attempt == 0 else FALLBACK_MODEL
            print(f"⚠️ AI error (attempt {attempt+1}, {which}): {e}")
            time.sleep(1.0)

    print("⚠️ Fallback → wybieram pierwsze 2")
    return unpub[:n]

# ─────────────────────────────────────────────
# 🖊️ 3. Generowanie postów
# ─────────────────────────────────────────────
from genesmanager_generate_posts_from_json_dziala import generate_posts

# ─────────────────────────────────────────────
# 🌐 4. Publikacja na WordPress (z 415‑proof fallback)
# ─────────────────────────────────────────────
def extract_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return None, None
    lines = text.splitlines()
    title = (lines[0] or "").replace("#", "").replace("<h1>", "").replace("</h1>", "").strip()
    body = "\n".join(lines[1:]).strip()
    if not title:
        first_words = " ".join((body.split()[:10] if body else ["Aktualność", "GenesManager"]))
        title = (first_words + "…").strip()
    return title, body

def publish_to_wordpress():
    if not POST_DIR.exists():
        print(f"❌ Brak folderu {POST_DIR}")
        return
    if not (API_ENDPOINT and AUTH and WP_URL):
        print("⚠️ Brak konfiguracji WP_URL/WP_USER/WP_APP_PASSWORD")
        return

    headers_json = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "GenesManager/1.0",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    headers_form = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "GenesManager/1.0",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    def _post_with_fallback(payload):
        # 1) klasyczny JSON
        resp = requests.post(API_ENDPOINT, auth=AUTH, headers=headers_json, json=payload, timeout=30)
        if resp.status_code == 201:
            return resp

        # 2) raw JSON w body
        if resp.status_code in (400, 403, 404, 406, 415, 500):
            resp2 = requests.post(
                API_ENDPOINT, auth=AUTH, headers=headers_json,
                data=json.dumps(payload).encode("utf-8"), timeout=30
            )
            if resp2.status_code == 201:
                return resp2

            # 3) application/x-www-form-urlencoded
            resp3 = requests.post(
                API_ENDPOINT, auth=AUTH, headers=headers_form,
                data={"title": payload["title"], "content": payload["content"], "status": payload["status"]},
                timeout=30
            )
            return resp3
        return resp

    for file in sorted(POST_DIR.glob("*.txt")):
        title, body = extract_title_and_body(file)
        if title and body:
            payload = {"title": title, "content": body, "status": "publish"}
            resp = _post_with_fallback(payload)
            if resp.status_code == 201:
                print(f"✅ Opublikowano: {title}")
            else:
                preview = (resp.text or "")[:600].replace("\n", " ")
                print(f"❌ Błąd {title}: {resp.status_code} – {preview}")
        else:
            print(f"⚠️ Pominięto plik: {file.name}")

# ─────────────────────────────────────────────
# 🚀 5. Main
# ─────────────────────────────────────────────
def main():
    print("\n🛠️ Parser...")
    parser_path = Path(__file__).parent / "parser_all_sources_combined_dziala.py"
    result = subprocess.run(["python", str(parser_path.resolve())])

    if result.returncode != 0:
        print("❌ Parser error (kontynuuję jeśli JSON istnieje)")

    POST_DIR.mkdir(exist_ok=True)
    for file in POST_DIR.glob("*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
        except Exception as e:
            print(f"⚠️ Delete fail {file}: {e}")

    if not ARTICLES_JSON_PATH.exists():
        print("❌ Brak all_articles_combined.json")
        return

    with ARTICLES_JSON_PATH.open("r", encoding="utf-8") as f:
        all_articles = json.load(f)

    print("\n🎯 Wybór artykułów...")
    selected = pick_most_relevant_articles(all_articles)

    if not selected:
        print("⚠️ Brak nowych artykułów")
        return

    print("\n✍️ Generowanie postów...")
    generate_posts(selected)

    print("\n🌐 Publikacja...")
    publish_to_wordpress()

    print("\n💾 Zapis publikacji...")
    for art in selected:
        published_titles.add(art.get("title", ""))
    save_published_titles(published_titles)

    print("\n✅ Pipeline zakończony")

if __name__ == "__main__":
    main()
