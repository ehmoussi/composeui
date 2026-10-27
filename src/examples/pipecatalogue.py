"""A catalogue of pipes kept in a SQLite database, runnable on every backend.

`python -m examples.pipecatalogue --backend qt` (or `textual`, or `web`). The pipes are
rows of the model's database, not view state: the catalogue lists them, an expander each,
through a query filtered by material, radius and installation date, with their mass
computed by a SQL view joining each pipe to its material, and beside them in a tree, under
their material (in bold), a border the user drags between the two: each pipe there is
marked done once its installation date is known, with a warning until then, and selecting
it expands its expander. A form in the sidebar adds a
pipe, which the catalogue beside it lists at once; each pipe's Edit button changes it in a
form dialog, and its Delete button removes it. The database checks every pipe added or
changed (a name, positive dimensions, a wall thinner than the radius) and File saves and
opens the views and the database together; a study saved before pipes had an installation
date gets the column, empty, as it opens (`PipeCatalogueModel.migrations`).
"""

from __future__ import annotations

import datetime
import enum
import functools
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Optional

import attrs
from attrs import Factory

from composeui.core.application import run
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, as_parameters, table
from composeui.core.view import (
    STRETCH,
    ButtonVariant,
    ButtonView,
    DialogKind,
    DialogView,
    ExpanderView,
    FormView,
    HorizontalView,
    LabelRowComboboxView,
    LabelRowDateInputView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelView,
    ListView,
    MainView,
    NodeMark,
    PageView,
    SidebarView,
    SplitterView,
    TreeNode,
    TreeView,
    TypedFormDialogView,
    View,
    child,
    define_view,
    format_date,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Hashable


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
    #: None while unknown
    installed: Optional[datetime.date] = None


@attrs.define
class ListedPipe:
    name: str
    material: Material
    radius: float
    thickness: float
    length: float
    #: kg
    mass: float
    installed: Optional[datetime.date] = None


@attrs.define
class Shown:
    """Which pipes to show: None shows them all."""

    material: Optional[Material]
    #: mm
    min_radius: Optional[float]
    #: a pipe installed on an unknown date is left out once it's set
    installed_from: Optional[datetime.date] = None


@attrs.define
class Total:
    count: int
    #: kg
    mass: float


#: the pipes with their mass: their cross-section (mm², hence the 1e-6) times their length
#: and density
_PIPE_MASS = """
    CREATE VIEW pipe_mass AS
    SELECT pipe.name, material, radius, thickness, length, installed,
        3.141592653589793 * (radius * radius - (radius - thickness) * (radius - thickness))
            * 1e-6 * length * material.density AS mass
    FROM pipe JOIN material ON material.name = pipe.material;
"""
#: the pipes a query keeps, `Shown`'s fields as its parameters, None keeping every pipe
_SHOWN = """
    (:material IS NULL OR material = :material)
    AND (:min_radius IS NULL OR radius >= :min_radius)
    AND (:installed_from IS NULL OR installed >= :installed_from)
"""


class Pipes(SqliteTable):
    create = (
        """
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
            -- as ISO 8601 writes it, as SQLite's own dates, sorting as the dates do
            installed TEXT
                CONSTRAINT dated CHECK (installed IS NULL OR date(installed) = installed),
            CONSTRAINT thin_wall CHECK (thickness < radius)
        );
        """
        + _PIPE_MASS
    )

    #: why the table refused a pipe, by the constraint the error names
    refusals: ClassVar[dict[str, str]] = {
        "UNIQUE constraint failed: pipe.name": "another pipe has this name",
        "named": "it needs a name",
        "NOT NULL": "every dimension is needed",
        "positive_": "its dimensions must be positive",
        "thin_wall": "its wall must be thinner than its radius",
        "dated": "its installation date isn't a date",
    }

    def add(self, pipe: Pipe) -> None:
        """Add a pipe; raises `RefusedError` for one the table refuses."""
        with self.connection() as db:
            db.execute(
                "INSERT INTO pipe(name, material, radius, thickness, length, installed)"
                " VALUES (:name, :material, :radius, :thickness, :length, :installed)",
                as_parameters(pipe),
            )

    def find(self, shown: Shown) -> list[ListedPipe]:
        return self.fetch(
            ListedPipe,
            f"SELECT * FROM pipe_mass WHERE {_SHOWN} ORDER BY name",  # noqa: S608 (the app's own SQL)
            as_parameters(shown),
        )

    def total(self, shown: Shown) -> Total:
        total = self.fetch_one(
            Total,
            # the app's own SQL, the user's values as parameters
            f"SELECT count(*) AS count, total(mass) AS mass FROM pipe_mass WHERE {_SHOWN}",  # noqa: S608
            as_parameters(shown),
        )
        assert total is not None  # an aggregate always has a row
        return total

    def get(self, name: str) -> Optional[ListedPipe]:
        """Get the pipe `name`, or None if no pipe has it."""
        return self.fetch_one(
            ListedPipe, "SELECT * FROM pipe_mass WHERE name = :name", {"name": name}
        )

    def update(self, name: str, pipe: Pipe) -> None:
        """Change the pipe `name` into `pipe`; raises `RefusedError` for one the table refuses."""
        with self.connection() as db:
            db.execute(
                "UPDATE pipe SET name = :name, material = :material, radius = :radius,"
                " thickness = :thickness, length = :length, installed = :installed"
                " WHERE name = :old_name",
                {**as_parameters(pipe), "old_name": name},
            )

    def delete(self, name: str) -> None:
        """Remove the pipe `name`."""
        with self.connection() as db:
            db.execute("DELETE FROM pipe WHERE name = :name", {"name": name})

    def remove(self, shown: Shown) -> int:
        """Remove the pipes `shown` names; return how many."""
        with self.connection() as db:
            removed = db.execute(
                f"DELETE FROM pipe WHERE {_SHOWN}",  # noqa: S608 (the app's own SQL)
                as_parameters(shown),
            )
            return removed.rowcount


def _add_installation_dates(db: sqlite3.Connection) -> None:
    """Bring a study from before pipes had an installation date: none of its pipes has one."""
    db.execute("ALTER TABLE pipe ADD COLUMN installed TEXT")
    db.execute("DROP VIEW pipe_mass")
    db.execute(_PIPE_MASS)


class PipeCatalogueModel(SqliteModel):
    pipes = table(Pipes)
    # 2: the pipes' installation dates
    schema_version = 2
    migrations = MappingProxyType({1: _add_installation_dates})


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
class InstalledRowView(LabelRowDateInputView):
    """When the pipe was installed, if known: never in the future."""

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Installed on"
        self.placeholder = "Unknown"
        # the calendar offers no later day; typed, a later one is refused below
        self.maximum = datetime.datetime.now().astimezone().date()
        self.set_validator(self._check_installed, self.value_changed)

    def _check_installed(self) -> Optional[str]:
        if self.value is not None and self.maximum is not None and self.value > self.maximum:
            return "A pipe can't be installed in the future"
        return None


@define_view
class PipeFormView(FormView):
    name: NameRowView = Factory(NameRowView)
    material: MaterialRowView = Factory(MaterialRowView)
    radius: DimensionRowView = Factory(DimensionRowView)
    thickness: DimensionRowView = Factory(DimensionRowView)
    length: DimensionRowView = Factory(DimensionRowView)
    installed: InstalledRowView = Factory(InstalledRowView)

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
            installed=self.installed.value,
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
    installed_from: LabelRowDateInputView = child(
        LabelRowDateInputView, label="Installed on or after", placeholder="Any"
    )

    def shown(self) -> Shown:
        material = self.material.value
        return Shown(
            material=Material(material) if material else None,
            min_radius=self.min_radius.value,
            installed_from=self.installed_from.value,
        )


@define_view
class PipeButtons(HorizontalView):
    edit: ButtonView = child(ButtonView, text="Edit", variant=ButtonVariant.SECONDARY)
    delete: ButtonView = child(ButtonView, text="Delete", variant=ButtonVariant.DANGER)


@define_view
class PipeExpander(ExpanderView):
    """A pipe of the catalogue: its name, material and mass, then its dimensions."""

    details: LabelView = Factory(LabelView)
    buttons: PipeButtons = Factory(PipeButtons)


@define_view
class PipeList(ListView[ListedPipe]):
    """The pipes shown, an expander each, told apart by their name, which is unique."""

    def build_item(self, item: ListedPipe) -> View:
        view = PipeExpander()
        self.update_item(view, item)
        view.buttons.edit.clicked.connect(functools.partial(self._edit, item.name))
        view.buttons.delete.clicked.connect(functools.partial(self._delete, item.name))
        return view

    def item_key(self, item: ListedPipe) -> Hashable:
        return item.name

    def update_item(self, view: View, item: ListedPipe) -> bool:
        # in place: an expanded pipe stays expanded
        assert isinstance(view, PipeExpander)
        # what tells the pipes apart at a glance, the rest once expanded
        view.title = f"{item.name} · {item.material.value} · {item.mass:.1f} kg"
        # the date in the language's format: ComposeUI's text for it, which catalogs translate
        installed = (
            "installed on an unknown date"
            if item.installed is None
            else f"installed {format_date(item.installed, self.tr('MM/dd/yyyy'))}"
        )
        view.details.text = (
            f"Outer radius {item.radius:g} mm, wall {item.thickness:g} mm,"
            f" {item.length:g} m long, {installed}"
        )
        return True

    @staticmethod
    def _edit(name: str, *, main_view: PipeCatalogueMainView, model: PipeCatalogueModel) -> None:
        main_view.edit_pipe(name, model=model)

    def _delete(
        self, name: str, *, main_view: PipeCatalogueMainView, model: PipeCatalogueModel
    ) -> None:
        """Remove the pipe `name`: the model's `changed` takes its expander away."""
        model.pipes.delete(name)
        main_view.status_bar.show_message(f"Deleted {name!r}")


@define_view
class PipeTree(TreeView):
    """The pipes shown under their material, a material by its enum's name.

    A material's label is bold; a pipe is marked done once installed on a known date, and
    with a warning until then.
    """

    def show(self, pipes: list[ListedPipe]) -> None:
        """Show `pipes`: what was expanded or selected and still is there stays so."""
        self.nodes = [
            TreeNode(
                material.value,
                [
                    TreeNode(
                        pipe.name,
                        mark=NodeMark.WARNING if pipe.installed is None else NodeMark.DONE,
                    )
                    for pipe in pipes
                    if pipe.material is material
                ],
                key=material.name,
                is_bold=True,
            )
            for material in Material
            if any(pipe.material is material for pipe in pipes)
        ]


@define_view
class PipeBrowser(SplitterView):
    """The pipes shown twice: in a narrow tree by material, beside their expanders.

    The user drags the border between them to widen the tree.
    """

    tree: PipeTree = attrs.field(factory=PipeTree, metadata={STRETCH: 1})
    pipes: PipeList = attrs.field(factory=PipeList, metadata={STRETCH: 3})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.tree.selection_changed.connect(self._expand_selected)

    def _expand_selected(self, path: tuple[str, ...]) -> None:
        """Expand the selected pipe's expander; a material selected expands nothing."""
        if len(path) == 1:  # a material
            return
        for item, view in zip(self.pipes.items, self.pipes.item_views):
            if item.name == path[-1] and isinstance(view, PipeExpander):
                view.is_expanded = True


@define_view
class CataloguePageView(PageView):
    # the filter and what it shows, then the pipes it shows, however many
    shown: ShownFormView = Factory(ShownFormView)
    total: LabelView = Factory(LabelView)
    remove_shown: ButtonView = child(
        ButtonView, text="Remove the Shown Pipes", variant=ButtonVariant.DANGER
    )
    browser: PipeBrowser = Factory(PipeBrowser)


@define_view
class AddPipeSidebar(SidebarView):
    """The form adding a pipe, beside the catalogue listing it."""

    pipe: PipeFormView = Factory(PipeFormView)
    add_pipe: ButtonView = child(ButtonView, text="Add the Pipe")


@define_view
class EditPipeDialog(TypedFormDialogView[PipeFormView]):
    """A pipe's values, to change: OK saves them, once its form's checks pass."""

    form: PipeFormView = Factory(PipeFormView)
    #: the name of the pipe edited, as it was before; the dialog's own, not shown
    _edited_name: str = attrs.field(default="", init=False)

    @property
    def edited_name(self) -> str:
        return self._edited_name

    def edit(self, name: str) -> None:
        """Open the dialog on the pipe `name`, its form filled with the pipe's values."""
        self._edited_name = name
        self.form.check()  # OK as these values leave it
        self.open()

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Edit the pipe"
        self.accept_text = "Save"


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

    add: AddPipeSidebar = child(AddPipeSidebar, title="Add a Pipe")
    catalogue: CataloguePageView = Factory(CataloguePageView)
    confirm_remove: RemoveShownDialog = Factory(RemoveShownDialog)
    edit_dialog: EditPipeDialog = Factory(EditPipeDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the callbacks get the model through their `model` parameter
        self.add.add_pipe.clicked.connect(self._add_pipe)
        # removing can't be undone: only once the user confirms
        self.catalogue.remove_shown.clicked.connect(self.confirm_remove.open)
        self.confirm_remove.accepted.connect(self._remove_shown)
        self.edit_dialog.accepted.connect(self._save_edited_pipe)
        shown = self.catalogue.shown
        shown.material.value_changed.connect(self.show_pipes)
        shown.min_radius.editing_finished.connect(self.show_pipes)
        shown.installed_from.value_changed.connect(self.show_pipes)

    def show_pipes(self, model: PipeCatalogueModel) -> None:
        """List the pipes the filter shows, in the tree too, and their total."""
        catalogue = self.catalogue
        shown = catalogue.shown.shown()
        pipes = model.pipes.find(shown)
        catalogue.browser.tree.show(pipes)
        catalogue.browser.pipes.items = pipes
        total = model.pipes.total(shown)
        noun = "pipe" if total.count == 1 else "pipes"
        catalogue.total.text = f"{total.count} {noun}, {total.mass:.1f} kg"

    def _add_pipe(self, *, model: PipeCatalogueModel) -> None:
        pipe = self.add.pipe.pipe()
        with self.refusing("Can't add the pipe: {error}."):
            model.pipes.add(pipe)
            self.status_bar.show_message(f"Added {pipe.name!r}")

    def edit_pipe(self, name: str, *, model: PipeCatalogueModel) -> None:
        """Open the edit dialog on the pipe `name`, as the database has it."""
        pipe = model.pipes.get(name)
        if pipe is None:
            return
        form = self.edit_dialog.form
        form.name.text = pipe.name
        form.material.value = pipe.material
        form.radius.value, form.thickness.value = pipe.radius, pipe.thickness
        form.length.value = pipe.length
        form.installed.value = pipe.installed
        self.edit_dialog.edit(name)

    def _save_edited_pipe(self, *, model: PipeCatalogueModel) -> None:
        """Save the dialog's pipe; the database may refuse it still, e.g. a name taken."""
        pipe = self.edit_dialog.form.pipe()
        with self.refusing("Can't save the pipe: {error}."):
            model.pipes.update(self.edit_dialog.edited_name, pipe)
            self.status_bar.show_message(f"Saved {pipe.name!r}")

    def _remove_shown(self, *, model: PipeCatalogueModel) -> None:
        count = model.pipes.remove(self.catalogue.shown.shown())
        self.status_bar.show_message(f"Removed {count} pipe{'' if count == 1 else 's'}")

    def connect_model(self, model: PipeCatalogueModel) -> None:
        """Keep the catalogue listing the database's pipes, whatever changes them."""
        model.pipes.changed.connect(self.show_pipes, now=True)


def main() -> None:
    run(
        PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )


if __name__ == "__main__":
    main()
