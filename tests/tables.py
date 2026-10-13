"""A table whose notes the user edits, shared by the backend tests of editable cells."""

from attrs import Factory

from composeui.core.view import MainView, TableView, define_view


@define_view
class EditableTableMainView(MainView):
    app_title = "Places"
    extension = ".places"

    places: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.places.headers = ["Place", "Note"]
        # the harbour has no note yet: its row is short of the cell
        self.places.rows = [["Lake", "Calm"], ["Harbour"]]
        self.places.editable_columns = [1]
