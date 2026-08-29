from app.services.sales_scoring import score_sales_project
from app.services.temporal_quality import assess_temporal_quality
from app.services.lead_gate import classify_lead


def test_unknown_company_reduces_sales_score():
    p = {
        "lead_score": 84,
        "company_name": None,
        "land_status": "confirmed_needed",
        "project_summary": "Подготовка стройплощадки запланирована на 2027 год.",
        "enrichment": {"resolution_confidence": "unresolved", "contacts": []},
    }
    scored = score_sales_project(assess_temporal_quality(p))
    assert scored["sales_score"] < scored["project_score"]
    assert scored["recommended_action"] == "resolve_company"


def test_generic_aggregator_goes_to_verification():
    item = {
        "title": "Инвестиционно-строительная активность - Московская область",
        "content": "В Московской области планируют построить несколько заводов.",
        "qualification": {
            "relevant": True,
            "confidence": "medium",
            "project_type": "Промышленный завод",
            "company_name": None,
            "project_summary": "Также в материале указан другой завод.",
            "location": "Московская область",
            "signal_status": "early_signal",
            "stage": "unknown",
        },
    }
    assert classify_lead(item)["lead_gate"]["bucket"] == "verification_pool"
