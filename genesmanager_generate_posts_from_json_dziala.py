import os
import time
import json
from pathlib import Path
from dotenv import load_dotenv
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv("bot.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

OUTPUT_DIR = Path("output_posts")
OUTPUT_DIR.mkdir(exist_ok=True)

def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        title = art.get("title", f"Aktualność {idx}")
        lead = art.get("lead", "")
        url = art.get("url", "")

        prompt = f"""
Jesteś ekspertem ds. ochrony zdrowia i redaktorem. 
Napisz artykuł na stronę dla managerów placówek medycznych.
Na podstawie informacji:
Tytuł: {title}
Lead: {lead}
Źródło: {url}

Założenia:
- Profesjonalny, ekspercki styl.
- Struktura: nagłówek H1 = tytuł, potem śródtytuły H4, akapity.
- Minimum 3000 znaków.
- Zoptymalizowany pod SEO.
"""

        content = ""
        if client:
            try:
                response = client.chat.completions.create(
                    model="gpt-5",  # użycie GPT-5
                    messages=[
                        {"role": "system", "content": "Jesteś ekspertem ds. ochrony zdrowia i redaktorem SEO."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4
                )
                content = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️ Błąd AI dla '{title}': {e}")
                continue

        if not content:
            content = f"# {title}\n\n{lead}\n\n(Brak treści – fallback)"

        filename = OUTPUT_DIR / f"{idx:03d}_{title.replace(' ','_')[:60]}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{content}")
        print(f"✅ Wygenerowano: {filename.name}")
