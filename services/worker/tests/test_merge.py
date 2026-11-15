from api.app.schemas.ai import ExtractedField
from worker.analysis.merge import merge_fields


def f(cle: str, valeur: str | None, doc: str, page: int = 1, conf: str = "haute") -> ExtractedField:
    return ExtractedField(
        cle=cle, valeur=valeur, citation=f"cit {valeur}", document_id=doc, page=page, confiance=conf, remarque=None
    )


RANKS = {"main": 0, "add1": 1, "add2": 2}


def test_addendum_supersedes_in_number_order() -> None:
    out = merge_fields(
        [
            ("calendrier", "T1", [f("date_limite_depot", "2026-11-18T11:00:00-05:00", "main", 3)]),
            (
                "calendrier",
                "T1",
                [
                    f("date_limite_depot", "2026-11-25T11:00:00-05:00", "add2", 1),
                    f("date_limite_depot", "2026-11-20T11:00:00-05:00", "add1", 1),
                ],
            ),
        ],
        RANKS,
    )
    chain = sorted([x for x in out if x.key == "date_limite_depot"], key=lambda x: x.rank)
    assert [c.value for c in chain] == [
        "2026-11-18T11:00:00-05:00",
        "2026-11-20T11:00:00-05:00",
        "2026-11-25T11:00:00-05:00",
    ]
    assert chain[0].superseded_by == chain[1].id
    assert chain[1].superseded_by == chain[2].id
    assert chain[2].superseded_by is None


def test_same_value_in_addendum_is_not_a_change() -> None:
    out = merge_fields(
        [("admissibilite", "T2", [f("garantie_soumission", "10 %", "main"), f("garantie_soumission", "10 %", "add1")])],
        RANKS,
    )
    assert len(out) == 1 and out[0].superseded_by is None


def test_highest_confidence_wins_at_same_rank() -> None:
    out = merge_fields(
        [
            (
                "calendrier",
                "T1",
                [
                    f("mode_depot", "papier", "main", conf="faible"),
                    f("mode_depot", "électronique (SEAO)", "main", conf="haute"),
                ],
            )
        ],
        RANKS,
    )
    assert [x.value for x in out] == ["électronique (SEAO)"]


def test_multi_valued_are_deduplicated() -> None:
    out = merge_fields(
        [
            (
                "documents",
                "T6",
                [
                    f("document_a_remettre", "Formulaire 1", "main"),
                    f("document_a_remettre", "formulaire 1 ", "main"),
                    f("document_a_remettre", "Formulaire 2", "add1"),
                ],
            )
        ],
        RANKS,
    )
    assert sorted(x.value or "" for x in out) == ["Formulaire 1", "Formulaire 2"]


def test_unknown_document_is_rejected_and_unknown_key_ignored() -> None:
    out = merge_fields(
        [("calendrier", "T1", [f("mode_depot", "papier", "doc_d_un_autre_client"), f("cle_inventee", "x", "main")])],
        RANKS,
    )
    assert len(out) == 1
    assert out[0].document_id is None and out[0].confidence == "low"


def test_not_found_kept_once() -> None:
    out = merge_fields([("calendrier", "T1", [f("date_visite", None, "main"), f("date_visite", None, "main")])], RANKS)
    assert len(out) == 1 and out[0].value is None
