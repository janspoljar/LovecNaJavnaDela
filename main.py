"""
main.py — Glavni orchestrator za jn-watchdog.
Dnevni job: scraping -> filtriranje po uporabnikih -> pošiljanje emailov.

Zagon:
    python main.py            # inicializira bazo + scheduler (vsak dan ob 06:00)
    python main.py --test     # požene dnevni job takoj enkrat
    python main.py --server   # zažene samo Flask API strežnik
"""

import sys
import time
import logging

import schedule

import db
import scraper
import emailer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def dnevni_job():
    """
    Dnevni job:
    1. Inicializira bazo
    2. Požene scraper in shrani nova naročila
    3. Za vsakega aktivnega uporabnika pošlje email z relevantnimi naročili
    4. Označi poslana naročila in shrani loge
    5. Izpiše summary
    """
    logger.info("=== Začetek dnevnega joba ===")

    # 1. Baza
    db.init_db()

    # 2. Scraping — pobere in shrani nova naročila
    novih = scraper.scrape_in_shrani()
    logger.info(f"Scraping končan, novih naročil: {novih}")

    # 3. Aktivni uporabniki
    uporabniki = db.poberi_aktivne_uporabnike()
    logger.info(f"Aktivnih uporabnikov: {len(uporabniki)}")

    poslanih_emailov = 0
    poslanih_narocil = set()

    # 4. Za vsakega uporabnika: relevantna neposlana naročila -> email -> log
    for uporabnik in uporabniki:
        narocila = db.poberi_nova_narocila(uporabnik["kategorije"])
        if not narocila:
            logger.info(f"Ni novih naročil za {uporabnik['email']}.")
            continue

        if emailer.pošlji_email(uporabnik["email"], narocila):
            poslanih_emailov += 1
            db.shrani_email_log(uporabnik["id"], len(narocila))
            # Zberi PJN oznake za kasnejšo označitev
            for n in narocila:
                poslanih_narocil.add(n["pjn"])
        else:
            logger.error(f"Email za {uporabnik['email']} ni bil poslan.")

    # Označi kot poslano šele po vseh uporabnikih,
    # da isto naročilo dobijo vsi relevantni uporabniki
    if poslanih_narocil:
        db.oznaci_kot_poslano(list(poslanih_narocil))

    # 5. Summary
    logger.info("=== Summary dnevnega joba ===")
    logger.info(f"Uporabnikov:        {len(uporabniki)}")
    logger.info(f"Poslanih emailov:   {poslanih_emailov}")
    logger.info(f"Naročil v emailih:  {len(poslanih_narocil)}")
    logger.info(f"Novih iz scraperja: {novih}")


def zazeni_scheduler():
    """Inicializira bazo in zažene scheduler — dnevni job vsak dan ob 06:00."""
    db.init_db()
    schedule.every().day.at("06:00").do(dnevni_job)
    logger.info("Scheduler zagnan — dnevni job ob 06:00. Čakam...")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        # Testni zagon — požene job takoj enkrat
        dnevni_job()
    elif "--server" in sys.argv:
        # Samo Flask API strežnik
        import config
        from server import app
        db.init_db()
        app.run(host="0.0.0.0", port=config.PORT)
    else:
        # Privzeto: scheduler v neskončni zanki
        zazeni_scheduler()
