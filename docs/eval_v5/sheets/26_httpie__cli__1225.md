# httpie/cli#1225

Title: Formalize @ suffix for all operators (#1225)
Predicted degrading: False
Risk score / threshold: 0.433345 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1225

## Top edges
- httpie/cli/requestitems.py:httpie.cli.requestitems.json_only.wrapper -> CALLS -> httpie/compat.py:httpie.compat.cached_property.func (attribution -0.012691; added=False)
- httpie/core.py:httpie.core.program -> CONTAINS -> httpie/core.py:httpie.core.program.request_body_read_callback (attribution -0.004974; added=False)
- httpie/core.py:httpie.core.program -> CALLS -> httpie/core.py:httpie.core.get_output_options (attribution 0.004875; added=False)
- httpie/cli/definition.py:httpie.cli.definition -> CALLS -> httpie/cli/argparser.py:httpie.cli.argparser.HTTPieArgumentParser (attribution 0.004517; added=False)
- httpie/client.py:httpie.client.finalize_headers -> CALLS -> httpie/cli/dicts.py:httpie.cli.dicts.HTTPHeadersDict.add (attribution 0.003915; added=False)
- httpie/cli/requestitems.py:httpie.cli.requestitems.json_only.wrapper -> CALLS -> httpie/cli/exceptions.py:httpie.cli.exceptions.ParseError (attribution -0.003643; added=False)
- httpie/cli/requestitems.py:httpie.cli.requestitems.load_text_file -> CALLS -> external_callable:f.read (attribution 0.003312; added=False)
- httpie/cli/requestitems.py:httpie.cli.requestitems.load_text_file -> CALLS -> external_callable:f.read.decode (attribution 0.003312; added=False)
- httpie/cli/requestitems.py:httpie.cli.requestitems -> IMPORTS -> httpie/cli/exceptions.py:httpie.cli.exceptions (attribution -0.002888; added=False)
- httpie/cli/constants.py:httpie.cli.constants -> CONTAINS -> httpie/cli/constants.py:httpie.cli.constants.PRETTY_MAP (attribution -0.002834; added=False)
- httpie/cli/constants.py:httpie.cli.constants -> CONTAINS -> httpie/cli/constants.py:httpie.cli.constants.PRETTY_STDOUT_TTY_ONLY (attribution -0.002834; added=False)
- httpie/cli/constants.py:httpie.cli.constants -> CONTAINS -> httpie/cli/constants.py:httpie.cli.constants.OUT_REQ_HEAD (attribution -0.002832; added=False)

## Touched module coupling
- httpie.cli.constants: {"ca_after": 5, "ca_before": 5, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}
- httpie.cli.requestitems: {"ca_after": 1, "ca_before": 1, "ce_after": 7, "ce_before": 7, "in_import_cycle": false}

## Diff hunks
- httpie/cli/requestitems.py: ["+            SEPARATOR_HEADER_EMBED: (", "+                process_embed_header_arg,", "+                instance.headers,", "+            ),"]
- httpie/cli/constants.py: ["+SEPARATOR_HEADER_EMBED = ':@'"]
- httpie/cli/constants.py: ["+    SEPARATOR_HEADER_EMBED,"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
