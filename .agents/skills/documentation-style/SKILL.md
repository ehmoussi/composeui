---
name: documentation-style
description: "Use before creating, editing, moving, or reviewing ComposeUI documentation: README.md, files under docs/, ROADMAP.md, AGENTS.md, and skills under .agents/skills/, including documentation updates within coding tasks such as a new view, backend, or behavior change. Applies ASD-STE100 writing principles, the repo's document split, and technical accuracy against the code while allowing structure and content to evolve with the task."
---

# Documentation Style

Use ASD-STE100 principles to make ComposeUI documentation easier to read.
For language-only edits, simplify the English, not the meaning. For feature updates
or restructuring, change the content and organization as the task requires.
These are writing guidelines, not a fixed document template.
Do not claim formal STE compliance or certification
without a separate check against the applicable standard and dictionary.

Docstrings and code comments are out of scope. Follow the code style in `AGENTS.md`
for them: brief docstrings, comments that explain *why*.

## Choose the right location

Each document has one audience:

| Document | Audience | Owns |
| --- | --- | --- |
| `README.md` | First-time users of ComposeUI | What the library is, why to use it, installation, quickstart, and links to the guides |
| `docs/user-guide.md` | App developers who use ComposeUI | One section per feature and widget, and the differences between the backends |
| `docs/examples-guide.md` | App developers who learn from the example apps | One section per app in `src/examples/`: what it shows, with links to the user guide, and how to run it |
| `docs/technical-guide.md` | Contributors to ComposeUI | The architecture, adding a widget or a backend, tests, checks, and code style |
| `ROADMAP.md` | Maintainers | Work left to do, and the design notes for the web backend |
| `AGENTS.md` | Coding agents | Setup, commands, architecture rules, code style, tests, commits |
| `.agents/skills/*/SKILL.md` | Coding agents | A focused workflow, such as `test-audit` |

`README.md` is also the package's long description on PyPI (`readme` in
`pyproject.toml`). Write it for a reader who has not seen the code.

- Keep `README.md` concise and useful to a first-time user. Explain the
  project before setup details. Make the next useful action easy to find.
- Put detailed usage and backend information in the user guide, and architecture and
  development information in the technical guide. Put what an example app shows in the
  examples guide, and link to the user guide for how each feature works. Add links from `README.md` where
  readers need them.
- When you move a section from `README.md` to `docs/`, leave a link in `README.md`
  where readers expect it.
- Give each user-facing feature its own section or document, such as "Tabs" or
  "Resizable panes". Put a sub-feature under a lower heading in it,
  such as "Sorting and filtering" under "A table of records".
- Put related features next to each other. Put a new section where a reader who
  follows the guide in order needs it, not always at the end.
- Order sections for the intended audience. Add, remove, split, merge, or reorder
  sections when this improves the document or meets the user's request.
- Put internal decisions that users do not see in `ROADMAP.md` under
  "Design notes for the web backend", or in a code comment. Do not put them in the
  user documentation.
- Put agent-only rules in `AGENTS.md` or in a skill. Do not put them in the user documentation.
- Include examples and links to `src/examples/` when they help readers.
  Avoid explanations that only repeat obvious interface actions or nearby text.
- Prefer one authoritative copy of each procedure. Link to it rather than
  maintaining duplicate instructions. Keep distinct procedures for different audiences.
  Setup, commands, tests, and code style appear in the technical guide ("Development")
  and in `AGENTS.md`. When one of them changes, update both.
- Group related topics under meaningful headings. Give independent topics their
  own sections instead of placing them under an unrelated heading.
- Keep contents lists, navigation, and in-page links such as `[Pages](#pages)`
  consistent with the current structure.

Use a different structure when it fits a document's purpose better.
The split above is a useful starting point, not a permanent requirement.

## Document a feature

A feature section in the user guide usually has this content, in this order:

1. One or two sentences: what the view or feature does, and a typical use.
2. A short Python example with the imports from `composeui.core`. Use
   `@define_view` and `attrs` fields as the other examples do.
3. The attributes and signals that the reader uses, and the behavior that a
   reader cannot guess, such as what is saved with the state and what is not.
4. What each backend shows, with the toolkit widget, for example:
   "Qt shows a `QTabWidget`, Textual a `TabbedContent`, and the web a row of tabs."
   Say clearly when a backend behaves differently or does not support the feature.
5. A link to an example app in `src/examples/` that uses the feature. From `docs/`,
   the link is relative, such as `../src/examples/pipecatalogue.py`.

Use only names that exist in `composeui.core`. A comment such as `# a TreeView` can
stand for an application view that the example does not define.

When the feature is a new widget, also update the list of widgets
("Already there: ...") at the top of `ROADMAP.md`, and delete its roadmap entry.
`ROADMAP.md` keeps only the work that is left. Keep the contents list at the top of the
guide in step with its `##` headings.

## Document an example app

An example section in `docs/examples-guide.md` usually has this content, in this order:

