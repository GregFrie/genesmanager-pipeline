import json
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# 🚀 Pomocnicza funkcja do tworzenia drivera
# ─────────────────────────────────────────────
def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=options)

# ─────────────────────────────────────────────
# 🔹 Funkcja fallback do pobrania statycznego HTML
# ─────────────────────────────────────────────
def fetch_static_html(url, css_selector, title_selector=None, lead_selector=None):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(css_selector)
        results = []
        for item in items:
            try:
                link_tag = item.select_one("a")
                url_link = link_tag["href"] if link_tag else ""
                if url_link and not url_link.startswith("http"):
                    if "rynekzdrowia.pl" in url:
                        url_link = "https://www.rynekzdrowia.pl" + url_link
                    elif "serwiszoz.pl" in url:
                        url_link = "https://serwiszoz.pl" + url_link

                title_tag = item.select_one(title_selector) if title_selector else None
                title = title_tag.get_text(strip=True) if title_tag else ""

                lead_tag = item.select_one(lead_selector) if lead_selector else None
                lead = lead_tag.get_text(strip=True) if lead_tag else title

                results.append({
                    "title": title or "Aktualizacja",
                    "url": url_link,
                    "lead": lead,
                    "date": datetime.today().strftime("%Y-%m-%d"),
                    "source": "Fallback"
                })
            except:
                continue
        return results
    except Exception as e:
        print(f"⚠️ Fallback HTML error for {url}: {e}")
        return []

# ---------------- NFZ Centrala ----------------
def parse_nfz_centrala_articles():
    print("▶ Pobieranie: NFZ Centrala")
    BASE_URL = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-centrali/"
    DAYS_BACK = 9
    driver = create_driver()
    all_articles = []
    try:
        for page_num in range(1, 4):
            url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
            driver.get(url)
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "news"))
            )
            time.sleep(2)
            articles = driver.find_elements(By.CLASS_NAME, "news")
            for article in articles:
                try:
                    date_text = article.find_element(By.CLASS_NAME, "date").text.strip()
                    article_date = datetime.strptime(date_text, "%d.%m.%Y")
                    if article_date < datetime.now() - timedelta(days=DAYS_BACK):
                        continue
                    a_tag = article.find_element(By.CSS_SELECTOR, ".title a")
                    title = a_tag.text.strip() or f"Aktualizacja NFZ Centrala {date_text}"
                    href = a_tag.get_attribute("href")
                    all_articles.append({
                        "date": article_date.strftime("%Y-%m-%d"),
                        "title": title,
                        "url": href,
                        "source": "NFZ Centrala"
                    })
                except:
                    continue
    except Exception as e:
        print("❌ Błąd w NFZ Centrala:", e)
        traceback.print_exc()
    finally:
        driver.quit()
    print(f"✅ NFZ Centrala: {len(all_articles)} artykułów")
    return all_articles

# ---------------- NFZ Oddziały ----------------
def parse_nfz_oddzialy_articles():
    print("▶ Pobieranie: NFZ Oddziały")
    url = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-oddzialow/"
    driver = create_driver()
    articles = []
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.padding-left-40"))
        )
        time.sleep(2)
        boxes = driver.find_elements(By.CSS_SELECTOR, "div.padding-left-40")
        for box in boxes:
            try:
                title_el = box.find_element(By.CSS_SELECTOR, "h3.title a")
                title = title_el.text.strip() or "Aktualizacja NFZ Oddziały"
                href = title_el.get_attribute("href")
                date_str = box.find_element(By.CSS_SELECTOR, "div.date").text.strip()
                date_obj = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                articles.append({
                    "title": title,
                    "url": href,
                    "date": date_obj,
                    "source": "NFZ Oddziały"
                })
            except:
                continue
    except Exception as e:
        print("❌ Błąd w NFZ Oddziały:", e)
        traceback.print_exc()
    finally:
        driver.quit()
    print(f"✅ NFZ Oddziały: {len(articles)} artykułów")
    return articles

# ---------------- gov.pl ----------------
def get_recent_gov_mz_articles():
    print("▶ Pobieranie: gov.pl")
    url = "https://www.gov.pl/web/zdrowie/wiadomosci"
    driver = create_driver()
    articles = []
    cutoff_date = datetime.today() - timedelta(days=9)
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "ul > li"))
        )
        time.sleep(2)
        li_elements = driver.find_elements(By.CSS_SELECTOR, "ul > li")
        for li in li_elements:
            try:
                link_el = li.find_element(By.CSS_SELECTOR, "a")
                url_suffix = link_el.get_attribute("href")
                title = li.find_element(By.CLASS_NAME, "title").text.strip() or "Aktualizacja MZ"
                intro = li.find_element(By.CLASS_NAME, "intro").text.strip()
                date_str = li.find_element(By.CLASS_NAME, "date").text.strip()
                pub_date = datetime.strptime(date_str.strip(), "%d.%m.%Y")
                if pub_date >= cutoff_date:
                    full_url = url_suffix if url_suffix.startswith("http") else "https://www.gov.pl" + url_suffix
                    articles.append({
                        "title": title,
                        "lead": intro,
                        "url": full_url,
                        "date": pub_date.strftime("%Y-%m-%d"),
                        "source": "gov.pl"
                    })
            except:
                continue
    except Exception as e:
        print("❌ Błąd w gov.pl:", e)
        traceback.print_exc()
    finally:
        driver.quit()
    print(f"✅ gov.pl: {len(articles)} artykułów")
    return articles

