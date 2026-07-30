import type { ReactNode } from 'react';

interface PageContainerProps {
    title: string;
    description?: string;
    children: ReactNode;
}

export function PageContainer({ title, description, children }: PageContainerProps) {
    return (
        <section>
            <h1 className="text-xl font-semibold">{title}</h1>
            {description !== undefined && (
                <p className="mt-1 text-sm text-text-muted">{description}</p>
            )}
            <div className="mt-4 rounded border border-border-subtle bg-surface p-4">
                {children}
            </div>
        </section>
    );
}
