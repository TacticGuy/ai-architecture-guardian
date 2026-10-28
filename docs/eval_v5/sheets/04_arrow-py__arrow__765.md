# arrow-py/arrow#765

Title: Merge pull request #765 from krisfremen/pytest_conversion
Predicted degrading: False
Risk score / threshold: 0.441004 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/765

## Top edges
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_number (attribution 0.004933; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.ordinal_number (attribution 0.004118; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe_multi (attribution 0.00406; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.year_abbreviation (attribution 0.003989; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.year_full (attribution 0.003989; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.meridian (attribution 0.003988; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe (attribution 0.003974; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.__init__ (attribution 0.0039; added=False)
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.humanize (attribution 0.003754; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_abbreviation (attribution 0.003749; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_name (attribution 0.003749; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_abbreviation (attribution 0.003749; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["+def get_locale_by_class_name(name):", "+    \"\"\"Returns an appropriate :class:`Locale <arrow.locales.Locale>`", "+    corresponding to an locale class name.", "+", "+    :param name: the name of the locale class.", "+", "+    \"\"\"", "+    locale_cls = globals()[name]", "+", "+    if locale_cls is None:", "+        raise ValueError(\"Unsupported locale '{}'\".format(name))", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
