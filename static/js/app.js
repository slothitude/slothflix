// SlothFlix - Main app entry point (Preact + htm, no build step)
import { h, render } from 'https://esm.sh/preact@10';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10/hooks';
import htm from 'https://esm.sh/htm@3';
import { signal } from 'https://esm.sh/@preact/signals';

import { authFetch } from './api.js';
import { currentTab, gameSubTab, currentHero, catalogData, installedRoms } from './state.js';
import { fmtSize, esc } from './lib/format.js';

const html = htm.bind(h);

// --- Signals ---
const streamState = signal({ active: false });
const playerState = signal('idle');
const currentSessionId = signal(null);
const detailItem = signal(null);
const playerOverlay = signal(false);
const gameOverlay = signal(false);
const gameItem = signal(null);
const vpnIp = signal('checking...');
const searchQuery = signal('');
const splashVisible = signal(true);
const trailerPlaylist = signal([]);
const fileList = signal([]);
const currentFileId = signal(null);

// --- Splash ---
function SplashScreen() {
    return html`<div class="splash ${splashVisible.value ? '' : 'fade-out'}">
        <img src="/static/sloth_logo.webp" alt="SlothFlix" />
        <div class="splash-sub">LOADING</div>
    </div>`;
}

// --- Nav ---
function Nav() {
    const scrolled = signal(false);
    const searchInput = useRef(null);

    useEffect(() => {
        const onScroll = () => scrolled.value = window.scrollY > 50;
        window.addEventListener('scroll', onScroll);
        return () => window.removeEventListener('scroll', onScroll);
    }, []);

    const onSearch = useCallback((e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            if (q) searchQuery.value = q;
        }
    }, []);

    const tab = currentTab.value;

    return html`<nav class="nav ${scrolled.value ? 'scrolled' : ''}">
        <div class="logo">SLOTHFLIX</div>
        <div class="nav-tabs">
            <div class="nav-tab ${tab === 'movies' ? 'active' : ''}" onClick=${() => currentTab.value = 'movies'}>Movies & TV</div>
            <div class="nav-tab ${tab === 'games' ? 'active' : ''}" onClick=${() => currentTab.value = 'games'}>Games</div>
            <div class="nav-tab" onClick=${() => window.location.href = 'https://chat.slothitude.giize.com'}>Chat</div>
            <div class="nav-tab" onClick=${() => window.location.href = 'https://mail.slothitude.giize.com'}>Mail</div>
        </div>
        <div class="search-box">
            <span class="icon">\uD83D\uDD0D</span>
            <input ref=${searchInput} type="text" placeholder="Search movies, TV shows..." autocomplete="off" onKeyDown=${onSearch} />
        </div>
        <div class="ip-badge" onClick=${checkIP}>VPN: ${vpnIp.value}</div>
    </nav>`;
}

// --- Hero ---
function Hero() {
    const hero = currentHero.value;
    const blurb = signal('');

    useEffect(() => {
        if (hero) loadBlurb(hero.title).then(b => blurb.value = b);
    }, [hero]);

    if (!hero) return null;

    return html`<section class="hero">
        <div class="hero-info">
            <h1>${hero.title}</h1>
            <p>${blurb.value}</p>
            <div>
                <button class="btn btn-play" onClick=${() => playItem(hero)}>▶ Play</button>
                <button class="btn btn-queue" onClick=${() => detailItem.value = hero}>More Info</button>
            </div>
        </div>
    </section>`;
}

// --- Card ---
function Card({ item }) {
    const cardRef = useRef(null);
    const imgRef = useRef(null);
    const loaded = signal(false);
    const observed = signal(false);

    useEffect(() => {
        const card = cardRef.current;
        if (!card) return;
        const obs = new IntersectionObserver(([entry]) => {
            if (entry.isIntersecting) {
                observed.value = true;
                obs.unobserve(card);
            }
        }, { rootMargin: '200px' });
        obs.observe(card);
        return () => obs.disconnect();
    }, []);

    useEffect(() => {
        if (!observed.value) return;
        const img = imgRef.current;
        if (!img) return;
        const src = '/api/poster/' + encodeURIComponent(item.title);
        const tmp = new Image();
        tmp.onload = () => { img.src = src; loaded.value = true; };
        tmp.onerror = () => { img.src = '/static/poster_default.webp'; loaded.value = true; };
        tmp.src = src;
    }, [observed.value]);

    return html`<div class="card" ref=${cardRef} onClick=${() => detailItem.value = item}>
        <img ref=${imgRef} src="" alt="" style=${loaded.value ? '' : 'opacity:0'} class=${loaded.value ? 'loaded' : ''} />
        <div class="card-placeholder" style=${loaded.value ? 'display:none' : ''}>🎬</div>
        <div class="card-title" title=${item.title}>${item.title}</div>
        <div class="card-meta">
            <span>${item.size || ''}</span>
            <span class="seed-badge">▲ ${item.seeders || 0}</span>
        </div>
    </div>`;
}

