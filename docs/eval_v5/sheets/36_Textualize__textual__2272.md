# Textualize/textual#2272

Title: Ensure styles applied in correct order in DataTable (#2272)
Predicted degrading: True
Risk score / threshold: 0.500814 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/2272

## Top edges
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.add_row -> CALLS -> src/textual/widgets/_data_table.py:textual.widgets._data_table.Row (attribution 0.00646; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table -> CONTAINS -> src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable (attribution -0.006378; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.sort -> CONTAINS -> src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.sort.sort_by_column_keys (attribution 0.004826; added=False)
- src/textual/widget.py:textual.widget.Widget -> CONTAINS -> src/textual/widget.py:textual.widget.Widget.get_pseudo_class_state (attribution 0.004611; added=False)
- src/textual/widget.py:textual.widget.Widget -> CONTAINS -> src/textual/widget.py:textual.widget.Widget.action_scroll_left (attribution 0.004452; added=False)
- src/textual/widget.py:textual.widget.Widget -> CONTAINS -> src/textual/widget.py:textual.widget.Widget.action_scroll_right (attribution 0.004452; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> CALLS -> src/textual/widget.py:textual.widget.PseudoClasses (attribution 0.004416; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> CALLS -> src/textual/widgets/_data_table.py:textual.widgets._data_table.Column (attribution 0.004403; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> CALLS -> src/textual/_cache.py:textual._cache.LRUCache (attribution 0.004275; added=False)
- src/textual/widgets/_text_log.py:textual.widgets._text_log.TextLog.__init__ -> CALLS -> src/textual/_cache.py:textual._cache.LRUCache (attribution 0.004161; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> ACCESSES_GLOBAL -> src/textual/widgets/_data_table.py:textual.widgets._data_table.CellCacheKey (attribution 0.003809; added=False)
- src/textual/widgets/_data_table.py:textual.widgets._data_table.DataTable.__init__ -> ACCESSES_GLOBAL -> src/textual/widgets/_data_table.py:textual.widgets._data_table.LineCacheKey (attribution 0.003809; added=False)

## Touched module coupling
- textual.renderables.styled: {"ca_after": 1, "ca_before": null, "ce_after": 0, "ce_before": null, "in_import_cycle": false}
- textual.widgets._data_table: {"ca_after": 8, "ca_before": 8, "ce_after": 20, "ce_before": 19, "in_import_cycle": false}

## Diff hunks
- src/textual/widgets/_data_table.py: ["-        style: Style,", "+        base_style: Style,"]
- src/textual/widgets/_data_table.py: ["-            style: Style to apply.", "+            base_style: Style to apply."]
- src/textual/widgets/_data_table.py: ["-        get_component = self.get_component_styles", "-        show_cursor = self.show_cursor", "-", "-        if hover and show_cursor and self._show_hover_cursor:", "-            style += get_component(\"datatable--hover\").rich_style", "-            if is_header_cell or is_row_label_cell:", "-                # Apply subtle variation in style for the header/label (blue background by", "-                # default) rows and columns affected by the cursor, to ensure we can", "-                # still differentiate between the labels and the data.", "-                style += get_component(\"datatable--header-hover\").rich_style", "-", "-        if cursor and show_cursor:"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
