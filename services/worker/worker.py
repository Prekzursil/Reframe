import os
from celery import Celery


BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", BROKER_URL)

celery_app = Celery(
    "reframe_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
)

celery_app.conf.task_default_queue = "default"


@celery_app.task(name="tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="tasks.echo")
def echo(message: str) -> str:
    return message


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
