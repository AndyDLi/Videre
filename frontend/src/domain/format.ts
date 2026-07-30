export function formatTimestamp(isoTimestamp: string): string {
    return new Date(isoTimestamp).toLocaleString();
}
