from app.services.contact_enrichment import _normalize_email, _normalize_phone


def test_email_validation():
    assert _normalize_email("sales@example.ru") == "sales@example.ru"
    assert _normalize_email("not-an-email") is None


def test_phone_validation():
    assert _normalize_phone("+7 (495) 123-45-67") is not None
    assert _normalize_phone("123") is None
