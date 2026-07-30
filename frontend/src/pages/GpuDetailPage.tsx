import { useParams } from 'react-router-dom';

import { PageContainer } from '../components/PageContainer';

export function GpuDetailPage() {
    const { nodeId, gpuId } = useParams<{ nodeId: string; gpuId: string }>();
    return (
        <PageContainer
            title={`GPU ${gpuId ?? ''}`}
            description={`On node ${nodeId ?? ''} · built in Task 7.4 from GET /nodes/{id}.`}
        >
            <p className="text-sm text-text-muted">Not implemented yet.</p>
        </PageContainer>
    );
}
