"""Streaming, cursor-based merged PR metadata scraper."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.github.client import GitHubClient
from src.github.queries import PR_COMMITS_QUERY, PULL_REQUESTS_QUERY
from src.scraper.checkpoint import CheckpointStore
from src.storage.jsonl import JSONLAppender


class PullRequestScraper:
    def __init__(self, client: GitHubClient, settings: dict[str, Any], output_path: str,
                 checkpoint: CheckpointStore, logger: logging.Logger | None = None) -> None:
        self.client, self.settings, self.checkpoint = client, settings, checkpoint
        self.writer = JSONLAppender(output_path)
        self.logger = logger or logging.getLogger("pr_dataset")

    def scrape_repository(self, repository: dict[str, Any], max_prs: int | None = None,
                          resume: bool = True) -> dict[str, Any]:
        owner, name = repository["owner"], repository["name"]
        repo_name = f"{owner}/{name}"
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
        return {
            "pr_id": f"{owner}/{name}#{number}", "repo": f"{owner}/{name}", "owner": owner, "repo_name": name,
            "pr_number": number, "title": node.get("title") if isinstance(node.get("title"), str) else "",
            "body": node.get("body") if isinstance(node.get("body"), str) else "", "url": node.get("url") if isinstance(node.get("url"), str) else "",
            "state": node.get("state") if isinstance(node.get("state"), str) else "MERGED", "merged": bool(node.get("merged")),
            "created_at": node.get("createdAt"), "updated_at": node.get("updatedAt"), "merged_at": node.get("mergedAt"),
            "author": author.get("login") if isinstance(author, dict) and isinstance(author.get("login"), str) else None,
            "changed_files": node.get("changedFiles") if isinstance(node.get("changedFiles"), int) else None,
            "commit_messages": self._messages(((node.get("commits") or {}).get("nodes"))),
            "commit_metadata_complete": False, "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

