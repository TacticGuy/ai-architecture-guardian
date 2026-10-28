# sphinx-doc/sphinx#8824

Title: Merge pull request #8824 from jfbu/merge_3.x_into_master
Predicted degrading: True
Risk score / threshold: 0.496822 / 0.441173
GitHub PR: https://github.com/sphinx-doc/sphinx/pull/8824

## Top edges
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check -> CALLS -> sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri (attribution 0.013464; added=False)
- sphinx/application.py:sphinx.application.Sphinx -> CONTAINS -> sphinx/application.py:sphinx.application.Sphinx.add_autodocumenter (attribution 0.00462; added=False)
- sphinx/util/__init__.py:sphinx.util.save_traceback -> IMPORTS -> external_module:docutils (attribution 0.004198; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:uri.split (attribution 0.004196; added=False)
- sphinx/application.py:sphinx.application.Sphinx -> CONTAINS -> sphinx/application.py:sphinx.application.Sphinx.add_config_value (attribution 0.004193; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:self.wqueue.put (attribution 0.00409; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:pattern.match (attribution 0.003997; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.check_anchor (attribution 0.003947; added=False)
- sphinx/ext/autodoc/directive.py:sphinx.ext.autodoc.directive.process_documenter_options -> ACCESSES_GLOBAL -> sphinx/ext/autodoc/directive.py:sphinx.ext.autodoc.directive.AUTODOC_DEFAULT_OPTIONS (attribution 0.00378; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:req_url.encode (attribution 0.003717; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:req_url.rstrip (attribution 0.003717; added=False)
- sphinx/builders/linkcheck.py:sphinx.builders.linkcheck.CheckExternalLinksBuilder.check_thread.check_uri -> CALLS -> external_callable:response.raise_for_status (attribution 0.003717; added=False)

## Touched module coupling
- sphinx.builders.linkcheck: {"ca_after": 0, "ca_before": 0, "ce_after": 12, "ce_before": 12, "in_import_cycle": false}
- sphinx.ext.autodoc.directive: {"ca_after": 3, "ca_before": 3, "ce_after": 7, "ce_before": 7, "in_import_cycle": true}

## Diff hunks
- sphinx/builders/linkcheck.py: ["-                        for rex in self.to_ignore:", "-                            if rex.match(uri):", "-                                return 'ignored', '', 0", "-                        else:", "-                            self._broken[uri] = ''", "-                            return 'broken', '', 0", "+                        self._broken[uri] = ''", "+                        return 'broken', '', 0", "-            for rex in self.to_ignore:", "-                if rex.match(uri):", "-                    return 'ignored', '', 0"]
- sphinx/ext/autodoc/directive.py: ["-                options[name] = config.autodoc_default_options[name]", "+                if name in options and isinstance(config.autodoc_default_options[name], str):", "+                    # take value from options if present or extend it", "+                    # with autodoc_default_options if necessary", "+                    if name in AUTODOC_EXTENDABLE_OPTIONS:", "+                        if options[name] is not None and options[name].startswith('+'):", "+                            options[name] = ','.join([config.autodoc_default_options[name],", "+                                                      options[name][1:]])", "+                else:", "+                    options[name] = config.autodoc_default_options[name]", "+", "+            elif options.get(name) is not None:"]
- sphinx/builders/linkcheck.py: ["+    def is_ignored_uri(self, uri: str) -> bool:", "+        return any(pat.match(uri) for pat in self.to_ignore)", "+"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