// --- Catalog Row ---
function CatalogRow({ title, items }) {
    if (!items || !items.length) return null;
    return html`<div class="row-section">
        <h2 class="row-title">${title}</h2>
        <div class="row-wrap">
            <div class="row-scroll">
                ${items.map(item => html`<${Card} key=${item.magnet || item.title} item=${item} />`)}
            </div>
        </div>
    </div>`;
}

// --- Detail Panel ---
function DetailPanel() {
    const item = detailItem.value;
    const blurb = signal('');
    const files = signal([]);
    const loadingFiles = signal(false);

    useEffect(() => {
        if (item) {
            loadBlurb(item.title).then(b => blurb.value = b);
            files.value = [];
        }
    }, [item]);

    if (!item) return null;

    const close = () => { detailItem.value = null; };

    const loadFiles = async () => {
        loadingFiles.value = true;
        try {
            const r = await authFetch('/api/stream/files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ magnet: item.magnet })
            });
            const d = await r.json();
            files.value = d.files || d || [];
        } catch (e) {
            files.value = [];
        }
        loadingFiles.value = false;
    };

    return html`<div>
        <div class="overlay open" onClick=${close}></div>
        <div class="detail-panel open">
            <button class="detail-close" onClick=${close}>×</button>
            <div class="detail-body" style="padding-top:24px">
                <h2>${item.title}</h2>
                <div class="detail-meta">
                    <span class="green">▲ ${item.seeders || 0} seeds</span>
                    <span>${item.leechers || 0} leechers</span>
                    <span>${item.size || ''}</span>
                    <span>${item.source || ''}</span>
                </div>
                <div class="detail-desc">${blurb.value || 'Loading description...'}</div>
                <div style="margin-top:16px">
                    <button class="btn btn-play" onClick=${() => { close(); playItem(item); }}>▶ Play</button>
                    <button class="btn btn-queue" onClick=${loadFiles} style="margin-left:10px">
                        ${loadingFiles.value ? 'Loading...' : 'Episodes'}
                    </button>
                </div>
                ${files.value.length > 1 ? html`
                    <h3 style="margin-top:16px;margin-bottom:8px">Select Episode</h3>
                    <div class="episode-grid">
                        ${files.value.map(f => html`
                            <div class="ep-card" key=${f.id} onClick=${() => { close(); playItem(item, f.id); }}>
                                <div class="ep-name" title=${f.name}>${f.name}</div>
                                <div class="ep-size">${fmtSize(f.size)}</div>
                            </div>
                        `)}
                    </div>
                ` : null}
            </div>
        </div>
    </div>`;
}