1. One sentence: what the app is, with a link to its file in `src/examples/`.
2. The command that runs it, with its default backend and the other `--backend` values.
3. A list of what it shows, each feature linked to its section in the user guide.

When you add an example, also add its row to the overview table, with its default backend
(the `default_backend` of its `run` call, else web), and its entry in the contents list.
When an example changes what it shows, update its section and its row. The module
docstring of each example is the first source for what it shows: check it against the code.
Do not document an example that is not committed.

## Write clear technical English

- Write short sentences. Give each sentence one main idea.
- Use short paragraphs that explain one topic.
- Prefer active voice and name the component that performs the action,
  such as the view, the renderer, the backend, or the user.
- Use direct instructions: "Set," "Run," "Select," and "Restart."
- Put conditions before instructions when readers need the condition first.
- Use numbered lists for ordered steps. Use bullets for options and inventories.
  In a bullet list of behaviors, start each bullet with a bold lead-in, such as
  "**One app state per browser.**" in the web backend's differences.
- Split long lists and sentences instead of removing technical information.
- Use one term consistently for each concept. Avoid stylistic synonyms.
  Use the repo's terms: view, main view, renderer, backend, model, signal, job, page.
  Use the backend names Qt, Textual, and the web.
- Replace complex everyday words with simpler words when the meaning stays the same.
- Avoid ambiguous pronouns, noun chains, and unexplained slash combinations.
- Keep necessary software and domain terms. Explain them when the audience needs it.
- Put code names in backticks: classes, attributes, signals, modules, paths, commands,
  extras, and `make` targets.
- Keep exact UI labels and key names, such as "Save", "Alt+Shift+S", or the arrow keys.
- Preserve existing icons and useful visual cues during wording edits. Simplifying
  English does not require removing them.

Use sentence length as a review signal, not a reason to damage meaning.
Aim for no more than 20 words in procedural sentences and 25 words in descriptive
sentences where practical. Split a longer sentence or use a list. Do not shorten
an exact identifier, command, or technical term to meet a word limit.

Wrap Markdown prose at 100 characters or less, as the code is. Do not wrap a
line inside a link, inline code, or a table row.

## Preserve the technical contract

For language-only edits, preserve:

- Commands, code examples, paths, URLs, identifiers, and UI labels.
- Class, attribute, signal, and metadata names, such as `SplitterView`, `sizes`,
  `resized`, and `STRETCH`.
- Extras (`pyside6`, `tui`, `web`, `report`), `--backend` values, and `make` targets.
- Versions, units, numeric limits, defaults, and configuration values,
  such as `42rem`, 24 rows, or `session_ttl`.
- Preconditions, optional features, ordering, scope, and version isolation.
- Differences between the backends, and the backends that a feature supports.
- What is saved, loaded, or reset with the state, and what is not.
- Warnings, security requirements, licenses, attribution, and acknowledgements.
- The project status ("early-stage / pre-alpha"), uncertainty, and limitations.
- Distinctions between confirmed and possible behavior, partial and complete
  support, and source analysis and runtime verification.

Do not turn "can" into "does," "candidate" into "confirmed," or an optional action
into a requirement. Keep the scope of words such as "all," "only," "never," and "up to."
Do not remove a qualification because it makes a sentence longer.

For example:

> Original: The web stacks the panes, without borders, in a splitter narrower than
> 42rem, as it does a row's views.
>
> Revised: When a splitter is narrower than 42rem, the web stacks its panes without
> borders. It stacks a row's views in the same way.

For substantive updates, change examples, values, claims, and qualifications when
the requested behavior or verified facts require it. Keep related documentation
consistent. Do not preserve obsolete information just to avoid a text change.
If a technical claim appears wrong, check the relevant code in `src/composeui/`,
the backend's renderer, or the tests. Make factual corrections explicit instead of
presenting them as wording-only edits.

## Editing workflow

1. Read the affected document and check `git status` and the current diff.
   Preserve unrelated work.
2. Decide which document owns the information. Read related sections before editing.
3. Make the requested change with the writing rules above. Avoid unrelated restructuring.
4. Compare the revised text with the original for technical meaning and qualifications.
5. Check contents lists, in-page links, heading anchors, and relative links between
   `README.md`, `docs/`, and `src/examples/`. When moving content, resolve relative
   paths from the new file's directory.
6. For language-only changes, compare fenced code blocks and inline code with the
   original. Investigate every difference; preserve exact examples unless the task
   requires a change. Keep headings stable where practical: other sections link to them.
7. When a Python example changes, check each name against `composeui.core`. If
   practical, run the example with `uv run python` in the scratchpad directory.
8. Run `git diff --check`. Run focused checks for changed commands or behavior if needed.
9. Report the changes and checks briefly. Do not claim checks that were not run.

Documentation-only changes do not require `make test` or `make check`.
Do not run installation or `make css` merely to check their wording.
Do not commit changes unless the user requests a commit. When documentation
belongs to a feature, commit it with that feature, as `AGENTS.md` describes under "Commits".
