import os
import re
import time
import base64
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

IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)

PRIMARY_MODEL = "gpt-5"
FALLBACK_MODEL = "gpt-4o-mini"

# Model do obrazów (najczęściej działa jako gpt-image-1)
IMAGE_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"

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
# ✅ FOTO (opis + ALT + GENERACJA PNG)
# ─────────────────────────────────────────────
def _image_prompt(title: str) -> str:
    return f"""
Wymyśl realistyczne, neutralne zdjęcie stockowe pasujące do artykułu:
„{title}”.

Wymagania:
- tematyka: ochrona zdrowia, NFZ/MZ, dokumentacja medyczna, zarządzanie placówką, IT w zdrowiu
- brak logo NFZ/MZ i brak osób publicznych
- styl: naturalne światło, reportażowe, bez „AI looku”
- żadnych napisów na zdjęciu (bez banerów, bez tekstu w kadrze)

Zwróć w formacie:
OPIS: jedno zdanie opisu zdjęcia
ALT: krótki tekst ALT (SEO-friendly)
""".strip()

def _parse_image_meta(text: str) -> tuple[str, str]:
    """
    Oczekuje:
    OPIS: ...
    ALT: ...
    """
    t = _clean(text)
    opis = ""
    alt = ""
    m1 = re.search(r"(?im)^\s*OPIS\s*:\s*(.+)\s*$", t)
    m2 = re.search(r"(?im)^\s*ALT\s*:\s*(.+)\s*$", t)
    if m1:
        opis = m1.group(1).strip()
    if m2:
        alt = m2.group(1).strip()

    if not alt:
        alt = opis or "Zdjęcie ilustracyjne do artykułu GenesManager"
    if not opis:
        opis = alt

    return opis, alt

def _generate_image_png(image_description: str, out_path: Path) -> bool:
    """
    Generuje obraz (PNG) przez OpenAI Images API i zapisuje do out_path.
    Zwraca True jeśli się udało.
    """
    if client is None:
        raise RuntimeError("Brak klienta OpenAI")

    # prompt stricte do obrazu (bez meta)
    prompt = (
        f"Realistyczne zdjęcie stockowe: {image_description}. "
        "Naturalne światło, dokumentalny/biurowy klimat, brak napisów w kadrze, brak logotypów, brak osób publicznych. "
        "Wygląd jak prawdziwa fotografia, bez sztucznego 'AI look'."
    )

    # Uwaga: w zależności od wersji biblioteki, pole może być b64_json
    resp = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=IMAGE_SIZE
    )

    # Najczęściej: resp.data[0].b64_json
    b64 = None
    if hasattr(resp, "data") and resp.data:
        first = resp.data[0]
        b64 = getattr(first, "b64_json", None) or first.get("b64_json") if isinstance(first, dict) else None

    if not b64:
        return False

    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_bytes(base64.b64decode(b64))
    return True

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

Priorytety analizy (od najważniejszego):
1) Wpływ na NFZ: kontraktowanie, ogłoszenia konkursowe, warunki realizacji umów, sprawozdawczość, rozliczenia, ryzyka korekt/zwrotów.
2) Wpływ na finansowanie i dofinansowania: programy, dotacje, środki UE/KPO, MZ/Agencje, fundusze celowe – o ile dotyczą tego tematu.
3) Wpływ operacyjny: organizacja pracy, wymagania kadrowe, procedury, dokumentacja, IT (P1, e-ZLA, RPWDL, gabinety), RODO.
4) Wpływ prawny i compliance: ustawy/rozporządzenia/zarządzenia/komunikaty, wymagania formalne, ryzyka interpretacyjne.

Źródła:
- Traktuj link poniżej jako punkt startowy.
- Uzupełnij o inne wiarygodne źródła TYLKO jeśli dotyczą dokładnie tego samego zagadnienia.
- Jeśli nie znajdujesz potwierdzeń w innych źródłach: napisz „Brak wiarygodnych potwierdzeń poza źródłem startowym”.

