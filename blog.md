# Projekt: GenesManager Blog Pipeline

## Co to jest i czym różni się od aktualności

Aktualności = reaktywne (co dziś opublikował NFZ/gov.pl). Blog = proaktywne (tematy które Twoi klienci szukają w Google). Razem tworzą dwie warstwy SEO: freshness + authority.

---

## Architektura (4 komponenty)

```
topics.json          ← Twoja lista tematów (raz skonfigurowana)
       ↓
blog_generator.py    ← GPT-5: research + H1 + obraz + artykuł 3500–5000 znaków
       ↓
blog_qa_claude.py    ← Claude API: weryfikacja faktów + jakość + decyzja PASS/REVISE/FAIL
       ↓
blog_pipeline.py     ← Orkiestracja + publikacja na WP (raz w tygodniu, cron Render)
```

**Kluczowa różnica od aktualności:** Claude wchodzi jako brama jakości między generacją a publikacją. GPT generuje, Claude ocenia, jeśli REVISE — GPT poprawia (max 2 próby), jeśli FAIL — temat skipowany i logowany.

---

## topics.json — skąd tematy

Dwa źródła jednocześnie:

**A) Lista stała (20–30 tematów wiecznych, powiązanych z usługami GM):**
```
- Jak negocjować kontrakt z NFZ w AOS krok po kroku
- Rejestracja podmiotu leczniczego w RPWDL – kompletny przewodnik
- Nadwykonania AOS: kiedy NFZ musi zapłacić
- Audyt NFZ w placówce – co sprawdzają kontrolerzy
- Umowy z lekarzami: B2B vs. kontrakt vs. umowa o pracę w 2026
- EDM w małej placówce – wdrożenie bez błędów
- Dofinansowania dla placówek medycznych z KPO 2025–2026
- Ustawa o jakości w opiece zdrowotnej – obowiązki dyrektora
- Jak zwiększyć wycenę kontraktu NFZ przy renegocjacji
- ...
```

**B) Tematy dynamiczne** — co tydzień pipeline aktualności liczy które słowa kluczowe pojawiają się najczęściej → jeśli temat pojawił się 3+ razy w tygodniu, automatycznie trafia jako priorytet do bloga. Gwarantuje aktualność bez ręcznej pracy.

Tematy z listy A oznaczane jako `"published": true` po użyciu — nie powtarzają się. Tematy z B mają datę wygaśnięcia (3 tygodnie).

---

## blog_qa_claude.py — weryfikacja przez Claude API

Serce całego projektu. Prompt dla Claude:

```
Jesteś redaktorem naczelnym, ekspertem prawa medycznego i zarządzania
placówkami w Polsce. Oceń poniższy artykuł według 5 kryteriów.

KRYTERIA:
1. FAKTY — czy daty, numery ustaw, kwoty wyglądają wiarygodnie?
   Jeśli coś wygląda jak hallucynacja (data nieistniejąca, błędny numer
   rozporządzenia) — ZAWSZE zgłoś jako issue.
2. H4 — czy max 8 nagłówków? Czy są konkretne (nie "Podsumowanie",
   "Wnioski", "Monitoring")?
3. PRZYDATNOŚĆ — czy artykuł realnie pomaga dyrektorowi placówki?
4. GŁĘBOKOŚĆ — min. 3000 znaków, czy temat potraktowany serio?
5. CTA — czy linki do usług GenesManager są uzasadnione kontekstem?

Zwróć TYLKO JSON:
{
  "verdict": "PASS" | "REVISE" | "FAIL",
  "score": 0–100,
  "issues": ["konkretny problem 1", "..."],
  "suggestions": ["co poprawić 1", "..."],
  "suspicious_facts": ["fakty które wyglądają jak hallucynacja"]
}

PASS (score >= 75, 0 suspicious_facts): publikuj
REVISE (score 50–74 lub suspicious_facts): odeślij do poprawy z issues
FAIL (score < 50 lub kluczowy błąd faktyczny): odrzuć temat
```

Przy REVISE: `suggestions` + `issues` wchodzą z powrotem do GPT jako dodatkowy kontekst do regeneracji. Max 2 próby regeneracji, po czym temat trafia do `failed_topics.log`.

---

## Schemat flow

```
Poniedziałek 08:00 (Render cron)
│
├── Wybierz temat z topics.json (niepublikowany, priorytet: dynamiczne > statyczne)
│
├── GPT-5: research (web search) → H1 → obraz → artykuł HTML
│
├── Claude API: ocena → verdict
│   ├── PASS  → publikuj na WP (status: publish, kategoria "Blog")
│   ├── REVISE → GPT ponowna generacja z feedback Claude (max 2x)
│   │   ├── PASS po retry → publikuj
│   │   └── FAIL po retry → log + wybierz kolejny temat z listy
│   └── FAIL  → log + następny temat
│
└── topics.json: oznacz temat jako published/failed
```

---

## Plan wdrożenia (3 tygodnie)

**Tydzień 1 — Generator i tematy**
- Plik `topics.json` z 20 tematami startowymi (do zatwierdzenia przez Ciebie)
- `blog_generator.py` — osobny od aktualności, inny prompt (głębszy research, więcej CTA, sekcja "Kluczowe wnioski" na końcu)
- Test ręczny: wygeneruj 2–3 artykuły i oceń jakość

**Tydzień 2 — Claude QA**
- `blog_qa_claude.py` — integracja Claude API (claude-sonnet-4-6)
- Kalibracja progu: ile razy REVISE przed uznaniem że prompt jest ok
- Test: wygeneruj 5 artykułów, przepuść przez QA, sprawdź co Claude odrzuca

**Tydzień 3 — Pipeline i Render**
- `blog_pipeline.py` — orkiestracja
- Render: drugi cron job (weekly, poniedziałki 08:00)
- Zmienne środowiskowe: `ANTHROPIC_API_KEY` do Render
- Monitoring: `failed_topics.log` + opcjonalnie email przy FAIL

---

## Co potrzebuję przed startem

1. **Zatwierdzenie listy tematów** — 20 propozycji do przeglądu, możesz dodać/usunąć
2. **Klucz Anthropic API** (`ANTHROPIC_API_KEY`) — wejdzie do `C:\GMSecrets\.env` i Render env vars
3. **Kategoria "Blog" na WP** — osobna od "Aktualności" (różna nawigacja, różne landing pages)

---

## Dlaczego to działa bez ryzyka błędów

W aktualności GPT pisze o realnych zdarzeniach z ostatnich 9 dni — ryzyko hallucynacji małe. Blog pisze o evergreen tematach (np. "jak działa kontrakt NFZ") gdzie GPT może wymyślić nieistniejące rozporządzenie. Claude jako reviewer nie puści artykułu z `suspicious_facts` — wyśle do regeneracji z konkretnym wskazaniem błędu.

Nie jest to 100% gwarancja — przy bardzo specyficznych tematach warto zerknąć przed indeksacją — ale w 90% przypadków Claude wyłapie błędy które byłyby problematyczne.
