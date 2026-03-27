from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.ops.services.escalation_policy_service import (
    EscalationPolicyService,
    EscalationPolicyValidationError,
)
from cockpit.ops.models.escalation import EscalationPolicy, EscalationStep
from cockpit.ops.repositories import (
    EscalationPolicyRepository,
    EscalationStepRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import EscalationTargetKind


def _build_service(store: SQLiteStore) -> EscalationPolicyService:
    return EscalationPolicyService(
        policy_repository=EscalationPolicyRepository(store),
        step_repository=EscalationStepRepository(store),
    )


class EscalationPolicyServiceTests(unittest.TestCase):
    def test_rejects_non_contiguous_step_indexes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = _build_service(store)

            with self.assertRaises(EscalationPolicyValidationError):
                service.save_policy(
                    EscalationPolicy(id="epc-1", name="Default"),
                    steps=(
                        EscalationStep(
                            id="est-1",
                            policy_id="epc-1",
                            step_index=0,
                            target_kind=EscalationTargetKind.TEAM,
                            target_ref="team-1",
                        ),
                        EscalationStep(
                            id="est-2",
                            policy_id="epc-1",
                            step_index=2,
                            target_kind=EscalationTargetKind.PERSON,
                            target_ref="opr-1",
                        ),
                    ),
                )

    def test_calculates_deadlines_and_repeat_times(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = _build_service(store)
            detail = service.save_policy(
                EscalationPolicy(
                    id="epc-1",
                    name="Default",
                    default_ack_timeout_seconds=600,
                    default_repeat_page_seconds=120,
                    max_repeat_pages=3,
                ),
                steps=(
                    EscalationStep(
                        id="est-1",
                        policy_id="epc-1",
                        step_index=0,
                        target_kind=EscalationTargetKind.TEAM,
                        target_ref="team-1",
                    ),
                ),
            )
            effective_at = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
            step = detail.steps[0]

            self.assertEqual(
                service.ack_deadline_for(
                    policy=detail.policy,
                    step=step,
                    effective_at=effective_at,
                ),
                datetime(2026, 3, 24, 12, 10, tzinfo=UTC),
            )
            self.assertEqual(
                service.next_repeat_at(
                    policy=detail.policy,
                    step=step,
                    effective_at=effective_at,
                ),
                datetime(2026, 3, 24, 12, 2, tzinfo=UTC),
            )
            self.assertEqual(
                service.max_repeat_pages(policy=detail.policy, step=step), 3
            )


if __name__ == "__main__":
    unittest.main()
