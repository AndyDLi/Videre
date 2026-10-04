"""Opt-in checks against an explicitly selected admin Kubernetes context.

The suite never installs policy or RBAC. Mutations are server dry runs except
three uniquely named, bounded materialization Jobs, which expire through TTL.
"""

from __future__ import annotations

import copy
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream
from kubernetes.stream.ws_client import create_websocket
from websocket import WebSocketBadStatusException

from videre.models import Job, ResourceRequest
from videre.simulator.materializer import build_materialized_job

NAMESPACE = "videre"
DEPLOYER = "system:serviceaccount:videre:videre-deployer"
SIMULATOR = "system:serviceaccount:videre:videre-simulator"
CONTROLLER = "system:serviceaccount:kube-system:job-controller"
pytestmark = pytest.mark.skipif(
    os.environ.get("VIDERE_TEST_KUBERNETES_SECURITY") != "1",
    reason="set VIDERE_TEST_KUBERNETES_SECURITY=1 and explicit admin KUBECONFIG for live checks",
)


@dataclass
class Cluster:
    admin: client.ApiClient
    deployer: client.ApiClient
    simulator: client.ApiClient
    controller: client.ApiClient
    kubeconfig: str

    def kubectl(self, actor: str, *args: str) -> subprocess.CompletedProcess[str]:
        # Force the traditional POST transport, separately from Python's GET WebSocket.
        env = dict(os.environ, KUBECONFIG=self.kubeconfig, KUBECTL_REMOTE_COMMAND_WEBSOCKETS="false")
        return subprocess.run(
            ["kubectl", "--request-timeout=15s", f"--as={actor}", "-n", NAMESPACE, *args],
            capture_output=True, text=True, timeout=25, check=False, env=env,
        )


@pytest.fixture(scope="module")
def cluster() -> Iterator[Cluster]:
    kubeconfig = os.environ.get("KUBECONFIG")
    if not kubeconfig:
        pytest.fail("live security checks require an explicit admin KUBECONFIG")
    clients = []
    for actor in (None, DEPLOYER, SIMULATOR, CONTROLLER):
        api = config.new_client_from_config(config_file=kubeconfig)
        if actor:
            api.set_default_header("Impersonate-User", actor)
        clients.append(api)
    try:
        yield Cluster(*clients, kubeconfig)
    finally:
        for api in clients:
            api.close()


def assert_denied(operation: Callable[[], object], policy: str) -> None:
    with pytest.raises(ApiException) as rejected:
        operation()
    assert rejected.value.status == 403, str(rejected.value)
    assert policy in (rejected.value.body or ""), str(rejected.value)


def workload(cluster: Cluster) -> dict[str, Any]:
    model = build_materialized_job(
        Job(id=f"job-security-{uuid4().hex[:12]}", cluster_id="security-check",
            resources=ResourceRequest(cpu_cores=1, memory_gb=1, gpu_count=0)),
        "security-check", ttl_seconds_after_finished=15,
    )
    body: dict[str, Any] = cluster.admin.sanitize_for_serialization(model)
    body.update(apiVersion="batch/v1", kind="Job")
    return body


