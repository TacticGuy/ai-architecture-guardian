# arrow-py/arrow#708

Title: Merge pull request #708 from systemcatch/release-0153
Predicted degrading: True
Risk score / threshold: 0.451247 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/708

## Top edges
- arrow/__init__.py:arrow -> IMPORTS -> arrow/_version.py:arrow._version (attribution -0.14414; added=False)
- arrow/arrow.py:arrow.arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow (attribution 0.0; added=False)
- arrow/factory.py:arrow.factory -> CONTAINS -> arrow/factory.py:arrow.factory.ArrowFactory (attribution 0.0; added=False)
- arrow/parser.py:arrow.parser -> CONTAINS -> arrow/parser.py:arrow.parser.DateTimeParser (attribution 0.0; added=False)
- arrow/parser.py:arrow.parser -> CONTAINS -> arrow/parser.py:arrow.parser.ParserError (attribution 0.0; added=False)
- arrow/parser.py:arrow.parser -> CONTAINS -> arrow/parser.py:arrow.parser.ParserMatchError (attribution 0.0; added=False)
- arrow/parser.py:arrow.parser -> CONTAINS -> arrow/parser.py:arrow.parser.TzinfoParser (attribution 0.0; added=False)
- arrow/api.py:arrow.api -> CONTAINS -> arrow/api.py:arrow.api.factory (attribution 0.0; added=False)
- arrow/api.py:arrow.api -> CONTAINS -> arrow/api.py:arrow.api.get (attribution 0.0; added=False)
- arrow/api.py:arrow.api -> CONTAINS -> arrow/api.py:arrow.api.now (attribution 0.0; added=False)
- arrow/api.py:arrow.api -> CONTAINS -> arrow/api.py:arrow.api.utcnow (attribution 0.0; added=False)
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.fromdatetime (attribution 0.0; added=False)

## Touched module coupling
- arrow._version: {"ca_after": 1, "ca_before": 1, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
