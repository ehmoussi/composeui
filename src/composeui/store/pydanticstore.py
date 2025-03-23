from composeui.commontypes import AnyPydanticBaseModel
from composeui.store.jsonstore import JsonStore


class PydanticStore(JsonStore[AnyPydanticBaseModel]):
    # - The root is a pydantic BaseModel that contains all the data in the study
    # only the root is used to store the data in the study.
    # - The root need to have default values otherwise this class need to be override
    # to manage the clear of the data
    # - Creating another BaseModel outside of root will be not used for saving the data
    # the implementation of the saving and opening and clearing of the data is let
    # to be implemented in the child classes if really needed

    def clear_study(self) -> None:
        try:
            self.root = self.root.model_construct()
        except AttributeError:  # old version
            self.root = self.root.construct()
        super().clear_study()

    def from_json(self, json_data: str) -> AnyPydanticBaseModel:
        try:
            return self.root.model_validate_json(json_data)
        except AttributeError:  # old version
            return self.root.parse_raw(json_data)

    def to_json(self) -> str:
        try:
            return self.root.model_dump_json()
        except AttributeError:  # old version
            return self.root.json()
