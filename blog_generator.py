import os
import re
import base64
import json
from datetime import date
from pathlib import Path

import requests
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

OUTPUT_DIR = Path("output_blog")
OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)

PRIMARY_MODEL   = "gpt-5"
FALLBACK_MODEL  = "gpt-4o-mini"
IMAGE_MODEL     = "gpt-image-1"
IMAGE_SIZE      = "1024x1024"

GENESMANAGER_LINKS = [
    "https://genesmanager.pl/rozliczenia-z-nfz/",
    "https://genesmanager.pl/audyty-dla-podmiotow-leczniczych/",
    "https://genesmanager.pl/audyt-rozliczen-nfz/",
    "https://genesmanager.pl/przygotowanie-oferty-konkursowej-do-nfz/",
    "https://genesmanager.pl/rejestracja-podmiotu-leczniczego/",
]

# Wymogi recenzji merytorycznej z 13.10.2026 — opublikowane poradniki (4756–4758) są wzorem.
# Ramkę CTA model wypełnia sam (pytanie i zdanie pod temat), reszta wzoru jest stała.
CTA_TEMPLATE = """<div class="gm-cta" style="border-left:4px solid #1f6feb;background:#f3f6fa;padding:16px 20px;margin:24px 0;">
<p><strong>[PYTANIE DO CZYTELNIKA W JEGO SYTUACJI]</strong> Zadzwoń lub napisz. [CO MA PODAĆ, np. rodzaj świadczeń, datę pisma]. [CO SPRAWDZIMY]. Na tym etapie nie wysyłaj nam dokumentacji pacjentów.</p>
<p><a href="tel:+48502514023"><strong>Zadzwoń: 502 514 023</strong></a> · <a href="https://genesmanager.pl/kontakt/"><strong>[KRÓTKIE WEZWANIE, np. Umów bezpłatną konsultację]</strong></a></p>
</div>"""

EDITORIAL_RULES = f"""
RAMKA KONTAKTOWA (obowiązkowa):
- Zaraz po wstępie wstaw ramkę według wzoru poniżej. Zmień tylko fragmenty w nawiasach kwadratowych, resztę przepisz dosłownie:
{CTA_TEMPLATE}

RZETELNOŚĆ (tekst przechodzi recenzję prawną):
- Żadnych kategorycznych uogólnień bez podstawy. Gdy reguła ma wyjątki, napisz to („co do zasady”, „z wyjątkiem…”) albo wskaż, gdzie czytelnik sprawdzi szczegóły (umowa, zarządzenie Prezesa NFZ).
- Żadnych procentów, widełek i statystyk, których nie ma w researchu z podanym źródłem. Szacunki „z praktyki” pomijaj.
- Fakty oznaczone w researchu jako „niepewne” pomijaj.
- Nie pisz „pełny katalog”, „zawsze”, „nigdy”, jeżeli research tego nie potwierdza przepisem.
- Nie doradzaj pobierania opłat za świadczenia, do których pacjent ma prawo w ramach umowy z NFZ.
- Bez marketingowego pośpiechu („Nie zwlekaj”, „Działaj już dziś”). Zakończ konkretem: co czytelnik będzie wiedział lub miał po wykonaniu kroków.
- Zwracaj się do czytelnika na „ty”.
""".strip()

