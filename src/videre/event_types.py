"""
Taxonomy of simulated event types: the values the envelope's `event_type` carries.
`EventType` covers the failure modes the correlation engine schedules and the generators produce;
`LifecycleEventType` covers routine telemetry, lifecycle and recovery.
"""

from enum import StrEnum


class EventType(StrEnum):
    # Node-level
    NODE_KUBELET_DOWN = "node.kubelet_down"
    NODE_UNTOLERATED_TAINT = "node.untolerated_taint"
    NODE_IMAGE_PULL_FAILURE = "node.image_pull_failure"
    NODE_CNI_FAILURE = "node.cni_failure"   # network connectivity issues.
    NODE_DISK_PRESSURE = "node.disk_pressure"
    
    # GPU-level
    GPU_THERMAL_THROTTLING = "gpu.thermal_throttling"
    GPU_ECC_UNCORRECTABLE = "gpu.ecc_uncorrectable"
    GPU_XID_ERROR = "gpu.xid_error"
    GPU_NVLINK_DEGRADED = "gpu.nvlink_degraded"
    GPU_DRIVER_CRASH = "gpu.driver_crash"
    
    # Job-level
    JOB_OOM_KILL = "job.oom_kill"
    JOB_NCCL_TIMEOUT = "job.nccl_timeout"   # collective operations takes too long to complete
    JOB_STRAGGLER = "job.straggler"         # slower-running job causes delays in synchronized operations
    JOB_CHECKPOINT_CORRUPT = "job.checkpoint_corrupt"
    JOB_PREEMPTED = "job.preempted"
    
    # Capacity-level
    CAPACITY_FRAGMENTATION = "capacity.fragmentation"
    NODE_DRAINED = "node.drained"
    CAPACITY_RESERVED_IDLE = "capacity.reserved_idle"
    NODE_HEALTH_CHECK_REMOVED = "node.health_check_removed"


class LifecycleEventType(StrEnum):
    NODE_STATE = "node.state"
    GPU_METRIC = "gpu.metric"

    JOB_PENDING = "job.pending"
    JOB_RUNNING = "job.running"
    JOB_COMPLETED = "job.completed"

    NODE_RECOVERED = "node.recovered"
    GPU_RECOVERED = "gpu.recovered"
