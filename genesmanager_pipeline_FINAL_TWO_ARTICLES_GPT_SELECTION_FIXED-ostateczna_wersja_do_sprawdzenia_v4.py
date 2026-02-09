import os
import re
import time
import json
from pathlib import Path
from dotenv import load_dotenv
from textwrap import dedent

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ─────────────────────────────────────────────
# KONFIG
# ─────────────────────────────────────────────
load_dotenv("bot.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

OUTPUT_DIR = Path("output_posts")
OUTPUT_DIR.mkdir(exist_ok=True)

PRIMARY_MODEL = "gpt-5"         # bez param. temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

# ─────────────────────────────────────────────
# Linki do usług + dopasowanie po słowach kluczowych
# ─────────────────────────────────────────────
SERVICE_LINKS = [
    {
        "name": "Audyty dla podmiotów leczniczych",
        "url": "https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/",
        "keywords": ["audyt", "kontrola", "ryzyko", "dokumentacja medyczna", "weryfikacja", "zgodność", "nieprawidłowości"],
    },
    {
        "name": "Rozliczenia z NFZ",
        "url": "https://genesmanager.pl/rozliczenia-z-nfz/",
        "keywords": ["rozliczenia", "sprawozdawczość", "raport", "świadczenia", "wycena", "finanse", "umowy", "nfz"],
    },
    {
        "name": "Przygotowanie oferty konkursowej do NFZ",
        "url": "https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/",
        "keywords": ["konkurssy", "postępowania", "oferty", "ogłoszenia", "rokowania", "kontraktowania", "świadczeniodawca"],
    },
    {
        "name": "Rejestracja podmiotu leczniczego",
        "url": "https://genesmanager.pl/rejestracja-podmiotu-leczniczego/",
        "keywords": ["rejestracja", "rpwdl", "wpis", "podmiot leczniczy", "działalność medyczna", "dokumentacja"],
    },
]

def _clean_fences(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
        # usuń ```lang\n ... \n```
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()

def _safe_filename(s: str, maxlen: int = 80) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s[:maxlen] if len(s) > maxlen else s

def _call_openai(messages, use_primary=True) -> str:
    if client is None:
        raise RuntimeError("Brak klienta OpenAI (OPENAI_API_KEY lub biblioteka)")

    if use_primary:
        resp = client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=messages
        )
    else:
        resp = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=messages,
            temperature=0.2
        )
    return (resp.choices[0].message.content or "").strip()

def _compose_prompt(title: str, lead: str, url: str) -> str:
    """
    Wymusza czytelną strukturę (H2 + listy + checklista)
    + sekcję, w której model MA wstawić max 2 linki kontekstowo.
    """
    return dedent(f"""\
    Jesteś ekspertem ds. ochrony zdrowia i redaktorem GenesManager.pl.
    Napisz ekspercki, bardzo czytelny artykuł dla właścicieli i managerów placówek medycznych.

    Dane wejściowe:
    - Tytuł: {title}
    - Lead: {lead}
    - Źródło: {url}

    Wymagania twarde:
    - Output w czystym Markdown (bez bloków ```).
    - Minimum 3000 znaków.
    - Styl: profesjonalny, merytoryczny, praktyczny (bez clickbaitu).
    - Jeśli źródło jest ogólne: nie zmyślaj liczb ani szczegółów; pisz ostrożnie i zaznacz brak danych.
    - Pisz tak, żeby tekst dało się SKANOWAĆ wzrokiem: krótkie akapity, listy, wyróżnienia.

    STRUKTURA (dokładnie w tej kolejności):

    # {title}

    **Lead (1–2 zdania):** krótkie streszczenie tematu.

    ## Najważniejsze wnioski (TL;DR)
    - 4–6 punktów (konkret).

    ## Co się zmienia / czego dotyczy informacja
    Krótko, rzeczowo: kontekst i zakres.

    ## Kogo to dotyczy w praktyce
    Jeśli pasuje: osobne podpunkty dla POZ / AOS / Szpital.

    ## Ryzyka i najczęstsze błędy
    Lista + krótkie wyjaśnienia (praktyczne).

    ## Co to oznacza dla rozliczeń i dokumentacji
    Sprawozdawczość / terminy / organizacja pracy — tylko to, co wynika z tematu.

    ## Dlaczego to ważne dla placówek
    Sekcja obowiązkowa – praktyczne uzasadnienie.

    ## Co zrobić teraz (checklista)
    - 8–12 punktów do odhaczenia.

    ## Jak GenesManager może pomóc
    Napisz 3–6 zdań i wstaw NATURALNIE maksymalnie 2 linki (Markdown) — tylko jeśli pasują do tematu:
    - Audyty: https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/
    - Rejestracja: https://genesmanager.pl/rejestracja-podmiotu-leczniczego/
    - Oferta konkursowa NFZ: https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/
    - Rozliczenia NFZ: https://genesmanager.pl/rozliczenia-z-nfz/
    Zasady:
    - nie dawaj 2 linków do tej samej usługi,
    - nie spamuj linkami w innych sekcjach.

    ## Źródło
    {url}
    """)

