from app.services.temporal_quality import assess_temporal_quality
from app.services.lead_gate import classify_lead
from app.services.candidate_ranking import score_candidate


def test_past_launch_requires_current_status_verification():
    item = {
        "qualification": {
            "relevant": True,
            "project_type": "завод",
            "project_summary": "Запуск производства был запланирован на 15 июня 2026 года.",
            "location": "Московская область",
            "stage": "V",
            "land_status": "land_defined",
            "signal_status": "confirmed_project",
            "confidence": "high",
            "evidence": [],
        }
    }
    assessed = assess_temporal_quality(item)
    gated = classify_lead(assessed)
    assert assessed["temporal_quality"]["needs_current_status_check"] is True
    assert gated["lead_gate"]["bucket"] == "verification_pool"


def test_official_source_not_hard_rejected_for_title_content_mismatch():
    item = {
        "title": "В Подмосковье запускается новый завод за 2 млрд рублей",
        "url": "https://invest.mosreg.ru/example",
        "content": "Совершенно другой короткий фрагмент выдачи, Московская область.",
        "score": 0.8,
        "extraction": {},
    }
    scored = score_candidate(item)
    pre = scored["prequalification"]
    assert pre["quality_reject"] is False


def test_extraction_budget_passthrough_goes_to_verification():
    item = {
        "title": "Инвестиционные проекты Московской области",
        "content": "Московская область. Планируется строительство завода.",
        "extraction": {"source_type": "extraction_budget_passthrough"},
        "qualification": {
            "relevant": True,
            "project_type": "завод",
            "project_summary": "Планируется строительство завода.",
            "location": "Московская область",
            "stage": "A",
            "land_status": "unknown",
            "signal_status": "confirmed_project",
            "confidence": "medium",
            "evidence": [],
        },
    }
    gated = classify_lead(item)
    assert gated["lead_gate"]["bucket"] == "verification_pool"
