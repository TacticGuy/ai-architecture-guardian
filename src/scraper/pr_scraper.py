"""Streaming, cursor-based merged PR metadata scraper."""
from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.github.client import GitHubClient
from src.github.queries import PR_COMMITS_QUERY, PULL_REQUESTS_QUERY, PULL_REQUESTS_HISTORY_QUERY
from src.dataset.future_refactor_labels import parse_timestamp
from src.scraper.checkpoint import CheckpointStore
from src.storage.jsonl import JSONLAppender, iter_jsonl


class PullRequestScraper:
    def __init__(self, client: GitHubClient, settings: dict[str, Any], output_path: str,
                 checkpoint: CheckpointStore | None, logger: logging.Logger | None = None) -> None:
        self.client, self.settings, self.checkpoint = client, settings, checkpoint
        self.writer = JSONLAppender(output_path)
        self.logger = logger or logging.getLogger("pr_dataset")

    def scrape_repository(self, repository: dict[str, Any], max_prs: int | None = None,
                          resume: bool = True) -> dict[str, Any]:
        owner, name = repository["owner"], repository["name"]
        repo_name = f"{owner}/{name}"
        if self.checkpoint is None:
            raise ValueError("Legacy scraping requires a checkpoint store")
        saved = self.checkpoint.get(repo_name) if resume else {"cursor": None, "completed": False}
        if saved.get("completed") and resume:
            self.logger.info("Skipping completed repository %s", repo_name)
            return {"repo": repo_name, "retrieved": 0, "written": 0, "completed": True}
        cursor = saved.get("cursor")
        retrieved = written = page_number = 0
        self.logger.info("Processing %s", repo_name)
        while max_prs is None or retrieved < max_prs:
            remaining = None if max_prs is None else max_prs - retrieved
            page_size = min(int(self.settings["pr_page_size"]), remaining or int(self.settings["pr_page_size"]))
            data = self.client.execute(PULL_REQUESTS_QUERY, {
                "owner": owner, "name": name, "cursor": cursor, "pageSize": page_size,
                "commitsFirst": min(int(self.settings["commit_page_size"]), int(self.settings["max_commits_per_pr"])),
            })
            repository_data = data.get("repository")
            if not repository_data:
                raise RuntimeError(f"Repository not found or inaccessible: {repo_name}")
            connection = repository_data.get("pullRequests")
            if not isinstance(connection, dict):
                raise RuntimeError(f"Malformed pullRequests response for {repo_name}")
            nodes = connection.get("nodes") or []
            if not isinstance(nodes, list):
                raise RuntimeError(f"Malformed pull request nodes for {repo_name}")
            page_number += 1
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                record = self._normalize(node, owner, name)
                self._complete_commit_metadata(record, owner, name, node.get("commits"))
                if self.writer.append(record):
                    written += 1
            retrieved += len(nodes)
            page_info = connection.get("pageInfo") or {}
            has_next = bool(page_info.get("hasNextPage"))
            next_cursor = page_info.get("endCursor")
            # Saving only after all nodes have been append-flushed makes interruption safe.
            reached_limit = max_prs is not None and retrieved >= max_prs
            completed = not has_next
            self.checkpoint.update(repo_name, next_cursor if has_next else None, completed)
            self.logger.info("%s page %d: retrieved %d PRs (%d new); checkpoint updated",
                             repo_name, page_number, len(nodes), written)
            if completed or reached_limit or not nodes:
                if completed:
                    self.logger.info("Completed %s", repo_name)
                return {"repo": repo_name, "retrieved": retrieved, "written": written, "completed": completed}
            cursor = next_cursor
        return {"repo": repo_name, "retrieved": retrieved, "written": written, "completed": False}

    def scrape_window(
        self, repository: dict[str, Any], window_start: str, window_end: str,
        coverage_path: str | Path, *, resume: bool = True, max_pages: int | None = None,
    ) -> dict[str, Any]:
        """Collect an inclusive merge-date interval with durable coverage state.

        Completion means pagination exhausted or creation-order traversal passed
        the interval end. A page cap or failure never marks coverage complete.
        """
        start, end = parse_timestamp(window_start), parse_timestamp(window_end)
        if start is None or end is None or start >= end:
            raise ValueError("Window bounds must be ordered, timezone-aware timestamps")
        if end > datetime.now(timezone.utc):
            raise ValueError("Collection window end must be in the past")
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be positive")
        owner, name = repository["owner"], repository["name"]
        repo_name = f"{owner}/{name}"
        destination = Path(coverage_path)
        manifest = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {
            "schema_version": 1, "repositories": [],
        }
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                or not isinstance(manifest.get("repositories"), list)
                or not all(isinstance(entry, dict) for entry in manifest["repositories"])):
            raise ValueError("Invalid collection coverage manifest")
        matches = [entry for entry in manifest["repositories"] if entry.get("repo") == repo_name]
        if len(matches) > 1:
            raise ValueError(f"Duplicate coverage entries for {repo_name}")
        existing = matches[0] if matches else None
        if existing and (parse_timestamp(existing.get("window_start")) != start
                         or parse_timestamp(existing.get("window_end")) != end):
            raise ValueError("Repository window differs from manifest; use a new coverage/raw file pair")
        if existing and existing.get("raw_file") != str(self.writer.path.resolve()):
            raise ValueError("Coverage manifest belongs to a different raw file")
        if existing and resume:
            state = existing
            if (state.get("source") != "github_repository_pull_requests"
                    or state.get("order") != "CREATED_AT_ASC"
                    or not isinstance(state.get("collected_pr_ids"), list)
                    or not all(isinstance(x, str) for x in state["collected_pr_ids"])
                    or type(state.get("pages_completed")) is not int
                    or type(state.get("scanned_prs")) is not int
                    or type(state.get("pagination_completed")) is not bool):
                raise ValueError("Invalid window checkpoint state; coverage cannot be resumed")
        else:
            state = {
                "repo": repo_name, "window_start": start.isoformat(), "window_end": end.isoformat(),
                "source": "github_repository_pull_requests", "order": "CREATED_AT_ASC",
                "raw_file": str(self.writer.path.resolve()), "pagination_completed": False,
                "cursor": None, "last_created_at": None, "collected_pr_ids": [],
                "pages_completed": 0, "scanned_prs": 0, "completion_reason": None,
            }
            manifest["repositories"] = [
                entry for entry in manifest["repositories"] if entry.get("repo") != repo_name
            ] + [state]
        collected = set(state["collected_pr_ids"])
        if not collected <= self.writer.existing_ids:
            raise ValueError("Raw records referenced by coverage are missing; do not resume this file pair")
        if state.get("pagination_completed") is True:
            self._check_window_records(repo_name, start, end, collected)
            return {"repo": repo_name, "retrieved": 0, "written": 0,
                    "window_prs": len(collected), "completed": True}
        self._save_coverage(destination, manifest)
        pages = scanned = written = 0
        while max_pages is None or pages < max_pages:
            cursor = state.get("cursor")
            data = self.client.execute(PULL_REQUESTS_HISTORY_QUERY, {
                "owner": owner, "name": name, "cursor": cursor,
                "pageSize": int(self.settings["pr_page_size"]),
            })
            connection = (data.get("repository") or {}).get("pullRequests")
            if not isinstance(connection, dict):
                raise RuntimeError(f"Missing pullRequests connection for {repo_name}")
            nodes, info = connection.get("nodes"), connection.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(info, dict):
                raise RuntimeError(f"Malformed history page for {repo_name}")
            has_next, next_cursor = info.get("hasNextPage"), info.get("endCursor")
            if type(has_next) is not bool or (has_next and (
                not nodes or not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor
            )):
                raise RuntimeError(f"Invalid history pagination for {repo_name}")
            previous = parse_timestamp(state.get("last_created_at"))
            prepared = []
            boundary_seen = False
            for node in nodes:
                if not isinstance(node, dict):
                    raise RuntimeError(f"Null/invalid PR in history page for {repo_name}")
                created = parse_timestamp(node.get("createdAt"))
                merged = parse_timestamp(node.get("mergedAt"))
                if created is None or merged is None or merged < created:
                    raise RuntimeError(f"Invalid PR timestamps in history page for {repo_name}")
                if node.get("merged") is not True or node.get("state") != "MERGED":
                    raise RuntimeError(f"Non-merged PR returned in history for {repo_name}")
                if previous is not None and created < previous:
                    raise RuntimeError(f"History is not in creation order for {repo_name}")
                previous = created
                boundary_seen |= created > end
                if start <= merged <= end:
                    prepared.append(self._normalize(node, owner, name))
            for record in prepared:
                if self.writer.append(record):
                    written += 1
                collected.add(record["pr_id"])
            pages += 1
            scanned += len(nodes)
            completed = boundary_seen or not has_next
            # Raw writes precede the manifest checkpoint. An interrupted page
            # is replayed and de-duplicated, without claiming uncollected IDs.
            state.update({
                "collected_pr_ids": sorted(collected),
                "cursor": None if completed else next_cursor,
                "last_created_at": previous.isoformat() if previous else None,
                "pages_completed": state["pages_completed"] + 1,
                "scanned_prs": state["scanned_prs"] + len(nodes),
                "pagination_completed": completed,
                "completion_reason": (
                    "created_after_window_end" if boundary_seen else "connection_exhausted"
                ) if completed else None,
            })
            if completed:
                try:
                    self._check_window_records(repo_name, start, end, collected)
                except ValueError:
                    state["pagination_completed"] = False
                    self._save_coverage(destination, manifest)
                    raise
            self._save_coverage(destination, manifest)
            self.logger.info(
                "%s history page %d: scanned=%d window_prs=%d completed=%s",
                repo_name, state["pages_completed"], len(nodes), len(collected), completed,
            )
            if completed:
                break
        return {"repo": repo_name, "retrieved": scanned, "written": written,
                "window_prs": len(collected), "completed": bool(state["pagination_completed"])}

    def _check_window_records(self, repo: str, start: datetime, end: datetime, collected: set[str]) -> None:
        actual = set()
        for record in iter_jsonl(self.writer.path):
            if record.get("repo") == repo:
                merged = parse_timestamp(record.get("merged_at"))
                if merged is None:
                    raise ValueError(f"Stored PR has invalid merged_at: {record.get('pr_id')}")
                if start <= merged <= end:
                    actual.add(record["pr_id"])
        if actual != collected:
            raise ValueError("Stored raw IDs differ from traversed window IDs; coverage cannot be certified")

    @staticmethod
    def _save_coverage(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _complete_commit_metadata(self, record: dict[str, Any], owner: str, name: str,
                                  initial: object) -> None:
        connection = initial if isinstance(initial, dict) else {}
        messages = record["commit_messages"]
        page_info = connection.get("pageInfo") or {}
        max_commits = int(self.settings["max_commits_per_pr"])
        while bool(page_info.get("hasNextPage")) and len(messages) < max_commits:
            request_size = min(int(self.settings["commit_page_size"]), max_commits - len(messages))
            data = self.client.execute(PR_COMMITS_QUERY, {
                "owner": owner, "name": name, "number": record["pr_number"],
                "cursor": page_info.get("endCursor"), "pageSize": request_size,
            })
            pr = ((data.get("repository") or {}).get("pullRequest") or {})
            connection = pr.get("commits") or {}
            messages.extend(self._messages(connection.get("nodes")))
            page_info = connection.get("pageInfo") or {}
        record["commit_messages"] = messages[:max_commits]
        record["commit_metadata_complete"] = not bool(page_info.get("hasNextPage"))

    @staticmethod
    def _messages(nodes: object) -> list[str]:
        result: list[str] = []
        if not isinstance(nodes, list):
            return result
        for node in nodes:
            message = ((node or {}).get("commit") or {}).get("message") if isinstance(node, dict) else None
            if isinstance(message, str):
                result.append(message)
        return result

    def _normalize(self, node: dict[str, Any], owner: str, name: str) -> dict[str, Any]:
        number = node.get("number")
        if not isinstance(number, int):
            raise RuntimeError(f"PR returned without numeric number in {owner}/{name}")
        author = node.get("author")
        merge_commit = node.get("mergeCommit")
        merge_commit_sha = (merge_commit.get("oid") if isinstance(merge_commit, dict)
                            and isinstance(merge_commit.get("oid"), str) else None)
        return {
            "pr_id": f"{owner}/{name}#{number}", "repo": f"{owner}/{name}", "owner": owner, "repo_name": name,
            "pr_number": number, "title": node.get("title") if isinstance(node.get("title"), str) else "",
            "body": node.get("body") if isinstance(node.get("body"), str) else "", "url": node.get("url") if isinstance(node.get("url"), str) else "",
            "state": node.get("state") if isinstance(node.get("state"), str) else "MERGED", "merged": bool(node.get("merged")),
            "created_at": node.get("createdAt"), "updated_at": node.get("updatedAt"), "merged_at": node.get("mergedAt"),
            "merge_commit_sha": merge_commit_sha,
            "base_ref_name": node.get("baseRefName"),
            "head_ref_sha": node.get("headRefOid"),
            "commit_count": (node.get("commits") or {}).get("totalCount"),
            "author": author.get("login") if isinstance(author, dict) and isinstance(author.get("login"), str) else None,
            "changed_files": node.get("changedFiles") if isinstance(node.get("changedFiles"), int) else None,
            "commit_messages": self._messages(((node.get("commits") or {}).get("nodes"))),
            "commit_metadata_complete": False, "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

