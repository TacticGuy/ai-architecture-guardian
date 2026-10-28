# httpie/cli#1113

Title: --download: Use `time.monotonic()` and rework code to prevent `ZeroDivisionError` specific handling (#1113)
Predicted degrading: True
Risk score / threshold: 0.510466 / 0.441173
GitHub PR: https://github.com/httpie/cli/pull/1113

## Top edges
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.start (attribution 0.009379; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader._get_output_file_from_response (attribution 0.007104; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.pre_request (attribution 0.006482; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.finish (attribution 0.00603; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.failed (attribution 0.005893; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.chunk_downloaded (attribution 0.005493; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.interrupted (attribution 0.005306; added=False)
- httpie/core.py:httpie.core.program -> CALLS -> httpie/downloads.py:httpie.downloads.Downloader.start (attribution 0.004953; added=False)
- httpie/downloads.py:httpie.downloads.Downloader -> CONTAINS -> httpie/downloads.py:httpie.downloads.Downloader.__init__ (attribution 0.004722; added=False)
- httpie/core.py:httpie.core.main -> CALLS -> httpie/core.py:httpie.core.program (attribution 0.003904; added=False)
- httpie/downloads.py:httpie.downloads.ProgressReporterThread.report_speed -> CALLS -> external_callable:PROGRESS.format (attribution 0.003526; added=False)
- httpie/downloads.py:httpie.downloads.ProgressReporterThread.report_speed -> CALLS -> external_callable:PROGRESS_NO_CONTENT_LENGTH.format (attribution 0.003526; added=False)

## Touched module coupling
- httpie.downloads: {"ca_after": 1, "ca_before": 1, "ce_after": 3, "ce_before": 3, "in_import_cycle": false}

## Diff hunks
- httpie/downloads.py: ["-        self.time_started = time()", "+        self.time_started = monotonic()"]
- httpie/downloads.py: ["+        speed = actually_downloaded / time_taken if time_taken else actually_downloaded", "-        try:", "-            speed = actually_downloaded / time_taken", "-        except ZeroDivisionError:", "-            # Either time is 0 (not all systems provide `time.time`", "-            # with a better precision than 1 second), and/or nothing", "-            # has been downloaded.", "-            speed = actually_downloaded", "-"]
- httpie/downloads.py: ["-", "-        now = time()", "-", "+        now = monotonic()", "-            try:", "-                speed = ((downloaded - self._prev_bytes)", "-                         / (now - self._prev_time))", "-            except ZeroDivisionError:", "-                speed = 0", "+            speed = ((downloaded - self._prev_bytes)", "+                     / (now - self._prev_time))"]

## Human reference (fill after checking GitHub diff)
Explanation: [write by hand]
Minimal fix: [write by hand]
Relevant principle IDs: [choose by hand]
