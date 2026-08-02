import { useState } from 'react';

import type { EntityType } from '../api/types';
import { formatEntityId } from '../domain/format';
import { AiAssistantPanel } from './AiAssistantPanel';
import { HealthBadge } from './HealthBadge';

interface EntityHeaderProps {
    state: string;
    entityType: EntityType;
    entityId: string;
}

export function EntityHeader({ state, entityType, entityId }: EntityHeaderProps) {
    const [isAssistantOpen, setIsAssistantOpen] = useState(false);

    return (
        <>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
                <div>
                    <p className="eyebrow text-accent">{entityId}</p>
                    <h1 className="display-title mt-2 text-4xl sm:text-5xl">
                        {formatEntityId(entityId)}
                    </h1>
                    <div className="mt-3">
                        <HealthBadge state={state} />
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => {
                        setIsAssistantOpen(true);
                    }}
                    className="control border-accent-border text-accent hover:bg-surface-raised"
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
