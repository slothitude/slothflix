// EmulatorJS bootstrap helper
export function launchEmulator(container, core, romUrl) {
    window.EJS_player = '#' + container;
    window.EJS_core = core;
    window.EJS_gameUrl = romUrl;
    window.EJS_language = 'en';
    window.EJS_alignStartButton = 'center';

    // Load EmulatorJS if not already loaded
    if (!document.getElementById('emulatorjs-script')) {
        const script = document.createElement('script');
        script.id = 'emulatorjs-script';
        script.src = '/emu/loader.js';
        document.head.appendChild(script);
    }
}
