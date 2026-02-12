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

# Model do obrazów
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
    if client is None:
        raise RuntimeError("Brak klienta OpenAI")

    prompt = (
        f"Realistyczne zdjęcie stockowe: {image_description}. "
        "Naturalne światło, dokumentalny/biurowy klimat, brak napisów w kadrze, brak logotypów, brak osób publicznych. "
        "Wygląd jak prawdziwa fotografia, bez sztucznego 'AI look'."
    )

    resp = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=IMAGE_SIZE
    )

    b64 = None
    try:
        if hasattr(resp, "data") and resp.data:
            first = resp.data[0]
            if hasattr(first, "b64_json") and first.b64_json:
                b64 = first.b64_json
            elif isinstance(first, dict) and first.get("b64_json"):
                b64 = first["b64_json"]
    except Exception as e:
        print(f"⚠️ Images API: błąd odczytu danych obrazu: {e}", flush=True)
        b64 = None

    if not b64:
        print("⚠️ Images API: brak b64_json w odpowiedzi (model/uprawnienia/SDK).", flush=True)
        return False

    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_bytes(base64.b64decode(b64))
    return True

# ─────────────────────────────────────────────
# ✅ H1 GENERATOR (redakcyjny, kontrolowany)
# ─────────────────────────────────────────────
def _h1_prompt(source_title: str, lead: str, url: str) -> str:
    lead_part = f"\nLead (jeśli jest): {lead}\n" if lead else "\n"
    return f"""
Na podstawie tematu (tytuł źródła):
„{source_title}”
{lead_part}
Wygeneruj profesjonalny, redakcyjny nagłówek artykułu dla właścicieli i managerów placówek medycznych.

Wymagania:
- maks. 140 znaków
- nie kopiuj tytułu źródła (ma być parafraza/inna konstrukcja)
- bez dat
- bez cudzysłowów
- bez wykrzykników
- nie zaczynaj od "Komunikat" ani "Informacja"
- jeśli dotyczy kontraktowania/konkursów NFZ lub rozliczeń, użyj wprost "NFZ" w nagłówku

Zwróć WYŁĄCZNIE sam tekst nagłówka (bez HTML).
""".strip()

def _generate_h1(source_title: str, lead: str, url: str) -> str:
    txt = _call_openai(
        [
            {"role": "system", "content": "Jesteś redaktorem medycznym. Tworzysz zwięzłe, trafne nagłówki."},
            {"role": "user", "content": _h1_prompt(source_title, lead, url)}
        ],
        use_primary=False
    )
    txt = _clean(txt)
    txt = re.sub(r"[\"“”]", "", txt).strip()
    # awaryjnie, jeśli model zwróci HTML lub puste
    txt = re.sub(r"<[^>]+>", "", txt).strip()
    if not txt:
        txt = source_title.strip() or "Aktualność GenesManager"
    return txt

