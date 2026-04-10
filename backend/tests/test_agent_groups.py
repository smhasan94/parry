"""Tests for agent groups — model construction and service schemas."""

import uuid

from app.db.models import Agent, AgentGroup


class TestAgentGroupModel:
    def test_construction(self) -> None:
        g = AgentGroup(
            org_id=uuid.uuid4(),
            name="Production",
            description="Customer-facing agents",
        )
        assert g.name == "Production"
        assert g.description == "Customer-facing agents"

    def test_name_required(self) -> None:
        g = AgentGroup(org_id=uuid.uuid4(), name="Test")
        assert g.name == "Test"
        assert g.description is None


class TestAgentGroupId:
    def test_agent_has_group_id(self) -> None:
        a = Agent(
            org_id=uuid.uuid4(),
            name="test-agent",
            group_id=uuid.uuid4(),
        )
        assert a.group_id is not None

    def test_agent_group_id_nullable(self) -> None:
        a = Agent(org_id=uuid.uuid4(), name="test-agent")
        assert a.group_id is None

    def test_agent_group_id_clearable(self) -> None:
        gid = uuid.uuid4()
        a = Agent(org_id=uuid.uuid4(), name="test-agent", group_id=gid)
        assert a.group_id == gid
        a.group_id = None
        assert a.group_id is None


class TestGroupSchemas:
    def test_group_create_request(self) -> None:
        from app.api.v1.agent_groups import GroupCreateRequest

        req = GroupCreateRequest(name="Test Group")
        assert req.name == "Test Group"
        assert req.description is None

    def test_group_create_with_description(self) -> None:
        from app.api.v1.agent_groups import GroupCreateRequest

        req = GroupCreateRequest(name="Prod", description="Production agents")
        assert req.description == "Production agents"

    def test_group_update_request(self) -> None:
        from app.api.v1.agent_groups import GroupUpdateRequest

        req = GroupUpdateRequest(name="New Name")
        assert req.name == "New Name"
        assert req.description is None

    def test_assign_group_request(self) -> None:
        from app.api.v1.agent_groups import AssignGroupRequest

        gid = uuid.uuid4()
        req = AssignGroupRequest(group_id=gid)
        assert req.group_id == gid

    def test_assign_group_null(self) -> None:
        from app.api.v1.agent_groups import AssignGroupRequest

        req = AssignGroupRequest(group_id=None)
        assert req.group_id is None

    def test_group_response(self) -> None:
        from app.api.v1.agent_groups import GroupResponse

        resp = GroupResponse(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            name="Test",
            description=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
            agent_count=5,
        )
        assert resp.agent_count == 5
