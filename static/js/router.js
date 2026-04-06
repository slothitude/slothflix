// Hash-based SPA router
const listeners = new Set();

export function navigate(path) {
    window.location.hash = '#' + path;
}

export function getRoute() {
    const hash = window.location.hash.slice(1) || '/';
    return hash;
}

export function onRouteChange(callback) {
    listeners.add(callback);
    return () => listeners.delete(callback);
}

window.addEventListener('hashchange', () => {
    const route = getRoute();
    for (const cb of listeners) cb(route);
});
