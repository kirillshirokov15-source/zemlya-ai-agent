from app.services.company_enrichment import valid_inn, valid_ogrn, _finalize


def test_inn_checksum():
    assert valid_inn("5029242308") is True
    assert valid_inn("5013014497") is True
    assert valid_inn("5029242309") is False


def test_ogrn_checksum_rejects_random():
    assert valid_ogrn("1234567890123") is False


def test_invalid_identifier_is_not_persisted_as_resolved():
    sources = [
        {
            "url": "https://invest.mosreg.ru/project",
            "official_source": True,
            "content": "Компания строит завод.",
        },
        {
            "url": "https://example.ru/company",
            "official_source": False,
            "content": "ООО Компания.",
        },
    ]
    raw = {
        "company_name": "Компания",
        "legal_name": "ООО Компания",
        "inn": "1234567890",
        "ogrn": None,
        "website": None,
        "project_relation_confidence": "high",
        "legal_identity_confidence": "medium",
        "project_relation_evidence": [
            {"fact": "Компания строит завод", "source_url": "https://invest.mosreg.ru/project"}
        ],
        "legal_identity_evidence": [
            {"fact": "Название юрлица", "source_url": "https://example.ru/company"}
        ],
        "unresolved_reason": None,
    }
    final = _finalize(raw, sources)
    assert final["inn"] is None
    assert final["resolution_confidence"] != "high"


def test_high_requires_project_and_legal_evidence():
    raw = {
        "company_name": "Гормаш Глобал",
        "legal_name": "ООО «ГОРМАШ ГЛОБАЛ»",
        "inn": "5029242308",
        "ogrn": None,
        "website": "https://example.ru",
        "project_relation_confidence": "high",
        "legal_identity_confidence": "high",
        "project_relation_evidence": [
            {"fact": "Строит завод в Московской области", "source_url": "https://invest.mosreg.ru/project"}
        ],
        "legal_identity_evidence": [
            {"fact": "ИНН юрлица", "source_url": "https://example.ru/company"}
        ],
        "unresolved_reason": None,
    }
    sources = [
        {"url": "https://invest.mosreg.ru/project"},
        {"url": "https://example.ru/company"},
    ]
    final = _finalize(raw, sources)
    assert final["resolution_confidence"] == "high"
    assert final["inn"] == "5029242308"
