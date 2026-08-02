import type { ReactNode } from 'react';

import type { FailureRecord } from '../api/types';
import { formatTimestamp } from '../domain/format';

interface FailureRecordEntryProps {
    record: FailureRecord;
    children: ReactNode;
}

export function FailureRecordEntry({ record, children }: FailureRecordEntryProps) {
    return (
        <li className="py-3.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {children}
                <span
                    className={`eyebrow ml-auto ${record.resolved_at === null ? 'text-state-bad' : 'text-text-muted'}`}
                >
                    {record.resolved_at === null ? 'Unresolved' : 'Resolved'}
                </span>
            </div>
            <p className="mt-1 text-sm text-text-muted">
                Detected {formatTimestamp(record.detected_at)}
                {record.resolved_at !== null &&
                    ` · resolved ${formatTimestamp(record.resolved_at)}`}
            </p>
        </li>
    );
}
