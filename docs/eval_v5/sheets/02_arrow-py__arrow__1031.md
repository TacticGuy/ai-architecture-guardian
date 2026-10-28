# arrow-py/arrow#1031

Title: Refactored Finnish Locale (#1031)
Predicted degrading: True
Risk score / threshold: 0.467506 / 0.441173
GitHub PR: https://github.com/arrow-py/arrow/pull/1031

## Top edges
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.humanize (attribution 0.009897; added=False)
- arrow/arrow.py:arrow.arrow.Arrow -> CONTAINS -> arrow/arrow.py:arrow.arrow.Arrow.dehumanize (attribution 0.009689; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_number (attribution 0.008605; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe_multi (attribution 0.008189; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.ordinal_number (attribution 0.007372; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.describe (attribution 0.007291; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.meridian (attribution 0.007063; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.__init__ (attribution 0.006981; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale._name_to_ordinal (attribution 0.006912; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_abbreviation (attribution 0.00689; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.day_name (attribution 0.00689; added=False)
- arrow/locales.py:arrow.locales.Locale -> CONTAINS -> arrow/locales.py:arrow.locales.Locale.month_abbreviation (attribution 0.00689; added=False)

## Touched module coupling
- arrow.locales: {"ca_after": 3, "ca_before": 3, "ce_after": 1, "ce_before": 1, "in_import_cycle": false}

## Diff hunks
- arrow/locales.py: ["-    timeframes: ClassVar[Mapping[TimeFrameLiteral, List[str]]] = {", "-        \"now\": [\"juuri nyt\", \"juuri nyt\"],", "-        \"second\": [\"sekunti\", \"sekunti\"],", "-        \"seconds\": [\"{0} muutama sekunti\", \"{0} muutaman sekunnin\"],", "-        \"minute\": [\"minuutti\", \"minuutin\"],", "-        \"minutes\": [\"{0} minuuttia\", \"{0} minuutin\"],", "-        \"hour\": [\"tunti\", \"tunnin\"],", "-        \"hours\": [\"{0} tuntia\", \"{0} tunnin\"],", "-        \"day\": [\"p\u00e4iv\u00e4\", \"p\u00e4iv\u00e4\"],", "-        \"days\": [\"{0} p\u00e4iv\u00e4\u00e4\", \"{0} p\u00e4iv\u00e4n\"],", "-        \"month\": [\"kuukausi\", \"kuukauden\"],", "-        \"months\": [\"{0} kuukautta\", \"{0} kuukauden\"],"]
- arrow/locales.py: ["-    # TODO: Fix return type", "-    def _format_timeframe(self, timeframe: TimeFrameLiteral, delta: int) -> Tuple[str, str]:  # type: ignore", "-        return (", "-            self.timeframes[timeframe][0].format(abs(delta)),", "-            self.timeframes[timeframe][1].format(abs(delta)),", "-        )", "-", "-    def _format_relative(", "-        self,", "-        humanized: str,", "-        timeframe: TimeFrameLiteral,", "-        delta: Union[float, int],"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
