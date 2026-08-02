import type { ReactNode } from 'react';

interface Detail {
    label: string;
    value: ReactNode;
}

export function DetailList({ details }: { details: Detail[] }) {
    return (
        <dl className="grid gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
            {details.map((detail) => (
                <div key={detail.label} className="border-t border-border-subtle pt-2">
                    <dt className="eyebrow text-accent">{detail.label}</dt>
                    <dd className="mt-1 font-display text-[1.0625rem] text-text-primary">
                        {detail.value}
                    </dd>
                </div>
            ))}
        </dl>
    );
}
