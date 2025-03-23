"""Data managing state using mashumaro."""

from composeui.commontypes import AnyMashumaroDataClass
from composeui.store.jsonstore import JsonStore


class MashumaroStore(JsonStore[AnyMashumaroDataClass]):

    def clear_study(self) -> None:
        """Clear all the data."""
        self.root = self.root.from_dict({})
        super().clear_study()

    def from_json(self, json_data: str) -> AnyMashumaroDataClass:
        return self.root.from_json(json_data)

    def to_json(self) -> str:
        return str(self.root.to_json())
