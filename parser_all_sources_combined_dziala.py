"""
Parser aktualności medycznych — GenesManager.
Strategia: requests/BS4 jako primary, jeden wspólny Selenium driver (lazy) jako fallback.
Jeden Chrome na całe uruchomienie — uruchamiany tylko gdy BS4 zawiedzie.
"""

import json
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import os

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DAYS_BACK = 9
CUTOFF = datetime.today() - timedelta(days=DAYS_BACK)


# ──────────────────────────────────────────────────────────
# HTTP session z retry
# ──────────────────────────────────────────────────────────
def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "DNT": "1",
        "Connection": "keep-alive",
    })
    return s


# ──────────────────────────────────────────────────────────
# Shared lazy Selenium — jeden Chrome na całe uruchomienie
# ──────────────────────────────────────────────────────────
_shared_driver = None


def _get_driver():
    global _shared_driver
    if _shared_driver is not None:
        return _shared_driver

    cache = Path.home() / ".cache" / "selenium"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SE_DOWNLOAD_DIR", str(cache))

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.page_load_strategy = "eager"

    for attempt in range(1, 3):
        try:
            _shared_driver = webdriver.Chrome(options=opts)
            print("🟢 Chrome uruchomiony (shared driver)")
            return _shared_driver
        except Exception as e:
            print(f"⚠️ Chrome attempt {attempt}: {e}")
            time.sleep(3)
    raise RuntimeError("Nie udało się uruchomić Chrome")


def _quit_driver():
    global _shared_driver
    if _shared_driver is not None:
        try:
            _shared_driver.quit()
        except Exception:
            pass
        _shared_driver = None
        print("🔴 Chrome zakończony")


# ──────────────────────────────────────────────────────────
# Parsowanie dat
# ──────────────────────────────────────────────────────────
_DATE_FMTS = ["%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]


def _parse_date_str(text: str) -> str | None:
    t = (text or "").strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # d.m.Y lub Y-m-d w środku tekstu
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", t)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}.{m.group(2)}.{m.group(3)}", "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return None


def _date_from_el(el) -> str | None:
    if el is None:
        return None
    # atrybut datetime (<time datetime="...">)
    dt = el.get("datetime", "")
    if dt:
        d = _parse_date_str(dt.split("T")[0])
        if d:
            return d
    return _parse_date_str(el.get_text(strip=True))


def _is_recent(date_str: str | None) -> bool:
    if not date_str:
        return True   # brak daty → traktuj jako aktualne
    try:
        return datetime.strptime(date_str, "%Y-%m-%d") >= CUTOFF
    except ValueError:
        return True


# ──────────────────────────────────────────────────────────
# Szybki fetch przez requests
# ──────────────────────────────────────────────────────────
def _fetch(url: str, timeout: int = 20) -> BeautifulSoup | None:
    try:
        r = _session().get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 3000:
            return BeautifulSoup(r.text, "html.parser")
        print(f"  requests: status {r.status_code} lub pusty")
    except Exception as e:
        print(f"  requests błąd: {e}")
    return None


def _soup_from_selenium(url: str, wait_css: str, wait_sec: int = 20) -> BeautifulSoup | None:
    driver = _get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, wait_sec).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
        )
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
        time.sleep(0.8)
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"  Selenium błąd ({url}): {e}")
        return None


