"""A catalogue of pipes kept in a SQLite database, runnable on every backend.

`python -m examples.pipecatalogue --backend qt` (or `textual`, or `web`). The pipes are
rows of the model's database, not view state: the Catalogue page lists them through a
query, filtered by material and radius, with their mass computed by a SQL view joining
each pipe to its material. The database checks every pipe added (a name, positive
dimensions, a wall thinner than the radius) and File saves and opens the views and the
database together.
"""

import enum
from typing import ClassVar, Optional

import attrs
from attrs import Factory

from composeui.core.application import run
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, as_parameters
from composeui.core.view import (
    ButtonVariant,
    ButtonView,
    DialogKind,
    DialogView,
    FormView,
    LabelRowComboboxView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelView,
    MainView,
    PageView,
    Router,
    TableView,
    child,
    define_view,
)


class Material(enum.Enum):
    STEEL = "Steel"
    ALUMINIUM = "Aluminium"
    COPPER = "Copper"
    PVC = "PVC"


@attrs.define
class Pipe:
    """A pipe to add, as the form gives it: a dimension left empty is None."""

    name: str
    material: Material
    #: mm
    radius: Optional[float]
    #: mm
    thickness: Optional[float]
    #: m
    length: Optional[float]


@attrs.define
class ListedPipe:
    name: str
    material: Material
    radius: float
    thickness: float
    length: float
    #: kg
    mass: float


@attrs.define
class Shown:
    """Which pipes to show: None shows them all."""

    material: Optional[Material]
    #: mm
    min_radius: Optional[float]


@attrs.define
class Total:
    count: int
    #: kg
    mass: float


class Pipes(SqliteTable):
    create = """
        CREATE TABLE material(name TEXT PRIMARY KEY, density REAL NOT NULL);  -- kg/m³
        INSERT INTO material(name, density) VALUES
            ('Steel', 7850), ('Aluminium', 2700), ('Copper', 8960), ('PVC', 1380);

        CREATE TABLE pipe(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE CONSTRAINT named CHECK (name <> ''),
            material TEXT NOT NULL REFERENCES material(name),
            radius REAL NOT NULL CONSTRAINT positive_radius CHECK (radius > 0),
            thickness REAL NOT NULL CONSTRAINT positive_thickness CHECK (thickness > 0),
            length REAL NOT NULL CONSTRAINT positive_length CHECK (length > 0),
            CONSTRAINT thin_wall CHECK (thickness < radius)
        );

        -- the pipe's cross-section (mm², hence the 1e-6) times its length and density
        CREATE VIEW pipe_mass AS
        SELECT pipe.name, material, radius, thickness, length,
            3.141592653589793 * (radius * radius - (radius - thickness) * (radius - thickness))
                * 1e-6 * length * material.density AS mass
        FROM pipe JOIN material ON material.name = pipe.material;
    """

    #: why the table refused a pipe, by the constraint the error names
    refusals: ClassVar[dict[str, str]] = {
        "UNIQUE constraint failed: pipe.name": "another pipe has this name",
        "named": "it needs a name",
        "NOT NULL": "every dimension is needed",
        "positive_": "its dimensions must be positive",
        "thin_wall": "its wall must be thinner than its radius",
    }

    def add(self, pipe: Pipe) -> None:
        """Add a pipe; raises `RefusedError` for one the table refuses."""
        with self.connection() as db:
            db.execute(
                "INSERT INTO pipe(name, material, radius, thickness, length)"
                " VALUES (:name, :material, :radius, :thickness, :length)",
                as_parameters(pipe),
            )

    # each query below takes `Shown`'s fields as parameters, None matching every pipe

    def find(self, shown: Shown) -> list[ListedPipe]:
        return self.fetch(
            ListedPipe,
            """SELECT * FROM pipe_mass
            WHERE (:material IS NULL OR material = :material)
                AND (:min_radius IS NULL OR radius >= :min_radius)
            ORDER BY name""",
            as_parameters(shown),
        )

    def total(self, shown: Shown) -> Total:
        total = self.fetch_one(
            Total,
            """SELECT count(*) AS count, total(mass) AS mass FROM pipe_mass
            WHERE (:material IS NULL OR material = :material)
                AND (:min_radius IS NULL OR radius >= :min_radius)""",
            as_parameters(shown),
        )
        assert total is not None  # an aggregate always has a row
        return total

    def remove(self, shown: Shown) -> int:
        """Remove the pipes `shown` names; return how many."""
        with self.connection() as db:
            removed = db.execute(
                """DELETE FROM pipe
                WHERE (:material IS NULL OR material = :material)
                    AND (:min_radius IS NULL OR radius >= :min_radius)""",
                as_parameters(shown),
            )
            return removed.rowcount


class PipeCatalogueModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.pipes = self.add_table(Pipes)


@define_view
class DimensionRowView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.minimum = 0
        self.decimals = 1


@define_view
class NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name"
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> Optional[str]:
        return "A name is mandatory" if self.text == "" else None


