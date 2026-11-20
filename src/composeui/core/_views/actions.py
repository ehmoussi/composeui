"""The views of the menus and the toolbar: actions, menus and the file menu."""

from __future__ import annotations

import functools
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
)

import attrs
from typing_extensions import override

from composeui.core import study
from composeui.core._views.base import OMIT, UI_TEXT, View, define_view
from composeui.core._views.dialogs import _CHANGED_ON_DISK_QUESTION
from composeui.core.model import InvalidStateError, Model
from composeui.core.renderer import MainRenderer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    LANGUAGE_NAMES,
    T,
    language_name,
)

if TYPE_CHECKING:
    from composeui.core._views.main import MainView


@define_view
class ActionView(View):
    """An entry of a menu or a toolbar that the user triggers, for example Save.

    `triggered` emits when the user triggers it. A checkable action (`is_checkable`) changes
    `is_checked` first, so the callbacks see the new state.
    """

    _renderer_key = "action"

    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: an image file's path; set by the app, not study data: never saved, loaded or
    #: reset (the web backend serves the file, so a study must not name one)
    icon: Optional[str] = attrs.field(default=None, metadata={OMIT: True})
    data: Any = attrs.field(default=None)
    shortcut: Optional[str] = attrs.field(default=None)
    is_checkable: bool = attrs.field(default=False)
    is_checked: bool = attrs.field(default=False)

    triggered: SignalNoArgs = attrs.Factory(SignalNoArgs)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # first, so the callbacks connected after it see the new check state; on Qt,
        # `QAction` has already toggled itself, and this brings the view in line
        self.triggered.connect(self._toggle_checked)

    def _toggle_checked(self) -> None:
        if self.is_checkable:
            self.is_checked = not self.is_checked


@define_view
class SeparatorAction(View):
    """A line between two groups of entries in a menu or a toolbar."""

    _renderer_key = "separator"


@define_view
class Menu(View):
    """A menu of the window, with an entry for each of its action fields.

    Its `ActionView` and `SeparatorAction` fields are its entries, in order. `title` names it.
    """

    _renderer_key = "menu"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the menu should be visible only when triggered
        self.is_visible = False


