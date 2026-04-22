from research_harness.cli import main


def test_task_priority_ordering(runner):
    runner.invoke(main, ["topic", "init", "demo"])
    runner.invoke(
        main,
        [
            "task",
            "add",
            "--topic",
            "demo",
            "--title",
            "medium task",
            "--priority",
            "medium",
        ],
    )
    runner.invoke(
        main,
        [
            "task",
            "add",
            "--topic",
            "demo",
            "--title",
            "high task",
            "--priority",
            "high",
        ],
    )

    result = runner.invoke(main, ["task", "list", "--topic", "demo"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert "high task" in lines[0]
