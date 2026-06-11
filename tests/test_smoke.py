"""
test_smoke.py — Smoke testi za kritično logiko (Faza 1: minimalni CI gate).
Pokriva: kategorizer, dedup naročil po pjn, dedup uporabnikov, oznako poslano.
"""

import db
from scraper import kategorize


def _vzorcno_narocilo(pjn: str, naziv: str) -> dict:
    return {
        "pjn": pjn,
        "narocnik": "Testni naročnik",
        "naziv": naziv,
        "vrsta": "Blago",
        "datum_objave": "2026-06-01",
        "rok_oddaje": "2026-07-01",
        "stanje": "Objavljeno",
        "kategorije": kategorize(naziv),
    }


def setup_module():
    db.init_db()


def test_kategorize_it():
    assert "IT & Software" in kategorize("Razvoj informacijskega sistema")


def test_kategorize_gradbenistvo():
    # Normalizacija šumnikov: "ceste" ujame "cest"
    assert "Gradbeništvo" in kategorize("Rekonstrukcija lokalne ceste")


def test_kategorize_drugo():
    assert kategorize("Nakup pisarniških stolov") == ["Drugo"]


def test_dedup_narocil_po_pjn():
    """Isto naročilo dvakrat -> samo en nov vnos (idempotentnost scraperja)."""
    n = _vzorcno_narocilo("JN-SMOKE-001/2026", "Razvoj spletne aplikacije")
    prvic = db.shrani_narocila([n])
    drugic = db.shrani_narocila([n])
    assert prvic == 1
    assert drugic == 0


def test_dedup_uporabnikov():
    """Isti email dvakrat -> drugi insert vrne False."""
    assert db.dodaj_uporabnika("smoke@test.si", ["IT & Software"]) is True
    assert db.dodaj_uporabnika("smoke@test.si", ["Gradbeništvo"]) is False


def test_oznaci_kot_poslano():
    n = _vzorcno_narocilo("JN-SMOKE-002/2026", "Dobava zdravil za lekarno")
    db.shrani_narocila([n])
    db.oznaci_kot_poslano(["JN-SMOKE-002/2026"])
    nepozlana = db.poberi_nova_narocila([])
    assert all(x["pjn"] != "JN-SMOKE-002/2026" for x in nepozlana)


def test_aktivacija_uporabnika():
    db.dodaj_uporabnika("aktiven@test.si", ["Energetika"])
    db.aktiviraj_uporabnika("aktiven@test.si")
    aktivni = db.poberi_aktivne_uporabnike()
    assert any(u["email"] == "aktiven@test.si" for u in aktivni)
