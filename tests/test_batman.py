"""Tests of the example batman: a click on the chart says whether it was on the bat."""

from examples.batman import BatmanMainView, is_in_bat


def test_a_point_is_in_the_bat_between_its_edges() -> None:
    assert is_in_bat(0, 0)
    assert is_in_bat(-6, 0)  # a wing
    assert not is_in_bat(0, 2.5)  # above the head, between the ears
    assert not is_in_bat(-2, 1.5)  # over a shoulder
    assert not is_in_bat(-7.5, 0)  # past the wings


def test_a_click_says_whether_it_was_on_the_bat() -> None:
    view = BatmanMainView()
    assert [series.name for series in view.chart.series] == ["Upper Edge", "Lower Edge"]

    view.chart.clicked.emit(0, 0)
    assert view.message.text == "I'm Batman"
    view.chart.clicked.emit(0, 2.5)
    assert view.message.text == "Click the bat"
