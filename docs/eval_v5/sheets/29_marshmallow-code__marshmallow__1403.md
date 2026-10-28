# marshmallow-code/marshmallow#1403

Title: Restore inheritance hierarchy of Number fields (#1403)
Predicted degrading: False
Risk score / threshold: 0.3722 / 0.441173
GitHub PR: https://github.com/marshmallow-code/marshmallow/pull/1403

## Top edges
- src/marshmallow/fields.py:marshmallow.fields.Decimal -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Decimal.__init__ (attribution -0.012616; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number._format_num (attribution -0.01212; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Integer -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Integer.__init__ (attribution -0.011791; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Decimal -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Decimal._format_num (attribution -0.011777; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number._validated (attribution -0.011771; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number.__init__ (attribution -0.011701; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Integer -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Integer._validated (attribution -0.011687; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Decimal -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Decimal._to_string (attribution -0.011671; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number._deserialize (attribution -0.011658; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Decimal -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Decimal._validated (attribution -0.011609; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number._to_string (attribution -0.011378; added=False)
- src/marshmallow/fields.py:marshmallow.fields.Number -> CONTAINS -> src/marshmallow/fields.py:marshmallow.fields.Number._serialize (attribution -0.011313; added=False)

## Touched module coupling
- marshmallow.fields: {"ca_after": 3, "ca_before": 3, "ce_after": 6, "ce_before": 6, "in_import_cycle": true}

## Diff hunks
- src/marshmallow/fields.py: ["-class Number(_BaseNumber):", "-    \"\"\"Base class for number fields.", "-", "-    :param bool as_string: If `True`, format the serialized value as a string.", "-    :param kwargs: The same keyword arguments that :class:`Field` receives.", "-    \"\"\"", "-", "-    num_type = float", "-", "-", "-class Integer(_BaseNumber):", "+class Integer(Number):"]
- src/marshmallow/fields.py: ["-class _BaseNumber(Field):", "-    \"\"\"Base implementation for all number classes. Users should not use this class directly.", "-    This class is considered private.", "+class Number(Field):", "+    \"\"\"Base class for number fields.", "+", "+    :param bool as_string: If `True`, format the serialized value as a string.", "+    :param kwargs: The same keyword arguments that :class:`Field` receives.", "+    num_type = float  # type: typing.Type", "+"]
- src/marshmallow/fields.py: ["-    @property", "-    def num_type(self):", "-        raise NotImplementedError", "-"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
