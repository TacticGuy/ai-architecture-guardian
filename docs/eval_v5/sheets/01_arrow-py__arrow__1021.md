# arrow-py/arrow#1021

Title: Refactor of Czech Locale For Dehumanize Support (#1021)
Predicted degrading: True
Risk score / threshold: 0.466733 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/1021

## Top edges
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.humanize (attribution 0.009886; added=False)
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.dehumanize (attribution 0.009675; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_number (attribution 0.008583; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe_multi (attribution 0.008176; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.ordinal_number (attribution 0.00735; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe (attribution 0.007268; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.meridian (attribution 0.007044; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.__init__ (attribution 0.006959; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale._name_to_ordinal (attribution 0.006895; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_abbreviation (attribution 0.006865; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_name (attribution 0.006865; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_abbreviation (attribution 0.006865; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 1, "ce_before": 1, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["-        elif delta > 0:", "-            key = \"future\"", "-        else:", "+        elif delta < 0:", "-        form: Union[List[str], str] = form[key]", "-", "-        if isinstance(form, list):", "-            if 2 <= abs_delta % 10 <= 4 and (", "+        else:", "+            # Needed since both regular future and future-singular and future-paucal cases", "+            if \"future-singular\" not in form:", "+                key = \"future\""]
- arrow/locales.py: ["-    timeframes: ClassVar[", "-        Mapping[TimeFrameLiteral, Union[Mapping[str, Union[List[str], str]], str]]", "-    ] = {", "+    timeframes: ClassVar[Mapping[TimeFrameLiteral, Union[str, Mapping[str, str]]]] = {", "-        \"seconds\": {\"past\": \"{0} sekundami\", \"future\": [\"{0} sekundy\", \"{0} sekund\"]},", "+        \"seconds\": {", "+            \"past\": \"{0} sekundami\",", "+            \"future-singular\": \"{0} sekundy\",", "+            \"future-paucal\": \"{0} sekund\",", "+        },", "-        \"minutes\": {\"past\": \"{0} minutami\", \"future\": [\"{0} minuty\", \"{0} minut\"]},", "+        \"minutes\": {"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
