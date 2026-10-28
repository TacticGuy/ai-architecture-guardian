# Textualize/textual#1182

Title: Merge pull request #1182 from davep/border-scream-test
Predicted degrading: True
Risk score / threshold: 0.492947 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/1182

## Top edges
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.get_box (attribution 0.365327; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.normalize_border_value (attribution 0.319925; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.render_row (attribution 0.279146; added=False)
- src/textual/_border.py:textual._border -> CALLS -> external_callable:typing.cast (attribution 0.144746; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border._edge_type_normalization_table (attribution -0.088102; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.BorderValue (attribution -0.087382; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.BORDER_CHARS (attribution -0.086883; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.BORDER_LOCATIONS (attribution -0.086883; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.BoxSegments (attribution -0.086883; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.Borders (attribution -0.081833; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.INNER (attribution -0.081833; added=False)
- src/textual/_border.py:textual._border -> CONTAINS -> src/textual/_border.py:textual._border.INVISIBLE_EDGE_TYPES (attribution -0.081833; added=False)

## Touched module coupling
- textual._border: {"ca_after": 4, "ca_before": 4, "ce_after": 4, "ce_before": 4, "in_import_cycle": false}

## Diff hunks
- src/textual/_border.py: ["-@rich.repr.auto", "-class Border:", "-    \"\"\"Renders Textual CSS borders.", "-", "-    This is analogous to Rich's `Box` but more flexible. Different borders may be", "-    applied to each of the four edges, and more advanced borders can be achieved through", "-    various combinations of Widget and parent background colors.", "-", "-    \"\"\"", "-", "-    def __init__(", "-        self,"]
- src/textual/_border.py: ["-", "-", "-if __name__ == \"__main__\":", "-    from rich import print", "-    from rich.text import Text", "-    from rich.padding import Padding", "-", "-    from .color import Color", "-", "-    inner = Color.parse(\"#303F9F\")", "-    outer = Color.parse(\"#212121\")", "-"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
