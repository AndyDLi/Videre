import { describe, expect, it } from 'vitest';

import { drillDownPath } from '../domain/entityLinks';

describe('drillDownPath', () => {
    it('routes a node to its own drill-down', () => {
        expect(drillDownPath('node', 'node-3')).toBe('/nodes/node-3');
    });

    it('routes a job to its own drill-down', () => {
        expect(drillDownPath('job', 'job-abc')).toBe('/jobs/job-abc');
    });

    it('nests a GPU under the node encoded in its id', () => {
        expect(drillDownPath('gpu', 'gpu-2-5')).toBe('/nodes/node-2/gpus/gpu-2-5');
    });

    it('has no path for a GPU id that does not encode a node', () => {
        expect(drillDownPath('gpu', 'gpu-unknown')).toBeNull();
    });
});