SOURCES_RULES = """
PODSTAWA PRAWNA (ostatni element tekstu):
- Zakończ akapitem: <p><em>Stan prawny: [akty]. Artykuł ma charakter informacyjny i nie zastępuje analizy konkretnej sprawy.</em></p>
- W miejsce [akty] wpisz tylko akty z researchu, na które powołuje się tekst, w formacie: pełna nazwa aktu (Dz.U. z RRRR r. poz. NNN), wskazane artykuły lub paragrafy.
- Nie dodawaj linków do aktów — linki do ISAP dodaje program po sprawdzeniu, że akt istnieje.
- Jeśli tekst nie powołuje się na żaden akt, napisz tylko drugie zdanie (bez „Stan prawny”).
""".strip()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _call_openai(messages, use_primary=True) -> str:
    if client is None:
        raise RuntimeError("Brak klienta OpenAI")
    models = [PRIMARY_MODEL, FALLBACK_MODEL] if use_primary else [FALLBACK_MODEL]
    last_err = None
    for model in models:
        try:
            kwargs = {"model": model, "messages": messages}
            if model == FALLBACK_MODEL:
                kwargs["temperature"] = 0.2
            resp = client.chat.completions.create(**kwargs)
            result = (resp.choices[0].message.content or "").strip()
            if result:
                return result
        except Exception as e:
            print(f"⚠️ Model {model} error: {e}")
            last_err = e
    raise RuntimeError(f"Wszystkie modele OpenAI niedostępne: {last_err}")

def _clean(text: str) -> str:
    return re.sub(r"```.*?```", "", text or "", flags=re.S).strip()

def _safe_filename(s: str, maxlen: int = 80) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s[:maxlen]

def _escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ─────────────────────────────────────────────
# RESEARCH PROMPT — evergreen, głęboki
# ─────────────────────────────────────────────
def _research_prompt(title: str, angle: str) -> str:
    return f"""
Jesteś ekspertem zarządzania placówkami medycznymi w Polsce i analitykiem systemu ochrony zdrowia.

Przygotuj SZCZEGÓŁOWE NOTATKI ANALITYCZNE (robocze, nie do publikacji) do artykułu blogowego:
„{title}"

Kąt artykułu (uwzględnij koniecznie):
{angle}

Zakres researchu — odpowiedz wyczerpująco na każdy punkt:

1. STAN FAKTYCZNY
   - Jak to działa w Polsce w 2026 roku (przepisy, procedury, instytucje)?
   - Jakie są aktualne regulacje prawne (ustawa, rozporządzenie, zarządzenie NFZ)?
   - Jakie są konkretne liczby: kwoty, terminy, progi, stawki?

2. PRAKTYKA
   - Jak wygląda to w rzeczywistości (co właściciel przychodni naprawdę robi, w jakiej kolejności)?
   - Jakie są najczęstsze problemy i przyczyny niepowodzeń?
   - Co odróżnia podmioty które sobie radzą od tych które mają problemy?

3. KONSEKWENCJE I RYZYKA
   - Co się dzieje jeśli coś pójdzie nie tak (kary, sankcje, utrata kontraktu)?
   - Jakie są typowe pułapki i jak ich uniknąć?

4. CO WŁAŚCICIEL POWINIEN ZROBIĆ
   - Konkretne kroki (z kolejnością i terminami jeśli istnieją)?
   - Które elementy warto zlecić zewnętrznie, które zrobić samodzielnie?
   - Jakie dokumenty / zaświadczenia / systemy są potrzebne?

5. AKTUALNOŚĆ
   - Co zmieniło się lub zmieni wkrótce (2025–2026) w tym obszarze?
   - Jakie planowane zmiany prawne warto śledzić?

WAŻNE:
- Podawaj tylko ZWERYFIKOWANE fakty. Jeśli nie jesteś pewien konkretnej liczby/daty — zaznacz to wyraźnie jako „niepewne" lub pomiń.
- Nie wymyślaj numerów zarządzeń NFZ ani dat ustaw których nie znasz.
- Przy każdym twierdzeniu prawnym podaj akt w formacie: nazwa aktu (Dz.U. z RRRR r. poz. NNN), artykuł lub paragraf. Bez tego twierdzenie nie trafi do artykułu.
- Liczby i odsetki „z praktyki rynkowej” bez źródła oznacz jako „niepewne”.
- Pisz po polsku, rzeczowo, bez lania wody.
""".strip()


