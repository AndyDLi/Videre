import type { EntityType } from '../api/types';

const GPU_ID_PATTERN = /^gpu-(\d+)-\d+$/;

export function drillDownPath(entityType: EntityType, entityId: string): string | null {
    if (entityType === 'node') {
        return `/nodes/${entityId}`;
    }
    if (entityType === 'job') {
        return `/jobs/${entityId}`;
    }

    const match = GPU_ID_PATTERN.exec(entityId);
    return match === null ? null : `/nodes/node-${match[1]}/gpus/${entityId}`;
}
