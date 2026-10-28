# celery/celery#6823

Title: The Consul backend must correctly associate requests and responses (#6823)
Predicted degrading: False
Risk score / threshold: 0.413409 / 0.441173
GitHub PR: https://github.com/celery/celery/pull/6823

## Top edges
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.set -> CALLS -> external_callable:client.kv.put (attribution -0.02905; added=True)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.set -> CALLS -> external_callable:client.session.create (attribution -0.02905; added=True)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend._init_from_params -> CALLS -> external_callable:params.get (attribution -0.022198; added=True)
- celery/exceptions.py:celery.exceptions.Retry.__init__ -> IMPORTS -> external_module:kombu.utils.encoding (attribution -0.013561; added=False)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.__init__ -> CALLS -> external_callable:kombu.utils.url.parse_url (attribution -0.013503; added=False)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.client -> CALLS -> external_callable:consul.Consul (attribution -0.007238; added=True)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.delete -> CALLS -> external_callable:self.client.kv.delete (attribution -0.006076; added=False)
- celery/utils/nodenames.py:celery.utils.nodenames._fmt_process_index -> IMPORTS -> celery/utils/log.py:celery.utils.log (attribution 0.005409; added=False)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.get -> CALLS -> external_callable:self.client.kv.get (attribution -0.005265; added=False)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.set -> ACCESSES_GLOBAL -> celery/backends/consul.py:celery.backends.consul.logger (attribution -0.004778; added=False)
- celery/backends/consul.py:celery.backends.consul -> CONTAINS -> celery/backends/consul.py:celery.backends.consul.CONSUL_MISSING (attribution -0.004159; added=False)
- celery/backends/consul.py:celery.backends.consul.ConsulBackend.__init__ -> ACCESSES_GLOBAL -> celery/backends/consul.py:celery.backends.consul.CONSUL_MISSING (attribution 0.003994; added=False)

## Touched module coupling
- celery.backends.consul: {"ca_after": 0, "ca_before": 0, "ce_after": 3, "ce_before": 3, "in_import_cycle": false}

## Diff hunks
- celery/backends/consul.py: ["-        session_id = self.client.session.create(name=session_name,", "-                                                behavior='delete',", "-                                                ttl=self.expires)", "+        client = self.client()", "+        session_id = client.session.create(name=session_name,", "+                                           behavior='delete',", "+                                           ttl=self.expires)", "-        return self.client.kv.put(key=key,", "-                                  value=value,", "-                                  acquire=session_id)", "+        return client.kv.put(key=key, value=value, acquire=session_id)", "-        return self.client.kv.delete(key)"]
- celery/backends/consul.py: ["-", "+        #", "+        # By default, for correctness, we use a client connection per", "+        # operation. If set, self.one_client will be used for all operations.", "+        # This provides for the original behaviour to be selected, and is", "+        # also convenient for mocking in the unit tests.", "+        #", "+        self.one_client = None", "-        self.client = consul.Consul(host=hostname, port=port,", "-                                    consistency=self.consistency)", "+        self.hostname = hostname", "+        self.port = port"]
- celery/backends/consul.py: ["-            _, data = self.client.kv.get(key)", "+            _, data = self.client().kv.get(key)"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
