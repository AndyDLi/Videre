# Self-Hosted vs. GitHub-Hosted

## Motivation

GitHub-hosted runners are fresh, ephemeral cloud VMs spun up and managed entirely by GitHub for each job, while self-hosted runners are machines, VMs, or containers (WSL2) that an individual owns and can configure and connect to GitHub.

In Videre, a runner needs to talk to the k3s API Server, but the only exposed public entry point is 443, which solely routes traffic to Traefik. As a result, the cluster sits behind an outbound-only tunnel, meaning there is no inbound route for GitHub Actions to execute deployment commands.

Although we could route public internet traffic through Traefik to expose the internal k3s API server, this should never be done because it invites security vulnerabilities that must be handled with precise configurations. Therefore, we keep 443 open for public web traffic and 6443 off the public internet entirely.

## Architecture

To deploy securely across this private network boundary, our pipeline relies on a least-privilege deployment identity and an outbound-initiated runner execution loop.

### 1. Least-Privilege Identity & Credential Management

Deployments authenticate against the private k3s API using a dedicated Kubernetes ServiceAccount (`videre-deployer`). Every request requires an authenticated token to prove its identity and enforce access rules.

- RBAC scope permissions are minimal, strictly limited to updating Deployment container images and monitoring rollout status within the `videre` namespace.
- Rather than using the default cluster admin configuration, a local script extracts a dedicated ServiceAccount token and converts it into an isolated `kubeconfig` file stored on the WSL2 filesystem outside the Git repository.

### 2. Outbound-Initiated Deployment Loop

Instead of GitHub initiating an inbound connection to the cluster, the self-hosted WSL2 runner drives the deployment from inside the private network.

- The runner continuously initiates outbound requests over the internet to GitHub Actions to check for queued deployment jobs.
- Once a scheduled job's workflow instructions and deployment artifacts are downloaded locally, the runner uses the local `videre-deployer` kubeconfig to execute `kubectl` commands directly against the private k3s API server.

## Workflow

Tests, image builds, and registry pushes run on GitHub's hosted runners (`ubuntu-latest`). Only the deploy job uses the self-hosted runner (`videre-deploy`). The pipeline is divided into three sequential phases:

### 1. Verification (PRs & `main`)

Three verification jobs run in parallel on every push to `main` and on all pull requests:

- **Backend & Simulator** (`test-python`): installs locked dependencies, runs lint/type checks, and migrates disposable PostgreSQL 17.10 before testing as `videre_app`. Required database tests cannot skip for missing configuration. CI uses no production database credentials.
- **Frontend** (`check-frontend`): uses Node.js 24 to run TypeScript type-checking, linting, and formatting verification.
- **Kubernetes manifests** (`check-manifests`): renders `k8s/kustomization.yaml` with `kubectl kustomize`. `kubectl apply -k k8s/` applies the stack, so a broken kustomization has to fail in review rather than at the terminal.

### 2. Packaging & Publishing (`main` only)

Once verification succeeds on `main`, the `build-and-push` job compiles and publishes images to the GitHub Container Registry (`ghcr.io`):

- Builds and pushes three distinct container images (simulator, backend, frontend), tagged using `<semantic-version>-<short-sha>`, read from `pyproject.toml` and `package.json` to ensure every deployment has a unique image reference and prevents Kubernetes nodes from silently serving stale cached layers.
- Records the three desired image tags on `main` and passes that commit SHA to deployment. Recording requires `main` to match the source revision; a normal push rejects a concurrent advance. These tags do not confirm rollout success. The bot push uses `GITHUB_TOKEN` and does not trigger another workflow.

### 3. Cluster Deployment & Security Auditing

- Before deploying, an automated security check executes against the cluster using the `videre-deployer` identity and explicitly attempts unauthorized actions, such as reading Secrets, deleting Deployments, spawning Pods, and accessing resources outside the `videre` namespace, asserting that Kubernetes denies every one.
- Before each image update, checks that remote `main` still matches this workflow's image-tag commit. Deploys backend, simulator, then frontend, checking readiness and the exact image after each rollout.
- After all three rollouts pass, writes a summary with source SHA, image-tag commit SHA, images and run link. The successful deploy job and summary confirm the release. Failed runs report Pods without a success summary.

## Release Serialization and Recovery

The `videre-release-${{ github.ref }}` concurrency group serializes the entire release. PRs have separate groups. Active runs finish (`cancel-in-progress: false`); only the latest pending run is kept. Future production release workflows must share this group.

The lock does not cover human merges or administrator changes. A merge during rollout can stop later updates and leave mixed images. Inspect the cluster before recovery; revision checks and cluster writes are separate operations.

Retry a failed deploy job only while its image-tag commit remains current on `main`. Rerunning the whole workflow after that commit fails the source check. Release newer source revisions through their own workflow.

Schema and configuration changes remain manual. Before merging, document the source SHA, schema revisions, files, compatibility checks and recovery target. Readiness alone does not verify schema or table access. See [the operator runbook](../../docs/setup.md#database-and-release-operations).