def set_field(body: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = body
    for key in path[:-1]:
        if isinstance(target, dict):
            target = target.setdefault(key, {})
        else:
            target = target[key]
    target[path[-1]] = copy.deepcopy(value)
    if path == ("containers", 0, "securityContext", "privileged") and value:
        body["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
    if path == ("containers", 0, "resources", "claims"):
        body["resourceClaims"] = [{"name": "device", "resourceClaimName": "unrelated"}]
    if path == ("containers", 0, "volumeDevices"):
        body["volumes"] = [{"name": "device", "persistentVolumeClaim": {"claimName": "unrelated"}}]


def authorized(cluster: Cluster, actor: str, verb: str, resource: str, *, name: str = "",
               namespace: str = NAMESPACE, group: str = "", subresource: str = "") -> bool:
    review = client.AuthorizationV1Api(cluster.admin).create_subject_access_review(
        client.V1SubjectAccessReview(spec=client.V1SubjectAccessReviewSpec(
            user=actor, groups=["system:authenticated", "system:serviceaccounts", "system:serviceaccounts:videre"],
            resource_attributes=client.V1ResourceAttributes(
                namespace=namespace, verb=verb, group=group, resource=resource,
                name=name or None, subresource=subresource or None,
            ),
        )),
    )
    return bool(review.status.allowed)


def test_deployer_cannot_patch_unrelated_deployment(cluster: Cluster) -> None:
    assert not authorized(cluster, DEPLOYER, "patch", "deployments", name="alloy", group="apps")


def test_authorization_boundaries(cluster: Cluster) -> None:
    for name in ("backend", "frontend", "simulator"):
        assert authorized(cluster, DEPLOYER, "patch", "deployments", name=name, group="apps")
    for verb in ("get", "list", "watch"):
        assert authorized(cluster, DEPLOYER, verb, "deployments", group="apps")
    assert authorized(cluster, DEPLOYER, "list", "pods")
    for verb in ("update", "create", "delete"):
        assert not authorized(cluster, DEPLOYER, verb, "deployments", name="backend", group="apps")
    for verb in ("get", "watch", "create", "patch", "delete"):
        assert not authorized(cluster, DEPLOYER, verb, "pods")
    assert authorized(cluster, SIMULATOR, "create", "jobs", group="batch")
    for verb in ("get", "list", "watch", "update", "patch", "delete"):
        assert not authorized(cluster, SIMULATOR, verb, "jobs", group="batch")
    for verb in ("get", "list"):
        assert authorized(cluster, SIMULATOR, verb, "pods")
    for verb in ("watch", "create", "update", "patch", "delete"):
        assert not authorized(cluster, SIMULATOR, verb, "pods")
    for verb in ("get", "create"):
        assert authorized(cluster, SIMULATOR, verb, "pods", subresource="exec")
    for actor in (DEPLOYER, SIMULATOR):
        for resource, group in (("secrets", ""), ("roles", "rbac.authorization.k8s.io"),
                                ("rolebindings", "rbac.authorization.k8s.io"),
                                ("validatingadmissionpolicies", "admissionregistration.k8s.io"),
                                ("validatingadmissionpolicybindings", "admissionregistration.k8s.io")):
            for verb in ("create", "patch", "update", "delete"):
                assert not authorized(cluster, actor, verb, resource, group=group)
        assert not authorized(cluster, actor, "get", "secrets")
        assert not authorized(cluster, actor, "impersonate", "serviceaccounts", name="default")
        assert not authorized(cluster, actor, "create", "serviceaccounts", name="videre-deployer", subresource="token")
        assert not authorized(cluster, actor, "create", "jobs", namespace="default", group="batch")
        assert not authorized(cluster, actor, "patch", "deployments", namespace="default", group="apps")


@pytest.mark.parametrize("name", ["backend", "frontend", "simulator"])
def test_named_image_patch_allowed(cluster: Cluster, name: str) -> None:
    apps = client.AppsV1Api(cluster.admin)
    deployment = apps.read_namespaced_deployment(name, NAMESPACE)
    container = deployment.spec.template.spec.containers[0]
    client.AppsV1Api(cluster.deployer).patch_namespaced_deployment(
        name, NAMESPACE,
        {"spec": {"template": {"spec": {"containers": [{"name": container.name, "image": "busybox:1.37"}]}}}},
        dry_run="All", _content_type="application/strategic-merge-patch+json",
    )


# Each object stays structurally valid: success must depend on admission, not schema validation.
POD_ATTACKS = [
    (("serviceAccountName",), "videre-simulator"),
    (("automountServiceAccountToken",), True),
    (("hostNetwork",), True), (("hostPID",), True), (("hostIPC",), True),
    (("runtimeClassName",), "crun"),
    (("imagePullSecrets",), [{"name": "videre-deployer-token"}]),
    (("volumes",), [{"name": "secret", "secret": {"secretName": "videre-deployer-token"}}]),
    (("volumes",), [{"name": "token", "projected": {"sources": [
        {"serviceAccountToken": {"path": "token", "expirationSeconds": 3600}}]}}]),
    (("volumes",), [{"name": "host", "hostPath": {"path": "/"}}]),
    (("volumes",), [{"name": "csi", "csi": {"driver": "secrets-store.csi.k8s.io"}}]),
    (("volumes",), [{"name": "pvc", "persistentVolumeClaim": {"claimName": "credentials"}}]),
    (("containers", 0, "env"), [{"name": "TOKEN", "valueFrom": {
        "secretKeyRef": {"name": "videre-deployer-token", "key": "token"}}}]),
    (("containers", 0, "envFrom"), [{"secretRef": {"name": "videre-deployer-token"}}]),
    (("containers", 0, "securityContext", "privileged"), True),
    (("containers", 0, "securityContext", "allowPrivilegeEscalation"), True),
    (("containers", 0, "securityContext", "capabilities", "add"), ["SYS_ADMIN"]),
    (("containers", 0, "securityContext", "seccompProfile", "type"), "Unconfined"),
    (("containers", 0, "ports"), [{"containerPort": 8080, "hostPort": 8080}]),
    (("containers", 0, "resources", "limits", "memory"), "512Mi"),
    (("containers", 0, "resources", "limits", "example.com/device"), "1"),
    (("securityContext", "sysctls"), [{"name": "kernel.shm_rmid_forced", "value": "1"}]),
    (("resources", "limits"), {"cpu": "1", "memory": "512Mi"}),
    (("terminationGracePeriodSeconds",), 121),
    (("containers", 0, "lifecycle"), {"preStop": {"exec": {"command": ["sleep", "300"]}}}),
    (("resourceClaims",), [{"name": "device", "resourceClaimName": "unrelated"}]),
    (("containers", 0, "resources", "claims"), [{"name": "device"}]),
    (("containers", 0, "volumeDevices"), [{"name": "device", "devicePath": "/dev/disk"}]),
    (("initContainers",), [{"name": "init", "image": "busybox:1.37", "command": ["true"]}]),
]


@pytest.mark.parametrize("path,value", POD_ATTACKS)
def test_simulator_job_privilege_changes_denied(cluster: Cluster, path: tuple[str | int, ...], value: Any) -> None:
    body = workload(cluster)
    set_field(body["spec"]["template"]["spec"], path, value)
    assert_denied(lambda: client.BatchV1Api(cluster.simulator).create_namespaced_job(
        NAMESPACE, body, dry_run="All"), "videre-materialized-jobs")


@pytest.mark.parametrize("change", ["unreserved-name", "manual-selector", "extra-container", "ttl", "deadline",
                                     "job-finalizer", "template-finalizer"])
def test_simulator_job_scope_and_lifecycle_denied(cluster: Cluster, change: str) -> None:
    body = workload(cluster)
    if change == "unreserved-name":
        body["metadata"]["name"] = "security-unreserved"
    elif change == "manual-selector":
        body["spec"]["manualSelector"] = True
        body["spec"]["selector"] = {"matchLabels": {"app.kubernetes.io/part-of": "videre"}}
    elif change == "job-finalizer":
        body["metadata"]["finalizers"] = ["security.example/hold"]
    elif change == "template-finalizer":
        body["spec"]["template"]["metadata"]["finalizers"] = ["security.example/hold"]
    elif change == "extra-container":
        extra = copy.deepcopy(body["spec"]["template"]["spec"]["containers"][0])
        extra["name"] = "extra"
        body["spec"]["template"]["spec"]["containers"].append(extra)
    else:
        field = "ttlSecondsAfterFinished" if change == "ttl" else "activeDeadlineSeconds"
        body["spec"][field] = 121
    assert_denied(lambda: client.BatchV1Api(cluster.simulator).create_namespaced_job(
        NAMESPACE, body, dry_run="All"), "videre-materialized-jobs")


def test_safe_materialization_job_allowed(cluster: Cluster) -> None:
    client.BatchV1Api(cluster.simulator).create_namespaced_job(NAMESPACE, workload(cluster), dry_run="All")


@pytest.mark.parametrize("path,value", POD_ATTACKS)
def test_deployer_privilege_changes_denied(cluster: Cluster, path: tuple[str | int, ...], value: Any) -> None:
    deployment = client.AppsV1Api(cluster.admin).read_namespaced_deployment("backend", NAMESPACE)
    body = cluster.admin.sanitize_for_serialization(deployment)
    set_field(body["spec"]["template"]["spec"], path, value)
    assert_denied(lambda: client.AppsV1Api(cluster.deployer).patch_namespaced_deployment(
        "backend", NAMESPACE, {"spec": body["spec"]}, dry_run="All",
        _content_type="application/merge-patch+json"), "videre-deployer-boundary")


def controller_pod(cluster: Cluster) -> dict[str, Any]:
    job = workload(cluster)
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {
        "generateName": job["metadata"]["name"] + "-", "labels": job["metadata"]["labels"],
        "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": job["metadata"]["name"],
                             "uid": str(uuid4()), "controller": True, "blockOwnerDeletion": True}],
    }, "spec": job["spec"]["template"]["spec"]}


