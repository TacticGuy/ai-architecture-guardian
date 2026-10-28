# encode/django-rest-framework#7530

Title: Fixes `BrowsableAPIRenderer` for usage with `ListSerializer`. (#7530)
Predicted degrading: False
Risk score / threshold: 0.438304 / 0.441173
GitHub PR: https://github.com/encode/django-rest-framework/pull/7530

## Top edges
- rest_framework/pagination.py:rest_framework.pagination.BasePagination -> CONTAINS -> rest_framework/pagination.py:rest_framework.pagination.BasePagination.get_results (attribution 0.005827; added=False)
- rest_framework/views.py:rest_framework.views.APIView -> CONTAINS -> rest_framework/views.py:rest_framework.views.APIView.check_permissions (attribution 0.005491; added=False)
- rest_framework/views.py:rest_framework.views.APIView -> CONTAINS -> rest_framework/views.py:rest_framework.views.APIView.check_object_permissions (attribution 0.005383; added=False)
- rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer -> CONTAINS -> rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer.get_paths (attribution 0.005224; added=False)
- rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer -> CONTAINS -> rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer.get_parameters (attribution 0.004717; added=False)
- rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer -> CONTAINS -> rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer.get_structure (attribution 0.004686; added=False)
- rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer -> CONTAINS -> rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer.get_schema (attribution 0.004512; added=False)
- rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer -> CONTAINS -> rest_framework/renderers.py:rest_framework.renderers._BaseOpenAPIRenderer.get_operation (attribution 0.004268; added=False)
- rest_framework/status.py:rest_framework.status -> CONTAINS -> rest_framework/status.py:rest_framework.status.HTTP_303_SEE_OTHER (attribution -0.003083; added=False)
- rest_framework/status.py:rest_framework.status -> CONTAINS -> rest_framework/status.py:rest_framework.status.HTTP_201_CREATED (attribution -0.003077; added=False)
- rest_framework/status.py:rest_framework.status -> CONTAINS -> rest_framework/status.py:rest_framework.status.HTTP_200_OK (attribution -0.003075; added=False)
- rest_framework/status.py:rest_framework.status -> CONTAINS -> rest_framework/status.py:rest_framework.status.HTTP_401_UNAUTHORIZED (attribution -0.003063; added=False)

## Touched module coupling
- rest_framework.renderers: {"ca_after": 7, "ca_before": 7, "ce_after": 16, "ce_before": 16, "in_import_cycle": true}

## Diff hunks
- rest_framework/renderers.py: ["+                is_list_serializer = isinstance(serializer, serializers.ListSerializer)", "+                serializer = serializer.child if is_list_serializer else serializer", "+                data = [data] if is_list_serializer else data"]
- rest_framework/renderers.py: ["+        if isinstance(serializer, serializers.ListSerializer):", "+            return None", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