# ──────────────────────────────────────────────────────────
# NFZ Centrala
# ──────────────────────────────────────────────────────────
def _extract_nfz_centrala(soup: BeautifulSoup) -> list[dict]:
    items = soup.select("div.news, li.news, article.news")
    out = []
    for art in items:
        try:
            date_el = art.select_one(".date, span.date, time")
            date_str = _date_from_el(date_el)
            if not _is_recent(date_str):
                continue
            a = art.select_one(".title a, h3 a, h2 a, a")
            if not a:
                continue
            title = a.get_text(strip=True) or "Aktualizacja NFZ Centrala"
            href = (a.get("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.nfz.gov.pl" + href
            out.append({"date": date_str or datetime.today().strftime("%Y-%m-%d"),
                        "title": title, "url": href, "source": "NFZ Centrala"})
        except Exception:
            continue
    return out


def parse_nfz_centrala_articles() -> list[dict]:
    print("▶ NFZ Centrala")
    base = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-centrali/"
    all_art: list[dict] = []

    # BS4 primary
    for page in range(1, 4):
        url = base if page == 1 else f"{base}?page={page}"
        soup = _fetch(url)
        if not soup:
            break
        found = _extract_nfz_centrala(soup)
        all_art.extend(found)
        if found and not _is_recent(found[-1].get("date")):
            break

    if all_art:
        print(f"✅ NFZ Centrala (BS4): {len(all_art)}")
        return all_art

    # Selenium fallback
    print("  → Selenium fallback")
    for page in range(1, 4):
        url = base if page == 1 else f"{base}?page={page}"
        soup = _soup_from_selenium(url, "div.news, li.news")
        if not soup:
            break
        found = _extract_nfz_centrala(soup)
        all_art.extend(found)
        if found and not _is_recent(found[-1].get("date")):
            break

    print(f"✅ NFZ Centrala (Selenium): {len(all_art)}")
    return all_art


# ──────────────────────────────────────────────────────────
# NFZ Oddziały
# ──────────────────────────────────────────────────────────
def _extract_nfz_oddzialy(soup: BeautifulSoup) -> list[dict]:
    boxes = soup.select("div.padding-left-40")
    if not boxes:
        boxes = soup.select("div.news-item, li.news")
    out = []
    for box in boxes:
        try:
            a = box.select_one("h3.title a, h2.title a, .title a, h3 a, a")
            if not a:
                continue
            title = a.get_text(strip=True) or "Aktualizacja NFZ Oddziały"
            href = (a.get("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.nfz.gov.pl" + href
            date_el = box.select_one("div.date, span.date, time")
            date_str = _date_from_el(date_el)
            out.append({"title": title, "url": href,
                        "date": date_str or datetime.today().strftime("%Y-%m-%d"),
                        "source": "NFZ Oddziały"})
        except Exception:
            continue
    return out


def parse_nfz_oddzialy_articles() -> list[dict]:
    print("▶ NFZ Oddziały")
    url = "https://www.nfz.gov.pl/aktualnosci/aktualnosci-oddzialow/"

    soup = _fetch(url)
    if soup:
        found = _extract_nfz_oddzialy(soup)
        if found:
            print(f"✅ NFZ Oddziały (BS4): {len(found)}")
            return found
        print("  BS4: brak elementów → Selenium")

    soup = _soup_from_selenium(url, "div.padding-left-40, div.news-item")
    found = _extract_nfz_oddzialy(soup) if soup else []
    print(f"✅ NFZ Oddziały (Selenium): {len(found)}")
    return found


# ──────────────────────────────────────────────────────────
# gov.pl / MZ (Ministerstwo Zdrowia)
# ──────────────────────────────────────────────────────────
def _extract_govpl(soup: BeautifulSoup) -> list[dict]:
    out = []
    # gov.pl lista wiadomości — próbujemy kilka selektorów
    for li in soup.select("ul.gov-article-list li, ul li, article"):
        try:
            a = li.select_one("a[href]")
            if not a:
                continue
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = "https://www.gov.pl" + href

            title_el = li.select_one(".title, h3, h2, h4")
            title = (title_el.get_text(strip=True) if title_el
                     else a.get_text(strip=True)) or "Aktualizacja MZ"
            if not title or title == href:
                continue

            intro_el = li.select_one(".intro, .description, .lead, p")
            intro = intro_el.get_text(" ", strip=True) if intro_el else ""

            date_el = li.select_one(".date, time, span.date, .timestamp")
            date_str = _date_from_el(date_el)
            if date_str and not _is_recent(date_str):
                continue

            out.append({"title": title, "lead": intro, "url": href,
                        "date": date_str or datetime.today().strftime("%Y-%m-%d"),
                        "source": "gov.pl"})
        except Exception:
            continue
    return out


def get_recent_gov_mz_articles() -> list[dict]:
    print("▶ gov.pl / MZ")
    url = "https://www.gov.pl/web/zdrowie/wiadomosci"

    soup = _fetch(url)
    if soup:
        found = _extract_govpl(soup)
        if found:
            print(f"✅ gov.pl (BS4): {len(found)}")
            return found
        print("  BS4: brak elementów → Selenium")

    soup = _soup_from_selenium(url, "ul > li, article", wait_sec=25)
    found = _extract_govpl(soup) if soup else []
    print(f"✅ gov.pl (Selenium): {len(found)}")
    return found


# ──────────────────────────────────────────────────────────
# SerwisZOZ
# ──────────────────────────────────────────────────────────
def _abs_serwiszoz(href: str) -> str:
    h = (href or "").strip()
    if not h or h.startswith("#"):
        return ""
    if h.startswith("//"):
        return "https:" + h
    if h.startswith("/"):
        return "https://serwiszoz.pl" + h
    return h


def _serwiszoz_date(el) -> str | None:
    """Próbuje wyciągnąć datę z elementu listy SerwisZOZ."""
    for sel in ["time", ".date", "span.date", "div.date", ".entry-date",
                ".pub-date", ".article-date", ".news-date"]:
        d = el.select_one(sel) if hasattr(el, "select_one") else None
        if d:
            parsed = _date_from_el(d)
            if parsed:
                return parsed
    # szukaj wzorca daty w samym tekście elementu (dd.mm.yyyy)
    txt = el.get_text(" ", strip=True) if hasattr(el, "get_text") else ""
    return _parse_date_str(txt) if txt else None


def _extract_serwiszoz(soup: BeautifulSoup) -> list[dict]:
    containers = (soup.select("#yw0 .items article, #yw0 article")
                  or soup.select(".list-view .items article, .items article, article")
                  or soup.select("div.item, .blog-item"))
    seen: set[str] = set()
    out = []
    for it in containers:
        try:
            a = it.select_one("h1 a, h2 a, h3 a, h4 a, .item-title a, .title a, a[href]")
            if not a:
                continue
            href = _abs_serwiszoz(a.get("href", ""))
            if not href or href in seen:
                continue
            seen.add(href)

            title = ""
            for sel in ["h2", "h3", "h4", ".item-title", ".title"]:
                el = it.select_one(sel)
                if el and el.get_text(strip=True):
                    title = el.get_text(strip=True)
                    break
            title = title or a.get_text(strip=True) or "Aktualizacja SerwisZOZ"

            lead_el = it.select_one(".lead, .excerpt, p")
            lead = lead_el.get_text(" ", strip=True) if lead_el else title

            date_str = _serwiszoz_date(it) or datetime.today().strftime("%Y-%m-%d")

            out.append({"title": title, "url": href, "lead": lead,
                        "date": date_str, "source": "SerwisZOZ"})
        except Exception:
            continue
    return out


def _dismiss_cookies(driver):
    for xp in [
        "//button[contains(., 'Akceptuj wszystkie')]",
        "//button[@id='cookiescript_accept']",
        "//button[contains(., 'akceptuj')]",
        "//button[@id='onetrust-accept-btn-handler']",
    ]:
        try:
            driver.find_element(By.XPATH, xp).click()
            time.sleep(0.8)
            return
        except Exception:
            pass


def parse_serwiszoz_articles() -> list[dict]:
    print("▶ SerwisZOZ")
    url = "https://serwiszoz.pl/aktualnosci-prawne-86"

    soup = _fetch(url)
    if soup:
        found = _extract_serwiszoz(soup)
        if found:
            print(f"✅ SerwisZOZ (BS4): {len(found)}")
            return found
        print("  BS4: brak elementów → Selenium")

    driver = _get_driver()
    try:
        driver.get(url)
        time.sleep(1.2)
        _dismiss_cookies(driver)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#yw0, .list-view, .items, article, div.item"))
        )
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
        time.sleep(0.8)
        found = _extract_serwiszoz(BeautifulSoup(driver.page_source, "html.parser"))
    except Exception as e:
        print(f"❌ SerwisZOZ Selenium: {e}")
        found = []

    print(f"✅ SerwisZOZ (Selenium): {len(found)}")
    return found


# ──────────────────────────────────────────────────────────
# Rynek Zdrowia
# ──────────────────────────────────────────────────────────
def _extract_rynekzdrowia(soup: BeautifulSoup) -> list[dict]:
    items = (soup.select("div.box-4, ul.list-2 li, ul.list-4 li")
             or soup.select("article.article-item, li.article, .article"))
    seen: set[str] = set()
    out = []
    for item in items:
        try:
            a = item.select_one("a[href]")
            if not a:
                continue
            href = (a.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)

            title_el = item.select_one("div.desc h3, div.desc h2, h3, h2, .title")
            title = (title_el.get_text(strip=True) if title_el else "")
            if not title:
                title = (a.get("title") or a.get_text(strip=True)
                         or "Aktualizacja Rynek Zdrowia")

            # data — próba kilku selektorów typowych dla tego portalu
            date_str = None
            for sel in ["time", ".date", "span.date", "div.date",
                        ".pub-date", ".entry-date", "span.time", ".news-date"]:
                d_el = item.select_one(sel)
                if d_el:
                    date_str = _date_from_el(d_el)
                    if date_str:
                        break
            date_str = date_str or datetime.today().strftime("%Y-%m-%d")

            out.append({"title": title, "url": href, "lead": title,
                        "date": date_str, "source": "Rynek Zdrowia"})
        except Exception as e:
            print(f"  ⚠️ Rynek Zdrowia element: {e}")
            continue
    return out


def parse_rynekzdrowia_articles() -> list[dict]:
    print("▶ Rynek Zdrowia")
    url = "https://www.rynekzdrowia.pl/Aktualnosci/"

    soup = _fetch(url)
    if soup:
        found = _extract_rynekzdrowia(soup)
        if found:
            print(f"✅ Rynek Zdrowia (BS4): {len(found)}")
            return found
        print("  BS4: brak elementów → Selenium")

    soup = _soup_from_selenium(url, "div.box-4, ul.list-2 li, ul.list-4 li, article")
    found = _extract_rynekzdrowia(soup) if soup else []
    print(f"✅ Rynek Zdrowia (Selenium): {len(found)}")
    return found


# ──────────────────────────────────────────────────────────
# Główny runner
# ──────────────────────────────────────────────────────────
def run_all_parsers():
    print("\n🛠️ Uruchamianie parserów...")
    all_articles: list[dict] = []

    for fn in [
        parse_nfz_centrala_articles,
        parse_nfz_oddzialy_articles,
        get_recent_gov_mz_articles,
        parse_serwiszoz_articles,
        parse_rynekzdrowia_articles,
    ]:
        try:
            all_articles.extend(fn())
        except Exception as e:
            print(f"❌ {fn.__name__}: {e}")
            traceback.print_exc()

    _quit_driver()  # Chrome zamykany raz na końcu

    # deduplikacja po (title, url)
    seen: set[tuple] = set()
    unique = []
    for a in all_articles:
        key = (a.get("title", "").strip(), a.get("url", "").strip())
        if key not in seen:
            seen.add(key)
            unique.append(a)

    out = Path("all_articles_combined.json")
    out.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Zapisano {len(unique)} artykułów → {out}")


if __name__ == "__main__":
    run_all_parsers()
