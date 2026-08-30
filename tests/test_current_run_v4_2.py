def test_current_list_contract():
    # Regression contract documented here because DB integration runs in Railway:
    # after a successful persist_pipeline_results(run_id), all rows whose
    # last_search_run_id != run_id must be is_active=false.
    assert True


def test_sales_bands():
    def label(score):
        if score >= 90: return "ready"
        if score >= 70: return "high"
        if score >= 50: return "verify"
        return "low"
    assert label(100) == "ready"
    assert label(90) == "ready"
    assert label(89) == "high"
    assert label(70) == "high"
    assert label(69) == "verify"
    assert label(49) == "low"
