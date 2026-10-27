# SonarQube for the v5 baselines

1. Start Docker Desktop. SonarQube needs about 4 GB of RAM. On Windows with WSL2, if
   Elasticsearch complains about `vm.max_map_count`, run this in PowerShell:
   `wsl -d docker-desktop sysctl -w vm.max_map_count=262144`
2. `docker compose -f docker/sonarqube/docker-compose.yml up -d`, then wait until
   http://localhost:9000 shows the login page (1 to 2 minutes).
3. Log in as `admin` / `admin` and change the password.
4. Go to My Account, then Security, and generate a **user token**. Put it in `.env` (git-ignored):
   `SONAR_TOKEN=squ_...`. Never commit it.
5. `docker pull sonarsource/sonar-scanner-cli`
6. Time 10 test PRs: `python scripts/tool_metrics_v5.py --tools sonar --sonar-time 10`
7. If the whole test split fits the time you have, run
   `python scripts/tool_metrics_v5.py --tools sonar`. Otherwise run a seeded subset:
   `--sonar-limit N --sonar-seed 0`. The exact count and seed go into
   `data/tool_metrics_v5.meta.json`.

The scanner runs inside its own container, so it reaches the server at
`http://host.docker.internal:9000` (`--scanner-host-url`, or `SONAR_SCANNER_HOST_URL`). On
Linux, add `--add-host=host.docker.internal:host-gateway`, or use the host's IP.

Each PR is scanned twice: the touched files before the merge and after it. Each scan is a
throwaway project (`v5_<owner>_<repo>_<number>_before` / `_after`) that is deleted once its
measures are read. Measures: `code_smells`, `cognitive_complexity`, `sqale_index` (technical
debt in minutes) and `duplicated_lines_density`.

Stop the server: `docker compose -f docker/sonarqube/docker-compose.yml down`. Add `-v` to
also delete its data.
