import asyncio

from app.worker import celery_app
from app.services.tavily_search import run_default_discovery


@celery_app.task(name="discovery.tavily_test")
def tavily_discovery_test():
    return asyncio.run(
        run_default_discovery(
            max_results_per_query=8,
            days_back=180,
        )
    )
