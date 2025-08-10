# GenesManager — render-ready

## Pliki
- `parser_all_sources_combined_dziala.py` — zbiera artykuły (NFZ, gov.pl, SerwisZOZ, Rynek Zdrowia), ma fallback BS4 i logi.
- `genesmanager_generate_posts_from_json_dziala.py` — generuje wpisy (bez placeholderów, pomija puste).
- `genesmanager_pipeline_FINAL_TWO_ARTICLES_GPT_SELECTION_FIXED-ostateczna_wersja_do_sprawdzenia_v4.py` — pipeline: parsing → wybór 2 artykułów → generacja → publikacja (zapisuje `selected_articles.json`).

## Wymagane zmienne środowiskowe
- `OPENAI_API_KEY`
- `WP_URL` (np. https://twojadomena.pl)
- `WP_USER` (użytkownik WordPress)
- `WP_APP_PASSWORD` (Application Password z WP)

## Uruchomienie lokalnie
```bash
pip install -r requirements.txt
python genesmanager_pipeline_FINAL_TWO_ARTICLES_GPT_SELECTION_FIXED-ostateczna_wersja_do_sprawdzenia_v4.py
```

## Uruchomienie na Render
1. Dodaj repo z tymi plikami (lub wgraj jako Private Service/Worker).
2. Ustaw zmienne środowiskowe jak wyżej.
3. **Command**:  
```
python genesmanager_pipeline_FINAL_TWO_ARTICLES_GPT_SELECTION_FIXED-ostateczna_wersja_do_sprawdzenia_v4.py
```
4. Logi pokażą:
   - liczbę zebranych artykułów,
   - wybór 2 pozycji przez AI (zapisane do `selected_articles.json`),
   - ścieżkę do wygenerowanych plików w `output_posts/`,
   - status publikacji na WordPressie.

> Uwaga: Render musi mieć dostęp do przeglądarki dla Selenium (headless Chrome). Jeśli środowisko jej nie zapewnia,
> rozważ kontener z preinstalowanym Chrome lub przełączenie trudnych źródeł na fallback BS4.
