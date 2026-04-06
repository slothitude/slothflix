// IntersectionObserver-based lazy image loading with max 4 concurrent loads
const MAX_CONCURRENT = 4;
let loading = 0;
const queue = [];

const observer = new IntersectionObserver(
    (entries) => {
        for (const entry of entries) {
            if (entry.isIntersecting) {
                const img = entry.target;
                observer.unobserve(img);
                enqueue(img);
            }
        }
    },
    { rootMargin: '200px' }
);

function enqueue(img) {
    queue.push(img);
    processQueue();
}

function processQueue() {
    while (loading < MAX_CONCURRENT && queue.length > 0) {
        const img = queue.shift();
        loading++;
        const src = img.dataset.src;
        if (src) {
            img.onload = () => { loading--; img.classList.add('loaded'); processQueue(); };
            img.onerror = () => { loading--; processQueue(); };
            img.src = src;
        } else {
            loading--;
            processQueue();
        }
    }
}

export function observe(img) {
    if (img) observer.observe(img);
}

export function unobserve(img) {
    if (img) observer.unobserve(img);
}