// --- Video Player ---
function VideoPlayer() {
    const visible = playerOverlay.value;
    const videoRef = useRef(null);
    const [statusText, setStatusText] = useState('');
    const [progress, setProgress] = useState(0);
    const [dlSpeed, setDlSpeed] = useState('--');
    const [seeds, setSeeds] = useState('--');
    const [peers, setPeers] = useState('--');
    const [showReady, setShowReady] = useState(false);
    const [showNextEp, setShowNextEp] = useState(false);
    const [nextEpTitle, setNextEpTitle] = useState('');
    const [countdown, setCountdown] = useState(5);
    const [showError, setShowError] = useState(false);
    const [errorMsg, setErrorMsg] = useState('');
    const pollRef = useRef(null);
    const countdownRef = useRef(null);

    const close = () => {
        if (videoRef.current) { videoRef.current.pause(); videoRef.current.src = ''; }
        if (pollRef.current) clearInterval(pollRef.current);
        if (countdownRef.current) clearInterval(countdownRef.current);
        playerOverlay.value = false;
        setShowReady(false);
        setShowNextEp(false);
        setShowError(false);
    };

    useEffect(() => {
        if (!visible || !currentSessionId.value) return;
        const poll = async () => {
            try {
                const r = await authFetch('/api/stream/status');
                const d = await r.json();
                if (!d.active) { close(); return; }
                setProgress(d.progress || 0);
                setDlSpeed(d.download_rate ? (d.download_rate >= 1 ? d.download_rate.toFixed(1) + ' MB/s' : (d.download_rate * 1024).toFixed(0) + ' KB/s') : '--');
                setSeeds(d.seeds || '--');
                setPeers(d.peers || '--');
            } catch (e) {}
        };
        pollRef.current = setInterval(poll, 2000);
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [visible, currentSessionId.value]);

    const startPlay = () => {
        setShowReady(false);
        if (videoRef.current && currentSessionId.value) {
            videoRef.current.src = '/play/' + currentSessionId.value;
            videoRef.current.play().catch(() => {});
        }
    };

    const onEnded = () => {
        const files = fileList.value;
        const fid = currentFileId.value;
        if (!files.length || fid === null) { setShowNextEp(true); setNextEpTitle(''); return; }
        const idx = files.findIndex(f => f.id === fid);
        const next = idx >= 0 && idx + 1 < files.length ? files[idx + 1] : null;
        if (next) {
            setNextEpTitle('Next: ' + next.name);
            setCountdown(5);
            setShowNextEp(true);
            countdownRef.current = setInterval(() => {
                setCountdown(c => {
                    if (c <= 1) {
                        clearInterval(countdownRef.current);
                        // Auto-play
                        if (currentHero.value) playItem(currentHero.value, next.id);
                        return 0;
                    }
                    return c - 1;
                });
            }, 1000);
        } else {
            setNextEpTitle('');
            setShowNextEp(true);
        }
    };

    const stop = async () => {
        try { await authFetch('/api/stream/stop', { method: 'POST' }); } catch (e) {}
        close();
    };

    if (!visible) return null;

    return html`<div class="player-overlay open">
        <button class="player-close" onClick=${close}>×</button>
        <video ref=${videoRef} controls autoplay onEnded=${onEnded} style="position:relative;z-index:1"></video>
        <div class="player-loading ${statusText ? '' : 'hidden'}">
            <div class="spinner" style="width:40px;height:40px"></div>
            <div>${statusText}</div>
            <div class="dl-stats">
                <div class="dl-stat"><span class="dl-val">${dlSpeed}</span><span class="dl-label">Speed</span></div>
                <div class="dl-stat"><span class="dl-val">${seeds}</span><span class="dl-label">Seeds</span></div>
                <div class="dl-stat"><span class="dl-val">${peers}</span><span class="dl-label">Peers</span></div>
            </div>
            <div class="dl-progress-wrap">
                <div class="dl-progress-bar"><div class="fill" style=${'width:' + progress + '%'}></div></div>
                <div class="dl-pct">${progress.toFixed(1)}%</div>
            </div>
        </div>
        ${showReady ? html`
            <div class="play-ready-overlay" onClick=${startPlay}>
                <div class="play-btn-big">▶</div>
                <div class="play-ready-title">${currentHero.value?.title || ''}</div>
            </div>
        ` : null}
        ${showNextEp ? html`
            <div class="next-ep-overlay">
                <div class="next-ep-title">${nextEpTitle}</div>
                ${nextEpTitle ? html`<div class="next-ep-countdown">Playing in ${countdown}s...</div>` : null}
                <div class="next-ep-buttons">
                    ${nextEpTitle ? html`<button class="btn btn-play" onClick=${() => {
                        if (countdownRef.current) clearInterval(countdownRef.current);
                        const files = fileList.value;
                        const fid = currentFileId.value;
                        const idx = files.findIndex(f => f.id === fid);
                        const next = files[idx + 1];
                        if (next && currentHero.value) playItem(currentHero.value, next.id);
                    }}>Play Now</button>` : null}
                    <button class="btn btn-queue" onClick=${close}>${nextEpTitle ? 'Cancel' : 'Back to Browse'}</button>
                </div>
            </div>
        ` : null}
        ${showError ? html`
            <div class="player-error-overlay">
                <div class="player-error-icon">⚠</div>
                <div class="player-error-msg">${errorMsg}</div>
                <div class="player-error-buttons">
                    <button class="btn btn-play" onClick=${() => { setShowError(false); if (currentHero.value) playItem(currentHero.value, currentFileId.value); }}>Try Again</button>
                    <button class="btn btn-queue" onClick=${close}>Close</button>
                </div>
            </div>
        ` : null}
        <div class="stream-bar open">
            <div class="spinner"></div>
            <div class="progress"><div class="progress-fill" style=${'width:' + progress + '%'}></div></div>
            <span class="speed">${dlSpeed}</span>
            <span class="seeds">${seeds} seeds</span>
            <button class="btn-stop" onClick=${stop}>Stop</button>
        </div>
    </div>`;
}

// --- Game Player ---
function GamePlayer() {
    const item = gameItem.value;
    const containerRef = useRef(null);

    useEffect(() => {
        if (!item || !containerRef.current) return;
        // Set EmulatorJS globals
        window.EJS_player = '#' + containerRef.current.id;
        window.EJS_core = item.core;
        window.EJS_gameUrl = `${location.origin}/api/games/rom/${encodeURIComponent(item.system)}/${encodeURIComponent(item.filename)}`;
        window.EJS_gameName = item.title;
        window.EJS_backgroundColor = '#000';

        const script = document.createElement('script');
        script.src = '/emu/data/loader.js';
        script.onerror = () => {
            containerRef.current.innerHTML = '<p style="color:#e50914;padding:40px;text-align:center">Failed to load EmulatorJS</p>';
        };
        containerRef.current.appendChild(script);
    }, [item]);

    const close = () => {
        gameOverlay.value = false;
        gameItem.value = null;
        if (containerRef.current) containerRef.current.innerHTML = '';
        delete window.EJS_player;
        delete window.EJS_core;
        delete window.EJS_gameUrl;
        delete window.EJS_gameName;
    };

    if (!gameOverlay.value) return null;

    return html`<div class="game-overlay open">
        <button class="game-close" onClick=${close}>×</button>
        <div ref=${containerRef} id="gameContainer" style="width:100%;height:100%"></div>
    </div>`;
}

// --- Game Card ---
function GameCard({ rom, system, icon }) {
    const name = rom.filename.replace(/\.[^.]+$/, '');
    const launch = () => {
        gameItem.value = { core: system, system, filename: rom.filename, title: name };
        gameOverlay.value = true;
    };
    return html`<div class="game-card" onClick=${launch}>
        <div class="game-icon">${icon}</div>
        <div class="game-title" title=${name}>${name}</div>
        <div class="game-meta">
            <span>${fmtSize(rom.size)}</span>
            <span class="system-badge">${system.toUpperCase()}</span>
        </div>
    </div>`;
}

// --- Games Tab ---
const SYSTEM_ICONS = {
    nes: '🎮', snes: '🎮', gba: '🕹', gbc: '🕹', n64: '🎮', ps1: '🎮',
    genesis: '🎮', atari2600: '🕹', nds: '🕹', segacd: '🎮', '32x': '🎮',
    sms: '🎮', gg: '🕹', ngp: '🕹', ws: '🕹', pce: '🎮', coleco: '🕹',
};
const VIMM_SYSTEMS = [
    { value: 'NES', label: 'Nintendo' }, { value: 'SNES', label: 'Super Nintendo' },
    { value: 'GBA', label: 'Game Boy Advance' }, { value: 'GBC', label: 'Game Boy Color' },
    { value: 'N64', label: 'Nintendo 64' }, { value: 'PS1', label: 'PlayStation' },
    { value: 'Genesis', label: 'Genesis' }, { value: 'DS', label: 'Nintendo DS' },
];
const VIMM_TO_SYS = { NES: 'nes', SNES: 'snes', GBA: 'gba', GBC: 'gbc', N64: 'n64', PS1: 'psx', Genesis: 'segamd', DS: 'nds' };

function GamesTab() {
    const sub = gameSubTab.value;
    const systems = signal({});
    const loading = signal(true);
    const vimmSystem = signal('NES');
    const vimmLetter = signal('S');
    const vimmGames = signal([]);
    const vimmLoading = signal(false);

    const loadRoms = async () => {
        loading.value = true;
        try {
            const r = await authFetch('/api/games');
            const d = await r.json();
            systems.value = d.systems || {};
            // Build installed set
            const inst = {};
            for (const [sys, info] of Object.entries(d.systems || {})) {
                inst[sys] = new Set(info.roms.map(r => r.filename.toLowerCase()));
            }
            installedRoms.value = inst;
        } catch (e) {}
        loading.value = false;
    };

    const loadVimm = async () => {
        vimmLoading.value = true;
        try {
            const r = await authFetch('/api/vimm/browse?system=' + vimmSystem.value + '&letter=' + vimmLetter.value);
            const d = await r.json();
            vimmGames.value = d.games || [];
        } catch (e) { vimmGames.value = []; }
        vimmLoading.value = false;
    };

    useEffect(() => { loadRoms(); }, []);
    useEffect(() => { if (sub === 'library') loadVimm(); }, [sub, vimmSystem.value, vimmLetter.value]);

    return html`<div style="padding-top:70px">
        <div class="tab-sub">
            <button class="tab-sub-btn ${sub === 'myroms' ? 'active' : ''}" onClick=${() => gameSubTab.value = 'myroms'}>My ROMs</button>
            <button class="tab-sub-btn ${sub === 'library' ? 'active' : ''}" onClick=${() => gameSubTab.value = 'library'}>ROM Library</button>
            <span class="manage-link" onClick=${() => window.open('/emu/', '_blank')}>Manage ROMs</span>
        </div>
        <div style="padding:20px 40px">
            ${sub === 'myroms' ? html`
                ${loading.value ? html`<div class="lib-loading">Loading...</div>` : html`
                    ${Object.keys(systems.value).length === 0 ? html`
                        <div class="row-section">
                            <h2 class="row-title">No ROMs installed</h2>
                            <p style="color:#888;margin-top:8px">Browse the <span style="color:#e50914;cursor:pointer" onClick=${() => gameSubTab.value = 'library'}>ROM Library</span> to download games</p>
                        </div>
                    ` : html`
                        ${Object.entries(systems.value).map(([sys, info]) => html`
                            <div class="row-section" key=${sys}>
                                <h2 class="row-title">${info.display_name} (${info.count})</h2>
                                <div class="row-wrap">
                                    <div class="row-scroll">
                                        ${info.roms.map(rom => html`<${GameCard} key=${rom.filename} rom=${rom} system=${sys} icon=${SYSTEM_ICONS[sys] || '🎮'} />`)}
                                    </div>
                                </div>
                            </div>
                        `)}
                    `}
                `}
            ` : html`
                <div class="library-bar">
                    <select value=${vimmSystem.value} onChange=${e => vimmSystem.value = e.target.value}>
                        ${VIMM_SYSTEMS.map(s => html`<option value=${s.value} key=${s.value}>${s.label}</option>`)}
                    </select>
                    <button onClick=${loadVimm}>Browse</button>
                    <span style="color:#888;font-size:12px">Powered by vimm.net</span>
                </div>
                <div class="letter-bar">
                    ${'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').map(l => html`
                        <span key=${l} class=${l === vimmLetter.value ? 'active' : ''} onClick=${() => vimmLetter.value = l}>${l}</span>
                    `)}
                </div>
                ${vimmLoading.value ? html`<div class="lib-loading">Loading...</div>` : html`
                    <div class="vimm-grid">
                        ${vimmGames.value.map(g => html`<${VimmCard} key=${g.id} game=${g} vimmSystem=${vimmSystem.value} installed=${installedRoms.value} />`)}
                    </div>
                `}
            `}
        </div>
    </div>`;
}

