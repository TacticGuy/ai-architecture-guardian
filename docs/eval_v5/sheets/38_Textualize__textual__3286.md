# Textualize/textual#3286

Title: Tweak progress bar docs. (#3286)
Predicted degrading: True
Risk score / threshold: 0.478776 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/3286

## Top edges
- src/textual/widget.py:textual.widget.Widget -> CONTAINS -> src/textual/widget.py:textual.widget.Widget.get_component_rich_style (attribution 0.008062; added=False)
- src/textual/widgets/_tabs.py:textual.widgets._tabs.Tab.__init__ -> CALLS -> external_callable:self.update (attribution 0.005169; added=False)
- src/textual/_import_app.py:textual._import_app.import_app -> IMPORTS -> src/textual/app.py:textual.app (attribution 0.005082; added=False)
- src/textual/message_pump.py:textual.message_pump.MessagePump -> CONTAINS -> src/textual/message_pump.py:textual.message_pump.MessagePump.set_interval (attribution 0.004127; added=False)
- src/textual/dom.py:textual.dom.DOMNode -> CONTAINS -> src/textual/dom.py:textual.dom.DOMNode.watch (attribution 0.003628; added=False)
- src/textual/css/styles.py:textual.css.styles.StylesBase -> CONTAINS -> src/textual/css/styles.py:textual.css.styles.StylesBase.__textual_animation__ (attribution 0.00345; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> ACCESSES_GLOBAL -> src/textual/_types.py:textual._types.SegmentLines (attribution 0.00277; added=False)
- src/textual/widgets/_progress_bar.py:textual.widgets._progress_bar -> CALLS -> src/textual/_types.py:textual._types.UnusedParameter (attribution 0.002731; added=True)
- src/textual/widgets/_progress_bar.py:textual.widgets._progress_bar -> CONTAINS -> src/textual/widgets/_progress_bar.py:textual.widgets._progress_bar.UNUSED (attribution -0.00225; added=False)
- src/textual/dom.py:textual.dom.DOMNode.watch -> CALLS -> src/textual/reactive.py:textual.reactive._watch (attribution -0.002169; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable._on_idle -> CALLS -> src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable._update_dimensions (attribution -0.002161; added=False)
- src/textual/_animator.py:textual._animator.Animator -> CONTAINS -> src/textual/_animator.py:textual._animator.Animator._animate (attribution 0.002091; added=False)

## Touched module coupling
- textual._types: {"ca_after": 15, "ca_before": 14, "ce_after": 1, "ce_before": 1, "in_import_cycle": true}
- textual.types: {"ca_after": 1, "ca_before": 1, "ce_after": 8, "ce_before": 8, "in_import_cycle": true}
- textual.widgets._progress_bar: {"ca_after": 1, "ca_before": 1, "ce_after": 12, "ce_before": 11, "in_import_cycle": true}

## Diff hunks
- src/textual/_types.py: ["+class UnusedParameter:", "+    \"\"\"Helper type for a parameter that isn't specified in a method call.\"\"\"", "+", "+"]
- src/textual/widgets/_progress_bar.py: ["+"]
- src/textual/widgets/_progress_bar.py: ["-    Once `total` is set to a numerical value, it cannot be set back to `None`."]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
