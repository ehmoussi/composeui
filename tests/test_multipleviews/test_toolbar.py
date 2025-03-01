from examples.multipleviews.app import MultipleViewsApp


def test_is_visible(app: MultipleViewsApp) -> None:
    main_view = app.main_view
    # view 1 is visible by default
    assert main_view.view_1.is_visible is True
    assert main_view.left_dock.is_visible is True
    assert main_view.left_dock.view_1.is_visible is True
    assert main_view.view_2.is_visible is False
    assert main_view.right_dock.is_visible is False
    assert main_view.right_dock.view_2.is_visible is False
    assert main_view.view_3.is_visible is False
    # select view_2 in the toolbar
    main_view.toolbar.navigation.view_1.is_checked = False
    main_view.toolbar.navigation.view_2.is_checked = True
    main_view.toolbar.navigation.toggled()
    assert main_view.view_1.is_visible is False
    assert main_view.left_dock.is_visible is False
    assert main_view.left_dock.view_1.is_visible is False
    assert main_view.view_2.is_visible is True
    assert main_view.right_dock.is_visible is True
    assert main_view.right_dock.view_2.is_visible is True
    assert main_view.view_3.is_visible is False
    # select view_3 in the toolbar
    main_view.toolbar.navigation.view_2.is_checked = False
    main_view.toolbar.navigation.view_3.is_checked = True
    main_view.toolbar.navigation.toggled()
    assert main_view.view_1.is_visible is False
    assert main_view.left_dock.is_visible is False
    assert main_view.left_dock.view_1.is_visible is False
    assert main_view.view_2.is_visible is False
    assert main_view.right_dock.is_visible is False
    assert main_view.right_dock.view_2.is_visible is False
    assert main_view.view_3.is_visible is True