@define_view
class MaterialRowView(LabelRowComboboxView[Material]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Material"
        self.values = {material.value: material for material in Material}
        self.value = Material.STEEL


@define_view
class PipeFormView(FormView):
    name: NameRowView = Factory(NameRowView)
    material: MaterialRowView = Factory(MaterialRowView)
    radius: DimensionRowView = Factory(DimensionRowView)
    thickness: DimensionRowView = Factory(DimensionRowView)
    length: DimensionRowView = Factory(DimensionRowView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.radius.label = "Outer radius (mm)"
        self.radius.value = 50.0
        self.thickness.label = "Wall thickness (mm)"
        self.thickness.value = 5.0
        self.length.label = "Length (m)"
        self.length.value = 6.0

    def pipe(self) -> Pipe:
        return Pipe(
            name=self.name.text,
            material=self.material.value or Material.STEEL,
            radius=self.radius.value,
            thickness=self.thickness.value,
            length=self.length.value,
        )


@define_view
class MaterialFilterRowView(LabelRowComboboxView[str]):
    """A material to show, by name, or every material ("")."""

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Material"
        self.values = {"All materials": "", **{m.value: m.value for m in Material}}
        self.value = ""


@define_view
class ShownFormView(FormView):
    material: MaterialFilterRowView = Factory(MaterialFilterRowView)
    min_radius: DimensionRowView = child(
        DimensionRowView, label="Outer radius at least (mm)", placeholder="Any"
    )

    def shown(self) -> Shown:
        material = self.material.value
        return Shown(
            material=Material(material) if material else None,
            min_radius=self.min_radius.value,
        )


@define_view
class CataloguePageView(PageView):
    route = "catalogue"
    page_title = "Catalogue"

    shown: ShownFormView = Factory(ShownFormView)
    pipes: TableView = child(
        TableView,
        headers=["Name", "Material", "Outer radius (mm)", "Wall (mm)", "Length (m)", "Mass (kg)"],
    )
    total: LabelView = Factory(LabelView)
    remove_shown: ButtonView = child(
        ButtonView, text="Remove the Shown Pipes", variant=ButtonVariant.DANGER
    )


@define_view
class AddPageView(PageView):
    route = "add"
    page_title = "Add"

    pipe: PipeFormView = Factory(PipeFormView)
    add_pipe: ButtonView = child(ButtonView, text="Add the Pipe")


@define_view
class CataloguePagesView(Router):
    # the app starts on its first page: adding a pipe
    add: AddPageView = Factory(AddPageView)
    catalogue: CataloguePageView = Factory(CataloguePageView)


@define_view
class RemoveShownDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = "Remove the shown pipes"
        self.text = "The pipes the catalogue shows are removed from it."
        self.accept_text = "Remove"


@define_view
class PipeCatalogueMainView(MainView):
    app_title = "Pipe Catalogue"
    extension = ".pipes"

    pages: CataloguePagesView = Factory(CataloguePagesView)
    confirm_remove: RemoveShownDialog = Factory(RemoveShownDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the callbacks get the model through their `model` parameter
        self.pages.add.add_pipe.clicked.connect(self._add_pipe)
        # removing can't be undone: only once the user confirms
        self.pages.catalogue.remove_shown.clicked.connect(self.confirm_remove.open)
        self.confirm_remove.accepted.connect(self._remove_shown)
        shown = self.pages.catalogue.shown
        shown.material.value_changed.connect(self.show_pipes)
        shown.min_radius.editing_finished.connect(self.show_pipes)

    def show_pipes(self, model: PipeCatalogueModel) -> None:
        """List the pipes the filter shows, and their total."""
        catalogue = self.pages.catalogue
        shown = catalogue.shown.shown()
        catalogue.pipes.rows = [
            [
                pipe.name,
                pipe.material.value,
                f"{pipe.radius:g}",
                f"{pipe.thickness:g}",
                f"{pipe.length:g}",
                f"{pipe.mass:.1f}",
            ]
            for pipe in model.pipes.find(shown)
        ]
        total = model.pipes.total(shown)
        pipes = "pipe" if total.count == 1 else "pipes"
        catalogue.total.text = f"{total.count} {pipes}, {total.mass:.1f} kg"

    def _add_pipe(self, *, model: PipeCatalogueModel) -> None:
        pipe = self.pages.add.pipe.pipe()
        with self.refusing("Can't add the pipe: {error}."):
            model.pipes.add(pipe)
            self.status_bar.show_message(f"Added {pipe.name!r}")

    def _remove_shown(self, *, model: PipeCatalogueModel) -> None:
        count = model.pipes.remove(self.pages.catalogue.shown.shown())
        self.status_bar.show_message(f"Removed {count} pipe{'' if count == 1 else 's'}")


def connect_model(main_view: PipeCatalogueMainView, model: PipeCatalogueModel) -> None:
    """Keep the catalogue listing the database's pipes, whatever changes them."""
    model.pipes.changed.connect(main_view.show_pipes, now=True)


def main() -> None:
    run(PipeCatalogueMainView, build_model=PipeCatalogueModel, setup_model=connect_model)


if __name__ == "__main__":
    main()
