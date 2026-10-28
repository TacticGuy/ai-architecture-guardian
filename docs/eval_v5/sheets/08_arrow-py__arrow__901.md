# arrow-py/arrow#901

Title: Fix simple docs typo, inpute -> input (#901)
Predicted degrading: True
Risk score / threshold: 0.476362 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/901

## Top edges
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.humanize (attribution 0.009309; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_number (attribution 0.0085; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe_multi (attribution 0.007768; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.ordinal_number (attribution 0.006977; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe (attribution 0.006816; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.meridian (attribution 0.006662; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.__init__ (attribution 0.006623; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_abbreviation (attribution 0.006441; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_name (attribution 0.006441; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_abbreviation (attribution 0.006441; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_name (attribution 0.006441; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale._name_to_ordinal (attribution 0.006432; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["-    corresponding to an inpute locale name.", "+    corresponding to an input locale name."]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