# ---------------- SerwisZOZ z fallback ----------------
def parse_serwiszoz_articles():
    print("▶ Pobieranie: SerwisZOZ")
    url = "https://serwiszoz.pl/aktualnosci-prawne-86"
    driver = create_driver()
    articles = []
    try:
        driver.get(url)
        WebDriverWait(driver, 40).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.item"))
        )
        time.sleep(2)
        # scroll + retry
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        elements = driver.find_elements(By.CSS_SELECTOR, "div.item")
        if not elements:
            driver.refresh()
            time.sleep(3)
            elements = driver.find_elements(By.CSS_SELECTOR, "div.item")

        for element in elements:
            try:
                title_elem = element.find_element(By.CSS_SELECTOR, "div.item-title h2 a")
                title = title_elem.text.strip() or "Aktualizacja SerwisZOZ"
                link = title_elem.get_attribute("href")
                try:
                    lead_elem = element.find_element(By.CSS_SELECTOR, "div.lead strong")
                    lead = lead_elem.text.strip()
                except:
                    lead = title
                articles.append({
                    "title": title,
                    "url": link,
                    "lead": lead,
                    "date": datetime.today().strftime("%Y-%m-%d"),
                    "source": "SerwisZOZ"
                })
            except:
                continue

        if not articles:
            print("⚠️ Selenium nie pobrał artykułów, używam fallback BeautifulSoup...")
            articles = fetch_static_html(url, "div.item", "div.item-title h2 a", "div.lead strong")

    except Exception as e:
        print("❌ Błąd w SerwisZOZ:", e)
        traceback.print_exc()
    finally:
        driver.quit()
    print(f"✅ SerwisZOZ: {len(articles)} artykułów")
    return articles

# ---------------- Rynek Zdrowia ----------------
def parse_rynekzdrowia_articles():
    print("▶ Pobieranie: Rynek Zdrowia")
    url = "https://www.rynekzdrowia.pl/Aktualnosci/"
    driver = create_driver()
    articles = []
    try:
        driver.get(url)
        WebDriverWait(driver, 40).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.box-4, ul.list-2 li, ul.list-4 li"))
        )
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        items = driver.find_elements(By.CSS_SELECTOR, "div.box-4, ul.list-2 li, ul.list-4 li")
        for item in items:
            try:
                link_el = item.find_element(By.TAG_NAME, "a")
                url_link = link_el.get_attribute("href")

                try:
                    title_el = item.find_element(By.CSS_SELECTOR, "div.desc h3, div.desc h2")
                    title = title_el.text.strip()
                except:
                    title = link_el.get_attribute("title") or \
                            (item.find_element(By.CSS_SELECTOR, "img").get_attribute("alt") if item.find_elements(By.CSS_SELECTOR, "img") else "") or \
                            "Aktualizacja Rynek Zdrowia"

                articles.append({
                    "title": title,
                    "url": url_link,
                    "lead": title,
                    "date": datetime.today().strftime("%Y-%m-%d"),
                    "source": "Rynek Zdrowia"
                })
            except:
                continue

        if not articles:
            print("⚠️ Selenium nie pobrał artykułów Rynek Zdrowia, fallback HTML...")
            articles = fetch_static_html(url, "div.box-4, ul.list-2 li, ul.list-4 li", "div.desc h3, div.desc h2", None)

    except Exception as e:
        print("❌ Błąd w Rynek Zdrowia:", e)
        traceback.print_exc()
    finally:
        driver.quit()
    print(f"✅ Rynek Zdrowia: {len(articles)} artykułów")
    return articles

# ---------------- Uruchomienie i zapis ----------------
def run_all_parsers():
    print("\n🛠️ Uruchamianie wszystkich parserów...")
    all_articles = []
    try:
        all_articles += parse_nfz_centrala_articles()
        all_articles += parse_nfz_oddzialy_articles()
        all_articles += get_recent_gov_mz_articles()
        all_articles += parse_serwiszoz_articles()
        all_articles += parse_rynekzdrowia_articles()
    except Exception as e:
        print("❌ Parser zgłosił wyjątek główny:", e)
        traceback.print_exc()
        raise

    # Deduplikacja po (title, url)
    seen = set()
    deduplicated = []
    for article in all_articles:
        key = (article.get("title", "").strip(), article.get("url", "").strip())
        if key not in seen:
            seen.add(key)
            deduplicated.append(article)

    output_path = Path("all_articles_combined.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(deduplicated, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Zapisano {len(deduplicated)} unikalnych artykułów do all_articles_combined.json")

if __name__ == "__main__":
    run_all_parsers()
