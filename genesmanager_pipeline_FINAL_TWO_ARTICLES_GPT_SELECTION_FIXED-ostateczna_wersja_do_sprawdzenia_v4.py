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

WP_URL = (os.getenv("WP_URL") or "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
API_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/posts" if WP_URL else ""
AUTH = (WP_USER, WP_APP_PASSWORD) if (WP_USER and WP_APP_PASSWORD) else None

MEDIA_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/media" if WP_URL else ""

DNI_WSTECZ = 3
CUTOFF_DATE = datetime.today() - timedelta(days=DNI_WSTECZ)

PUBLISHED_TITLES_PATH = Path("published_posts.json")   # przechowujemy klucze publikacji (URL; fallback: title)
ARTICLES_JSON_PATH = Path("all_articles_combined.json")
POST_DIR = Path("output_posts")

# ─────────────────────────────────────────────
# ✅ DEDUPE: po URL (fallback: title)
# ─────────────────────────────────────────────
def _load_published_set() -> set:
    if not PUBLISHED_TITLES_PATH.exists():
        return set()
    try:
        with PUBLISHED_TITLES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set([str(x).strip() for x in data if str(x).strip()])
        if isinstance(data, dict):
            return set([str(x).strip() for x in data.get("items", []) if str(x).strip()])
    except Exception:
        pass
    return set()

published_keys = _load_published_set()

def save_published_keys(keys: set):
    with PUBLISHED_TITLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(list(keys)), f, ensure_ascii=False, indent=2)

def _key_for_article(a: dict) -> str:
    return (a.get("url") or a.get("title") or "").strip()

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# ✅ PRIORYTET: kontraktowanie NFZ + dofinansowania (scoring + autowybór)
# ─────────────────────────────────────────────
PRIO_KEYWORDS = [
    # kontraktowanie / konkursy / umowy
    "konkurs", "postępowanie", "ogłoszenie postępownia", "kontrakty", "umowy", "aneks",
    "świadczeniodawca", "zawarcie umowy", "warunki realizacji", "zarządzenie prezesa nfz",
    "komunikat nfz", "sprawozdawczość", "rozliczenia", "korekty", "zwroty",
    "wycena", "taryfy", "limity", "budżet", "stawki", "ryczałt",

    # finansowanie / dofinansowania
    "dofinansowania", "dotacje", "granty", "subwencje", "kpo", "fundusz", "środki",
    "nabór", "program", "finansowanie", "refundacja",
]

def _prio_score(article: dict) -> int:
    txt = f"{article.get('title','')} {article.get('lead','')}".lower()
    score = 0
    for kw in PRIO_KEYWORDS:
        if kw in txt:
            score += 2
    if "nfz" in txt:
        score += 3
    if ("konkurs" in txt) or ("postępowan" in txt):
        score += 3
    if ("dofinansowan" in txt) or ("dotacj" in txt) or ("kpo" in txt):
        score += 3
    return score

# ─────────────────────────────────────────────
# ✅ FIX: twarde parsowanie indeksów z GPT (obsługa ```json ...```)
# ─────────────────────────────────────────────
def _parse_indices_from_gpt(content: str):
    if not content:
        return None
    c = content.strip()

    c = re.sub(r"^\s*```(?:json)?\s*", "", c, flags=re.I)
    c = re.sub(r"\s*```\s*$", "", c)

    m = re.search(r"\[[\s\d,]+\]", c)
    if not m:
        return None

    try:
        arr = json.loads(m.group(0))
        if isinstance(arr, list):
            out = []
            for x in arr:
                try:
                    out.append(int(x))
                except Exception:
                    pass
            return out
    except Exception:
        return None

    return None

