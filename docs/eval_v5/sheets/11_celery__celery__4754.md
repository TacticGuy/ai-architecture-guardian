# celery/celery#4754

Title: Fix gevent import (#4754)
Predicted degrading: False
Risk score / threshold: 0.343512 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/4754

## Top edges
- celery/concurrency/gevent.py:celery.concurrency.gevent.Timer.__init__ -> IMPORTS -> external_module:gevent (attribution -0.019857; added=True)
- celery/concurrency/gevent.py:celery.concurrency.gevent.TaskPool.__init__ -> IMPORTS -> external_module:gevent.pool (attribution -0.017949; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent.Timer.__init__ -> CONTAINS -> celery/concurrency/gevent.py:celery.concurrency.gevent.Timer.__init__._Greenlet (attribution 0.016437; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent.Timer.__init__._Greenlet -> INHERITS -> external_callable:gevent.Greenlet (attribution -0.009744; added=True)
- celery/concurrency/gevent.py:celery.concurrency.gevent.TaskPool.__init__ -> IMPORTS -> external_module:gevent (attribution -0.009008; added=False)
- celery/__init__.py:celery._patch_gevent -> IMPORTS -> external_module:gevent (attribution 0.007757; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent.Timer._enter -> CALLS -> external_callable:self._Greenlet.spawn_later (attribution -0.006357; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent -> CONTAINS -> celery/concurrency/gevent.py:celery.concurrency.gevent.apply_timeout (attribution 0.006288; added=False)
- celery/concurrency/eventlet.py:celery.concurrency.eventlet.Timer -> INHERITS -> external_callable:kombu.asynchronous.timer.Timer (attribution 0.003997; added=False)
- celery/worker/components.py:celery.worker.components.Timer.create -> CALLS -> external_callable:kombu.asynchronous.timer.Timer (attribution -0.003847; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent.Timer -> INHERITS -> external_callable:kombu.asynchronous.timer.Timer (attribution 0.003729; added=False)
- celery/concurrency/gevent.py:celery.concurrency.gevent.TaskPool.on_apply -> CALLS -> external_callable:self._quick_put (attribution -0.003261; added=False)

## Touched module coupling
- celery.concurrency.gevent: {"ca_after": 0, "ca_before": 0, "ce_after": 2, "ce_before": 2, "in_import_cycle": false}

## Diff hunks
- celery/concurrency/gevent.py: ["-        from gevent.greenlet import Greenlet, GreenletExit", "+        from gevent import Greenlet, GreenletExit"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
