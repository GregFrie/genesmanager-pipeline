# ─────────────────────────────────────────────
# 🧩 ALL-IN-ONE FINAL PIPELINE for GenesManager
# Automatyczne: parsing → wybór → generacja → publikacja
# ─────────────────────────────────────────────

import os
import json
import time
import subprocess
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI  # nowy import

# ─────────────────────────────────────────────
# ⚙️ 1. Konfiguracja
# ─────────────────────────────────────────────
load_dotenv("bot.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # zaktualizowany klient

WP_URL = os.getenv("WP_URL")
WP_USER = os.getenv("WP_USER")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
API_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/posts"
AUTH = (WP_USER, WP_APP_PASSWORD)

DNI_WSTECZ = 3
ARTYKULY_NA_ZRODLO = 2
CUTOFF_DATE = datetime.today() - timedelta(days=DNI_WSTECZ)
PUBLISHED_TITLES_PATH = Path("published_posts.json")
ARTICLES_JSON_PATH = Path("all_articles_combined.json")
POST_DIR = Path("output_posts")

# ─────────────────────────────────────────────
# 📦 2. Historia publikacji
# ─────────────────────────────────────────────
if PUBLISHED_TITLES_PATH.exists():
    with PUBLISHED_TITLES_PATH.open("r", encoding="utf-8") as f:
        published_titles = set(json.load(f))
else:
    published_titles = set()

def save_published_titles(titles):
    with PUBLISHED_TITLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(list(titles)), f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
# 🕒 3. Pomocnicza funkcja daty
# ─────────────────────────────────────────────
def is_recent(article_date_str):
    try:
        article_date = datetime.strptime(article_date_str, "%Y-%m-%d")
        return article_date >= CUTOFF_DATE
    except Exception:
        return False

# ─────────────────────────────────────────────
# 🧠 4. Wybór artykułów przez GPT-4
# ─────────────────────────────────────────────
def pick_most_relevant_articles(all_articles, n=2):
    recent_articles = [a for a in all_articles if is_recent(a.get("date", ""))]
    unpub = [a for a in recent_articles if a.get("title", "") not in published_titles]

    if len(unpub) <= n:
        return unpub

    prompt = (
        "Jesteś doświadczonym redaktorem medycznym. Spośród poniższych artykułów wybierz dokładnie 2, które są najważniejsze dla właścicieli i managerów placówek medycznych. "
        "Priorytetowo traktuj informacje o postępowaniach konkursowych NFZ oraz o zmianach w przepisach (NFZ, MZ, RCL). "
        "Podaj tylko numery wybranych pozycji jako listę JSON, np. [1, 4]\n\n"
    )
    for i, a in enumerate(unpub, 1):
        prompt += f"{i}. {a['title']}: {a.get('lead', '')}\n"

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Jesteś doświadczonym redaktorem medycznym."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        content = response.choices[0].message.content
        indices = json.loads(content)
        return [unpub[i - 1] for i in indices if 0 < i <= len(unpub)]
    except Exception as e:
        print(f"⚠️ Błąd przy wyborze przez AI: {e}")
        return unpub[:n]

# ─────────────────────────────────────────────
# 🖊️ 5. Generowanie postów
# ─────────────────────────────────────────────
from genesmanager_generate_posts_from_json_dziala import generate_posts

# ─────────────────────────────────────────────
# 🌐 6. Publikacja na WordPress
# ─────────────────────────────────────────────
def extract_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        if not lines:
            return None, None
        title = lines[0].replace("#", "").replace("<h1>", "").replace("</h1>", "").strip()
        title = title.capitalize()
        body = "".join(lines[1:]).strip()
        return title, body

def publish_to_wordpress():
    if not POST_DIR.exists():
        print(f"❌ Folder {POST_DIR} nie istnieje.")
        return

    for file in sorted(POST_DIR.glob("*.txt")):
        title, body = extract_title_and_body(file)
        if title and body:
            payload = {
                "title": title,
                "content": body,
                "status": "publish",
                "categories": [],
            }
            response = requests.post(API_ENDPOINT, auth=AUTH, json=payload)
            if response.status_code == 201:
                print(f"✅ Opublikowano: {title}")
            else:
                print(f"❌ Błąd publikacji {title}: {response.status_code} – {response.text}")
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
        print("❌ Parser nie został uruchomiony poprawnie.")
        return

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
    with open("selected_articles.json", "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)

    with open("selected_articles.json", "r", encoding="utf-8") as f:
        selected_articles = json.load(f)
        to_generate = [a for a in selected_articles if a.get("title", "") not in published_titles]

        if not to_generate:
            print("⚠️ Wszystkie wybrane artykuły zostały już opublikowane – brak nowych postów do generacji.")
            return

        generate_posts(to_generate)

    print("\n🌐 5. Publikacja na WordPress...")
    publish_to_wordpress()

    print("\n💾 6. Zapis publikacji...")
    for art in selected:
        published_titles.add(art.get("title", ""))
    save_published_titles(published_titles)

    print("\n✅ Zakończono cały pipeline.")

if __name__ == "__main__":
    main()
