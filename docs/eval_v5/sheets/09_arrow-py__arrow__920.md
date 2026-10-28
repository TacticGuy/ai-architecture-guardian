# arrow-py/arrow#920

Title: Utilize __init_subclass__ instead of inspect on Locale mapping to improve type checking (#920)
Predicted degrading: False
Risk score / threshold: 0.249516 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/920

## Top edges
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.Locale (attribution -0.054268; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.get_locale_by_class_name (attribution 0.022748; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.get_locale (attribution 0.015469; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.ThaiLocale (attribution -0.015322; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.FinnishLocale (attribution -0.015181; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.BrazilianPortugueseLocale (attribution -0.015166; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.GermanBaseLocale (attribution -0.01496; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.EnglishLocale (attribution -0.014692; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.KoreanLocale (attribution -0.014678; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.HebrewLocale (attribution -0.014626; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.FrenchCanadianLocale (attribution -0.014539; added=False)
- arrow/locales.py:arrow.locales -> CONTAINS -> arrow/locales.py:arrow.locales.FrenchLocale (attribution -0.014539; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["+    def __init_subclass__(cls, **kwargs: Any) -> None:", "+        for locale_name in cls.names:", "+            if locale_name in _locale_map:", "+                raise LookupError(f\"Duplicated locale name: {locale_name}\")", "+", "+            _locale_map[locale_name] = cls", "+"]
- arrow/locales.py: ["+_locale_map: Dict[str, Type[\"Locale\"]] = dict()", "+", "+"]
- arrow/locales.py: ["-    locale_cls = _locales.get(name.lower())", "+    locale_cls = _locale_map.get(name.lower())"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
