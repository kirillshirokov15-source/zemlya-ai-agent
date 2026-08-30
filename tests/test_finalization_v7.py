from app.services.final_verification import verify_project


def test_land_defined_caps_sales():
    p = {
        "sales_score": 84,
        "project_score": 80,
        "land_status": "land_defined",
        "company_resolution_confidence": "high",
        "project_summary": "Новый завод",
    }
    out = verify_project(p)
    assert out["sales_score"] <= 59


def test_modernization_is_low():
    p = {
        "sales_score": 90,
        "project_score": 90,
        "company_resolution_confidence": "high",
        "project_summary": "Модернизация существующей производственной линии",
    }
    out = verify_project(p)
    assert out["project_score"] <= 30
    assert out["sales_score"] <= 29


def test_unresolved_company_caps_sales():
    p = {
        "sales_score": 80,
        "project_score": 80,
        "company_resolution_confidence": "unresolved",
        "project_summary": "Строительство нового завода",
    }
    out = verify_project(p)
    assert out["sales_score"] <= 49