@define_view
class ToolBar(View):
    """A row of actions at the top of the window, for the ones the user runs most.

    Its `ActionView` and `SeparatorAction` fields are its entries, in order; a field of
    the main view, docked by the window. `title` names it, e.g. for a screen reader.
    """

    _renderer_key = "toolbar"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class NewAction(ActionView):
    """The New action of the File menu, which starts a new study."""

    text: str = attrs.field(default=T("New"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+n"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._new_study)

    def _new_study(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        main_view.ask_discard_changes(functools.partial(study.new_study, main_view, model))


@define_view
class OpenFileAction(ActionView):
    """The Open action of the File menu, which opens a study from a file."""

    text: str = attrs.field(default=T("Open"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+o"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._open_study)

    def _open_study(self) -> None: ...


@define_view
class PickFileAction(ActionView):
    """An action picking a file to open; `file_picked` emits its path.

    On Qt and Textual, triggering it shows the file picker. On the web, the browser's
    picker uploads the file: the path is then a copy, gone once `file_picked`'s
    callbacks have run. Unlike `OpenFileAction`, the file is the app's to read, not a
    study.
    """

    #: the file types the picker offers, by name: ``{"Markdown": (".md", ".markdown")}``;
    #: on the web, a file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], metadata={OMIT: True}
    )
    file_picked: Signal[Path] = attrs.Factory(Signal[Path])

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.triggered.connect(self._pick_file)

    def _pick_file(self, *, main_view: MainView) -> None:
        path = main_view.ask_open_filepath(extensions=self.extensions)
        if path is not None:
            self.file_picked.emit(path)


@define_view
class SaveAction(ActionView):
    """The Save action of the File menu, which saves the study into its file.

    The file it was opened from or saved to; without one, it asks for it, as Save As does.
    On the web, Save downloads the study.
    """

    text: str = attrs.field(default=T("Save"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+s"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._save_study)

    def _save_study(self) -> None: ...


@define_view
class SaveAsAction(ActionView):
    """The Save As action of the File menu, which saves the study to a file the user picks."""

    text: str = attrs.field(default=T("Save As"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+Shift+s"
        self.is_checkable = False
        self.icon = None
        self.data = None


@define_view
class ExitAppAction(ActionView):
    """The Exit action of the File menu, which closes the app."""

    text: str = attrs.field(default=T("Exit"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.shortcut = "Ctrl+q"
        self.is_checkable = False
        self.icon = None
        self.data = None
        self.triggered.connect(self._exit_app)

    def _exit_app(self, *, main_view: MainView) -> None:
        main_view.ask_discard_changes(main_view.close)


@define_view
class FileMenu(Menu):
    """The File menu of the main view, with New, Open, Save, Save As and Exit.

    An app without studies sets `MainView.has_file_menu` to False to leave it out.
    """

    new: NewAction = attrs.Factory(NewAction)
    open_file: OpenFileAction = attrs.Factory(OpenFileAction)
    save: SaveAction = attrs.Factory(SaveAction)
    save_as: SaveAsAction = attrs.Factory(SaveAsAction)
    separator_exit: SeparatorAction = attrs.Factory(SeparatorAction)
    exit_app: ExitAppAction = attrs.Factory(ExitAppAction)

    title: str = attrs.field(default=T("File"), metadata={UI_TEXT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.save.triggered.connect(self._save)
        self.save_as.triggered.connect(self._save_state)
        self.open_file.triggered.connect(self._load_state)

    def _load_state(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        filepath = main_view.ask_open_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            # once the file is picked: on Textual, only a worker thread may show the picker,
            # and the answer comes on the app's
            main_view.ask_discard_changes(
                functools.partial(self._open_study, main_view, model, filepath)
            )

    @staticmethod
    def _open_study(main_view: MainView, model: Optional[Model], filepath: Path) -> None:
        try:
            study.open_study(main_view, model, filepath)
        except InvalidStateError as error:
            message = main_view.tr("Can't open {name}: {error}.")
            main_view.status_bar.show_message(message.format(name=repr(filepath.name), error=error))

    def _save(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        """Save the study into its file; without one, ask for it, as Save As does.

        A file changed on disk since it was opened or saved, e.g. by another app or after a
        restore, is replaced once the user agrees.
        """
        filepath = main_view.state_filepath
        renderer = main_view.renderer
        if filepath is None or (isinstance(renderer, MainRenderer) and not renderer.saves_in_place):
            self._save_state(main_view=main_view, model=model)
            return
        write = functools.partial(self._save_study, main_view, model)
        if not main_view._is_study_file_changed(filepath):  # noqa: SLF001 (the study's own)
            write(filepath)
            return
        dialog = main_view.replace_file
        dialog.title, dialog.accept_text = "", main_view.tr("Replace")
        dialog.save(filepath, write, question=_CHANGED_ON_DISK_QUESTION)

    def _save_state(self, *, main_view: MainView, model: Optional[Model] = None) -> None:
        filepath = main_view.ask_save_filepath(
            extensions={main_view.extension: (f"{main_view.extension}",)}
        )
        if filepath is not None:
            self._save_study(main_view, model, filepath)

    @staticmethod
    def _save_study(main_view: MainView, model: Optional[Model], filepath: Path) -> None:
        """Save the study into `filepath`; the status bar says why it can't."""
        try:
            study.save_study(main_view, model, filepath)
        except OSError as error:  # e.g. its folder is gone, or the disk is full
            failed = main_view.tr("Can't save to {name}: {error}.")
            main_view.status_bar.show_message(failed.format(name=filepath.name, error=error))


@define_view
class LanguageMenu(Menu):
    """A menu of the app's languages, the one shown checked; triggering one shows it.

    Make it a field of the main view. The main view gives it the languages it has catalogs
    for (`MainView.languages`), and keeps the shown one checked. The menu names each
    language in itself, whatever the language shown. The language isn't study data:
    never saved, loaded or reset.
    """

    title: str = attrs.field(default=T("Language"), metadata={UI_TEXT: True})
    #: each language's action, its code as `data`; set with `set_languages`
    actions: list[ActionView] = attrs.field(factory=list[ActionView], metadata={OMIT: True})
    #: the languages' names, by code; a subclass extends it for a language it lacks:
    #: ``names = {**LanguageMenu.names, "eo": "Esperanto"}``
    names: ClassVar[Mapping[str, str]] = LANGUAGE_NAMES

    @property
    @override
    def children_views(self) -> list[View]:
        return [*super().children_views, *self.actions]

    def set_languages(self, languages: Sequence[str]) -> None:
        """Offer `languages`, by code, before the menu is rendered.

        A language whose first letter no other one shares gets a Ctrl+Shift shortcut.
        """
        initials = [language[:1].lower() for language in languages]
        self.actions = [
            ActionView(
                text=language_name(language, self.names),
                data=language,
                is_checkable=True,
                shortcut=f"Ctrl+Shift+{initial}" if initials.count(initial) == 1 else None,
            )
            for language, initial in zip(languages, initials)
        ]

    def action(self, language: str) -> ActionView:
        """Get the action of `language`, e.g. "fr"."""
        for action in self.actions:
            if action.data == language:
                return action
        msg = f"{type(self).__name__} doesn't offer {language!r}."
        raise KeyError(msg)

    def check(self, language: str) -> None:
        """Check `language`'s action, else its base language's: "fr-CA" checks French."""
        offered = [action.data for action in self.actions]
        base = language.replace("_", "-").split("-")[0]
        checked = language if language in offered else base
        for action in self.actions:
            action.is_checked = action.data == checked
