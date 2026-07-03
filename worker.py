import logging
import os

from arq.connections import RedisSettings
from dotenv import load_dotenv

# Import Tasks
from tasks.document_tasks import process_document_task
from tasks.memory_tasks import persist_memories_task, refresh_rolling_summary_task

# Ensure environment is loaded
load_dotenv()

logger = logging.getLogger("worker")

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", "6379"))
redis_password = os.getenv("REDIS_PASSWORD", None)


async def on_startup(ctx):
    """Give the worker the same observability the API has.

    - structured JSON logs (LOG_FORMAT already arrives via the shared ConfigMap)
    - OTel tracing as its own service so upload->ingestion traces continue here
    - a Prometheus endpoint for agenticrag_worker_* task metrics
    """
    from observability.logging_config import setup_logging
    from observability.tracing import setup_tracing

    setup_logging()
    setup_tracing(service_name=os.getenv("OTEL_SERVICE_NAME", "agenticrag-worker"))

    try:
        from prometheus_client import start_http_server

        port = int(os.getenv("WORKER_METRICS_PORT", "9100"))
        start_http_server(port)
        logger.info("worker metrics server listening on :%d", port)
    except OSError as exc:
        # Port already bound (e.g. two workers in one pod) — metrics from the
        # first process still flow; log rather than kill the worker.
        logger.warning("worker metrics server not started: %s", exc)


async def on_shutdown(ctx):
    logger.info("worker shutting down")


# Setup ARQ Redis Settings
WorkerSettings = type(
    "WorkerSettings",
    (),
    {
        "redis_settings": RedisSettings(host=redis_host, port=redis_port, password=redis_password),
        "functions": [
            process_document_task,
            persist_memories_task,
            refresh_rolling_summary_task,
        ],
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
    }
)
