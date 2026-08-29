import asyncio

from app.worker import celery_app
from app.services.tavily_search import run_default_discovery
from app.services.project_extraction import extract_atomic_projects
from app.services.qualification import qualify_results
from app.services.project_dedup import deduplicate_qualified_projects
from app.services.lead_scoring import score_projects


@celery_app.task(name="qualification.discovery_test")
def qualification_discovery_test():
    discovery = asyncio.run(
        run_default_discovery(max_results_per_query=8, days_back=180)
    )

    extraction = extract_atomic_projects(
        discovery["results"],
        max_llm_sources=12,
    )

    qualification = qualify_results(
        extraction["results"],
        max_llm_items=20,
    )

    deduplication = deduplicate_qualified_projects(
        qualification["qualified"]
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
        "qualification": qualification,
        "deduplication": deduplication,
        "scoring": scoring,
    }
