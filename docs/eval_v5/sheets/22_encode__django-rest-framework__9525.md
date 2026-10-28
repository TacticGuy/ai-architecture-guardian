# encode/django-rest-framework#9525

Title: Drop deprecated AutoSchema._get_reference method (#9525)
Predicted degrading: True
Risk score / threshold: 0.468965 / 0.441173
GitHub PR: https://github.com/encode/django-rest-framework/pull/9525

## Top edges
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> CONTAINS -> rest_framework/schemas/openapi.py:rest_framework.schemas.openapi.AutoSchema (attribution -0.035885; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> external_module:urllib.parse (attribution 0.01456; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> CONTAINS -> rest_framework/schemas/openapi.py:rest_framework.schemas.openapi.SchemaGenerator (attribution -0.01322; added=False)
- rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator -> CONTAINS -> rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator._initialise_endpoints (attribution 0.008874; added=False)
- rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator -> CONTAINS -> rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator._get_paths_and_endpoints (attribution 0.008602; added=False)
- rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator -> CONTAINS -> rest_framework/schemas/generators.py:rest_framework.schemas.generators.BaseSchemaGenerator.has_view_permissions (attribution 0.008153; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> external_module:operator (attribution 0.005133; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> external_module:decimal (attribution 0.005081; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> external_module:django.core.validators (attribution 0.005046; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> external_module:warnings (attribution 0.003059; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> rest_framework/schemas/utils.py:rest_framework.schemas.utils (attribution -0.002497; added=False)
- rest_framework/schemas/openapi.py:rest_framework.schemas.openapi -> IMPORTS -> rest_framework/schemas/generators.py:rest_framework.schemas.generators (attribution -0.002008; added=False)

## Touched module coupling
- rest_framework: {"ca_after": 9, "ca_before": 10, "ce_after": 0, "ce_before": 0, "in_import_cycle": false}
- rest_framework.schemas.openapi: {"ca_after": 2, "ca_before": 2, "ce_after": 9, "ce_before": 10, "in_import_cycle": true}

## Diff hunks
- rest_framework/schemas/openapi.py: ["-", "-    def _get_reference(self, serializer):", "-        warnings.warn(", "-            \"Method `_get_reference()` has been renamed to `get_reference()`. \"", "-            \"The old name will be removed in DRF v3.16.\",", "-            RemovedInDRF316Warning, stacklevel=2", "-        )", "-        return self.get_reference(serializer)"]
- rest_framework/__init__.py: ["-class RemovedInDRF316Warning(DeprecationWarning):", "-    pass", "-", "-"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
