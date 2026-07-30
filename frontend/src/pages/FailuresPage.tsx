import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { listFailures } from '../api/endpoints';
import type { EntityType } from '../api/types';
import { Card } from '../components/Card';
import { FailureRecordEntry } from '../components/FailureRecordEntry';
import { LoadingOrError } from '../components/LoadingOrError';
import { drillDownPath } from '../domain/entityLinks';
import { useApiResource } from '../hooks/useApiResource';

const PAGE_SIZE = 25;
const REFRESH_INTERVAL_MILLISECONDS = 20_000;
const HOUR_IN_MILLISECONDS = 3_600_000;

type EntityTypeFilter = EntityType | 'all';
type StatusFilter = 'all' | 'unresolved' | 'resolved';

const ENTITY_TYPE_OPTIONS: { value: EntityTypeFilter; label: string }[] = [
    { value: 'all', label: 'All Entities' },
    { value: 'node', label: 'Nodes' },
    { value: 'gpu', label: 'GPUs' },
    { value: 'job', label: 'Jobs' },
];

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All Statuses' },
    { value: 'unresolved', label: 'Unresolved' },
    { value: 'resolved', label: 'Resolved' },
];

const TIME_RANGE_OPTIONS: { hours: number; label: string }[] = [
    { hours: 0, label: 'All Time' },
    { hours: 1, label: 'Last Hour' },
    { hours: 24, label: 'Last 24 Hours' },
    { hours: 72, label: 'Last 3 Days' },
];

const SELECT_CLASSES =
    'rounded border border-border-subtle bg-surface px-2 py-1 text-sm text-text-primary';
const PAGE_BUTTON_CLASSES =
    'rounded border border-border-subtle px-3 py-1 text-sm font-medium hover:bg-surface-muted disabled:opacity-40';

export function FailuresPage() {
    const [entityType, setEntityType] = useState<EntityTypeFilter>('all');
    const [status, setStatus] = useState<StatusFilter>('all');
    const [sinceHours, setSinceHours] = useState(0);
    const [offset, setOffset] = useState(0);

    const fetcher = useCallback(
        (signal: AbortSignal) =>
            listFailures(
                {
                    limit: PAGE_SIZE,
                    offset,
                    entity_type: entityType === 'all' ? undefined : entityType,
                    resolved: status === 'all' ? undefined : status === 'resolved',
                    since:
                        sinceHours === 0
                            ? undefined
                            : new Date(
                                  Date.now() - sinceHours * HOUR_IN_MILLISECONDS,
                              ).toISOString(),
                },
                signal,
            ),
        [entityType, status, sinceHours, offset],
    );
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    return (
        <section className="space-y-4">
            <h1 className="text-xl font-semibold">Failed Jobs &amp; Unavailable Nodes</h1>

            <div className="flex flex-wrap gap-3">
                <label className="text-sm">
                    <span className="mr-2 text-text-muted">Entity Type</span>
                    <select
                        className={SELECT_CLASSES}
                        value={entityType}
                        onChange={(event) => {
                            setEntityType(event.target.value as EntityTypeFilter);
                            setOffset(0);
                        }}
                    >
                        {ENTITY_TYPE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>

                <label className="text-sm">
                    <span className="mr-2 text-text-muted">Status</span>
                    <select
                        className={SELECT_CLASSES}
                        value={status}
                        onChange={(event) => {
                            setStatus(event.target.value as StatusFilter);
                            setOffset(0);
                        }}
                    >
                        {STATUS_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>

                <label className="text-sm">
                    <span className="mr-2 text-text-muted">Time Range</span>
                    <select
                        className={SELECT_CLASSES}
                        value={sinceHours}
                        onChange={(event) => {
                            setSinceHours(Number(event.target.value));
                            setOffset(0);
                        }}
                    >
                        {TIME_RANGE_OPTIONS.map((option) => (
                            <option key={option.hours} value={option.hours}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>
            </div>

            <Card>
                {data === null ? (
                    <LoadingOrError isLoading={isLoading} error={error} subject="failures" />
                ) : data.items.length === 0 ? (
                    <p className="text-sm text-text-muted">
                        No failure records match these filters.
                    </p>
                ) : (
                    <ul className="divide-y divide-border-subtle">
                        {data.items.map((record) => {
                            const path = drillDownPath(record.entity_type, record.entity_id);
                            return (
                                <FailureRecordEntry key={record.id} record={record}>
                                    {path === null ? (
                                        <span className="font-medium">{record.entity_id}</span>
                                    ) : (
                                        <Link to={path} className="font-medium hover:underline">
                                            {record.entity_id}
                                        </Link>
                                    )}
                                    <span className="text-xs uppercase text-text-muted">
                                        {record.entity_type}
                                    </span>
                                    <span className="text-sm">{record.root_cause_tag}</span>
                                </FailureRecordEntry>
                            );
                        })}
                    </ul>
                )}
            </Card>

            {data !== null && data.items.length > 0 && (
                <div className="flex flex-wrap items-center gap-3">
                    <span className="text-sm text-text-muted">
                        Showing {data.offset + 1}–{data.offset + data.items.length} of {data.total}
                    </span>
                    <div className="ml-auto flex gap-2">
                        <button
                            type="button"
                            disabled={data.offset === 0}
                            onClick={() => {
                                setOffset(Math.max(data.offset - PAGE_SIZE, 0));
                            }}
                            className={PAGE_BUTTON_CLASSES}
                        >
                            Previous
                        </button>
                        <button
                            type="button"
                            disabled={data.offset + data.items.length >= data.total}
                            onClick={() => {
                                setOffset(data.offset + PAGE_SIZE);
                            }}
                            className={PAGE_BUTTON_CLASSES}
                        >
                            Next
                        </button>
                    </div>
                </div>
            )}
        </section>
    );
}