function VimmCard({ game, vimmSystem, installed }) {
    const [downloading, setDownloading] = useState(false);
    const [isInstalled, setIsInstalled] = useState(false);
    const sysKey = VIMM_TO_SYS[vimmSystem] || vimmSystem.toLowerCase();

    useEffect(() => {
        const inst = installed[sysKey];
        setIsInstalled(inst ? inst.has(game.title.toLowerCase() + '.nes') : false);
    }, [installed]);

    const download = async (e) => {
        e.stopPropagation();
        setDownloading(true);
        try {
            const r = await authFetch('/api/vimm/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game_id: game.id, system: sysKey })
            });
            const d = await r.json();
            if (!d.error) setIsInstalled(true);
        } catch (e) {}
        setDownloading(false);
    };

    return html`<div class="vimm-card">
        <div style="width:100%;height:220px;background:linear-gradient(135deg,#1a1a2e,#16213e);display:flex;align-items:center;justify-content:center;font-size:32px">🎮</div>
        <div class="vimm-title">${game.title}</div>
        <div class="vimm-meta">
            <span class="vimm-rating">${game.rating || ''}</span>
            <span>${vimmSystem}</span>
        </div>
        <div class="dl-overlay">
            ${isInstalled ? html`<button class="btn-sm btn-installed">Installed</button>` :
                html`<button class="btn-sm btn-dl" disabled=${downloading} onClick=${download}>${downloading ? 'Downloading...' : 'Download'}</button>`}
        </div>
    </div>`;
}

