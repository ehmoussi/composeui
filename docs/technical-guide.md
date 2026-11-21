# Technical guide

This guide explains how ComposeUI works and how to contribute to it. To build an app, read the
[user guide](user-guide.md) instead.

## Start here

- [Set up the repository](technical-guide/development.md#setup) for your first contribution.
- [Read the architecture](technical-guide/architecture.md) to see how the code fits together.
- [Add a widget or a backend](technical-guide/extending.md) to extend ComposeUI.

## Contents

<!-- Keep existing bookmarks next to the links to their new destinations. -->

- <a id="architecture" name="architecture"></a>
  [Architecture](technical-guide/architecture.md)
  - <a id="project-layout" name="project-layout"></a>
    [Project layout](technical-guide/architecture.md#project-layout)
  - [The core imports no backend](technical-guide/architecture.md#the-core-imports-no-backend)
  - [The registry](technical-guide/architecture.md#the-registry)
  - <a id="views-and-renderers" name="views-and-renderers"></a>
    [Views and renderers](technical-guide/architecture.md#views-and-renderers)
  - [Signals](technical-guide/architecture.md#signals)
  - [Reactive methods](technical-guide/architecture.md#reactive-methods)
  - [Shared data](technical-guide/architecture.md#shared-data)
  - [View state](technical-guide/architecture.md#view-state)
  - [A button click](technical-guide/architecture.md#a-button-click)
- <a id="design-of-the-web-backend" name="design-of-the-web-backend"></a>
  [Design of the web backend](technical-guide/web-backend.md)
  - [The web backend](technical-guide/web-backend.md#the-web-backend)
  - [A button click on the web](technical-guide/web-backend.md#a-button-click-on-the-web)
  - [Requests and updates](technical-guide/web-backend.md#requests-and-updates)
  - [The page's scripts](technical-guide/web-backend.md#the-pages-scripts)
  - [Tables on the web](technical-guide/web-backend.md#tables-on-the-web)
  - [Order and sessions](technical-guide/web-backend.md#order-and-sessions)
  - [Pages, tabs, and dialogs](technical-guide/web-backend.md#pages-tabs-and-dialogs)
  - [The header, icons, and images](technical-guide/web-backend.md#the-header-icons-and-images)
  - [Testing the web backend](technical-guide/web-backend.md#testing-the-web-backend)
- [File transfers on the web](technical-guide/web-file-transfers.md)
  - <a id="uploads-and-open" name="uploads-and-open"></a>
    [Uploads and Open](technical-guide/web-file-transfers.md#uploads-and-open)
  - <a id="downloads-on-the-web" name="downloads-on-the-web"></a>
    [Downloads on the web](technical-guide/web-file-transfers.md#downloads-on-the-web)
    - [Download steps](technical-guide/web-file-transfers.md#download-steps)
    - [Ticket lifetime and limits](technical-guide/web-file-transfers.md#ticket-lifetime-and-limits)
    - [Streaming](technical-guide/web-file-transfers.md#streaming)
    - [Why use POST and GET](technical-guide/web-file-transfers.md#why-use-post-and-get)
- <a id="reloading-on-a-change" name="reloading-on-a-change"></a>
  [Reloading on a change](technical-guide/reloading.md)
  - [Reloading on Qt](technical-guide/reloading.md#reloading-on-qt)
  - [Reloading on Textual](technical-guide/reloading.md#reloading-on-textual)
  - [Reloading on the web](technical-guide/reloading.md#reloading-on-the-web)
- [Extend ComposeUI](technical-guide/extending.md)
  - <a id="add-a-widget" name="add-a-widget"></a>
    [Add a widget](technical-guide/extending.md#add-a-widget)
  - <a id="add-a-backend" name="add-a-backend"></a>
    [Add a backend](technical-guide/extending.md#add-a-backend)
- <a id="development" name="development"></a>
  [Development](technical-guide/development.md)
  - [Setup](technical-guide/development.md#setup)
  - [Commands](technical-guide/development.md#commands)
  - [Tests](technical-guide/development.md#tests)
  - [Translations](technical-guide/development.md#translations)
  - [Styles of the web backend](technical-guide/development.md#styles-of-the-web-backend)
  - [Code style](technical-guide/development.md#code-style)
  - [Documentation site](technical-guide/development.md#documentation-site)
  - [Continuous integration](technical-guide/development.md#continuous-integration)
  - [Release](technical-guide/development.md#release)

```{toctree}
:hidden:

technical-guide/architecture
technical-guide/web-backend
technical-guide/web-file-transfers
technical-guide/reloading
technical-guide/extending
technical-guide/development
```