@pytest.mark.parametrize("spoof", ["explicit-name", "generate-name", "copied-labels", "forged-owner"])
def test_reserved_pod_spoof_denied(cluster: Cluster, spoof: str) -> None:
    body = controller_pod(cluster)
    if spoof == "explicit-name":
        body["metadata"]["name"] = body["metadata"].pop("generateName") + "spoof"
    if spoof != "forged-owner":
        body["metadata"].pop("ownerReferences")
    if spoof == "copied-labels":
        body["metadata"]["labels"]["app.kubernetes.io/name"] = "alloy"
    # An admin identity has Pod create RBAC but still cannot forge controller provenance.
    assert_denied(lambda: client.CoreV1Api(cluster.admin).create_namespaced_pod(
        NAMESPACE, body, dry_run="All"), "videre-materialized-pods")


@pytest.mark.parametrize("path,value", POD_ATTACKS)
def test_unsafe_controller_pod_denied(cluster: Cluster, path: tuple[str | int, ...], value: Any) -> None:
    body = controller_pod(cluster)
    set_field(body["spec"], path, value)
    assert_denied(lambda: client.CoreV1Api(cluster.controller).create_namespaced_pod(
        NAMESPACE, body, dry_run="All"), "videre-materialized-pods")


def test_safe_controller_pod_allowed(cluster: Cluster) -> None:
    client.CoreV1Api(cluster.controller).create_namespaced_pod(NAMESPACE, controller_pod(cluster), dry_run="All")


