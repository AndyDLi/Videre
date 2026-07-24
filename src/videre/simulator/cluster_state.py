"""
Simulated world: fixed set of clusters, nodes,
and GPUs created at startup, including a dynamic set of jobs.
"""

from __future__ import annotations

from videre.models import GPU, Cluster, Job, JobState, Node, NodeHealthState


class ClusterState:
    def __init__(self, clusters: list[Cluster], nodes: list[Node], gpus: list[GPU]) -> None:
        self.clusters: dict[str, Cluster] = {cluster.id: cluster for cluster in clusters}
        self.nodes: dict[str, Node] = {node.id: node for node in nodes}
        self.gpus: dict[str, GPU] = {gpu.id: gpu for gpu in gpus}
        self.jobs: dict[str, Job] = {}

    def gpus_on_node(self, node_id: str) -> list[GPU]:
        return [gpu for gpu in self.gpus.values() if gpu.node_id == node_id]

    def running_jobs_on_node(self, node_id: str) -> list[Job]:
        return [
            job
            for job in self.jobs.values()
            if job.state is JobState.RUNNING and node_id in job.assigned_node_ids
        ]

    def node_ids(self) -> list[str]:
        return list(self.nodes)

    def schedulable_node_ids(self) -> list[str]:
        return [node.id for node in self.nodes.values() if node.health_state is NodeHealthState.READY]


def build_cluster_state(
    *,
    cluster_id: str = "cluster-a",
    node_count: int = 4,
    gpus_per_node: int = 8,
    cpu_cores: int = 64,
    memory_gb: int = 512,
) -> ClusterState:
    nodes: list[Node] = []
    gpus: list[GPU] = []
    for node_index in range(node_count):
        node_id = f"node-{node_index}"
        nodes.append(
            Node(
                id=node_id,
                cluster_id=cluster_id,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                gpu_count=gpus_per_node,
            )
        )
        
        for gpu_index in range(gpus_per_node):
            gpu_id = f"gpu-{node_index}-{gpu_index}"
            gpus.append(
                GPU(
                    id=gpu_id,
                    node_id=node_id,
                    memory_total_mb=81920
                )
            )
    
    cluster = Cluster(id=cluster_id, name="Cluster A", node_ids=[node.id for node in nodes])
    return ClusterState([cluster], nodes, gpus)
