import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pii_shield.agent import PIIAgent
from pii_shield.agent.demo_tools import demo_registry
from pii_shield.api.errors import register_error_handlers
from pii_shield.api.routes import router
from pii_shield.config import get_settings
from pii_shield.pipeline import PIIShield
from pii_shield.providers import build_provider
from pii_shield.storage import SessionStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "GROQ_API_KEY": settings.groq_api_key,
            "GEMINI_API_KEY": settings.gemini_api_key,
            "ENCRYPTION_KEY": settings.encryption_key,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
    
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Built once: loading the spaCy model takes seconds, so never per request.
    store = SessionStore.from_settings(settings)
    app.state.settings = settings
    app.state.store = store
    app.state.agent = PIIAgent(
        PIIShield.from_settings(settings),
        build_provider(settings),
        demo_registry(),
        max_tool_rounds=settings.agent_max_tool_rounds,
    )
    logger.info("PII Shield ready (environment=%s)", settings.environment)
    try:
        yield
    finally:
        await store.close()


def create_app(use_lifespan: bool = True) -> FastAPI:
    app = FastAPI(
        title="PII Shield",
        version="0.1.0",
        description="Privacy-preserving middleware: the LLM never sees raw PII.",
        lifespan=lifespan if use_lifespan else None,
    )
    register_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
