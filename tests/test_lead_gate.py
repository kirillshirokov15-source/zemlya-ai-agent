from app.services.lead_gate import gate_qualified_results


def _item(**q):
    return {
        "title": q.pop("_title", "Test"),
        "url": "https://example.com/x",
        "content": q.pop("_content", ""),
        "qualification": q,
    }


def test_paused_project_goes_to_verification():
    item = _item(
        relevant=True,
        company_name=None,
        project_type="фармацевтический завод",
        project_summary="Проект приостановлен",
        location="Московская область",
        investment_rub=4_000_000_000,
        stage="A",
        land_status="confirmed_needed",
        signal_status="confirmed_project",
        confidence="medium",
        evidence=["Проект приостановлен"],
    )
    result = gate_qualified_results([item])
    assert result["active_count"] == 0
    assert result["verification_pool_count"] == 1


def test_catalog_goes_to_verification():
    item = _item(
        relevant=True,
        company_name="Инвест-Недвижимость",
        project_type="Торговый центр / коммерческая недвижимость",
        project_summary=(
            "На странице представлены земельные участки. "
            "Это каталог объектов продажи, а не подтвержденный "
            "инвестиционный проект."
        ),
        location="Московская область",
        investment_rub=None,
        stage="unknown",
        land_status="land_defined",
        signal_status="early_signal",
        confidence="medium",
        evidence=[],
    )
    result = gate_qualified_results([item])
    assert result["active_count"] == 0
    assert result["verification_pool_count"] == 1


def test_confirmed_etm_like_project_stays_active():
    item = _item(
        relevant=True,
        company_name="ЭТМ",
        project_type="производственно-складской комплекс",
        project_summary="Компания планирует построить комплекс.",
        location="Дмитровский городской округ, Московская область",
        investment_rub=4_500_000_000,
        stage="V",
        land_status="land_defined",
        signal_status="confirmed_project",
        confidence="high",
        evidence=["Компании передан земельный участок."],
    )
    result = gate_qualified_results([item])
    assert result["active_count"] == 1
    assert result["verification_pool_count"] == 0
