"""Definition of the app for the async view example."""

from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.mashumaromodel import MashumaroModel
from examples.network.example import ExampleMainView, initialize_navigation
from examples.network.llm import connect_llm, connect_llm_async, initialize_form

from mashumaro.mixins.json import DataClassJSONMixin
from qtpy import API

import itertools as it
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
        for question, answer in it.zip_longest(
            self.root.questions, self.root.answers, fillvalue=None
        ):
            if question is not None:
                messages.append({"role": "user", "content": question})
            if answer is not None:
                messages.append({"role": "assistant", "content": answer})
        return messages

    def build_conversation(self) -> str:
        """Build the whole conversation."""
        conversation = ""
        for question, answer in it.zip_longest(
            self.root.questions, self.root.answers, fillvalue=None
        ):
            if question is not None:
                conversation += self._get_html_question(question)
            if answer is not None:
                conversation += self._get_html_answer(answer)
        return conversation

    def get_last_html_question(self) -> str:
        if len(self.root.questions) > 0:
            return self._get_html_question(self.root.questions[-1])
        return ""

    def get_last_html_answer(self) -> str:
        if len(self.root.answers) > 0:
            return self._get_html_answer(self.root.answers[-1])
        return ""

    def get_answer_html_header(self) -> str:
        llm = self._clean_llm_name(self.get_current_llm())
        return f"<br/><p><b>{llm}</b>:</p><p><blockquote>"

    def get_answer_html_footer(self) -> str:
        return "</blockquote></p>"

    def clean_answer(self, answer: str) -> str:
        """Clean the answer of the LLM."""
        return answer.replace("\n", "<br/>").replace(" ", "&nbsp;")

    def _get_html_answer(self, answer: str) -> str:
        return (
            f"{self.get_answer_html_header()}"
            f"{self.clean_answer(answer)}"
            f"{self.get_answer_html_footer()}"
        )

    def _get_html_question(self, question: str) -> str:
        return (
            "<br/><p><b><i>You</i></b>:</p>"
            f"<p><blockquote><i>{question if question else 'No question'}</i></blockquote></p>"
        )

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
