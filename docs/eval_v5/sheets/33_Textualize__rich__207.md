# Textualize/rich#207

Title: Merge pull request #207 from hedythedev/rule-mult-chars
Predicted degrading: True
Risk score / threshold: 0.682847 / 0.441173
GitHub PR: https://github.com/Textualize/rich/pull/207

## Top edges
- rich/console.py:rich.console.Console.__init__ -> CALLS -> rich/console.py:rich.console.ConsoleThreadLocals (attribution 0.020591; added=False)
- rich/console.py:rich.console.Console.print -> CALLS -> external_callable:self.options.update (attribution 0.019332; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:caller.filename.rpartition (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:caller.filename.startswith (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:caller.frame.f_locals.items (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:inspect.stack (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:os.path.abspath (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:renderables.append (attribution 0.017043; added=False)
- rich/console.py:rich.console.Console.log -> CALLS -> external_callable:key.startswith (attribution 0.016983; added=False)
- rich/console.py:rich.console.Console._collect_renderables -> CONTAINS -> rich/console.py:rich.console.Console._collect_renderables.align_append (attribution 0.015308; added=False)
- rich/console.py:rich.console.Console._collect_renderables -> CONTAINS -> rich/console.py:rich.console.Console._collect_renderables.check_text (attribution 0.015157; added=False)
- rich/console.py:rich.console.Console.export_html -> CALLS -> external_callable:escape (attribution 0.014914; added=False)

## Touched module coupling
- rich.console: {"ca_after": 34, "ca_before": 34, "ce_after": 24, "ce_before": 24, "in_import_cycle": true}
- rich.rule: {"ca_after": 3, "ca_before": 3, "ce_after": 6, "ce_before": 6, "in_import_cycle": true}

## Diff hunks
- rich/console.py: ["-        character: str = \"\u2500\",", "+        character: Optional[str] = None,", "+        characters: str = \"\u2500\",", "-            character (str, optional): Character to form the line. Defaults to \"\u2500\".", "+            character: Will be deprecated in v6.0.0, please use characters argument instead.", "+            characters (str, optional): Character(s) to form the line. Defaults to \"\u2500\".", "-        rule = Rule(title=title, character=character, style=style)", "+        if character:", "+            characters = character", "+        rule = Rule(title=title, characters=characters, style=style)"]
- rich/rule.py: ["-        character (str, optional): Character used to draw the line. Defaults to \"\u2500\".", "+        character: Will be deprecated in v6.0.0, please use characters argument instead.", "+        characters (str, optional): Character(s) used to draw the line. Defaults to \"\u2500\"."]
- rich/rule.py: ["-            center = (width - cell_len(title_text.plain)) // 2", "-            rule_text.append(character * (center - 1) + \" \", self.style)", "+            side_width = (width - cell_len(title_text.plain)) // 2", "+            left = Text(characters * (side_width // chars_len + 1))", "+            left.truncate(side_width - 1)", "+            right_length = width - cell_len(left.plain) - cell_len(title_text.plain)", "+            right = Text(characters * (side_width // chars_len + 1))", "+            right.truncate(right_length)", "+            rule_text.append(left.plain + \" \", self.style)", "-            rule_text.append(", "-                \" \" + character * (width - cell_len(rule_text.plain) - 1), self.style", "-            )"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
