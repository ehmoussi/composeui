"""LLM conversation UI."""

from composeui import form
from composeui.core import tools
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.formview import (
    GroupBoxApplyFormView,
    LabelComboBoxView,
    LabelTextEditView,
    TextEditType,
)
from composeui.network import network
from composeui.network.networkmanager import HttpMethod, NetworkManager

import json
import typing
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple

if typing.TYPE_CHECKING:
    from examples.network.app import Model
    from examples.network.example import ExampleMainView


class LLMItems(AbstractFormItems["Model", "LLMView"]):
    def __init__(self, model: "Model", view: "LLMView") -> None:
        super().__init__(model, view)

    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        if field == "llm":
            return self._model.get_current_llm()
        elif field == "question":
            return ""
        elif field == "conversation":
            return self._model.build_conversation()
        return super().get_value(field, parent_fields)

    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        if field == "llm":
            try:
                self._model.root.current_index_llm = self._model.root.llms.index(str(value))
            except ValueError:
                return False
            return True
        elif field == "question":
            self._model.root.questions.append(str(value))
            return True
        return super().set_value(field, value, parent_fields)

    def acceptable_values(
        self, field: str, parent_fields: Tuple[str, ...] = ()
    ) -> Optional[Sequence[Any]]:
        if field == "llm":
            return self._model.root.llms
        return super().acceptable_values(field, parent_fields)


@dataclass(eq=False)
class LLMView(GroupBoxApplyFormView[LLMItems]):
    conversation: LabelTextEditView[LLMItems] = field(
        init=False, repr=False, default_factory=LabelTextEditView
    )
    llm: LabelComboBoxView[LLMItems] = field(
        init=False, repr=False, default_factory=LabelComboBoxView
    )
    question: LabelTextEditView[LLMItems] = field(
        init=False, repr=False, default_factory=LabelTextEditView
    )


def fill_llms(*, main_view: "ExampleMainView", model: "Model") -> None:
    if main_view.network_manager.response != b"":
        json_response = json.loads(main_view.network_manager.response)
        model.root.llms = [model_info["name"] for model_info in json_response["models"]]
    tools.update_view_with_dependencies(main_view.llm)


def append_last_question(view: LLMView, model: "Model") -> None:
    view.conversation.field_view.append_text(model.get_last_html_question())
    view.question.field_view.text = ""


def run_llm(*, view: LLMView, main_view: "ExampleMainView", model: "Model") -> None:
    append_last_question(main_view.llm, model)
    network.fetch(
        main_view,
        "http://localhost:11434/api/chat",
        HttpMethod.POST,
        json.dumps(
            {
                "model": model.root.llms[view.llm.field_view.current_index],
                "messages": model.build_ollama_messages(),
                "stream": False,
            }
        ).encode(),
        reply_callbacks=[write_content],
    )


def write_content(
    *, view: NetworkManager, main_view: "ExampleMainView", model: "Model"
) -> None:
    response = view.response
    if response != b"":
        json_response = json.loads(response)
        model.root.answers.append(json_response["message"]["content"])
        main_view.llm.conversation.field_view.append_text(model.get_last_html_answer())


async def run_llm_async(
    *, view: LLMView, main_view: "ExampleMainView", model: "Model"
) -> None:
    append_last_question(main_view.llm, model)
    answer = ""
    view.conversation.field_view.append_text(model.get_answer_html_header())
    response = b""
    async for chunk_response in network.fetch_stream_async(
        main_view,
        "http://localhost:11434/api/chat",
        HttpMethod.POST,
        json.dumps(
            {
                "model": model.root.llms[view.llm.field_view.current_index],
                "messages": model.build_ollama_messages(),
                "stream": True,
            }
        ).encode(),
    ):
        response += chunk_response
        index = response.find(b"\n")
        while index >= 0:
            json_response = json.loads(response[: index + 1])
            partial_answer = json_response["message"]["content"]
            answer += partial_answer
            view.conversation.field_view.append_text(model.clean_answer(partial_answer))
            response = response[index + 1 :]
            index = response.find(b"\n")
    view.conversation.field_view.append_text(model.get_answer_html_footer())
    model.root.answers.append(answer)


def initialize_form(view: LLMView, model: "Model") -> None:
    form.initialize_form_view_items(view, LLMItems(model, view))
    view.title = "LLM"
    view.conversation.field_view.minimum_height = 400
    view.conversation.field_view.is_read_only = True
    view.conversation.field_view.text_type = TextEditType.HTML
    view.apply_button_text = "Ask"


def fetch_llms(*, main_view: "ExampleMainView") -> None:
    network.fetch(
        main_view,
        "http://localhost:11434/api/tags",
        HttpMethod.GET,
        reply_callbacks=[fill_llms],
    )


async def fetch_llms_async(*, main_view: "ExampleMainView", model: "Model") -> None:
    await network.fetch_async(
        main_view,
        "http://localhost:11434/api/tags",
        HttpMethod.GET,
    )
    fill_llms(main_view=main_view, model=model)


def connect_llm(*, llm_view: LLMView, main_view: "ExampleMainView") -> None:
    main_view.on_start.append(fetch_llms)
    main_view.toolbar.file.new.triggered.append_final_callback(fetch_llms)
    main_view.menu.file.new.triggered.append_final_callback(fetch_llms)
    llm_view.apply_clicked.append(run_llm)


def connect_llm_async(*, llm_view: LLMView, main_view: "ExampleMainView") -> None:
    main_view.on_start.append(fetch_llms_async)
    main_view.toolbar.file.new.triggered.append_final_callback(fetch_llms_async)
    main_view.menu.file.new.triggered.append_final_callback(fetch_llms_async)
    llm_view.apply_clicked.append(run_llm_async)
