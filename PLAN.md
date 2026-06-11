# PLAN — Lovec (jn-watchdog) → production-ready SaaS

## Kontekst

Delujoč backend za SaaS, ki dnevno scrapea javna naročila z ejn.gov.si,
jih filtrira in strankam pošilja email alerte.

Obstoječe stanje: Python/Flask, SQLite (3 tabele: narocila, uporabniki,
email_logi), scraper (JSF POST paginacija, ~1.600 naročil), keyword
kategorizer, emailer prek Resend, endpointi /registracija, /stripe-webhook,
/odjava, /zdravje, dnevni job orchestrator. Stripe koda napisana, ključi še
ne obstajajo.

Cilj: production-ready sistem na Hetzner serverju, s personaliziranim AI
matchingom namesto fiksnih kategorij, landing pageom in Stripe naročninami:

| Paket    | Cena       | Frekvenca             | Profili    |
|----------|------------|-----------------------|------------|
| Osnovni  | 29 €/mes   | tedenski email        | 1          |
| Pro      | 59 €/mes   | dnevni alerti         | 3          |
| Business | 119 €/mes  | real-time             | neomejeno  |

## Pravila dela

- Delaj STROGO po fazah spodaj. Po vsaki fazi se ustavi, povzemi kaj je
  narejeno, kaj mora Jan ročno narediti, in počakaj na potrditev.
- Najprej preglej obstoječo kodo, preden karkoli spreminjaš.
- Ne briši in ne prepisuj obstoječe logike brez razlage zakaj.
- Vse skrivnosti samo v .env (v repo samo .env.example). Nikoli ne commitaj ključev.
- Vsaka faza = ločen git commit (ali branch + PR) s smiselnim sporočilom.
- Testi za kritično logiko (idempotentnost, webhook, matching parsing).
- Komentarji in uporabniško vidni teksti v slovenščini, koda/spremenljivke v angleščini.
- Če nečesa ni mogoče narediti (manjka dostop, ključ, odločitev), to jasno
  povej in predlagaj rešitev — brez ugibanja in tihega mockanja.

## FAZA 1 — Dockerizacija in deploy

1. Dockerfile za Flask app (gunicorn, non-root user) + docker-compose.yml z
   app + Caddy (reverse proxy, auto HTTPS, domena prek env placeholderja).
   Volume za SQLite datoteko in za Caddy podatke.
2. cloud-init skripta za svež Ubuntu 24.04 Hetzner server: ufw (22,80,443),
   fail2ban, unattended-upgrades, docker install, SSH samo s ključi.
3. GitHub Actions workflow: push na main → testi → SSH deploy na server
   (git pull && docker compose up -d --build). Server IP/secrets kot GitHub secrets.
4. DEPLOY.md s točnimi ročnimi koraki (Hetzner account, domena DNS, GitHub secrets).

STOP — počakaj da Jan postavi server in potrdi, da deploy dela.

## FAZA 2 — Zanesljivost dnevnega joba

5. SQLite WAL mode povsod, en write connection pattern.
6. Idempotentnost: dedup naročil po portal ID; pred pošiljanjem preveri email
   log (uporabnik+datum) — dvojni zagon joba ne sme poslati dvojnih emailov.
7. Scraper: 1–2s delay med requesti, razumen User-Agent, retry 3x z backoffom
   (30s, 2min, 10min); ob popolnem failu alert email Janu.
8. Nočni backup: cron skripta sqlite .backup → upload na S3-kompatibilen
   storage (Hetzner Object Storage ali Backblaze B2, credentials iz .env) +
   retencija 30 dni. Tudi restore skripta in test zanjo.
9. Dnevni povzetek Janu na email: scraped/novih/poslanih/napak.
10. Abstrahiraj vir podatkov v interface ProcurementSource (ejn scraper =
    prva implementacija). Preveri ali na podatki.gov.si (OPSI) obstaja uradni
    odprti dataset javnih naročil — če da, implementiraj kot drugi vir.

STOP — povzetek in potrditev.

## FAZA 3 — AI matching namesto kategorij

11. Nova shema: profil stranke (tekstovni opis dejavnosti, regije, opcijski
    razpon vrednosti naročila; Pro=3 profili, Business=neomejeno).
12. Matching: za vsa NOVA naročila dneva × aktivne profile batch klici na
    Claude API (model claude-haiku, structured output JSON:
    {relevant: bool, confidence: float, reason: string v slovenščini, en
    stavek}). API ključ iz .env. Optimiziraj stroške (batch, samo nova
    naročila, cache).
13. Logiraj vsako matching odločitev v bazo (naročilo, profil, score, reason).
14. Prenovi email template: naročila sortirana po confidence, vsak zapis ima
    "Zakaj je to za vas: ..." in vidno označen rok oddaje. Prag ≥0.7 glavna
    sekcija, 0.5–0.7 sekcija "Morda zanimivo".
15. Frekvenca po paketu: Osnovni tedensko (ponedeljek 7:00), Pro/Business
    dnevno (7:00).

STOP.

## FAZA 4 — Landing page + lead magnet

16. Landing page (server-side rendered, isti Flask, brez frameworkov, hiter,
    mobile-first, slovenščina): hero "Nikoli več zamujenega razpisa", kako
    deluje v 3 korakih, ceniki s 3 paketi, CTA.
17. Lead magnet: forma "Vpišite svojo dejavnost → brezplačen pregled
    zamujenih naročil zadnjih 30 dni" → matching čez obstoječo bazo → HTML
    report na email → shrani lead (email+profil) v bazo.
18. Registracijski flow: opis dejavnosti → izbira paketa → (Stripe checkout
    v fazi 5, zaenkrat placeholder "beta — brezplačno") → double opt-in
    potrditev emaila.
19. GDPR: stran s politiko zasebnosti, unsubscribe link v vsakem emailu.

STOP.

## FAZA 5 — Stripe (šele s ključi)

20. Checkout sessions za 3 pakete, webhook z OBVEZNO verifikacijo podpisa:
    checkout.session.completed, invoice.payment_failed,
    customer.subscription.deleted. Strani /uspeh in /preklicano.
21. Status naročnine v bazi gatea frekvenco emailov in št. profilov.
22. Navodila za Jana: kaj klikniti v Stripe dashboardu (Products, Customer
    Portal, Smart Retries) korak za korakom.

## FAZA 6 — Monitoring

23. Sentry SDK integracija (DSN iz .env), strukturirano logiranje.
24. /zdravje endpoint razširi: zadnji uspešen job, št. naročil v bazi, verzija.
25. Končni E2E test plan: registracija → plačilo (test mode) → dnevni email →
    odpoved. Checklist za ročni pregled.
