# Textualize/rich#1655

Title: Merge pull request #1655 from willmcgugan/word-wrap-codeblock
Predicted degrading: True
Risk score / threshold: 0.466862 / 0.441173
GitHub PR: https://github.com/Textualize/rich/pull/1655

## Top edges
- rich/console.py:rich.console.Console -> CONTAINS -> rich/console.py:rich.console.Console.get_style (attribution 0.013096; added=False)
- rich/console.py:rich.console.Console -> CONTAINS -> rich/console.py:rich.console.Console.render_lines (attribution 0.011663; added=False)
- rich/scope.py:rich.scope.render_scope -> CALLS -> rich/text.py:rich.text.Text.assemble (attribution 0.009626; added=False)
- rich/text.py:rich.text.Text -> CONTAINS -> rich/text.py:rich.text.Text.stylize (attribution 0.005775; added=False)
- rich/text.py:rich.text.Text -> CONTAINS -> rich/text.py:rich.text.Text.rstrip (attribution 0.005751; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.on_enter (attribution 0.005633; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.on_leave (attribution 0.005633; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.on_child_close (attribution 0.005526; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.create (attribution 0.005465; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.on_text (attribution 0.005431; added=False)
- rich/markdown.py:rich.markdown.MarkdownElement -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement.__rich_console__ (attribution 0.005072; added=False)
- rich/console.py:rich.console.Console.rule -> CALLS -> rich/rule.py:rich.rule.Rule (attribution 0.004514; added=False)

## Touched module coupling
- rich.markdown: {"ca_after": 2, "ca_before": 2, "ce_after": 13, "ce_before": 13, "in_import_cycle": true}

## Diff hunks
- rich/markdown.py: ["-            Syntax(code, self.lexer_name, theme=self.theme),", "+            Syntax(code, self.lexer_name, theme=self.theme, word_wrap=True),"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
