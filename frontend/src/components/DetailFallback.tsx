import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

interface DetailFallbackProps {
    title: string;
    children: ReactNode;
}

export function DetailFallback({ title, children }: DetailFallbackProps) {
    return (
        <section className="max-w-2xl">
            <h1 className="display-title text-4xl sm:text-5xl">{title}</h1>
            <p className="mt-5 text-text-muted">{children}</p>
            <Link
                to="/"
                className="mt-7 inline-block border-b border-accent-border pb-0.5 font-display text-[0.9375rem] font-semibold text-accent"
            >
                Back to the Cluster Overview
                <span aria-hidden="true"> →</span>
            </Link>
        </section>
    );
}
