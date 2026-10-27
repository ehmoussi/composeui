# Changelog

The notable changes of each release of ComposeUI. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version can break the API.

## [Unreleased]

## [0.1.0] - Unreleased

The first release on PyPI.

### Added

- Views as typed `attrs` classes, signals, models, and a `run` function that starts the app
  on the backend that the command line chooses.
- Three backends: Qt (the `pyside6` extra), Textual (the `tui` extra), and the web
  (the `web` extra, the default).
- Layouts, a status bar, menus, toolbars, inputs, forms and their checks, pages, tabs,
  resizable panes, a sidebar, dialogs, tables, large tables, trees, Markdown, charts, and
  street maps (Qt and the web).
- The state of the views saved to a study file and loaded from it.
- Threads, SQLite models, CSV imports, translations, and tests of an app that need no backend.
- A skill for coding agents that write a ComposeUI app.
- `composeui.__version__`, the version of the installed package.

[Unreleased]: https://github.com/ehmoussi/composeui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ehmoussi/composeui/releases/tag/v0.1.0
