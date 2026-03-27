import unittest

from cockpit.core.enums import SessionTargetKind, TargetRiskLevel
from cockpit.core.risk import classify_target_risk, risk_presentation


class TargetRiskTests(unittest.TestCase):
    def test_local_workspace_defaults_to_dev_risk(self) -> None:
        level = classify_target_risk(
            target_kind=SessionTargetKind.LOCAL,
            target_ref=None,
            workspace_name="cockpit",
            workspace_root="/home/dev/cockpit",
        )

        self.assertIs(level, TargetRiskLevel.DEV)

    def test_remote_workspace_defaults_to_stage_risk(self) -> None:
        level = classify_target_risk(
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
            workspace_name="app",
            workspace_root="/srv/app",
        )

        self.assertIs(level, TargetRiskLevel.STAGE)

    def test_prod_markers_override_target_defaults(self) -> None:
        level = classify_target_risk(
            target_kind=SessionTargetKind.SSH,
            target_ref="prod@example.com",
            workspace_name="payments-prod",
            workspace_root="/srv/payments",
        )

        self.assertIs(level, TargetRiskLevel.PROD)
        self.assertEqual(risk_presentation(level).label, "PROD")


if __name__ == "__main__":
    unittest.main()
