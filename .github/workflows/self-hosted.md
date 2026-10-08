# Self-Hosted Runner

A runner is a machine that carries out GitHub Actions jobs, such as testing or deploying an app.

## Why Videre Uses One

Videre's Kubernetes cluster (k3s) runs inside WSL2 on a personal computer. Its public link serves the website; the cluster's management interface stays private.

GitHub's runners cannot reach that private interface. A local runner checks GitHub for deployment jobs and runs them inside WSL2. No inbound ports need to be opened.

## What the Pipeline Does

1. **Check the Code:** On pull requests and pushes to `main`, GitHub's runners test the backend and simulator, check the frontend, and validate the Kubernetes deployment files.
2. **Build the Apps:** After checks pass on `main`, GitHub builds and publishes the three apps as container images. Each image is labeled with the project version and code commit ID. The workflow records those image versions on `main`.
3. **Deploy Locally:** The local runner updates the backend, simulator, then frontend. It checks that each app is ready and uses the expected image.

Recorded image versions show what should be deployed. A successful deploy job and its summary confirm what was deployed. See [the workflow](ci.yml) for exact steps.

### Deployment and Retries

- Releases run one at a time. Active runs finish; only the latest waiting run is kept. Future release workflows must share the `videre-release-${{ github.ref }}` concurrency group. See [GitHub's queue rules](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency).
- Before recording image versions, the workflow checks that `main` still matches its source commit. Before each app update, it checks that `main` still matches its image-tag commit. A merge or administrator change can still leave apps on different versions.
- Retry only the failed deploy job while its image-tag commit remains current on `main`. Retrying the whole workflow after tags were recorded fails the source check. Newer commits need their own release workflow.

## Safety Rules

- **Pull Request Jobs Never Run on the Personal Computer.** Only pushes to `main` can deploy.
- The runner uses a restricted account (`videre-deployer`) to update the three apps and check their status in the `videre` namespace. Its credentials stay outside the repository.
- Before deploying, the workflow checks that the account cannot read secrets, delete apps, create pods, or access other namespaces.
- Database and configuration changes require manual steps. Follow [database and release operations](../../docs/setup.md#database-and-release-operations).
