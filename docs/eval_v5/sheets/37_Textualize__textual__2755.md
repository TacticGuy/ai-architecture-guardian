# Textualize/textual#2755

Title: Pull `Tooltip` out of the main DOM (#2755)
Predicted degrading: False
Risk score / threshold: 0.420879 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/2755

## Top edges
- src/textual/screen.py:textual.screen.Screen -> CONTAINS -> src/textual/screen.py:textual.screen.Screen._extend_compose (attribution 0.020653; added=False)
- src/textual/widgets/__init__.py:textual.widgets -> IMPORTS -> src/textual/widgets/_tooltip.py:textual.widgets._tooltip (attribution -0.013008; added=False)
- src/textual/app.py:textual.app.App.on_event -> CALLS -> src/textual/screen.py:textual.screen.Screen (attribution 0.005196; added=False)
- src/textual/widgets/_tooltip.py:textual.widgets._tooltip -> CONTAINS -> src/textual/widgets/_tooltip.py:textual.widgets._tooltip.Tooltip (attribution -0.005159; added=False)
- src/textual/demo.py:textual.demo -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.003403; added=False)
- src/textual/cli/previews/easing.py:textual.cli.previews.easing -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.002447; added=False)
- tools/widget_documentation.py:widget_documentation -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.002309; added=False)
- src/textual/cli/previews/colors.py:textual.cli.previews.colors -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.002257; added=False)
- src/textual/widgets/_select.py:textual.widgets._select -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.002241; added=False)
- src/textual/widgets/_markdown.py:textual.widgets._markdown -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.00221; added=False)
- src/textual/cli/previews/keys.py:textual.cli.previews.keys -> IMPORTS -> src/textual/widgets/__init__.py:textual.widgets (attribution -0.002034; added=False)
- src/textual/widgets/_toggle_button.py:textual.widgets._toggle_button.ToggleButton -> INHERITS -> src/textual/widgets/_static.py:textual.widgets._static.Static (attribution -0.001991; added=False)

## Touched module coupling
- textual.widgets._tooltip: {"ca_after": 2, "ca_before": 2, "ce_after": 2, "ce_before": 2, "in_import_cycle": true}

## Diff hunks
- src/textual/widgets/_tooltip.py: ["-class Tooltip(Static):", "+class Tooltip(Static, inherit_css=False):"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