def simulator_stream_client(cluster: Cluster) -> client.ApiClient:
    # The Python WebSocket transport drops impersonation headers. Authenticate
    # with a short-lived simulator token and no administrator client certificate.
    token = client.CoreV1Api(cluster.admin).create_namespaced_service_account_token(
        "videre-simulator", NAMESPACE,
        client.AuthenticationV1TokenRequest(spec=client.V1TokenRequestSpec(audiences=[], expiration_seconds=600)),
    ).status.token
    admin_config = cluster.admin.configuration
    configuration = client.Configuration(
        host=admin_config.host, api_key={"authorization": f"Bearer {token}"},
    )
    configuration.ssl_ca_cert = admin_config.ssl_ca_cert
    configuration.verify_ssl = admin_config.verify_ssl
    configuration.tls_server_name = admin_config.tls_server_name
    api = client.ApiClient(configuration)
    identity = client.AuthenticationV1Api(api).create_self_subject_review(client.V1SelfSubjectReview())
    assert identity.status.user_info.username == SIMULATOR
    return api


def running_pod(cluster: Cluster, app: str) -> client.V1Pod:
    pods = client.CoreV1Api(cluster.admin).list_namespaced_pod(
        NAMESPACE, label_selector=f"app.kubernetes.io/name={app}")
    ready = [pod for pod in pods.items if pod.status.phase == "Running"]
    assert ready, f"expected running {app} Pod for exec restriction checks"
    return ready[0]