# ─────────────────────────────────────────────
# ARTICLE PROMPT — filar (długi, szeroki)
# ─────────────────────────────────────────────
def _pillar_prompt(title: str, service_cta: str, research: str) -> str:
    cta_instruction = (
        f"Wpleć naturalnie 2–3 linki do usług GenesManager (tylko jeśli kontekstowo pasują):\n"
        f"   Priorytet: {service_cta}\n"
        f"   Pozostałe do wyboru: {', '.join(l for l in GENESMANAGER_LINKS if l != service_cta)}\n"
        f"   Format: <a href=\"URL\">tekst linku</a>"
    ) if service_cta else (
        f"Wpleć naturalnie 1–2 linki do usług GenesManager jeśli pasują kontekstowo:\n"
        f"   {', '.join(GENESMANAGER_LINKS)}\n"
        f"   Format: <a href=\"URL\">tekst linku</a>"
    )

    return f"""
Jesteś doświadczonym redaktorem i ekspertem GenesManager.pl — firmy doradczej dla właścicieli i managerów placówek medycznych w Polsce.

Napisz KOMPLEKSOWY ARTYKUŁ FILAROWY na temat:
„{title}"

Na podstawie poniższego researchu:
{research}

WYMAGANIA FORMALNE:
1) Zwróć WYŁĄCZNIE czysty HTML (bez Markdown, bez komentarzy, bez bloków kodu).
2) Dozwolone tagi: <h2>, <h3>, <p>, <strong>, <em>, <ul>, <li>, <a> oraz <div> wyłącznie w ramce kontaktowej. NIE używaj <h1> — tytuł wpisu nadaje WordPress.
3) Długość: MINIMUM 5000 znaków treści.

STRUKTURA ARTYKUŁU (zachowaj tę kolejność):
- Wstęp (<p>): 2–3 zdania które od razu mówią czytelnikowi dlaczego ten temat go dotyczy i ile może stracić/zyskać.
- Sekcje tematyczne (<h2> + akapity, w razie potrzeby podsekcje <h3>): pełne, wyczerpujące omówienie tematu.
- Sekcja końcowa <h2>Kluczowe punkty</h2>: lista <ul> max 6 punktów — najważniejsze rzeczy do zapamiętania i działania.

NAGŁÓWKI <h2>:
- LIMIT: MAKSYMALNIE 10 nagłówków <h2>. Policz je przed wysłaniem.
- Każdy opisuje KONKRETNĄ treść swojej sekcji — nie ogólne kategorie.
- Nagłówek = wyrażenie rzeczownikowe lub zdanie twierdzące, 4–10 słów.
- ZAKAZ (żadna odmiana): „Podsumowanie", „Wnioski", „Kontekst", „Tło", „Dla kogo",
  „Co dalej", „Dlaczego to ważne", „Praktyczne wskazówki", „Konsekwencje dla…",
  „monitorować", „monitoring", „Ryzyka", „Zmiany", nagłówki zaczynające się od liczebnika + czynność,
  „wsparcie zewnętrzne", „rekomendowane", „Co warto".
- Wzorzec dobrego nagłówka:
  ✓ „Termin składania wniosku upływa 30 czerwca"
  ✓ „NFZ odrzuca ofertę jeśli brakuje zaświadczenia z CEIDG"
  ✓ „Wymagana opinia sanitarna Sanepidu przed złożeniem wniosku"

STYL:
- Piszesz do właściciela lub managera przychodni — osoby która nie zna żargonu prawniczego, ale potrzebuje konkretów.
- Format odpowiedzi na potrzeby czytelnika: sytuacja → problem → konsekwencje → co zrobić → termin (jeśli wynika z przepisu).
- Profesjonalna polszczyzna, krótkie akapity (2–4 zdania).
- Nie pisz o sobie ani o GenesManager w trzeciej osobie — link wystarczy.
- Nie wymyślaj liczb, dat ani numerów aktów prawnych których nie ma w researchu.

LINKI DO GENESMANAGER:
{cta_instruction}

{EDITORIAL_RULES}

{SOURCES_RULES}

Zwróć wyłącznie HTML.
""".strip()


