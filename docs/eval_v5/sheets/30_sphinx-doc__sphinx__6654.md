# sphinx-doc/sphinx#6654

Title: Merge pull request #6654 from jdufresne/str-bytes
Predicted degrading: False
Risk score / threshold: 0.399639 / 0.441173
GitHub PR: https://github.com/sphinx-doc/sphinx/pull/6654

## Top edges
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CONTAINS -> utils/jssplitter_generator.py:utils.jssplitter_generator.fold (attribution 0.115644; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> external_callable:subprocess.call (attribution 0.068425; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> external_callable:match.match (attribution 0.066034; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> external_callable:ranges.append (attribution 0.066034; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> external_callable:singles.append (attribution 0.066034; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> external_callable:f.write (attribution 0.056893; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CALLS -> utils/jssplitter_generator.py:utils.jssplitter_generator.fold (attribution -0.045405; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> IMPORTS -> external_module:json (attribution 0.039728; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CONTAINS -> utils/jssplitter_generator.py:utils.jssplitter_generator.begin (attribution -0.030879; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CONTAINS -> utils/jssplitter_generator.py:utils.jssplitter_generator.js_src (attribution -0.030879; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CONTAINS -> utils/jssplitter_generator.py:utils.jssplitter_generator.js_test_src (attribution -0.030879; added=False)
- utils/jssplitter_generator.py:utils.jssplitter_generator -> CONTAINS -> utils/jssplitter_generator.py:utils.jssplitter_generator.match (attribution -0.030879; added=False)

## Touched module coupling
- utils.jssplitter_generator: {"ca_after": 0, "ca_before": 0, "ce_after": 1, "ce_before": 1, "in_import_cycle": false}

## Diff hunks
- utils/jssplitter_generator.py: ["-    f.write(js_test_src.encode())", "+    f.write(js_test_src)"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
