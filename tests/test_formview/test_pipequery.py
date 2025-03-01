from examples.formview.app import FormViewApp
from examples.formview.pipeform import PipeQuery

import pytest


@pytest.fixture()
def query(app: FormViewApp) -> PipeQuery:
    """Get the points query class with some points."""
    return app.model.pipe_query


def test_id(query: PipeQuery) -> None:
    assert query.p_id == 1


def test_name(query: PipeQuery) -> None:
    assert query.get_name() == "PipeTShape"
    query.set_name("New Pipe")
    assert query.get_name() == "New Pipe"


def test_main_radius(query: PipeQuery) -> None:
    assert query.get_main_radius() == 80.0
    query.set_main_radius(1.0)
    assert query.get_main_radius() == 1.0


def test_main_width(query: PipeQuery) -> None:
    assert query.get_main_width() == 20.0
    query.set_main_width(1.0)
    assert query.get_main_width() == 1.0


def test_main_half_length(query: PipeQuery) -> None:
    assert query.get_main_half_length() == 200.0
    query.set_main_half_length(1.0)
    assert query.get_main_half_length() == 1.0


def test_incident_radius(query: PipeQuery) -> None:
    assert query.get_incident_radius() == 50.0
    query.set_incident_radius(1.0)
    assert query.get_incident_radius() == 1.0


def test_incident_width(query: PipeQuery) -> None:
    assert query.get_incident_width() == 20.0
    query.set_incident_width(1.0)
    assert query.get_incident_width() == 1.0


def test_incident_half_length(query: PipeQuery) -> None:
    assert query.get_incident_half_length() == 200.0
    query.set_incident_half_length(1.0)
    assert query.get_incident_half_length() == 1.0
