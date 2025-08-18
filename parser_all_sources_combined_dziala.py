import json
from datetime import datetime

# Przyjmujemy że parser zbiera dane ze źródeł i zapisuje do pliku:
OUTPUT = "all_articles_combined.json"

def run_parser():
    # Tu normalnie parsowanie NFZ, MZ, GIS, RynekZdrowia, itd.
    # Placeholder – zostawiam Twoją realną logikę.
    articles = [
        {
            "title": "Przykładowy komunikat NFZ",
            "lead": "NFZ ogłasza konkurs na świadczenia zdrowotne...",
            "url": "https://www.nfz.gov.pl/aktualnosc/1",
            "date": datetime.today().strftime("%Y-%m-%d"),
            "source": "NFZ"
        }
    ]
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"✅ Zapisano {len(articles)} artykułów do {OUTPUT}")

if __name__ == "__main__":
    run_parser()
