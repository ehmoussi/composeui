"""A run's output, shared by the backend tests of `ConsoleView`.

Each click on Run writes `STEP_LINES` lines, then a progress line that the next run's
first line replaces. The console keeps `MAX_LINES` lines.
"""

from __future__ import annotations

from composeui.core.view import ButtonView, ConsoleView, MainView, child, define_view

#: the lines a run writes, before its progress line
STEP_LINES = 30
MAX_LINES = 50


@define_view
class RunMainView(MainView):
    app_title = "Run"
    extension = ".run"

    run: ButtonView = child(ButtonView, text="Run")
    output: ConsoleView = child(ConsoleView, max_lines=MAX_LINES)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.output.append("Ready <ok>\n")
        self.run.clicked.connect(self._run)

    def _run(self) -> None:
        start = self.output.line_count
        lines = "".join(f"\rStep {start + index}\n" for index in range(STEP_LINES))
        self.output.append(f"{lines}Progress 100%")
