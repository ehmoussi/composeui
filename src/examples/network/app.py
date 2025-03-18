"""Definition of the app for the async view example."""

from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.mashumaromodel import MashumaroModel
from examples.network.example import ExampleMainView, initialize_navigation
from examples.network.llm import connect_llm, connect_llm_async, initialize_form

from mashumaro.mixins.json import DataClassJSONMixin
from qtpy import API

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class LLMConfig(DataClassJSONMixin):
    questions: List[str] = field(default_factory=list)
    answers: List[str] = field(default_factory=list)
    llms: List[str] = field(default_factory=list)
    current_index_llm: int = 0


class Model(MashumaroModel[LLMConfig]):

    def get_current_llm(self) -> str:
        """Get the current LLM."""
        if self.root.current_index_llm < len(self.root.llms):
            return self.root.llms[self.root.current_index_llm]
        return ""

    def build_ollama_messages(self) -> List[Dict[str, str]]:
        messages = []
        for question, answer in zip(self.root.questions, self.root.answers):
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})
        if len(self.root.questions) > len(self.root.answers):
            messages.append({"role": "user", "content": self.root.questions[-1]})
        return messages

    def get_last_question(self) -> str:
        question = self.root.questions[-1]
        return (
            "<b><i>You</i></b>:"
            f"<blockquote><i>{question if question else 'No question'}</i></blockquote><br/>"
        )

    def get_last_answer(self) -> str:
        answer = self.root.answers[-1]
        llm = self._clean_llm_name(self.get_current_llm())
        return f"<b>{llm}</b>:<blockquote>{self._clean_answer(answer)}</blockquote><br/>"

    def _clean_answer(self, answer: str) -> str:
        """Clean the answer of the LLM."""
        return answer.replace("\n", "<br/>")

    def _clean_llm_name(self, name: str) -> str:
        """Clean the name of the LLM to dump the version."""
        return name.split(":")[0]


class NetworkViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            Model("example", get_version("composeui"), LLMConfig()),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_navigation(view=self.main_view.toolbar.navigation)
        initialize_form(view=self.main_view.llm, model=self.model)

    def connect_app(self) -> None:
        if API == "pyside6":
            connect_llm_async(llm_view=self.main_view.llm, main_view=self.main_view)
        else:
            connect_llm(llm_view=self.main_view.llm, main_view=self.main_view)
