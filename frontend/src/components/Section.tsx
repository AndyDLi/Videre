import type { ReactNode } from 'react';

interface SectionProps {
    title?: string;
    headingLevel?: 2 | 3;
    children: ReactNode;
}

export function Section({ title, headingLevel = 2, children }: SectionProps) {
    const Heading = headingLevel === 2 ? 'h2' : 'h3';

    return (
        <section className="border-t border-border-subtle pt-4">
            {title !== undefined && <Heading className="eyebrow text-accent">{title}</Heading>}
            <div className={title === undefined ? '' : 'mt-4'}>{children}</div>
        </section>
    );
}