def inject_service_links(markdown: str, max_links: int = 2) -> str:
    """
    Deterministycznie dopilnowuje linków:
    - max 2 linki
    - bez duplikacji
    - w sekcji "Jak GenesManager może pomóc" (jeśli istnieje), inaczej doda sekcję.
    """
    if not markdown:
        return markdown

    used = set()
    for s in SERVICE_LINKS:
        if s["url"] in markdown:
            used.add(s["url"])

    if len(used) >= max_links:
        return markdown

    lower = markdown.lower()

    scored = []
    for s in SERVICE_LINKS:
        if s["url"] in used:
            continue
        score = 0
        for kw in s["keywords"]:
            if kw in lower:
                score += 1
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    picks = [s for score, s in scored if score > 0][: (max_links - len(used))]

    if not picks:
        return markdown

    bullets = []
    for s in picks:
        used.add(s["url"])
        bullets.append(f"- [{s['name']}]({s['url']}) – wsparcie w tym obszarze, porządek w dokumentacji i mniejsze ryzyko błędów.")

    block = "\n".join(bullets)

    # 1) spróbuj w sekcji "Jak GenesManager może pomóc"
    m = re.search(r"(?im)^(##\s+Jak\s+GenesManager\s+może\s+pomóc\s*)$", markdown)
    if m:
        # wstaw tuż po nagłówku
        insert_pos = m.end()
        return markdown[:insert_pos] + "\n" + block + "\n" + markdown[insert_pos:]

    # 2) jeśli jest "## Źródło" — wstaw przed nim
    src = re.search(r"(?im)^\s*##\s+Źródło\s*$", markdown)
    if src:
        pos = src.start()
        return markdown[:pos] + "\n## Jak GenesManager może pomóc\n" + block + "\n\n" + markdown[pos:]

    # 3) ostatecznie dopisz na końcu
    return markdown.rstrip() + "\n\n## Jak GenesManager może pomóc\n" + block + "\n"

def normalize_headings(markdown: str) -> str:
    """
    Dodatkowo: jeśli model użyje H4 jako głównych nagłówków, podniesiemy je na H2.
    (Nie rozwala to struktury, a poprawia czytelność.)
    """
    if not markdown:
        return markdown
    # Zamień linie zaczynające się od "#### " na "## "
    markdown = re.sub(r"(?m)^####\s+", "## ", markdown)
    return markdown

def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        title = (art.get("title") or f"Aktualność {idx}").strip()
        lead = (art.get("lead") or "").strip()
        url = (art.get("url") or "").strip()

        messages = [
            {"role": "system", "content": "Jesteś ekspertem ds. ochrony zdrowia i redaktorem SEO dla GenesManager.pl."},
            {"role": "user", "content": _compose_prompt(title, lead, url)}
        ]

        content = ""
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

        if not content:
            content = f"# {title}\n\n{lead}\n\n(Brak treści – fallback)"

        # jeśli model nie zaczął od H1, dołóż
        normalized = content.lstrip()
        if not normalized.startswith("#"):
            content = f"# {title}\n\n{content}"

        # popraw czytelność nagłówków + dopilnuj linków
        content = normalize_headings(content)
        content = inject_service_links(content, max_links=2)

        safe = _safe_filename(title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"

        with filename.open("w", encoding="utf-8") as f:
            f.write(content)

        print(f"✅ Wygenerowano: {filename.name}")
