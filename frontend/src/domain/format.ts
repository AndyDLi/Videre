const ACRONYMS = new Map([
    ['gpu', 'GPU'],
    ['gpus', 'GPUs'],
    ['cpu', 'CPU'],
    ['ecc', 'ECC'],
    ['nvlink', 'NVLink'],
    ['xid', 'Xid'],
    ['nccl', 'NCCL'],
    ['oom', 'OOM'],
    ['cni', 'CNI'],
]);

function capitalize(word: string): string {
    const acronym = ACRONYMS.get(word.toLowerCase());
    if (acronym !== undefined) {
        return acronym;
    }
    const isMixedCase = word !== word.toLowerCase() && word !== word.toUpperCase();
    if (isMixedCase) {
        return word;
    }
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

export function formatTimestamp(isoTimestamp: string): string {
    return new Date(isoTimestamp).toLocaleString();
}

export function formatTerm(value: string): string {
    return value
        .split(/[._]/)
        .filter((part) => part.length > 0)
        .map(capitalize)
        .join(' ');
}

export function formatEntityId(id: string): string {
    const separator = id.indexOf('-');
    if (separator === -1) {
        return capitalize(id);
    }
    const kind = capitalize(id.slice(0, separator));
    const remainder = id.slice(separator + 1);
    return `${kind} ${remainder.length === 1 ? remainder.toUpperCase() : remainder}`;
}
