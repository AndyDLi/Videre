import { describe, expect, it } from 'vitest';

import { toneForState } from '../domain/healthState';

describe('toneForState', () => {
    it('maps every node health state', () => {
        expect(toneForState('READY')).toBe('good');
        expect(toneForState('NOT_READY')).toBe('bad');
        expect(toneForState('DRAINING')).toBe('warning');
        expect(toneForState('CORDONED')).toBe('warning');
    });

    it('maps every GPU health state', () => {
        expect(toneForState('HEALTHY')).toBe('good');
        expect(toneForState('THROTTLING')).toBe('warning');
        expect(toneForState('DEGRADED')).toBe('warning');
        expect(toneForState('FAILED')).toBe('bad');
    });

    it('maps every job lifecycle state', () => {
        expect(toneForState('PENDING')).toBe('neutral');
        expect(toneForState('RUNNING')).toBe('good');
        expect(toneForState('FAILED')).toBe('bad');
        expect(toneForState('COMPLETED')).toBe('neutral');
    });

    it('falls back to neutral for an unrecognized state', () => {
        expect(toneForState('SOMETHING_NEW')).toBe('neutral');
    });
});
