import os
import json
import time
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
            main = soup.find("div", class_="content") or soup.find("div", class_="article-content") or soup.find("div", class_="entry-content")

        if not main:
            return ""

        paragraphs = main.find_all("p")
        return "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    except Exception as e:
        print(f"❌ Błąd pobierania treści z URL: {url} → {e}")
        return ""

def sanitize_filename(name):
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()[:60]

def normalize_title(title):
    title = title.strip()
    if title.lower().startswith("tytuł"):
        title = title.split(":", 1)[-1].strip()
    return title.capitalize()

def generate_posts(articles):
    output_dir = "output_posts"
    os.makedirs(output_dir, exist_ok=True)
    processed_urls = set()

    for i, article in enumerate(articles, 1):
        try:
            url = article.get("url", "").strip()
            if not url or url in processed_urls:
                continue
            processed_urls.add(url)

            title = normalize_title(article.get("title", "").strip())
            lead = article.get("lead", "").strip()
            content = extract_content_from_url(url)
            if not content and lead:
                content = lead
            if not content:
                print(f"⚠️ Pominięto artykuł {i} – brak treści z URL i LEAD")
                continue

            prompt = (
                "Napisz ekspercki, ale przystępny artykuł blogowy na podstawie poniższego tekstu źródłowego. "
                "Artykuł ma być unikalny, inspirowany treścią, ale nie może jej kopiować. "
                "Ma być przeznaczony dla właścicieli i managerów podmiotów medycznych.\n\n"
                f"{content}"
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
            filename = f"{i:03d}_{filename_base}.txt"
            output_path = os.path.join(output_dir, filename)

            with open(output_path, "w", encoding="utf-8") as out_f:
                out_f.write(title + "\n\n" + final_text)

            print(f"✅ Wygenerowano: {filename}")
            time.sleep(1.5)

        except Exception as e:
            print(f"❌ Błąd przy generowaniu artykułu {i}: {e}")
