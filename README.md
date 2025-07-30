# GenesManager – Automatyczny system publikacji aktualności medycznych

Ten projekt automatycznie:

1. 🔍 Parsuje aktualności z portali NFZ, MZ, GIS, itp.
2. 🧠 Wybiera 2 najważniejsze wiadomości dzięki GPT-4
3. ✍️ Generuje unikalne artykuły blogowe
4. 🌐 Publikuje je na stronie WordPress

## 📦 Zawartość repozytorium

- `genesmanager_pipeline_FINAL_TWO_ARTICLES_GPT_SELECTION_FIXED.py` – główny plik uruchamiający cały pipeline
- `parser_all_sources_combined_dziala.py` – parser źródeł NFZ/MZ itd.
- `genesmanager_generate_posts_from_json_dziala.py` – generowanie postów przez OpenAI
- `requirements.txt` – zależności do instalacji na Render
- `README.md` – ten plik 🙂

## ⚙️ Wymagane zmienne środowiskowe

Ustaw je w Render (Environment tab):

- `OPENAI_API_KEY` – klucz API z OpenAI
- `WP_URL` – adres WordPressa, np. `https://genesmanager.pl`
- `WP_USER` – login WordPressa z dostępem do API
- `WP_APP_PASSWORD` – hasło aplikacyjne WordPressa

## 🚀 Start na Render

1. Utwórz **Background Worker** na [https://dashboard.render.com](https://dashboard.render.com)
2. Start command:
   ```bash
   python genesmanager_pipeline_FINAL_TWO_ARTICLES_GPT_SELECTION_FIXED.py
