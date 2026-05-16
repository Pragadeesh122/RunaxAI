import uuid

import pytest
from sqlalchemy import func, select

from api import projects as projects_module
from database.models import ChatMessage, ChatSession, Document, Project


@pytest.mark.asyncio
async def test_project_search_returns_results_without_mutating_chat_state(
    async_client,
    session_factory,
    test_user,
    monkeypatch,
):
    project_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    async with session_factory() as session:
        session.add(
            Project(
                id=project_id,
                user_id=test_user.id,
                name="Searchable Project",
            )
        )
        session.add(
            Document(
                id=str(uuid.uuid4()),
                project_id=project_id,
                filename="Guide.pdf",
                file_type="pdf",
                file_size=1024,
                chunk_count=12,
                status="ready",
            )
        )
        session.add(
            ChatSession(
                id=session_id,
                user_id=test_user.id,
                project_id=project_id,
                title="Existing chat",
            )
        )
        session.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                chat_session_id=session_id,
                role="user",
                content="Already here",
                tool_calls=[],
                metadata_={},
            )
        )
        await session.commit()

    monkeypatch.setattr(
        projects_module,
        "retrieve",
        lambda **_: (
            [
                {
                    "id": "chunk-1",
                    "text": "Important searchable project snippet for testing.",
                    "source": "Guide.pdf",
                    "page": 4,
                    "score": 0.88,
                    "document_id": "doc-1",
                }
            ],
            {"cache_hit": False},
        ),
    )

    async with session_factory() as session:
        chat_sessions_before = await session.scalar(select(func.count()).select_from(ChatSession))
        chat_messages_before = await session.scalar(select(func.count()).select_from(ChatMessage))

    response = await async_client.post(
        f"/projects/{project_id}/search",
        json={"query": "searchable snippet", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["snippet"] == "Important searchable project snippet for testing."
    assert payload["results"][0]["source"] == "Guide.pdf"
    assert payload["results"][0]["page"] == 4

    async with session_factory() as session:
        chat_sessions_after = await session.scalar(select(func.count()).select_from(ChatSession))
        chat_messages_after = await session.scalar(select(func.count()).select_from(ChatMessage))

    assert chat_sessions_before == chat_sessions_after
    assert chat_messages_before == chat_messages_after
