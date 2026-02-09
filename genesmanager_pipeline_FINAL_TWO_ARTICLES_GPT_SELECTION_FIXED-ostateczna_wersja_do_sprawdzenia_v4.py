# 🧩 ALL-IN-ONE FINAL PIPELINE for GenesManager
# Automatyczne: parsing → wybór → generacja → publikacja

import os
import re
import time
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
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

OUTPUT_DIR = Path("output_posts")
OUTPUT_DIR.mkdir(exist_ok=True)

PRIMARY_MODEL = "gpt-5"         # bez temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

SERVICE_LINKS = [
    {
        "name": "Rozliczenia z NFZ",
        "url": "https://genesmanager.pl/rozliczenia-z-nfz/",
        "keywords": ["rozlicze", "sprawozdawczo", "raport", "świadcze", "produkt", "wycena", "umow", "nfz"],
    },
    {
        "name": "Audyty dla podmiotów leczniczych",
        "url": "https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/",
        "keywords": ["audyt", "kontrol", "ryzyk", "korekt", "weryfikac", "zgodność", "nieprawidłowo"],
    },
    {
        "name": "Przygotowanie oferty konkursowej do NFZ",
        "url": "https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/",
        "keywords": ["konkurs", "postępowan", "ofert", "ogłoszen", "rokowan", "kontraktowan"],
    },
    {
        "name": "Rejestracja podmiotu leczniczego",
        "url": "https://genesmanager.pl/rejestracja-podmiotu-leczniczego/",
        "keywords": ["rejestrac", "rpwdl", "wpis", "podmiot lecznicz", "działalno", "forma praw"],
    },
]

def _clean_fences(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
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
        resp = client.chat.completions.create(model=PRIMARY_MODEL, messages=messages)
    else:
        resp = client.chat.completions.create(model=FALLBACK_MODEL, messages=messages, temperature=0.2)
    return (resp.choices[0].message.content or "").strip()

def _compose_prompt(title: str, lead: str, url: str) -> str:
    return dedent(f"""\
    Jesteś ekspertem ds. ochrony zdrowia i redaktorem GenesManager.pl.
    Napisz ekspercki, bardzo czytelny artykuł dla właścicieli i managerów placówek medycznych.

    Dane wejściowe:
    - Tytuł: {title}
    - Lead: {lead}
    - Źródło: {url}

    Wymagania:
    - Output w czystym Markdown (bez bloków ```).
    - Minimum 3000 znaków.
    - Krótkie akapity, listy, treść „do skanowania”.
    - Bez zmyślania liczb i szczegółów, jeśli źródło jest ogólne.

    STRUKTURA (dokładnie w tej kolejności):

    # {title}

    **Lead (1–2 zdania):** krótkie streszczenie tematu.

    ## Najważniejsze wnioski (TL;DR)
    - 4–6 punktów.

    ## Co się zmienia / czego dotyczy informacja
    Kontekst i zakres.

    ## Kogo to dotyczy w praktyce
    Jeśli pasuje: POZ / AOS / Szpital (w punktach).

    ## Ryzyka i najczęstsze błędy
    Lista + krótkie objaśnienia.

    ## Co to oznacza dla rozliczeń i dokumentacji
    Konkret: sprawozdawczość / organizacja pracy / terminy.

    ## Dlaczego to ważne dla placówek
    Sekcja obowiązkowa.

    ## Co zrobić teraz (checklista)
    - 8–12 punktów.

    ## Jak GenesManager może pomóc
    3–6 zdań + wstaw naturalnie maksymalnie 2 linki (Markdown) do pasujących usług (bez spamu).

    ## Źródło
    {url}
    """)

def inject_service_links(md: str, max_links: int = 2) -> str:
    if not md:
        return md

    used = {s["url"] for s in SERVICE_LINKS if s["url"] in md}
    if len(used) >= max_links:
        return md

    lower = md.lower()
    scored = []
    for s in SERVICE_LINKS:
        if s["url"] in used:
            continue
        score = sum(1 for kw in s["keywords"] if kw in lower)
        scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)

    picks = [s for score, s in scored if score > 0][: (max_links - len(used))]
    if not picks:
        return md

    bullets = "\n".join(
        f"- [{s['name']}]({s['url']}) – wsparcie w tym obszarze, porządek w dokumentacji i mniejsze ryzyko błędów."
        for s in picks
    )

    # wstaw w sekcji, jeśli istnieje
    m = re.search(r"(?im)^\s*##\s+Jak\s+GenesManager\s+może\s+pomóc\s*$", md)
    if m:
        insert_pos = m.end()
        return md[:insert_pos] + "\n" + bullets + "\n" + md[insert_pos:]

    # albo dodaj przed Źródłem
    src = re.search(r"(?im)^\s*##\s+Źródło\s*$", md)
    if src:
        pos = src.start()
        return md[:pos] + "\n## Jak GenesManager może pomóc\n" + bullets + "\n\n" + md[pos:]

    return md.rstrip() + "\n\n## Jak GenesManager może pomóc\n" + bullets + "\n"

def normalize_headings(md: str) -> str:
    # jeśli model użyje H4 jako głównych nagłówków, podnieś je na H2
    return re.sub(r"(?m)^####\s+", "## ", md or "")

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
                content = _clean_fences(txt)
                break
            except Exception as e:
                model_name = PRIMARY_MODEL if attempt == 0 else FALLBACK_MODEL
                print(f"⚠️ Błąd AI ({model_name}) dla '{title}': {e}", flush=True)
                time.sleep(1.2)

        if not content:
            content = f"# {title}\n\n{lead}\n\n(Brak treści – fallback)"

        if not content.lstrip().startswith("#"):
            content = f"# {title}\n\n{content}"

        content = normalize_headings(content)
        content = inject_service_links(content, max_links=2)

        safe = _safe_filename(title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"
        filename.write_text(content, encoding="utf-8")
        print(f"✅ Wygenerowano: {filename.name}", flush=True)