# ─────────────────────────────────────────────
# 🧠 4. Wybór artykułów przez GPT z retry i logowaniem
# + priorytet kontraktowanie/dofinansowania
# + dedupe po URL
# ─────────────────────────────────────────────
def pick_most_relevant_articles(all_articles, n=2, retries=2):
    recent_articles = [a for a in all_articles if is_recent(a.get("date", ""))]

    for a in recent_articles:
        if not (a.get("title") or "").strip():
            a["title"] = _safe_title(a) or f"Aktualność {a.get('source','') or ''} {a.get('date','') or ''}".strip()
        if not (a.get("lead") or "").strip():
            a["lead"] = _safe_lead(a) or a["title"]

    # ✅ dedupe po URL (fallback title)
    unpub = [a for a in recent_articles if _key_for_article(a) and _key_for_article(a) not in published_keys]
    if not unpub:
        return []

    # ✅ sortuj po priorytecie
    unpub = sorted(unpub, key=_prio_score, reverse=True)

    # ✅ autowybór jeśli są tematy priorytetowe
    prio = [a for a in unpub if _prio_score(a) >= 6]
    if len(prio) >= n:
        print("⭐ Priorytet: wykryto tematy kontraktowanie/dofinansowania – wybór bez GPT.")
        return prio[:n]

    if len(unpub) <= n:
        return unpub

    for attempt in range(retries):
        prompt = (
            "Jesteś doświadczonym redaktorem medycznym GenesManager.pl. Masz wybrać DOKŁADNIE 2 tematy do publikacji.\n\n"
            "ZASADA PRIORYTETU (bezwzględna):\n"
            "1) Kontraktowanie z NFZ: postępowania konkursowe, ogłoszenia, aneksy, warunki umów, wyceny i rozliczenia.\n"
            "2) Dofinansowania/finansowanie: KPO, dotacje, nabory, środki, programy finansowane.\n\n"
            "Dopiero jeśli w zestawie NIE MA takich tematów, wybierz inne ważne zmiany regulacyjne.\n"
            "Zwróć WYŁĄCZNIE listę JSON z numerami pozycji, np. [1, 4]. Bez ``` i bez komentarzy.\n\n"
        )
        for i, a in enumerate(unpub, 1):
            prompt += f"{i}. {a['title']} — {a.get('lead','')}\n"

        print("\n📋 Nieopublikowane (posortowane priorytetem):", len(unpub))
        for i, a in enumerate(unpub, 1):
            print(f"{i}. ({_prio_score(a)}) {a['title']}")

        try:
            if client is None:
                raise RuntimeError("Brak klienta OpenAI (OPENAI_API_KEY lub biblioteka)")

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Jesteś doświadczonym redaktorem medycznym."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )

            content = response.choices[0].message.content.strip() if response.choices else ""
            print(f"🔹 Debug GPT response (attempt {attempt+1}): {repr(content)}")

            indices = _parse_indices_from_gpt(content)
            if not indices:
                print("⚠️ Nie udało się sparsować indeksów, retry...")
                time.sleep(2)
                continue

            chosen = [unpub[i - 1] for i in indices if 0 < i <= len(unpub)]
            if chosen:
                return chosen[:n]

        except Exception as e:
            print(f"⚠️ Błąd przy wyborze przez AI (attempt {attempt+1}): {e}")
            time.sleep(2)

    print("⚠️ Fallback: wybieram pierwsze 2 nieopublikowane (po priorytecie)")
    return unpub[:n]

# ─────────────────────────────────────────────
# 🖊️ 5. Generowanie postów
# ─────────────────────────────────────────────
from genesmanager_generate_posts_from_json_dziala import generate_posts

# ─────────────────────────────────────────────
# ✅ Tytuł z H1 z generatora + usuwanie H1 z treści (żeby nie dublować)
# ─────────────────────────────────────────────
def _title_from_filename(file_path: Path) -> str:
    name = file_path.stem
    name = re.sub(r"^\d{3}_", "", name)
    name = name.replace("_", " ").strip()
    return name or "Aktualność GenesManager"

