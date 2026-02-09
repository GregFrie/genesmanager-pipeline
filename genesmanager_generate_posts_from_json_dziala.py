import os
import re
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

PRIMARY_MODEL = "gpt-5"         # użyjemy bez param. temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

def _clean_fences(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
        # usuń ```lang\n ... \n```
        t = t.strip("`")
        if "\n" in t:
            t = t.split("\n", 1)[1]
    return t.strip()

def _safe_filename(s: str, maxlen: int = 80) -> str:
    # zamień spacje na _, usuń znaki niebezpieczne
    s = s.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s[:maxlen] if len(s) > maxlen else s

def _call_openai(messages, use_primary=True):
    """
    Zwraca content jako string.
    - gpt-5: bez temperature
    - fallback gpt-4o-mini: temperature=0.2
    """
    if client is None:
        raise RuntimeError("Brak klienta OpenAI (OPENAI_API_KEY lub biblioteka)")

    if use_primary:
        # GPT-5 – bez temperature (wymóg API)
        resp = client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=messages
        )
    else:
        # fallback – gpt-4o-mini z łagodną temperaturą
        resp = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=messages,
            temperature=0.2
        )
    return (resp.choices[0].message.content or "").strip()

def _compose_prompt(title: str, lead: str, url: str) -> str:
    return f"""
Jesteś ekspertem ds. ochrony zdrowia i redaktorem medycznym GenesManager.pl
Napisz artykuł na stronę dla managerów placówek medycznych.

Dane wejściowe:
- Tytuł: {title}
- Lead: {lead}
- Źródło: {url}

Wymagania:
- Styl: profesjonalny, ekspercki, merytoryczny – bez clickbaitu.
- Struktura: H1 = tytuł (jedna linia), następnie śródtytuły H4 i akapity.
- Minimum 3000 znaków (nie krócej).
- Dodaj sekcję „Dlaczego to ważne dla placówek” oraz „Co zrobić teraz (checklista)”.
- SEO: zwięzły lead (1–2 zdania), śródtytuły zawierają słowa kluczowe z tematu.
- Jeśli źródło jest ogólne, nie zmyślaj liczb – pisz ostrożnie i zaznacz brak pełnych danych.
Output w czystym Markdown (bez bloków ```).
STRUKTURA (dokładnie w tej kolejności):
# {title}

**Lead (1–2 zdania):** krótkie streszczenie.

## Najważniejsze wnioski (TL;DR)
- 4–6 punktów, zwięzłe, konkretne.

## Co się zmienia / czego dotyczy informacja
Wyjaśnij temat i kontekst (bez lania wody).

## Kogo to dotyczy w praktyce
Podziel na: POZ / AOS / Szpital / inne (jeśli pasuje).

## Ryzyka i najczęstsze błędy (jesli pasuje)
Lista + krótkie wyjaśnienia.

## Co to oznacza dla rozliczeń i dokumentacji (jesli pasuje)
Konkrety: sprawozdawczość, terminy, organizacja pracy.

## Dlaczego to ważne dla placówek
Sekcja obowiązkowa – praktyczne uzasadnienie.

## Co zrobić teraz (checklista) (jesli pasuje)
- 5–10 punktów do odhaczenia.

## Jak GenesManager może pomóc (wstaw linki kontekstowo)
W tej sekcji wstaw NATURALNIE maksymalnie 2 linki (Markdown):
- Audyty: https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/
- Rejestracja podmiotu: https://genesmanager.pl/rejestracja-podmiotu-leczniczego/
- Oferta konkursowa NFZ: https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/
- Rozliczenia z NFZ: https://genesmanager.pl/rozliczenia-z-nfz/
Zasady linkowania:
- Tylko tam, gdzie temat pasuje (np. kontrola/ryzyko -> audyt; sprawozdawczość -> rozliczenia; konkurs -> oferta; formalności -> rejestracja).
- Nie wstawiaj 2 linków do tej samej usługi.
- Nie wstawiaj linków w każdym akapicie.

## Źródło
Podaj link do źródła: {url}
"""
def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        title = art.get("title", f"Aktualność {idx}").strip()
        lead = art.get("lead", "").strip()
        url = art.get("url", "").strip()

        messages = [
            {"role": "system", "content": "Jesteś ekspertem ds. ochrony zdrowia i redaktorem SEO."},
            {"role": "user", "content": _compose_prompt(title, lead, url)}
        ]

        content = ""
        # 2 próby: 1) gpt-5, 2) fallback
        for attempt in range(2):
            try:
                use_primary = (attempt == 0)
                txt = _call_openai(messages, use_primary=use_primary)
                txt = _clean_fences(txt)
                content = txt
                break
            except Exception as e:
                model_name = PRIMARY_MODEL if attempt == 0 else FALLBACK_MODEL
                print(f"⚠️ Błąd AI ({model_name}) dla '{title}': {e}")
                time.sleep(1.2)
                continue

        if not content:
            # awaryjna treść
            content = f"# {title}\n\n{lead}\n\n(Brak treści – fallback)"

        # upewnij się, że nie wstawimy podwójnego H1
        normalized = content.lstrip()
        if not normalized.startswith("#"):
            # dołóż H1 tylko jeśli model sam nie zaczął od nagłówka
            content = f"# {title}\n\n{content}"

        # nazwa pliku
        safe = _safe_filename(title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"

        with filename.open("w", encoding="utf-8") as f:
            f.write(content)

        print(f"✅ Wygenerowano: {filename.name}")


