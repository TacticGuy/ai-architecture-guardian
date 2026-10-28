# arrow-py/arrow#776

Title: Adds "week" locale support for zh_tw (#776)
Predicted degrading: False
Risk score / threshold: 0.440278 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/776

## Top edges
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_number (attribution 0.004983; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.ordinal_number (attribution 0.00416; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe_multi (attribution 0.004123; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.meridian (attribution 0.004047; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.year_abbreviation (attribution 0.004035; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.year_full (attribution 0.004035; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe (attribution 0.004009; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.__init__ (attribution 0.003968; added=False)
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.humanize (attribution 0.00383; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_abbreviation (attribution 0.003801; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_name (attribution 0.003801; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_abbreviation (attribution 0.003801; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["+    and_word = \"\u548c\"", "-        \"second\": \"\u4e00\u79d2\",", "-        \"seconds\": \"{0}\u5e7e\u79d2\",", "+        \"second\": \"1\u79d2\",", "+        \"seconds\": \"{0}\u79d2\",", "+        \"week\": \"1\u9031\",", "+        \"weeks\": \"{0}\u9031\","]
- arrow/locales.py: ["-    day_names = [\"\", \"\u5468\u4e00\", \"\u5468\u4e8c\", \"\u5468\u4e09\", \"\u5468\u56db\", \"\u5468\u4e94\", \"\u5468\u516d\", \"\u5468\u65e5\"]", "+    day_names = [\"\", \"\u9031\u4e00\", \"\u9031\u4e8c\", \"\u9031\u4e09\", \"\u9031\u56db\", \"\u9031\u4e94\", \"\u9031\u516d\", \"\u9031\u65e5\"]"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
