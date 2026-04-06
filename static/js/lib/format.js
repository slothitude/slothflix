export function fmtSize(bytes) {
    if (!bytes) return '';
    const n = Number(bytes);
    if (isNaN(n)) return bytes;
    for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
        if (n < 1024) return `${n.toFixed(1)} ${unit}`;
        n /= 1024;
    }
    return `${n.toFixed(1)} PB`;
}

export function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
