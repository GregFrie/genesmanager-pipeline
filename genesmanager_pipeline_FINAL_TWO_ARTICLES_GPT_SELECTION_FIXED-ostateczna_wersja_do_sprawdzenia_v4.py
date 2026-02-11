# 🧩 ALL-IN-ONE FINAL PIPELINE for GenesManager
# Automatyczne: parsing → wybór → generacja → publikacja

import os
import json
import time
import subprocess
import requests
import shutil
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

WP_URL = (os.getenv("WP_URL") or "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
API_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/posts" if WP_URL else ""
AUTH = (WP_USER, WP_APP_PASSWORD) if (WP_USER and WP_APP_PASSWORD) else None

# ✅ (ZMIANA: tylko dodanie endpointu media)
MEDIA_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/media" if WP_URL else ""

DNI_WSTECZ = 3
ARTYKULY_NA_ZRODLO = 2
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

# Helpers to ensure non-empty fields
def _safe_title(a):
    return (a.get("title") or a.get("lead") or a.get("url") or "").strip()

def _safe_lead(a):
    return (a.get("lead") or a.get("title") or "").strip()

# ─────────────────────────────────────────────
# 🧠 4. Wybór artykułów przez GPT z retry i logowaniem
# ─────────────────────────────────────────────
def pick_most_relevant_articles(all_articles, n=2, retries=2):
    recent_articles = [a for a in all_articles if is_recent(a.get("date", ""))]

    # Uzupełnij braki tytułów/leadów PRZED wysłaniem do GPT
    for a in recent_articles:
        if not (a.get("title") or "").strip():
            a["title"] = _safe_title(a) or f"Aktualność {a.get('source','') or ''} {a.get('date','') or ''}".strip()
        if not (a.get("lead") or "").strip():
            a["lead"] = _safe_lead(a) or a["title"]

    unpub = [a for a in recent_articles if a.get("title", "").strip() not in published_titles]

    if len(unpub) <= n:
        return unpub

    for attempt in range(retries):
        prompt = (
            "Jesteś doświadczonym redaktorem medycznym. Spośród poniższych artykułów wybierz dokładnie 2, "
            "które są najważniejsze dla właścicieli i managerów placówek medycznych. "
            "Priorytetowo traktuj informacje o postępowaniach konkursowych NFZ oraz o zmianach w przepisach (NFZ, MZ, RCL). "
            "Podaj tylko numery wybranych pozycji jako listę JSON, np. [1, 4]\n\n"
        )
        for i, a in enumerate(unpub, 1):
            prompt += f"{i}. {a['title']} — {a.get('lead','')}\n"

        # Debug listy podawanej do GPT
        print("\n📋 Po odfiltrowaniu mamy", len(unpub), "nieopublikowanych artykułów")
        for i, a in enumerate(unpub, 1):
            print(f"{i}. {a['title']}")

        try:
            if client is None:
                raise RuntimeError("Brak klienta OpenAI (OPENAI_API_KEY lub biblioteka)")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Jesteś doświadczonym redaktorem medycznym."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            content = response.choices[0].message.content.strip() if response.choices else ""
            print(f"🔹 Debug GPT response (attempt {attempt+1}): {repr(content)}")
            if not content:
                time.sleep(2)
                continue
            try:
                indices = json.loads(content)
                chosen = [unpub[i - 1] for i in indices if 0 < i <= len(unpub)]
                if chosen:
                    return chosen[:n]
            except json.JSONDecodeError:
                print("⚠️ Nie udało się sparsować JSON, retry...")
                time.sleep(2)
        except Exception as e:
            print(f"⚠️ Błąd przy wyborze przez AI (attempt {attempt+1}): {e}")
            time.sleep(2)

    print("⚠️ Fallback: wybieram pierwsze 2 nieopublikowane artykuły")
    return unpub[:n]

# ─────────────────────────────────────────────
# 🖊️ 5. Generowanie postów
# ─────────────────────────────────────────────
from genesmanager_generate_posts_from_json_dziala import generate_posts

# ─────────────────────────────────────────────
# 🌐 6. Publikacja na WordPress — 415-proof
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
        # awaryjny tytuł z treści, ~10 słów
        first_words = " ".join((body.split()[:10] if body else ["Aktualność", "GenesManager"]))
        title = (first_words + "…").strip()
    return title, body


# ✅ (ZMIANA: tylko funkcje do zdjęć)
def _guess_mime(filename: str) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".jpg") or fn.endswith(".jpeg"):
        return "image/jpeg"
    if fn.endswith(".webp"):
        return "image/webp"
    if fn.endswith(".gif"):
        return "image/gif"
    return "image/png"


