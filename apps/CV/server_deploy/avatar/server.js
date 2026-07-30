const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const { execFile, spawn } = require('child_process');
const fs = require('fs');
const crypto = require('crypto');
const {
    TenantAvatarStateStore,
    resolveWsRoleBinding,
    shouldDeliverBroadcastToRole
} = require('./tenant_state');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const PORT = Number(process.env.AVATAR_PORT || process.env.PORT || 3456);
const STATIC_DIR = __dirname;
const CACHE_DIR = path.join(__dirname, 'cache');
const ROOT_DIR = path.join(__dirname, '..');
const SHARED_RUNTIME_DIR = path.resolve(ROOT_DIR, '..', 'shared_runtime');
process.env.PYTHONPATH = [ROOT_DIR, SHARED_RUNTIME_DIR, process.env.PYTHONPATH]
    .filter(Boolean)
    .join(path.delimiter);
loadEnvFile(path.join(ROOT_DIR, '.env'));
const SHARED_CACHE_DIR = path.join(ROOT_DIR, 'cache');
const CLIENT_DOWNLOAD_FILE = path.resolve(
    process.env.CLIENT_DOWNLOAD_FILE || path.join(SHARED_CACHE_DIR, 'downloads', 'CVClient.zip')
);
const CLIENT_DOWNLOAD_NAME = sanitizeDownloadFileName(
    process.env.CLIENT_DOWNLOAD_NAME || 'CVClient.zip'
);
const INTERACTION_MODE_FILE = path.join(SHARED_CACHE_DIR, 'interaction_mode.json');
const GESTURE_STATUS_FILE = path.join(SHARED_CACHE_DIR, 'gesture_status.json');
const EMPLOYEES_DIR = path.join(ROOT_DIR, 'employees');
const TTS_SCRIPT = resolveRuntimeFile('core', 'tts_server.py');
const EMPLOYEE_SYNC_SCRIPT = resolveRuntimeFile('core', 'employee_sync.py');
const LOCAL_ENROLL_SCRIPT = resolveRuntimeFile('core', 'local_enroll.py');
const DAILY_TTS_SCRIPT = resolveRuntimeFile('tools', 'generate_daily_tts_texts.py');
const VENV_PYTHON = path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe');
const PYTHON_BIN = process.env.PYTHON_BIN || (fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python');
const TTS_VOICE_BY_MODEL = {
    epsilon: process.env.TTS_VOICE_EPSILON || process.env.TTS_VOICE || 'zh-CN-XiaoyiNeural',
    chitose: process.env.TTS_VOICE_CHITOSE || 'zh-TW-YunJheNeural',
    haruGreeter: process.env.TTS_VOICE_HARU_GREETER || 'zh-CN-XiaoxiaoNeural',
    haru: process.env.TTS_VOICE_HARU || 'zh-CN-XiaoyiNeural',
    natori: process.env.TTS_VOICE_NATORI || 'zh_male_yunzhou_jupiter_bigtts'
};
const TTS_VOICES = Array.from(new Set(Object.values(TTS_VOICE_BY_MODEL)));
const FIXED_TTS_PROVIDER = String(process.env.FIXED_TTS_PROVIDER || 'volc').trim().toLowerCase();
const RAW_TTS_CACHE_ENABLED = process.env.RAW_TTS_CACHE_ENABLED === '1';
const REALTIME_DIALOG_OUTPUT_FORMAT = String(process.env.REALTIME_DIALOG_OUTPUT_FORMAT || 'pcm_s16le').trim().toLowerCase();
const TTS_PREWARM_CONCURRENCY = Math.max(1, Number(process.env.TTS_PREWARM_CONCURRENCY) || 2);
const API_KEY = process.env.API_KEY || '';
const API_SECRET = process.env.API_SECRET || '';
const API_BASE_URL = (process.env.API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const API_SIGNATURE_TOLERANCE_SECONDS = Math.max(1, Number(process.env.API_SIGNATURE_TOLERANCE_SECONDS) || 300);
const CONTROL_AUTH_ENABLED = process.env.CONTROL_AUTH_ENABLED !== '0';
const CONTROL_USERNAME = process.env.CONTROL_USERNAME || 'admin';
const CONTROL_AUTH_MAX_FAILURES = Math.max(1, Number(process.env.CONTROL_AUTH_MAX_FAILURES) || 5);
const CONTROL_AUTH_WINDOW_SECONDS = Math.max(30, Number(process.env.CONTROL_AUTH_WINDOW_SECONDS) || 300);
const CONTROL_AUTH_LOCK_SECONDS = Math.max(30, Number(process.env.CONTROL_AUTH_LOCK_SECONDS) || 600);
const CONTROL_SESSION_SECONDS = Math.max(300, Number(process.env.CONTROL_SESSION_SECONDS) || 43200);
const CONTROL_SESSION_CACHE_SECONDS = Math.max(5, Number(process.env.TENANT_ADMIN_SESSION_CACHE_SECONDS) || 30);
const CONTROL_SESSION_COOKIE = 'cv_control_session';
const CONTROL_DEFAULT_TENANT_NAME = process.env.CONTROL_DEFAULT_TENANT_NAME || '默认企业';
const AVATAR_SESSION_COOKIE = 'cv_avatar_session';
const AVATAR_SESSION_SECONDS = Math.max(300, Number(process.env.AVATAR_SESSION_TTL_SECONDS) || 2592000);
const AVATAR_PUBLIC_DISPLAY_ENABLED = process.env.AVATAR_PUBLIC_DISPLAY_ENABLED !== '0';
const DIALOG_CHAT_PRIORITY_MODE = Number.isFinite(Number(process.env.DIALOG_CHAT_PRIORITY_MODE))
    ? Number(process.env.DIALOG_CHAT_PRIORITY_MODE)
    : 0;
const ENABLE_REALTIME_DIALOG = process.env.ENABLE_REALTIME_DIALOG === '1';
const REALTIME_DIALOG_RAG_ENABLED = process.env.REALTIME_DIALOG_RAG_ENABLED !== '0';
const VOICE_PIPELINE_ENABLED = process.env.VOICE_PIPELINE_ENABLED !== '0';
const VOICE_PIPELINE_BACKEND = String(process.env.VOICE_PIPELINE_BACKEND || 'cascade').trim().toLowerCase();
const VOICE_PIPELINE_CLIENT_VAD_FALLBACK_MS = Math.max(
    1800,
    Number(process.env.VOICE_PIPELINE_CLIENT_VAD_FALLBACK_MS) || 8000
);
const FIXED_SPEECH_NOISE_GUARD_ENABLED = process.env.FIXED_SPEECH_NOISE_GUARD_ENABLED !== '0';
const FIXED_SPEECH_POST_GUARD_MS = Math.max(
    0,
    Number(process.env.FIXED_SPEECH_POST_GUARD_MS) || 1200
);
const VOICE_PIPELINE_PUBLIC_URL = process.env.VOICE_PIPELINE_PUBLIC_URL || '';
const DEVICE_ID = process.env.DEVICE_ID || 'frontdesk-001';
const TENANT_ID = process.env.TENANT_ID || 'default';
const SITE_ID = process.env.SITE_ID || 'default';
const INTERACTION_MODES = [
    {
        key: 'quotes_only',
        label: '语录',
        description: '固定/随机语录',
        realtimeDialog: false,
        realtimeRag: false
    },
    {
        key: 'quotes_realtime',
        label: '语录+实时',
        description: '语录保留，实时沟通不检索',
        realtimeDialog: true,
        realtimeRag: false
    },
    {
        key: 'quotes_realtime_rag',
        label: '语录+实时RAG',
        description: '语录保留，实时沟通接入知识库',
        realtimeDialog: true,
        realtimeRag: true
    }
];
const NAMED_TTS_TYPES = ['check_in', 'check_out', 'repeat', 'first_time', 'returning'];
const ANONYMOUS_TTS_TYPES = ['stranger', 'returning_stranger', 'stranger_stare', 'checked_in_stare', 'idle_long', 'crowd'];
const prewarmStatus = {
    running: false,
    complete: false,
    generated: 0,
    skipped: 0,
    total: 0,
    error: ''
};
const tenantAvatarState = new TenantAvatarStateStore();
const CAPTURE_LOG_LIMIT = 12000;
const dailyTtsStatus = {
    running: false,
    complete: false,
    startedAt: '',
    finishedAt: '',
    error: '',
    stdout: '',
    stderr: '',
    clearedCacheFiles: 0
};
const avatarSessionBindings = new Map();
const faceCaptureStatuses = new Map();
const knowledgeIndexStatuses = new Map();
let gestureStatusCache = null;
const wsClientMeta = new WeakMap();
const activeAvatarClients = new Map();
const controlAuthFailures = new Map();
const controlSessions = new Map();

function resolveRuntimeFile(...relativeParts) {
    const rolePath = path.join(ROOT_DIR, ...relativeParts);
    if (fs.existsSync(rolePath)) {
        return rolePath;
    }
    const sharedPath = path.join(SHARED_RUNTIME_DIR, ...relativeParts);
    if (fs.existsSync(sharedPath)) {
        return sharedPath;
    }
    console.warn('Runtime file not found in role or shared layer:', relativeParts.join('/'));
    return rolePath;
}

function loadEnvFile(filePath) {
    if (!fs.existsSync(filePath)) return;
    const content = fs.readFileSync(filePath, 'utf8');
    content.split(/\r?\n/).forEach((rawLine) => {
        const line = rawLine.trim();
        if (!line || line.startsWith('#') || !line.includes('=')) return;
        const index = line.indexOf('=');
        const key = line.slice(0, index).trim();
        let value = line.slice(index + 1).trim();
        if (!key || Object.prototype.hasOwnProperty.call(process.env, key)) return;
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
            value = value.slice(1, -1);
        }
        process.env[key] = value;
    });
}

function isControlProtectedPath(req) {
    const routePath = req.path || '';
    if (routePath === '/employees/sync' || routePath === '/employees/enroll-local') {
        return false;
    }
    if (routePath === '/control.html' || routePath === '/control.js' || routePath === '/control.css') {
        return true;
    }
    if (routePath === '/super-admin.html' || routePath === '/super-admin.js' || routePath === '/super-admin.css') {
        return true;
    }
    return [
        '/interaction-mode',
        '/gesture/status',
        '/faces/capture',
        '/faces/capture-status',
        '/daily-tts',
        '/knowledge',
        '/employees',
        '/tenant',
        '/platform-admin'
    ].some((prefix) => routePath === prefix || routePath.startsWith(`${prefix}/`));
}

function isControlPublicPath(req) {
    const routePath = req.path || '';
    return routePath === '/control-login.html'
        || routePath === '/control-login.js'
        || routePath === '/control-login.css'
        || routePath === '/download/client'
        || routePath === '/download/client.zip'
        || routePath === '/control-auth/login'
        || routePath === '/control-auth/status'
        || routePath === '/control-auth/logout';
}

function sanitizeDownloadFileName(value) {
    const name = String(value || '').trim().replace(/[\\/:*?"<>|]/g, '_');
    return name.endsWith('.zip') ? name : 'CVClient.zip';
}

function parseCookies(req) {
    const header = req.get('cookie') || '';
    const cookies = {};
    header.split(';').forEach((part) => {
        const index = part.indexOf('=');
        if (index < 0) return;
        const key = part.slice(0, index).trim();
        const value = part.slice(index + 1).trim();
        if (key) {
            cookies[key] = decodeURIComponent(value);
        }
    });
    return cookies;
}

function getControlSessionToken(req) {
    return String(parseCookies(req)[CONTROL_SESSION_COOKIE] || '').trim();
}

function cacheControlSession(token, binding) {
    if (!token || !binding || !binding.tenantId || !binding.accountId) return;
    controlSessions.set(token, {
        ...binding,
        cacheExpiresAt: Date.now() + CONTROL_SESSION_CACHE_SECONDS * 1000
    });
}

async function resolveControlSession(req) {
    if (!CONTROL_AUTH_ENABLED) {
        return {
            token: '',
            tenantId: TENANT_ID,
            tenantName: CONTROL_DEFAULT_TENANT_NAME,
            accountId: 0,
            username: CONTROL_USERNAME,
            displayName: '开发模式管理员',
            expiresAt: Date.now() + CONTROL_SESSION_SECONDS * 1000
        };
    }
    const token = getControlSessionToken(req);
    return resolveControlSessionToken(token);
}

async function resolveControlSessionToken(token) {
    if (!token) return null;
    const cached = controlSessions.get(token);
    if (cached && cached.cacheExpiresAt > Date.now()) {
        return { token, ...cached };
    }
    try {
        const response = await apiRequest(
            'GET',
            '/api/v1/tenant-admin/session',
            null,
            { 'X-Tenant-Admin-Session': token },
            { timeoutMs: 10000 }
        );
        const binding = response.data || {};
        cacheControlSession(token, binding);
        return { token, ...binding };
    } catch (err) {
        controlSessions.delete(token);
        if (err && (err.statusCode === 401 || err.statusCode === 403)) return null;
        throw err;
    }
}

function clearControlSessionCookie(req, res) {
    const secure = req.secure || req.get('x-forwarded-proto') === 'https' ? '; Secure' : '';
    res.setHeader(
        'Set-Cookie',
        `${CONTROL_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${secure}`
    );
}

function setControlSessionCookie(req, res, session) {
    const expiresAtMs = Number(session.expiresAt || 0) * (Number(session.expiresAt || 0) < 1e12 ? 1000 : 1);
    const maxAge = Math.max(300, Math.min(
        CONTROL_SESSION_SECONDS,
        Math.floor((expiresAtMs - Date.now()) / 1000) || CONTROL_SESSION_SECONDS
    ));
    const secure = req.secure || req.get('x-forwarded-proto') === 'https' ? '; Secure' : '';
    res.setHeader(
        'Set-Cookie',
        `${CONTROL_SESSION_COOKIE}=${encodeURIComponent(session.token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`
    );
}

function controlCapabilities(session) {
    const platformOperations = Boolean(session && session.tenantId === TENANT_ID);
    return {
        tenantData: true,
        deviceManagement: true,
        platformOperations
    };
}

function controlSessionPayload(session) {
    return {
        tenantId: session.tenantId,
        tenantName: session.tenantName || session.tenantId,
        accountId: Number(session.accountId) || 0,
        username: session.username || '',
        displayName: session.displayName || session.username || '企业管理员',
        expiresAt: session.expiresAt || 0,
        capabilities: controlCapabilities(session)
    };
}

function requirePlatformControl(req, res, next) {
    const session = req.controlSession;
    if (session && controlCapabilities(session).platformOperations) {
        next();
        return;
    }
    console.warn(
        '平台级控制操作已拒绝: tenant=%s path=%s',
        session ? session.tenantId : 'unknown',
        req.path
    );
    res.status(403).json({ ok: false, error: 'platform operation is not available for this tenant' });
}

function createFaceCaptureStatus() {
    return {
        running: false,
        name: '',
        deviceId: '',
        startedAt: '',
        finishedAt: '',
        clientTaskId: '',
        clientTaskDispatched: false,
        exitCode: null,
        error: '',
        stdout: '',
        stderr: ''
    };
}

function createKnowledgeIndexStatus() {
    return {
        running: false,
        complete: false,
        startedAt: '',
        finishedAt: '',
        reset: false,
        paths: null,
        error: '',
        result: null
    };
}

function tenantStatus(statuses, tenantId, factory) {
    if (!statuses.has(tenantId)) statuses.set(tenantId, factory());
    return statuses.get(tenantId);
}

function setAvatarSessionCookie(req, res, token, expiresAt) {
    const remainingSeconds = Math.max(AVATAR_SESSION_SECONDS, 365 * 24 * 3600);
    const secure = req.secure || req.get('x-forwarded-proto') === 'https' ? '; Secure' : '';
    res.setHeader(
        'Set-Cookie',
        `${AVATAR_SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${remainingSeconds}${secure}`
    );
}

function getAvatarSessionToken(req) {
    return String(
        req.get('x-avatar-session') || parseCookies(req)[AVATAR_SESSION_COOKIE] || ''
    ).trim();
}

function cacheAvatarSession(token, binding) {
    if (!token || !binding || !binding.deviceId || !binding.tenantId) return;
    const sessionExpiresAt = Number(binding.expiresAt) || (Date.now() + AVATAR_SESSION_SECONDS * 1000);
    avatarSessionBindings.set(token, {
        tenantId: String(binding.tenantId),
        deviceId: String(binding.deviceId),
        sessionExpiresAt,
        expiresAt: Math.min(sessionExpiresAt, Date.now() + 5 * 60 * 1000)
    });
    if (avatarSessionBindings.size > 4096) {
        const now = Date.now();
        for (const [key, value] of avatarSessionBindings.entries()) {
            if (value.expiresAt <= now || avatarSessionBindings.size > 4096) {
                avatarSessionBindings.delete(key);
            }
        }
    }
}

async function resolveAvatarSession(req) {
    if (req.avatarSession) return req.avatarSession;
    const token = getAvatarSessionToken(req);
    if (!token) return null;
    const cached = avatarSessionBindings.get(token);
    if (cached && cached.expiresAt > Date.now()) {
        return { token, ...cached };
    }
    try {
        const response = await apiRequest(
            'GET',
            '/api/v1/device-sessions/avatar-session',
            null,
            { 'X-Avatar-Session': token },
            { timeoutMs: 10000 }
        );
        const data = response.data || {};
        cacheAvatarSession(token, {
            tenantId: data.tenantId,
            deviceId: data.deviceId,
            expiresAt: Date.now() + AVATAR_SESSION_SECONDS * 1000
        });
        return { token, ...avatarSessionBindings.get(token) };
    } catch (err) {
        avatarSessionBindings.delete(token);
        console.warn('Avatar session validation failed:', err.message || err);
        if (err && Number(err.statusCode) >= 500) throw err;
        return null;
    }
}

async function requireAvatarDevice(req, res, next) {
    try {
        const session = await resolveAvatarSession(req);
        if (!session) {
            res.status(401).json({ ok: false, error: 'avatar device session required' });
            return;
        }
        req.avatarSession = session;
        next();
    } catch (err) {
        console.error('数字人设备会话验证依赖不可用: path=%s error=%s', req.path, err.message || err);
        res.status(503).json({ ok: false, error: 'avatar session service unavailable' });
    }
}

async function requireAvatarStateAuth(req, res, next) {
    try {
        const session = await resolveAvatarSession(req);
        if (session) {
            req.avatarSession = session;
            next();
            return;
        }
        if (API_KEY && API_SECRET && isEmployeeSyncAuthorized(req)) {
            req.avatarSession = {
                token: '',
                tenantId: TENANT_ID,
                deviceId: DEVICE_ID,
                expiresAt: Date.now() + 60000
            };
            next();
            return;
        }
        res.status(401).json({ ok: false, error: 'authenticated avatar state session required' });
    } catch (err) {
        console.error('数字人状态会话验证依赖不可用: path=%s error=%s', req.path, err.message || err);
        res.status(503).json({ ok: false, error: 'avatar state session service unavailable' });
    }
}

function wantsHtml(req) {
    const accept = req.get('accept') || '';
    return req.method === 'GET' && accept.includes('text/html');
}

function getClientIp(req) {
    const forwarded = String(req.get('x-forwarded-for') || '').split(',')[0].trim();
    return forwarded || req.ip || (req.socket && req.socket.remoteAddress) || 'unknown';
}

function getControlAuthFailureState(ip, now) {
    const state = controlAuthFailures.get(ip) || {
        count: 0,
        firstFailureAt: 0,
        lockedUntil: 0,
        lastLogAt: 0
    };
    if (state.firstFailureAt && now - state.firstFailureAt > CONTROL_AUTH_WINDOW_SECONDS * 1000) {
        state.count = 0;
        state.firstFailureAt = 0;
    }
    return state;
}

function recordControlAuthFailure(ip, req) {
    const now = Date.now();
    const state = getControlAuthFailureState(ip, now);
    state.count += 1;
    state.firstFailureAt = state.firstFailureAt || now;
    if (state.count >= CONTROL_AUTH_MAX_FAILURES) {
        state.lockedUntil = now + CONTROL_AUTH_LOCK_SECONDS * 1000;
        console.warn(
            '控制台鉴权锁定: ip=%s attempts=%d lock_seconds=%d path=%s',
            ip,
            state.count,
            CONTROL_AUTH_LOCK_SECONDS,
            req.path
        );
    } else if (now - state.lastLogAt > 3000) {
        console.warn(
            '控制台鉴权失败: ip=%s attempts=%d/%d path=%s',
            ip,
            state.count,
            CONTROL_AUTH_MAX_FAILURES,
            req.path
        );
        state.lastLogAt = now;
    }
    controlAuthFailures.set(ip, state);
    return state;
}

function clearControlAuthFailures(ip) {
    if (controlAuthFailures.delete(ip)) {
        console.info('控制台鉴权成功，失败计数已清空: ip=%s', ip);
    }
}

async function requireControlAuth(req, res, next) {
    if (!CONTROL_AUTH_ENABLED || isControlPublicPath(req) || !isControlProtectedPath(req)) {
        if (!CONTROL_AUTH_ENABLED && isControlProtectedPath(req)) {
            req.controlSession = await resolveControlSession(req);
        }
        next();
        return;
    }

    const ip = getClientIp(req);
    try {
        const session = await resolveControlSession(req);
        if (session) {
            req.controlSession = session;
            next();
            return;
        }
    } catch (err) {
        console.error('控制台会话验证依赖不可用: ip=%s path=%s error=%s', ip, req.path, err.message || err);
        res.status(503).json({ ok: false, error: 'control session service unavailable' });
        return;
    }

    const failureState = getControlAuthFailureState(ip, Date.now());
    if (failureState.lockedUntil && Date.now() < failureState.lockedUntil) {
        const retryAfterSeconds = Math.max(1, Math.ceil((failureState.lockedUntil - Date.now()) / 1000));
        if (Date.now() - failureState.lastLogAt > 3000) {
            console.warn(
                '控制台鉴权拒绝: ip=%s locked_remaining=%ds path=%s',
                ip,
                retryAfterSeconds,
                req.path
            );
            failureState.lastLogAt = Date.now();
            controlAuthFailures.set(ip, failureState);
        }
        res.setHeader('Retry-After', String(retryAfterSeconds));
        res.status(429).send('Too many authentication failures');
        return;
    }

    if (wantsHtml(req)) {
        res.redirect(302, `/control-login.html?next=${encodeURIComponent(req.originalUrl || '/control.html')}`);
        return;
    }
    res.status(401).json({ ok: false, error: 'authentication required' });
}

app.use(express.json({
    verify: (req, res, buf) => {
        req.rawBody = Buffer.from(buf);
    }
}));

app.use((req, res, next) => {
    res.setHeader('Referrer-Policy', 'no-referrer');
    next();
});

app.use(requireControlAuth);

app.use(async (req, res, next) => {
    const bootstrap = String((req.query && req.query.bootstrap) || '').trim();
    if (req.method !== 'GET' || req.path !== '/' || !bootstrap) {
        next();
        return;
    }
    try {
        const response = await apiRequest(
            'POST',
            '/api/v1/device-sessions/avatar-bootstrap/consume',
            { token: bootstrap },
            {},
            { timeoutMs: 10000 }
        );
        const data = response.data || {};
        const sessionToken = String(data.sessionToken || '');
        const expiresAt = Number(data.expiresAt) * 1000;
        if (!sessionToken || !data.tenantId || !data.deviceId || !Number.isFinite(expiresAt)) {
            throw new Error('invalid avatar bootstrap response');
        }
        cacheAvatarSession(sessionToken, {
            tenantId: data.tenantId,
            deviceId: data.deviceId,
            expiresAt
        });
        setAvatarSessionCookie(req, res, sessionToken, expiresAt);
        const query = new URLSearchParams(req.query || {});
        query.delete('bootstrap');
        const target = query.toString() ? `/?${query.toString()}` : '/';
        console.log(`Avatar bootstrap consumed: tenant=${data.tenantId} device=${data.deviceId}`);
        res.redirect(303, target);
    } catch (err) {
        console.error('Avatar bootstrap failed:', err.message || err);
        res.status(401).send('数字人设备会话无效或已过期，请从客户端重新启动。');
    }
});

app.get('/healthz', (req, res) => {
    res.json({ ok: true, service: 'avatar' });
});

app.get(['/download/client', '/download/client.zip'], (req, res) => {
    let stat = null;
    try {
        stat = fs.statSync(CLIENT_DOWNLOAD_FILE);
    } catch (err) {
        console.warn(
            'Client download unavailable: path=%s error=%s',
            CLIENT_DOWNLOAD_FILE,
            err.message || err
        );
        res.status(404).send('客户端安装包暂未发布，请稍后再试。');
        return;
    }
    if (!stat.isFile() || stat.size <= 0) {
        console.warn(
            'Client download invalid: path=%s size=%s',
            CLIENT_DOWNLOAD_FILE,
            stat.size || 0
        );
        res.status(404).send('客户端安装包暂未发布，请稍后再试。');
        return;
    }
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Type', 'application/zip');
    res.download(CLIENT_DOWNLOAD_FILE, CLIENT_DOWNLOAD_NAME, (err) => {
        if (err && !res.headersSent) {
            res.status(500).send('客户端下载失败。');
        }
        if (err) {
            console.warn(
                'Client download failed: ip=%s path=%s error=%s',
                getClientIp(req),
                CLIENT_DOWNLOAD_FILE,
                err.message || err
            );
        }
    });
});

app.use((req, res, next) => {
    if (
        req.method === 'GET'
        && (
            req.path === '/'
            || req.path === '/index.html'
        )
    ) {
        if (AVATAR_PUBLIC_DISPLAY_ENABLED) {
            next();
            return;
        }
        requireAvatarDevice(req, res, next);
        return;
    }
    next();
});

app.use('/models', express.static(path.join(STATIC_DIR, 'models')));
app.use('/lib', express.static(path.join(STATIC_DIR, 'lib')));
app.use('/node_modules', express.static(path.join(STATIC_DIR, 'node_modules')));
app.get(['/super-admin.html', '/super-admin.js', '/super-admin.css'], requirePlatformControl, (req, res, next) => {
    next();
});
app.use(express.static(STATIC_DIR, {
    setHeaders: (res, filePath) => {
        if (filePath.endsWith('.html') || filePath.endsWith('.js')) {
            res.setHeader('Cache-Control', 'no-cache');
        }
    }
}));

app.get('/control-auth/status', async (req, res) => {
    try {
        const session = await resolveControlSession(req);
        res.json({
            ok: true,
            authenticated: Boolean(session),
            authEnabled: CONTROL_AUTH_ENABLED,
            session: session ? controlSessionPayload(session) : null
        });
    } catch (err) {
        console.error('控制台会话状态读取失败: error=%s', err.message || err);
        res.status(503).json({ ok: false, error: 'control session service unavailable' });
    }
});

app.post('/control-auth/login', async (req, res) => {
    if (!CONTROL_AUTH_ENABLED) {
        const session = await resolveControlSession(req);
        res.json({
            ok: true,
            authenticated: true,
            authEnabled: false,
            session: controlSessionPayload(session)
        });
        return;
    }

    const ip = getClientIp(req);
    const failureState = getControlAuthFailureState(ip, Date.now());
    if (failureState.lockedUntil && Date.now() < failureState.lockedUntil) {
        const retryAfterSeconds = Math.max(1, Math.ceil((failureState.lockedUntil - Date.now()) / 1000));
        res.setHeader('Retry-After', String(retryAfterSeconds));
        res.status(429).json({
            ok: false,
            error: 'too many authentication failures',
            retryAfterSeconds
        });
        return;
    }

    const tenantId = String((req.body && req.body.tenantId) || '').trim();
    const username = String((req.body && req.body.username) || '');
    const password = String((req.body && req.body.password) || '');
    if (!tenantId || !username || !password) {
        res.status(400).json({ ok: false, error: 'tenant, username and password are required' });
        return;
    }
    try {
        const response = await signedApiRequest(
            'POST',
            '/api/v1/tenant-admin/login',
            { tenant_id: tenantId, username, password },
            { timeoutMs: 15000 }
        );
        const data = response.data || {};
        const session = { token: String(data.sessionToken || ''), ...data };
        if (!session.token || !session.tenantId || !session.accountId) {
            throw new Error('invalid tenant admin login response');
        }
        clearControlAuthFailures(ip);
        cacheControlSession(session.token, session);
        setControlSessionCookie(req, res, session);
        console.info('租户控制台登录成功: ip=%s tenant=%s user=%s', ip, session.tenantId, username);
        res.json({
            ok: true,
            authenticated: true,
            session: controlSessionPayload(session)
        });
        return;
    } catch (err) {
        console.warn('租户控制台登录失败: ip=%s tenant=%s user=%s error=%s', ip, tenantId, username, err.message || err);
        if (err && Number(err.statusCode) >= 500) {
            res.status(503).json({ ok: false, error: 'tenant authentication service unavailable' });
            return;
        }
    }

    const state = recordControlAuthFailure(ip, req);
    res.status(state.lockedUntil && Date.now() < state.lockedUntil ? 429 : 401).json({
        ok: false,
        error: 'invalid username or password',
        attempts: state.count,
        maxAttempts: CONTROL_AUTH_MAX_FAILURES,
        lockedUntil: state.lockedUntil || 0
    });
});

async function logoutControlSession(req, res) {
    const token = getControlSessionToken(req);
    if (token) {
        try {
            await apiRequest(
                'POST',
                '/api/v1/tenant-admin/logout',
                null,
                { 'X-Tenant-Admin-Session': token },
                { timeoutMs: 10000 }
            );
        } catch (err) {
            console.warn('租户控制台云端会话撤销失败: error=%s', err.message || err);
        }
        controlSessions.delete(token);
    }
    clearControlSessionCookie(req, res);
}

app.post('/control-auth/logout', async (req, res) => {
    await logoutControlSession(req, res);
    res.json({ ok: true });
});

app.get('/control-auth/logout', async (req, res) => {
    await logoutControlSession(req, res);
    res.redirect(302, '/control-login.html');
});

app.get('/tenant/devices', async (req, res) => {
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            '/api/v1/tenant-admin/devices',
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || [] });
    } catch (err) {
        console.error('租户设备列表读取失败: tenant=%s error=%s', req.controlSession.tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/tenant/devices/:deviceId/status', async (req, res) => {
    const deviceId = String((req.params && req.params.deviceId) || '').trim();
    const status = String((req.body && req.body.status) || '').trim();
    if (!deviceId || !['active', 'revoked'].includes(status)) {
        res.status(400).json({ ok: false, error: 'deviceId and valid status are required' });
        return;
    }
    try {
        const apiPath = `/api/v1/tenant-admin/devices/${encodeURIComponent(deviceId)}/status`;
        const response = await tenantAdminApiRequest(
            req,
            'POST',
            apiPath,
            { status },
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error(
            '租户设备状态修改失败: tenant=%s device=%s error=%s',
            req.controlSession.tenantId,
            deviceId,
            err.message || err
        );
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/tenant/avatar-persona', async (req, res) => {
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            '/api/v1/tenant-admin/avatar-persona',
            null,
            { timeoutMs: 10000 }
        );
        res.json({ ok: true, data: response.data || {} });
    } catch (err) {
        console.error(
            '租户数字人人设读取失败: tenant=%s error=%s',
            req.controlSession.tenantId,
            err.message || err
        );
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.put('/tenant/avatar-persona', async (req, res) => {
    const body = req.body || {};
    const payload = {
        assistantName: String(body.assistantName || '').trim(),
        personality: String(body.personality || '').trim(),
        speakingTone: String(body.speakingTone || '').trim(),
        extraInstructions: String(body.extraInstructions || '').trim(),
        wakeAliases: Array.isArray(body.wakeAliases) ? body.wakeAliases : []
    };
    try {
        const response = await tenantAdminApiRequest(
            req,
            'PUT',
            '/api/v1/tenant-admin/avatar-persona',
            payload,
            { timeoutMs: 30000 }
        );
        res.json({ ok: true, data: response.data || {} });
    } catch (err) {
        console.error(
            '租户数字人人设保存失败: tenant=%s error=%s',
            req.controlSession.tenantId,
            err.message || err
        );
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/tenant/avatar-persona/quote-status', async (req, res) => {
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            '/api/v1/tenant-admin/avatar-persona/quote-status',
            null,
            { timeoutMs: 10000 }
        );
        res.json({ ok: true, data: response.data || {} });
    } catch (err) {
        console.error(
            '租户数字人人设语录状态读取失败: tenant=%s error=%s',
            req.controlSession.tenantId,
            err.message || err
        );
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/tts', requireAvatarDevice, (req, res) => {
    const type = req.query.type || 'check_in';
    const name = req.query.name || '访客';
    const voice = resolveTtsVoice(req.query.model || req.query.voice);
    const tenantId = req.avatarSession.tenantId;
    const variant = Number.isInteger(Number(req.query.variant))
        ? Math.max(0, Number(req.query.variant))
        : Math.floor(Math.random() * 6);

    if (!fs.existsSync(CACHE_DIR)) {
        fs.mkdirSync(CACHE_DIR, { recursive: true });
    }

    const cacheFile = getTtsCacheFile(name, type, variant, tenantId, voice);

    if (fs.existsSync(cacheFile) && fs.statSync(cacheFile).size > 0) {
        return res.sendFile(cacheFile);
    }
    if (fs.existsSync(cacheFile)) {
        fs.rmSync(cacheFile, { force: true });
    }

    execFile(PYTHON_BIN, [TTS_SCRIPT, '--tenant-id', tenantId, name, type, cacheFile, String(variant), voice], { cwd: ROOT_DIR }, (err, stdout, stderr) => {
        if (err) {
            console.error('TTS error: tenant=%s provider=%s error=%s', tenantId, FIXED_TTS_PROVIDER, stderr || err.message);
            return res.status(500).json({ error: 'TTS generation failed' });
        }
        if (fs.existsSync(cacheFile)) {
            res.sendFile(cacheFile);
        } else {
            res.status(500).json({ error: 'TTS file not found' });
        }
    });
});

app.get('/tts-raw', requireAvatarDevice, (req, res) => {
    const text = String(req.query.text || '').trim();
    const voice = resolveTtsVoice(req.query.model || req.query.voice);
    const tenantId = req.avatarSession.tenantId;
    if (!text) {
        return res.status(400).json({ error: 'text is required' });
    }
    if (text.length > 500) {
        return res.status(400).json({ error: 'text is too long' });
    }
    if (!fs.existsSync(CACHE_DIR)) {
        fs.mkdirSync(CACHE_DIR, { recursive: true });
    }

    const cacheFile = RAW_TTS_CACHE_ENABLED
        ? getRawTtsCacheFile(text, tenantId, voice)
        : getRawTtsTempFile(tenantId, voice);
    if (RAW_TTS_CACHE_ENABLED && fs.existsSync(cacheFile) && fs.statSync(cacheFile).size > 0) {
        return res.sendFile(cacheFile);
    }

    const child = execFile(PYTHON_BIN, [TTS_SCRIPT, '--tenant-id', tenantId, '--raw', text, cacheFile, voice], { cwd: ROOT_DIR }, (err, stdout, stderr) => {
        if (res.writableEnded || res.destroyed) {
            return;
        }
        if (err && err.killed) {
            console.info('Raw TTS generation cancelled: tenant=%s provider=%s', tenantId, FIXED_TTS_PROVIDER);
            if (!RAW_TTS_CACHE_ENABLED) {
                fs.rm(cacheFile, { force: true }, () => { });
            }
            return;
        }
        if (err) {
            console.error('Raw TTS error: tenant=%s provider=%s error=%s', tenantId, FIXED_TTS_PROVIDER, stderr || err.message);
            if (!RAW_TTS_CACHE_ENABLED) {
                fs.rm(cacheFile, { force: true }, () => { });
            }
            return res.status(500).json({ error: 'TTS generation failed' });
        }
        if (fs.existsSync(cacheFile) && fs.statSync(cacheFile).size > 0) {
            res.sendFile(cacheFile, () => {
                if (!RAW_TTS_CACHE_ENABLED) {
                    fs.rm(cacheFile, { force: true }, () => { });
                }
            });
        } else {
            res.status(500).json({ error: 'TTS file not found' });
        }
    });
    req.on('aborted', () => {
        if (!res.writableEnded && child && !child.killed) {
            console.info('Raw TTS client aborted; killing generation: tenant=%s provider=%s', tenantId, FIXED_TTS_PROVIDER);
            child.kill();
        }
        if (!RAW_TTS_CACHE_ENABLED) {
            fs.rm(cacheFile, { force: true }, () => { });
        }
    });
});

app.get('/tts-raw-stream', requireAvatarDevice, (req, res) => {
    const text = String(req.query.text || '').trim();
    const voice = resolveTtsVoice(req.query.model || req.query.voice);
    const tenantId = req.avatarSession.tenantId;
    if (!text) {
        return res.status(400).json({ error: 'text is required' });
    }
    if (text.length > 500) {
        return res.status(400).json({ error: 'text is too long' });
    }

    const startedAt = Date.now();
    res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Accel-Buffering', 'no');
    if (typeof res.flushHeaders === 'function') {
        res.flushHeaders();
    }

    const child = spawn(
        PYTHON_BIN,
        [TTS_SCRIPT, '--tenant-id', tenantId, '--raw', '--stream', text, voice],
        { cwd: ROOT_DIR, stdio: ['ignore', 'pipe', 'pipe'] }
    );
    let stderr = '';
    let stdoutBytes = 0;
    let cancelled = false;

    console.info(
        'Raw TTS stream started: tenant=%s provider=%s voice=%s chars=%s',
        tenantId,
        FIXED_TTS_PROVIDER,
        voice,
        text.length
    );

    child.stdout.on('data', (chunk) => {
        stdoutBytes += chunk.length;
        if (!res.writableEnded && !res.destroyed) {
            res.write(chunk);
        }
    });
    child.stderr.on('data', (chunk) => {
        stderr += chunk.toString('utf8');
        if (stderr.length > 4000) {
            stderr = stderr.slice(-4000);
        }
    });
    child.on('error', (err) => {
        if (res.writableEnded || res.destroyed) {
            return;
        }
        console.error('Raw TTS stream spawn error: tenant=%s provider=%s error=%s', tenantId, FIXED_TTS_PROVIDER, err.message);
        res.write(JSON.stringify({ type: 'error', error: 'TTS stream failed' }) + '\n');
        res.end();
    });
    child.on('close', (code, signal) => {
        if (res.writableEnded || res.destroyed) {
            return;
        }
        if (cancelled || signal) {
            console.info(
                'Raw TTS stream cancelled: tenant=%s provider=%s signal=%s elapsedMs=%s',
                tenantId,
                FIXED_TTS_PROVIDER,
                signal || '',
                Date.now() - startedAt
            );
            return res.end();
        }
        if (code !== 0) {
            console.error(
                'Raw TTS stream error: tenant=%s provider=%s code=%s elapsedMs=%s error=%s',
                tenantId,
                FIXED_TTS_PROVIDER,
                code,
                Date.now() - startedAt,
                stderr || 'unknown'
            );
            res.write(JSON.stringify({ type: 'error', error: 'TTS stream failed' }) + '\n');
            return res.end();
        }
        console.info(
            'Raw TTS stream finished: tenant=%s provider=%s bytes=%s elapsedMs=%s',
            tenantId,
            FIXED_TTS_PROVIDER,
            stdoutBytes,
            Date.now() - startedAt
        );
        res.end();
    });
    req.on('aborted', () => {
        cancelled = true;
        if (child && !child.killed) {
            console.info('Raw TTS stream client aborted; killing generation: tenant=%s provider=%s', tenantId, FIXED_TTS_PROVIDER);
            child.kill();
        }
    });
});

app.post('/dialog/chat', requireAvatarDevice, async (req, res) => {
    const text = String((req.body && req.body.text) || '').trim();
    if (!text) {
        return res.status(400).json({ ok: false, error: 'text is required' });
    }
    try {
        const startedAt = Date.now();
        const data = await tenantApiRequest(req, 'POST', '/api/v1/dialog/chat', { text });
        res.json({
            ok: true,
            data: data.data,
            elapsedMs: Date.now() - startedAt
        });
    } catch (err) {
        console.error('Dialog chat failed:', err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/dialog/scene-reply', requireAvatarDevice, async (req, res) => {
    const body = req.body || {};
    const scene = String(body.scene || '').trim();
    if (!scene) {
        return res.status(400).json({ ok: false, error: 'scene is required' });
    }
    const payload = {
        scene,
        userText: String(body.userText || body.user_text || '').trim(),
        requiredFacts: Array.isArray(body.requiredFacts || body.required_facts)
            ? (body.requiredFacts || body.required_facts).map((item) => String(item || '').trim()).filter(Boolean)
            : [],
        responseGoal: String(body.responseGoal || body.response_goal || '').trim(),
        constraints: Array.isArray(body.constraints)
            ? body.constraints.map((item) => String(item || '').trim()).filter(Boolean)
            : [],
        context: Array.isArray(body.context) ? body.context : [],
        userInfo: body.userInfo && typeof body.userInfo === 'object' ? body.userInfo : {}
    };
    try {
        const startedAt = Date.now();
        const data = await tenantApiRequest(req, 'POST', '/api/v1/dialog/scene-reply', payload);
        res.json({
            ok: true,
            data: data.data,
            elapsedMs: Date.now() - startedAt
        });
    } catch (err) {
        console.error('Dialog scene reply failed:', err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/tts-text', requireAvatarDevice, (req, res) => {
    const name = req.query.name || '访客';
    const type = req.query.type || 'check_in';
    const variant = Number.isInteger(Number(req.query.variant))
        ? Math.max(0, Number(req.query.variant))
        : 0;

    execFile(
        PYTHON_BIN,
        [TTS_SCRIPT, name, type, '--print-text', String(variant)],
        { cwd: ROOT_DIR, encoding: 'utf8' },
        (err, stdout, stderr) => {
            if (err) {
                console.error('TTS text error:', stderr || err.message);
                return res.status(500).json({ error: 'TTS text failed' });
            }
            res.json({ text: stdout.trim() });
        }
    );
});

app.get('/tts-manifest', requireAvatarDevice, async (req, res) => {
    const manifest = await loadTtsManifest();
    res.json(manifest);
});

app.get('/tts-voices', requireAvatarDevice, (req, res) => {
    res.json({
        defaultVoice: TTS_VOICE_BY_MODEL.epsilon,
        byModel: TTS_VOICE_BY_MODEL,
        voices: TTS_VOICES,
        fixedProvider: FIXED_TTS_PROVIDER,
        fixedVoices: fixedTtsVoiceKeys(),
        cacheExtension: fixedTtsCacheExtension()
    });
});

app.get('/dialog-settings', requireAvatarDevice, async (req, res) => {
    const mode = getInteractionMode();
    const modeConfig = getInteractionModeConfig(mode);
    const avatarSession = req.avatarSession;
    let persona = null;
    try {
        const response = await apiRequest(
            'GET',
            '/api/v1/avatar/persona',
            null,
            { 'X-Avatar-Session': avatarSession.token },
            { timeoutMs: 5000 }
        );
        persona = response.data || null;
    } catch (err) {
        console.warn('数字人人设读取失败，dialog-settings 使用默认展示: tenant=%s error=%s', avatarSession.tenantId, err.message || err);
    }
    res.set('Cache-Control', 'no-store');
    res.json({
        avatarSessionValid: true,
        priorityMode: DIALOG_CHAT_PRIORITY_MODE,
        interactionMode: mode,
        realtimeDialogEnabled: Boolean(modeConfig.realtimeDialog),
        realtimeRagEnabled: Boolean(modeConfig.realtimeRag),
        voiceBackend: VOICE_PIPELINE_BACKEND,
        voiceClientVadSilenceMs: VOICE_PIPELINE_BACKEND === 'omni'
            ? VOICE_PIPELINE_CLIENT_VAD_FALLBACK_MS
            : 1400,
        fixedSpeechNoiseGuardEnabled: FIXED_SPEECH_NOISE_GUARD_ENABLED,
        fixedSpeechPostGuardMs: FIXED_SPEECH_POST_GUARD_MS,
        deviceId: avatarSession.deviceId,
        tenantId: avatarSession.tenantId,
        siteId: SITE_ID,
        avatarPersona: persona,
        voiceStreamUrl: VOICE_PIPELINE_ENABLED
            ? resolveVoiceStreamUrl(req)
            : ''
    });
});

app.post('/voice-ticket', requireAvatarDevice, async (req, res) => {
    try {
        const avatarSession = req.avatarSession;
        const clientId = String(req.get('X-Avatar-Client-Id') || '').trim().slice(0, 80);
        const activeCheck = getActiveAvatarHttpClientCheck(
            avatarSession.tenantId,
            avatarSession.deviceId,
            clientId
        );
        if (!activeCheck.allowed) {
            console.warn(
                'Voice ticket rejected for inactive avatar: tenant=%s device=%s client=%s active=%s reason=%s',
                avatarSession.tenantId,
                avatarSession.deviceId,
                clientId || '(missing)',
                activeCheck.activeClientId || '(none)',
                activeCheck.reason
            );
            return res.status(409).json({
                ok: false,
                error: 'inactive avatar client cannot start voice turn',
                reason: activeCheck.reason
            });
        }
        const response = await tenantApiRequest(req, 'POST', '/api/v1/dialog/voice-ticket', {
            deviceId: avatarSession.deviceId
        });
        res.json(response);
    } catch (err) {
        console.error('Voice ticket request failed:', err.message);
        res.status(Number(err.statusCode) || 502).json({ ok: false, error: err.message });
    }
});

function getActiveAvatarHttpClientCheck(tenantId, deviceId, clientId) {
    const active = activeAvatarClients.get(tenantId);
    if (!active || active.readyState !== WebSocket.OPEN) {
        return { allowed: true, reason: 'no_active_avatar' };
    }
    const meta = wsClientMeta.get(active) || {};
    if (deviceId && meta.deviceId && meta.deviceId !== deviceId) {
        return {
            allowed: false,
            reason: 'active_device_mismatch',
            activeClientId: meta.clientId || ''
        };
    }
    if (!clientId) {
        return {
            allowed: false,
            reason: 'missing_client_id',
            activeClientId: meta.clientId || ''
        };
    }
    if (meta.clientId && meta.clientId !== clientId) {
        return {
            allowed: false,
            reason: 'inactive_client',
            activeClientId: meta.clientId || ''
        };
    }
    return {
        allowed: true,
        reason: 'active_client',
        activeClientId: meta.clientId || ''
    };
}

app.get('/platform-admin/clients', requirePlatformControl, async (req, res) => {
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            '/api/v1/platform-admin/clients',
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || [] });
    } catch (err) {
        console.error('平台客户端列表读取失败: error=%s', err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/platform-admin/clients', requirePlatformControl, async (req, res) => {
    try {
        const response = await tenantAdminApiRequest(
            req,
            'POST',
            '/api/v1/platform-admin/clients',
            req.body || {},
            { timeoutMs: 20000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台客户端创建失败: error=%s', err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.delete('/platform-admin/clients/:tenantId', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    if (!tenantId) {
        res.status(400).json({ ok: false, error: 'tenantId is required' });
        return;
    }
    try {
        const apiPath = `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}`;
        const response = await tenantAdminApiRequest(
            req,
            'DELETE',
            apiPath,
            req.body || {},
            { timeoutMs: 20000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台客户端删除失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/platform-admin/clients/:tenantId/admins', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/admins`,
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || [] });
    } catch (err) {
        console.error('平台客户端管理员列表读取失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/platform-admin/clients/:tenantId/admins/password', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'POST',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/admins/password`,
            req.body || {},
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台客户端管理员密码重置失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/platform-admin/clients/:tenantId/activations', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/activations`,
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || [] });
    } catch (err) {
        console.error('平台客户端激活码列表读取失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/platform-admin/clients/:tenantId/activations', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'POST',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/activations`,
            req.body || {},
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台客户端激活码创建失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.delete('/platform-admin/clients/:tenantId/activations/:activationId', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    const activationId = String((req.params && req.params.activationId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'DELETE',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/activations/${encodeURIComponent(activationId)}`,
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台客户端激活码删除失败: tenant=%s activation=%s error=%s', tenantId, activationId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/platform-admin/clients/:tenantId/devices', requirePlatformControl, async (req, res) => {
    const tenantId = String((req.params && req.params.tenantId) || '').trim();
    try {
        const response = await tenantAdminApiRequest(
            req,
            'GET',
            `/api/v1/platform-admin/clients/${encodeURIComponent(tenantId)}/devices`,
            null,
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || [] });
    } catch (err) {
        console.error('平台客户端设备列表读取失败: tenant=%s error=%s', tenantId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/platform-admin/devices/:deviceId/status', requirePlatformControl, async (req, res) => {
    const deviceId = String((req.params && req.params.deviceId) || '').trim();
    const status = String((req.body && req.body.status) || '').trim();
    if (!deviceId || !['active', 'revoked'].includes(status)) {
        res.status(400).json({ ok: false, error: 'deviceId and valid status are required' });
        return;
    }
    try {
        const response = await tenantAdminApiRequest(
            req,
            'POST',
            `/api/v1/platform-admin/devices/${encodeURIComponent(deviceId)}/status`,
            { status },
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台设备状态修改失败: device=%s error=%s', deviceId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.delete('/platform-admin/devices/:deviceId', requirePlatformControl, async (req, res) => {
    const deviceId = String((req.params && req.params.deviceId) || '').trim();
    if (!deviceId) {
        res.status(400).json({ ok: false, error: 'deviceId is required' });
        return;
    }
    try {
        const response = await tenantAdminApiRequest(
            req,
            'DELETE',
            `/api/v1/platform-admin/devices/${encodeURIComponent(deviceId)}`,
            req.body || {},
            { timeoutMs: 15000 }
        );
        res.json({ ok: true, data: response.data || response });
    } catch (err) {
        console.error('平台注册设备删除失败: device=%s error=%s', deviceId, err.message || err);
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/interaction-mode', requirePlatformControl, (req, res) => {
    const mode = getInteractionMode();
    res.json({
        ok: true,
        mode,
        modes: INTERACTION_MODES
    });
});

app.post('/interaction-mode', requirePlatformControl, (req, res) => {
    const mode = normalizeInteractionMode(req.body && req.body.mode);
    try {
        fs.mkdirSync(path.dirname(INTERACTION_MODE_FILE), { recursive: true });
        const tmpFile = `${INTERACTION_MODE_FILE}.${process.pid}.tmp`;
        fs.writeFileSync(tmpFile, JSON.stringify({ mode }, null, 2), 'utf8');
        fs.renameSync(tmpFile, INTERACTION_MODE_FILE);
        broadcast({
            type: 'interaction_mode_changed',
            mode,
            modes: INTERACTION_MODES
        });
        res.json({
            ok: true,
            mode,
            modes: INTERACTION_MODES
        });
    } catch (err) {
        console.error('Interaction mode write failed:', err.message || err);
        res.status(500).json({ ok: false, error: 'interaction mode write failed' });
    }
});

app.get('/dialog-audio-lock', requireAvatarStateAuth, (req, res) => {
    res.json(tenantAvatarState.getAudioLock(req.avatarSession));
});

app.get('/gesture/status', requirePlatformControl, (req, res) => {
    res.json(readGestureStatus());
});

app.post('/dialog-audio-lock', requireAvatarStateAuth, (req, res) => {
    const snapshot = tenantAvatarState.updateAudioLock(
        req.avatarSession,
        req.body || {}
    );
    res.json({ ok: true, ...snapshot });
});

app.get('/tts-prewarm-status', requireAvatarDevice, (req, res) => {
    res.json(prewarmStatus);
});

app.get('/avatar-ready', requireAvatarStateAuth, (req, res) => {
    res.json(tenantAvatarState.getReadyState(req.avatarSession));
});

app.post('/avatar-ready', requireAvatarStateAuth, (req, res) => {
    const state = tenantAvatarState.updateReadyState(
        req.avatarSession,
        req.body || {}
    );
    res.json({ ok: true, ...state });
});

app.post('/client-log', requireAvatarDevice, (req, res) => {
    const body = req.body || {};
    console.log('Client log:', {
        tenantId: req.avatarSession.tenantId,
        deviceId: req.avatarSession.deviceId,
        scope: String(body.scope || 'avatar'),
        message: String(body.message || ''),
        detail: body.detail || null,
        at: new Date().toISOString()
    });
    res.json({ ok: true });
});

app.get('/faces/capture-status', (req, res) => {
    const status = tenantStatus(
        faceCaptureStatuses,
        req.controlSession.tenantId,
        createFaceCaptureStatus
    );
    res.json({ ok: true, ...status });
});

app.post('/faces/capture', async (req, res) => {
    const status = tenantStatus(
        faceCaptureStatuses,
        req.controlSession.tenantId,
        createFaceCaptureStatus
    );
    if (status.running) {
        return res.status(409).json({
            ok: false,
            error: `${status.name || '上一位员工'}的人脸注册仍在进行中`,
            status
        });
    }

    let name = '';
    const deviceId = String((req.body && req.body.deviceId) || '').trim();
    try {
        name = normalizeCaptureEmployeeName(req.body && req.body.name);
        if (!deviceId) throw new Error('请选择执行人脸采集的在线设备');
    } catch (err) {
        return res.status(400).json({ ok: false, error: err.message || String(err) });
    }

    try {
        const task = await createFaceCaptureClientTask(req, name, deviceId);
        Object.assign(status, {
            running: false,
            name,
            deviceId,
            startedAt: new Date().toISOString(),
            finishedAt: '',
            clientTaskId: task.id || '',
            clientTaskDispatched: true,
            exitCode: null,
            error: '',
            stdout: `已下发到企业设备执行，人脸录入窗口会在客户端电脑打开。task=${task.id || ''}`,
            stderr: ''
        });
        res.status(202).json({ ok: true, status, task });
    } catch (err) {
        Object.assign(status, {
            running: false,
            name,
            deviceId,
            finishedAt: new Date().toISOString(),
            clientTaskId: '',
            clientTaskDispatched: false,
            exitCode: 1,
            error: err.message || String(err),
            stdout: '',
            stderr: ''
        });
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: status.error, status });
    }
});

app.post('/avatar/faces/capture', requireAvatarDevice, async (req, res) => {
    const avatarSession = req.avatarSession;
    const status = tenantStatus(
        faceCaptureStatuses,
        avatarSession.tenantId,
        createFaceCaptureStatus
    );
    if (status.running) {
        return res.status(409).json({
            ok: false,
            error: `${status.name || '上一位员工'}的人脸注册仍在进行中`,
            status
        });
    }

    let name = '';
    const deviceId = avatarSession.deviceId;
    try {
        name = normalizeCaptureEmployeeName(req.body && req.body.name);
        if (!deviceId) throw new Error('当前数字人设备会话缺少 device_id，请从客户端重新打开数字人页面');
    } catch (err) {
        return res.status(400).json({ ok: false, error: err.message || String(err) });
    }

    try {
        const task = await createAvatarFaceCaptureClientTask(req, name, deviceId);
        Object.assign(status, {
            running: false,
            name,
            deviceId,
            startedAt: new Date().toISOString(),
            finishedAt: '',
            clientTaskId: task.id || '',
            clientTaskDispatched: true,
            exitCode: null,
            error: '',
            stdout: `已下发到当前数字人客户端执行，人脸录入窗口会打开。task=${task.id || ''}`,
            stderr: ''
        });
        console.info(
            '数字人浏览器已下发人脸录入任务: tenant=%s device=%s name=%s task=%s',
            avatarSession.tenantId,
            deviceId,
            name,
            task.id || ''
        );
        res.status(202).json({ ok: true, status, task });
    } catch (err) {
        Object.assign(status, {
            running: false,
            name,
            deviceId,
            finishedAt: new Date().toISOString(),
            clientTaskId: '',
            clientTaskDispatched: false,
            exitCode: 1,
            error: err.message || String(err),
            stdout: '',
            stderr: ''
        });
        res.status(Number(err.statusCode) || 500).json({ ok: false, error: status.error, status });
    }
});

app.get('/daily-tts/status', requirePlatformControl, (req, res) => {
    res.json({ ok: true, ...dailyTtsStatus });
});

app.post('/daily-tts/generate', requirePlatformControl, (req, res) => {
    if (dailyTtsStatus.running) {
        return res.status(409).json({
            ok: false,
            error: '今日语录正在生成中',
            status: dailyTtsStatus
        });
    }
    startDailyTtsGeneration();
    res.status(202).json({ ok: true, status: dailyTtsStatus });
});

app.get('/knowledge/stats', async (req, res) => {
    try {
        const data = await tenantAdminApiRequest(req, 'GET', '/api/v1/knowledge/stats', null, { timeoutMs: 30000 });
        res.json({ ok: true, data: data.data || data });
    } catch (err) {
        console.error('Knowledge stats failed:', err.message || err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/knowledge/index', async (req, res) => {
    const reset = Boolean(req.body && req.body.reset);
    const paths = Array.isArray(req.body && req.body.paths)
        ? req.body.paths.map((item) => String(item || '').trim()).filter(Boolean)
        : null;
    const status = tenantStatus(
        knowledgeIndexStatuses,
        req.controlSession.tenantId,
        createKnowledgeIndexStatus
    );
    if (status.running) {
        return res.status(409).json({
            ok: false,
            error: '知识库索引正在重建中',
            status
        });
    }
    startKnowledgeIndex(req.controlSession, status, reset, paths && paths.length ? paths : null);
    res.status(202).json({ ok: true, status });
});

app.get('/knowledge/index-status', (req, res) => {
    const status = tenantStatus(
        knowledgeIndexStatuses,
        req.controlSession.tenantId,
        createKnowledgeIndexStatus
    );
    res.json({ ok: true, ...status });
});

app.post('/knowledge/search', async (req, res) => {
    const query = String((req.body && req.body.query) || '').trim();
    const topK = normalizeTopK(req.body && req.body.topK);
    const minScore = normalizeMinScore(req.body && req.body.minScore);
    if (!query) {
        return res.status(400).json({ ok: false, error: 'query is required' });
    }
    try {
        const data = await tenantAdminApiRequest(
            req,
            'POST',
            '/api/v1/knowledge/search',
            { query, top_k: topK, min_score: minScore },
            { timeoutMs: 60000 }
        );
        res.json({ ok: true, data: data.data || [] });
    } catch (err) {
        console.error('Knowledge search failed:', err.message || err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/knowledge/ask', async (req, res) => {
    const question = String((req.body && req.body.question) || '').trim();
    const topK = normalizeTopK(req.body && req.body.topK);
    if (!question) {
        return res.status(400).json({ ok: false, error: 'question is required' });
    }
    try {
        const data = await tenantAdminApiRequest(
            req,
            'POST',
            '/api/v1/knowledge/ask',
            { question, top_k: topK },
            { timeoutMs: 90000 }
        );
        res.json({ ok: true, data: data.data || data });
    } catch (err) {
        console.error('Knowledge ask failed:', err.message || err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/employees/sync', async (req, res) => {
    if (!isEmployeeSyncAuthorized(req)) {
        return res.status(401).json({ ok: false, error: 'unauthorized' });
    }

    const names = normalizeEmployeeNames(req.body);
    if (names.length === 0) {
        return res.status(400).json({ ok: false, error: 'name is required' });
    }

    try {
        const manifest = await loadTtsManifest();
        const results = [];
        for (const name of names) {
            const registered = await registerEmployee(name);
            fs.mkdirSync(path.join(EMPLOYEES_DIR, name), { recursive: true });
            const tts = await prewarmEmployeeTts(name, manifest);
            results.push({ name, inserted: registered.inserted, tts });
        }
        res.json({ ok: true, results });
    } catch (err) {
        console.error('Employee sync failed:', err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.post('/employees/enroll-local', async (req, res) => {
    if (!isEmployeeSyncAuthorized(req)) {
        return res.status(401).json({ ok: false, error: 'unauthorized' });
    }

    const name = String((req.body && req.body.name) || '').trim();
    if (!name) {
        return res.status(400).json({ ok: false, error: 'name is required' });
    }

    try {
        const enrollment = await enrollLocalEmployee(req.body);
        const manifest = await loadTtsManifest();
        const tts = await prewarmEmployeeTts(name, manifest);
        res.json({ ok: true, enrollment, tts });
    } catch (err) {
        console.error('Local enrollment failed:', err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.get('/employees', async (req, res) => {
    try {
        const data = await tenantAdminApiRequest(req, 'GET', '/api/v1/employees', null, { timeoutMs: 30000 });
        const employees = data.data || data;
        res.json({
            ok: true,
            names: employees.names || [],
            count: employees.count || 0
        });
    } catch (err) {
        console.error('Employee list failed:', err.message || err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

app.delete('/employees/:name', async (req, res) => {
    const name = String((req.params && req.params.name) || '').trim();
    if (!name) {
        return res.status(400).json({ ok: false, error: 'name is required' });
    }

    try {
        const data = await tenantAdminApiRequest(
            req,
            'DELETE',
            `/api/v1/employees/${encodeURIComponent(name)}`,
            null,
            { timeoutMs: 30000 }
        );
        res.json({ ok: true, ...(data.data || data) });
    } catch (err) {
        console.error('Employee delete failed:', err.message || err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

function safeCachePart(value) {
    return String(value || '访客').replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
}

function normalizeCaptureEmployeeName(value) {
    const name = String(value || '').trim();
    if (!name) {
        throw new Error('name is required');
    }
    if (/[<>:"/\\|?*\x00-\x1F]/.test(name)) {
        throw new Error('name contains invalid path characters');
    }
    return name;
}

async function createFaceCaptureClientTask(req, name, deviceId) {
    const data = await tenantAdminApiRequest(
        req,
        'POST',
        '/api/v1/client-tasks',
        {
            action: 'capture_face_enroll',
            payload: {
                name,
                source: 'avatar_control'
            },
            targetDeviceId: deviceId
        },
        { timeoutMs: 30000 }
    );
    return data.data || data;
}

async function createAvatarFaceCaptureClientTask(req, name, deviceId) {
    const data = await tenantApiRequest(
        req,
        'POST',
        '/api/v1/client-tasks',
        {
            action: 'capture_face_enroll',
            payload: {
                name,
                source: 'avatar_voice_browser'
            },
            targetDeviceId: deviceId
        },
        { timeoutMs: 30000 }
    );
    return data.data || data;
}

function normalizeTopK(value) {
    const topK = Number(value);
    if (!Number.isFinite(topK)) return null;
    return Math.max(1, Math.min(20, Math.floor(topK)));
}

function normalizeMinScore(value) {
    const score = Number(value);
    if (!Number.isFinite(score)) return null;
    return Math.max(0, Math.min(1, score));
}

function startKnowledgeIndex(session, status, reset, paths) {
    status.running = true;
    status.complete = false;
    status.startedAt = new Date().toISOString();
    status.finishedAt = '';
    status.reset = Boolean(reset);
    status.paths = paths;
    status.error = '';
    status.result = null;

    console.log('租户知识库索引开始:', {
        tenant: session.tenantId,
        reset: status.reset,
        paths: status.paths
    });

    tenantAdminApiRequestFromSession(
        session,
        'POST',
        '/api/v1/knowledge/index',
        { paths, reset: Boolean(reset) },
        { timeoutMs: 900000 }
    )
        .then((data) => {
            status.running = false;
            status.complete = true;
            status.finishedAt = new Date().toISOString();
            status.result = data.data || data;
            console.log('租户知识库索引完成: tenant=%s result=%j', session.tenantId, status.result);
        })
        .catch((err) => {
            status.running = false;
            status.complete = true;
            status.finishedAt = new Date().toISOString();
            status.error = err.message || String(err);
            console.error('租户知识库索引失败: tenant=%s error=%s', session.tenantId, err.message || err);
        });
}

function startDailyTtsGeneration() {
    dailyTtsStatus.running = true;
    dailyTtsStatus.complete = false;
    dailyTtsStatus.startedAt = new Date().toISOString();
    dailyTtsStatus.finishedAt = '';
    dailyTtsStatus.error = '';
    dailyTtsStatus.stdout = '';
    dailyTtsStatus.stderr = '';
    dailyTtsStatus.clearedCacheFiles = 0;

    execFile(
        PYTHON_BIN,
        [DAILY_TTS_SCRIPT, '--allow-fallback'],
        {
            cwd: ROOT_DIR,
            encoding: 'utf8',
            timeout: 180000,
            env: {
                ...process.env,
                PYTHONIOENCODING: 'utf-8'
            }
        },
        (err, stdout, stderr) => {
            dailyTtsStatus.running = false;
            dailyTtsStatus.complete = true;
            dailyTtsStatus.finishedAt = new Date().toISOString();
            dailyTtsStatus.stdout = String(stdout || '').slice(-CAPTURE_LOG_LIMIT);
            dailyTtsStatus.stderr = String(stderr || '').slice(-CAPTURE_LOG_LIMIT);

            if (err) {
                dailyTtsStatus.error = stderr || err.message || String(err);
                return;
            }

            try {
                dailyTtsStatus.clearedCacheFiles = clearAvatarTtsCacheFiles();
                requestDailyTtsReload();
            } catch (clearErr) {
                dailyTtsStatus.error = `语录已生成，但刷新旧缓存失败: ${clearErr.message || clearErr}`;
            }
        }
    );
}

function clearAvatarTtsCacheFiles() {
    if (!fs.existsSync(CACHE_DIR)) return 0;
    let count = 0;
    for (const entry of fs.readdirSync(CACHE_DIR, { withFileTypes: true })) {
        if (!entry.isFile()) continue;
        if (!/\.(mp3|wav|ogg)$/i.test(entry.name)) continue;
        fs.rmSync(path.join(CACHE_DIR, entry.name), { force: true });
        count += 1;
    }
    return count;
}

function requestDailyTtsReload() {
    fs.mkdirSync(SHARED_CACHE_DIR, { recursive: true });
    const markerFile = path.join(SHARED_CACHE_DIR, 'daily_tts_reload.json');
    const tmpFile = `${markerFile}.${process.pid}.tmp`;
    fs.writeFileSync(
        tmpFile,
        JSON.stringify({ requestedAt: Date.now() / 1000, source: 'avatar-control' }, null, 2),
        'utf8'
    );
    fs.renameSync(tmpFile, markerFile);
}

function resolveTtsVoice(modelOrVoice = '') {
    const key = String(modelOrVoice || '').trim();
    return TTS_VOICE_BY_MODEL[key] || key || TTS_VOICE_BY_MODEL.epsilon;
}

function fixedTtsCacheExtension() {
    if (FIXED_TTS_PROVIDER === 'edge') return '.mp3';
    return '.wav';
}

function fixedTtsVoiceKeys() {
    return FIXED_TTS_PROVIDER === 'edge' ? TTS_VOICES : ['unified'];
}

function getTtsCacheFile(name, type, variant, tenantId = TENANT_ID, voice = '') {
    return path.join(
        CACHE_DIR,
        [
            safeCachePart(tenantId || TENANT_ID),
            safeCachePart(FIXED_TTS_PROVIDER || 'volc'),
            safeCachePart(name),
            safeCachePart(type),
            safeCachePart(FIXED_TTS_PROVIDER === 'edge' ? resolveTtsVoice(voice) : 'unified'),
            Math.max(0, Number(variant) || 0)
        ].join('_') + fixedTtsCacheExtension()
    );
}

function getRawTtsCacheFile(text, tenantId = TENANT_ID, voice = '') {
    const hash = crypto
        .createHash('sha256')
        .update([
            tenantId || TENANT_ID,
            FIXED_TTS_PROVIDER || 'volc',
            FIXED_TTS_PROVIDER === 'edge' ? resolveTtsVoice(voice) : 'unified',
            REALTIME_DIALOG_OUTPUT_FORMAT,
            text
        ].join('\n'))
        .digest('hex');
    return path.join(CACHE_DIR, `raw_${hash}${fixedTtsCacheExtension()}`);
}

function getRawTtsTempFile(tenantId = TENANT_ID, voice = '') {
    const suffix = crypto.randomBytes(8).toString('hex');
    return path.join(
        CACHE_DIR,
        [
            'raw_tmp',
            safeCachePart(tenantId || TENANT_ID),
            safeCachePart(FIXED_TTS_PROVIDER || 'volc'),
            safeCachePart(FIXED_TTS_PROVIDER === 'edge' ? resolveTtsVoice(voice) : 'unified'),
            Date.now(),
            suffix
        ].join('_') + fixedTtsCacheExtension()
    );
}

function deriveDefaultInteractionMode() {
    if (ENABLE_REALTIME_DIALOG) {
        return REALTIME_DIALOG_RAG_ENABLED ? 'quotes_realtime_rag' : 'quotes_realtime';
    }
    return 'quotes_only';
}

function normalizeInteractionMode(mode) {
    const key = String(mode || '').trim();
    return INTERACTION_MODES.some((item) => item.key === key)
        ? key
        : deriveDefaultInteractionMode();
}

function getInteractionMode() {
    try {
        const data = JSON.parse(fs.readFileSync(INTERACTION_MODE_FILE, 'utf8'));
        return normalizeInteractionMode(data && data.mode);
    } catch (err) {
        return deriveDefaultInteractionMode();
    }
}

function getInteractionModeConfig(mode) {
    const key = normalizeInteractionMode(mode);
    return INTERACTION_MODES.find((item) => item.key === key) || INTERACTION_MODES[0];
}

function readGestureStatus() {
    try {
        const data = readGestureStatusFile();
        const updatedAt = Number(data.updatedAt) || 0;
        gestureStatusCache = {
            ok: data.ok !== false,
            enabled: Boolean(data.enabled),
            running: Boolean(data.running),
            stage: data.stage || '',
            updatedAt,
            stale: updatedAt > 0 ? (Date.now() / 1000 - updatedAt > 3) : true,
            candidate: data.candidate || null,
            stableCandidate: data.stableCandidate || null,
            event: data.event || null,
            error: data.error || ''
        };
        return gestureStatusCache;
    } catch (err) {
        if (gestureStatusCache) {
            return {
                ...gestureStatusCache,
                stale: true
            };
        }
        return {
            ok: true,
            enabled: false,
            running: false,
            stage: '',
            updatedAt: 0,
            stale: true,
            candidate: null,
            stableCandidate: null,
            event: null,
            error: ''
        };
    }
}

function readGestureStatusFile() {
    let lastError = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
            return JSON.parse(fs.readFileSync(GESTURE_STATUS_FILE, 'utf8'));
        } catch (err) {
            lastError = err;
            if (!['EBUSY', 'EPERM', 'ENOENT'].includes(err.code)) {
                throw err;
            }
        }
    }
    throw lastError || new Error('gesture status read failed');
}

function postSignedApi(apiPath, payload) {
    return signedApiRequest('POST', apiPath, payload);
}

async function tenantApiRequest(req, method, apiPath, payload = null, options = {}) {
    const sessionToken = getAvatarSessionToken(req);
    const avatarSession = req.avatarSession || await resolveAvatarSession(req);
    if (avatarSession) {
        return apiRequest(
            method,
            apiPath,
            payload,
            { 'X-Avatar-Session': avatarSession.token },
            options
        );
    }
    const error = new Error(
        sessionToken
            ? 'avatar device session expired; restart CVClient'
            : 'avatar device session required'
    );
    error.statusCode = 401;
    throw error;
}

async function tenantAdminApiRequest(req, method, apiPath, payload = null, options = {}) {
    const session = req.controlSession || await resolveControlSession(req);
    if (!session) {
        const error = new Error('tenant administrator session expired');
        error.statusCode = 401;
        throw error;
    }
    return tenantAdminApiRequestFromSession(session, method, apiPath, payload, options);
}

function tenantAdminApiRequestFromSession(session, method, apiPath, payload = null, options = {}) {
    if (!CONTROL_AUTH_ENABLED || !session.token) {
        return signedApiRequest(method, apiPath, payload, options);
    }
    return apiRequest(
        method,
        apiPath,
        payload,
        { 'X-Tenant-Admin-Session': session.token },
        options
    );
}

function signedApiRequest(method, apiPath, payload = null, options = {}) {
    const body = payload === null || payload === undefined
        ? Buffer.alloc(0)
        : Buffer.from(JSON.stringify(payload), 'utf8');
    const timestamp = String(Math.floor(Date.now() / 1000));
    const normalizedMethod = String(method || 'GET').toUpperCase();
    const signPath = options.signPath || apiPath;
    const prefix = Buffer.from(`${normalizedMethod}\n${signPath}\n${timestamp}\n`, 'utf8');
    const signature = crypto
        .createHmac('sha256', API_SECRET)
        .update(Buffer.concat([prefix, body]))
        .digest('hex');
    return apiRequest(
        normalizedMethod,
        apiPath,
        payload,
        {
            'X-Api-Key': API_KEY,
            'X-Timestamp': timestamp,
            'X-Signature': signature
        },
        options
    );
}

function apiRequest(method, apiPath, payload = null, extraHeaders = {}, options = {}) {
    return new Promise((resolve, reject) => {
        const body = payload === null || payload === undefined
            ? Buffer.alloc(0)
            : Buffer.from(JSON.stringify(payload), 'utf8');
        const normalizedMethod = String(method || 'GET').toUpperCase();
        const headers = { ...extraHeaders };
        if (body.length > 0) {
            headers['Content-Type'] = 'application/json';
            headers['Content-Length'] = body.length;
        }

        const url = new URL(apiPath, API_BASE_URL);
        const req = http.request(
            url,
            {
                method: normalizedMethod,
                headers,
                timeout: Math.max(1000, Number(options.timeoutMs) || 60000)
            },
            (resp) => {
                const chunks = [];
                resp.on('data', (chunk) => chunks.push(chunk));
                resp.on('end', () => {
                    const text = Buffer.concat(chunks).toString('utf8');
                    let data = null;
                    try {
                        data = JSON.parse(text || '{}');
                    } catch (err) {
                        reject(new Error(text || err.message));
                        return;
                    }
                    if (resp.statusCode < 200 || resp.statusCode >= 300 || data.ok === false) {
                        const requestError = new Error(data.detail || data.error || text || `HTTP ${resp.statusCode}`);
                        requestError.statusCode = resp.statusCode;
                        requestError.response = data;
                        reject(requestError);
                        return;
                    }
                    resolve(data);
                });
            }
        );
        req.on('timeout', () => {
            req.destroy(new Error('dialog chat timeout'));
        });
        req.on('error', reject);
        if (body.length > 0) {
            req.write(body);
        }
        req.end();
    });
}

function resolveVoiceStreamUrl(req) {
    if (VOICE_PIPELINE_PUBLIC_URL) {
        return VOICE_PIPELINE_PUBLIC_URL;
    }
    const forwardedProto = req && req.get && req.get('x-forwarded-proto');
    const requestProto = forwardedProto || (req && req.protocol) || 'http';
    const forwardedHost = req && req.get && req.get('x-forwarded-host');
    const host = forwardedHost || (req && req.get && req.get('host'));
    const baseUrl = host ? `${requestProto}://${host}` : API_BASE_URL;
    const url = new URL('/api/v1/dialog/voice-stream', baseUrl);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.toString();
}

function isEmployeeSyncAuthorized(req) {
    if (!API_KEY || !API_SECRET) return true;
    const apiKey = req.get('x-api-key') || '';
    const timestamp = req.get('x-timestamp') || '';
    const signature = req.get('x-signature') || '';
    if (apiKey !== API_KEY || !timestamp || !signature) return false;

    const timestampSeconds = Number(timestamp);
    if (!Number.isFinite(timestampSeconds)) return false;
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (Math.abs(nowSeconds - timestampSeconds) > API_SIGNATURE_TOLERANCE_SECONDS) return false;

    const body = req.rawBody || Buffer.alloc(0);
    const prefix = Buffer.from(`${req.method.toUpperCase()}\n${req.path}\n${timestamp}\n`, 'utf8');
    const payload = Buffer.concat([prefix, body]);
    const expected = crypto
        .createHmac('sha256', API_SECRET)
        .update(payload)
        .digest('hex');
    if (signature.length !== expected.length) return false;
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
}

function normalizeEmployeeNames(body) {
    const source = Array.isArray(body && body.names)
        ? body.names
        : [body && body.name];
    return Array.from(new Set(
        source
            .map((name) => String(name || '').trim())
            .filter(Boolean)
    ));
}

function runEmployeeSync(args) {
    return new Promise((resolve, reject) => {
        execFile(
            PYTHON_BIN,
            [EMPLOYEE_SYNC_SCRIPT, ...args],
            { cwd: ROOT_DIR, encoding: 'utf8' },
            (err, stdout, stderr) => {
                let data = null;
                try {
                    data = parseJsonOutput(stdout);
                } catch (parseErr) {
                    reject(new Error(stderr || stdout || parseErr.message));
                    return;
                }
                if (err || data.ok === false) {
                    reject(new Error((data && data.error) || stderr || err.message));
                    return;
                }
                resolve(data);
            }
        );
    });
}

function registerEmployee(name) {
    return runEmployeeSync(['--register', name]);
}

function parseJsonOutput(stdout) {
    const text = String(stdout || '').trim();
    if (!text) return {};
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].startsWith('{') && lines[i].endsWith('}')) {
            return JSON.parse(lines[i]);
        }
    }
    return JSON.parse(text);
}

function runPythonJsonScript(scriptPath, payload) {
    const payloadPath = path.join(
        CACHE_DIR,
        `payload_${Date.now()}_${Math.random().toString(16).slice(2)}.json`
    );
    if (!fs.existsSync(CACHE_DIR)) {
        fs.mkdirSync(CACHE_DIR, { recursive: true });
    }
    fs.writeFileSync(payloadPath, JSON.stringify(payload), 'utf8');

    return new Promise((resolve, reject) => {
        execFile(
            PYTHON_BIN,
            [scriptPath, payloadPath],
            { cwd: ROOT_DIR, encoding: 'utf8' },
            (err, stdout, stderr) => {
                fs.rm(payloadPath, { force: true }, () => { });
                let data = null;
                try {
                    data = parseJsonOutput(stdout);
                } catch (parseErr) {
                    reject(new Error(stderr || stdout || parseErr.message));
                    return;
                }
                if (err || data.ok === false) {
                    reject(new Error((data && data.error) || stderr || err.message));
                    return;
                }
                resolve(data);
            }
        );
    });
}

function enrollLocalEmployee(payload) {
    const apiPayload = {
        name: payload && payload.name,
        photoPaths: payload && (payload.photoPaths || payload.photo_paths || payload.photos || []),
        folder: payload && (payload.folder || payload.photoDir || null)
    };
    return signedApiRequest('POST', '/api/v1/employees/enroll-local', apiPayload, { timeoutMs: 180000 });
}

async function listDbEmployeeNames() {
    try {
        const data = await runEmployeeSync(['--list']);
        return Array.isArray(data.names) ? data.names : [];
    } catch (err) {
        console.error('Employee list from DB failed:', err.message || err);
        return [];
    }
}

async function listTtsNames() {
    const names = new Set(['访客']);
    if (!fs.existsSync(EMPLOYEES_DIR)) {
        return Array.from(new Set([...names, ...(await listDbEmployeeNames())]));
    }

    for (const entry of fs.readdirSync(EMPLOYEES_DIR, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            names.add(entry.name);
        }
    }

    for (const name of await listDbEmployeeNames()) {
        names.add(name);
    }
    return Array.from(names);
}

function loadTtsManifest() {
    return new Promise((resolve) => {
        execFile(
            PYTHON_BIN,
            [TTS_SCRIPT, '--print-manifest'],
            { cwd: ROOT_DIR, encoding: 'utf8' },
            (err, stdout, stderr) => {
                if (err) {
                    console.error('TTS manifest failed:', stderr || err.message);
                    resolve({});
                    return;
                }
                try {
                    resolve(JSON.parse(stdout));
                } catch (parseErr) {
                    console.error('TTS manifest parse failed:', parseErr.message);
                    resolve({});
                }
            }
        );
    });
}

function generateTtsFile(name, type, variant, tenantId = TENANT_ID, voice = '') {
    voice = resolveTtsVoice(voice);
    const cacheFile = getTtsCacheFile(name, type, variant, tenantId, voice);
    if (fs.existsSync(cacheFile) && fs.statSync(cacheFile).size > 0) {
        return Promise.resolve('cached');
    }

    return generateTtsFileWithRetry(name, type, variant, tenantId, voice, cacheFile, 3);
}

function generateTtsFileWithRetry(name, type, variant, tenantId, voice, cacheFile, attempts) {
    return new Promise((resolve) => {
        let attempt = 0;

        function run() {
            attempt += 1;
            execFile(
                PYTHON_BIN,
                [TTS_SCRIPT, '--tenant-id', tenantId, name, type, cacheFile, String(variant), voice],
                { cwd: ROOT_DIR },
                (err, stdout, stderr) => {
                    if (!err && fs.existsSync(cacheFile) && fs.statSync(cacheFile).size > 0) {
                        resolve('created');
                        return;
                    }

                    if (attempt < attempts) {
                        setTimeout(run, 800 * attempt);
                        return;
                    }

                    console.error(
                        `TTS prewarm failed: ${tenantId}/${type}/${voice || 'default'}/${variant}`,
                        stderr || (err && err.message) || 'file not created'
                    );
                    resolve('failed');
                }
            );
        }

        run();
    });
}

async function prewarmEmployeeTts(name, manifest, tenantId = TENANT_ID) {
    let generated = 0;
    let skipped = 0;
    let failed = 0;
    const files = NAMED_TTS_TYPES.flatMap((type) => {
        const variantCount = Math.max(1, manifest[type] || 1);
        return fixedTtsVoiceKeys().flatMap((voice) => {
            return Array.from({ length: variantCount }, (_, variant) => ({
                name,
                type,
                tenantId,
                voice,
                variant
            }));
        });
    });

    let cursor = 0;
    async function worker() {
        while (cursor < files.length) {
            const file = files[cursor++];
            try {
                const status = await generateTtsFile(file.name, file.type, file.variant, file.tenantId, file.voice);
                if (status === 'created') {
                    generated += 1;
                } else if (status === 'cached') {
                    skipped += 1;
                } else {
                    failed += 1;
                }
            } catch (err) {
                failed += 1;
                console.error(`Employee TTS failed: ${file.tenantId}/${file.name}/${file.type}/${file.voice}/${file.variant}`, err.message || err);
            }
        }
    }

    await Promise.all(
        Array.from({ length: Math.min(TTS_PREWARM_CONCURRENCY, files.length) }, worker)
    );

    if (failed > 0) {
        throw new Error(`TTS failed for ${failed} files`);
    }

    return { generated, skipped, total: files.length };
}

async function prewarmTtsCache() {
    if (!fs.existsSync(CACHE_DIR)) {
        fs.mkdirSync(CACHE_DIR, { recursive: true });
    }

    prewarmStatus.running = true;
    prewarmStatus.complete = false;
    prewarmStatus.generated = 0;
    prewarmStatus.skipped = 0;
    prewarmStatus.total = 0;
    prewarmStatus.error = '';

    const names = await listTtsNames();
    const manifest = await loadTtsManifest();
    let generated = 0;
    let skipped = 0;

    const jobs = [
        ...NAMED_TTS_TYPES.flatMap((type) => names.flatMap((name) => fixedTtsVoiceKeys().map((voice) => ({ name, type, tenantId: TENANT_ID, voice })))),
        ...ANONYMOUS_TTS_TYPES.flatMap((type) => fixedTtsVoiceKeys().map((voice) => ({ name: '访客', type, tenantId: TENANT_ID, voice })))
    ];

    prewarmStatus.total = jobs.reduce((sum, job) => {
        return sum + Math.max(1, manifest[job.type] || 1);
    }, 0);

    console.log(`TTS prewarm started: ${jobs.length} name/type groups, ${prewarmStatus.total} files`);

    const files = jobs.flatMap((job) => {
        const variantCount = Math.max(1, manifest[job.type] || 1);
        return Array.from({ length: variantCount }, (_, variant) => ({ ...job, variant }));
    });
    let cursor = 0;

    async function worker() {
        while (cursor < files.length) {
            const file = files[cursor++];
            const status = await generateTtsFile(file.name, file.type, file.variant, file.tenantId, file.voice);
            if (status === 'created') {
                generated += 1;
            } else if (status === 'cached') {
                skipped += 1;
            } else {
                prewarmStatus.error = `TTS failed: ${file.tenantId}/${file.name}/${file.type}/${file.voice}/${file.variant}`;
                throw new Error(prewarmStatus.error);
            }
            prewarmStatus.generated = generated;
            prewarmStatus.skipped = skipped;
        }
    }

    await Promise.all(
        Array.from({ length: Math.min(TTS_PREWARM_CONCURRENCY, files.length) }, worker)
    );

    prewarmStatus.running = false;
    prewarmStatus.complete = true;
    console.log(`TTS prewarm complete: generated=${generated}, cached/failed=${skipped}`);
}

wss.on('connection', (ws, request) => {
    console.log('Client connected');
    wsClientMeta.set(ws, {
        role: 'unknown',
        tenantId: '',
        deviceId: '',
        authPending: true,
        connectedAt: Date.now(),
        pendingRegister: null
    });
    initializeWsClientIdentity(ws, request).catch((err) => {
        console.warn('WebSocket tenant authentication failed:', err.message || err);
        ws.close(1008, 'invalid avatar device session');
    });

    ws.on('message', (data) => {
        try {
            const msg = JSON.parse(data.toString());
            const meta = wsClientMeta.get(ws) || {};
            if (meta.authPending) {
                if (msg.target === 'server' && msg.type === 'REGISTER') {
                    meta.pendingRegister = msg;
                    wsClientMeta.set(ws, meta);
                }
                return;
            }
            if (msg.target !== 'server' && !['avatar', 'control'].includes(meta.role)) {
                console.warn('WebSocket 未注册连接尝试转发消息');
                ws.close(1008, 'websocket registration required');
                return;
            }
            if (msg.target === 'server') {
                handleWsServerMessage(ws, msg);
            } else if (msg.target === 'avatar') {
                forwardToActiveAvatar(ws, msg);
            } else if (msg.target === 'control') {
                forwardToControls(ws, msg);
            } else {
                console.log('Received:', msg);
            }
        } catch (e) {
            console.error('Invalid message:', data.toString());
        }
    });

    ws.on('close', () => {
        console.log('Client disconnected');
        const meta = wsClientMeta.get(ws) || {};
        const tenantId = meta.tenantId || '';
        if (!tenantId) return;
        if (ws === activeAvatarClients.get(tenantId)) {
            const replacement = pickLatestOpenAvatarClient(tenantId, ws);
            if (replacement) {
                activeAvatarClients.set(tenantId, replacement);
            } else {
                activeAvatarClients.delete(tenantId);
            }
            const replacementMeta = replacement ? wsClientMeta.get(replacement) : null;
            console.log(
                'Active avatar client changed:',
                `tenant=${tenantId}`,
                replacementMeta ? replacementMeta.clientId || 'unknown' : 'none'
            );
        }
    });
});

async function initializeWsClientIdentity(ws, request) {
    const cookieHeader = String((request.headers && request.headers.cookie) || '');
    const avatarToken = getCookieFromHeader(cookieHeader, AVATAR_SESSION_COOKIE);
    const controlToken = getCookieFromHeader(cookieHeader, CONTROL_SESSION_COOKIE);
    let avatarBinding = null;
    let controlBinding = null;
    if (avatarToken) {
        const cached = avatarSessionBindings.get(avatarToken);
        if (cached && cached.expiresAt > Date.now()) {
            avatarBinding = cached;
        } else {
            try {
                const response = await apiRequest(
                    'GET',
                    '/api/v1/device-sessions/avatar-session',
                    null,
                    { 'X-Avatar-Session': avatarToken },
                    { timeoutMs: 10000 }
                );
                const data = response.data || {};
                cacheAvatarSession(avatarToken, {
                    tenantId: data.tenantId,
                    deviceId: data.deviceId,
                    expiresAt: Date.now() + AVATAR_SESSION_SECONDS * 1000
                });
                avatarBinding = avatarSessionBindings.get(avatarToken);
            } catch (err) {
                console.warn('WebSocket 数字人设备会话无效: error=%s', err.message || err);
            }
        }
    }
    if (!CONTROL_AUTH_ENABLED) {
        controlBinding = {
            tenantId: TENANT_ID,
            deviceId: '',
            accountId: 0
        };
    } else if (controlToken) {
        try {
            controlBinding = await resolveControlSessionToken(controlToken);
        } catch (err) {
            console.error('WebSocket 控制台会话依赖不可用: error=%s', err.message || err);
            throw err;
        }
    }
    if (!avatarBinding && !controlBinding) {
        throw new Error('authenticated websocket binding required');
    }
    const meta = wsClientMeta.get(ws) || {};
    meta.avatarBinding = avatarBinding;
    meta.controlBinding = controlBinding;
    meta.tenantId = (avatarBinding || controlBinding).tenantId;
    meta.deviceId = avatarBinding ? avatarBinding.deviceId : '';
    meta.authPending = false;
    wsClientMeta.set(ws, meta);
    console.log(
        'WebSocket 身份候选已解析: avatar_tenant=%s control_tenant=%s',
        avatarBinding ? avatarBinding.tenantId : 'none',
        controlBinding ? controlBinding.tenantId : 'none'
    );
    if (meta.pendingRegister) {
        const pendingRegister = meta.pendingRegister;
        meta.pendingRegister = null;
        handleWsServerMessage(ws, pendingRegister);
    }
}

function getCookieFromHeader(header, name) {
    const prefix = `${name}=`;
    for (const part of String(header || '').split(';')) {
        const value = part.trim();
        if (value.startsWith(prefix)) {
            try {
                return decodeURIComponent(value.slice(prefix.length));
            } catch (err) {
                return '';
            }
        }
    }
    return '';
}

function handleWsServerMessage(ws, msg) {
    if (msg.type !== 'REGISTER') return;
    const current = wsClientMeta.get(ws) || {};
    const role = msg.role === 'avatar' || msg.role === 'control' ? msg.role : 'unknown';
    let roleBinding;
    try {
        roleBinding = resolveWsRoleBinding(
            role,
            current.avatarBinding,
            current.controlBinding,
            CONTROL_AUTH_ENABLED
        );
    } catch (err) {
        console.warn('WebSocket 角色身份绑定失败: role=%s error=%s', role, err.message || err);
        ws.close(1008, err.message || 'websocket role authentication failed');
        return;
    }
    const meta = {
        ...current,
        role,
        tenantId: roleBinding.tenantId,
        deviceId: role === 'avatar' ? roleBinding.deviceId : '',
        clientId: String(msg.clientId || '').slice(0, 80),
        connectedAt: Date.now(),
        registeredAt: Date.now()
    };
    delete meta.avatarBinding;
    delete meta.controlBinding;
    wsClientMeta.set(ws, meta);
    console.log('WebSocket 租户身份已锁定: role=%s tenant=%s', role, meta.tenantId);
    if (role === 'avatar') {
        activeAvatarClients.set(meta.tenantId, ws);
        console.log(
            'Active avatar client registered:',
            `tenant=${meta.tenantId}`,
            meta.clientId || 'unknown'
        );
    }
}

function forwardToActiveAvatar(sender, msg) {
    const senderMeta = wsClientMeta.get(sender) || {};
    const tenantId = senderMeta.tenantId;
    if (!tenantId) return;
    const activeAvatarClient = activeAvatarClients.get(tenantId);
    if (activeAvatarClient && activeAvatarClient.readyState === WebSocket.OPEN) {
        if (activeAvatarClient !== sender) {
            activeAvatarClient.send(JSON.stringify(msg));
        }
        return;
    }
    wss.clients.forEach((client) => {
        const meta = wsClientMeta.get(client) || {};
        if (
            client !== sender
            && client.readyState === WebSocket.OPEN
            && meta.tenantId === tenantId
            && meta.role === 'avatar'
        ) {
            client.send(JSON.stringify(msg));
        }
    });
}

function forwardToControls(sender, msg) {
    const senderMeta = wsClientMeta.get(sender) || {};
    const tenantId = senderMeta.tenantId;
    if (!tenantId) return;
    const activeAvatarClient = activeAvatarClients.get(tenantId);
    if (
        msg.type === 'STATE_SYNC'
        && activeAvatarClient
        && senderMeta.role === 'avatar'
        && sender !== activeAvatarClient
    ) {
        console.log('Dropped STATE_SYNC from inactive avatar:', senderMeta.clientId || 'unknown');
        return;
    }
    wss.clients.forEach((client) => {
        const meta = wsClientMeta.get(client) || {};
        if (
            client !== sender
            && client.readyState === WebSocket.OPEN
            && meta.tenantId === tenantId
            && meta.role === 'control'
        ) {
            client.send(JSON.stringify(msg));
        }
    });
}

function pickLatestOpenAvatarClient(tenantId, excluding) {
    let selected = null;
    let selectedAt = -1;
    wss.clients.forEach((client) => {
        if (client === excluding || client.readyState !== WebSocket.OPEN) return;
        const meta = wsClientMeta.get(client) || {};
        if (meta.role !== 'avatar') return;
        if (meta.tenantId !== tenantId) return;
        const at = Number(meta.registeredAt || meta.connectedAt || 0);
        if (at > selectedAt) {
            selected = client;
            selectedAt = at;
        }
    });
    return selected;
}

function broadcast(event) {
    const payload = JSON.stringify(event);
    const tenantId = String((event && (event.tenant_id || event.tenantId)) || TENANT_ID);
    const activeAvatarClient = activeAvatarClients.get(tenantId);
    wss.clients.forEach((client) => {
        const meta = wsClientMeta.get(client) || {};
        const activeAvatar = activeAvatarClient
            ? client === activeAvatarClient
            : meta.role === 'avatar';
        if (
            client.readyState === WebSocket.OPEN
            && shouldDeliverBroadcastToRole(meta, tenantId, activeAvatar)
        ) {
            client.send(payload);
        }
    });
}

app.post('/event', (req, res) => {
    if (!isEmployeeSyncAuthorized(req)) {
        return res.status(401).json({ ok: false, error: 'unauthorized' });
    }
    const event = req.body;
    const eventTenantId = String(event && (event.tenant_id || event.tenantId) || TENANT_ID);
    console.log(`Event received: tenant=${eventTenantId}`, event);
    broadcast(event);
    res.json({ ok: true });
});

server.listen(PORT, () => {
    console.log(`Avatar server running at http://localhost:${PORT}`);
    console.log(`Open http://localhost:${PORT} to see Epsilon`);
    if (process.env.ENABLE_TTS_PREWARM === '1') {
        prewarmTtsCache().catch((err) => {
            prewarmStatus.running = false;
            prewarmStatus.complete = true;
            prewarmStatus.error = err.message || String(err);
            console.error('TTS prewarm error:', err);
        });
    } else {
        prewarmStatus.complete = true;
        prewarmStatus.error = '';
        console.log('TTS prewarm skipped. Set ENABLE_TTS_PREWARM=1 to enable legacy full-cache generation.');
    }
});
