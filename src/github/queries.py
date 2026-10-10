"""GraphQL documents used by the metadata-only scraper."""

PULL_REQUESTS_QUERY = """
query PullRequests($owner: String!, $name: String!, $cursor: String, $pageSize: Int!, $commitsFirst: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, states: MERGED,
      orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url state merged mergedAt createdAt updatedAt changedFiles
        mergeCommit { oid }
        author { login }
        commits(first: $commitsFirst) {
          pageInfo { hasNextPage endCursor }
          nodes { commit { message } }
        }
      }
    }
  }
  rateLimit { limit cost remaining resetAt }
}
"""

PR_COMMITS_QUERY = """
query PullRequestCommits($owner: String!, $name: String!, $number: Int!, $cursor: String!, $pageSize: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      commits(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { commit { message } }
      }
    }
  }
  rateLimit { limit cost remaining resetAt }
}
"""

VIEWER_QUERY = """
query ViewerAndRepository($owner: String!, $name: String!) {
  viewer { login }
  repository(owner: $owner, name: $name) { nameWithOwner }
  rateLimit { limit cost remaining resetAt }
}
"""

