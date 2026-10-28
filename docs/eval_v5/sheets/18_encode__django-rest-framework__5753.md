# encode/django-rest-framework#5753

Title: permissions: Allow permissions to be composed (#5753)
Predicted degrading: False
Risk score / threshold: 0.378967 / 0.441173
GitHub PR: https://github.com/encode/django-rest-framework/pull/5753

## Top edges
- rest_framework/permissions.py:rest_framework.permissions -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.SAFE_METHODS (attribution -0.019783; added=False)
- rest_framework/permissions.py:rest_framework.permissions.OperandHolder.__call__ -> CALLS -> external_callable:self.op1_class (attribution -0.004964; added=True)
- rest_framework/permissions.py:rest_framework.permissions.OperandHolder.__call__ -> CALLS -> external_callable:self.op2_class (attribution -0.004964; added=True)
- rest_framework/permissions.py:rest_framework.permissions.OperandHolder.__call__ -> CALLS -> external_callable:self.operator_class (attribution -0.004964; added=True)
- rest_framework/permissions.py:rest_framework.permissions -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.AND (attribution 0.003996; added=False)
- rest_framework/permissions.py:rest_framework.permissions -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.OR (attribution 0.003996; added=False)
- rest_framework/permissions.py:rest_framework.permissions -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.OperandHolder (attribution 0.003909; added=False)
- rest_framework/permissions.py:rest_framework.permissions -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.BasePermissionMetaclass (attribution 0.003268; added=False)
- rest_framework/permissions.py:rest_framework.permissions.BasePermission -> CALLS -> external_callable:django.utils.six.add_metaclass (attribution -0.003084; added=True)
- rest_framework/permissions.py:rest_framework.permissions.AND -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.AND.has_permission (attribution -0.002647; added=False)
- rest_framework/permissions.py:rest_framework.permissions.OR -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.OR.has_permission (attribution -0.002647; added=False)
- rest_framework/permissions.py:rest_framework.permissions.AND -> CONTAINS -> rest_framework/permissions.py:rest_framework.permissions.AND.has_object_permission (attribution -0.002634; added=False)

## Touched module coupling
- rest_framework.permissions: {"ca_after": 0, "ca_before": 0, "ce_after": 1, "ce_before": 1, "in_import_cycle": false}

## Diff hunks
- rest_framework/permissions.py: ["+from django.utils import six", "+class OperandHolder:", "+    def __init__(self, operator_class, op1_class, op2_class):", "+        self.operator_class = operator_class", "+        self.op1_class = op1_class", "+        self.op2_class = op2_class", "+", "+    def __call__(self, *args, **kwargs):", "+        op1 = self.op1_class(*args, **kwargs)", "+        op2 = self.op2_class(*args, **kwargs)", "+        return self.operator_class(op1, op2)", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
