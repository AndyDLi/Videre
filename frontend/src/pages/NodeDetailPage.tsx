import { useParams } from 'react-router-dom';

import { PageContainer } from '../components/PageContainer';

export function NodeDetailPage() {
    const { nodeId } = useParams<{ nodeId: string }>();
    return (
        <PageContainer
            title={`Node ${nodeId ?? ''}`}
            description="Built in Task 7.4 from GET /nodes/{id}."
        >
            <p className="text-sm text-text-muted">Not implemented yet.</p>
        </PageContainer>
    );
}
