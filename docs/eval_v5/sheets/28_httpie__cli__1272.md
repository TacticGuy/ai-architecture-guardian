# httpie/cli#1272

Title: 3.0 release prep (#1272)
Predicted degrading: False
Risk score / threshold: 0.409355 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1272

## Top edges
- httpie/cli/definition.py:httpie.cli.definition -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.053335; added=False)
- httpie/manager/__main__.py:httpie.manager.__main__.main -> IMPORTS -> httpie/core.py:httpie.core (attribution 0.045424; added=False)
- httpie/client.py:httpie.client -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.041941; added=False)
- httpie/config.py:httpie.config -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.033705; added=False)
- httpie/manager/__main__.py:httpie.manager.__main__.is_http_command -> IMPORTS -> httpie/manager/cli.py:httpie.manager.cli (attribution 0.029461; added=False)
- httpie/core.py:httpie.core -> IMPORTS -> httpie/client.py:httpie.client (attribution -0.028471; added=False)
- httpie/__main__.py:httpie.__main__.main -> IMPORTS -> httpie/core.py:httpie.core (attribution 0.022305; added=False)
- httpie/core.py:httpie.core -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.021431; added=False)
- httpie/manager/cli.py:httpie.manager.cli -> IMPORTS -> httpie/__init__.py:httpie (attribution -0.017756; added=False)
- httpie/manager/__main__.py:httpie.manager.__main__ -> IMPORTS -> httpie/manager/cli.py:httpie.manager.cli (attribution -0.013157; added=False)
- httpie/sessions.py:httpie.sessions -> IMPORTS -> httpie/config.py:httpie.config (attribution -0.011716; added=False)
- httpie/manager/__main__.py:httpie.manager.__main__.main -> CALLS -> httpie/manager/__main__.py:httpie.manager.__main__.is_http_command (attribution 0.011609; added=False)

## Touched module coupling
- httpie: {"ca_after": 5, "ca_before": 5, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