# ─────────────────────────────────────────────
# ARTICLE PROMPT — klaster (skupiony, krótszy)
# ─────────────────────────────────────────────
def _cluster_prompt(title: str, service_cta: str, research: str) -> str:
    cta_instruction = (
        f"Wpleć naturalnie 1–2 linki do usług GenesManager (tylko jeśli kontekstowo pasują):\n"
        f"   Priorytet: {service_cta}\n"
        f"   Pozostałe do wyboru: {', '.join(l for l in GENESMANAGER_LINKS if l != service_cta)}\n"
        f"   Format: <a href=\"URL\">tekst linku</a>"
    ) if service_cta else ""

    return f"""
Jesteś doświadczonym redaktorem i ekspertem GenesManager.pl — firmy doradczej dla właścicieli i managerów placówek medycznych w Polsce.

Napisz SKUPIONY ARTYKUŁ KLASTROWY na temat:
„{title}"

Na podstawie poniższego researchu:
{research}

WYMAGANIA FORMALNE:
1) Zwróć WYŁĄCZNIE czysty HTML (bez Markdown, bez komentarzy, bez bloków kodu).
2) Dozwolone tagi: <h2>, <h3>, <p>, <strong>, <em>, <ul>, <li>, <a> oraz <div> wyłącznie w ramce kontaktowej. NIE używaj <h1> — tytuł wpisu nadaje WordPress.
3) Długość: 2500–3500 znaków treści. Nie rozpisuj się — każde zdanie musi wnosić wartość.

STRUKTURA ARTYKUŁU:
- Wstęp (<p>): 1–2 zdania — konkretna sytuacja której dotyczy artykuł.
- Sekcje tematyczne (<h2> + akapity): skupione WYŁĄCZNIE na temacie tego artykułu.
- NIE staraj się objąć całego obszaru tematycznego — to jest rola artykułu filarowego.

NAGŁÓWKI <h2>:
- LIMIT: MAKSYMALNIE 6 nagłówków <h2>. Policz je przed wysłaniem.
- Każdy opisuje KONKRETNĄ treść swojej sekcji — nie ogólne kategorie.
- Nagłówek = wyrażenie rzeczownikowe lub zdanie twierdzące, 4–10 słów.
- ZAKAZ (żadna odmiana): „Podsumowanie", „Wnioski", „Kontekst", „Tło", „Dla kogo",
  „Co dalej", „Dlaczego to ważne", „Praktyczne wskazówki", „Konsekwencje dla…",
  „monitorować", „monitoring", „Ryzyka", „Zmiany", nagłówki zaczynające się od liczebnika + czynność,
  „wsparcie zewnętrzne", „rekomendowane", „Co warto".

STYL:
- Piszesz do właściciela lub managera przychodni.
- Format: sytuacja → problem → konsekwencje → co zrobić → termin (jeśli wynika z przepisu).
- Profesjonalna polszczyzna, krótkie akapity (2–3 zdania).
- Nie wymyślaj liczb, dat ani numerów aktów prawnych których nie ma w researchu.

LINKI DO GENESMANAGER:
{cta_instruction}

{EDITORIAL_RULES}

{SOURCES_RULES}

Zwróć wyłącznie HTML.
""".strip()


# ─────────────────────────────────────────────
# OBRAZ
# ─────────────────────────────────────────────
def _image_prompt(title: str) -> str:
    return f"""
Wymyśl realistyczne, neutralne zdjęcie stockowe pasujące do artykułu:
„{title}"

Wymagania:
- tematyka: ochrona zdrowia, zarządzanie placówką medyczną, dokumentacja, finanse, prawo medyczne
- brak logo NFZ/MZ i brak osób publicznych
- styl: naturalne światło, reportażowe, bez „AI looku"
- żadnych napisów na zdjęciu

Zwróć w formacie:
OPIS: jedno zdanie opisu zdjęcia
ALT: krótki tekst ALT (SEO-friendly, po polsku)
""".strip()

def _parse_image_meta(text: str) -> tuple[str, str]:
    t = _clean(text)
    m1 = re.search(r"(?im)^\s*OPIS\s*:\s*(.+)\s*$", t)
    m2 = re.search(r"(?im)^\s*ALT\s*:\s*(.+)\s*$", t)
    opis = m1.group(1).strip() if m1 else ""
    alt  = m2.group(1).strip() if m2 else opis or "Zdjęcie ilustracyjne"
    return opis or alt, alt

