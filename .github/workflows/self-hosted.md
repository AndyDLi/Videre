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

- **Backend & Simulator** (`test-python`): uses uv to install locked dependencies, lint code, enforce static type safety, and execute test suites.
- **Frontend** (`check-frontend`): uses Node.js 24 to run TypeScript type-checking, linting, and formatting verification.
- **Kubernetes manifests** (`check-manifests`): renders `k8s/kustomization.yaml` with `kubectl kustomize`. `kubectl apply -k k8s/` applies the stack, so a broken kustomization has to fail in review rather than at the terminal.

### 2. Packaging & Publishing (`main` only)

Once verification succeeds on `main`, the `build-and-push` job compiles and publishes images to the GitHub Container Registry (`ghcr.io`):

- Builds and pushes three distinct container images (simulator, backend, frontend), tagged using `<semantic-version>-<short-sha>`, read from `pyproject.toml` and `package.json` to ensure every deployment has a unique image reference and prevents Kubernetes nodes from silently serving stale cached layers.
- Writes those three tags back into the Deployment manifests and commits them to `main`. The deploy job below rolls images out with `kubectl set image`, which records the live tag nowhere in Git; without this commit the manifests fall behind by every deploy and `kubectl apply -k k8s/` becomes a rollback instead of a no-op. The commit uses `GITHUB_TOKEN`, whose pushes do not start a new workflow run, so the pipeline cannot loop.

### 3. Cluster Deployment & Security Auditing

- Before deploying, an automated security check executes against the cluster using the `videre-deployer` identity and explicitly attempts unauthorized actions, such as reading Secrets, deleting Deployments, spawning Pods, and accessing resources outside the `videre` namespace, asserting that Kubernetes denies every one.
- Updates the backend image and waits for readiness before updating the simulator, then the frontend.
- Monitors the clusters to ensure all new pods become healthy and ready before marking the pipeline as successful, and reports a post-deploy final state of the namespace for auditing.
