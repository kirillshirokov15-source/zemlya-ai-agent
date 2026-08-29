import asyncio

from app.worker import celery_app
from app.services.tavily_search import run_default_discovery
from app.services.qualification import qualify_results
from app.services.project_dedup import deduplicate_qualified_projects


@celery_app.task(name="qualification.discovery_test")
def qualification_discovery_test():
    discovery = asyncio.run(
        run_default_discovery(max_results_per_query=8, days_back=180)
    )

    qualification = qualify_results(
        discovery["results"],
        max_llm_items=20,
    )

    deduplication = deduplicate_qualified_projects(
        qualification["qualified"]
    )

    return {
        "discovery": {
            "queries_used": discovery["queries_used"],
            "unique_results": discovery["unique_results"],
        },
        "qualification": qualification,
        "deduplication": deduplication,
    }
