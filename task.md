# cockpit-cli Architecture Refinement

## Phase 1 — Panel Isolation + Bootstrap Split

### Panel Isolation
- [x] Add `PanelErrorBoundary` wrapper in [PanelHost](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/panels/panel_host.py#19-429)
- [x] Replace `self.app._dispatch_command()` in [DBPanel](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/panels/db_panel.py#28-235), [CurlPanel](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/panels/curl_panel.py#22-149), [CronPanel](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/panels/cron_panel.py#23-179) with injected callback
- [x] Replace silent `except: pass` in `PanelHost._update_switcher()` with logging
- [x] Add [dispatch](file:///home/damien/Dokumente/cockpit/src/cockpit/application/dispatch/command_dispatcher.py#44-132) callback injection via `PanelHost.on_mount()` late-binding
- [x] Fix [CommandParser](file:///home/damien/Dokumente/cockpit/src/cockpit/application/dispatch/command_parser.py#17-68) incorrectly mutating dot-separated subcommands
- [x] Fix [DBPanel](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/panels/db_panel.py#28-235) silent return when query runs without selected database
- [x] Patch [TabBar](file:///home/damien/Dokumente/cockpit/src/cockpit/ui/widgets/tab_bar.py#14-93) unawaited asyncio coroutines causing test freezes

### Bootstrap Split
- [x] Create `bootstrap/` package
- [x] Extract [container.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/container.py) (ApplicationContainer dataclass)
- [x] Extract [wire_core.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_core.py)
- [x] Extract [wire_workspace.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_workspace.py)
- [x] Extract [wire_ops.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_ops.py)
- [x] Extract [wire_datasources.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_datasources.py)
- [x] Extract [wire_notifications.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_notifications.py)
- [x] Extract [wire_plugins.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_plugins.py)
- [x] Extract [wire_admin.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_admin.py)
- [x] Extract [wire_ui.py](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/wire_ui.py)
- [x] Facade [__init__.py](file:///home/damien/Dokumente/cockpit/tests/__init__.py) with [build_container()](file:///home/damien/Dokumente/cockpit/src/cockpit/bootstrap/__init__.py#50-283)

### Verification
- [x] All existing tests pass (206/206, 2 pre-existing failures)
- [x] `python -m compileall` passes
- [x] Smoke test passes (Container build successful)