# ─────────────────────────────────────────────
# PROMPTY
# ─────────────────────────────────────────────
def _research_prompt(title: str, url: str) -> str:
    return f"""
Jesteś analitykiem systemu ochrony zdrowia i redaktorem medycznym GenesManager.pl.

Cel: przygotuj NOTATKI ANALITYCZNE (nie do publikacji) do artykułu na temat:
„{title}”.

Zasada nadrzędna: TRZYMAJ SIĘ WYŁĄCZNIE TEGO TEMATU.
- Nie opisuj innych zmian w ochronie zdrowia, nawet jeśli są „podobne”.
- Jeśli trafisz na wątek poboczny, uwzględnij go tylko wtedy, gdy ma bezpośredni wpływ na temat (1–2 zdania max).

Priorytety analizy (od najważniejszego):
1) Wpływ na NFZ: kontraktowanie, ogłoszenia konkursowe, warunki realizacji umów, sprawozdawczość, rozliczenia, ryzyka korekt/zwrotów - tylko jeśli dotyczy tego tematu.
2) Wpływ na finansowanie i dofinansowania: programy, dotacje, środki UE/KPO, MZ/Agencje, fundusze celowe – o ile dotyczą tego tematu.
3) Wpływ operacyjny: organizacja pracy, wymagania kadrowe, procedury, dokumentacja, RPWDL, RODO.
4) Wpływ prawny i compliance: ustawy/rozporządzenia/zarządzenia/komunikaty, wymagania formalne, ryzyka interpretacyjne.
Nie staraj się na siłę dopasować artykułu do powyższych tematów. Stosuj priorytet analizy w takim zakresie w jakim dotyczy to danego tmatu.

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
   - Nagłówki mają brzmieć naturalnie i redakcyjnie, a nie jak lista kontrolna.
   - NIE wolno używać w nagłówkach sformułowań z prompta (np. „konsekwencje dla NFZ”, „co monitorować”, „ryzyka…”).
   - Unikaj powtarzania tych samych nazw nagłówków w kolejnych artykułach.
   - Technika: najpierw napisz treść, a dopiero potem nazwij sekcje krótkimi tytułami <h4>.
   - Tytuł artykułu MA BYĆ INNY niż tytuł źródła.
5) Styl:
   - profesjonalna polszczyzna,
   - krótkie akapity (1–3 zdania),
   - ma być „do czytania”, a nie sama checklista.
6) Listy:
   - maksymalnie 1 lista <ul> w całym tekście,
   - maksymalnie 5 punktów.
7) Treść:
   - minimum 3500 znaków,
   - nie wymyślaj liczb i faktów; jeśli źródło nie daje detali, zaznacz to ostrożnie.
8) Wpleć naturalnie maksymalnie 2 linki (HTML) do usług GenesManager — tylko jeśli pasują:
   - https://genesmanager.pl/rozliczenia-z-nfz/
   - https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/
   - https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/
   - https://genesmanager.pl/rejestracja-podmiotu-leczniczego/
   Linki: <a href="...">tekst linku</a>

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
        source_title = (art.get("title") or f"Aktualność {idx}").strip()
        lead = (art.get("lead") or "").strip()
        url = (art.get("url") or "").strip()

        # ✅ H1 do publikacji: generujemy redakcyjny, kontrolowany
        h1_text = _generate_h1(source_title, lead, url)

        # ── ETAP 0: FOTO META (opis + ALT) ──
        img_meta_raw = _call_openai(
            [
                {"role": "system", "content": "Jesteś specjalistą od zdjęć stockowych do artykułów branżowych."},
                {"role": "user", "content": _image_prompt(h1_text)}
            ],
            use_primary=True
        )
        img_desc, img_alt = _parse_image_meta(img_meta_raw)

        # ── ETAP 0.5: GENERACJA OBRAZKA (PNG) ──
        img_name = f"{idx:03d}_{_safe_filename(h1_text, 50)}.png"
        img_path = IMAGES_DIR / img_name

        try:
            ok = _generate_image_png(img_desc, img_path)
            if not ok:
                print(f"⚠️ Nie udało się wygenerować obrazu dla: {h1_text}", flush=True)
        except Exception as e:
            print(f"⚠️ Błąd generowania obrazu dla '{h1_text}': {e}", flush=True)

        # ── ETAP 1: RESEARCH (na podstawie tytułu źródła) ──
        research = _call_openai(
            [
                {"role": "system", "content": "Jesteś analitykiem ochrony zdrowia."},
                {"role": "user", "content": _research_prompt(source_title, url)}
            ],
            use_primary=True
        )
        research = _clean(research)

        # ── ETAP 2: ARTYKUŁ ──
        html = _call_openai(
            [
                {"role": "system", "content": "Piszesz po polsku. Zwracasz wyłącznie HTML."},
                {"role": "user", "content": _article_prompt(source_title, lead, url, research)}
            ],
            use_primary=True
        )
        html = _clean(html)

        # usuń ewentualny H1 z treści jeśli model go mimo wszystko wstawi
        html = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", html, flags=re.I | re.S).strip()

        # obrazek pod H1 (pipeline wrzuci do WP Media i podmieni na URL)
        img_tag = (
            f'<img src="images/{img_name}" alt="{_escape_html(img_alt)}" loading="lazy" '
            f'style="max-width:100%;height:auto;margin:16px 0 24px 0;" />\n'
            if img_path.exists() else
            ""
        )

        # ✅ Final: H1 jest pierwszym elementem w pliku
        final_html = (
            f"<h1>{_escape_html(h1_text)}</h1>\n"
            f"{img_tag}"
            f"{html}"
        )

        # plik: krótki slug, ale H1 w środku jest pełny (pipeline bierze title z H1)
        filename = OUTPUT_DIR / f"{idx:03d}_{_safe_filename(h1_text, 60)}.txt"
        filename.write_text(final_html, encoding="utf-8")

        print(f"✅ Wygenerowano: {filename.name}", flush=True)
