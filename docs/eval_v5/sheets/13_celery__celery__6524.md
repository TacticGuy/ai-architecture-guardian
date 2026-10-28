# celery/celery#6524

Title: DummyClient of cache+memory:// backend now shares state between threads (#6524)
Predicted degrading: False
Risk score / threshold: 0.39311 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/6524

## Top edges
- celery/backends/base.py:celery.backends.base.Backend -> CONTAINS -> celery/backends/base.py:celery.backends.base.Backend.prepare_expires (attribution 0.039153; added=False)
- celery/backends/cache.py:celery.backends.cache -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.REQUIRES_BACKEND (attribution -0.029019; added=False)
- celery/backends/cache.py:celery.backends.cache -> CONTAINS -> celery/backends/cache.py:celery.backends.cache._imp (attribution -0.029019; added=False)
- celery/backends/cache.py:celery.backends.cache -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.UNKNOWN_BACKEND (attribution -0.028589; added=False)
- celery/backends/cache.py:celery.backends.cache -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.backends (attribution -0.028589; added=False)
- celery/backends/cache.py:celery.backends.cache.get_best_memcache -> CALLS -> celery/backends/cache.py:celery.backends.cache.import_best_memcache (attribution -0.019646; added=False)
- celery/backends/cache.py:celery.backends.cache -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.get_best_memcache (attribution 0.014527; added=False)
- celery/backends/cache.py:celery.backends.cache.DummyClient -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.DummyClient.get_multi (attribution 0.011795; added=False)
- celery/backends/cache.py:celery.backends.cache.DummyClient -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.DummyClient.incr (attribution 0.011642; added=False)
- celery/backends/cache.py:celery.backends.cache.DummyClient -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.DummyClient.touch (attribution 0.010645; added=False)
- celery/backends/cache.py:celery.backends.cache.DummyClient -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.DummyClient.delete (attribution 0.009165; added=False)
- celery/backends/cache.py:celery.backends.cache.DummyClient -> CONTAINS -> celery/backends/cache.py:celery.backends.cache.DummyClient.get (attribution 0.009165; added=False)

## Touched module coupling
- celery.backends.cache: {"ca_after": 1, "ca_before": 1, "ce_after": 3, "ce_before": 3, "in_import_cycle": false}

## Diff hunks
- celery/backends/cache.py: ["-        self.cache = LRUCache(limit=5000)", "+        self.cache = _DUMMY_CLIENT_CACHE"]
- celery/backends/cache.py: ["+# Global shared in-memory cache for in-memory cache client", "+# This is to share cache between threads", "+_DUMMY_CLIENT_CACHE = LRUCache(limit=5000)", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
