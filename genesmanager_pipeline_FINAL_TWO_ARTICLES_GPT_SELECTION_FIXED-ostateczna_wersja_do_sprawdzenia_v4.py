# 🧩 GenesManager Render-Stable FINAL Pipeline
# Parsing → AI Selection → Post Generation → WordPress Publish (without subprocess)

import os
import json
import time
import requests
import shutil
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import json
from datetime import datetime

def accept_cookies(driver, selectors):
    try:
        for selector in selectors:
            WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector))).click()
            print(f"✅ Zaakceptowano cookies przez selektor: {selector}")
            return
    except:
        print("ℹ️ Brak widocznego popupu z cookies (OK)")

def parse_serwiszoz_articles():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    driver.get("https://serwiszoz.pl/")
    accept_cookies(driver, ["button.accept-cookie", "#cn-accept-cookie", ".cc-btn"])
    WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.item")))
    articles = driver.find_elements(By.CSS_SELECTOR, "div.item")
    results = []
    for article in articles:
        try:
            title = article.find_element(By.CSS_SELECTOR, "h2").text.strip()
            url = article.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
            date = article.find_element(By.CSS_SELECTOR, "div.meta").text.strip()
            results.append({
                "title": title,
                "url": url,
                "source": "SerwisZOZ",
                "date": date,
                "content": ""  # Treść ładowana osobno
            })
        except Exception as e:
            print(f"Błąd artykułu: {e}")
    driver.quit()
    return results

def parse_rynekzdrowia_articles():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.rynekzdrowia.pl/")
    accept_cookies(driver, ["button#didomi-notice-agree-button", ".cookie-accept", ".accept-cookies"])
    articles = []
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article")))
        for el in driver.find_elements(By.CSS_SELECTOR, "article"):
            try:
                a = el.find_element(By.TAG_NAME, "a")
                href = a.get_attribute("href")
                title = a.text.strip()
                articles.append({
                    "title": title,
                    "url": href,
                    "source": "Rynek Zdrowia",
                    "date": str(datetime.today().date()),
                    "content": ""
                })
            except:
                continue
    finally:
        driver.quit()
    return articles

# Inne funkcje parsujące niezmienione (NFZ, gov.pl itd.)
# Kod główny uruchamiający wszystko też niezmieniony

from pathlib import Path
from openai import OpenAI

# Import parser and generator with current filenames
import parser_all_sources_combined_dziala as parser
from genesmanager_generate_posts_from_json_dziala import generate_posts

# ─────────────────────────────────────────────
# ⚙️ 1. Config
# ─────────────────────────────────────────────
load_dotenv("bot.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

WP_URL = os.getenv("WP_URL")
WP_USER = os.getenv("WP_USER")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
API_ENDPOINT = f"{WP_URL}/wp-json/wp/v2/posts"
AUTH = (WP_USER, WP_APP_PASSWORD)

DNI_WSTECZ = 3
CUTOFF_DATE = datetime.today() - timedelta(days=DNI_WSTECZ)
PUBLISHED_TITLES_PATH = Path("published_posts.json")
ARTICLES_JSON_PATH = Path("all_articles_combined.json")
POST_DIR = Path("output_posts")

if PUBLISHED_TITLES_PATH.exists():
    with PUBLISHED_TITLES_PATH.open("r", encoding="utf-8") as f:
        published_titles = set(json.load(f))
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

# ─────────────────────────────────────────────
# 🧠 2. AI Selection with logging & fallback
# ─────────────────────────────────────────────
def pick_most_relevant_articles(all_articles, n=2, retries=2):
    recent_articles = [a for a in all_articles if is_recent(a.get("date", ""))]
    unpub = [a for a in recent_articles if a.get("title", "").strip() not in published_titles]

    print(f"\nℹ️ Po odfiltrowaniu mamy {len(unpub)} nieopublikowanych artykułów")
    for i, a in enumerate(unpub, 1):
        print(f"   {i}. {a.get('title','(brak tytułu)')}")

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
            prompt += f"{i}. {a.get('title','(brak tytułu)')}: {a.get('lead','')}\n"

        try:
            response = client.chat.completions.create(
                model="gpt-4",
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
                selected = [unpub[i - 1] for i in indices if 0 < i <= len(unpub)]
                with open("selected_articles.json","w",encoding="utf-8") as f:
                    json.dump(selected,f,ensure_ascii=False,indent=2)
                return selected
            except json.JSONDecodeError:
                print("⚠️ Nie udało się sparsować JSON, retry...")
                time.sleep(2)
        except Exception as e:
            print(f"⚠️ Błąd przy wyborze przez AI (attempt {attempt+1}): {e}")
            traceback.print_exc()
            time.sleep(2)

    print("⚠️ Fallback: wybieram pierwsze 2 nieopublikowane artykuły")
    return unpub[:n]

# ─────────────────────────────────────────────
# 🌐 3. WordPress Publish
# ─────────────────────────────────────────────
def extract_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        if not lines:
            return None, None
        title = lines[0].strip()
        body = "".join(lines[1:]).strip()
        return title, body

def publish_to_wordpress():
    if not POST_DIR.exists():
        print(f"❌ Folder {POST_DIR} nie istnieje.")
        return

    headers = {"Content-Type": "application/json"}

    for file in sorted(POST_DIR.glob("*.txt")):
        title, body = extract_title_and_body(file)
        if title and body:
            payload = {
                "title": title,
                "content": body,
                "status": "publish",
                "categories": [],
            }
            try:
                response = requests.post(API_ENDPOINT, auth=AUTH, headers=headers, json=payload)
                if response.status_code == 201:
                    print(f"✅ Opublikowano: {title}")
                else:
                    print(f"❌ Błąd publikacji {title}: {response.status_code} – {response.text}")
            except Exception as e:
                print(f"❌ Błąd połączenia z WordPress: {e}")
                traceback.print_exc()
        else:
            print(f"⚠️ Pominięto pusty lub niepoprawny plik: {file.name}")

# ─────────────────────────────────────────────
# 🚀 4. Main
# ─────────────────────────────────────────────
def main():
    print("\n🛠️ 1. Uruchamianie parsera bez subprocess...")
    try:
        parser.run_all_parsers()
    except Exception as e:
        print(f"❌ Parser zgłosił błąd: {e}")
        traceback.print_exc()
        return

    # Clear output_posts
    POST_DIR.mkdir(exist_ok=True)
    for file in POST_DIR.glob("*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
        except Exception as e:
            print(f"⚠️ Nie udało się usunąć {file}: {e}")
            traceback.print_exc()

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
    try:
        generate_posts(selected)
    except Exception as e:
        print(f"❌ Błąd przy generowaniu postów: {e}")
        traceback.print_exc()

    print("\n🌐 5. Publikacja na WordPress...")
    publish_to_wordpress()

    print("\n💾 6. Zapis publikacji...")
    for art in selected:
        if art.get("title", "").strip():
            published_titles.add(art["title"].strip())
    save_published_titles(published_titles)

    print("\n✅ Zakończono cały pipeline.")

if __name__ == "__main__":
    main()