def _generate_image_png(description: str, out_path: Path) -> bool:
    if client is None:
        raise RuntimeError("Brak klienta OpenAI")
    prompt = (
        f"Realistyczne zdjęcie stockowe: {description}. "
        "Naturalne światło, brak napisów, brak logotypów, brak osób publicznych. "
        "Wygląd jak prawdziwa fotografia."
    )
    resp = client.images.generate(model=IMAGE_MODEL, prompt=prompt, size=IMAGE_SIZE)
    b64 = None
    try:
        first = resp.data[0]
        b64 = getattr(first, "b64_json", None) or (first.get("b64_json") if isinstance(first, dict) else None)
    except Exception as e:
        print(f"⚠️ Błąd odczytu obrazu: {e}")
    if not b64:
        print("⚠️ Brak b64_json w odpowiedzi Images API")
        return False
    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_bytes(base64.b64decode(b64))
    return True


# ─────────────────────────────────────────────
# PODSTAWA PRAWNA — linki do ISAP po sprawdzeniu w API Sejmu (ELI)
# ─────────────────────────────────────────────
DZU_RE = re.compile(r"Dz\.\s?U\.\s?z\s?(\d{4})\s?r\.\s?poz\.\s?(\d+)")

def _act_exists(year: str, pos: str) -> bool | None:
    """True/False wg api.sejm.gov.pl; None, gdy API nie odpowiada."""
    try:
        r = requests.get(f"https://api.sejm.gov.pl/eli/acts/DU/{year}/{int(pos)}",
                         headers={"User-Agent": "GenesManager/1.0"}, timeout=20)
    except Exception:
        return None
    if r.status_code == 404:
        return False
    return bool(r.ok and r.json().get("title"))

def _link_sources(html: str) -> str:
    """Każdy „Dz.U. z RRRR r. poz. N” → link do ISAP; akt nieznaleziony → znacznik dla recenzenta."""
    def repl(m):
        year, pos = m.group(1), m.group(2)
        ok = _act_exists(year, pos)
        if ok is False:
            return f'{m.group(0)} <strong>[SPRAWDŹ: brak takiego aktu w ISAP]</strong>'
        if ok is None:
            return f'{m.group(0)} <strong>[SPRAWDŹ: API Sejmu nie odpowiedziało]</strong>'
        return f'<a href="https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU{year}{int(pos):07d}">{m.group(0)}</a>'
    return DZU_RE.sub(repl, html)


