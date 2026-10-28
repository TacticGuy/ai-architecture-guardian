# httpie/cli#1232

Title: Add initial benchmarking infrastructure (#1232)
Predicted degrading: False
Risk score / threshold: 0.414296 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1232

## Top edges
- extras/profiling/run.py:run.run -> CALLS -> extras/profiling/run.py:run.call (attribution 0.006817; added=True)
- extras/profiling/run.py:run -> CONTAINS -> extras/profiling/run.py:run.call (attribution 0.00597; added=False)
- extras/profiling/run.py:run.main -> CALLS -> external_callable:argparse.ArgumentParser (attribution 0.005339; added=True)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.start (attribution 0.005237; added=False)
- extras/profiling/run.py:run.main -> CALLS -> external_callable:argparse.FileType (attribution 0.005201; added=True)
- extras/profiling/run.py:run.main -> CALLS -> external_callable:parser.add_argument (attribution 0.005055; added=True)
- extras/profiling/run.py:run -> CONTAINS -> extras/profiling/run.py:run.run (attribution 0.004994; added=False)
- extras/profiling/run.py:run -> CONTAINS -> extras/profiling/run.py:run.main (attribution 0.004494; added=False)
- extras/profiling/benchmarks.py:benchmarks.start_server -> CALLS -> external_callable:threading.Thread (attribution 0.004469; added=True)
- extras/profiling/benchmarks.py:benchmarks -> CONTAINS -> extras/profiling/benchmarks.py:benchmarks.DownloadRunner (attribution -0.003828; added=False)
- extras/profiling/benchmarks.py:benchmarks -> CONTAINS -> extras/profiling/benchmarks.py:benchmarks.CommandRunner (attribution -0.003809; added=False)
- extras/profiling/benchmarks.py:benchmarks -> CONTAINS -> extras/profiling/benchmarks.py:benchmarks.start_server (attribution 0.003776; added=False)

## Touched module coupling
- benchmarks: {"ca_after": 0, "ca_before": null, "ce_after": 1, "ce_before": null, "in_import_cycle": false}
- run: {"ca_after": 0, "ca_before": null, "ce_after": 0, "ce_before": null, "in_import_cycle": false}

## Diff hunks
- extras/profiling/run.py: ["+\"\"\"", "+Run the HTTPie benchmark suite with multiple environments.", "+", "+This script is configured in a way that, it will create", "+two (or more) isolated environments and compare the *last", "+commit* of this repository with it's master.", "+", "+> If you didn't commit yet, it won't be showing results.", "+", "+You can also pass --fresh, which would test the *last", "+commit* of this repository with a fresh copy of HTTPie", "+itself. This way even if you don't have an up-to-date"]
- extras/profiling/benchmarks.py: ["+\"\"\"", "+This file is the declaration of benchmarks for HTTPie. It", "+is also used to run them with the current environment.", "+", "+Each instance of BaseRunner class will be an individual", "+benchmark. And if run without any arguments, this file", "+will execute every benchmark instance and report the", "+timings.", "+", "+The benchmarks are run through 'pyperf', which allows to", "+do get very precise results. For micro-benchmarks like startup,", "+please run `pyperf system tune` to get even more acurrate results."]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
