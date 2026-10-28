# celery/celery#9465

Title: Fix cassandra backend port settings not working (#9465)
Predicted degrading: False
Risk score / threshold: 0.415776 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/9465

## Top edges
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.current_task_children (attribution 0.048086; added=False)
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.meta_from_decoded (attribution 0.047175; added=False)
- celery/worker/request.py:celery.worker.request.Request -> CONTAINS -> celery/worker/request.py:celery.worker.request.Request.execute (attribution 0.035563; added=False)
- celery/platforms.py:celery.platforms.Pidfile -> CONTAINS -> celery/platforms.py:celery.platforms.Pidfile.acquire (attribution 0.015352; added=False)
- celery/platforms.py:celery.platforms.Pidfile -> CONTAINS -> celery/platforms.py:celery.platforms.Pidfile.release (attribution 0.012396; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.E_CASSANDRA_MISCONFIGURED (attribution -0.011355; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.E_CASSANDRA_NOT_CONFIGURED (attribution -0.011355; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.E_NO_CASSANDRA (attribution -0.011355; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.E_NO_SUCH_CASSANDRA_AUTH_PROVIDER (attribution -0.011355; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.Q_EXPIRES (attribution -0.011355; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.logger (attribution -0.01108; added=False)
- celery/backends/cassandra.py:celery.backends.cassandra -> CONTAINS -> celery/backends/cassandra.py:celery.backends.cassandra.Q_CREATE_RESULT_TABLE (attribution -0.010981; added=False)

## Touched module coupling
- celery.backends.cassandra: {"ca_after": 0, "ca_before": 0, "ce_after": 6, "ce_before": 6, "in_import_cycle": false}

## Diff hunks
- celery/backends/cassandra.py: ["-                 port=9042, bundle_path=None, **kwargs):", "+                 port=None, bundle_path=None, **kwargs):"]
- celery/backends/cassandra.py: ["-        self.port = port or conf.get('cassandra_port', None)", "+        self.port = port or conf.get('cassandra_port', None) or 9042"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
