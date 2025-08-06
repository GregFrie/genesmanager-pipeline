import os
import json
import time
import requests
import traceback
from bs4 import BeautifulSoup
from openai import OpenAI

# Wymaga ustawionej zmiennej środowiskowej OPENAI_API_KEY
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─────────────────────────────────────────────
# 🔹 Normalizacja tytułu po polsku
# ─────────────────────────────────────────────
def format_polish_title(raw_title: str) -> str:
    raw_title = raw_title.strip()
    if raw_title.lower().startswith("tytuł:"):
        raw_title = raw_title[6:].strip()
    if not raw_title:
        return ""
    words = raw_title.split()
    if not words:
        return ""
    words[0] = words[0].capitalize()
    return " ".join(words)

# ─────────────────────────────────────────────
# 🔹 Pobieranie treści artykułu ze strony źródłowej
# ─────────────────────────────────────────────
def extract_content_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        if "gov.pl" in url:
            main = soup.find("div", class_="editor-content")
        elif "serwiszoz.pl" in url:
            main = soup.find("div", class_="blog-content")
        elif "rynekzdrowia.pl" in url:
            main = soup.find("article")
        elif "nfz.gov.pl" in url:
            main = soup.find("div", class_="main-content") or soup.find("article")
        else:
            main = soup.find("div", class_="content") \
                   or soup.find("div", class_="article-content") \
                   or soup.find("div", class_="entry-content")

        if not main:
            return ""

        paragraphs = main.find_all("p")
        return "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    except Exception as e:
        print(f"❌ Błąd pobierania treści z URL: {url} → {e}")
        traceback.print_exc()
        return ""

# ─────────────────────────────────────────────
# 🔹 Czyszczenie nazw plików
# ─────────────────────────────────────────────
def sanitize_filename(name):
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()[:60]

# ─────────────────────────────────────────────
# 🔹 Generowanie postów na podstawie listy artykułów
# ─────────────────────────────────────────────
def generate_posts(articles):
    output_dir = "output_posts"
    os.makedirs(output_dir, exist_ok=True)
    processed_urls = set()

    for i, article in enumerate(articles):
        try:
            url = article.get("url", "").strip()
            if not url or url in processed_urls:
                continue
            processed_urls.add(url)

            title = format_polish_title(article.get("title", "").strip())
            lead = article.get("lead", "").strip()
            content = extract_content_from_url(url)
            if not content and lead:
                content = lead
            if not content:
                print(f"⚠️ Artykuł {i+1}: brak treści – fallback do komunikatu zastępczego.")
                content = f"Aktualizacja z serwisu {article.get('source','nieznane źródło')} – brak szczegółowej treści na stronie źródłowej."

            prompt = (
                "Napisz ekspercki, ale przystępny artykuł blogowy na podstawie poniższego tekstu źródłowego. "
                "Artykuł ma być unikalny, inspirowany treścią, ale nie może jej kopiować. "
                "Ma być przeznaczony dla właścicieli i managerów podmiotów medycznych.\n\n"
                f"Tytuł artykułu: {title}\n\n"
                f"Treść źródłowa:\n{content}"
            )

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Jesteś doświadczonym redaktorem medycznym."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )

            final_text = response.choices[0].message.content.strip() if response.choices else "⚠️ Brak odpowiedzi od modelu"

            filename_base = sanitize_filename(title if title else "bez_tytulu")
            filename = f"{i+1:03d}_{filename_base}.txt"
            output_path = os.path.join(output_dir, filename)

            with open(output_path, "w", encoding="utf-8") as out_f:
                out_f.write(title + "\n\n" + final_text)

            print(f"✅ Wygenerowano: {filename}")
            time.sleep(1.5)

        except Exception as e:
            print(f"❌ Błąd przy generowaniu artykułu {i+1}: {e}")
            traceback.print_exc()

# Jeśli chcesz, żeby skrypt mógł być testowany samodzielnie:
if __name__ == "__main__":
    # Przykładowe dane testowe
    test_articles = [
        {"title": "Nowe wytyczne NFZ", "url": "https://www.gov.pl/web/zdrowie/wiadomosci", "lead": "NFZ opublikował nowe wytyczne", "source": "NFZ"},
    ]
    generate_posts(test_articles)
