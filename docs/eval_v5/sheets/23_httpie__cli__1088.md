# httpie/cli#1088

Title: Fix printing redirected prepared request in verbose mode (#1088)
Predicted degrading: True
Risk score / threshold: 0.542678 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1088

## Top edges
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.pre_request (attribution 0.009692; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.start (attribution 0.009546; added=False)
- httpie/context.py:httpie.context.Environment -> CONTAINS -> httpie/context.py:httpie.context.Environment.log_error (attribution 0.009345; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.finish (attribution 0.009245; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.failed (attribution 0.009031; added=False)
- httpie/core.py:httpie.core.main -> CALLS -> httpie/core.py:httpie.core.program (attribution 0.008704; added=False)
- httpie/core.py:httpie.core.main -> CALLS -> httpie/core.py:httpie.core.print_debug_info (attribution 0.008226; added=False)
- httpie/__main__.py:httpie.__main__.main -> CALLS -> httpie/core.py:httpie.core.main (attribution 0.007366; added=False)
- httpie/core.py:httpie.core.program -> CONTAINS -> httpie/core.py:httpie.core.program.separate (attribution -0.006564; added=False)
- httpie/core.py:httpie.core.program -> CONTAINS -> httpie/core.py:httpie.core.program.request_body_read_callback (attribution -0.006505; added=False)
- httpie/core.py:httpie.core.program -> CALLS -> httpie/core.py:httpie.core.program.separate (attribution 0.006195; added=False)
- httpie/core.py:httpie.core.program -> CALLS -> httpie/core.py:httpie.core.get_output_options (attribution 0.005984; added=False)

## Touched module coupling
- httpie.core: {"ca_after": 1, "ca_before": 1, "ce_after": 9, "ce_before": 9, "in_import_cycle": false}

## Diff hunks
- httpie/core.py: ["+                if with_body:", "-                    if with_body:", "-                        do_write_body = not is_streamed_upload", "-                        force_separator = is_streamed_upload and env.stdout_isatty", "+                    do_write_body = not is_streamed_upload", "+                    force_separator = is_streamed_upload and env.stdout_isatty"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
