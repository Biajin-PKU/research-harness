from research_harness.cli import main


def test_task_priority_and_project_scoping(runner):
    runner.invoke(main, ["topic", "init", "demo"])
    runner.invoke(main, ["project", "add", "--topic", "demo", "--name", "paper1"])
    runner.invoke(main, ["task", "add", "--topic", "demo", "--project", "paper1", "--title", "high task", "--priority", "high"])
    runner.invoke(main, ["task", "add", "--topic", "demo", "--title", "medium task", "--priority", "medium"])

    result = runner.invoke(main, ["task", "list", "--topic", "demo"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert "high task" in lines[0]

    scoped = runner.invoke(main, ["task", "list", "--project", "paper1"])
    assert scoped.exit_code != 0
