import type { ReactNode } from 'react';

interface PageHeadingProps {
    eyebrow: string;
    title: string;
    description?: string;
    aside?: ReactNode;
}

export function PageHeading({ eyebrow, title, description, aside }: PageHeadingProps) {
    return (
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
            <div className="max-w-2xl">
                <p className="eyebrow text-accent">{eyebrow}</p>
                <h1 className="display-title mt-2 text-4xl sm:text-5xl">{title}</h1>
                {description !== undefined && <p className="mt-4 text-text-muted">{description}</p>}
            </div>
            {aside}
        </div>
    );
}
