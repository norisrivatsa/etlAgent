from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.api import router
from app.config import Settings, get_settings
from app.llm import LLMRouter
from app.repositories import MongoStateRepository, StateRepository
from app.runtime import RuntimeManager
from app.services import SessionService
from app.tools import create_tool_registry


def create_app(
    settings: Settings | None = None,
    repository: StateRepository | None = None,
    llm: LLMRouter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    mongo_client: AsyncIOMotorClient | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal mongo_client, repository
        if repository is None:
            mongo_client = AsyncIOMotorClient(settings.mongo_uri)
            mongo_repository = MongoStateRepository(
                mongo_client[settings.mongo_database]
            )
            await mongo_repository.ensure_indexes()
            repository = mongo_repository
        tools = create_tool_registry(repository, settings)
        runtimes = RuntimeManager(repository, llm or LLMRouter(settings), tools)
        app.state.session_service = SessionService(repository, runtimes, settings)
        yield
        await runtimes.close()
        if mongo_client:
            mongo_client.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
