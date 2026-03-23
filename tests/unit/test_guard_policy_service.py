from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.domain.models.policy import GuardContext
from cockpit.infrastructure.persistence.ops_repositories import GuardDecisionRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    TargetRiskLevel,
)


class GuardPolicyServiceTests(unittest.TestCase):
    def test_requires_confirmation_for_docker_mutation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = GuardPolicyService(GuardDecisionRepository(store))

            decision = service.evaluate(
                GuardContext(
                    command_id="cmd-1",
                    action_kind=GuardActionKind.DOCKER_STOP,
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    target_risk=TargetRiskLevel.STAGE,
                    description="docker stop for web",
                )
            )

            self.assertEqual(decision.outcome, GuardDecisionOutcome.REQUIRE_CONFIRMATION)
            self.assertTrue(decision.requires_confirmation)
            self.assertEqual(len(GuardDecisionRepository(store).list_recent()), 1)

    def test_blocks_destructive_db_operation_on_prod(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = GuardPolicyService(GuardDecisionRepository(store))

            decision = service.evaluate(
                GuardContext(
                    command_id="cmd-2",
                    action_kind=GuardActionKind.DB_DESTRUCTIVE,
                    component_kind=ComponentKind.DATASOURCE,
                    target_risk=TargetRiskLevel.PROD,
                    description="drop schema public",
                )
            )

            self.assertEqual(decision.outcome, GuardDecisionOutcome.BLOCK)

    def test_allows_http_read_requests(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = GuardPolicyService(GuardDecisionRepository(store))

            decision = service.evaluate(
                GuardContext(
                    command_id="cmd-3",
                    action_kind=GuardActionKind.HTTP_READ,
                    component_kind=ComponentKind.HTTP_REQUEST,
                    target_risk=TargetRiskLevel.PROD,
                    description="GET https://example.com/health",
                    metadata={"method": "GET"},
                )
            )

            self.assertEqual(decision.outcome, GuardDecisionOutcome.ALLOW)


if __name__ == "__main__":
    unittest.main()
