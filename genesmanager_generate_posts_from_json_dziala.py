import os
import re
import time
import json
import html
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ─────────────────────────────────────────────
# Konfiguracja
# ─────────────────────────────────────────────
load_dotenv("bot.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

OUTPUT_DIR = Path("output_posts")
OUTPUT_DIR.mkdir(exist_ok=True)

PRIMARY_MODEL = "gpt-5"         # bez temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.7,en;q=0.6",
})

# Zaufane domeny (preferowane)
PREFERRED_DOMAINS = {
    "gov.pl", "rcl.gov.pl", "isap.sejm.gov.pl", "sejm.gov.pl", "zus.pl", "nfz.gov.pl",
    "mzdrowie.gov.pl", "cez.gov.pl", "nil.org.pl", "rynekzdrowia.pl"
}

# Kotwice tematyczne – pilnują "dokładnie o tym"
TOPIC_ANCHORS = [
    "pielęgniark", "zgon", "zwolnien", "e-zla", "zus", "uprawnien", "kompetencj",
    "projekt", "rozporz", "ustaw", "ministerstw", "zdrowia"
]

def _has_anchor(text: str) -> bool:
    t = (text or "").lower()
    return any(a in t for a in TOPIC_ANCHORS)

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
        resp = client.chat.completions.create(
            model=FALLBACK_MODEL, messages=messages, temperature=0.2
        )
    return (resp.choices[0].message.content or "").strip()

# ─────────────────────────────────────────────
# Research: wyszukaj + pobierz + wytnij fragmenty
# ─────────────────────────────────────────────
def ddg_search(query: str, max_results: int = 6):
    # DuckDuckGo HTML (bez klucza)
    url = f"https://duckduckgo.com/html/?q={quote(query)}"
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a.result__a")[:max_results]:
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)
        if href and title:
            out.append({"title": title, "url": href})
    return out

def _domain(u: str) -> str:
    try:
        return urlparse(u).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def fetch_page_text(url: str, max_chars: int = 3500) -> str:
    # pobierz HTML i wyciągnij sensowny tekst (bez ściany)
    r = SESSION.get(url, timeout=25, allow_redirects=True)
    if r.status_code != 200:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")

    # usuń śmieci
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    # preferuj artykuł / main, jeśli istnieje
    main = soup.select_one("article") or soup.select_one("main") or soup.body
    if not main:
        return ""

    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # utnij
    return text[:max_chars]

def build_research_queries(title: str, url: str):
    base = title
    return [
        f"{base} Ministerstwo Zdrowia projekt",
        f"{base} rozporządzenie lub ustawa",
        f"{base} e-ZLA ZUS",
        f"site:gov.pl {base}",
        f"site:rcl.gov.pl {base}",
    ]

def research_pack(title: str, lead: str, source_url: str, max_sources: int = 4):
    queries = build_research_queries(title, source_url)

    candidates = []
    for q in queries:
        try:
            candidates.extend(ddg_search(q, max_results=5))
            time.sleep(0.4)
        except Exception:
            continue

    # dedup URL
    seen = set()
    uniq = []
    for c in candidates:
        u = c["url"]
        if u in seen:
            continue
        seen.add(u)
        uniq.append(c)

    # preferuj domeny zaufane
    uniq.sort(key=lambda x: (0 if _domain(x["url"]) in PREFERRED_DOMAINS else 1))

    pack = []
    topic_text = f"{title} {lead}".lower()

    for c in uniq:
        if len(pack) >= max_sources:
            break
        u = c["url"]
        d = _domain(u)

        try:
            txt = fetch_page_text(u)
            if not txt:
                continue

            # twardy filtr: musi mieć kotwice tematyczne
            if not _has_anchor(txt) and not _has_anchor(c["title"]):
                continue

            # miękki filtr: musi mieć co najmniej 2 wspólne słowa "tematyczne"
            hits = 0
            for a in TOPIC_ANCHORS:
                if a in txt.lower() and a in topic_text:
                    hits += 1
            if hits < 2:
                continue

            pack.append({
                "title": c["title"],
                "url": u,
                "domain": d,
                "excerpt": txt
            })
        except Exception:
            continue

    return pack

def format_research_for_prompt(pack):
    if not pack:
        return "BRAK DODATKOWYCH POTWIERDZONYCH ŹRÓDEŁ (nie udało się znaleźć pewnych materiałów)."

    blocks = []
    for i, p in enumerate(pack, 1):
        excerpt = p["excerpt"]
        blocks.append(
            f"[ŹRÓDŁO {i}] {p['title']} ({p['domain']})\n"
            f"URL: {p['url']}\n"
            f"FRAGMENT:\n{excerpt}\n"
        )
    return "\n\n".join(blocks)

