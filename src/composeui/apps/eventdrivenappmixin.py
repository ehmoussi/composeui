from composeui.commontypes import AnyMainView, AnyModel
from composeui.core import disconnect
from composeui.core.basesignal import BaseSignal
from composeui.core.connect import connect_by_default
from composeui.core.initialize import initialize_default_view
from composeui.core.views.view import View
from composeui.form.formview import FormView, RowItemView
from composeui.model.basemodel import BaseModel

import weakref
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import fields
from typing import Generic, Optional, Tuple


class EventDrivenAppMixin(ABC, Generic[AnyMainView, AnyModel]):

    def __init__(self) -> None:
        super().__init__()
        self._main_view: Optional[AnyMainView] = None
        self._model: Optional[AnyModel] = None

    @abstractmethod
    def initialize_app(self) -> None: ...

    @abstractmethod
    def connect_app(self) -> None: ...

    def initialize(self) -> None:
        assert self._main_view is not None
        assert self._model is not None
        self._add_app_to_base_signal(self._main_view, self._model, self)
        initialize_default_view(self._main_view)
        self.initialize_app()

    def connect(self) -> None:
        assert self._main_view is not None
        assert self._model is not None
        connect_by_default(self._main_view, self._main_view)
        self.connect_app()

    def disconnect(self) -> None:
        assert self._main_view is not None
        disconnect.disconnect(self._main_view)

    def new_study(self) -> None:
        assert self._main_view is not None
        assert self._model is not None
        self._model.new()
        self.disconnect()
        self.initialize()
        self.connect()

    @staticmethod
    def _add_app_to_base_signal(
        main_view: View, model: BaseModel, app: "EventDrivenAppMixin[AnyMainView, AnyModel]"
    ) -> None:
        views: deque[  # type:ignore[type-arg]
            Tuple[Optional[FormView], Optional[View], View]
        ] = deque()
        views.append((None, None, main_view))
        while len(views) > 0:
            current_form_view, current_parent_view, current_view = views.popleft()
            for view_field in fields(current_view):
                try:
                    current_field = getattr(current_view, view_field.name)
                except AttributeError:
                    msg = (
                        f"Missing a default value or a default factory for the field "
                        f"'{view_field.name}' of '{current_view.__class__.__name__}'. "
                        "It can also be defined in the __post_init__ method. "
                        "This is mandatory for using it without its implementation "
                        "(e.g. in a test environment)."
                    )
                    raise AttributeError(msg) from None
                if view_field.type is BaseSignal:
                    if current_form_view is not None:
                        current_field.current_form_view = weakref.ref(current_form_view)
                    if current_parent_view is not None:
                        current_field.current_parent_view = weakref.ref(current_parent_view)
                    current_field.current_view = weakref.ref(current_view)
                    current_field.main_view = weakref.ref(main_view)
                    current_field.model = weakref.ref(model)
                    current_field.event_driven_app = weakref.ref(app)
                elif isinstance(current_field, View):
                    if isinstance(current_field, RowItemView) and isinstance(
                        current_parent_view, FormView
                    ):
                        views.append((current_parent_view, current_view, current_field))
                    else:
                        views.append((None, current_view, current_field))
