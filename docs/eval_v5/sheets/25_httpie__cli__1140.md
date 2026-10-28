# httpie/cli#1140

Title: v2.5.0 (#1140)
Predicted degrading: False
Risk score / threshold: 0.377205 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1140

## Top edges
- httpie/cli/definition.py:httpie.cli.definition -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.093057; added=False)
- httpie/client.py:httpie.client -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.061961; added=False)
- httpie/config.py:httpie.config -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.051585; added=False)
- httpie/core.py:httpie.core -> IMPORTS -> httpie/client.py:httpie.client (attribution -0.044725; added=False)
- httpie/__main__.py:httpie.__main__.main -> IMPORTS -> httpie/core.py:httpie.core (attribution 0.043892; added=False)
- httpie/core.py:httpie.core -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.043417; added=False)
- httpie/sessions.py:httpie.sessions -> IMPORTS -> httpie/config.py:httpie.config (attribution -0.014607; added=False)
- httpie/core.py:httpie.core.main -> IMPORTS -> httpie/cli/definition.py:httpie.cli.definition (attribution 0.012287; added=False)
- httpie/__main__.py:httpie.__main__ -> CALLS -> httpie/core.py:httpie.core.main (attribution -0.009149; added=False)
- httpie/context.py:httpie.context -> IMPORTS -> httpie/config.py:httpie.config (attribution -0.007582; added=False)
- httpie/__main__.py:httpie.__main__ -> CONTAINS -> httpie/__main__.py:httpie.__main__.main (attribution 0.005438; added=False)
- httpie/__main__.py:httpie.__main__.main -> CALLS -> httpie/core.py:httpie.core.main (attribution 0.004977; added=False)

## Touched module coupling
- httpie: {"ca_after": 4, "ca_before": 4, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
