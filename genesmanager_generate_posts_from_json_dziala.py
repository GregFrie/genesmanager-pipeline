import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv

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

PRIMARY_MODEL = "gpt-5"
FALLBACK_MODEL = "gpt-4o-mini"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _call_openai(messages, use_primary=True) -> str:
    if client is None:
        raise RuntimeError("Brak klienta OpenAI")

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

def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return text.strip()

def _safe_filename(s: str, maxlen: int = 80) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s[:maxlen]

def _escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ─────────────────────────────────────────────
# PROMPTY
# ─────────────────────────────────────────────
def _research_prompt(title: str, url: str) -> str:
    return f"""
Jesteś analitykiem systemu ochrony zdrowia i redaktorem GenesManager.pl.

Cel: przygotuj NOTATKI ANALITYCZNE (nie do publikacji) do artykułu na temat:
„{title}”.

Zasada nadrzędna: TRZYMAJ SIĘ WYŁĄCZNIE TEGO TEMATU.
- Nie opisuj innych zmian w ochronie zdrowia, nawet jeśli są „podobne”.
- Jeśli trafisz na wątek poboczny, uwzględnij go tylko wtedy, gdy ma bezpośredni wpływ na temat (1–2 zdania max).

Źródła:
- Traktuj link poniżej jako punkt startowy.
- Uzupełnij o inne wiarygodne źródła TYLKO jeśli dotyczą dokładnie tego samego zagadnienia.
- Jeśli nie znajdujesz potwierdzeń w innych źródłach: napisz „Brak wiarygodnych potwierdzeń poza źródłem startowym”.

Wynik (format obowiązkowy):
1) Co wiemy na pewno (fakty + podstawa: dokument/instytucja/źródło)
2) Czego nie wiemy / co jest na etapie zapowiedzi
3) Konsekwencje dla placówek (POZ/AOS/szpital – tylko jeśli ma sens)
4) Konsekwencje dla NFZ (kontraktowanie/rozliczenia/sprawozdawczość)
5) Finansowanie/dofinansowania (jeśli dotyczy)
6) Ryzyka i typowe błędy (interpretacja, dokumentacja, IT, odpowiedzialność)
7) Co monitorować w kolejnych tygodniach (sygnały, dokumenty, terminy)

Źródło startowe:
{url}

Pisz po polsku, rzeczowo, bez lania wody. Bez cytowania długich fragmentów.
""".strip()


def _article_prompt(title: str, lead: str, url: str, research: str) -> str:
    return f"""
Jesteś redaktorem medycznym i eksperckim GenesManager.pl.

Na podstawie PONIŻSZEGO RESEARCHU przygotuj AUTORSKI artykuł
dla właścicieli i managerów placówek medycznych.

RESEARCH (do wykorzystania, nie cytowania):
{research}

Wymagania kluczowe:
0) Pierwsza linia MUSI być: <h1>...</h1>
   - to ma być NOWY tytuł (inny niż tytuł źródła i inny niż: "{title}").
1) Zwróć WYŁĄCZNIE czysty HTML do WordPressa (bez Markdown).
2) Zakaz Markdown: żadnych #, ##, **, list z myślnikami, żadnych ``` .
3) Używaj tylko tagów: <h3>, <h4>, <p>, <strong>, <ul>, <li>, <a>.
   - NIE używaj <h2>.
4) Nagłówki sekcji mają być krótkie i naturalne, ale NIE NARZUCAMY ich brzmienia:
   - sam dobierz 5–8 nagłówków <h4> adekwatnych do treści (bez schematu „TL;DR” jeśli nie pasuje).
5) Styl:
   - dobra, profesjonalna polszczyzna,
   - pełne zdania, logiczne łączenia myśli,
   - krótkie akapity (1–3 zdania),
   - ma być „do czytania”, a nie sama checklista.
6) Listy:
   - maksymalnie 1 lista <ul> w całym tekście,
   - maksymalnie 5 punktów,
   - reszta w normalnych akapitach.
7) Treść:
   - minimum 3500 znaków,
   - nie wymyślaj liczb i faktów; jeśli źródło nie daje detali, zaznacz to ostrożnie.
8) Wpleć naturalnie maksymalnie 2 linki (HTML) do usług GenesManager — tylko jeśli pasują kontekstowo:
   - https://genesmanager.pl/rozliczenia-z-nfz/
   - https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/
   - https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/
   - https://genesmanager.pl/rejestracja-podmiotu-leczniczego/
   Linki mają wyglądać tak: <a href="...">tekst linku</a>

Na końcu:
<h4>Źródło</h4>
<p><a href="{url}">{url}</a></p>

Nie opisuj procesu researchu.
Zwróć wyłącznie HTML.
""".strip()

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        title = (art.get("title") or f"Aktualność {idx}").strip()
        lead = (art.get("lead") or "").strip()
        url = (art.get("url") or "").strip()

        # ── ETAP 1: RESEARCH ──
        research = _call_openai(
            [
                {"role": "system", "content": "Jesteś analitykiem ochrony zdrowia."},
                {"role": "user", "content": _research_prompt(title, url)}
            ],
            use_primary=True
        )
        research = _clean(research)

        # ── ETAP 2: ARTYKUŁ ──
        html = _call_openai(
            [
                {"role": "system", "content": "Piszesz po polsku. Zwracasz wyłącznie HTML."},
                {"role": "user", "content": _article_prompt(title, lead, url, research)}
            ],
            use_primary=True
        )
        html = _clean(html)

        # Kontrola: upewnij się, że jest H1 na początku; jeśli nie, dodaj awaryjnie
        if not re.search(r"(?is)^\s*<h1\b[^>]*>.*?</h1>", html):
            html = f"<h1>{_escape_html(title)}</h1>\n{html}"

        filename = OUTPUT_DIR / f"{idx:03d}_{_safe_filename(title, 60)}.txt"
        filename.write_text(html, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
