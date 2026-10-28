# celery/celery#9879

Title: Feature: Add support credential_provider to Redis Backend (#9879)
Predicted degrading: True
Risk score / threshold: 0.443395 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/9879

## Top edges
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.exception_to_python (attribution 0.012433; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_RETRY_LIMIT_EXCEEDED (attribution -0.012388; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_LOST (attribution -0.012379; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_REDIS_SENTINEL_MISSING (attribution -0.012139; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_REDIS_SSL_PARAMS_AND_SCHEME_MISMATCH (attribution -0.01207; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_REDIS_MISSING (attribution -0.012031; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.E_REDIS_SSL_CERT_REQS_MISSING_INVALID (attribution -0.012031; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.W_REDIS_SSL_CERT_NONE (attribution -0.012031; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.W_REDIS_SSL_CERT_OPTIONAL (attribution -0.012031; added=False)
- celery/backends/redis.py:celery.backends.redis -> CONTAINS -> celery/backends/redis.py:celery.backends.redis.logger (attribution -0.011929; added=False)
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.chord_error_from_stack (attribution 0.011474; added=False)
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.encode_result (attribution 0.011114; added=False)

## Touched module coupling
- celery.backends.redis: {"ca_after": 1, "ca_before": 1, "ce_after": 17, "ce_before": 17, "in_import_cycle": false}

## Diff hunks
- celery/backends/redis.py: ["+        # credential provider as query string", "+        credential_provider = query.pop(\"credential_provider\", None)", "+        if credential_provider:", "+            if isinstance(credential_provider, str):", "+                credential_provider_cls = symbol_by_name(credential_provider)", "+                credential_provider = credential_provider_cls()", "+", "+            if not isinstance(credential_provider, CredentialProvider):", "+                raise ValueError(", "+                    \"Credential provider is not an instance of a redis.CredentialProvider or a subclass\"", "+                )", "+"]
- celery/backends/redis.py: ["+        credential_provider = _get('redis_backend_credential_provider')"]
- celery/backends/redis.py: ["+        if credential_provider:", "+            # if credential provider passed as string or query param", "+            if isinstance(credential_provider, str):", "+                credential_provider_cls = symbol_by_name(credential_provider)", "+                credential_provider = credential_provider_cls()", "+", "+            if not isinstance(credential_provider, CredentialProvider):", "+                raise ValueError(", "+                    \"Credential provider is not an instance of a redis.CredentialProvider or a subclass\"", "+                )", "+", "+            self.connparams['credential_provider'] = credential_provider"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
