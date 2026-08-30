import asyncio

from app.worker import celery_app
from app.services.tavily_search import run_default_discovery
from app.services.page_enrichment import enrich_search_results_with_full_pages_sync
from app.services.project_extraction import extract_atomic_projects
from app.services.candidate_ranking import rank_candidates
from app.services.qualification import qualify_results
from app.services.lead_gate import gate_qualified_results
from app.services.project_dedup import deduplicate_qualified_projects
from app.services.lead_scoring import score_projects
from app.services.temporal_quality import assess_temporal_projects
from app.services.company_enrichment import enrich_projects
from app.services.sales_scoring import score_sales_projects
from app.services.final_quality_gate import apply_business_relevance, deduplicate_business_projects
from app.services.contact_enrichment import enrich_project_contacts
from app.services.project_persistence import (
    create_search_run,
    finish_search_run,
    persist_pipeline_results,
)


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
        "title_content_integrity_ratio": preq.get("title_content_integrity_ratio"),
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
    discovery = asyncio.run(run_default_discovery(max_results_per_query=8, days_back=180))

    search_run_id = create_search_run(
        queries_used=discovery["queries_used"],
        discovered_count=discovery["unique_results"],
        metadata={"task": "qualification.discovery_test", "pipeline_version": "quality-v4"},
    )

    try:
        page_enrichment = enrich_search_results_with_full_pages_sync(
            discovery["results"], max_urls=45, extract_depth="basic"
        )
        extraction = extract_atomic_projects(page_enrichment["results"], max_llm_sources=20)
        ranking = rank_candidates(extraction["results"], max_selected=40, minimum_score=20)
        qualification = qualify_results(ranking["selected"], max_llm_items=40)
        temporally_qualified = assess_temporal_projects(qualification["qualified"])
        lead_gate = gate_qualified_results(temporally_qualified)
        deduplication = deduplicate_qualified_projects(lead_gate["active"])

        # Project-fit score remains independent from contactability.
        project_scoring = score_projects(deduplication["projects"])
        # Resolve investor/company and public contacts only for stronger leads.
        enrichment = enrich_projects(
            project_scoring["projects"],
            max_projects=20,
            min_project_score=40,
        )
        business_checked = apply_business_relevance(enrichment["projects"])
        final_dedup = deduplicate_business_projects(business_checked)
        contact_enrichment = enrich_project_contacts(
            final_dedup["projects"],
            max_projects=15,
            min_project_score=50,
        )
        sales_scoring = score_sales_projects(contact_enrichment["projects"])

        persistence = persist_pipeline_results(
            search_run_id=search_run_id,
            active_scored_projects=sales_scoring["projects"],
            verification_items=lead_gate["verification_pool"],
        )

        finish_search_run(
            search_run_id,
            status="success",
            extracted_count=extraction["results_count"],
            qualified_count=qualification["qualified_count"],
            active_count=lead_gate["active_count"],
            verification_count=lead_gate["verification_pool_count"],
            rejected_count=lead_gate["rejected_count"],
            metadata_patch={
                "quality_rejected_count": ranking["quality_rejected_count"],
                "below_threshold_count": ranking["below_threshold_count"],
                "enrichment_processed": enrichment["processed_count"],
                "enrichment_resolved": enrichment["resolved_count"],
                "company_resolution_high": enrichment["high_confidence_count"],
                "company_resolution_medium": enrichment["medium_confidence_count"],
                "company_resolution_unresolved": enrichment["unresolved_count"],
                "final_duplicates_merged": final_dedup["merged_count"],
                "contacts_processed": contact_enrichment["processed_count"],
                "projects_with_contacts": contact_enrichment["with_contacts_count"],
                "projects_with_direct_contact": contact_enrichment["with_direct_contact_count"],
                "pipeline_version": "contacts-v6",
            },
        )

        return {
            "search_run_id": search_run_id,
            "pipeline_version": "contacts-v6",
            "discovery": {
                "queries_used": discovery["queries_used"],
                "unique_results": discovery["unique_results"],
            },
            "page_enrichment": {
                "urls_requested": page_enrichment["urls_requested"],
                "full_page_success_count": page_enrichment["full_page_success_count"],
                "snippet_fallback_count": page_enrichment["snippet_fallback_count"],
                "failed_batches": page_enrichment["failed_batches"],
                "extract_depth": page_enrichment["extract_depth"],
            },
            "extraction": {
                "input_sources_count": extraction["input_sources_count"],
                "llm_sources_processed": extraction["llm_sources_processed"],
                "split_sources_count": extraction["split_sources_count"],
                "extracted_projects_count": extraction["extracted_projects_count"],
                "passthrough_count": extraction["passthrough_count"],
                "discovery_only_count": extraction["discovery_only_count"],
                "results_count": extraction["results_count"],
            },
            "ranking": {
                "input_count": ranking["input_count"],
                "eligible_count": ranking["eligible_count"],
                "selected_count": ranking["selected_count"],
                "deferred_count": ranking["deferred_count"],
                "below_threshold_count": ranking["below_threshold_count"],
                "quality_rejected_count": ranking["quality_rejected_count"],
                "deferred_queue": [_queue_view(x) for x in ranking["deferred"]],
                "quality_rejected": [_queue_view(x) for x in ranking["quality_rejected"]],
            },
            "qualification": {
                "input_results": qualification["input_results"],
                "llm_items_processed": qualification["llm_items_processed"],
                "hard_filtered_count": qualification["hard_filtered_count"],
                "stale_filtered_count": qualification["stale_filtered_count"],
                "reserve_candidate_count": qualification["reserve_candidate_count"],
                "qualified_count": qualification["qualified_count"],
            },
            "lead_gate": {
                "input_qualified_count": lead_gate["input_qualified_count"],
                "active_count": lead_gate["active_count"],
                "verification_pool_count": lead_gate["verification_pool_count"],
                "rejected_count": lead_gate["rejected_count"],
                "verification_pool": [_gate_view(x) for x in lead_gate["verification_pool"]],
            },
            "deduplication": {
                "unique_projects_count": deduplication["unique_projects_count"],
                "duplicates_merged_count": deduplication["duplicates_merged_count"],
            },
            "project_scoring": {
                "projects_scored_count": project_scoring["projects_scored_count"],
                "priority_counts": project_scoring["priority_counts"],
            },
            "company_resolution": {
                "processed_count": enrichment["processed_count"],
                "resolved_count": enrichment["resolved_count"],
                "high_confidence_count": enrichment["high_confidence_count"],
                "medium_confidence_count": enrichment["medium_confidence_count"],
                "unresolved_count": enrichment["unresolved_count"],
            },
            "final_quality_gate": {
                "input_count": final_dedup["input_count"],
                "unique_count": final_dedup["unique_count"],
                "merged_count": final_dedup["merged_count"],
            },
            "contact_enrichment": {
                "processed_count": contact_enrichment["processed_count"],
                "with_contacts_count": contact_enrichment["with_contacts_count"],
                "with_direct_contact_count": contact_enrichment["with_direct_contact_count"],
            },
            "sales_scoring": {
                "projects_scored_count": sales_scoring["projects_scored_count"],
                "priority_counts": sales_scoring["priority_counts"],
            },
            "persistence": persistence,
        }
    except Exception as exc:
        finish_search_run(
            search_run_id,
            status="failed",
            metadata_patch={
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
                "pipeline_version": "quality-v4",
            },
        )
        raise
