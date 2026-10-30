"""A run's output, shared by the backend tests of `ConsoleView`.

Each click on Run writes `STEP_LINES` lines, then a progress line that the next run's
first line replaces. The console keeps `MAX_LINES` lines. `ColoredRunMainView`'s output
has ANSI colors, which its console shows.
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


#: a colored output: bold red, a green background, then a green line being written
COLORED = "\x1b[1;31mERR\x1b[0mOR <x> \x1b[42mbg\x1b[0m\n\x1b[32mgreen"


@define_view
class ColoredRunMainView(MainView):
    """A console showing its output's colors: More ends the green line, and adds one."""

    app_title = "Colors"
    extension = ".colors"

    more: ButtonView = child(ButtonView, text="More")
    output: ConsoleView = child(ConsoleView, ansi_colors=True)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.output.append(COLORED)
        self.more.clicked.connect(self._more)

    def _more(self) -> None:
        self.output.append(" \x1b[3;4;34mblue\x1b[0m\nerror again\n")
