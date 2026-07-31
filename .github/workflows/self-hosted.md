# Self-Hosted vs. GitHub-Hosted

## Motivation

GitHub-hosted runners are fresh, ephemeral cloud VMs spun up and managed entirely by GitHub for each job, while self-hosted runners are machines, VMs, or containers (WSL2) that an individual owns and can configure and connect to GitHub.

In Videre, a runner needs to talk to the k3s API Server, but the only exposed public entry point is 443, which solely routes traffic to Traefik. As a result, the cluster sits behind an outbound-only tunnel, meaning there is no inbound route for GitHub Actions to execute deployment commands.

Although we could route public internet traffic through Traefik to expose the internal k3s API server, this should never be done because it invites security vulnerabilities that must be handled with precise configurations. Therefore, we keep 443 open for public web traffic and 6443 strictly private.

## Workflow

To deploy securely across this private network boundary, our pipeline relies on three core mechanisms: a least-privilege deployment identity, an outbound-initiated runner execution loop, and automated RBAC verification.

### 1. Least-Privilege Identity & Credential Management

Deployments authenticate against the private k3s API using a dedicated Kubernetes ServiceAccount (`videre-deployer`). Every request requires an authenticated token to prove its identity and enforce access rules.

- RBAC scope permissions are minimal, strictly limited to updating Deployment container images and monitoring rollout status within the `videre` namespace.
- Rather than using the default cluster admin configuration, a local script extracts a dedicated ServiceAccount token and converts it into an isolated `kubeconfig` file stored on the WSL2 filesystem outside the Git repository.

### 2. Outbound-Initiated Deployment Loop

Instead of GitHub initiating an inbound connection to the cluster, the self-hosted WSL2 runner drives the deployment from inside the private network.

- The runner continuously initiates outbound requests over the internet to GitHub Actions to check for queued deployment jobs.
- Once a scheduled job's workflow instructions and deployment artifacts are downloaded locally, the runner uses the local `videre-deployer` kubeconfig to execute `kubectl` commands directly against the private k3s API server.

### 3. CI-Enforced RBAC Guardrails

To prevent configuration drift and enforce least-privilege access, security boundaries are continuously tested as code:

- On every push to `main`, an automated smoke-test workflow executes againts the cluster using the `videre-deployer` identity and explicitly attempts unauthorized actions, such as reading Secrets, spawning Pods, or accessing resources outside the `videre` namespace, and asserts that Kubernetes denies every request.