def _upload_media_to_wp(image_path: Path, title: str):
    """
    Upload do /media. Zwraca (source_url, media_id) albo (None, None).
    """
    if not (MEDIA_ENDPOINT and AUTH):
        return None, None
    if not image_path.exists():
        return None, None

    mime = _guess_mime(image_path.name)
    headers_media = {
        "Accept": "application/json",
        "Content-Disposition": f'attachment; filename="{image_path.name}"',
        "Content-Type": mime,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "GenesManager/1.0 (+requests)"
    }

    try:
        with image_path.open("rb") as f:
            resp = requests.post(MEDIA_ENDPOINT, auth=AUTH, headers=headers_media, data=f.read(), timeout=60)
    except Exception as e:
        print(f"❌ Upload media wyjątek {image_path.name}: {e}")
        return None, None

    if resp.status_code not in (200, 201):
        preview = (resp.text or "")[:400].replace("\n", " ")
        print(f"❌ Upload media failed ({resp.status_code}) {image_path.name}: {preview}")
        return None, None

    try:
        data = resp.json()
        return data.get("source_url"), data.get("id")
    except Exception:
        return None, None


def _replace_local_images_with_wp_urls(body_html: str, title: str):
    """
    Podmienia src="images/..." -> URL z WP po uploadzie pliku z output_posts/images/.
    Zwraca (body_html_po, featured_media_id_lub_None)
    """
    if not body_html:
        return body_html, None

    images_dir = POST_DIR / "images"
    if not images_dir.exists():
        return body_html, None

    # src="images/xxx.png" lub src='images/xxx.png'
    pattern = r"""src=(["'])(images/[^"']+)\1"""
    matches = list(re.finditer(pattern, body_html, flags=re.IGNORECASE))
    if not matches:
        return body_html, None

    out = body_html
    featured_media_id = None

    for m in matches:
        local_rel = m.group(2)  # images/xxx.png
        local_name = local_rel.split("/", 1)[1] if "/" in local_rel else local_rel
        local_path = images_dir / local_name

        source_url, media_id = _upload_media_to_wp(local_path, title)
        if not source_url:
            continue

        if featured_media_id is None and media_id:
            featured_media_id = media_id

        # podmień tylko pierwszy pasujący fragment (dla tej iteracji)
        out = re.sub(
            r"""src=(["'])%s\1""" % re.escape(local_rel),
            f'src="{source_url}"',
            out,
            count=1,
            flags=re.IGNORECASE
        )

    return out, featured_media_id


def publish_to_wordpress():
    if not POST_DIR.exists():
        print(f"❌ Folder {POST_DIR} nie istnieje.")
        return

    if not (API_ENDPOINT and AUTH and WP_URL):
        print("⚠️ Brak konfiguracji WP_URL/WP_USER/WP_APP_PASSWORD – pomijam publikację.")
        return

    headers_json = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=UTF-8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "GenesManager/1.0 (+requests)"
    }
    headers_form = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "GenesManager/1.0 (+requests)"
    }

    def _post_with_fallback(payload):
        # 1) JSON
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

            # ✅ (ZMIANA: tylko tu – upload/podmiana obrazka + featured_media)
            body2, featured_media_id = _replace_local_images_with_wp_urls(body, title)

            payload = {"title": title, "content": body2, "status": "publish"}
            if featured_media_id:
                payload["featured_media"] = featured_media_id

            resp = _post_with_fallback(payload)
            if resp.status_code == 201:
                print(f"✅ Opublikowano: {title}")
            else:
                preview = (resp.text or "")[:600].replace("\n", " ")
                print(f"❌ Błąd publikacji {title}: {resp.status_code} – {preview}")
        else:
            print(f"⚠️ Pominięto pusty lub niepoprawny plik: {file.name}")

# ─────────────────────────────────────────────
# 🚀 7. Główna logika
# ─────────────────────────────────────────────
def main():
    print("\n🛠️ 1. Uruchamianie parsera...")
    parser_path = Path(__file__).parent / "parser_all_sources_combined_dziala.py"
    result = subprocess.run(["python", str(parser_path.resolve())])

    if result.returncode != 0:
        print("❌ Parser nie został uruchomiony poprawnie (kontynuuję, jeśli JSON istnieje).")

    # Bezpieczne czyszczenie output_posts
    POST_DIR.mkdir(exist_ok=True)
    for file in POST_DIR.glob("*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
        except Exception as e:
            print(f"⚠️ Nie udało się usunąć {file}: {e}")

    if not ARTICLES_JSON_PATH.exists():
        print("❌ Nie znaleziono pliku all_articles_combined.json po parsowaniu.")
        return

    print("\n📥 2. Wczytywanie artykułów...")
    with ARTICLES_JSON_PATH.open("r", encoding="utf-8") as f:
        all_articles = json.load(f)

    print("\n🎯 3. Wybór 2 najważniejszych artykułów przez AI...")
    selected = pick_most_relevant_articles(all_articles)

    if not selected:
        print("⚠️ Brak nowych artykułów do przetworzenia.")
        return

    print("\n✍️ 4. Generowanie postów z AI...")
    generate_posts(selected)

    print("\n🌐 5. Publikacja na WordPress...")
    publish_to_wordpress()

    print("\n💾 6. Zapis publikacji...")
    for art in selected:
        published_titles.add(art.get("title", ""))
    save_published_titles(published_titles)

    print("\n✅ Zakończono cały pipeline.")

if __name__ == "__main__":
    main()