Wynik:
- Zwróć notatki w 7 sekcjach logicznych odpowiadających: (a) fakty potwierdzone, (b) elementy niepewne/zapowiedzi, (c) konsekwencje dla placówek, (d) konsekwencje dla NFZ, (e) finansowanie/dofinansowania (jeśli dotyczy), (f) ryzyka i typowe błędy, (g) co monitorować dalej.
- UWAGA: nie nazywaj sekcji dosłownie w stylu „Co wiemy na pewno / Czego nie wiemy…”.
  Zamiast tego użyj NATURALNYCH, krótkich tytułów roboczych (1 linia), które pasują do konkretnego tematu.
- Tytuły sekcji mają się różnić pomiędzy tematami; unikaj powtarzalnych „szablonowych” nazw.

Źródło startowe:
{url}

Pisz po polsku, rzeczowo, bez lania wody. Bez cytowania długich fragmentów.
""".strip()

def _article_prompt(title: str, lead: str, url: str, research: str) -> str:
    return f"""
Jesteś redaktorem medycznym i ekspertem GenesManager.pl.

Na podstawie PONIŻSZEGO RESEARCHU przygotuj AUTORSKI artykuł
dla właścicieli i managerów placówek medycznych.

RESEARCH (do wykorzystania, nie cytowania):
{research}

Wymagania kluczowe:
1) Zwróć WYŁĄCZNIE czysty HTML do WordPressa (bez Markdown).
2) Zakaz Markdown: żadnych #, ##, **, list z myślnikami, żadnych ``` .
3) Używaj tylko tagów: <h3>, <h4>, <p>, <strong>, <ul>, <li>, <a>.
   - NIE używaj <h2>.
4) Nagłówki sekcji:
   - Sam dobierz 5–8 nagłówków <h4> adekwatnych do treści.
   - Nagłówki mają brzmieć naturalnie i redakcyjnie (jak w dobrym artykule branżowym), a nie jak lista kontrolna.
   - NIE wolno używać w nagłówkach sformułowań przeniesionych z prompta lub „formatu notatek” (np. „konsekwencje dla NFZ”, „co monitorować”, „ryzyka i typowe błędy” itp.).
   - Unikaj powtarzania tych samych nazw nagłówków w kolejnych artykułach: każde <h4> ma być możliwie unikalne dla tematu.
   - Technika: najpierw napisz całą treść w akapitach, a dopiero potem nazwij sekcje krótkimi tytułami <h4> pasującymi do już napisanego tekstu.
   - Tytuł artykułu MA BYĆ INNY niż tytuł źródła.
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

        # ── ETAP 0: FOTO META (opis + ALT) ──
        img_meta_raw = _call_openai(
            [
                {"role": "system", "content": "Jesteś specjalistą od zdjęć stockowych do artykułów branżowych."},
                {"role": "user", "content": _image_prompt(title)}
            ],
            use_primary=True
        )
        img_desc, img_alt = _parse_image_meta(img_meta_raw)

        # ── ETAP 0.5: GENERACJA OBRAZKA (PNG) ──
        img_name = f"{idx:03d}_{_safe_filename(title, 50)}.png"
        img_path = IMAGES_DIR / img_name

        try:
            ok = _generate_image_png(img_desc, img_path)
            if not ok:
                print(f"⚠️ Nie udało się wygenerować obrazu dla: {title}", flush=True)
        except Exception as e:
            print(f"⚠️ Błąd generowania obrazu dla '{title}': {e}", flush=True)

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

        # H1, a zaraz po nim obrazek (tak jak chcesz)
        # src jest lokalny: images/xxx.png -> pipeline wrzuci do WP Media i podmieni na URL
        img_tag = (
            f'<img src="images/{img_name}" alt="{_escape_html(img_alt)}" loading="lazy" '
            f'style="max-width:100%;height:auto;margin:16px 0 24px 0;" />\n'
            if img_path.exists() else
            ""
        )

        html = (
            f"<h1>{_escape_html(title)}</h1>\n"
            f"{img_tag}"
            f"{html}"
        )

        filename = OUTPUT_DIR / f"{idx:03d}_{_safe_filename(title, 60)}.txt"
        filename.write_text(html, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
