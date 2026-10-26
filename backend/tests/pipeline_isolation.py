"""For tests that run pipeline jobs: no real pipeline_settings.json, no spacing between Claude calls, no leftover reservations."""
from unittest import mock

from supply_chain import control, orchestrator


def isolate(test, root):
    """Point the pipeline settings at a temp folder (default budget, pacing on), switch the Gate's spacing off, and start clean."""
    for patcher in (mock.patch.object(control, "settings_path", lambda: root / "pipeline_settings.json"),
                    mock.patch.object(orchestrator, "MIN_GAP_S", 0.0),
                    mock.patch.object(orchestrator, "_gate", None),
                    mock.patch.object(control, "clock_zone", None)):
        patcher.start()
        test.addCleanup(patcher.stop)
    orchestrator._reserved.clear()
    test.addCleanup(orchestrator._reserved.clear)
