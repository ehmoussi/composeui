from composeui.commontypes import AnyMsgspecStruct
from composeui.store.jsonstore import JsonStore

import msgspec


class MsgspecStore(JsonStore[AnyMsgspecStruct]):
    # - The root is a msgspec struct that contains all the data in the study
    # only the root is used to store the data in the study.
    # - The root need to have default values otherwise this class need to be override
    # to manage the clear of the data
    # - Creating another struct outside of root will be not used for saving the data
    # the implementation of the saving and opening and clearing of the data is let
    # to be implemented in the child classes if really needed

    def clear_study(self) -> None:
        self.root = type(self.root)()
        super().clear_study()

    def from_json(self, json_data: str) -> AnyMsgspecStruct:
        decoder = msgspec.json.Decoder(type(self.root))
        return decoder.decode(json_data)

    def to_json(self) -> str:
        encoder = msgspec.json.Encoder()
        return encoder.encode(self.root).decode()
