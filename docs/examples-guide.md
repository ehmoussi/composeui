# Examples guide

The example apps in [`src/examples/`](../src/examples/) show ComposeUI's features in
complete apps. This guide says what each example shows, and how to run it. The
[user guide](user-guide.md) explains each feature. The examples are not in the wheel:
run them from a clone of the repository.

## Contents

- [Run an example](#run-an-example)
- [Overview](#overview)
- [Pipe form](#pipe-form)
- [Pipe catalogue](#pipe-catalogue)
- [Pipe chart](#pipe-chart)
- [Task view](#task-view)
- [Batman](#batman)
- [Markdown viewer](#markdown-viewer)
- [Web hello](#web-hello)
- [Textual demo](#textual-demo)

## Run an example

Install the extras of the backends that you want (see the [README](../README.md#installation)).
Then run an example as a module:

```bash
uv run python -m examples.pipeform --backend qt
```

`--backend` takes `qt`, `textual`, or `web`. Without `--backend`, the `COMPOSEUI_BACKEND`
environment variable picks the backend. Without both, each example starts its own default
backend, which the [overview](#overview) gives. `--help` lists the other
options, such as `--language` and `-f FILE`.

## Overview

| Example | Default backend | Shows |
| --- | --- | --- |
| [`pipeform.py`](../src/examples/pipeform.py) | web | Forms, validation, pages, a menu, a confirm dialog, Markdown help, a French translation |
| [`pipecatalogue.py`](../src/examples/pipecatalogue.py) | web | A SQLite model, a sidebar, a list of views, a tree, resizable panes, a form dialog, a date input |
| [`pipechart.py`](../src/examples/pipechart.py) | qt | Line and scatter charts, a reference line, tabs, a table |
| [`taskview.py`](../src/examples/taskview.py) | web | Jobs in threads, metrics, a progress bar, a step chart, an expander, a French translation |
| [`batman.py`](../src/examples/batman.py) | qt | Series colors, fills, and clicks on a chart |
| [`markdownviewer.py`](../src/examples/markdownviewer.py) | web | A Markdown view, a file picker, an option of the app's own, no File menu |
| [`webhello.py`](../src/examples/webhello.py) | web only | A form on the web backend, built with `WebApplication` |
| [`textual_demo.py`](../src/examples/textual_demo.py) | textual | A small form in a terminal |

The tests in [`tests/`](../tests/) also run these examples. When you change an example,
run its tests.

## Pipe form

[`pipeform.py`](../src/examples/pipeform.py) is a form that describes two pipes: a main pipe
and an incident pipe.

```bash
uv run python -m examples.pipeform --backend qt   # or textual, or web
```

It shows:

- [forms](user-guide.md#compose-views-from-mixins) with labelled rows: text, float inputs, a
  checkbox, radio groups, and a combobox;
- validation on a row, such as the name, and across rows, such as a main pipe that must
  fit the incident pipe;
- three [pages](user-guide.md#pages): Inputs, Results (a read-only table of the
  dimensions), and Help (a [Markdown](user-guide.md#markdown) page);
- a Pipe menu, whose Reset Dimensions asks for a
  [confirmation](user-guide.md#dialogs) first;
- the File menu, which saves and loads the study as a `.pipe` file;
- a [French translation](user-guide.md#translating-the-app) and a Language menu. To start in
  French, add `--language fr`.

## Pipe catalogue

[`pipecatalogue.py`](../src/examples/pipecatalogue.py) is a catalogue of pipes, kept in a
SQLite database.

```bash
uv run python -m examples.pipecatalogue --backend qt   # or textual, or web
```

It shows:

- a [SQLite model](user-guide.md#a-sqlite-model): the pipes are rows of the model's
  database, not view state. The database checks every pipe added or changed: a name,
  positive dimensions, and a wall thinner than the radius. A SQL view computes the mass of
  each pipe from its material.
- a [sidebar](user-guide.md#sidebar) with a form that adds a pipe;
- a [list of views](user-guide.md#a-list-of-views): an [expander](user-guide.md#expander)
  per pipe, with its Edit and Delete buttons. A query filters the list by material, radius,
  and installation date.
- a [tree](user-guide.md#tree) of the pipes by material, beside the list, in
  [resizable panes](user-guide.md#resizable-panes). The materials are bold. A pipe has a
  done mark when its installation date is known, and a warning mark until then. When the
  user selects a pipe in the tree, its expander expands.
- a [form dialog](user-guide.md#form-dialogs) that edits a pipe;
- a [date input](user-guide.md#date-input) for the installation date of a pipe;
- studies saved as a `.pipes` file with the views and the database. A study saved before
  pipes had an installation date gets the column, empty, when it opens, through a
  migration (`PipeCatalogueModel.migrations`).

## Pipe chart

[`pipechart.py`](../src/examples/pipechart.py) plots the pressure drop of a pipe against its
flow rate.

```bash
uv run python -m examples.pipechart   # qt; or --backend textual, or web
```

It shows:

- a [line chart](user-guide.md#charts): each click on Add Curve plots one curve for the
  diameter in the form, with its own flow rates;
- a gap in a curve: between laminar and turbulent flow neither law holds, so the curve
  leaves a gap there (a NaN);
- [scatter series](user-guide.md#kinds-of-chart): Add Measurements plots, as dots over the
  curves, what a test rig measured on that pipe;
- a [reference line](user-guide.md#reference-lines) at the pressure of the pump;
- [tabs](user-guide.md#tabs): the chart on one tab, and the measurements in a table on the
  Measurements tab, each against the computed drop.

## Task view

[`taskview.py`](../src/examples/taskview.py) runs 25 tasks side by side in threads.

```bash
uv run python -m examples.taskview   # web; or --backend qt, or textual
```

It shows:

- [jobs](user-guide.md#running-work-in-threads): each task is a function that runs in a
  thread and never touches a view. Its job emits the status of the task on the main thread,
  where the views show it. A button cancels the jobs.
- a configuration form with an [integer input](user-guide.md#integer-input) and a
  [slider](user-guide.md#slider);
- a [progress bar](user-guide.md#progress-bar) of the tasks done;
- [metrics](user-guide.md#metric) that count the tasks. Once a run is over, they show how
  each count changed since the last run.
- a [step chart](user-guide.md#colors-fill-steps-and-height) of the tasks running over the
  time of the run;
- an [expander](user-guide.md#expander) with the table of the tasks, which collapses to
  leave only the metrics and the chart;
- a [French translation](user-guide.md#translating-the-app) and a Language menu.

## Batman

[`batman.py`](../src/examples/batman.py) draws the Batman logo on a chart.

```bash
uv run python -m examples.batman   # qt; or --backend web, or textual
```

It shows:

- [series colors and fills](user-guide.md#colors-fill-steps-and-height): a yellow oval and
  the edges of the bat in black, each series in the color of the logo, whatever the theme;
- [clicks on a chart](user-guide.md#clicks-on-a-chart): `clicked` emits the point, and the
  view says whether it is on the bat. Textual draws the logo too, but a terminal has no
  pointer to click it with.

## Markdown viewer

[`markdownviewer.py`](../src/examples/markdownviewer.py) shows a Markdown file.

```bash
uv run python -m examples.markdownviewer --markdown README.md --backend qt
```

It shows:

- a [Markdown view](user-guide.md#markdown);
- an [option of the app's own](user-guide.md#command-line-options-of-your-own):
  `--markdown`, beside the options of the backend;
- a [file picker](user-guide.md#the-file-menu-and-picking-a-file): Markdown > Open Markdown
  (Ctrl+M) picks a file. On the web, the browser uploads it.
- an app without studies: `has_file_menu = False` leaves out the File menu.

## Web hello

[`webhello.py`](../src/examples/webhello.py) is a small form on the
[web backend](user-guide.md#web-backend) only.

```bash
uv run python -m examples.webhello
```

It serves http://127.0.0.1:8000. It shows:

- an application built as a `WebApplication` subclass, without `run`;
- a form with a text input, a float input, a radio group, and a combobox, with validation
  on the name and the age;
- one keystroke that updates the status bar, the log of the row, and a summary label at
  once.

## Textual demo

[`textual_demo.py`](../src/examples/textual_demo.py) is a small form in a terminal.

```bash
uv run python -m examples.textual_demo
```

It shows a form with a text input, a float input, and a radio group. A change of shape
shows a message in the status bar. It starts on Textual: `run(...,
default_backend=RendererType.TEXTUAL)`.
