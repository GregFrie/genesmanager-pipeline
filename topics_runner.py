# 📚 Tryb poradników (plan SEO 2026)
# Jeden temat z topics.json → SZKIC w WordPressie, najwyżej raz na CADENCE_DAYS.
#
# Dlaczego szkic, a nie publikacja: poradniki mówią o terminach ustawowych
# i karach umownych — pomyłka kosztuje klienta pieniądze, więc każdy tekst
# przechodzi weryfikację merytoryczną przed publikacją (strategia SEO, faza 4).
#
# Stan trzymamy w WordPressie, nie w topics.json: dysk Rendera jest efemeryczny,
# więc mark_published() z blog_generator.py ginęłoby przy każdym uruchomieniu.
#   • temat zrobiony = istnieje wpis (dowolny status) o tym samym tytule
#   • rytm          = najnowszy wpis z tagiem „poradnik" ma mniej niż CADENCE_DAYS

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

from blog_generator import generate_blog_post

WP_URL = (os.getenv("WP_URL") or "").rstrip("/")
AUTH = (os.getenv("WP_USER", ""), os.getenv("WP_APP_PASSWORD", ""))
API = f"{WP_URL}/wp-json/wp/v2"
# Bez własnego User-Agent zapora hostingu oddaje 404 na zapisach REST.
HEADERS = {"User-Agent": "GenesManager/1.0 (+requests)", "Accept": "application/json"}

TOPICS_PATH = Path(__file__).parent / "topics.json"
# 2,9 a nie 3: runner startuje raz dziennie o podobnej porze, a szkic powstaje kilka minut po starcie,
# więc po trzech dniach „since” wynosi ok. 2,99 — przy progu 3 rytm wydłużyłby się do 4 dni.
CADENCE_DAYS = float(os.getenv("TOPICS_CADENCE_DAYS", "2.9"))   # ok. 2 szkice tygodniowo (od 14.10.2026)
TAG_SLUG = "poradnik"
CATEGORY_SLUG = "poradniki"

# Kolejność ze strategii SEO (Marketing/strategia-seo-2026.md, rozdz. 5):
# najpierw tematy wspierające o wysokiej intencji w kolejności usług
# (audyty → rozliczenia → konkursy → rejestracja), filary na końcu.
# 21–23 (14.10.2026): tematy, na których widoczny jest gpmed.pl — outsourcing wcześnie, bo to intencja zakupowa.
QUEUE = [14, 13, 10, 21, 4, 2, 3, 12, 22, 6, 8, 1, 5, 9, 23, 7, 11, 15, 16, 17, 18, 19, 20]


def _norm(title: str) -> str:
    t = unicodedata.normalize("NFKD", re.sub(r"<[^>]+>", "", title or "")).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _get(path: str, **params):
    r = requests.get(f"{API}{path}", auth=AUTH, headers=HEADERS, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _term_id(taxonomy: str, slug: str) -> int | None:
    found = _get(f"/{taxonomy}", slug=slug, _fields="id")
    return found[0]["id"] if found else None


def _existing_titles() -> set[str]:
    titles: set[str] = set()
    for status in ("publish", "draft", "pending", "future", "private"):
        page = 1
        while True:
            r = requests.get(f"{API}/posts", auth=AUTH, headers=HEADERS, timeout=60, params={
                "status": status, "per_page": 100, "page": page, "_fields": "title",
                "context": "edit"})
            if r.status_code != 200:
                break
            batch = r.json()
            titles |= {_norm((p.get("title") or {}).get("raw") or (p.get("title") or {}).get("rendered", ""))
                       for p in batch}
            if len(batch) < 100:
                break
            page += 1
    return titles


def _days_since_last_guide(tag_id: int) -> float | None:
    last = _get("/posts", tags=tag_id, status="publish,draft,pending,future,private",
                per_page=1, orderby="date", order="desc", _fields="date_gmt", context="edit")
    if not last:
        return None
    d = datetime.fromisoformat(last[0]["date_gmt"]).replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400


def _upload_image(path: Path, title: str) -> tuple[str | None, int | None]:
    if not path.exists():
        return None, None
    r = requests.post(f"{API}/media", auth=AUTH, timeout=120, data=path.read_bytes(), headers={
        **HEADERS, "Content-Type": "image/png",
        "Content-Disposition": f'attachment; filename="{path.name}"'})
    if r.status_code not in (200, 201):
        print(f"⚠️ Upload obrazu nieudany ({r.status_code})")
        return None, None
    j = r.json()
    return j.get("source_url"), j.get("id")


def _meta_desc(html: str, maxlen: int = 155) -> str:
    # Pierwszy akapit wstępu — pomijamy linię z datą aktualizacji (<em>) i ramkę kontaktową.
    html = re.sub(r'<div class="gm-cta".*?</div>', "", html, flags=re.S | re.I)
    m = re.search(r"<p[^>]*>(?!\s*<em>)(.*?)</p>", html, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1) if m else html)).strip()
    return text if len(text) <= maxlen else text[:maxlen - 1].rsplit(" ", 1)[0] + "…"


def run() -> None:
    if not (WP_URL and all(AUTH)):
        print("⚠️ Brak WP_URL/WP_USER/WP_APP_PASSWORD — pomijam.")
        return

    tag_id = _term_id("tags", TAG_SLUG)
    cat_id = _term_id("categories", CATEGORY_SLUG)
    if not tag_id:
        print(f"❌ Brak tagu „{TAG_SLUG}” w WordPressie — bez niego nie da się pilnować rytmu.")
        return

    since = _days_since_last_guide(tag_id)
    if since is not None and since < CADENCE_DAYS:
        print(f"⏸️ Ostatni poradnik {since:.1f} dni temu (rytm: co {CADENCE_DAYS} dni) — dziś nic.")
        return

    topics = {t["id"]: t for t in json.loads(TOPICS_PATH.read_text(encoding="utf-8"))}
    done = _existing_titles()
    order = QUEUE + [i for i in topics if i not in QUEUE]
    topic = next((topics[i] for i in order
                  if i in topics and not topics[i].get("failed") and _norm(topics[i]["title"]) not in done), None)
    if not topic:
        print("✅ Wszystkie tematy z topics.json są już w WordPressie.")
        return

    out = generate_blog_post(topic)
    html = out.read_text(encoding="utf-8")
    html = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", html, count=1, flags=re.S | re.I)

    featured = None
    m = re.search(r'<img[^>]+src="(images/[^"]+)"[^>]*>\s*', html)
    if m:
        _, featured = _upload_image(out.parent / m.group(1), topic["title"])
        html = html.replace(m.group(0), "", 1)   # obraz idzie jako wyróżniony, nie w treść

    payload = {
        "title": topic["title"],
        "content": html,
        "status": "draft",
        "tags": [tag_id],
        "meta": {"_yoast_wpseo_metadesc": _meta_desc(html)},
    }
    if cat_id:
        payload["categories"] = [cat_id]
    if featured:
        payload["featured_media"] = featured

    r = requests.post(f"{API}/posts", auth=AUTH, headers=HEADERS, json=payload, timeout=60)
    if r.status_code == 201:
        print(f"📝 Szkic do weryfikacji: {topic['title']} → {r.json().get('link')}")
    else:
        print(f"❌ Zapis szkicu nieudany ({r.status_code}): {r.text[:400]}")


if __name__ == "__main__":
    run()
