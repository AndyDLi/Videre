import type { ReactNode } from 'react';

interface CardProps {
    title?: string;
    headingLevel?: 2 | 3;
    children: ReactNode;
}

export function Card({ title, headingLevel = 2, children }: CardProps) {
    const Heading = headingLevel === 2 ? 'h2' : 'h3';

    return (
        <section className="rounded border border-border-subtle bg-surface p-4">
            {title !== undefined && <Heading className="text-sm font-semibold">{title}</Heading>}
            <div className={title === undefined ? '' : 'mt-2'}>{children}</div>
        </section>
    );
}
