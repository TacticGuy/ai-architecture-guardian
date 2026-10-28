# celery/celery#5951

Title: Update __init__.py (#5951)
Predicted degrading: False
Risk score / threshold: 0.433148 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/5951

## Top edges
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.meta_from_decoded (attribution 0.013261; added=False)
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend._get_result_meta (attribution 0.011801; added=False)
- celery/backends/database/__init__.py:celery.backends.database -> CONTAINS -> celery/backends/database/__init__.py:celery.backends.database.logger (attribution -0.006783; added=False)
- celery/backends/database/__init__.py:celery.backends.database -> CONTAINS -> celery/backends/database/__init__.py:celery.backends.database.session_cleanup (attribution 0.005182; added=False)
- celery/backends/database/__init__.py:celery.backends.database -> IMPORTS -> celery/backends/database/models.py:celery.backends.database.models (attribution -0.004451; added=False)
- celery/backends/database/__init__.py:celery.backends.database -> CONTAINS -> celery/backends/database/__init__.py:celery.backends.database.retry (attribution 0.003995; added=False)
- celery/backends/database/__init__.py:celery.backends.database.DatabaseBackend.__init__ -> CALLS -> external_callable:schemas.get (attribution -0.003659; added=False)
- celery/backends/database/__init__.py:celery.backends.database.DatabaseBackend.__init__ -> CALLS -> external_callable:tablenames.get (attribution -0.003659; added=False)
- celery/backends/database/__init__.py:celery.backends.database.session_cleanup -> CALLS -> external_callable:session.close (attribution 0.003206; added=False)
- celery/backends/database/__init__.py:celery.backends.database.session_cleanup -> CALLS -> external_callable:session.rollback (attribution 0.003206; added=False)
- celery/states.py:celery.states -> CONTAINS -> celery/states.py:celery.states.PENDING (attribution -0.003066; added=False)
- celery/backends/database/__init__.py:celery.backends.database.DatabaseBackend._store_result -> CALLS -> celery/backends/database/__init__.py:celery.backends.database.DatabaseBackend._update_result (attribution -0.002881; added=False)

## Touched module coupling
- celery.backends.database: {"ca_after": 0, "ca_before": 0, "ce_after": 8, "ce_before": 8, "in_import_cycle": false}

## Diff hunks
- celery/backends/database/__init__.py: ["-            if 'args' in data:", "+            if data.get('args', None) is not None:", "-            if 'kwargs' in data:", "+            if data.get('kwargs', None) is not None:"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
