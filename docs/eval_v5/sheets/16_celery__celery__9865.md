# celery/celery#9865

Title: Fix `AsyncResult.forget()` with couchdb backend method raises `TypeError: a bytes-like object is required, not 'str'` (#9865)
Predicted degrading: False
Risk score / threshold: 0.440275 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/9865

## Top edges
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend.__init__ -> CALLS -> external_callable:ucontainer.strip (attribution -0.021093; added=False)
- celery/exceptions.py:celery.exceptions.Retry.__init__ -> IMPORTS -> external_module:kombu.utils.encoding (attribution -0.017539; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb -> CONTAINS -> celery/backends/couchdb.py:celery.backends.couchdb.ERR_LIB_MISSING (attribution -0.009661; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend.__init__ -> ACCESSES_GLOBAL -> celery/backends/couchdb.py:celery.backends.couchdb.ERR_LIB_MISSING (attribution 0.006736; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend -> CONTAINS -> celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend._get_connection (attribution -0.005046; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend.set -> CALLS -> external_callable:self.connection.save (attribution -0.004814; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend -> CONTAINS -> celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend.__init__ (attribution -0.00465; added=False)
- celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend -> CONTAINS -> celery/backends/couchdb.py:celery.backends.couchdb.CouchBackend.delete (attribution -0.00353; added=False)
- celery/backends/arangodb.py:celery.backends.arangodb.ArangoDbBackend.__init__ -> CALLS -> external_callable:kombu.utils.url._parse_url (attribution -0.002758; added=False)
- celery/backends/dynamodb.py:celery.backends.dynamodb.DynamoDBBackend.__init__ -> CALLS -> external_callable:kombu.utils.url._parse_url (attribution -0.002707; added=False)
- celery/utils/serialization.py:celery.utils.serialization.b64encode -> CALLS -> external_callable:kombu.utils.encoding.bytes_to_str (attribution 0.002683; added=False)
- celery/backends/couchbase.py:celery.backends.couchbase.CouchbaseBackend.__init__ -> CALLS -> external_callable:kombu.utils.url._parse_url (attribution -0.002631; added=False)

## Touched module coupling
- celery.backends.couchdb: {"ca_after": 0, "ca_before": 0, "ce_after": 3, "ce_before": 3, "in_import_cycle": false}

## Diff hunks
- celery/backends/couchdb.py: ["+        key = bytes_to_str(key)"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
