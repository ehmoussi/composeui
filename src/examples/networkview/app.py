"""Definition of the app for the async view example."""

from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.mashumaromodel import MashumaroModel
from examples.networkview.example import ExampleMainView, initialize_navigation
from examples.networkview.llm import connect_llm, initialize_llm

from mashumaro.mixins.json import DataClassJSONMixin

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class LLMConfig(DataClassJSONMixin):
    llm: str = "llama3.1"
    questions: List[str] = field(default_factory=list)
    answers: List[str] = field(default_factory=list)
    llms: List[str] = field(default_factory=list)


class Model(MashumaroModel[LLMConfig]):
    def build_ollama_messages(self) -> List[Dict[str, str]]:
        messages = []
        for question, answer in zip(self.root.questions, self.root.answers):
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})
        if len(self.root.questions) > len(self.root.answers):
            messages.append({"role": "user", "content": self.root.questions[-1]})
        return messages

    def build_conversation(self) -> str:
        conversation = ""
        for question, answer in zip(self.root.questions, self.root.answers):
            text = (
                f"> **You** {' ' * max(len(self.root.llm) - 3, 0)}: "
                f"*{question if question else 'No question'}*"
                "\n\n"
                f"> **{self.root.llm}**: {answer}"
            )
            conversation += text
        return conversation


class NetworkViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            Model("example", get_version("composeui"), LLMConfig()),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_navigation(view=self.main_view.toolbar.navigation)
        initialize_llm(view=self.main_view.llm, main_view=self.main_view, model=self.model)

    def connect_app(self) -> None:
        connect_llm(llm_view=self.main_view.llm)
