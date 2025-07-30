import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------------- NFZ Centrala i Oddziały ----------------

def parse_nfz_centrala_articles():
    BASE_URL = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-centrali/"
    DAYS_BACK = 9
    ARTICLE_CLASS = "news"
    DATE_CLASS = "date"
    TITLE_CLASS = "title"
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    all_articles = []
    try:
        for page_num in range(1, 4):
            url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
            driver.get(url)
            time.sleep(2)
            articles = driver.find_elements(By.CLASS_NAME, ARTICLE_CLASS)
            for article in articles:
                try:
                    date_div = article.find_element(By.CLASS_NAME, DATE_CLASS)
                    date_text = date_div.text.strip()
                    article_date = datetime.strptime(date_text, "%d.%m.%Y")
                    if article_date < datetime.now() - timedelta(days=DAYS_BACK):
                        continue
                    title_div = article.find_element(By.CLASS_NAME, TITLE_CLASS)
                    a_tag = title_div.find_element(By.TAG_NAME, "a")
                    href = a_tag.get_attribute("href")
                    title = a_tag.text.strip()
                    all_articles.append({
                        "date": article_date.strftime("%Y-%m-%d"),
                        "title": title,
                        "url": href,
                        "source": "NFZ Centrala"
                    })
                except:
                    continue
    finally:
        driver.quit()
    return all_articles

def parse_nfz_oddzialy_articles():
    url = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-oddzialow/"
    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    articles = []
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.padding-left-40"))
        )
        time.sleep(3)
        boxes = driver.find_elements(By.CSS_SELECTOR, "div.padding-left-40")
        for box in boxes:
            try:
                link_element = box.find_element(By.CSS_SELECTOR, "h3.title a")
                title = link_element.text.strip()
                href = link_element.get_attribute("href")
                date_element = box.find_element(By.CSS_SELECTOR, "div.date")
                date_str = date_element.text.strip()
                date_obj = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                articles.append({
                    "title": title,
                    "url": href,
                    "date": date_obj,
                    "source": "NFZ Oddziały"
                })
            except:
                continue
    finally:
        driver.quit()
    return articles

# ---------------- gov.pl ----------------

def get_recent_gov_mz_articles():
    url = "https://www.gov.pl/web/zdrowie/wiadomosci"
    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    articles = []
    cutoff_date = datetime.today() - timedelta(days=9)
    try:
        driver.get(url)
        time.sleep(2)
        li_elements = driver.find_elements(By.CSS_SELECTOR, "ul > li")
        for li in li_elements:
            try:
                link_el = li.find_element(By.CSS_SELECTOR, "a")
                url_suffix = link_el.get_attribute("href")
                title = li.find_element(By.CLASS_NAME, "title").text.strip()
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
    finally:
        driver.quit()
    return articles

# ---------------- SerwisZOZ ----------------

def parse_serwiszoz_articles():
    url = "https://serwiszoz.pl/aktualnosci-prawne-86"
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    articles = []
    try:
        driver.get(url)
        time.sleep(3)
        elements = driver.find_elements(By.CSS_SELECTOR, "div.item")
        for element in elements:
            try:
                title_elem = element.find_element(By.CSS_SELECTOR, "div.item-title h2 a")
                title = title_elem.text.strip()
                link = title_elem.get_attribute("href")
                try:
                    lead_elem = element.find_element(By.CSS_SELECTOR, "div.lead strong")
                    lead = lead_elem.text.strip()
                except:
                    lead = ""
                articles.append({
                    "title": title,
                    "url": link,
                    "lead": lead,
                    "date": datetime.today().strftime("%Y-%m-%d"),
                    "source": "SerwisZOZ"
                })
            except:
                continue
    finally:
        driver.quit()
    return articles

# ---------------- Rynek Zdrowia ----------------

def parse_rynekzdrowia_articles():
    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    base_url = "https://www.rynekzdrowia.pl/Aktualnosci/"
    articles = []
    try:
        driver.get(base_url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "ul.list-2 li"))
        )
        items = driver.find_elements(By.CSS_SELECTOR, "ul.list-2 li")
        for item in items:
            try:
                title_element = item.find_element(By.CSS_SELECTOR, "div.desc > h3")
                title = title_element.text.strip()
                url = item.find_element(By.TAG_NAME, "a").get_attribute("href")
                articles.append({
                    "title": title,
                    "url": url,
                    "source": "Rynek Zdrowia",
                    "date": datetime.today().strftime("%Y-%m-%d")
                })
            except:
                continue
    finally:
        driver.quit()
    return articles

# ---------------- Uruchomienie i zapis ----------------

def run_all_parsers():
    all_articles = []
    all_articles += parse_nfz_centrala_articles()
    all_articles += parse_nfz_oddzialy_articles()
    all_articles += get_recent_gov_mz_articles()
    all_articles += parse_serwiszoz_articles()
    all_articles += parse_rynekzdrowia_articles()

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
    print(f"✅ Zapisano {len(deduplicated)} unikalnych artykułów do all_articles_combined.json")

if __name__ == "__main__":
    run_all_parsers()