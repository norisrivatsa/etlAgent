from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.llm import LLMError, LLMRouter, OllamaLLMClient, StubLLMRouter
from app.main import create_app
from app.models import AgentModelConfig, ModelProvider
from app.repositories import InMemoryStateRepository


def _responses() -> list[dict]:
    """Planner -> Connect -> Planner -> KsqlDB -> Planner, in the order the
    orchestrator's synchronous phase loop consumes them."""
    return [
        {
            "reply_to_user": "Got it — generating the orders connector.",
            "requirements_patch": {
                "source": {"type": "postgres", "table": "orders"},
                "sink": {"type": "mongodb", "collection": "orders"},
            },
            "next_steps": [
                {
                    "agent": "connect",
                    "instruction": "Generate the orders connector",
                    "context_slice": {"table": "orders"},
                    "phase": "connect",
                }
            ],
            "awaiting": "agent:connect",
        },
        {
            "status": "ok",
            "artifacts": [
                {
                    "name": "orders-source",
                    "config": {
                        "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
                        "topic.prefix": "orders.",
                    },
                }
            ],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated orders-source connector",
        },
        {
            "reply_to_user": "Connector approved. Building the ksqlDB pipeline.",
            "requirements_patch": {},
            "next_steps": [
                {
                    "agent": "ksqldb",
                    "instruction": "Design the ksqlDB pipeline",
                    "context_slice": {"topics": ["orders.orders"]},
                    "phase": "ksqldb",
                }
            ],
            "awaiting": "agent:ksqldb",
        },
        {
            "status": "ok",
            "artifacts": [
                {"statement": "CREATE STREAM orders_raw ...;", "layer": "raw"},
            ],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated raw ksqlDB pipeline",
        },
        {
            "reply_to_user": "Pipeline complete and ready to deploy.",
            "requirements_patch": {},
            "next_steps": [],
            "awaiting": "done",
        },
    ]


@pytest.fixture
def llm() -> StubLLMRouter:
    return StubLLMRouter(_responses())


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
async def test_session_workflow_fans_through_connect_then_ksqldb_to_deployment(
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
            assert len(planned.json()["session"]["whiteboard"]["artifacts"]) == 1

            connect_approved = await client.post(
                f"/sessions/{session_id}/approve", json={"approved": True}
            )
            assert connect_approved.status_code == 200
            # committing the connector triggers a fresh Planner call, which
            # immediately dispatches the ksqlDB phase — so we land right back
            # in awaiting_approval, now for ksqldb.
            assert connect_approved.json()["session"]["status"] == "awaiting_approval"

            ksqldb_approved = await client.post(
                f"/sessions/{session_id}/approve", json={"approved": True}
            )
            assert ksqldb_approved.status_code == 200
            assert ksqldb_approved.json()["session"]["status"] == "ready"

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
            assert len(whiteboard.json()["connectors"]) == 1
            assert len(whiteboard.json()["ksqldb_objects"]) == 1

            events = await client.get(f"/sessions/{session_id}/events")
            assert events.status_code == 200
            event_types = [event["type"] for event in events.json()["events"]]
            assert "task" in event_types
            assert "agent_message" in event_types

            chat_messages = await client.get(f"/sessions/{session_id}/chat-messages")
            assert chat_messages.status_code == 200
            roles = [message["role"] for message in chat_messages.json()["messages"]]
            assert "user" in roles
            assert "assistant" in roles

            artifacts_on_disk = list(
                (Path(settings.deployment_root) / session_id / "artifacts").glob("*.json")
            )
            assert len(artifacts_on_disk) == 2  # 1 connector + 1 ksql statement


@pytest.mark.asyncio
async def test_star_message_persists_and_appears_in_chat_messages(
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
            created = await client.post("/sessions", json={"pipeline_name": "orders"})
            session_id = created.json()["session_id"]

            await client.post(
                f"/sessions/{session_id}/message",
                json={"message": "Move Postgres orders into MongoDB."},
            )

            chat = await client.get(f"/sessions/{session_id}/chat-messages")
            messages = chat.json()["messages"]
            assert all(message["starred"] is False for message in messages)
            message_id = messages[0]["message_id"]

            starred = await client.post(
                f"/sessions/{session_id}/chat-messages/{message_id}/star",
                json={"starred": True},
            )
            assert starred.status_code == 200
            assert starred.json()["starred"] is True

            chat_after = await client.get(f"/sessions/{session_id}/chat-messages")
            target = next(
                m for m in chat_after.json()["messages"] if m["message_id"] == message_id
            )
            assert target["starred"] is True

            unstarred = await client.post(
                f"/sessions/{session_id}/chat-messages/{message_id}/star",
                json={"starred": False},
            )
            assert unstarred.json()["starred"] is False

            missing = await client.post(
                f"/sessions/{session_id}/chat-messages/not-a-real-id/star",
                json={"starred": True},
            )
            assert missing.status_code == 404


@pytest.mark.asyncio
async def test_approve_artifact_endpoint_commits_single_artifact(
    tmp_path: Path, llm: StubLLMRouter
) -> None:
    settings = Settings(deployment_root=tmp_path)
    app = create_app(settings=settings, repository=InMemoryStateRepository(), llm=llm)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/sessions", json={"pipeline_name": "orders"})
            session_id = created.json()["session_id"]

            planned = await client.post(
                f"/sessions/{session_id}/message",
                json={"message": "Move Postgres orders into MongoDB."},
            )
            artifact_id = planned.json()["session"]["whiteboard"]["artifacts"][0]["artifact_id"]

            missing = await client.post(
                f"/sessions/{session_id}/artifacts/not-a-real-id/approve",
                json={"approved": True},
            )
            assert missing.status_code == 404

            approved = await client.post(
                f"/sessions/{session_id}/artifacts/{artifact_id}/approve",
                json={"approved": True},
            )
            assert approved.status_code == 200
            artifact = next(
                a
                for a in approved.json()["session"]["whiteboard"]["artifacts"]
                if a["artifact_id"] == artifact_id
            )
            assert artifact["status"] == "committed"

            artifacts_on_disk = list(
                (Path(settings.deployment_root) / session_id / "artifacts").glob("*.json")
            )
            assert len(artifacts_on_disk) == 1  # only the approved connector, not the ksqldb one

            conflict = await client.post(
                f"/sessions/{session_id}/artifacts/{artifact_id}/approve",
                json={"approved": True},
            )
            assert conflict.status_code == 409


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
