"""The dialogs: questions to the user, and the forms and content they show."""

from __future__ import annotations

import enum
import functools
from collections import deque
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Optional,
    TypeVar,
)

import attrs
from typing_extensions import override

from composeui.core import reactivity
from composeui.core._views.base import OMIT, UI_TEXT, View, catching_context, define_view
from composeui.core._views.content import LogType, LogView, Validator
from composeui.core._views.controls import DialogButtonView
from composeui.core._views.forms import FormT, FormView
from composeui.core.model import RefusedError
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
    translate_again,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from typing_extensions import Unpack


class DialogKind(enum.Enum):
    """The kind of a `DialogView`: a message or a confirmation."""

    #: tells the user something: one button, accepting
    MESSAGE = enum.auto()
    #: asks the user to confirm: an accepting and a rejecting button
    CONFIRM = enum.auto()


def _do_nothing() -> None:
    """Go on with nothing: what a question not asked would do once answered."""


#: the answers of a question not asked, or answered already: nothing goes on
_NOT_ASKED = (_do_nothing, _do_nothing)


@define_view
class DialogView(View):
    """A modal message or confirmation, shown from `open` until the user answers.

    Nothing waits for the answer, since a web request can't: it comes through
    `accepted` or `rejected`, once the dialog is closed. A dialog is what the app asks,
    not study data: never saved, loaded or reset.

    `ask` opens it and calls a function of the app once it's answered, instead of a
    callback of `accepted` that would need to know what the question was about.

    A confirmation that loses something once accepted, such as deleting files, sets
    `is_destructive`: the focus goes to the rejecting button, so Enter rejects, and the
    accepting button shows as dangerous.
    """

    _renderer_key = "dialog"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    kind: DialogKind = attrs.field(default=DialogKind.MESSAGE)
    accept_text: str = attrs.field(default=T("OK"), metadata={UI_TEXT: True})
    #: the rejecting button's text; a message has no such button
    reject_text: str = attrs.field(default=T("Cancel"), metadata={UI_TEXT: True})
    #: whether accepting loses something: Enter then rejects; a message or form ignores it
    is_destructive: bool = attrs.field(default=False)

    accepted: SignalNoArgs = attrs.Factory(SignalNoArgs)
    rejected: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: what accepting and rejecting call, while the question `ask` asked isn't answered
    _asked: tuple[Callable[[], object], Callable[[], object]] = attrs.field(
        default=_NOT_ASKED, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # shown only once opened
        self.is_visible = False

    def open(self) -> None:
        """Show the dialog; its answer comes through `accepted` or `rejected`.

        Opening a closed dialog forgets the functions of a question asked before it closed.
        """
        if not self.is_visible:
            self._asked = _NOT_ASKED
        self.is_visible = True

    def ask(
        self, on_accept: Callable[[], object], on_reject: Optional[Callable[[], object]] = None
    ) -> None:
        """Open the dialog, and call `on_accept()` or `on_reject()` once the user answers.

        Only the answer's function is called, once, before `accepted` or `rejected` fires.
        A new `ask` before the answer replaces both. A button of the dialog's own that closes
        it calls neither.
        """
        self.open()
        self._asked = (on_accept, _do_nothing if on_reject is None else on_reject)

    def forget(self) -> None:
        """Close the dialog, if it's open, without calling what `ask` was given."""
        self._asked = _NOT_ASKED  # `open` would drop them too: free what they hold now
        self.is_visible = False

    def accept(self) -> None:
        """Close the dialog with its accepting answer; ignored unless it's open."""
        if self.is_visible:
            self._answer(0, self.accepted)

    def reject(self) -> None:
        """Close the dialog with its rejecting answer; ignored unless it's open."""
        if self.is_visible:
            self._answer(1, self.rejected)

    def _answer(self, index: int, signal: SignalNoArgs) -> None:
        self.is_visible = False
        asked, self._asked = self._asked, _NOT_ASKED  # free what they hold once answered
        # as if a callback of the signal: the reactive methods run once, after both
        with reactivity.batch():
            asked[index]()
            signal.emit()

    def dismiss(self) -> None:
        """Close the dialog without a button (e.g. Escape): a confirmation is rejected.

        A message has only one answer, so dismissing it accepts it.
        """
        if self.kind is DialogKind.CONFIRM:
            self.reject()
        else:
            self.accept()


@define_view
class ReplaceFileDialogView(DialogView):
    """A question before saving over a file that exists, e.g. a path typed: Replace or Cancel.

    The main view's own, which `MainView.write_file` asks. `save` writes at once a file
    that doesn't exist yet, else once the user agrees to replace it. The app's own function
    writes: the dialog only decides when. Cancel writes nothing, and the file stays as it is.
    """

    kind: DialogKind = attrs.field(default=DialogKind.CONFIRM)
    accept_text: str = attrs.field(default=T("Replace"), metadata={UI_TEXT: True})
    is_destructive: bool = attrs.field(default=True)

    def save(
        self,
        path: Path,
        write: Callable[[Path], object],
        *,
        is_agreed: bool = False,
        question: str = T("{name} already exists. Replace it?"),
    ) -> None:
        """Call `write(path)` now if no file is at `path`, else once the user agrees to replace it.

        With `is_agreed`, at once too: the user already agreed. `question` asks, its
        ``{name}`` the file's. A new `save` before the answer replaces the file and the
        function, and closes the question if it writes at once.
        """
        if is_agreed or not (path.exists() or path.is_symlink()):
            self.forget()  # a question still open is about another file
            write(path)
            return
        self.text = translate_again(question, self._tr).format(name=path.name)
        self.ask(functools.partial(write, path))


@define_view
class DiscardChangesDialogView(DialogView):
    """A question before the study's unsaved changes are lost, e.g. by New: Discard or Cancel.

    The main view's own, which `MainView.ask_discard_changes` asks. The app's own function
    goes on once the user agrees: the dialog only decides when. Cancel leaves the study as
    it is.
    """

    kind: DialogKind = attrs.field(default=DialogKind.CONFIRM)
    text: str = attrs.field(
        default=T("The study has unsaved changes. Discard them?"), metadata={UI_TEXT: True}
    )
    accept_text: str = attrs.field(default=T("Discard"), metadata={UI_TEXT: True})
    is_destructive: bool = attrs.field(default=True)


#: what Save asks before it replaces a study file changed on disk, its ``{name}`` the file's
_CHANGED_ON_DISK_QUESTION = T("{name} changed on disk since it was opened. Replace it?")
#: the answers of a `RestoreWorkDialogView` not asked, or answered already: nothing goes on
_NOT_ASKED_RESTORE = (_do_nothing, _do_nothing, _do_nothing)
#: the question `RestoreWorkDialogView` asks, its ``{time}`` the work's
_RESTORE_WORK_QUESTION = T("The app closed without saving. Restore the unsaved work of {time}?")


@define_view
class RestoreWorkDialogView(DialogView):
    """A question as the app starts after a crash: restore the unsaved work it left, or discard it.

    The main view's own, which its autosave asks (`MainView.autosave`). Closing the question
    without a button, e.g. with Escape, keeps the work for the next start.
    """

    kind: DialogKind = attrs.field(default=DialogKind.CONFIRM)
    accept_text: str = attrs.field(default=T("Restore"), metadata={UI_TEXT: True})
    reject_text: str = attrs.field(default=T("Discard"), metadata={UI_TEXT: True})
    #: what Restore, Discard and closing the question do, while the user hasn't answered
    _answers: tuple[Callable[[], object], Callable[[], object], Callable[[], object]] = attrs.field(
        default=_NOT_ASKED_RESTORE, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.accepted.connect(functools.partial(self._restore_answer, 0))
        self.rejected.connect(functools.partial(self._restore_answer, 1))

    def ask_restore(
        self,
        saved: str,
        *,
        restore: Callable[[], object],
        discard: Callable[[], object],
        later: Callable[[], object],
    ) -> None:
        """Ask about the work saved at `saved`, a time; one of the functions goes on."""
        self._answers = (restore, discard, later)
        self.text = translate_again(_RESTORE_WORK_QUESTION, self._tr).format(time=saved)
        self.open()

    @override
    def dismiss(self) -> None:
        """Close the question without a button: the work waits for the next start."""
        self.is_visible = False
        self._restore_answer(2)

    def _restore_answer(self, index: int) -> None:
        answers, self._answers = self._answers, _NOT_ASKED_RESTORE
        answers[index]()


@define_view
class OkCancelDialogView(DialogView):
    """A modal showing a view above its buttons: Cancel, its own, then OK.

    The base of `ContentDialogView` and `TypedFormDialogView`. Its own buttons are its
    `DialogButtonView` fields (`buttons`), e.g. Apply. Its own checks (`add_check`) are
    about any view it shows: while one fails, its message shows above the buttons, and OK
    can't be pressed. The answer comes through `accepted` or `rejected`. To do the work of
    OK while the dialog is open, e.g. a save that the model may refuse, connect to
    `accepting` and do it in `refusing`. A refusal then keeps the dialog open. `show_message`
    tells the user something else there, e.g. that Apply saved the changes.
    """

    #: whether OK can be pressed, as the app or the form says; a failing check also stops it
    is_accept_enabled: bool = attrs.field(default=True)
    #: a check of the dialog's own failed when last run (`validate`)
    has_failing_check: bool = attrs.field(default=False, init=False)
    #: the message of the dialog's own checks, above its buttons
    log_view: LogView = attrs.field(factory=LogView)
    #: the user pressed OK and every check passed: the dialog is still open
    accepting: SignalNoArgs = attrs.Factory(SignalNoArgs)
    _checks: list[Validator] = attrs.field(
        factory=list, init=False, repr=False, metadata={OMIT: True}
    )
    #: the work of the answer being given refused its change: the dialog stays open
    _is_refused: bool = attrs.field(
        default=False, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the message shown is an answer's, a refusal or `show_message`, not the checks'
    _shows_answer: bool = attrs.field(
        default=False, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    if TYPE_CHECKING:

        @property
        def content(self) -> View:
            """Get the view the dialog shows above its buttons."""

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.log_view.is_visible = False
        for button in self.buttons:
            button._answer_click = functools.partial(self.click, button)  # noqa: SLF001

    @property
    def buttons(self) -> list[DialogButtonView]:
        """Get the dialog's own buttons, in order: they show between Cancel and OK."""
        return [view for view in self.children_views if isinstance(view, DialogButtonView)]

    @property
    def can_accept(self) -> bool:
        """Whether OK can be pressed: enabled, and no check of the dialog's own fails."""
        return self.is_accept_enabled and not self.has_failing_check

    @property
    def is_valid(self) -> bool:
        """Whether no check shown fails; as last checked: a check not run yet passes."""
        return not self.has_failing_check

    def add_check(self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]) -> None:
        """Register a check of the dialog's own, run again whenever any of `signals` fires.

        `validator` returns the message to show, or None when it passes. Like a form's
        (`FormView.add_validator`), but about any view the dialog shows. It doesn't run
        now: call `validate` for a first check. OK runs every check.
        """
        self._checks.append(validator)
        for signal in signals:
            signal.connect(self.validate)

    def validate(self, *_args: Any) -> None:
        """Run the dialog's own checks, and show the message of each failing one.

        Takes (and ignores) any positional args, to be connected to signals of any arity.
        """
        messages = [message for message in (check() for check in self._checks) if message]
        self._show_messages(messages)
        self._shows_answer = False
        self.has_failing_check = len(messages) > 0
        self._follow_checks()

    @override
    @catching_context
    def refusing(self, message: str) -> Iterator[None]:
        """Show the model's refusal of the block's change in the dialog, which stays open.

        As `View.refusing`, but the message shows above the dialog's buttons, as a failing
        check's does, rather than in the status bar. In `accepting`, or in the `clicked` of
        a button of its own that closes, the refusal keeps the dialog open. The next click,
        or the next opening, takes the message away.
        """
        try:
            yield
        except RefusedError as error:
            self._is_refused = True
            self._show_messages([self._refusal(message, error)])
            self._shows_answer = True

    def show_message(self, message: str) -> None:
        """Show `message` above the dialog's buttons, e.g. "Saved" after Apply: not an error.

        It doesn't keep the dialog open, nor stop OK. The next click, a check running again,
        or the next opening takes it away.
        """
        self.log_view.log_message = message
        self.log_view.log_type = LogType.INFO
        self.log_view.is_visible = message != ""
        self._shows_answer = True

    def check(self) -> None:
        """Run every check of the dialog now."""
        self.validate()

    @override
    def accept(self) -> None:
        """Close the dialog with its accepting answer, once every check passes.

        Ignored unless it's open; while a check fails, it stays open, showing why.
        """
        if not self.is_visible:
            return
        self._forget_answer()
        self.check()
        if not self.can_accept:
            return
        self.accepting.emit()
        if not self._is_refused:
            super().accept()

    def click(self, button: DialogButtonView) -> None:
        """Answer a click of `button`, one of its own: check, fire `clicked`, then close.

        Ignored unless the dialog is open, or while a check fails and the button checks. It
        closes only for a button that closes, and unless `clicked` refused the change.
        """
        if not self.is_visible:
            return
        self._forget_answer()
        if button.checks:
            self.check()
            if not self.is_valid:
                return
        button.clicked.emit()
        if button.closes and not self._is_refused:
            self.is_visible = False

    @override
    def open(self) -> None:
        """Show the dialog, without the message of an earlier answer."""
        self._forget_answer()
        super().open()

    def _forget_answer(self) -> None:
        # a new answer, or a new opening: the message of the checks, as they last ran
        self._is_refused = False
        if self._shows_answer:
            self.validate()

    def _show_messages(self, messages: list[str]) -> None:
        """Show `messages` above the buttons, each an error; none hides the message."""
        if len(messages) > 0:
            self.log_view.log_message = "- " + "\n- ".join(messages)
            self.log_view.log_type = LogType.ERROR
        else:
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO
        self.log_view.is_visible = len(messages) > 0

    def _follow_checks(self) -> None:
        for button in self.buttons:
            button.is_blocked = button.checks and not self.is_valid


@define_view
class TypedFormDialogView(OkCancelDialogView, Generic[FormT]):
    """A modal holding a form, e.g. editing a record from its Edit button, with OK and Cancel.

    Pass a form, or give a subclass its typed ``form`` default. Its `text` shows above it. OK can't
    be pressed while a check of the form fails (`is_accept_enabled`). Accepting runs every
    check first, even one the user hasn't triggered yet, and the dialog stays open while
    one fails. The answer comes through `accepted` or `rejected`. The form keeps its
    values, for the app to read, or to fill before opening the dialog again.
    """

    _renderer_key = "form_dialog"

    form: FormT = attrs.field()

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        forms: list[FormView] = [self.form]
        while len(forms) > 0:
            form = forms.pop()
            form.checked.connect(self._follow_form)
            for row in form.field_rows:
                if isinstance(row, FormView):
                    forms.append(row)
                else:
                    row.checked.connect(self._follow_form)
        self._follow_form()

    @property
    @override
    def is_valid(self) -> bool:
        """Whether no check shown fails, the form's or the dialog's own."""
        return self.form.is_valid and super().is_valid

    @override
    def open(self) -> None:
        """Show the dialog, OK as the form's checks last left it."""
        self._follow_form()
        super().open()

    @override
    def check(self) -> None:
        """Run every check now: the form's, then the dialog's own."""
        self.form.check()
        super().check()

    @property
    @override
    def content(self) -> FormT:
        """Get the view the dialog shows: its form."""
        return self.form

    def _follow_form(self) -> None:
        self.is_accept_enabled = self.form.is_valid
        self._follow_checks()


@define_view
class FormDialogView(TypedFormDialogView[FormView]):
    """A form dialog with a default empty `FormView`, with OK and Cancel.

    Use `TypedFormDialogView` to declare a subclass with a more specific form type.
    Both classes use the same validation, signals, and renderers.
    """

    form: FormView = attrs.Factory(FormView)


ContentT = TypeVar("ContentT", bound=View)


@define_view
class ContentDialogView(OkCancelDialogView, Generic[ContentT]):
    """A modal holding a view, e.g. a table to pick a file from, with OK and Cancel.

    Pass the view as ``content``, or give a subclass its typed ``content`` default. Its
    `text` shows above it. The app sets `is_accept_enabled`, e.g. once a row is selected:
    OK can't be pressed before. The answer comes through `accepted` or `rejected`. A
    button of the content acts without closing the dialog. To keep it open on OK too,
    e.g. to show the folder selected rather than open it, a subclass overrides `accept`
    and calls ``super().accept()`` only to close it.
    """

    _renderer_key = "content_dialog"

    content: ContentT = attrs.field()


def dialogs_in(view: View) -> list[DialogView]:
    """Get the dialogs under `view`, not those inside another dialog."""
    dialogs: list[DialogView] = []
    views = deque(view.children_views)
    while len(views) > 0:
        current = views.popleft()
        if isinstance(current, DialogView):
            dialogs.append(current)
        else:
            views.extend(current.children_views)
    return dialogs
