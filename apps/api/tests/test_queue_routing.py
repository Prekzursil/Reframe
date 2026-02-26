from __future__ import annotations


def test_resolve_task_queue_routes_caption_cuda_to_gpu(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_GPU_QUEUE", "true")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_GPU", "gpu")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_CPU", "cpu")

    import app.api as api_module

    queue = api_module._resolve_task_queue(
        "tasks.generate_captions",
        "job-id",
        "asset-id",
        {"backend": "faster_whisper", "device": "cuda"},
    )
    assert queue == "gpu"


def test_resolve_task_queue_falls_back_to_cpu_when_gpu_disabled(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_GPU_QUEUE", "false")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_CPU", "cpu")

    import app.api as api_module

    queue = api_module._resolve_task_queue(
        "tasks.generate_captions",
        "job-id",
        "asset-id",
        {"backend": "faster_whisper", "device": "cuda"},
    )
    assert queue == "cpu"


def test_resolve_task_queue_routes_merge_to_cpu(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_GPU_QUEUE", "true")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_CPU", "cpu")

    import app.api as api_module

    queue = api_module._resolve_task_queue("tasks.merge_video_audio", "job-id", "video-id", "audio-id", {"offset": 0})
    assert queue == "cpu"
