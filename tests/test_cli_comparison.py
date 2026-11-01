from cli_comparison import ITEMS, render


def test_panel_menu_items_stay_on_same_lines_when_selection_moves():
    positions = []
    for selected in range(len(ITEMS)):
        lines = render(2, selected, False).splitlines()
        positions.append([next(i for i, line in enumerate(lines) if label in line) for label in ITEMS])
    assert all(position == positions[0] for position in positions)
