from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.llm import LLMError, LLMRouter, OllamaLLMClient, StubLLMRouter
from app.main import create_app
from app.models import AgentModelConfig, ModelProvider
from app.repositories import InMemoryStateRepository


@pytest.fixture
def llm() -> StubLLMRouter:
    return StubLLMRouter(
        [
            {
                "reply": "The plan is ready for approval.",
                "requirements_patch": {
                    "source": {"type": "postgres", "table": "orders"},
                    "sink": {"type": "mongodb", "collection": "orders"},
                    "scale": {"events_per_second": 100},
                },
                "plan": {
                    "summary": "Postgres orders to MongoDB",
                    "topics": [
                        {
                            "name": "orders.raw",
                            "partitions": 3,
                            "replication_factor": 1,
                        }
                    ],
                    "connectors": [{"type": "source"}, {"type": "sink"}],
                    "ksqldb_objects": [],
                    "dependencies": [],
                    "deployment_order": ["topics", "connectors"],
                },
                "open_questions": [],
                "ready_for_approval": True,
            },
            {
                "connector_configs": [
                    {
                        "name": "orders-source",
                        "config": {
                            "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
                            "topic.prefix": "orders.",
                        },
                    }
                ],
                "dlq_configs": [],
                "warnings": [],
            },
            {"statements": [], "objects": [], "warnings": []},
            {"edge_cases": [], "summary": "No critical edge cases."},
            {"findings": [], "approved": True, "summary": "Approved."},
        ]
    )


def test_llm_router_allows_missing_openai_key_for_unused_provider() -> None:
    LLMRouter(Settings(openai_api_key=None))


@pytest.mark.asyncio
async def test_llm_router_reports_missing_openai_key_when_openai_is_selected() -> None:
    router = LLMRouter(Settings(openai_api_key=None))

    with pytest.raises(LLMError, match="OpenAI provider requires"):
        await router.generate_json(
            AgentModelConfig(provider=ModelProvider.OPENAI, model="gpt-5-mini"),
            "Return JSON.",
            "Return {}.",
        )


@pytest.mark.asyncio
async def test_ollama_client_reports_unreachable_server() -> None:
    client = OllamaLLMClient(
        Settings(ollama_url="http://127.0.0.1:9", http_timeout_seconds=0.1)
    )

    with pytest.raises(LLMError, match="Ollama is not reachable"):
        await client.generate_json(
            AgentModelConfig(provider=ModelProvider.OLLAMA),
            "Return JSON.",
            "Return {}.",
        )


@pytest.mark.asyncio
async def test_create_session_defaults_to_ollama_without_openai_key(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    app = create_app(
        settings=Settings(
            deployment_root=tmp_path,
            openai_api_key=None,
            ollama_model="llama3.1:8b",
        ),
        repository=InMemoryStateRepository(),
        llm=llm,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/sessions", json={"pipeline_name": "orders"})

    assert response.status_code == 201
    planner_config = response.json()["config"]["planner"]
    assert planner_config["provider"] == "ollama"
    assert planner_config["model"] == "llama3.1:8b"


@pytest.mark.asyncio
async def test_create_session_defaults_to_openai_with_openai_key(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    app = create_app(
        settings=Settings(
            deployment_root=tmp_path,
            openai_api_key="test-key",
            openai_model="gpt-test",
        ),
        repository=InMemoryStateRepository(),
        llm=llm,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/sessions", json={"pipeline_name": "orders"})

    assert response.status_code == 201
    planner_config = response.json()["config"]["planner"]
    assert planner_config["provider"] == "openai"
    assert planner_config["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_create_session_preserves_explicit_config(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    app = create_app(
        settings=Settings(deployment_root=tmp_path, openai_api_key="test-key"),
        repository=InMemoryStateRepository(),
        llm=llm,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/sessions",
                json={
                    "pipeline_name": "orders",
                    "config": {
                        "planner": {
                            "provider": "ollama",
                            "model": "custom-ollama",
                        }
                    },
                },
            )

    assert response.status_code == 201
    planner_config = response.json()["config"]["planner"]
    assert planner_config["provider"] == "ollama"
    assert planner_config["model"] == "custom-ollama"


@pytest.mark.asyncio
async def test_list_sessions_returns_existing_sessions(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    app = create_app(
        settings=Settings(deployment_root=tmp_path),
        repository=InMemoryStateRepository(),
        llm=llm,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/sessions", json={"pipeline_name": "first"})
            second = await client.post("/sessions", json={"pipeline_name": "second"})
            listed = await client.get("/sessions?limit=10")

    assert first.status_code == 201
    assert second.status_code == 201
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert [session["pipeline_name"] for session in sessions[:2]] == [
        "second",
        "first",
    ]


@pytest.mark.asyncio
async def test_session_workflow_generates_deployment_package(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    repository = InMemoryStateRepository()
    settings = Settings(deployment_root=tmp_path)
    app = create_app(settings=settings, repository=repository, llm=llm)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            created = await client.post(
                "/sessions", json={"pipeline_name": "orders-pipeline"}
            )
            assert created.status_code == 201
            session_id = created.json()["session_id"]

            planned = await client.post(
                f"/sessions/{session_id}/message",
                json={"message": "Move Postgres orders into MongoDB."},
            )
            assert planned.status_code == 200
            assert planned.json()["session"]["status"] == "awaiting_approval"

            approved = await client.post(
                f"/sessions/{session_id}/approve", json={"approved": True}
            )
            assert approved.status_code == 200
            assert approved.json()["session"]["status"] == "ready"
            assert len(approved.json()["tasks"]) == 4

            deployed = await client.post(
                f"/sessions/{session_id}/deploy", json={"mode": "package"}
            )
            assert deployed.status_code == 200
            package_path = Path(
                deployed.json()["whiteboard"]["deployment_status"]["package_path"]
            )
            assert (package_path / "create_topics.sh").is_file()
            assert (package_path / "deploy_connectors.sh").is_file()
            assert (package_path / "deploy_ksql.sh").is_file()
            assert (package_path / "rollback.sh").is_file()
            assert (package_path / "connector_configs" / "orders-source.json").is_file()

            whiteboard = await client.get(f"/sessions/{session_id}/whiteboard")
            assert whiteboard.status_code == 200
            assert whiteboard.json()["topics"][0]["name"] == "orders.raw"

            events = await client.get(f"/sessions/{session_id}/events")
            assert events.status_code == 200
            assert any(
                event["type"] == "deployment" for event in events.json()["events"]
            )


@pytest.mark.asyncio
async def test_missing_session_returns_404(llm: StubLLMRouter) -> None:
    app = create_app(
        settings=Settings(),
        repository=InMemoryStateRepository(),
        llm=llm,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/sessions/missing")
    assert response.status_code == 404
