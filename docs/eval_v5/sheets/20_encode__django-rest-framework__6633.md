# encode/django-rest-framework#6633

Title: Drop default 'utf-8' to .encode()/.decode() (#6633)
Predicted degrading: True
Risk score / threshold: 0.466816 / 0.441173
GitHub PR: https://github.com/encode/django-rest-framework/pull/6633

## Top edges
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.run_validators (attribution 0.005048; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.bind (attribution 0.004854; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.run_validation (attribution 0.004504; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.get_attribute (attribution 0.004322; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.__deepcopy__ (attribution 0.004285; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.get_default (attribution 0.004274; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.get_value (attribution 0.004253; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.__repr__ (attribution 0.004232; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.get_initial (attribution 0.00422; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.validate_empty_values (attribution 0.004144; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.root (attribution 0.004101; added=False)
- rest_framework/fields.py:rest_framework.fields.Field -> CONTAINS -> rest_framework/fields.py:rest_framework.fields.Field.fail (attribution 0.004078; added=False)

## Touched module coupling
- rest_framework.fields: {"ca_after": 3, "ca_before": 3, "ce_after": 12, "ce_before": 12, "in_import_cycle": false}
- rest_framework.management.commands.generateschema: {"ca_after": 0, "ca_before": 0, "ce_after": 3, "ce_before": 3, "in_import_cycle": false}
- rest_framework.parsers: {"ca_after": 1, "ca_before": 1, "ce_after": 5, "ce_before": 5, "in_import_cycle": false}
- rest_framework.renderers: {"ca_after": 6, "ca_before": 6, "ce_after": 17, "ce_before": 17, "in_import_cycle": true}
- rest_framework.utils.encoders: {"ca_after": 2, "ca_before": 2, "ce_after": 1, "ce_before": 1, "in_import_cycle": false}

## Diff hunks
- rest_framework/renderers.py: ["-        # On python 2.x json.dumps() returns bytestrings if ensure_ascii=True,", "-        # but if ensure_ascii=False, the return type is underspecified,", "-        # and may (or may not) be unicode.", "-        # On python 3.x json.dumps() returns unicode strings.", "-        if isinstance(ret, str):", "-            # We always fully escape \\u2028 and \\u2029 to ensure we output JSON", "-            # that is a strict javascript subset. If bytes were returned", "-            # by json.dumps() then we don't have these characters in any case.", "-            # See: http://timelessrepo.com/json-isnt-a-javascript-subset", "-            ret = ret.replace('\\u2028', '\\\\u2028').replace('\\u2029', '\\\\u2029')", "-            return bytes(ret.encode('utf-8'))", "-        return ret"]
- rest_framework/renderers.py: ["-        return yaml.dump(structure, default_flow_style=False).encode('utf-8')", "+        return yaml.dump(structure, default_flow_style=False).encode()"]
- rest_framework/renderers.py: ["-                content = content.decode('utf-8')", "+                content = content.decode()"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