def extract_title_and_body(file_path: Path):
    body = file_path.read_text(encoding="utf-8").strip()
    if not body:
        return None, None

    # 1) tytuł z <h1>...</h1>
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.I | re.S)
    if m:
        title_raw = re.sub(r"<[^>]+>", "", m.group(1))
        title = title_raw.strip()

        # usuń ten H1 z body, żeby WP nie miał podwójnego nagłówka
        body = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", body, count=1, flags=re.I | re.S).strip()

        return title, body

    # fallback: z nazwy pliku
    return _title_from_filename(file_path), body

# ─────────────────────────────────────────────
# ✅ Zdjęcia: upload -> podmiana src -> featured_media
# ✅ Brak duplikacji: jeśli ustawiono featured, usuń pierwszy <img> z treści
# ─────────────────────────────────────────────
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
    if not body_html:
        return body_html, None

    images_dir = POST_DIR / "images"
    if not images_dir.exists():
        return body_html, None

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

        out = re.sub(
            r"""src=(["'])%s\1""" % re.escape(local_rel),
            f'src="{source_url}"',
            out,
            count=1,
            flags=re.IGNORECASE
        )

    return out, featured_media_id

def _remove_first_img_tag(html: str) -> str:
    if not html:
        return html
    return re.sub(r"<img\b[^>]*>\s*", "", html, count=1, flags=re.IGNORECASE)

# ─────────────────────────────────────────────
# 🌐 6. Publikacja na WordPress — 415-proof
# ─────────────────────────────────────────────
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
        resp = requests.post(API_ENDPOINT, auth=AUTH, headers=headers_json, json=payload, timeout=30)
        if resp.status_code == 201:
            return resp

        if resp.status_code in (400, 403, 404, 406, 415, 500):
            resp2 = requests.post(
                API_ENDPOINT, auth=AUTH, headers=headers_json,
                data=json.dumps(payload).encode("utf-8"), timeout=30
            )
            if resp2.status_code == 201:
                return resp2

            resp3 = requests.post(
                API_ENDPOINT, auth=AUTH, headers=headers_form,
                data={"title": payload["title"], "content": payload["content"], "status": payload["status"]},
                timeout=30
            )
            return resp3
        return resp

    for file in sorted(POST_DIR.glob("*.txt")):
        title, body = extract_title_and_body(file)
        if not (title and body):
            print(f"⚠️ Pominięto pusty lub niepoprawny plik: {file.name}")
            continue

        # upload + podmiana src + featured id
        body2, featured_media_id = _replace_local_images_with_wp_urls(body, title)

        # ✅ jeśli jest featured image, usuń obrazek z treści (żeby nie dublowało)
        if featured_media_id:
            body2 = _remove_first_img_tag(body2)

        payload = {"title": title, "content": body2, "status": "publish"}
        if featured_media_id:
            payload["featured_media"] = featured_media_id

        resp = _post_with_fallback(payload)
        if resp.status_code == 201:
            print(f"✅ Opublikowano: {title}")
        else:
            preview = (resp.text or "")[:600].replace("\n", " ")
            print(f"❌ Błąd publikacji {title}: {resp.status_code} – {preview}")

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

    print("\n🎯 3. Wybór 2 najważniejszych artykułów (priorytet: kontraktowanie NFZ + dofinansowania)...")
    selected = pick_most_relevant_articles(all_articles, n=2, retries=2)

    if not selected:
        print("⚠️ Brak nowych artykułów do przetworzenia.")
        return

    print("\n✍️ 4. Generowanie postów z AI...")
    generate_posts(selected)

    print("\n🌐 5. Publikacja na WordPress...")
    publish_to_wordpress()

    print("\n💾 6. Zapis publikacji (dedupe po URL)...")
    for art in selected:
        k = _key_for_article(art)
        if k:
            published_keys.add(k)
    save_published_keys(published_keys)

    print("\n✅ Zakończono cały pipeline.")

if __name__ == "__main__":
    main()