@pytest.mark.parametrize("app", ["backend", "frontend", "alloy", "prometheus"])
def test_exec_into_application_pods_denied(cluster: Cluster, app: str) -> None:
    pod = running_pod(cluster, app)
    with simulator_stream_client(cluster) as api:
        # Use the same GET handshake as stream; this client version masks denied
        # handshakes by trying to decode an absent ApiException body.
        query = urlencode({"command": "true", "container": pod.spec.containers[0].name,
                           "stderr": "true", "stdout": "true"})
        url = f"{api.configuration.host}/api/v1/namespaces/{NAMESPACE}/pods/{pod.metadata.name}/exec?{query}"
        with pytest.raises(WebSocketBadStatusException) as rejected:
            create_websocket(api.configuration, url.replace("https://", "wss://", 1),
                             {"authorization": api.configuration.get_api_key_with_prefix("authorization")})
        assert rejected.value.status_code == 403
        assert "videre-simulator-exec" in str(rejected.value), str(rejected.value)
    post = cluster.kubectl(SIMULATOR, "exec", pod.metadata.name, "-c", pod.spec.containers[0].name, "--", "true")
    assert post.returncode != 0
    assert "videre-simulator-exec" in post.stderr, post.stderr


def wait_for(operation: Callable[[], Any], predicate: Callable[[Any], bool], seconds: int = 130) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = operation()
        if predicate(value):
            return value
        time.sleep(0.5)
    pytest.fail("bounded materialization lifecycle timed out")


@pytest.mark.parametrize("outcome,exit_code,reason", [("complete", 0, "Completed"),
                                                      ("error", 1, "Error"), ("oom", 137, "OOMKilled")])
def test_materialization_outcomes_and_ttl(cluster: Cluster, outcome: str, exit_code: int, reason: str) -> None:
    body = workload(cluster)
    name = body["metadata"]["name"]
    core = client.CoreV1Api(cluster.admin)
    batch = client.BatchV1Api(cluster.admin)
    client.BatchV1Api(cluster.simulator).create_namespaced_job(NAMESPACE, body)
    pods = wait_for(lambda: core.list_namespaced_pod(NAMESPACE, label_selector=f"batch.kubernetes.io/job-name={name}"),
                    lambda result: bool(result.items))
    pod_name = pods.items[0].metadata.name
    pod = wait_for(lambda: core.read_namespaced_pod(pod_name, NAMESPACE),
                   lambda pod: bool(pod.status.container_statuses and pod.status.container_statuses[0].state.running))
    assert pod.spec.automount_service_account_token is False
    assert pod.spec.service_account_name == "default"
    assert not pod.spec.volumes
    assert all(not container.volume_mounts for container in pod.spec.containers)
    assert pod.metadata.owner_references[0].name == name
    # Subresource checks use only this test's Pod, with dry runs and admin RBAC.
    assert_denied(lambda: core.patch_namespaced_pod_ephemeralcontainers(
        pod_name, NAMESPACE, {"spec": {"ephemeralContainers": [{
            "name": "debug", "image": "busybox:1.37", "command": ["true"],
            "securityContext": {"privileged": True},
        }]}}, dry_run="All", _content_type="application/merge-patch+json"), "videre-materialized-pods")
    assert_denied(lambda: core.patch_namespaced_pod_resize(
        pod_name, NAMESPACE, {"spec": {"containers": [{"name": "workload", "resources": {
            "requests": {"cpu": "5m", "memory": "16Mi"}, "limits": {"cpu": "50m", "memory": "64Mi"},
        }}]}}, dry_run="All", _content_type="application/strategic-merge-patch+json"), "videre-materialized-pods")
    assert_denied(lambda: batch.patch_namespaced_job(
        name, NAMESPACE, {"spec": {"ttlSecondsAfterFinished": 121}}, dry_run="All"), "videre-materialized-jobs")
    # Both allowed exec transports use only the test's own generated workload.
    post = cluster.kubectl(SIMULATOR, "exec", pod_name, "--", "true")
    assert post.returncode == 0, post.stderr
    with simulator_stream_client(cluster) as api:
        stream(client.CoreV1Api(api).connect_get_namespaced_pod_exec, pod_name, NAMESPACE,
               command=["sh", "-c", f"echo {outcome} > /tmp/outcome"], stderr=True, stdout=True,
               stdin=False, tty=False, _request_timeout=15)
    pod = wait_for(lambda: core.read_namespaced_pod(pod_name, NAMESPACE),
                   lambda pod: bool(
                       pod.status.container_statuses and pod.status.container_statuses[0].state.terminated))
    terminated = pod.status.container_statuses[0].state.terminated
    assert terminated.exit_code == exit_code
    assert terminated.reason == reason

    def expired() -> bool:
        try:
            batch.read_namespaced_job(name, NAMESPACE)
        except ApiException as error:
            if error.status == 404:
                return True
            raise
        return False

    wait_for(expired, bool, seconds=75)
    wait_for(lambda: core.list_namespaced_pod(NAMESPACE, label_selector=f"batch.kubernetes.io/job-name={name}"),
             lambda result: not result.items, seconds=30)


