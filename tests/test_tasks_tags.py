"""Unit tests for task and tag tools."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from morgenmcp.models import (
    MorgenAPIError,
    Tag,
    Task,
    TaskCreateRequest,
    TaskMoveRequest,
    TaskRelation,
    TaskUpdateRequest,
)
from morgenmcp.tools.id_registry import clear_registry, register_id
from morgenmcp.tools.tags import create_tag, delete_tag, list_tags, update_tag
from morgenmcp.tools.tasks import (
    batch_delete_tasks,
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    move_task,
    reopen_task,
    update_task,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def mock_task_client():
    with patch("morgenmcp.tools.tasks.get_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_tag_client():
    with patch("morgenmcp.tools.tags.get_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
def sample_task():
    return Task(
        id="task_real_id_001",
        account_id="acc_real_id_001",
        integration_id="morgen",
        task_list_id="default",
        title="Review report",
        description="Q4 review",
        due="2026-05-01T17:00:00",
        time_zone="Europe/Berlin",
        priority=1,
        progress="needs-action",
        position=0,
        tags=["tag_real_id_001", "tag_real_id_002"],
    )


@pytest.fixture
def sample_tag():
    return Tag(
        id="550e8400-e29b-41d4-a716-446655440000",
        name="Work",
        color="#A8D5BA",
        updated="2026-04-15T10:30:00Z",
    )


class TestListTasks:
    async def test_list_tasks_returns_virtual_ids(self, mock_task_client, sample_task):
        mock_task_client.list_tasks.return_value = [sample_task]
        result = await list_tasks()
        assert result["count"] == 1
        assert len(result["tasks"][0]["id"]) == 7
        assert result["tasks"][0]["title"] == "Review report"
        # tags virtualized
        assert all(len(t) == 7 for t in result["tasks"][0]["tags"])

    async def test_list_tasks_passes_filter_args(self, mock_task_client):
        mock_task_client.list_tasks.return_value = []
        await list_tasks(limit=50, updated_after="2026-04-01T00:00:00Z")
        mock_task_client.list_tasks.assert_awaited_once_with(
            limit=50, updated_after="2026-04-01T00:00:00Z"
        )

    async def test_list_tasks_rejects_bad_limit(self, mock_task_client):
        with pytest.raises(ToolError, match="limit must be"):
            await list_tasks(limit=0)
        with pytest.raises(ToolError, match="limit must be"):
            await list_tasks(limit=101)

    async def test_list_tasks_api_error(self, mock_task_client):
        mock_task_client.list_tasks.side_effect = MorgenAPIError(
            "nope", status_code=500
        )
        with pytest.raises(ToolError, match="API error"):
            await list_tasks()


class TestGetTask:
    async def test_get_task_resolves_virtual(self, mock_task_client, sample_task):
        virtual = register_id(sample_task.id)
        mock_task_client.get_task.return_value = sample_task

        result = await get_task(virtual)
        mock_task_client.get_task.assert_awaited_once_with(sample_task.id)
        assert result["task"]["id"] == virtual


class TestCreateTask:
    async def test_create_task_returns_virtual_id(self, mock_task_client):
        mock_task_client.create_task.return_value = "new_real_id"
        result = await create_task(title="Hello")
        assert result["success"] is True
        assert len(result["task"]["id"]) == 7

    async def test_create_task_validates_title(self, mock_task_client):
        with pytest.raises(ToolError, match="title cannot be empty"):
            await create_task(title="   ")

    async def test_create_task_validates_priority(self, mock_task_client):
        with pytest.raises(ToolError, match="priority"):
            await create_task(title="X", priority=15)

    async def test_create_task_validates_progress(self, mock_task_client):
        with pytest.raises(ToolError, match="Invalid progress"):
            # Mypy/pyright wouldn't allow this Literal value but the runtime check should
            await create_task(title="X", progress="bogus")  # type: ignore[arg-type]

    async def test_create_task_resolves_parent(self, mock_task_client):
        parent_real = "parent_real_001"
        parent_virtual = register_id(parent_real)
        mock_task_client.create_task.return_value = "new_id"

        await create_task(title="Sub", parent_task_id=parent_virtual)
        sent: TaskCreateRequest = mock_task_client.create_task.call_args.args[0]
        assert sent.related_to is not None
        assert parent_real in sent.related_to
        assert sent.related_to[parent_real].relation == {"parent": True}

    async def test_create_task_resolves_tags(self, mock_task_client):
        tag_virtual = register_id("real_tag_id")
        mock_task_client.create_task.return_value = "new_id"
        await create_task(title="X", tag_ids=[tag_virtual])
        sent: TaskCreateRequest = mock_task_client.create_task.call_args.args[0]
        assert sent.tags == ["real_tag_id"]


class TestUpdateTask:
    async def test_update_task_resolves_virtual(self, mock_task_client):
        virtual = register_id("task_real_xyz")
        await update_task(virtual, title="New title")
        sent: TaskUpdateRequest = mock_task_client.update_task.call_args.args[0]
        assert sent.id == "task_real_xyz"
        assert sent.title == "New title"

    async def test_update_task_validates_priority(self, mock_task_client):
        virtual = register_id("task_xyz")
        with pytest.raises(ToolError, match="priority"):
            await update_task(virtual, priority=-1)

    async def test_update_task_resolves_tag_ids(self, mock_task_client):
        task_virtual = register_id("task_xyz")
        tag_virtual = register_id("tag_real_id")
        await update_task(task_virtual, tag_ids=[tag_virtual])
        sent: TaskUpdateRequest = mock_task_client.update_task.call_args.args[0]
        assert sent.tags == ["tag_real_id"]


class TestMoveTask:
    async def test_move_to_root(self, mock_task_client):
        v = register_id("task_a")
        await move_task(v, move_to_root=True)
        sent: TaskMoveRequest = mock_task_client.move_task.call_args.args[0]
        # parent_id explicitly serialized as null
        dumped = sent.model_dump(by_alias=True)
        assert dumped["parentId"] is None

    async def test_move_to_first(self, mock_task_client):
        v = register_id("task_a")
        await move_task(v, move_to_first=True)
        sent: TaskMoveRequest = mock_task_client.move_task.call_args.args[0]
        dumped = sent.model_dump(by_alias=True)
        assert dumped["previousId"] is None

    async def test_move_after(self, mock_task_client):
        a = register_id("task_a")
        b = register_id("task_b")
        await move_task(a, previous_task_id=b)
        sent: TaskMoveRequest = mock_task_client.move_task.call_args.args[0]
        assert sent.previous_id == "task_b"

    async def test_move_under_parent(self, mock_task_client):
        a = register_id("task_a")
        p = register_id("task_p")
        await move_task(a, parent_task_id=p)
        sent: TaskMoveRequest = mock_task_client.move_task.call_args.args[0]
        assert sent.parent_id == "task_p"

    async def test_move_requires_target(self, mock_task_client):
        v = register_id("task_a")
        with pytest.raises(ToolError, match="needs at least one"):
            await move_task(v)

    async def test_move_conflict_first_and_previous(self, mock_task_client):
        v = register_id("task_a")
        u = register_id("task_b")
        with pytest.raises(ToolError, match="conflicts"):
            await move_task(v, move_to_first=True, previous_task_id=u)


class TestCompleteAndReopen:
    async def test_complete_task(self, mock_task_client):
        v = register_id("task_x")
        result = await complete_task(v)
        assert result["success"] is True
        sent = mock_task_client.close_task.call_args.args[0]
        assert sent.id == "task_x"
        assert sent.occurrence_start is None

    async def test_complete_with_occurrence(self, mock_task_client):
        v = register_id("task_x")
        await complete_task(v, occurrence_start="2026-05-01T10:00:00")
        sent = mock_task_client.close_task.call_args.args[0]
        assert sent.occurrence_start == "2026-05-01T10:00:00"

    async def test_complete_validates_occurrence(self, mock_task_client):
        v = register_id("task_x")
        with pytest.raises(ToolError, match="Validation error"):
            await complete_task(v, occurrence_start="bad")

    async def test_reopen_task(self, mock_task_client):
        v = register_id("task_x")
        await reopen_task(v)
        sent = mock_task_client.reopen_task.call_args.args[0]
        assert sent.id == "task_x"


class TestDeleteTask:
    async def test_delete_task(self, mock_task_client):
        v = register_id("task_x")
        await delete_task(v)
        sent = mock_task_client.delete_task.call_args.args[0]
        assert sent.id == "task_x"

    async def test_batch_delete_partial_failure(self, mock_task_client):
        good = register_id("task_good")
        bad = register_id("task_bad")

        async def _delete(req):
            if req.id == "task_bad":
                raise MorgenAPIError("boom", status_code=500)

        mock_task_client.delete_task.side_effect = _delete

        result = await batch_delete_tasks([good, bad])
        assert good in result["deleted"]
        assert any(f["id"] == bad for f in result["failed"])

    async def test_batch_delete_empty(self, mock_task_client):
        result = await batch_delete_tasks([])
        assert result["deleted"] == []
        assert result["failed"] == []

    async def test_batch_delete_unresolvable_id(self, mock_task_client):
        result = await batch_delete_tasks(["xxxxxxx"])
        assert result["deleted"] == []
        assert result["failed"][0]["id"] == "xxxxxxx"


class TestListTags:
    async def test_list_tags(self, mock_tag_client, sample_tag):
        mock_tag_client.list_tags.return_value = [sample_tag]
        result = await list_tags()
        assert result["count"] == 1
        assert result["tags"][0]["name"] == "Work"
        assert len(result["tags"][0]["id"]) == 7

    async def test_list_tags_with_limit(self, mock_tag_client):
        mock_tag_client.list_tags.return_value = []
        await list_tags(updated_after="2026-04-01T00:00:00Z", limit=10)
        mock_tag_client.list_tags.assert_awaited_once_with(
            limit=10, updated_after="2026-04-01T00:00:00Z"
        )

    async def test_list_tags_rejects_bad_limit(self, mock_tag_client):
        with pytest.raises(ToolError, match="limit"):
            await list_tags(limit=0)


class TestCreateTag:
    async def test_create_tag(self, mock_tag_client, sample_tag):
        mock_tag_client.create_tag.return_value = sample_tag
        result = await create_tag(name="Work", color="#A8D5BA")
        assert result["success"] is True
        assert len(result["tag"]["id"]) == 7

    async def test_create_tag_empty_name(self, mock_tag_client):
        with pytest.raises(ToolError, match="name"):
            await create_tag(name="")

    async def test_create_tag_bad_color(self, mock_tag_client):
        with pytest.raises(ToolError, match="color"):
            await create_tag(name="X", color="not-a-color")


class TestUpdateTag:
    async def test_update_tag(self, mock_tag_client):
        v = register_id("tag_real_id")
        await update_tag(v, name="New Name")
        sent = mock_tag_client.update_tag.call_args.args[0]
        assert sent.id == "tag_real_id"
        assert sent.name == "New Name"

    async def test_update_tag_requires_field(self, mock_tag_client):
        v = register_id("tag_real_id")
        with pytest.raises(ToolError, match="At least one"):
            await update_tag(v)

    async def test_update_tag_bad_color(self, mock_tag_client):
        v = register_id("tag_real_id")
        with pytest.raises(ToolError, match="color"):
            await update_tag(v, color="oops")


class TestDeleteTag:
    async def test_delete_tag(self, mock_tag_client):
        v = register_id("tag_real_id")
        await delete_tag(v)
        sent = mock_tag_client.delete_tag.call_args.args[0]
        assert sent.id == "tag_real_id"


class TestRelationModel:
    """Defensive — TaskRelation is constructed in tools, ensure shape is right."""

    def test_relation_dump(self):
        rel = TaskRelation(relation={"parent": True})
        dumped = rel.model_dump(by_alias=True)
        assert dumped["@type"] == "Relation"
        assert dumped["relation"] == {"parent": True}