// --- Search Results ---
function SearchResults({ query }) {
    const results = signal([]);
    const loading = signal(true);

    useEffect(() => {
        if (!query) return;
        loading.value = true;
        authFetch('/api/search?q=' + encodeURIComponent(query))
            .then(r => r.json())
            .then(d => { results.value = Array.isArray(d) ? d : []; loading.value = false; })
            .catch(() => { results.value = []; loading.value = false; });
    }, [query]);

    if (loading.value) return html`<div style="padding:20px 40px"><h2 class="row-title">Searching...</h2></div>`;
    if (!results.value.length) return html`<div style="padding:20px 40px"><h2 class="row-title">No results found</h2></div>`;

    return html`<div style="padding-top:70px">
        <${CatalogRow} title="Results for \"${query}\"" items=${results.value} />
    </div>`;
}

// --- Main App ---
function App() {
    const tab = currentTab.value;
    const search = searchQuery.value;

    // Load catalog on mount
    useEffect(() => {
        checkIP();
        loadCatalog();
        // Deep-link: ?game=system:filename
        const params = new URLSearchParams(location.search);
        const gameParam = params.get('game');
        if (gameParam && gameParam.includes(':')) {
            const idx = gameParam.indexOf(':');
            const system = gameParam.substring(0, idx);
            const filename = gameParam.substring(idx + 1);
            currentTab.value = 'games';
            setTimeout(() => {
                gameItem.value = { core: system, system, filename, title: filename.replace(/\.[^.]+$/, '') };
                gameOverlay.value = true;
            }, 100);
        }
    }, []);

    return html`<div>
        <${SplashScreen} />
        <${Nav} />
        ${search ? html`<${SearchResults} query=${search} />` : html`
            ${tab === 'movies' ? html`
                <${Hero} />
                <div id="catalogRows">
                    <${CatalogRow} title="Top Movies" items=${catalogData.value.movies} />
                    <${CatalogRow} title="Top TV Shows" items=${catalogData.value.tv} />
                </div>
            ` : html`<${GamesTab} />`}
        `}
        <${DetailPanel} />
        <${VideoPlayer} />
        <${GamePlayer} />
    </div>`;
}

