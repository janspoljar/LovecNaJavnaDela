"""
test_faza2.py — Testi za Fazo 2: idempotentnost emailov, retry logika virov,
backup/restore.
"""

import os
import sqlite3

import pytest

import db
import sources
from scripts.backup import ustvari_backup
from scripts.restore import obnovi_iz_datoteke


def setup_module():
    db.init_db()


# ---------------------------------------------------------------------------
# Idempotentnost emailov (uporabnik + datum)
# ---------------------------------------------------------------------------

def test_email_log_idempotentnost():
    """Po shrani_email_log mora je_email_poslan_danes vrniti True."""
    db.dodaj_uporabnika("idem@test.si", ["IT & Software"])
    db.aktiviraj_uporabnika("idem@test.si")
    uporabnik = next(
        u for u in db.poberi_aktivne_uporabnike() if u["email"] == "idem@test.si"
    )

    assert db.je_email_poslan_danes(uporabnik["id"]) is False
    db.shrani_email_log(uporabnik["id"], 5)
    assert db.je_email_poslan_danes(uporabnik["id"]) is True


def test_email_log_drug_datum():
    """Log z današnjim datumom ne sme blokirati drugega datuma."""
    db.dodaj_uporabnika("datum@test.si", ["Energetika"])
    db.aktiviraj_uporabnika("datum@test.si")
    uporabnik = next(
        u for u in db.poberi_aktivne_uporabnike() if u["email"] == "datum@test.si"
    )
    db.shrani_email_log(uporabnik["id"], 1)
    assert db.je_email_poslan_danes(uporabnik["id"], datum="2020-01-01") is False


# ---------------------------------------------------------------------------
# Retry logika virov
# ---------------------------------------------------------------------------

class _NestabilenVir(sources.ProcurementSource):
    """Testni vir: prvih n klicev vrže izjemo, potem uspe."""

    name = "test-vir"

    def __init__(self, failov: int):
        self.failov = failov
        self.klicev = 0

    def fetch(self) -> list:
        self.klicev += 1
        if self.klicev <= self.failov:
            raise ConnectionError("simulirana napaka")
        return [{"pjn": "JN-RETRY-001"}]


def test_retry_uspe_po_dveh_failih():
    vir = _NestabilenVir(failov=2)
    narocila = sources.fetch_z_retryjem(vir, delays=[0, 0, 0])
    assert len(narocila) == 1
    assert vir.klicev == 3


def test_retry_popoln_fail():
    """Po 1 + 3 neuspešnih poskusih mora dvigniti SourceError."""
    vir = _NestabilenVir(failov=99)
    with pytest.raises(sources.SourceError):
        sources.fetch_z_retryjem(vir, delays=[0, 0, 0])
    assert vir.klicev == 4


# ---------------------------------------------------------------------------
# Backup & restore
# ---------------------------------------------------------------------------

def test_backup_in_restore(tmp_path):
    """Backup mora biti veljavna kopija; restore jo mora postaviti nazaj."""
    izvor = str(tmp_path / "izvor.db")
    conn = sqlite3.connect(izvor)
    conn.execute("CREATE TABLE narocila (pjn TEXT UNIQUE)")
    conn.execute("INSERT INTO narocila VALUES ('JN-BAK-001')")
    conn.commit()
    conn.close()

    # Backup
    backup_pot = str(tmp_path / "backup.db")
    ustvari_backup(izvor, backup_pot)
    assert os.path.exists(backup_pot)

    # "Pokvarimo" izvor (simulacija izgube podatkov)
    conn = sqlite3.connect(izvor)
    conn.execute("DELETE FROM narocila")
    conn.commit()
    conn.close()

    # Restore
    obnovi_iz_datoteke(backup_pot, izvor)
    conn = sqlite3.connect(izvor)
    vrstic = conn.execute("SELECT COUNT(*) FROM narocila").fetchone()[0]
    conn.close()
    assert vrstic == 1

    # Varnostna kopija pred restore mora obstajati
    assert os.path.exists(izvor + ".pred-restore")


def test_restore_zavrne_pokvarjen_backup(tmp_path):
    """Restore mora zavrniti datoteko, ki ni veljavna SQLite baza."""
    pokvarjen = str(tmp_path / "pokvarjen.db")
    with open(pokvarjen, "wb") as f:
        f.write(b"to ni sqlite baza")

    cilj = str(tmp_path / "cilj.db")
    with pytest.raises(Exception):
        obnovi_iz_datoteke(pokvarjen, cilj)
