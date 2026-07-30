import { useState } from 'react';

import type { EntityType } from '../api/types';
import { AiAssistantPanel } from './AiAssistantPanel';
import { HealthBadge } from './HealthBadge';

interface EntityHeaderProps {
    title: string;
    state: string;
    entityType: EntityType;
    entityId: string;
}

export function EntityHeader({ title, state, entityType, entityId }: EntityHeaderProps) {
    const [isAssistantOpen, setIsAssistantOpen] = useState(false);

    return (
        <>
            <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-xl font-semibold">{title}</h1>
                <HealthBadge state={state} />
                <button
                    type="button"
                    onClick={() => {
                        setIsAssistantOpen(true);
                    }}
                    className="ml-auto rounded border border-border-subtle bg-surface px-3 py-1 text-sm font-medium hover:bg-surface-muted"
                >
                    Ask the AI Assistant
                </button>
            </div>

            {isAssistantOpen && (
                <AiAssistantPanel
                    entityType={entityType}
                    entityId={entityId}
                    onClose={() => {
                        setIsAssistantOpen(false);
                    }}
                />
            )}
        </>
    );
}
