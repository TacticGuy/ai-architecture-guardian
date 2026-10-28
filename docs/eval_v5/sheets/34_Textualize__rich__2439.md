# Textualize/rich#2439

Title: Merge pull request #2439 from Textualize/new-markdown-parser
Predicted degrading: False
Risk score / threshold: 0.429677 / 0.441173
GitHub PR: https://github.com/Textualize/rich/pull/2439

## Top edges
- rich/markdown.py:rich.markdown -> IMPORTS -> external_module:markdown_it (attribution 0.023801; added=True)
- rich/markdown.py:rich.markdown -> IMPORTS -> external_module:markdown_it.token (attribution 0.023801; added=True)
- rich/markdown.py:rich.markdown -> IMPORTS -> external_module:pydoc (attribution 0.023098; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.MarkdownElement (attribution -0.018935; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.ListElement (attribution -0.017994; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.ImageItem (attribution -0.01795; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.ListItem (attribution -0.01791; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.Heading (attribution -0.017861; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.TextElement (attribution -0.017766; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.Markdown (attribution -0.01768; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.CodeBlock (attribution -0.017516; added=False)
- rich/markdown.py:rich.markdown -> CONTAINS -> rich/markdown.py:rich.markdown.Paragraph (attribution -0.017486; added=False)

## Touched module coupling
- rich.default_styles: {"ca_after": 2, "ca_before": 2, "ce_after": 4, "ce_before": 4, "in_import_cycle": true}
- rich.markdown: {"ca_after": 2, "ca_before": 2, "ce_after": 12, "ce_before": 13, "in_import_cycle": true}

## Diff hunks
- rich/markdown.py: ["+    def _flatten_tokens(self, tokens: Iterable[Token]) -> Iterable[Token]:", "+        \"\"\"Flattens the token stream.\"\"\"", "+        for token in tokens:", "+            is_fence = token.type == \"fence\"", "+            is_image = token.tag == \"img\"", "+            if token.children and not (is_image or is_fence):", "+                yield from self._flatten_tokens(token.children)", "+            else:", "+                yield token", "+"]
- rich/markdown.py: ["-        nodes = self.parsed.walker()", "-        inlines = self.inlines", "+        tokens = self.parsed", "+        inline_style_tags = self.inlines", "-        for current, entering in nodes:", "-            node_type = current.t", "-            if node_type in (\"html_inline\", \"html_block\", \"text\"):", "-                context.on_text(current.literal.replace(\"\\n\", \" \"), node_type)", "-            elif node_type == \"linebreak\":", "-                if entering:", "-                    context.on_text(\"\\n\", node_type)", "+        _new_line_segment = Segment.line()"]
- rich/markdown.py: ["+class Link(TextElement):", "+    @classmethod", "+    def create(cls, markdown: \"Markdown\", token: Token) -> \"MarkdownElement\":", "+        url = token.attrs.get(\"href\", \"#\")", "+        return cls(token.content, str(url))", "+", "+    def __init__(self, text: str, href: str):", "+        self.text = Text(text)", "+        self.href = href", "+", "+", "-    def create(cls, markdown: \"Markdown\", node: Any) -> \"MarkdownElement\":"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
