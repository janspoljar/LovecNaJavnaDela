"""
restore.py — Obnova SQLite baze iz backupa.

Zagon (v containerju):
    python -m scripts.restore                       # obnovi NAJNOVEJŠI backup z S3
    python -m scripts.restore --key backups/narocila-20260612-023000.db
    python -m scripts.restore --from-file /pot/do/backup.db   # iz lokalne datoteke

Varnost: pred zamenjavo se trenutna baza shrani kot <DB_PATH>.pred-restore,
obnovljena kopija pa mora prestati PRAGMA integrity_check.
POZOR: med restore naj bosta app in scheduler ustavljena
(docker compose stop app scheduler).
"""

import os
import sys
import shutil
import sqlite3
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from scripts.backup import _s3_client, BACKUP_PREFIX  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def preveri_integriteto(pot: str):
    """PRAGMA integrity_check — ob napaki dvigne izjemo."""
    conn = sqlite3.connect(pot)
    rezultat = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    if rezultat != "ok":
        raise RuntimeError(f"Backup datoteka ni veljavna ({rezultat}): {pot}")


def najnovejsi_s3_kljuc() -> str:
    """Vrne ključ najnovejšega backupa na S3."""
    s3 = _s3_client()
    odgovor = s3.list_objects_v2(Bucket=config.S3_BUCKET, Prefix=BACKUP_PREFIX)
    objekti = odgovor.get("Contents", [])
    if not objekti:
        raise RuntimeError(f"Na S3 ni nobenega backupa pod {BACKUP_PREFIX}")
    najnovejsi = max(objekti, key=lambda o: o["LastModified"])
    return najnovejsi["Key"]


def obnovi_iz_datoteke(backup_pot: str, db_pot: str):
    """
    Obnovi bazo iz backup datoteke:
    1. preveri integriteto backupa,
    2. trenutno bazo shrani kot .pred-restore (če obstaja),
    3. backup skopira na mesto baze in pobriše zastarele -wal/-shm.
    """
    preveri_integriteto(backup_pot)

    if os.path.exists(db_pot):
        varnostna = db_pot + ".pred-restore"
        shutil.copy2(db_pot, varnostna)
        logger.info(f"Trenutna baza shranjena kot: {varnostna}")

    shutil.copy2(backup_pot, db_pot)

    # WAL/SHM datoteke stare baze niso veljavne za obnovljeno kopijo
    for pripona in ("-wal", "-shm"):
        try:
            os.remove(db_pot + pripona)
        except FileNotFoundError:
            pass

    preveri_integriteto(db_pot)
    logger.info(f"Baza obnovljena: {db_pot}")


def main():
    if "--from-file" in sys.argv:
        backup_pot = sys.argv[sys.argv.index("--from-file") + 1]
        obnovi_iz_datoteke(backup_pot, config.DB_PATH)
        print(f"Obnovljeno iz lokalne datoteke: {backup_pot}")
        return

    # Z S3: --key <kljuc> ali najnovejši
    if "--key" in sys.argv:
        kljuc = sys.argv[sys.argv.index("--key") + 1]
    else:
        kljuc = najnovejsi_s3_kljuc()
        logger.info(f"Najnovejši backup na S3: {kljuc}")

    s3 = _s3_client()
    lokalna = "/tmp/" + os.path.basename(kljuc)
    s3.download_file(config.S3_BUCKET, kljuc, lokalna)
    logger.info(f"Preneseno z S3: {kljuc}")

    obnovi_iz_datoteke(lokalna, config.DB_PATH)
    os.remove(lokalna)
    print(f"Obnovljeno iz S3: {kljuc}")


if __name__ == "__main__":
    main()
