import type { ReactNode } from 'react';

interface Detail {
    label: string;
    value: ReactNode;
}

export function DetailList({ details }: { details: Detail[] }) {
    return (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {details.map((detail) => (
                <div key={detail.label}>
                    <dt className="text-sm font-medium text-text-muted">{detail.label}</dt>
                    <dd className="mt-0.5 text-sm">{detail.value}</dd>
                </div>
            ))}
        </dl>
    );
}
