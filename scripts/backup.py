"""
backup.py — Nočni backup SQLite baze na S3-kompatibilen storage.

Uporablja sqlite3 .backup API (konsistenten snapshot tudi med pisanjem,
varno z WAL). Po uploadu pobriše backupe, starejše od BACKUP_RETENTION_DAYS.

Zagon (v containerju, prek host crona — glej DEPLOY.md):
    python -m scripts.backup                 # backup -> S3
    python -m scripts.backup --local-dir /pot  # backup samo v lokalno mapo (brez S3)

Credentials iz .env: S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID,
S3_SECRET_ACCESS_KEY, S3_REGION, BACKUP_RETENTION_DAYS.
"""

import os
import sys
import sqlite3
import logging
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups/"


def ustvari_backup(db_path: str, cilj_pot: str):
    """
    Naredi konsistenten snapshot baze z sqlite3 .backup API in preveri
    integriteto kopije. Ob napaki dvigne izjemo.
    """
    izvor = sqlite3.connect(db_path)
    cilj = sqlite3.connect(cilj_pot)
    try:
        izvor.backup(cilj)
    finally:
        izvor.close()
        cilj.close()

    # Preveri integriteto backupa
    kontrola = sqlite3.connect(cilj_pot)
    rezultat = kontrola.execute("PRAGMA integrity_check").fetchone()[0]
    kontrola.close()
    if rezultat != "ok":
        raise RuntimeError(f"Backup ni prestal integrity_check: {rezultat}")

    logger.info(f"Backup ustvarjen in preverjen: {cilj_pot}")


def _s3_client():
    """Vrne boto3 S3 klient iz config nastavitev. Ob manjkajočih dvigne izjemo."""
    import boto3

    manjka = [k for k in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
              if not getattr(config, k)]
    if manjka:
        raise RuntimeError(f"Manjkajo S3 nastavitve v .env: {', '.join(manjka)}")

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        region_name=config.S3_REGION,
        aws_access_key_id=config.S3_ACCESS_KEY_ID,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
    )


def nalozi_na_s3(lokalna_pot: str, ime: str):
    """Naloži backup datoteko na S3 pod ključ backups/<ime>."""
    s3 = _s3_client()
    kljuc = BACKUP_PREFIX + ime
    s3.upload_file(lokalna_pot, config.S3_BUCKET, kljuc)
    logger.info(f"Naloženo na S3: s3://{config.S3_BUCKET}/{kljuc}")


def pobrisi_stare_backupe(retention_days: int):
    """Pobriše S3 objekte pod backups/, starejše od retention_days."""
    s3 = _s3_client()
    meja = datetime.now(timezone.utc) - timedelta(days=retention_days)
    odgovor = s3.list_objects_v2(Bucket=config.S3_BUCKET, Prefix=BACKUP_PREFIX)

    pobrisanih = 0
    for obj in odgovor.get("Contents", []):
        if obj["LastModified"] < meja:
            s3.delete_object(Bucket=config.S3_BUCKET, Key=obj["Key"])
            logger.info(f"Pobrisan star backup: {obj['Key']}")
            pobrisanih += 1

    logger.info(f"Retencija {retention_days} dni: pobrisanih {pobrisanih} starih backupov.")


def main():
    ime = f"narocila-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"

    # --local-dir: backup samo v lokalno mapo (za teste / brez S3)
    if "--local-dir" in sys.argv:
        mapa = sys.argv[sys.argv.index("--local-dir") + 1]
        os.makedirs(mapa, exist_ok=True)
        cilj = os.path.join(mapa, ime)
        ustvari_backup(config.DB_PATH, cilj)
        print(f"Lokalni backup: {cilj}")
        return

    # Privzeto: backup -> temp -> S3 -> retencija
    with tempfile.TemporaryDirectory() as tmp:
        cilj = os.path.join(tmp, ime)
        ustvari_backup(config.DB_PATH, cilj)
        nalozi_na_s3(cilj, ime)

    pobrisi_stare_backupe(config.BACKUP_RETENTION_DAYS)
    print(f"Backup končan: {ime}")


if __name__ == "__main__":
    main()
