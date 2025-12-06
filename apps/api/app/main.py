from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Reframe API", version="0.1.0")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
