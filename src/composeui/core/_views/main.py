"""The main view, and the state of its views: what a study saves and loads."""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import mimetypes
import re
import subprocess
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
    Union,
    cast,
    get_args,
    get_origin,
)

import attrs
from cattrs.gen import make_dict_unstructure_fn
from cattrs.gen import override as attribute_override
from typing_extensions import override

from composeui.core._files import partial_path
from composeui.core._views import base
from composeui.core._views.actions import FileMenu, LanguageMenu
from composeui.core._views.base import (
    _BAD_STATE_ERRORS,
    _OMITTED_TYPES,
    CONVERTER,
    OMIT,
    SESSION,
    UI_TEXT,
    LogType,
    View,
    _attach_jobs,
    _retranslate,
    define_view,
    view_fields,
)
from composeui.core._views.charts import ChartView
from composeui.core._views.choices import ChoicesMixin
from composeui.core._views.containers import PageWidth
from composeui.core._views.content import NotificationBar, StatusBar
from composeui.core._views.controls import CheckBoxMixin
from composeui.core._views.dialogs import (
    DialogView,
    DiscardChangesDialogView,
    ReplaceFileDialogView,
    RestoreWorkDialogView,
)
from composeui.core._views.files import (
    DownloadedFile,
    SavePathInputMixin,
    StreamContent,
    _publish,
    is_within_roots,
)
from composeui.core._views.tables import RecordTableView, SourceTableView, TableMixin
from composeui.core.autosave import Autosave
from composeui.core.client import (
    building_for_browser,
    check_url,
    current_browser_id,
    current_client,
    current_user,
    launch,
)
from composeui.core.jobs import Jobs, _check_main_thread
from composeui.core.model import InvalidStateError, Model
from composeui.core.reactivity import (
    batch,
)
from composeui.core.renderer import MainRenderer
from composeui.core.signal import SignalNoArgs
from composeui.core.translation import (
    CATALOGS_DIR,
    translator,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Iterator

    from attrs import AttrsInstance

    from composeui.core.client import ClientCapabilities
    from composeui.core.registry import RendererType


#: the version of how a study file holds the views' state, written in it as
#: ``{"composeui": {"format": ...}, "app": {"version": ...}, "views": ...}``. A file
#: without them is from before, and holds the views' state alone.
STATE_FORMAT = 1
#: `MainView._saved_study` of a study changed whatever it holds: no study has its mark
_UNSAVED_STUDY = ("", -1)


def _is_version(value: Any) -> bool:
    """Tell whether a study file's version is one: a positive integer, not a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_omitted_type(tp: Any) -> bool:
    """Check whether a (possibly generic/Optional/Union) type is or wraps an omitted type."""
    origin = get_origin(tp)
    if origin is Union:
        return any(_is_omitted_type(arg) for arg in get_args(tp))
    cls = origin if origin is not None else tp
    # a dialog is what the app asks the user, and the language how it shows: not study data
    return isinstance(cls, type) and issubclass(cls, (*_OMITTED_TYPES, DialogView, LanguageMenu))


def _is_omitted_field(f: attrs.Attribute[Any]) -> bool:
    """Check whether `f` should skip (de)serialization: by type, or by `OMIT` tag."""
    return _is_omitted_type(f.type) or bool(f.metadata.get(OMIT, False))


def _is_state_field(f: attrs.Attribute[Any]) -> bool:
    """Check whether `f` is study data, which state files save and load."""
    return not _is_omitted_field(f) and not f.metadata.get(UI_TEXT, False)


@CONVERTER.register_unstructure_hook_factory(attrs.has)
def _omit_renderer_and_signals(
    cls: type[AttrsInstance],
) -> Callable[[Any], dict[str, Any]]:
    # a generic view's class, e.g. a field's `RecordTableView[Room]`
    view_cls = get_origin(cls) or cls
    attrs.resolve_types(view_cls)
    overrides = {
        str(f.name): attribute_override(omit=True)
        for f in attrs.fields(view_cls)
        if not _is_state_field(f)
    }
    unstructure = make_dict_unstructure_fn(
        cls,
        CONVERTER,
        # every field, even one equal to its attrs default: views set their starting
        # state in `__attrs_post_init__`, so a default value left out of the file would
        # load back as that starting state instead (e.g. a validator message, or a
        # group hidden until an option shows it)
        _cattrs_omit_if_default=False,
        _cattrs_use_linecache=True,
        _cattrs_use_alias="from_converter",
        _cattrs_include_init_false=False,
        **overrides,
    )
    if issubclass(view_cls, RecordTableView):

        def unstructure_record_table(obj: RecordTableView[Any]) -> dict[str, Any]:
            data = unstructure(cast("AttrsInstance", obj))
            # the records by their own type, which the field's `RecordT` doesn't name;
            # the rows only show them, and the columns, the app's, set what's editable
            data["records"] = CONVERTER.unstructure(obj.records)
            for name in ("rows", "editable_columns", "sortable_columns", "filterable_columns"):
                del data[name]
            return data

        return unstructure_record_table
    if not issubclass(view_cls, ChoicesMixin):
        return unstructure

    def unstructure_choices(obj: ChoicesMixin[Any]) -> dict[str, Any]:
        data = unstructure(cast("AttrsInstance", obj))
        data[obj.choice_field] = obj.saved_choice()
        return data

    return unstructure_choices


#: what a `RecordTableView`'s records and columns set, which loading leaves to them
_RECORD_TABLE_SETUP = (
    "rows",
    "records",
    "editable_columns",
    "sortable_columns",
    "filterable_columns",
)


#: set while a reload opens its study (`load_reloaded_state`): what changes the state to load
_RELOADED_STATE: contextvars.ContextVar[Callable[[Any], Any] | None] = contextvars.ContextVar(
    "composeui_reloaded_state", default=None
)


def _choice_field(view: View) -> Optional[str]:
    """Get the field of a `ChoicesMixin`'s choice, which loads by its keys: else None."""
    return view.choice_field if isinstance(view, ChoicesMixin) else None


@batch()
def _apply_state(view: View, data: dict[str, Any]) -> None:
    """Update a live view tree in place from previously saved state.

    A fresh ``CONVERTER.structure(data, type(view))`` would build new nested
    view instances, losing their bound renderers and connected signals. Setting
    the existing attributes instead lets the normal ``notify_renderer``
    on_setattr hook refresh the UI as each value is applied.

    The choice of a `ChoicesMixin` (``ValuesGroupMixin.value``,
    ``MultiValuesMixin.selected``) is handled separately: its declared type is an
    unresolved generic ``TypeVar`` that cattrs can't structure statically. So it is
    saved by its keys and restored through the mixin's own `values`. ``values`` is
    included in saved state (for inspection/debugging) but never restored from it on load.
    It's app-defined config, not persisted user data, and has the same unresolved-`TValue`
    structuring problem, without an equivalent key-based workaround.
    ``RecordTableView.records`` is restored first, by `RecordTableView.record_type`: its
    rows, before the selection checked against them.
    """
    states = deque([(view, data)])
    while len(states) > 0:
        current_view, new_data = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        choice = _choice_field(current_view)
        if isinstance(current_view, ChoicesMixin) and choice in new_data:
            current_view.load_choice(new_data[choice])
        if isinstance(current_view, RecordTableView) and "records" in new_data:
            current_view.records = current_view.structure_records(new_data["records"])
        if isinstance(current_view, ChartView):
            new_data = ChartView.loadable_state(new_data)
        for f in attrs.fields(current_cls):
            if (
                f.name not in new_data
                or not _is_state_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (choice is not None and f.name in ("values", choice))
                or (f.name in _RECORD_TABLE_SETUP and isinstance(current_view, RecordTableView))
            ):
                continue
            new_value = new_data[f.name]
            current_field = getattr(current_view, f.name, None)
            if isinstance(current_field, View) and isinstance(new_value, dict):
                states.append((current_field, new_value))
                continue
            value = CONVERTER.structure(new_value, f.type)
            if isinstance(current_view, (TableMixin, SourceTableView)):
                # a sort or a filter on a column the table no longer sorts or filters
                value = current_view.loadable(f.name, value)
            setattr(current_view, f.name, value)


def _show_checked(view: View) -> None:
    """Show the views of each check box under `view` as the box is: a study's done loading.

    Their own visibility, a state too, may have been loaded after their box's.
    """
    views = deque([view])
    while len(views) > 0:
        current = views.popleft()
        # an `object`: from Python 3.13, mypy finds the `__replace__` of attrs' `View` and
        # mixin incompatible, so a view that is both looks impossible to it
        checkable: object = current
        if isinstance(checkable, CheckBoxMixin):
            for shown in checkable.shown_views:
                shown.is_visible = checkable.is_checked
        views.extend(current.children_views)


#: the key of a view's `_session_content` after its path: no field has this name
_CONTENT_KEY = "<content>"


def session_views(view: View) -> Iterator[tuple[str, View]]:
    """Get `view` and the views in its fields, below it too, each with its path as a prefix.

    Not the views of a list, such as a `ListView`'s: a session doesn't keep them.
    """
    views: deque[tuple[str, View]] = deque([("", view)])
    while len(views) > 0:
        prefix, current = views.popleft()
        yield prefix, current
        attrs.resolve_types(cast("type[AttrsInstance]", type(current)))
        for f in view_fields(type(current)):
            if not f.metadata.get(SESSION, False):
                value = getattr(current, f.name)
                if isinstance(value, View):
                    views.append((f"{prefix}{f.name}.", value))


def _session_fields(view: View) -> Iterator[tuple[str, View, attrs.Attribute[Any]]]:
    """Get the `SESSION` fields of `view` and of the views under it, each with its path."""
    for prefix, current in session_views(view):
        for f in view_fields(type(current)):
            if f.metadata.get(SESSION, False):
                yield f"{prefix}{f.name}", current, f


def session_data(view: View) -> dict[str, Any]:
    """Get the `SESSION` fields of `view` and of the views under it, by their path.

    And what each view shows that no field holds (`View._session_content`).
    """
    data = {
        path: CONVERTER.unstructure(getattr(current, f.name))
        for path, current, f in _session_fields(view)
    }
    for prefix, current in session_views(view):
        content = current._session_content()  # noqa: SLF001 (View's hook for this)
        if content is not None:
            data[f"{prefix}{_CONTENT_KEY}"] = content
    return data


@batch()
def load_session_data(view: View, data: Mapping[str, Any]) -> None:
    """Set the `SESSION` fields that `session_data` got, wherever they still fit.

    A field that the code added keeps its value, and so does one given a value that it no
    longer takes (e.g. a tab removed): it's only where the user was, not their data.
    """
    for path, current, f in _session_fields(view):
        if path in data:
            # resolved by `_session_fields`
            field_type = cast("type[Any]", f.type)
            with contextlib.suppress(*_BAD_STATE_ERRORS):
                setattr(current, f.name, CONVERTER.structure(data[path], field_type))
    for prefix, current in session_views(view):
        key = f"{prefix}{_CONTENT_KEY}"
        if key in data:
            with contextlib.suppress(*_BAD_STATE_ERRORS):
                current._load_session_content(data[key])  # noqa: SLF001 (View's hook for this)


@batch()
def _reset_state(view: View, initial: View) -> None:
    """Set a live view tree back to `initial`'s state, in place.

    `initial` is a freshly built instance of the same class. Copying from it, rather than
    from attrs defaults, also restores whatever its `__attrs_post_init__` set up (titles,
    `values`, an initial validator message...). Like `_apply_state`, it sets the existing
    attributes, so renderers and connected signals stay bound and only what actually
    changed is pushed to the UI. Fields `_apply_state` never restores are skipped the
    same way (omitted, frozen); a `ChoicesMixin`'s `values` is reset before its choice,
    which must be among them, and `RecordTableView.records` before the selection.
    """
    states: deque[tuple[View, View]] = deque([(view, initial)])
    while len(states) > 0:
        current_view, initial_view = states.popleft()
        current_cls = cast("type[AttrsInstance]", type(current_view))
        attrs.resolve_types(current_cls)
        choice = _choice_field(current_view)
        if isinstance(current_view, RecordTableView) and isinstance(initial_view, RecordTableView):
            current_view.records = initial_view.records
        for f in attrs.fields(current_cls):
            if (
                _is_omitted_field(f)
                or f.on_setattr is attrs.setters.frozen
                or (isinstance(current_view, ChoicesMixin) and f.name in ("values", choice))
                or (f.name in ("rows", "records") and isinstance(current_view, RecordTableView))
            ):
                continue
            current_field = getattr(current_view, f.name)
            initial_field = getattr(initial_view, f.name)
            if isinstance(current_field, View) and isinstance(initial_field, View):
                states.append((current_field, initial_field))
            else:
                setattr(current_view, f.name, initial_field)
        if isinstance(current_view, ChoicesMixin) and isinstance(initial_view, ChoicesMixin):
            current_view.values = initial_view.values
            setattr(
                current_view,
                current_view.choice_field,
                getattr(initial_view, current_view.choice_field),
            )


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class FileView(View):
    """The file path that the last file dialog of the main view gave."""

    filepath: Optional[Path] = attrs.field(default=None)
    extensions: dict[str, tuple[str, ...]] = attrs.Factory(dict[str, tuple[str, ...]])
    # file_type: FileType = attrs.field(default=FileType.OpenFile)

    @override
    def _create_renderer(self, renderer_type: RendererType) -> None:
        return None


@define_view
class MainView(View):
    """The root view of an app: its window, with the menus, the status bar and the content.

    A subclass sets `app_title`, `extension` and `translations_dir`, and adds its views as
    fields. The main view saves and loads the state of its views (`save_state`,
    `load_state`), and runs work in threads with `jobs`.
    """

    _renderer_key = "main"

    #: the web content's default width; a subclass sets it: ``width = PageWidth.WIDE``
    width: ClassVar[PageWidth] = PageWidth.NARROW

    #: the app's name, in the window's title; a subclass sets it: ``app_title = T("Pipes")``
    app_title: ClassVar[str] = ""
    #: the extension of the app's study files; a subclass sets it: ``extension = ".pipe"``
    extension: ClassVar[str] = ""
    #: the app's icon, an image file: the window's on Qt, the browser tab's and the header's
    #: on the web. ComposeUI's by default; a subclass sets its own, or None for none
    app_icon: ClassVar[Optional[Path]] = Path(__file__).parents[2] / "images" / "composeui.svg"
    #: whether the window has `file_menu`, the studies' New, Open, Save, Save As and Exit;
    #: an app without studies, e.g. a viewer, sets it to False and leaves it out
    has_file_menu: ClassVar[bool] = True
    #: the version of the app's state, saved with it: a subclass raises it when a change of
    #: its views would lose an older study's state, and upgrades the state in `migrate_state`
    state_version: ClassVar[int] = 1
    #: the largest file, in bytes, that a user can upload to the web app, 5 MiB by default, or
    #: the files of one choice together; not a study (Open has its own limit). A subclass sets it:
    #: ``max_upload_size = 200 * 1024 * 1024``
    max_upload_size: ClassVar[int] = 5 * 1024 * 1024
    #: the bytes that an upload to the web app leaves free on the disk, 1 GiB by default: the
    #: app refuses a file that goes below it. 0 refuses only when the disk is full.
    #: A subclass sets it, e.g. for a small container: ``min_free_disk = 100 * 1024 * 1024``
    min_free_disk: ClassVar[int] = 1024 * 1024 * 1024
    #: whether Qt and Textual save the unsaved work to a folder of the app's own, every
    #: `autosave_interval` seconds, and open it at the next start after a crash. False by
    #: default: a form that must start empty must not open old values
    autosave: ClassVar[bool] = False
    #: the seconds between two autosaves, while the study has unsaved changes
    autosave_interval: ClassVar[float] = 60.0
    #: a fixed name of the app's folder of autosaves, e.g. ``"pipes"``; None names it after
    #: the main view's module and class, and a script's (``__main__``) after its file
    app_id: ClassVar[Optional[str]] = None
    #: `app_title`, in the main view's language
    title: str = attrs.field(
        default=attrs.Factory(lambda self: self.app_title, takes_self=True),
        init=False,
        on_setattr=attrs.setters.frozen,
    )
    state_filepath: Optional[Path] = None

    minimum_width: int = attrs.field(default=720)
    minimum_height: int = attrs.field(default=480)

    file_menu: FileMenu = attrs.Factory(FileMenu)
    # study_toolbar: StudyToolbar = StudyToolbar(title="study")
    # a file dialog's last answer, not study data: never saved, loaded or reset
    file_view: FileView = attrs.field(factory=FileView, metadata={OMIT: True})
    #: what `download` gave without a backend, for a test to read
    _downloads: list[DownloadedFile] = attrs.field(
        factory=list, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the app's model, for the signals made later (see `set_references`); weak
    _model_reference: Optional[Callable[[], Optional[Model]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    # message_view: MessageView = MessageView()
    status_bar: StatusBar = attrs.Factory(StatusBar)
    #: a message above the page that stays until closed, such as an error (`notify`); not
    #: study data: never saved, loaded or reset
    notification: NotificationBar = attrs.field(factory=NotificationBar, metadata={OMIT: True})
    #: the question before `write_file` replaces a file that exists
    replace_file: ReplaceFileDialogView = attrs.Factory(ReplaceFileDialogView)
    #: the question before New, Open or Exit loses unsaved changes (`ask_discard_changes`)
    discard_changes: DiscardChangesDialogView = attrs.Factory(DiscardChangesDialogView)
    #: the question as the app starts after a crash, about the work its autosave kept
    restore_work: RestoreWorkDialogView = attrs.Factory(RestoreWorkDialogView)
    #: the study as last saved, opened or started (`_mark_saved`): its views' digest and the
    #: model's `Model.data_version`. None until then: nothing known to lose
    _saved_study: Optional[tuple[str, int]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: emitted once the views and the model's data are in place: as the app starts, with the
    #: study of ``-f`` or a new one, and after New and Open (after `Model.loaded`). The app
    #: gives again then what a study doesn't hold, such as the source of a large table
    loaded: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: the study file last opened or saved, and its modification time then (``st_mtime_ns``):
    #: Save asks before it writes over a file changed on disk since. None: not known
    _study_file: Optional[tuple[str, int]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the app's autosave, which `_mark_saved` tells; None without one
    _autosave: Optional[Autosave] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: functions run in threads, their results given back on the main thread
    jobs: Jobs = attrs.field(
        default=attrs.Factory(Jobs, takes_self=True),
        init=False,
        repr=False,
        eq=False,
        metadata={OMIT: True},
    )

    #: the directory of the app's catalogs, ``<language>.json`` files (see
    #: `composeui.core.translation`); a subclass sets it, e.g. to
    #: ``Path(__file__).parent / "locales"``
    translations_dir: ClassVar[Optional[Path]] = None
    #: the language the app's text is written in, shown until `set_language`
    source_language: ClassVar[str] = "en"
    #: set by `set_language`; empty while the text shows as written in the code
    _language: str = attrs.field(default="", init=False, repr=False, metadata={OMIT: True})
    #: the browser's id, or the user's account (`browser_id`), fixed as the view is built
    _browser_id: str = attrs.field(
        factory=current_browser_id, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the user that a login proxy named (`user`), fixed as the view is built
    _user: Optional[str] = attrs.field(
        factory=current_user, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the tasks that the views built as they were built start from now on
        _attach_jobs(self, self.jobs)
        for menu in self._language_menus():
            menu.set_languages(self.languages)
            for action in menu.actions:
                action.triggered.connect(functools.partial(self.set_language, action.data))
            menu.check(self.language)

    @property
    @override
    def children_views(self) -> list[View]:
        views = super().children_views
        if self.has_file_menu:
            return views
        # never rendered: no backend shows it, or binds its shortcuts
        return [view for view in views if view is not self.file_menu]

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the app's own command-line options to `parser`, e.g. a file to show.

        After the backend's (``-f``, ``--language``, ``--port``...); `apply_arguments` gets
        their values. None by default.
        """

    def apply_arguments(self, args: argparse.Namespace) -> None:
        """Apply the app's own command-line options (`add_arguments`), parsed in `args`.

        Once the main view is wired and ``-f``'s study is open: once on Qt and Textual, for
        every session on the web.
        """

    @property
    def language(self) -> str:
        """Get the language the text shows in: set with `set_language`, or the source's."""
        return self._language or self.source_language

    @property
    def languages(self) -> list[str]:
        """Get the languages the app shows: `source_language`, then the catalogs'."""
        found = (
            []
            if self.translations_dir is None
            else sorted(path.stem for path in self.translations_dir.glob("*.json"))
        )
        return list(dict.fromkeys([self.source_language, *found]))

    def set_language(self, language: str) -> None:
        """Show the text of every view in `language`, e.g. "fr" or "fr-CA".

        From the app's catalogs (`translations_dir`), then ComposeUI's; text neither
        translates shows as written in the code.
        """
        directories = [d for d in (self.translations_dir, CATALOGS_DIR) if d is not None]
        # first: `retranslate` can show it
        self._language = language
        _retranslate(self, translator(language, directories))
        for menu in self._language_menus():
            menu.check(language)

    def _language_menus(self) -> list[LanguageMenu]:
        return [view for view in self.children_views if isinstance(view, LanguageMenu)]

    def load_state(self, filepath: Path) -> None:
        """Load the state saved in a json file; see `load_state_data`."""
        with filepath.open("rb") as f:
            try:
                data = json.load(f)
            except ValueError as error:  # also covers bytes that aren't text
                msg = f"it isn't a valid {self.extension} file"
                raise InvalidStateError(msg) from error
        self.load_state_data(self.state_data_from_file(data))
        self.state_filepath = filepath

    def file_data(self) -> dict[str, Any]:
        """Get what a study file holds: the views' state (`state_data`) and its versions."""
        return {
            "composeui": {"format": STATE_FORMAT},
            "app": {"version": self.state_version},
            "views": self.state_data(),
        }

    def state_data_from_file(self, data: Any) -> Any:
        """Get the views' state from what a study file holds (`file_data`), upgraded.

        A state of an older `state_version` goes through `migrate_state`. Raises
        `InvalidStateError` for a file of a newer ComposeUI or app, or not one at all.
        """
        invalid = f"it isn't a valid {self.extension} file"
        if not isinstance(data, dict):
            raise InvalidStateError(invalid)
        if "composeui" not in data:
            # saved before the versions were: the first of each
            state_format, version, views = 1, 1, data
        else:
            try:
                state_format = data["composeui"]["format"]
                version = data["app"]["version"]
                views = data["views"]
            except (KeyError, TypeError) as error:
                raise InvalidStateError(invalid) from error
        if not _is_version(state_format) or not _is_version(version):
            raise InvalidStateError(invalid)
        if state_format > STATE_FORMAT:
            msg = "it was saved by a newer version of ComposeUI"
            raise InvalidStateError(msg)
        if version > self.state_version:
            msg = "it was saved by a newer version of this application"
            raise InvalidStateError(msg)
        if version == self.state_version:
            return views
        try:
            return self.migrate_state(views, version)
        except _BAD_STATE_ERRORS as error:
            msg = "it doesn't match this application"
            raise InvalidStateError(msg) from error

    def migrate_state(self, data: Any, version: int) -> Any:
        """Upgrade a state saved by an older `state_version` of the app, `version`.

        Return the state as `state_data` gets it now. The app overrides it when it raises
        `state_version`, e.g. to move a renamed field's value to its new name. Without an
        override, the state loads as it is: the fields it no longer has are skipped.
        """
        del version
        return data

    def load_state_data(self, data: Any) -> None:
        """Load state, as `state_data` gets it: a study file's from `state_data_from_file`.

        Raises `InvalidStateError`, leaving this view unchanged, when the data doesn't fit
        it (see `check_state_data`).
        """
        self.check_state_data(data)
        # after the check: a saved value that no longer fits drops the study, even if edited
        adapt = _RELOADED_STATE.get()
        if adapt is not None:
            data = adapt(data)
        self.jobs.drop()  # working for the study replaced
        _apply_state(self, data)
        # the study saved the `is_enabled` of the views that the tasks own (`Task.disables`,
        # `cancel_with`) as it was, e.g. during a run: set it again. The method is private
        # because only an opened study needs it; public, it would be an API that apps have no
        # use for
        self.jobs._set_enabled()  # noqa: SLF001
        _show_checked(self)

    def build_initial_view(self) -> MainView:
        """Build a new, unrendered main view of the same class in its initial state.

        By default, this calls the class without arguments. Override it if the constructor
        needs arguments. Do not share child views with the running app or start jobs here.
        ComposeUI uses the new view to check saved state, start a new study, and compare
        initial values across a reload.
        """
        return type(self)()

    def _initial_view(self) -> MainView:
        """Build the view of `build_initial_view` for this view's browser (`browser_id`).

        Outside the session's build, e.g. for New: a view that reads its id as it is built
        would read the server's account instead.
        """
        with building_for_browser(lambda: self._browser_id, self._user):
            return self.build_initial_view()

    def check_state_data(self, data: Any) -> None:
        """Raise `InvalidStateError` if the data does not fit the view.

        Apply the data to a new view from `build_initial_view`. If a field fails to load
        after other fields have loaded, this view stays unchanged. Errors from building
        the new view propagate as they are.
        """
        if not isinstance(data, dict):
            msg = f"it isn't a valid {self.extension} file"
            raise InvalidStateError(msg)
        initial = self._initial_view()
        try:
            _apply_state(initial, data)
        except _BAD_STATE_ERRORS as error:
            msg = "it doesn't match this application"
            raise InvalidStateError(msg) from error

    def state_data(self) -> Any:
        """Get the state `save_state` writes, before it's turned into json."""
        return CONVERTER.unstructure(self)

    def reset_state(self) -> None:
        """Set every view back to the state from `build_initial_view` (a new study).

        The tree is reset in place, as `load_state` loads into it, so renderers and
        connected signals keep working.
        """
        _check_main_thread("MainView.reset_state")
        initial = self._initial_view()
        self.jobs.drop()  # working for the study replaced
        _reset_state(self, initial)
        _show_checked(self)
        # the new view's text is as written in the code
        _retranslate(self, self._tr)
        # the reset copied the `is_enabled` of the tasks' views from the new view, whose
        # fields may differ from this one's: a condition of `Task.disables` may read a field
        # that New keeps, as the study doesn't hold it (see `load_state_data`)
        self.jobs._set_enabled()  # noqa: SLF001

    def save_state(self, filepath: Path) -> None:
        """Save the current state into a json file, with its versions (`file_data`)."""
        path = filepath.resolve()
        with partial_path(path) as partial:
            with partial.open("w") as f:
                json.dump(self.file_data(), f)
            _publish(partial, path)
        self.state_filepath = filepath

    def has_unsaved_changes(self) -> bool:
        """Tell whether the study changed since it was last saved, opened or started.

        It compares what Save would write: the views' state and the model's data (see
        `Model.data_version`). A change undone is no change; nor is UI text, a dialog, the
        status bar's message, a notification, or the study's file name.
        """
        return self._saved_study is not None and self._saved_study != self._study_mark()

    def _remember_study_file(self, path: Path) -> None:
        """Remember the study file `path`, as opened or saved now: its modification time."""
        self._study_file = (str(path), path.stat().st_mtime_ns)

    def _is_study_file_changed(self, path: Path) -> bool:
        """Tell whether the study file `path` changed on disk since it was opened or saved.

        False when it's not known, e.g. a path the app set, or when the file is gone.
        """
        known = self._study_file
        if known is None or known[0] != str(path):
            return False
        try:
            return path.stat().st_mtime_ns != known[1]
        except FileNotFoundError:
            return False

    def _is_saved(self) -> bool:
        """Tell whether the study is as last saved, opened or started: once one was."""
        return self._saved_study is not None and self._saved_study == self._study_mark()

    def _mark_saved(self) -> None:
        """Take the study as it is now as saved: `has_unsaved_changes` is False until a change.

        The app's start, New, Open and Save do it, and a job started with the study once it
        gave its result (`starting_study`).
        """
        self._saved_study = self._study_mark()
        if self._autosave is not None:
            self._autosave.forget()  # older than the study saved, opened or started

    def _mark_unsaved(self) -> None:
        """Take the study as changed, whatever it holds: e.g. a reload restoring it unsaved."""
        self._saved_study = _UNSAVED_STUDY

    def _study_mark(self, state: Any = None) -> tuple[str, int]:
        """Get the study's mark, of the views' `state` (`state_data`) if given, else now's."""
        views = dict(self.state_data() if state is None else state)
        # the name of the user's file, which the web's Save keeps apart from what it writes,
        # and a passing message, e.g. why Open failed
        views.pop("state_filepath", None)
        views["status_bar"] = {k: v for k, v in views["status_bar"].items() if k != "message"}
        digest = hashlib.blake2b(json.dumps(views).encode(), digest_size=16).hexdigest()
        model = None if self._model_reference is None else self._model_reference()
        return digest, 0 if model is None else model.data_version

    def notify(self, message: str, kind: LogType = LogType.INFO) -> None:
        """Show `message` above the page, as `kind`, instead of the message shown.

        A warning or an error stays until the user closes it or `clear_notification`, an
        information for `notification`'s timeout. The status bar suits a passing message,
        such as "Saved".
        """
        self.notification.show(message, kind)

    def clear_notification(self) -> None:
        """Remove the message that `notify` shows, if any."""
        self.notification.clear()

    @property
    def client(self) -> ClientCapabilities:
        """Get what the app can do for its user, from where it runs for them.

        Each backend sets it, and `WebSettings.client` on the web. Read it only to hide or
        change a control, such as an "Open folder" button where `can_open_on_desktop` is
        False: `open_folder`, `open_file`, `open_url` and `display_path` adapt by
        themselves. It is set before the app builds its main view.
        """
        return current_client()

    @property
    def browser_id(self) -> str:
        """Get a lasting id of the user's browser on the web; elsewhere, of their account.

        Label what the app keeps with it to show a browser its own work first, such as the
        studies it opened, from every one of its visits. On the web, every tab of a browser
        has the same id, and so has each of its sessions for `WebSettings.browser_ttl` after
        its last visit, also after a restart of a server with a `session_folder`. Another
        browser, a private window or cleared cookies get another id. On Qt and Textual, it
        is the name of the account that runs the app (``getpass.getuser``), the same for
        each user of a served terminal app. It never changes for a main view, and is known
        once the main view is made. It is no user, and no proof of one: never grant access
        by it.
        """
        return self._browser_id

    @property
    def user(self) -> str | None:
        """Get the name of the user whom a login proxy let in, on the web; else None.

        A web server with `WebSettings.user_header` reads it from that header, which the
        proxy sets on each request. Each session belongs to its user: another user, even in
        the same browser, gets a session and a `browser_id` of their own. Without a login,
        on Qt and Textual, and on the web without `user_header`, it is None. It never
        changes for a main view, and is known once the main view is made.
        """
        return self._user

    def open_folder(self, path: Path) -> None:
        """Open the folder `path` in the user's file manager: Windows' Explorer in WSL.

        Where the app can't reach the user's desktop (`client`), e.g. on a web server, the
        page says so above it (`notify`). So it does for a folder that isn't there, or a
        file manager that doesn't start. Call it on the main thread.
        """
        _check_main_thread("MainView.open_folder")
        self._open_on_desktop(path, is_folder=True, download=False)

    def open_file(self, path: Path, *, download: bool = False) -> None:
        """Open the file `path` in the app that the user's desktop opens it with.

        Where the app can't reach the user's desktop (`client`), the page says so above it
        (`notify`), or with `download` gives the user the file (`MainView.download`), e.g.
        a report. So it does for a file that isn't there, or an app that doesn't start.
        Call it on the main thread.
        """
        _check_main_thread("MainView.open_file")
        self._open_on_desktop(path, is_folder=False, download=download)

    def open_url(self, url: str) -> None:
        """Open `url` in the user's browser: in a new tab on the web.

        Only ``http`` and ``https`` URLs open: another raises `ValueError`.
        Where the app reaches neither the browser nor the desktop, e.g. Textual over SSH,
        the page shows the URL for the user to open. Call it on the main thread.
        """
        _check_main_thread("MainView.open_url")
        check_url(url)
        if isinstance(self.renderer, MainRenderer) and self.renderer.open_url(url):
            return
        if self.client.can_open_on_desktop:
            self._launch(url, url)
        else:
            self.notify(self.tr("Open {url} in your browser.").format(url=url), LogType.WARNING)

    def display_path(self, path: Path, roots: Iterable[Path] = ()) -> str:
        """Get the text that names `path` for the user.

        The whole path where the user shares the app's files (`client`). Elsewhere, a
        server's path means nothing to the user: inside one of `roots`, e.g. a field's
        `server_roots`, the path from that root, its name first (``results/run-3``); else
        the name alone.
        """
        if self.client.shares_files:
            return str(path)
        for root in roots:
            if is_within_roots(path, (root,)):
                folder = root.expanduser().resolve()
                inside = path.expanduser().resolve().relative_to(folder)
                return PurePosixPath(folder.name, *inside.parts).as_posix()
        return path.name

    def _open_on_desktop(self, path: Path, *, is_folder: bool, download: bool) -> None:
        name = self.display_path(path)
        on_desktop = self.client.can_open_on_desktop
        if not on_desktop and not download:
            elsewhere = self.tr("Can't open {name} here: the app runs on another computer.")
            self.notify(elsewhere.format(name=name), LogType.WARNING)
        elif not (path.is_dir() if is_folder else path.is_file()):
            missing = self.tr("Can't open {name}: it isn't there.")
            self.notify(missing.format(name=name), LogType.ERROR)
        elif on_desktop:
            self._launch(str(path), name)
        else:
            self.download(path.name, path)

    def _launch(self, target: str, name: str) -> None:
        """Open `target` on the desktop; say why above the page if it can't."""
        try:
            launch(target)
        except (OSError, subprocess.SubprocessError) as error:
            failed = self.tr("Can't open {name}: {error}.")
            self.notify(failed.format(name=name, error=error), LogType.ERROR)

    def ask_discard_changes(self, proceed: Callable[[], object]) -> None:
        """Call `proceed()` now if the study has no unsaved changes, else once the user agrees.

        New, Open and Exit ask through the `discard_changes` dialog; Cancel leaves the study
        as it is. An app asks too before it replaces the study its own way. Without a File
        menu (`has_file_menu`), the user can't save, so it never asks.
        """
        if not self.has_file_menu or not self.has_unsaved_changes():
            self.discard_changes.forget()  # a question still open is about other changes
            proceed()
            return
        self.discard_changes.ask(proceed)

    def can_hibernate(self) -> bool:
        """Tell whether the web may save this session to disk while it's idle, and free it.

        See `WebSettings.session_idle`. An app returns False while the session holds what
        its views' state and its model's data don't, e.g. an object that a callback built
        from the user's input: the session then stays in memory.
        """
        return True

    def ask_open_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.open_file()
        return self.file_view.filepath

    def write_file(
        self, target: Union[SavePathInputMixin, Path], write: Callable[[Path], object]
    ) -> None:
        """Call `write(path)` to write a file, once the user agrees to replace one that exists.

        `target` is a save path field, whose `path` it writes, or a path. Nothing happens
        while the field is empty. A field asks with its own texts, and only once: not again
        when the user already agreed in its picker (`SavePathInputMixin.is_replace_agreed`).
        The app's `write` writes the file; Cancel writes nothing. Give `write` the data as
        it is now, e.g. with `functools.partial`: the answer comes later.
        """
        dialog = self.replace_file
        if isinstance(target, Path):
            dialog.title, dialog.accept_text = "", self.tr("Replace")
            dialog.save(target, write)
            return
        path = target.path
        if path is None:
            return
        dialog.title, dialog.accept_text = target.browse_text, target.replace_text
        dialog.save(
            path, write, is_agreed=target.is_replace_agreed, question=target.replace_question_text
        )

    def ask_save_filepath(self, extensions: dict[str, tuple[str, ...]]) -> Optional[Path]:
        self.file_view.extensions = extensions
        if isinstance(self.renderer, MainRenderer):
            self.file_view.filepath = self.renderer.save_file()
        return self.file_view.filepath

    def download(
        self,
        filename: str,
        content: Union[bytes, Path, StreamContent],
        media_type: Optional[str] = None,
    ) -> None:
        """Give the user a file that the app made, e.g. a report, to save where they choose.

        `content` is the file's bytes, the path of a file that the app wrote, read when the
        user saves it and never deleted, or a `StreamContent`, which writes the file as the
        user receives it. `filename` names the file; `media_type` says what it holds,
        guessed from `filename` when None. The web downloads it in the browser. Qt and
        Textual ask where to save it, then write it, and say how it went.
        Call it on the main thread, e.g. from a job's `finished` callback. While no backend
        shows the main view, e.g. in a test, `downloads` keeps the file.
        """
        _check_main_thread("MainView.download")
        # a name, never a folder: the browser or the dialog picks the folder
        name = re.split(r"[\\/]", filename)[-1] or "download"
        if media_type is None:
            media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        file = DownloadedFile(name, content, media_type)
        if isinstance(self.renderer, MainRenderer):
            self.renderer.download(file)
        else:
            self._downloads.append(file)

    @property
    def downloads(self) -> Sequence[DownloadedFile]:
        """Get the files `download` gave while no backend showed the main view, e.g. in a test."""
        return self._downloads

    @override
    def render(self, renderer_type: RendererType) -> None:
        super().render(renderer_type)
        if self.renderer is not None:
            # the jobs started before, e.g. by `setup_model`, show their results now
            self.jobs.hand_over_to(self.renderer)

    def close(self) -> None:
        self.jobs.drop()
        if isinstance(self.renderer, MainRenderer):
            self.renderer.close()


# `View._main_view` names it, which attrs resolves in `base`'s module: there, as `base` can't
# import this module, which imports it
vars(base)["MainView"] = MainView
