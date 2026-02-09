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

PRIMARY_MODEL = "gpt-5"         # bez temperature
FALLBACK_MODEL = "gpt-4o-mini"  # fallback z temperature

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
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

def _escape_html(s: str) -> str:
    if s is None:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

def _strip_h1_if_model_added(html: str) -> str:
    if not html:
        return html
    return re.sub(r"(?is)^\s*<h1[^>]*>.*?</h1>\s*", "", html, count=1).strip()

def _ensure_has_h1(title: str, html: str) -> str:
    html = (html or "").strip()
    if re.search(r"(?is)^\s*<h1[^>]*>.*?</h1>", html):
        return html
    return f"<h1>{_escape_html(title)}</h1>\n{html}"

def _soft_sanitize(html: str) -> str:
    if not html:
        return html
    h = _clean_fences(html)

    # usuń ewentualne markdownowe śmieci, jeśli się wkradną
    h = re.sub(r"(?m)^\s*#{1,6}\s+", "", h)
    h = re.sub(r"\*\*(.+?)\*\*", r"\1", h)
    h = re.sub(r"\n{3,}", "\n\n", h)

    return h.strip()

# ─────────────────────────────────────────────
# PROMPT
# ─────────────────────────────────────────────
def _compose_prompt(title: str, lead: str, url: str) -> str:
    return f"""
Jesteś ekspertem ds. ochrony zdrowia i redaktorem GenesManager.pl.
Twoim zadaniem jest przygotowanie profesjonalnego, czytelnego artykułu dla właścicieli i managerów placówek medycznych.

Dane wejściowe:
- Tytuł roboczy: {title}
- Lead (jeśli jest): {lead}
- Źródło: {url}

Wymagania kluczowe:
1) Zwróć WYŁĄCZNIE czysty HTML do WordPressa.
2) Zakaz Markdown: żadnych #, ##, **, list z myślnikami, żadnych ``` .
3) Używaj tylko tagów: <h4>, <p>, <strong>, <ul>, <li>, <a>.
   - NIE używaj <h2> ani <h3>.
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

Zakończ krótką sekcją „Źródło” jako <h4>Źródło</h4> i w <p> dodaj link:
<a href="{url}">{url}</a>

Wynik: sam HTML.
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
            {"role": "system", "content": "Piszesz po polsku, profesjonalnie, językiem zrozumiałym dla managera placówki medycznej. Zwracasz wyłącznie HTML."},
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
            safe_title = _escape_html(title)
            safe_lead = _escape_html(lead)
            safe_url = _escape_html(url)
            html = (
                f"<p><strong>{safe_title}</strong></p>"
                f"<p>{safe_lead}</p>"
                f"<h4>Źródło</h4><p><a href=\"{safe_url}\">{safe_url}</a></p>"
            )

        html = _soft_sanitize(html)
        html = _strip_h1_if_model_added(html)
        html = _ensure_has_h1(title, html)

        safe = _safe_filename(title, 60)
        filename = OUTPUT_DIR / f"{idx:03d}_{safe}.txt"
        filename.write_text(html, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
