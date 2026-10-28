# encode/django-rest-framework#5818

Title: Fix authtoken views imports (#5818)
Predicted degrading: False
Risk score / threshold: 0.402582 / 0.441173
GitHub PR: https://github.com/encode/django-rest-framework/pull/5818

## Top edges
- rest_framework/schemas/inspectors.py:rest_framework.schemas.inspectors.field_to_schema -> CALLS -> external_callable:coreschema.String (attribution 0.027792; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views.ObtainAuthToken.post -> CALLS -> external_callable:self.serializer_class (attribution -0.021399; added=False)
- rest_framework/templatetags/rest_framework.py:rest_framework.templatetags.rest_framework.form_for_link -> IMPORTS -> external_module:coreschema (attribution 0.020062; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views.ObtainAuthToken -> CALLS -> external_callable:coreschema.String (attribution -0.019886; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views -> IMPORTS -> rest_framework/authtoken/serializers.py:rest_framework.authtoken.serializers (attribution -0.019523; added=False)
- rest_framework/templatetags/rest_framework.py:rest_framework.templatetags.rest_framework.form_for_link -> CALLS -> external_callable:coreschema.String (attribution 0.018906; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views -> CONTAINS -> rest_framework/authtoken/views.py:rest_framework.authtoken.views.obtain_auth_token (attribution -0.018692; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views.ObtainAuthToken -> CALLS -> external_callable:coreapi.Field (attribution -0.015124; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views.ObtainAuthToken.post -> CALLS -> external_callable:rest_framework.authtoken.models.Token.objects.get_or_create (attribution -0.011609; added=False)
- rest_framework/routers.py:rest_framework.routers -> IMPORTS -> rest_framework/schemas/__init__.py:rest_framework.schemas (attribution -0.01043; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views.ObtainAuthToken -> CALLS -> rest_framework/schemas/inspectors.py:rest_framework.schemas.inspectors.ManualSchema (attribution -0.009166; added=False)
- rest_framework/authtoken/views.py:rest_framework.authtoken.views -> IMPORTS -> rest_framework/schemas/__init__.py:rest_framework.schemas (attribution -0.007122; added=False)

## Touched module coupling
- rest_framework.authtoken.views: {"ca_after": 0, "ca_before": 0, "ce_after": 8, "ce_before": 8, "in_import_cycle": false}

## Diff hunks
- rest_framework/authtoken/views.py: ["+import coreapi", "+import coreschema", "-from rest_framework.views import APIView", "-import coreapi", "-import coreschema", "+from rest_framework.views import APIView"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