def test_alloy_required_mounts_preserved(cluster: Cluster) -> None:
    pod = running_pod(cluster, "alloy")
    assert pod.spec.service_account_name == "alloy"
    assert pod.spec.security_context.run_as_user == 0
    host_paths = {volume.host_path.path for volume in pod.spec.volumes or [] if volume.host_path}
    assert {"/var/log/pods", "/var/lib/alloy"} <= host_paths
    assert any(condition.type == "Ready" and condition.status == "True" for condition in pod.status.conditions or [])
    deployment = client.AppsV1Api(cluster.admin).read_namespaced_daemon_set("alloy", NAMESPACE)
    body = cluster.admin.sanitize_for_serialization(deployment)
    client.AppsV1Api(cluster.admin).patch_namespaced_daemon_set(
        "alloy", NAMESPACE, {"spec": body["spec"]}, dry_run="All", _content_type="application/merge-patch+json")

@pytest.mark.parametrize("spoof", ["explicit-name", "generate-name", "copied-alloy-labels"])
def test_reserved_job_identity_cannot_be_forged(cluster: Cluster, spoof: str) -> None:
    body = workload(cluster)
    if spoof == "generate-name":
        body["metadata"]["generateName"] = body["metadata"].pop("name") + "-"
    elif spoof == "copied-alloy-labels":
        body["metadata"]["labels"]["app.kubernetes.io/name"] = "alloy"
        body["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"] = "alloy"
    assert_denied(lambda: client.BatchV1Api(cluster.admin).create_namespaced_job(
        NAMESPACE, body, dry_run="All"), "videre-materialized-jobs")


@pytest.mark.parametrize("ownership", ["missing", "unreserved-job", "noncontrolling", "wrong-kind"])
def test_controller_pod_requires_reserved_job_owner(cluster: Cluster, ownership: str) -> None:
    body = controller_pod(cluster)
    if ownership == "missing":
        body["metadata"].pop("ownerReferences")
    else:
        owner = body["metadata"]["ownerReferences"][0]
        if ownership == "unreserved-job":
            owner["name"] = "unrelated-job"
        elif ownership == "noncontrolling":
            owner["controller"] = False
        else:
            owner.update(apiVersion="apps/v1", kind="Deployment")
    assert_denied(lambda: client.CoreV1Api(cluster.controller).create_namespaced_pod(
        NAMESPACE, body, dry_run="All"), "videre-materialized-pods")


def test_unreserved_pod_with_copied_labels_is_ordinary(cluster: Cluster) -> None:
    body = controller_pod(cluster)
    body["metadata"]["generateName"] = "security-ordinary-"
    body["metadata"].pop("ownerReferences")
    body["metadata"]["labels"]["app.kubernetes.io/name"] = "alloy"
    client.CoreV1Api(cluster.admin).create_namespaced_pod(NAMESPACE, body, dry_run="All")
