from smeargle import console as console_module


def test_console_is_a_singleton_on_stderr():
    first = console_module.console()
    second = console_module.console()
    assert first is second
    assert first.stderr is True


def test_new_progress_disables_live_display_off_terminal():
    progress = console_module.new_progress()
    assert progress.disable is not console_module.console().is_terminal


def test_stage_task_returns_none_without_progress():
    assert console_module.stage_task(None, "extract", 5) is None


def test_stage_task_returns_none_for_empty_total():
    progress = console_module.new_progress()
    assert console_module.stage_task(progress, "extract", 0) is None


def test_stage_task_advances_the_registered_task():
    progress = console_module.new_progress()
    advance = console_module.stage_task(progress, "extract", 2)
    assert advance is not None
    (task_id,) = progress.task_ids
    assert progress.tasks[task_id].total == 2
    advance()
    assert progress.tasks[task_id].completed == 1