# ─────────────────────────────────────────────
# Prompty
# ─────────────────────────────────────────────
def _prompt_new_title(original_title: str, lead: str, url: str) -> str:
    return f"""
Jesteś redaktorem GenesManager.pl. Wymyśl NOWY tytuł H1 po polsku (maks. 90 znaków),
który NIE będzie kopią tytułu źródłowego. Ma być profesjonalny, informacyjny, bez clickbaitu.

Tytuł źródłowy: {original_title}
Lead źródłowy: {lead}
Źródło: {url}

Zwróć wyłącznie jedną linię z tytułem (bez cudzysłowów, bez kropek na końcu).
""".strip()

def _compose_prompt(final_title: str, lead: str, url: str, research_blob: str) -> str:
    return f"""
Jesteś ekspertem ds. ochrony zdrowia i redaktorem GenesManager.pl.
Masz napisać artykuł w bardzo dobrej, profesjonalnej polszczyźnie.

WAŻNE ZASADY:
- Nie powielaj tytułu źródłowego – tytuł jest już podany.
- Artykuł źródłowy traktuj jako punkt wyjścia, ale doprecyzuj temat na podstawie RESEARCH (jeśli jest).
- Używaj pełnych zdań. Ma być więcej treści do czytania niż list wypunktowanych.
- Listy dopuszczalne, ale tylko gdy realnie porządkują treść (max 1–2 listy w całym tekście).
- Nie wymyślaj faktów. Jeśli czegoś nie da się potwierdzić w RESEARCH – opisz to ostrożnie jako “na etapie zapowiedzi / brak projektu w ISAP/RCL”.
- Nie ustawiamy sztywno tytułów sekcji. Dobierz własne, adekwatne do treści, ale zachowaj czytelną strukturę.

Dane wejściowe:
- Tytuł: {final_title}
- Lead: {lead}
- Źródło startowe: {url}

RESEARCH (używaj tylko jeśli pasuje dokładnie do tematu; jeśli nie pasuje — ignoruj w całości):
{research_blob}

WYMAGANIA FORMATU:
- Output w czystym Markdown (bez bloków ```).
- Nagłówki: H1 tylko raz na początku, potem H2 (##) i ewentualnie H3 (###).
- Minimum 4500 znaków.
- Ma się dać czytać na stronie: krótsze akapity, ale sensowne (2–5 zdań).

Na końcu dodaj sekcję:
## Źródła
- {url}
- (jeśli użyłeś RESEARCH, dopisz 1–3 linki, tylko te faktycznie wykorzystane)
""".strip()

# ─────────────────────────────────────────────
# Główna funkcja
# ─────────────────────────────────────────────
def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        src_title = (art.get("title") or f"Aktualność {idx}").strip()
        lead = (art.get("lead") or "").strip()
        url = (art.get("url") or "").strip()

        # 1) research
        pack = []
        try:
            pack = research_pack(src_title, lead, url, max_sources=4)
        except Exception:
            pack = []
        research_blob = format_research_for_prompt(pack)

        # 2) nowy tytuł (żeby nie kopiować źródła)
        new_title = ""
        try:
            title_messages = [
                {"role": "system", "content": "Jesteś redaktorem GenesManager.pl."},
                {"role": "user", "content": _prompt_new_title(src_title, lead, url)},
            ]
            new_title = _clean_fences(_call_openai(title_messages, use_primary=True)).strip()
            if not new_title or new_title.lower() == src_title.lower():
                raise RuntimeError("Tytuł niewystarczający / zbyt podobny")
        except Exception:
            # fallback: delikatna parafraza mechaniczna
            new_title = f"{src_title} – co to oznacza dla placówek medycznych"

        # 3) artykuł
        messages = [
            {"role": "system", "content": "Jesteś ekspertem ds. ochrony zdrowia i redaktorem SEO."},
            {"role": "user", "content": _compose_prompt(new_title, lead, url, research_blob)},
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
                print(f"⚠️ Błąd AI ({model_name}) dla '{new_title}': {e}")
                time.sleep(1.2)

        if not content:
            content = f"# {new_title}\n\n{lead}\n\n(Brak treści – fallback)\n\n## Źródła\n- {url}\n"

        if not content.lstrip().startswith("#"):
            content = f"# {new_title}\n\n{content}"

        safe = _safe_filename(new_title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"
        filename.write_text(content, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