// --- API helpers ---
async function checkIP() {
    try {
        const r = await authFetch('/api/ip');
        const d = await r.json();
        vpnIp.value = d.ip || 'unknown';
    } catch (e) {
        vpnIp.value = 'error';
    }
}

async function loadCatalog() {
    const [movies, tv] = await Promise.all([
        authFetch('/api/catalog/movies').then(r => r.json()).catch(() => []),
        authFetch('/api/catalog/tv').then(r => r.json()).catch(() => []),
    ]);
    catalogData.value = { movies: Array.isArray(movies) ? movies : [], tv: Array.isArray(tv) ? tv : [] };
    if (catalogData.value.movies.length) {
        currentHero.value = catalogData.value.movies[0];
    }
    splashVisible.value = false;
    setTimeout(() => { splashVisible.value = false; }, 700);
}

async function loadBlurb(title) {
    try {
        const r = await authFetch('/api/blurb/' + encodeURIComponent(title));
        const d = await r.json();
        return d.blurb || '';
    } catch (e) { return ''; }
}

async function playItem(item, fileId) {
    currentFileId.value = fileId !== undefined ? fileId : null;
    playerOverlay.value = true;

    const body = { magnet: item.magnet };
    if (fileId !== undefined) body.file_id = fileId;

    const MAX_RETRIES = 3;
    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
            if (attempt > 1) {
                try { await authFetch('/api/stream/stop', { method: 'POST' }); } catch (e) {}
                await new Promise(r => setTimeout(r, 2000));
            }
            const r = await authFetch('/api/stream/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (d.error) throw new Error(d.error);
            currentSessionId.value = d.session_id;
            return; // success
        } catch (e) {
            if (attempt === MAX_RETRIES) {
                playerOverlay.value = false;
                alert('Failed to start stream: ' + e.message);
            }
        }
    }
}

// --- Mount ---
render(html`<${App} />`, document.getElementById('app'));
