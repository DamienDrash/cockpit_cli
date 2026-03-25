#!/usr/bin/env bash
set -euo pipefail

echo "Running smoke tests..."

# Check if cockpit-cli can be imported and shows help
python3 -m cockpit.app --help > /dev/null

echo "Import and --help: OK"

# Check if PanelStateChanged can be instantiated with all fields
python3 -c "
from cockpit.domain.events.runtime_events import PanelStateChanged
event = PanelStateChanged(
    panel_id='test',
    panel_type='test',
    snapshot={},
    config={}
)
"

echo "PanelStateChanged contract: OK"

echo "Smoke tests passed!"
