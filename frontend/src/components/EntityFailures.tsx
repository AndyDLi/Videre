import { useCallback } from 'react';

import { listFailures } from '../api/endpoints';
import type { EntityType } from '../api/types';
import { useApiResource } from '../hooks/useApiResource';
import { FailureRecordEntry } from './FailureRecordEntry';
import { LoadingOrError } from './LoadingOrError';

const FAILURE_PAGE_SIZE = 10;
const REFRESH_INTERVAL_MILLISECONDS = 15_000;

interface EntityFailuresProps {
    entityType: EntityType;
    entityId: string;
}

export function EntityFailures({ entityType, entityId }: EntityFailuresProps) {
    const fetcher = useCallback(
        (signal: AbortSignal) =>
            listFailures(
                { entity_type: entityType, entity_id: entityId, limit: FAILURE_PAGE_SIZE },
                signal,
            ),
        [entityType, entityId],
    );
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (data === null) {
        return <LoadingOrError isLoading={isLoading} error={error} subject="failures" />;
    }

    if (data.items.length === 0) {
        return <p className="text-sm text-text-muted">No failures recorded for this entity.</p>;
    }

    return (
        <ul className="divide-y divide-border-subtle">
            {data.items.map((record) => (
                <FailureRecordEntry key={record.id} record={record}>
                    <span className="text-sm font-medium">{record.root_cause_tag}</span>
                </FailureRecordEntry>
            ))}
        </ul>
    );
}
