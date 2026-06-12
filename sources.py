"""
sources.py — Abstrakcija virov podatkov o javnih naročilih (Faza 2).

Vsak vir implementira interface ProcurementSource in vrača naročila v
enotnem formatu (slovar s ključi: pjn, narocnik, naziv, vrsta, datum_objave,
rok_oddaje, stanje, kategorije, datum_scrape).

OPOMBA — raziskava OPSI (podatki.gov.si), junij 2026:
Preverjena sta bila dataseta "Seznam aktualnih javnih naročil v IS e-JN"
in "Zbirka obvestil v zvezi s postopki javnih naročil". Oba sta zgolj
HTML povezavi na ejn.gov.si oz. enarocanje.si — strukturiranega
CSV/JSON/API vira NI (ocena odprtosti 1 zvezdica, format HTML).
Zato ostaja ejn scraper edina implementacija; interface je pripravljen
za morebitni prihodnji uradni API.
"""

import time
import logging
from abc import ABC, abstractmethod

import scraper

logger = logging.getLogger(__name__)

# Backoff razmiki med ponovnimi poskusi: 30s, 2min, 10min
RETRY_DELAYS_S = [30, 120, 600]


class SourceError(Exception):
    """Vir podatkov ni uspel niti po vseh ponovnih poskusih."""


class ProcurementSource(ABC):
    """Interface za vir podatkov o javnih naročilih."""

    name: str = "neimenovan vir"

    @abstractmethod
    def fetch(self) -> list:
        """Vrne seznam naročil v enotnem formatu. Ob napaki dvigne izjemo."""


class EjnSource(ProcurementSource):
    """Vir: scraper strani aktualnih javnih naročil na ejn.gov.si."""

    name = "ejn.gov.si"

    def fetch(self) -> list:
        return scraper.poberi_narocila()


# Registrirani viri — dnevni job gre čez vse
SOURCES: list = [EjnSource()]


def fetch_z_retryjem(source: ProcurementSource, delays: list | None = None) -> list:
    """
    Pokliče source.fetch() z retry logiko: 1 poskus + 3 ponovitve
    z backoffom (30s, 2min, 10min). Ob popolnem failu dvigne SourceError —
    klicatelj (dnevni job) ob tem pošlje alert adminu.

    Args:
        source: Vir podatkov.
        delays: Razmiki med poskusi v sekundah (za teste).

    Returns:
        Seznam naročil.
    """
    if delays is None:
        delays = RETRY_DELAYS_S

    zadnja_napaka = None
    for poskus in range(len(delays) + 1):
        try:
            narocila = source.fetch()
            if poskus > 0:
                logger.info(f"Vir {source.name}: uspeh v poskusu {poskus + 1}.")
            return narocila
        except Exception as e:
            zadnja_napaka = e
            if poskus < len(delays):
                logger.warning(
                    f"Vir {source.name}: poskus {poskus + 1} ni uspel ({e}). "
                    f"Ponovni poskus čez {delays[poskus]}s."
                )
                time.sleep(delays[poskus])

    raise SourceError(
        f"Vir {source.name} ni uspel po {len(delays) + 1} poskusih: {zadnja_napaka}"
    ) from zadnja_napaka