# ─────────────────────────────────────────────
# MAIN — generuj jeden artykuł z tematu
# ─────────────────────────────────────────────
def generate_blog_post(topic: dict) -> Path:
    """
    Przyjmuje słownik tematu z topics.json.
    Zwraca ścieżkę do wygenerowanego pliku .txt z HTML.
    """
    title       = topic["title"]
    angle       = topic.get("angle", "")
    art_type    = topic.get("type", "cluster")  # "pillar" | "cluster"
    service_cta = topic.get("service_cta") or ""
    topic_id    = topic.get("id", 0)

    print(f"\n📝 [{art_type.upper()}] {title}", flush=True)

    # ── ETAP 1: OBRAZ ──
    print("  🖼️  Generuję obraz...", flush=True)
    img_meta_raw = _call_openai([
        {"role": "system", "content": "Jesteś specjalistą od zdjęć stockowych."},
        {"role": "user",   "content": _image_prompt(title)},
    ], use_primary=False)
    img_desc, img_alt = _parse_image_meta(img_meta_raw)

    img_name = f"{topic_id:03d}_{_safe_filename(title, 50)}.png"
    img_path = IMAGES_DIR / img_name
    try:
        ok = _generate_image_png(img_desc, img_path)
        if not ok:
            img_path = Path("")
    except Exception as e:
        print(f"  ⚠️ Błąd obrazu: {e}", flush=True)
        img_path = Path("")

    # ── ETAP 2: RESEARCH ──
    print("  🔍 Research...", flush=True)
    research = _call_openai([
        {"role": "system", "content": "Jesteś ekspertem zarządzania placówkami medycznymi w Polsce."},
        {"role": "user",   "content": _research_prompt(title, angle)},
    ], use_primary=True)
    research = _clean(research)

    # ── ETAP 3: ARTYKUŁ ──
    print("  ✍️  Generuję artykuł...", flush=True)
    if art_type == "pillar":
        prompt = _pillar_prompt(title, service_cta, research)
    else:
        prompt = _cluster_prompt(title, service_cta, research)

    html = _call_openai([
        {"role": "system", "content": "Piszesz po polsku. Zwracasz wyłącznie HTML."},
        {"role": "user",   "content": prompt},
    ], use_primary=True)
    html = _clean(html)
    html = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", html, flags=re.I | re.S).strip()
    html = _link_sources(html)
    # Klasy gm-meta / gm-zrodla stylizuje CSS szablonu wpisu (Elementor #473).
    stan = [m.start() for m in re.finditer(r"<p>\s*<em>\s*(Stan prawny|Artykuł ma charakter)", html)]
    if stan:
        html = html[:stan[-1]] + '<p class="gm-zrodla">' + html[stan[-1] + 3:]
    # Data szkicu — recenzent podmienia ją na datę publikacji.
    html = (f"<p class=\"gm-meta\"><em>Opracowanie: zespół GenesManager. Stan prawny i data aktualizacji: "
            f"{date.today():%d.%m.%Y}.</em></p>\n\n{html}")

    # ── SKŁADANIE PLIKU ──
    img_tag = (
        f'<img src="images/{img_name}" alt="{_escape_html(img_alt)}" '
        f'loading="lazy" style="max-width:100%;height:auto;margin:16px 0 24px 0;" />\n'
        if img_path.exists() else ""
    )

    final_html = (
        f"<h1>{_escape_html(title)}</h1>\n"
        f"{img_tag}"
        f"{html}"
    )

    out_path = OUTPUT_DIR / f"{topic_id:03d}_{_safe_filename(title, 60)}.txt"
    out_path.write_text(final_html, encoding="utf-8")
    print(f"  ✅ Zapisano: {out_path.name}", flush=True)
    return out_path


# ─────────────────────────────────────────────
# WYBÓR TEMATU Z topics.json
# ─────────────────────────────────────────────
def pick_next_topic(topics_path: Path = Path("topics.json")) -> dict | None:
    """
    Zwraca następny niepublikowany temat.
    Priorytet: pillar przed cluster, potem priority ASC.
    """
    topics = json.loads(topics_path.read_text(encoding="utf-8"))
    candidates = [t for t in topics if not t.get("published") and not t.get("failed")]
    if not candidates:
        return None
    # pillar przed cluster
    candidates.sort(key=lambda t: (0 if t.get("type") == "pillar" else 1, t.get("priority", 99)))
    return candidates[0]


def mark_published(topic_id: int, topics_path: Path = Path("topics.json")) -> None:
    from datetime import date
    topics = json.loads(topics_path.read_text(encoding="utf-8"))
    for t in topics:
        if t["id"] == topic_id:
            t["published"] = True
            t["published_date"] = date.today().isoformat()
    topics_path.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_failed(topic_id: int, topics_path: Path = Path("topics.json")) -> None:
    topics = json.loads(topics_path.read_text(encoding="utf-8"))
    for t in topics:
        if t["id"] == topic_id:
            t["failed"] = True
    topics_path.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────
# CLI — test jednego tematu
# ─────────────────────────────────────────────
if __name__ == "__main__":
    topic = pick_next_topic()
    if not topic:
        print("Brak tematów do wygenerowania.")
    else:
        print(f"Wybrany temat: [{topic['type']}] {topic['title']}")
        out = generate_blog_post(topic)
        print(f"\nGotowe: {out}")
