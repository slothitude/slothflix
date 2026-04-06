// Preact signals for global state
import { signal, computed } from 'https://esm.sh/@preact/signals';

export const currentTab = signal('movies');
export const gameSubTab = signal('myroms');
export const currentHero = signal(null);
export const streamState = signal({ active: false });
export const playerState = signal('idle'); // idle, loading, trailer, buffering, playing, ended
export const currentSessionId = signal(null);
export const detailItem = signal(null);
export const searchQuery = signal('');
export const searchResults = signal([]);
export const vimmSystem = signal('NES');
export const vimmLetter = signal('A');
export const installedRoms = signal(new Set());
export const catalogData = signal({ movies: [], tv: [] });
