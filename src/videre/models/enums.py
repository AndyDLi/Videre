"""
Enumerations for the core entity models.
StrEnum ensures all models serialize to plain string in JSON.
"""

from enum import StrEnum


class NodeHealthState(StrEnum):
    READY = "READY"             # node is healthy, reachable, and ready to accept workloads
    NOT_READY = "NOT_READY"     # node is unhealthy, unreachable, or not ready to accept workloads
    DRAINING = "DRAINING"       # node is being gracefully removed from service
    CORDONED = "CORDONED"       # node keeps its current workloads but does not accept new workloads


class GpuHealthState(StrEnum):
    HEALTHY = "HEALTHY"         # operating normally within expected limits
    THROTTLING = "THROTTLING"   # performance is reduced due to thermal or power limits
    DEGRADED = "DEGRADED"       # usable but reports errors or reduced reliability/performance
    FAILED = "FAILED"           # unusable and cannot be used for workloads


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class SchedulerEventType(StrEnum):
    PLACEMENT = "PLACEMENT"             # a workload is assigned to a node/GPU
    PREEMPTION = "PREEMPTION"           # a running workload is interrupted for a higher-priority workload
    QUEUEING_DELAY = "QUEUEING_DELAY"   # a workload waits because no eligible capacity is currently available
