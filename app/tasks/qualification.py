import asyncio

from app.worker import celery_app
from app.services.tavily_search import run_default_discovery
from app.services.project_extraction import extract_atomic_projects
from app.services.candidate_ranking import rank_candidates
from app.services.qualification import qualify_results
from app.services.lead_gate import gate_qualified_results
from app.services.project_dedup import deduplicate_qualified_projects
from app.services.lead_scoring import score_projects


def _queue_view(item):
    preq = item.get("prequalification") or {}
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "query": item.get("query"),
        "search_score": item.get("score"),
        "prequalification_score": preq.get("score"),
        "prequalification_reasons": preq.get("reasons", []),
        "quality_reject_reasons": preq.get("quality_reject_reasons", []),
        "title_content_integrity_ratio": preq.get(
            "title_content_integrity_ratio"
        ),
        "extraction": item.get("extraction"),
    }


def _gate_view(item):
    qualification = item.get("qualification") or {}
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "company_name": qualification.get("company_name"),
        "project_type": qualification.get("project_type"),
        "project_summary": qualification.get("project_summary"),
        "location": qualification.get("location"),
        "investment_rub": qualification.get("investment_rub"),
        "stage": qualification.get("stage"),
        "land_status": qualification.get("land_status"),
        "signal_status": qualification.get("signal_status"),
        "confidence": qualification.get("confidence"),
        "lead_gate": item.get("lead_gate"),
    }


@celery_app.task(name="qualification.discovery_test")
def qualification_discovery_test():
    discovery = asyncio.run(
        run_default_discovery(max_results_per_query=8, days_back=180)
    )

    extraction = extract_atomic_projects(
        discovery["results"],
        max_llm_sources=12,
    )

    ranking = rank_candidates(
        extraction["results"],
        max_selected=35,
        minimum_score=20,
    )

    qualification = qualify_results(
        ranking["selected"],
        max_llm_items=35,
    )

    lead_gate = gate_qualified_results(
        qualification["qualified"]
    )

    # Only active candidates enter CRM scoring.
    # Verification candidates are retained separately and can be enriched later.
    deduplication = deduplicate_qualified_projects(
        lead_gate["active"]
    )

    scoring = score_projects(
        deduplication["projects"]
    )

    return {
        "discovery": {
            "queries_used": discovery["queries_used"],
            "unique_results": discovery["unique_results"],
        },
        "extraction": {
            "input_sources_count": extraction["input_sources_count"],
            "llm_sources_processed": extraction["llm_sources_processed"],
            "split_sources_count": extraction["split_sources_count"],
            "extracted_projects_count": extraction["extracted_projects_count"],
            "passthrough_count": extraction["passthrough_count"],
            "discovery_only_count": extraction["discovery_only_count"],
            "results_count": extraction["results_count"],
            "discovery_only": extraction["discovery_only"],
        },
        "ranking": {
            "input_count": ranking["input_count"],
            "eligible_count": ranking["eligible_count"],
            "selected_count": ranking["selected_count"],
            "deferred_count": ranking["deferred_count"],
            "below_threshold_count": ranking["below_threshold_count"],
            "quality_rejected_count": ranking["quality_rejected_count"],
            "max_selected": ranking["max_selected"],
            "minimum_score": ranking["minimum_score"],
            "deferred_queue": [
                _queue_view(x) for x in ranking["deferred"]
            ],
            "quality_rejected": [
                _queue_view(x) for x in ranking["quality_rejected"]
            ],
        },
        "qualification": qualification,
        "lead_gate": {
            "input_qualified_count": lead_gate["input_qualified_count"],
            "active_count": lead_gate["active_count"],
            "verification_pool_count": lead_gate["verification_pool_count"],
            "rejected_count": lead_gate["rejected_count"],
            "verification_pool": [
                _gate_view(x) for x in lead_gate["verification_pool"]
            ],
            "rejected": [
                _gate_view(x) for x in lead_gate["rejected"]
            ],
        },
        "deduplication": deduplication,
        "scoring": scoring,
    }
