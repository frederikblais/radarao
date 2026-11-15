from datetime import UTC, datetime

from worker.analysis.verifier import best_ratio, normalize, validate_value, verify_quote

PAGE3 = """SECTION 2 — DÉPÔT DES SOUMISSIONS
Les soumissions doivent être reçues au plus tard le 20 novembre 2026 à 11 h, heure en vigueur,
à l’adresse suivante : 125, rue Principale, Magog (Québec).
Toute soumission reçue en retard sera retournée sans être ouverte."""
PAGE4 = """La garantie de soumis-
sion doit représenter 10 % du prix total soumis, sous forme de cautionnement."""
PAGES = {3: PAGE3, 4: PAGE4, 5: "Page sans rapport. Visite des lieux : non obligatoire."}


def test_normalize_typography() -> None:
    assert normalize("L’adresse  « suivante »") == normalize("l'adresse \"suivante\"")
    assert normalize("soumis-\nsion") == "soumission"
    assert normalize("Ouvrages – génie civil") == normalize("ouvrages - génie civil")


def test_exact_quote_on_right_page() -> None:
    v = verify_quote("au plus tard le 20 novembre 2026 à 11 h", 3, PAGES)
    assert v.status == "auto_ok" and v.page == 3 and v.ratio == 1.0


def test_quote_with_typographic_differences() -> None:
    v = verify_quote("à l'adresse suivante : 125, rue Principale", 3, PAGES)
    assert v.ok


def test_hyphenated_line_break() -> None:
    assert verify_quote("La garantie de soumission doit représenter 10 % du prix total", 4, PAGES).ok


def test_neighbor_page_is_corrected() -> None:
    v = verify_quote("garantie de soumission doit représenter 10 %", 3, PAGES)
    assert v.status == "auto_ok" and v.page == 4


def test_small_ocr_noise_is_tolerated() -> None:
    assert best_ratio("Toute soumission recue en retard sera retournee sans etre ouverte", PAGE3) >= 0.90


def test_invented_quote_is_rejected() -> None:
    v = verify_quote("la garantie de soumission est de 0 %", 4, PAGES)
    assert v.status == "quote_not_found"
    assert verify_quote("au plus tard le 20 novembre 2026 à 11 h", 9, PAGES).status == "quote_not_found"
    assert verify_quote(None, 3, PAGES).status == "quote_not_found"


def test_value_validation() -> None:
    now = datetime(2026, 11, 15, tzinfo=UTC)
    assert validate_value("date_limite_depot", "2026-11-20T11:00:00-05:00", now) is None
    assert validate_value("date_limite_depot", "2025-11-20T11:00:00-05:00", now) is not None
    assert validate_value("date_limite_depot", "20 novembre", now) is not None
    assert validate_value("garantie_soumission", "10 %") is None
    assert validate_value("validite_soumission_jours", "90") is None
    assert validate_value("validite_soumission_jours", "quatre-vingt-dix") is not None
    assert validate_value("visite_obligatoire", "Oui") is None
    assert validate_value("visite_obligatoire", "peut-être") is not None
