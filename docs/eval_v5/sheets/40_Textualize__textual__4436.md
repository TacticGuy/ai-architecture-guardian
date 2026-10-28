# Textualize/textual#4436

Title: fix(text area): end mouse selection only if currently selecting (#4436)
Predicted degrading: True
Risk score / threshold: 0.609332 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/4436

## Top edges
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea.__init__ -> CALLS -> src/textual/document/_history.py:textual.document._history.EditHistory (attribution 0.013868; added=False)
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea -> CONTAINS -> src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea.render_line (attribution 0.007839; added=False)
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea -> CONTAINS -> src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea.Changed (attribution 0.006254; added=False)
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea -> CONTAINS -> src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea.SelectionChanged (attribution 0.005835; added=False)
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea.__init__ -> CALLS -> src/textual/document/_document.py:textual.document._document.Document (attribution 0.004902; added=False)
- src/textual/widget.py:textual.widget.Widget -> CONTAINS -> src/textual/widget.py:textual.widget.Widget.release_mouse (attribution 0.00476; added=False)
- src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder -> CONTAINS -> src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder.process_color (attribution 0.004384; added=False)
- src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder -> CONTAINS -> src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder.add_declaration (attribution 0.004379; added=False)
- src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea -> CONTAINS -> src/textual/widgets/_text_area.py:textual.widgets._text_area.TextArea._set_document (attribution 0.004222; added=False)
- src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder -> CONTAINS -> src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder._process_scalar (attribution 0.004207; added=False)
- src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder -> CONTAINS -> src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder._process_fractional (attribution 0.004168; added=False)
- src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder -> CONTAINS -> src/textual/css/_styles_builder.py:textual.css._styles_builder.StylesBuilder._process_space_partial (attribution 0.004138; added=False)

## Touched module coupling
- textual.widgets._text_area: {"ca_after": 9, "ca_before": 9, "ce_after": 25, "ce_before": 25, "in_import_cycle": true}

## Diff hunks
- src/textual/widgets/_text_area.py: ["-        self._selecting = False", "-        self.release_mouse()", "-        self.record_cursor_width()", "-        self._restart_blink()", "+        if self._selecting:", "+            self._selecting = False", "+            self.release_mouse()", "+            self.record_cursor_width()", "+            self._restart_blink()", "-        \"\"\"Finalize the selection that has been made using the mouse when thew widget is hidden.\"\"\"", "+        \"\"\"Finalize the selection that has been made using the mouse when the widget is hidden.\"\"\""]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
