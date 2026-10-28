# Textualize/textual#4280

Title: Merge pull request #4280 from davep/leaky-select
Predicted degrading: True
Risk score / threshold: 0.456657 / 0.441173
GitHub PR: https://github.com/Textualize/textual/pull/4280

## Top edges
- src/textual/message_pump.py:textual.message_pump.MessagePump -> CONTAINS -> src/textual/message_pump.py:textual.message_pump.MessagePump.call_after_refresh (attribution 0.011899; added=False)
- src/textual/dom.py:textual.dom.DOMNode -> CONTAINS -> src/textual/dom.py:textual.dom.DOMNode.query_one (attribution 0.00599; added=False)
- src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList -> CONTAINS -> src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList.action_first (attribution 0.005103; added=False)
- src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList -> CONTAINS -> src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList.scroll_to_highlight (attribution 0.004814; added=False)
- src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList -> CONTAINS -> src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList.replace_option_prompt_at_index (attribution 0.004516; added=False)
- src/textual/app.py:textual.app.App._shutdown -> IMPORTS -> external_module:rich.console (attribution -0.003827; added=False)
- src/textual/widgets/_select.py:textual.widgets._select.Select.__init__ -> CALLS -> src/textual/widgets/_select.py:textual.widgets._select.Select._setup_variables_for_options (attribution 0.002851; added=False)
- src/textual/widgets/_select.py:textual.widgets._select.Select.from_values -> ACCESSES_GLOBAL -> src/textual/widgets/_select.py:textual.widgets._select.BLANK (attribution 0.002694; added=False)
- src/textual/widgets/_select.py:textual.widgets._select.Select.__init__ -> ACCESSES_GLOBAL -> src/textual/widgets/_select.py:textual.widgets._select.BLANK (attribution 0.002659; added=False)
- src/textual/_import_app.py:textual._import_app.import_app -> IMPORTS -> src/textual/app.py:textual.app (attribution 0.002651; added=False)
- src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList.__init__ -> CALLS -> src/textual/widgets/_option_list.py:textual.widgets._option_list.OptionList.action_first (attribution 0.002473; added=False)
- src/textual/widgets/_select.py:textual.widgets._select.Select -> INHERITS -> src/textual/containers.py:textual.containers.Vertical (attribution -0.002243; added=False)

## Touched module coupling
- textual.widgets._select: {"ca_after": 3, "ca_before": 3, "ce_after": 14, "ce_before": 14, "in_import_cycle": true}

## Diff hunks
- src/textual/widgets/_select.py: ["+    def on_option_list_option_highlighted(", "+        self, event: OptionList.OptionHighlighted", "+    ) -> None:", "+        \"\"\"Stop option list highlighted messages leaking.\"\"\"", "+        event.stop()", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
