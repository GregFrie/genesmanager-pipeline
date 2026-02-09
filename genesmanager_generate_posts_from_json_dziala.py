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

PRIMARY_MODEL = "gpt-5"         # bez param. temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

GENESMANAGER_LINKS = [
    ("Audyty dla podmiotów leczniczych", "https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/"),
    ("Rejestracja podmiotu leczniczego", "https://genesmanager.pl/rejestracja-podmiotu-leczniczego/"),
    ("Przygotowanie oferty konkursowej do NFZ", "https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/"),
    ("Rozliczenia z NFZ", "https://genesmanager.pl/rozliczenia-z-nfz/"),
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _clean_fences(text: str) -> str:
    """Usuń ```...``` jeśli model je jednak zwróci."""
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

def _strip_h1_if_model_added(html: str) -> str:
    """Jeśli model dodał <h1>...</h1>, usuń je, bo my kontrolujemy H1."""
    if not html:
        return html
    # usuń pierwszy nagłówek h1 (tylko pierwszy)
    return re.sub(r"(?is)^\s*<h1[^>]*>.*?</h1>\s*", "", html, count=1).strip()

def _ensure_has_h1(title: str, html: str) -> str:
    """Zawsze na początku ma być <h1>Title</h1>."""
    html = (html or "").strip()
    if re.search(r"(?is)^\s*<h1[^>]*>.*?</h1>", html):
        return html
    return f"<h1>{_escape_html(title)}</h1>\n{html}"

def _escape_html(s: str) -> str:
    """Minimalne escapowanie na wypadek znaków specjalnych w tytule."""
    if s is None:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

def _soft_sanitize(html: str) -> str:
    """
    Minimalne sprzątanie:
    - usuń pozostałości markdowna (#, **, ```), jeśli się pojawią
    - zamień podwójne nowe linie na jeden odstęp (HTML i tak ogarnia)
    """
    if not html:
        return html
    h = html

    # usuń fences
    h = _clean_fences(h)

    # usuń przypadkowe markdown H2/H3
    h = re.sub(r"(?m)^\s*#{1,6}\s+", "", h)

    # usuń **bold** jeśli się pojawi
    h = re.sub(r"\*\*(.+?)\*\*", r"\1", h)

    # czasem model wstawi "- " zamiast <li> — zostawiamy, ale lekko redukujemy szkody:
    # (nie próbujemy automatycznie konwertować do HTML, bo to robi prompt)
    h = re.sub(r"\n{3,}", "\n\n", h)

    return h.strip()

# ─────────────────────────────────────────────
# PROMPT
# ─────────────────────────────────────────────
def _compose_prompt(title: str, lead: str, url: str) -> str:
    # UWAGA: wymuszamy HTML + zakaz markdowna
    return f"""
Jesteś ekspertem ds. ochrony zdrowia i redaktorem GenesManager.pl.
Napisz ekspercki, bardzo czytelny artykuł dla właścicieli i managerów placówek medycznych.

Dane wejściowe:
- Tytuł: {title}
- Lead: {lead}
- Źródło: {url}

WYMAGANIA FORMATU (krytyczne):
- Zwróć WYŁĄCZNIE czysty HTML do WordPressa.
- NIE używaj Markdowna: żadnych #, ##, **, list z myślnikami.
- Używaj wyłącznie tagów: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <a>.
- Linki podawaj jako <a href="...">tekst</a>.
- Zero bloków ```.

WYMAGANIA MERYTORYCZNE:
- Styl: profesjonalny, ekspercki, merytoryczny – bez clickbaitu.
- Minimum 3000 znaków.
- Krótkie akapity (1–3 zdania), dużo „powietrza”.
- Jeśli źródło jest ogólne: nie zmyślaj liczb; pisz ostrożnie.

STRUKTURA (w tej kolejności, z zachowaniem nagłówków):
<h2>Lead</h2>
<p><strong>Lead (1–2 zdania):</strong> krótkie streszczenie tematu.</p>

<h2>Najważniejsze wnioski (TL;DR)</h2>
<ul>
  <li>4–6 krótkich punktów.</li>
</ul>

<h2>Co się zmienia / czego dotyczy informacja</h2>
<p>Kontekst i zakres.</p>

<h2>Kogo to dotyczy w praktyce</h2>
<ul>
  <li><strong>POZ:</strong> …</li>
  <li><strong>AOS:</strong> …</li>
  <li><strong>Szpital:</strong> …</li>
</ul>

<h2>Ryzyka i najczęstsze błędy</h2>
<ul>
  <li>Lista + krótkie objaśnienia.</li>
</ul>

<h2>Co to oznacza dla rozliczeń i dokumentacji</h2>
<p>Konkrety: sprawozdawczość / organizacja pracy / terminy.</p>

<h2>Dlaczego to ważne dla placówek</h2>
<p>Sekcja obowiązkowa – praktyczne uzasadnienie.</p>

<h2>Co zrobić teraz (checklista)</h2>
<ul>
  <li>8–12 punktów do odhaczenia.</li>
</ul>

<h2>Jak GenesManager może pomóc</h2>
<p>Napisz 3–6 zdań i wstaw naturalnie maksymalnie 2 linki (HTML) do usług – tylko jeśli pasują tematycznie:</p>
<ul>
  <li>Audyty: <a href="https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/">Audyty dla podmiotów leczniczych</a></li>
  <li>Rejestracja: <a href="https://genesmanager.pl/rejestracja-podmiotu-leczniczego/">Rejestracja podmiotu leczniczego</a></li>
  <li>Konkurs NFZ: <a href="https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/">Przygotowanie oferty konkursowej do NFZ</a></li>
  <li>Rozliczenia NFZ: <a href="https://genesmanager.pl/rozliczenia-z-nfz/">Rozliczenia z NFZ</a></li>
</ul>

<h2>Źródło</h2>
<p><a href="{url}">{url}</a></p>

Zwróć sam HTML (bez komentarzy).
""".strip()

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def generate_posts(articles):
    for idx, art in enumerate(articles, 1):
        title = (art.get("title") or f"Aktualność {idx}").strip()
        lead = (art.get("lead") or "").strip()
        url = (art.get("url") or "").strip()

        messages = [
            {"role": "system", "content": "Jesteś ekspertem ds. ochrony zdrowia i redaktorem SEO dla GenesManager.pl."},
            {"role": "user", "content": _compose_prompt(title, lead, url)}
        ]

        html = ""
        for attempt in range(2):
            try:
                use_primary = (attempt == 0)
                txt = _call_openai(messages, use_primary=use_primary)
                html = _clean_fences(txt)
                break
            except Exception as e:
                model_name = PRIMARY_MODEL if attempt == 0 else FALLBACK_MODEL
                print(f"⚠️ Błąd AI ({model_name}) dla '{title}': {e}", flush=True)
                time.sleep(1.2)

        if not html:
            # fallback minimalny, ale czytelny
            safe_title = _escape_html(title)
            safe_lead = _escape_html(lead)
            safe_url = _escape_html(url)
            html = (
                f"<h2>Lead</h2><p><strong>Lead:</strong> {safe_lead}</p>"
                f"<h2>Najważniejsze wnioski (TL;DR)</h2><ul><li>Brak danych z generatora – fallback.</li></ul>"
                f"<h2>Źródło</h2><p><a href=\"{safe_url}\">{safe_url}</a></p>"
            )

        html = _soft_sanitize(html)
        html = _strip_h1_if_model_added(html)
        html = _ensure_has_h1(title, html)

        safe = _safe_filename(title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"
        filename.write_text(html, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
