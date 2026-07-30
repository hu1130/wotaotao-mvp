(function () {
    const { Live2DModel } = PIXI.live2d;
    const voiceTurnPolicy = window.VoiceTurnPolicy;
    if (!voiceTurnPolicy) {
        throw new Error('VoiceTurnPolicy is required before avatar.js');
    }
    const canvas = document.getElementById('canvas');
    const statusEl = document.getElementById('status');
    const loadingEl = document.getElementById('loading');
    const subtitleEl = document.getElementById('subtitle');
    const modelTransitionEl = document.getElementById('model-transition');
    const modelTransitionNameEl = document.getElementById('model-transition-name');
    const modelTransitionTextEl = document.getElementById('model-transition-text');
    const modelSwitcherEl = document.getElementById('model-switcher');
    const interactionModeSwitcherEl = document.getElementById('interaction-mode-switcher');
    const voiceChatButton = document.getElementById('voice-chat-button');
    const voiceChatText = document.getElementById('voice-chat-text');
    const faceNameDialog = document.getElementById('face-name-dialog');
    const faceNameForm = document.getElementById('face-name-form');
    const faceNameInput = document.getElementById('face-name-input');
    const faceNameStatus = document.getElementById('face-name-status');
    const faceNameCancel = document.getElementById('face-name-cancel');
    const faceNameSubmit = document.getElementById('face-name-submit');

    function safeBtn(el, prop, val) { if (el) el[prop] = val; }
    function safeCls(el, cls, method) { if (el) el.classList[method](cls); }

    let app, model = null;
    let currentModelKey = 'epsilon';
    let currentModelConfig = null;
    let ws = null;
    let audio = null;
    let idleState = 'idle';
    let idleTimer = null;
    let microTimer = null;
    let fidgetTimer = null;
    let subtitleTimer = null;
    let voiceChatTextTimer = null;
    let speechErrorStatusTimer = null;
    let externalSpeechWatchdogTimer = null;
    let streamingDialogWatchdogTimer = null;
    let voiceAsrFinalWatchdogTimer = null;
    let ttsManifest = {};
    let ttsVoiceByModel = {};
    let audioUnlocked = false;
    let audioContext = null;
    let lipAnalyser = null;
    let lipGainNode = null;
    let lipSourceNode = null;
    let lipData = null;
    let lipFrame = null;
    let lipSyncToken = 0;
    let lipSyncAudioElement = null;
    let lipSyncMode = '';
    let lipValue = 0;
    let mouthOpenValue = 0;
    let mouthBoundModel = null;
    let externalLipTarget = 0;
    let externalLipNextChangeAt = 0;
    let externalLipPauseUntil = 0;
    let externalLipNextPauseAt = 0;
    let lipStartedAt = 0;
    let ttsRequestId = 0;
    let ttsMutedUntil = 0;
    let isSwitchingModel = false;
    let queuedModelKey = null;
    let modelPreloadStarted = false;
    let lastModelSwitchRequestAt = 0;
    let statusMode = 'idle';
    let voicePhase = 'ready';
    let voicePhaseText = 'Ready for next visitor';
    let voiceActivityLevel = 0.18;
    let lastBehaviorName = '';
    let lastBehaviorAt = 0;
    let speechRecognition = null;
    let isListening = false;
    let isDialogBusy = false;
    let dialogPriorityMode = 0;
    let realtimeDialogEnabled = false;
    let realtimeRagEnabled = false;
    let interactionMode = '';
    let interactionModes = [];
    let voiceStreamUrl = '';
    let voiceStreamBackend = 'cascade';
    let voiceVadSilenceMs = 1400;
    let voiceDeviceId = '';
    let voiceTenantId = '';
    let voiceSiteId = '';
    let avatarSessionValid = false;
    let dialogSettingsPromise = null;
    let voiceStreamWs = null;
    let voiceStreamKeepOpen = false;
    let voicePersonSession = null;
    let voiceMediaStream = null;
    let voiceProcessor = null;
    let voiceSource = null;
    let voiceInputContext = null;
    let streamingAudioQueue = [];
    let streamingAudioPlaying = false;
    let streamingAudioDone = true;
    let streamingPlaybackStarted = false;
    let streamingAudioActiveItem = null;
    let streamingPlayedMsByReply = {};
    let streamingPlaybackAckSent = false;
    let streamingAudioProgressTimer = null;
    let activeFixedTtsStream = null;
    let activeLocalDialogPlaybackText = '';
    let activeLocalDialogPlaybackEstimatedMs = 0;
    let streamingSpeechStatusRefresh = null;
    let pendingEmptyBargeResume = null;
    let emptyBargeResumePlaybackActive = false;
    let interruptedListeningStatusUntil = 0;
    let activeSpeechPriority = 0;
    let activeSpeechOwner = '';
    let autoVoiceChatEnabled = true;
    let autoVoiceRestartTimer = null;
    let voiceSpeechStarted = false;
    let voiceUserSpeechDetectedThisTurn = false;
    let voiceSpeechStartedAt = 0;
    let voiceLastSpeechAt = 0;
    let voiceNoiseFloor = 0.012;
    let voiceVadCandidateFrames = 0;
    let voiceVadCandidateStartedAt = 0;
    let voiceVadCandidatePeak = 0;
    let voiceVadCandidateRmsSum = 0;
    let voiceVadPreRoll = [];
    let voicePendingInputFrames = [];
    let voicePcmPacketRemainder = new Uint8Array(0);
    let voiceSentBytesThisTurn = 0;
    let lastVoiceVadRejectLogAt = 0;
    let voiceStopRequested = false;
    let voiceMonitorReady = false;
    let voiceMonitorStarting = false;
    let voiceConversationId = createVoiceConversationId();
    let voiceOutputVolume = loadVoiceOutputVolume();
    let voiceInputRate = 48000;
    let voiceTurnId = 0;
    let activeVoiceTurnId = 0;
    let dialogHistory = [];
    let currentUserText = '';
    let currentAnswerText = '';
    let visitorSpeechText = '';
    let assistantSpeechText = '';
    let speechStatusText = '';
    let voiceDialogSilenced = false;
    let voiceDialogSilenceStatusText = '';
    let voiceDialogSilenceFeedbackActive = false;
    let voiceDialogSilenceFeedbackTurnId = 0;
    let voiceDialogSilenceFeedbackAudioSeen = false;
    let voiceDialogSilenceFeedbackDoneSeen = false;
    let voiceDialogSilenceFeedbackRestoresSilence = false;
    let voiceDialogSilenceFeedbackStatusText = '';
    let voiceDialogSilenceFeedbackText = '';
    let voiceDialogSilenceFeedbackDynamic = false;
    let voiceDialogSilenceFeedbackTimer = null;
    let faceNameSubmitting = false;
    let avatarEventQueue = [];
    let avatarEventPumpTimer = null;
    let lastScheduledEventAtByKey = {};
    let lastAvatarEventBlockedLogAt = 0;
    let lastFixedSpeechPreserveVoiceLogAt = 0;
    const avatarRuntimeClientId = 'avatar:' + Date.now().toString(36) + ':' + Math.random().toString(36).slice(2, 8);
    let selfSpeechMutedUntil = 0;
    let fixedSpeechNoiseGuardEnabled = true;
    let fixedSpeechPostGuardMs = 1200;
    let fixedSpeechActive = false;
    let fixedSpeechPlaybackActive = false;
    let fixedSpeechGuardUntil = 0;
    let activeFixedSpeechEventType = '';
    let dialogAudioLockedUntil = 0;
    let dialogAudioLockOwners = {};
    let dialogAudioLockTimers = {};
    const modelLoadCache = new Map();
    const modelLoadPromises = new Map();
    let modelSwitchGeneration = 0;
    let modelHandoffAbortController = null;
    let modelHandoffOwner = '';
    const MODEL_SWITCH_FADE_MS = 220;
    const MODEL_TRANSITION_HOLD_MS = 80;
    const MODEL_PRELOAD_CONCURRENCY = 2;
    const MODEL_SWITCH_MIN_INTERVAL_MS = 180;
    const MODEL_HANDOFF_LOCK_MS = 18000;
    const DIALOG_AUDIO_LOCK_MAX_MS = 120000;
    const DIALOG_AUDIO_RELEASE_GRACE_MS = 1800;
    const SPEECH_PRIORITY_MODEL_SWITCH = 120;
    const SPEECH_PRIORITY_REALTIME_DIALOG = 100;
    const SPEECH_PRIORITY_LOCAL_DIALOG_HIGH = 90;
    const SPEECH_PRIORITY_LOCAL_DIALOG_NORMAL = 50;
    const SPEECH_PRIORITY_FIXED_DEFAULT = 70;
    const SPEECH_PRIORITY_LEGACY_TTS = 40;
    const STREAMING_AUDIO_STALL_MS = 3000;
    const VOICE_VAD_START_RATIO = 2.6;
    const VOICE_VAD_START_MIN = 0.032;
    const VOICE_VAD_END_RATIO = 1.6;
    const VOICE_VAD_END_MIN = 0.018;
    const VOICE_PCM_PACKET_BYTES = 640;
    const VOICE_VAD_MIN_SPEECH_MS = 650;
    const VOICE_VAD_START_FRAMES = 3;
    const VOICE_VAD_START_WINDOW_MS = 650;
    const VOICE_VAD_PEAK_MIN = 0.045;
    const VOICE_VAD_FAST_PEAK_MIN = 0.085;
    const VOICE_VAD_PREROLL_FRAMES = 12;
    const VOICE_PENDING_INPUT_MAX_FRAMES = 240;
    const VOICE_BARGE_IN_START_MIN = 0.03;
    const VOICE_BARGE_IN_START_RATIO = 2.1;
    const VOICE_BARGE_IN_START_FRAMES = 3;
    const VOICE_BARGE_IN_MIN_MS = 90;
    const VOICE_BARGE_IN_MIN_AVG_RATIO = 0.78;
    const VOICE_BARGE_IN_PEAK_AVG_MAX = 4.0;
    const VOICE_PENDING_INTERRUPT_START_MIN = 0.05;
    const VOICE_PENDING_INTERRUPT_START_RATIO = 3.0;
    const VOICE_PENDING_INTERRUPT_START_FRAMES = 10;
    const VOICE_PENDING_INTERRUPT_MIN_MS = 380;
    const VOICE_PENDING_INTERRUPT_MIN_AVG_RATIO = 0.95;
    const VOICE_PENDING_INTERRUPT_PEAK_AVG_MAX = 3.0;
    const VOICE_AUTO_RESTART_MS = 900;
    const VOICE_ASR_FINAL_WATCHDOG_MS = 9000;
    const EMPTY_BARGE_RESUME_TTL_MS = 20000;
    const EMPTY_BARGE_RESUME_MAX_CHARS = 360;
    const EMPTY_BARGE_RESUME_SILENCE_MS = 1200;
    const EMPTY_BARGE_ASR_FINAL_WATCHDOG_MS = 2500;
    const STREAMING_SELF_SPEECH_RELEASE_GRACE_MS = 350;
    const SELF_SPEECH_RELEASE_GRACE_MS = 900;
    const AVATAR_EVENT_DEDUP_MS = 2200;

    function defaultVoicePhaseText(phase) {
        switch (phase) {
            case 'listening':
                return 'Listening to visitor intent';
            case 'understanding':
                return 'Understanding request';
            case 'speaking':
                return 'Speaking response';
            case 'error':
                return 'Recovering voice channel';
            case 'ready':
            default:
                return 'Ready for next visitor';
        }
    }

    function setVoicePhase(phase, text, activityLevel) {
        var nextPhase = String(phase || 'ready');
        var nextText = String(text || '').trim() || defaultVoicePhaseText(nextPhase);
        var parsedLevel = Number(activityLevel);
        var nextLevel = Number.isFinite(parsedLevel) ? parsedLevel : voiceActivityLevel;
        nextLevel = Math.max(0, Math.min(1, nextLevel));
        var changed = voicePhase !== nextPhase
            || voicePhaseText !== nextText
            || Math.abs(voiceActivityLevel - nextLevel) > 0.001;
        voicePhase = nextPhase;
        voicePhaseText = nextText;
        voiceActivityLevel = nextLevel;
        if (changed && typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({
                voicePhase: voicePhase,
                voicePhaseText: voicePhaseText,
                voiceActivityLevel: voiceActivityLevel
            });
        }
    }

    function setVisitorSpeechText(text) {
        visitorSpeechText = String(text || '').trim();
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({ visitorSpeechText: visitorSpeechText });
        }
    }

    function setAssistantSpeechText(text) {
        assistantSpeechText = String(text || '').trim();
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({ assistantSpeechText: assistantSpeechText });
        }
    }

    function clearConversationDisplayText() {
        visitorSpeechText = '';
        assistantSpeechText = '';
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({
                visitorSpeechText: '',
                assistantSpeechText: ''
            });
        }
    }

    function clientLog(message, detail) {
        try {
            fetch('/client-log', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scope: 'voice', message: message, detail: detail || null })
            }).catch(function () { });
        } catch (err) { }
    }

    function fetchJsonWithError(url, options) {
        return fetch(url, options || {}).then(function (res) {
            return res.text().then(function (raw) {
                var payload = {};
                if (raw) {
                    try {
                        payload = JSON.parse(raw);
                    } catch (err) {
                        payload = { raw: raw };
                    }
                }
                if (!res.ok) {
                    var message = payload.error || payload.detail || payload.message || ('HTTP ' + res.status);
                    var error = new Error(message);
                    error.status = res.status;
                    error.payload = payload;
                    throw error;
                }
                return payload;
            });
        });
    }

    function avatarSessionUnavailableText(err) {
        var status = err && err.status;
        if (status === 401 || status === 403) {
            return '设备会话失效，请从客户端重新打开前台';
        }
        return '设备会话异常，请稍后重试';
    }

    function createVoiceConversationId() {
        if (window.crypto && window.crypto.randomUUID) {
            return window.crypto.randomUUID();
        }
        return 'voice-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    function loadVoiceOutputVolume() {
        try {
            var stored = localStorage.getItem('voiceOutputVolume');
            if (stored !== null && stored !== '') {
                return clampVolume(Number(stored));
            }
        } catch (err) { }
        return 1;
    }

    function clampVolume(value) {
        value = Number(value);
        if (!Number.isFinite(value)) return 1;
        return Math.max(0, Math.min(2.5, value));
    }

    function persistVoiceOutputVolume() {
        try {
            localStorage.setItem('voiceOutputVolume', String(voiceOutputVolume));
        } catch (err) { }
    }

    function applyVoiceOutputVolume(audioElement) {
        if (!audioElement) return;
        audioElement.volume = Math.min(1, voiceOutputVolume);
        if (lipGainNode && lipGainNode.gain) {
            lipGainNode.gain.value = voiceOutputVolume;
        }
    }

    function adjustVoiceOutputVolume(payload) {
        payload = payload || {};
        var previous = voiceOutputVolume;
        var direction = payload.direction || 'set';
        if (direction === 'increase') {
            voiceOutputVolume = clampVolume(voiceOutputVolume + (Number(payload.delta || 10) / 100));
        } else if (direction === 'decrease') {
            voiceOutputVolume = clampVolume(voiceOutputVolume - (Number(payload.delta || 10) / 100));
        } else if (direction === 'mute') {
            voiceOutputVolume = 0;
        } else if (payload.level !== undefined) {
            voiceOutputVolume = clampVolume(Number(payload.level));
        }
        persistVoiceOutputVolume();
        applyVoiceOutputVolume(audio);
        clientLog('voice output volume changed', {
            previous: Math.round(previous * 100),
            current: Math.round(voiceOutputVolume * 100),
            payload: payload
        });
        updateVoiceChatText('音量 ' + Math.round(voiceOutputVolume * 100) + '%', 1200);
    }

    const MODEL_REGISTRY = {
        epsilon: {
            label: 'Epsilon',
            role: '活力助手',
            path: 'models/Epsilon/Epsilon.model3.json',
            voice: 'zh-CN-XiaoyiNeural',
            handoffText: '叮当接棒啦，我会用轻快一点的方式陪你继续。',
            enterMotion: ['Tap', 0],
            enterExpression: 'Smile',
            fit: { width: 1200, height: 2000, scale: 0.8, y: 0.52 },
            expressions: {
                Angry: 'Angry.exp3.json',
                Blushing: 'Blushing.exp3.json',
                f01: 'f01.exp3.json',
                f02: 'f02.exp3.json',
                Normal: 'Normal.exp3.json',
                Sad: 'Sad.exp3.json',
                Smile: 'Smile.exp3.json',
                Surprised: 'Surprised.exp3.json'
            },
            expressionButtons: ['Angry', 'Blushing', 'f01', 'f02', 'Normal', 'Sad', 'Smile', 'Surprised'],
            motionCounts: {
                Idle: 1,
                Tap: 4,
                Flick: 2,
                FlickUp: 2,
                FlickDown: 2,
                Flick3: 2,
                Shake: 2
            }
        },
        chitose: {
            label: 'Chitose 男',
            role: '沉稳伙伴',
            path: 'models/chitose_ja/runtime/chitose.model3.json',
            voice: 'zh-TW-YunJheNeural',
            handoffText: '千岁来了，我会认真听你说，慢慢来就好。',
            enterMotion: ['Tap', 0],
            enterExpression: 'Normal',
            fit: { width: 1150, height: 1900, scale: 0.86, y: 0.54 },
            expressions: {
                Angry: 'Angry.exp3.json',
                Blushing: 'Blushing.exp3.json',
                f01: 'f01.exp3.json',
                f02: 'f01.exp3.json',
                Normal: 'Normal.exp3.json',
                Sad: 'Sad.exp3.json',
                Smile: 'Smile.exp3.json',
                Surprised: 'Surprised.exp3.json'
            },
            expressionButtons: ['Angry', 'Blushing', 'f01', 'Normal', 'Sad', 'Smile', 'Surprised'],
            motionCounts: {
                Idle: 1,
                Tap: 2,
                Flick: 1
            },
            motionMap: {
                Idle: [['Idle', 0]],
                Tap: [['Tap', 0], ['Tap', 1]],
                Flick: [['Flick', 0]],
                FlickUp: [['Tap', 0], ['Tap', 1]],
                FlickDown: [['Tap', 1], ['Idle', 0]],
                Flick3: [['Tap', 0], ['Flick', 0]],
                Shake: [['Tap', 1], ['Flick', 0]]
            }
        },
        haruGreeter: {
            label: 'Haru',
            role: '热情接待',
            path: 'models/haru_greeter_ja/runtime/haru_greeter_t05.model3.json',
            voice: 'zh-CN-XiaoxiaoNeural',
            handoffText: 'Haru上线，我来负责热情接待这一段。',
            enterMotion: ['', 21],
            fit: { width: 1200, height: 1900, scale: 0.52, y: 0.62 },
            expressions: {},
            expressionButtons: [],
            motionCounts: {
                '': 27
            },
            motionIndexLabels: {
                '': {
                    5: '震惊',
                    7: '害羞',
                    8: '害羞',
                    10: '害羞',
                    12: '害羞',
                    13: '震惊',
                    14: '震惊',
                    16: '害羞',
                    17: '害羞',
                    18: '害羞',
                    19: '害羞',
                    20: '失落',
                    21: '开心',
                    22: '开心',
                    23: '搞怪',
                    24: '失落',
                    25: '震惊',
                    26: '震惊'
                }
            },
            motionMap: {
                Idle: [['', 0]],
                Tap: [['', 1], ['', 2], ['', 3], ['', 4], ['', 5]],
                Flick: [['', 6], ['', 7], ['', 8]],
                FlickUp: [['', 9], ['', 10], ['', 11]],
                FlickDown: [['', 12], ['', 13], ['', 14]],
                Flick3: [['', 15], ['', 16], ['', 17]],
                Shake: [['', 18], ['', 19], ['', 20]]
            }
        },
        haru: {
            label: 'Hiyori',
            role: '日向向导',
            path: 'models/hiyori_zh-Hans/runtime/hiyori_pro_t11.model3.json',
            voice: 'zh-CN-XiaoyiNeural',
            handoffText: '日向到位，接下来就交给我吧。',
            enterMotion: ['Tap', 0],
            fit: { width: 1200, height: 2100, scale: 0.5, y: 0.55 },
            expressions: {},
            expressionButtons: [],
            motionCounts: {
                Idle: 3,
                Tap: 2,
                Flick: 1,
                FlickUp: 1,
                FlickDown: 1,
                'Tap@Body': 1,
                'Flick@Body': 1
            },
            motionMap: {
                Idle: [['Idle', 0], ['Idle', 1], ['Idle', 2]],
                Tap: [['Tap', 0], ['Tap', 1], ['Tap@Body', 0]],
                Flick: [['Flick', 0], ['Flick@Body', 0]],
                FlickUp: [['FlickUp', 0], ['Tap', 0]],
                FlickDown: [['FlickDown', 0], ['Idle', 1]],
                Flick3: [['Tap', 0], ['Tap', 1], ['Flick@Body', 0]],
                Shake: [['Flick', 0], ['FlickDown', 0]]
            }
        },
        natori: {
            label: 'Natori 男',
            role: '从容顾问',
            path: 'models/natori_zh-Hans/runtime/natori_pro_t06.model3.json',
            voice: 'zh-TW-YunJheNeural',
            handoffText: '名取已接入，我会从容地继续为你处理。',
            enterMotion: ['Tap@Head', 0],
            enterExpression: 'Normal',
            fit: { width: 1200, height: 2100, scale: 0.42, y: 0.68 },
            expressions: {
                Angry: 'Angry',
                Blushing: 'Blushing',
                f01: 'exp_01',
                f02: 'exp_02',
                Normal: 'Normal',
                Sad: 'Sad',
                Smile: 'Smile',
                Surprised: 'Surprised'
            },
            expressionButtons: ['Angry', 'Blushing', 'exp_01', 'exp_02', 'exp_03', 'exp_04', 'exp_05', 'Normal', 'Sad', 'Smile', 'Surprised'],
            motionCounts: {
                Idle: 3,
                Tap: 1,
                'FlickUp@Head': 1,
                'Flick@Body': 1,
                'FlickDown@Body': 1,
                'Tap@Head': 1
            },
            motionMap: {
                Idle: [['Idle', 0], ['Idle', 1], ['Idle', 2]],
                Tap: [['Tap', 0], ['Tap@Head', 0]],
                Flick: [['Flick@Body', 0]],
                FlickUp: [['FlickUp@Head', 0], ['Tap@Head', 0]],
                FlickDown: [['FlickDown@Body', 0]],
                Flick3: [['Tap', 0], ['Flick@Body', 0]],
                Shake: [['FlickDown@Body', 0], ['Flick@Body', 0]]
            }
        }
    };

    const DEFAULT_MODEL_KEY = 'epsilon';
    const DEFAULT_TTS_VOICE = 'zh-CN-XiaoxiaoNeural';
    const MODEL_LOAD_ATTEMPTS = 3;
    const EMPTY_BARGE_RESUME_PREPARING_TEXT = '正在继续思考你的问题';
    const INTERRUPTED_LISTENING_STATUS_TEXT = '你说，我听着~';
    const INTERRUPTED_LISTENING_STATUS_HOLD_MS = 3500;

    const BEHAVIORS = {
        greet: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 1],
                ['Tap', 2]
            ],
            tts: 'check_in',
            idleDelay: 4200
        },
        wave: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 1],
                ['Tap', 2],
                ['Tap', 3]
            ],
            idleDelay: 3600
        },
        gesture_wave: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 1],
                ['Tap', 2],
                ['Tap', 3]
            ],
            idleDelay: 4200
        },
        gesture_thumbs_up: {
            expression: 'Smile',
            motions: [
                ['Flick3', 0],
                ['Tap', 1],
                ['Shake', 0]
            ],
            idleDelay: 4200
        },
        gesture_heart: {
            expression: 'Blushing',
            motions: [
                ['Shake', 0],
                ['FlickUp', 0],
                ['Tap', 2]
            ],
            idleDelay: 5200
        },
        gesture_ok: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 1]
            ],
            idleDelay: 3800
        },
        gesture_peace: {
            expression: 'Smile',
            motions: [
                ['Flick3', 0],
                ['Flick3', 1],
                ['Tap', 3]
            ],
            idleDelay: 4600
        },
        gesture_middle_finger: {
            expression: 'Angry',
            motions: [
                ['Shake', 0],
                ['Shake', 1],
                ['Flick3', 0]
            ],
            idleDelay: 5200
        },
        bye: {
            expression: 'Normal',
            motions: [
                ['Flick', 0],
                ['Flick', 1]
            ],
            tts: 'check_out',
            idleDelay: 4200
        },
        check_in: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 1],
                ['Tap', 2],
                ['Tap', 3]
            ],
            tts: 'check_in',
            idleDelay: 4600
        },
        first_time: {
            expression: 'Blushing',
            motions: [
                ['Tap', 0],
                ['FlickUp', 0]
            ],
            tts: 'first_time',
            idleDelay: 5200
        },
        returning: {
            expression: 'Smile',
            motions: [
                ['Tap', 1],
                ['Tap', 3],
                ['Flick3', 0]
            ],
            tts: 'returning',
            idleDelay: 5200
        },
        check_out: {
            expression: 'Normal',
            motions: [
                ['Flick', 0],
                ['Flick', 1]
            ],
            tts: 'check_out',
            idleDelay: 4600
        },
        stranger: {
            expression: 'Surprised',
            motions: [
                ['FlickUp', 0],
                ['FlickUp', 1]
            ],
            tts: 'stranger',
            idleDelay: 4600
        },
        stranger_stare: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['FlickUp', 1],
                ['Shake', 0]
            ],
            tts: 'stranger_stare',
            idleDelay: 4800
        },
        repeat: {
            expression: 'Blushing',
            motions: [
                ['Shake', 0],
                ['Shake', 1]
            ],
            tts: 'repeat',
            idleDelay: 4600
        },
        checked_in_stare: {
            expression: 'Blushing',
            motions: [
                ['Shake', 0],
                ['FlickUp', 0],
                ['Tap', 2]
            ],
            tts: 'checked_in_stare',
            idleDelay: 4800
        },
        attention: {
            expression: 'Smile',
            motions: [
                ['Tap', 0],
                ['Tap', 2]
            ],
            idleDelay: 3600
        },
        idle_long: {
            expression: 'Sad',
            motions: [
                ['FlickDown', 0],
                ['FlickDown', 1]
            ],
            tts: 'idle_long',
            idleDelay: 5600
        },
        crowd: {
            expression: 'Surprised',
            motions: [
                ['Flick3', 0],
                ['Flick3', 1]
            ],
            tts: 'crowd',
            idleDelay: 5600
        }
    };

    const MODEL_BEHAVIOR_OVERRIDES = {
        epsilon: {
            greet: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1], ['Shake', 0], ['Shake', 1]]
            },
            check_in: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1], ['Shake', 0], ['Shake', 1]]
            },
            first_time: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1]]
            },
            returning: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1], ['Shake', 0], ['Shake', 1]]
            },
            check_out: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1], ['Shake', 0], ['Shake', 1]]
            },
            stranger: {
                expression: ['Normal', 'Blushing', 'Smile'],
                motions: [['Flick3', 0], ['Flick3', 1], ['Shake', 0], ['Shake', 1]]
            },
            repeat: {
                expressionPool: 'all',
                motionPool: 'visible'
            }
        },
        haruGreeter: {
            greet: {
                motions: [['', 21], ['', 22]]
            },
            check_in: {
                motions: [['', 21], ['', 22]]
            },
            first_time: {
                motions: [['', 21], ['', 22]]
            },
            returning: {
                motions: [['', 21], ['', 22]]
            },
            check_out: {
                motions: [['', 21], ['', 22]]
            },
            stranger: {
                motions: [['', 5], ['', 13], ['', 14], ['', 25], ['', 26]]
            },
            repeat: {
                motions: [['', 7], ['', 8], ['', 10], ['', 12], ['', 16], ['', 17], ['', 18], ['', 19], ['', 5], ['', 13], ['', 14], ['', 20], ['', 23], ['', 24], ['', 25], ['', 26]]
            },
            attention: {
                motions: [['', 7], ['', 8], ['', 10], ['', 12], ['', 16], ['', 17], ['', 18], ['', 19], ['', 21], ['', 22]]
            },
            idle_long: {
                motions: [['', 3], ['', 4], ['', 20], ['', 24]]
            },
            crowd: {
                motions: [['', 5], ['', 13], ['', 14], ['', 25], ['', 26]]
            }
        },
        haru: {
            greet: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            check_in: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            first_time: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            returning: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            check_out: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            stranger: {
                motions: [['Tap', 0], ['Tap', 1], ['Flick', 0]]
            },
            repeat: {
                motionPool: 'visible'
            },
            attention: {
                motionPool: 'visible'
            },
            idle_long: {
                motionPool: 'visible'
            },
            crowd: {
                motionPool: 'visible'
            }
        }
    };

    function showStatus(text, mode) {
        mode = mode || 'speech';
        var nextText = String(text || '').trim();
        if (shouldProtectDialogSilenceFeedbackText(nextText)) {
            nextText = voiceDialogSilenceFeedbackText;
        }
        if (shouldProtectDialogSilenceStatus(nextText)) {
            nextText = voiceDialogSilenceStatusText;
        }
        if (mode === 'speech' && shouldProtectInterruptedListeningUi(nextText)) {
            return;
        }
        if (mode === 'speech') {
            clearIdleTimer();
        }
        if (!nextText) {
            if (shouldProtectDialogSilenceStatus(nextText)) {
                nextText = voiceDialogSilenceStatusText;
            } else {
                statusMode = 'idle';
                statusEl.textContent = '';
                statusEl.classList.add('status-hidden');
                statusEl.hidden = true;
                speechStatusText = '';
                if (typeof broadcastStateToControl === 'function') {
                    broadcastStateToControl({ speechStatusText: speechStatusText });
                }
                return;
            }
        }
        if (statusMode === 'speech' && mode !== 'speech') {
            return;
        }
        statusMode = mode;
        statusEl.textContent = nextText;
        statusEl.classList.remove('status-hidden');
        statusEl.hidden = false;
        if (mode === 'speech') {
            speechStatusText = nextText;
        } else if (!nextText || mode === 'idle') {
            speechStatusText = '';
        }
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({ speechStatusText: speechStatusText });
        }
    }

    function clearStatusBeforeDeferredSpeech() {
        if (isInterruptedListeningStatusProtected()) {
            return;
        }
        if (shouldProtectDialogSilenceStatus('')) {
            showStatus(voiceDialogSilenceStatusText, 'speech');
            return;
        }
        statusMode = 'idle';
        speechStatusText = '';
        statusEl.textContent = '';
        statusEl.classList.add('status-hidden');
        statusEl.hidden = true;
    }

    function isInterruptedListeningStatusProtected() {
        var protectedText = interruptedListeningStatusText();
        return Boolean(
            speechStatusText === protectedText
            && performance.now() < interruptedListeningStatusUntil
        );
    }

    function interruptedListeningStatusText() {
        return voiceTurnPolicy.statusText('listening', INTERRUPTED_LISTENING_STATUS_TEXT);
    }

    function shouldProtectInterruptedListeningUi(nextText) {
        return voiceTurnPolicy.shouldProtectInterruptedListeningStatus({
            protected: isInterruptedListeningStatusProtected(),
            nextText: nextText,
            listeningText: INTERRUPTED_LISTENING_STATUS_TEXT
        });
    }

    function clearInterruptedListeningStatus(reason) {
        if (interruptedListeningStatusUntil > 0) {
            clientLog('interrupted listening status cleared', {
                reason: reason || ''
            });
        }
        interruptedListeningStatusUntil = 0;
    }

    function showInterruptedListeningStatus(reason) {
        var statusText = interruptedListeningStatusText();
        interruptedListeningStatusUntil = performance.now() + INTERRUPTED_LISTENING_STATUS_HOLD_MS;
        updateVoiceChatText(INTERRUPTED_LISTENING_STATUS_TEXT);
        showStatus(statusText, 'speech');
        clientLog('interrupted listening status shown', {
            reason: reason || '',
            holdMs: INTERRUPTED_LISTENING_STATUS_HOLD_MS
        });
    }

    function showSpeechErrorStatus(text, autoClearMs) {
        var nextText = String(text || '').trim() || '语音链路异常，已重置';
        if (speechErrorStatusTimer) {
            clearTimeout(speechErrorStatusTimer);
            speechErrorStatusTimer = null;
        }
        updateVoiceChatText(nextText, autoClearMs || 5000);
        showStatus(nextText, 'speech');
        if (autoClearMs > 0) {
            speechErrorStatusTimer = setTimeout(function () {
                speechErrorStatusTimer = null;
                if (
                    speechStatusText === nextText
                    && !isDialogBusy
                    && !isListening
                    && !streamingAudioPlaying
                    && streamingAudioQueue.length === 0
                    && !audio
                ) {
                    clearStatusBeforeDeferredSpeech();
                }
            }, autoClearMs);
        }
    }

    function fitModel() {
        if (!model) return;
        applyModelFit(model, currentModelConfig);
    }

    function applyModelFit(targetModel, config) {
        if (!targetModel) return;
        const w = app.screen.width;
        const h = app.screen.height;
        const fit = (config && config.fit) || {};
        const displayCentered = document.body.classList.contains('display-mode') || Boolean(document.fullscreenElement);
        targetModel.anchor.set(0.5, 0.5);
        const scale = Math.min(w / (fit.width || 1200), h / (fit.height || 2000)) * (fit.scale || 0.8);
        targetModel.scale.set(scale);
        const yRatio = displayCentered ? (fit.displayY || 0.5) : (fit.y || 0.52);
        targetModel.position.set(w / 2, h * yRatio);
    }

    function resize() {
        const rect = canvas.getBoundingClientRect();
        app.renderer.resize(rect.width, rect.height);
        fitModel();
    }

    async function playMotion(group, index) {
        if (!model) return;
        var motion = resolveMotion(group, index);
        try {
            var priority = PIXI.live2d.MotionPriority
                ? PIXI.live2d.MotionPriority.FORCE
                : 3;
            var started = await model.motion(motion[0], motion[1], priority);
            if (!started) {
                console.warn('Motion rejected:', motion[0], motion[1]);
            }
        } catch (e) {
            console.error('Motion error:', motion[0], motion[1], e);
        }
    }

    function setExpression(name) {
        if (!model) return;
        var expression = resolveExpression(name);
        if (!expression) return;
        try {
            model.expression(expression);
            document.querySelectorAll('#expression-buttons button').forEach(function (button) {
                button.classList.toggle('active', button.dataset.name === expression);
            });
        } catch (e) {
            console.error('Expression error:', expression, e);
        }
    }

    function normalizeExpressionName(name) {
        return String(name || '').replace(/\.exp3\.json$/i, '');
    }

    function resolveExpression(name) {
        var config = currentModelConfig || {};
        var expressions = config.expressions || {};
        var normalized = normalizeExpressionName(name);
        if (Object.prototype.hasOwnProperty.call(expressions, normalized)) {
            return expressions[normalized];
        }
        if (Object.prototype.hasOwnProperty.call(expressions, name)) {
            return expressions[name];
        }
        return expressions.Normal || null;
    }

    function getExpressionLabel(name) {
        var labels = {
            Angry: '生气',
            Blushing: '害羞',
            f01: '表情01',
            f02: '表情02',
            exp_01: '表情01',
            exp_02: '表情02',
            exp_03: '表情03',
            exp_04: '表情04',
            exp_05: '表情05',
            Normal: '正常',
            Sad: '悲伤',
            Smile: '微笑',
            Surprised: '惊讶'
        };
        var normalized = normalizeExpressionName(name);
        return labels[normalized] || normalized || name;
    }

    function resolveMotion(group, index) {
        var config = currentModelConfig || {};
        var map = config.motionMap || {};
        var mapped = map[group];
        if (mapped && mapped.length > 0) {
            return mapped[Math.abs(index || 0) % mapped.length];
        }

        var count = config.motionCounts && config.motionCounts[group];
        if (count) {
            return [group, Math.abs(index || 0) % count];
        }

        var idle = map.Idle && map.Idle[0];
        return idle || ['Idle', 0];
    }

    function playTTS(name, type) {
        if (performance.now() < ttsMutedUntil) return;
        if (!requestSpeechTurn('legacy_tts', SPEECH_PRIORITY_LEGACY_TTS, {
            lock: true,
            lockMs: 60000
        })) return;
        fixedSpeechPlaybackActive = true;
        activeFixedSpeechEventType = String(type || '');
        var requestId = ++ttsRequestId;
        if (audio) {
            audio.pause();
            audio = null;
        }
        stopLipSync();

        var variantCount = Math.max(1, ttsManifest[type] || 1);
        var variant = Math.floor(Math.random() * variantCount);
        var subtitleText = '';
        var audioStarted = false;
        var lastFixedSpeechStatusText = '';
        var playbackAudio = null;

        function refreshFixedSpeechStatus() {
            if (!subtitleText) return;
            var nextText = speechStatusTextForAudio(subtitleText, playbackAudio, 0);
            if (nextText && nextText !== lastFixedSpeechStatusText) {
                lastFixedSpeechStatusText = nextText;
                showStatus(nextText, 'speech');
                updateVoiceChatText(nextText);
            }
        }

        loadSubtitleText(name, type, variant).then(function (text) {
            subtitleText = text;
            if (audioStarted && subtitleText) {
                setAssistantSpeechText(subtitleText);
                refreshFixedSpeechStatus();
            }
        });

        var modelKey = currentModelKey || DEFAULT_MODEL_KEY;
        var audioUrl = '/tts?name=' + encodeURIComponent(name || '访客') + '&type=' + type + '&variant=' + variant + '&model=' + encodeURIComponent(modelKey);

        fetch(audioUrl)
            .then(function (res) {
                if (!res.ok) {
                    throw new Error('TTS HTTP ' + res.status);
                }
                return res.blob();
            })
            .then(function (blob) {
                if (requestId !== ttsRequestId) {
                    fixedSpeechPlaybackActive = false;
                    releaseFixedSpeechGuardSoon('legacy_tts');
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio('legacy_tts');
                    releaseSpeechPriority('legacy_tts');
                    return;
                }
                var objectUrl = URL.createObjectURL(blob);
                playbackAudio = new Audio(objectUrl);
                applyVoiceOutputVolume(playbackAudio);
                audio = playbackAudio;
                playbackAudio.addEventListener('playing', function () {
                    var selfMuteMs = estimateSelfSpeechMuteMs(playbackAudio, 9000);
                    audioStarted = true;
                    if (subtitleText) {
                        setAssistantSpeechText(subtitleText);
                    }
                    setVoicePhase('speaking', 'Speaking response', 0.68);
                    if (shouldProtectFixedSpeechFromVoice(type)) {
                        muteVoiceDetectionForSelfSpeech(selfMuteMs);
                        markFixedSpeechGuard('legacy_tts', selfMuteMs + fixedSpeechPostGuardMs);
                    } else {
                        clearSelfSpeechMuteNow('interruptible fixed speech');
                    }
                    startLipSync(playbackAudio);
                    refreshFixedSpeechStatus();
                });
                playbackAudio.addEventListener('timeupdate', refreshFixedSpeechStatus);
                playbackAudio.addEventListener('ended', function () {
                    URL.revokeObjectURL(objectUrl);
                    if (audio === playbackAudio) {
                        audio = null;
                    }
                    statusMode = 'idle';
                    if (lipSyncAudioElement === playbackAudio) {
                        stopLipSync();
                    }
                    hideSubtitle();
                    setVoicePhase('ready', 'Ready for next visitor', 0.18);
                    clearStatusBeforeDeferredSpeech();
                    clearVoiceChatText();
                    setAssistantSpeechText('');
                    fixedSpeechPlaybackActive = false;
                    releaseFixedSpeechGuardSoon('legacy_tts');
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio('legacy_tts');
                    releaseSpeechPriority('legacy_tts');
                    scheduleAvatarEventPump(100);
                });
                playbackAudio.addEventListener('error', function () {
                    URL.revokeObjectURL(objectUrl);
                    if (audio === playbackAudio) {
                        audio = null;
                    }
                    statusMode = 'idle';
                    if (lipSyncAudioElement === playbackAudio) {
                        stopLipSync();
                    }
                    hideSubtitle();
                    setVoicePhase('ready', 'Ready for next visitor', 0.18);
                    clearStatusBeforeDeferredSpeech();
                    clearVoiceChatText();
                    setAssistantSpeechText('');
                    fixedSpeechPlaybackActive = false;
                    releaseFixedSpeechGuardSoon('legacy_tts');
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio('legacy_tts');
                    releaseSpeechPriority('legacy_tts');
                    scheduleAvatarEventPump(100);
                });
                return playbackAudio.play();
            })
            .catch(function (err) {
                if (requestId !== ttsRequestId) {
                    fixedSpeechPlaybackActive = false;
                    releaseFixedSpeechGuardSoon('legacy_tts');
                    return;
                }
                statusMode = 'idle';
                stopLipSync();
                console.error('TTS play failed:', err);
                hideSubtitle();
                setVoicePhase('error', 'Recovering voice channel', 0.22);
                showSpeechErrorStatus('固定语音生成失败', 5000);
                setAssistantSpeechText('');
                fixedSpeechPlaybackActive = false;
                releaseFixedSpeechGuardSoon('legacy_tts');
                releaseShortSelfSpeechMuteSoon();
                forceReleaseLocalDialogAudio('legacy_tts');
                releaseSpeechPriority('legacy_tts');
                scheduleAvatarEventPump(100);
            });
    }

    async function playStreamingRawTTS(text, options, context) {
        var owner = context.owner;
        var modelKey = context.modelKey;
        var requestId = context.requestId;
        var estimatedMaxPlayMs = context.estimatedMaxPlayMs;
        var ttsRequestedAt = context.ttsRequestedAt;
        var audioUrl = '/tts-raw-stream?text=' + encodeURIComponent(text) + '&model=' + encodeURIComponent(modelKey);
        var ctx = ensureAudioContext();
        if (!ctx) {
            throw new Error('AudioContext is unavailable');
        }
        if (ctx.state === 'suspended') {
            await ctx.resume().catch(function () { });
        }

        var abortController = new AbortController();
        var stream = {
            owner: owner,
            abortController: abortController,
            cancelled: false,
            sources: [],
            gain: ctx.createGain(),
            scheduledUntil: 0,
            started: false,
            playbackStartedAt: 0,
            chunkCount: 0,
            totalBytes: 0,
            finishTimer: null,
            statusTimer: null,
            lastStatusText: '',
            timedOut: false
        };
        stream.gain.gain.value = voiceOutputVolume;
        stream.gain.connect(ctx.destination);
        activeFixedTtsStream = stream;

        if (options.signal) {
            if (options.signal.aborted) {
                abortController.abort();
            } else {
                options.signal.addEventListener('abort', function () {
                    abortController.abort();
                }, { once: true });
            }
        }

        function assertCurrent() {
            if (stream.cancelled || activeFixedTtsStream !== stream || requestId !== ttsRequestId) {
                throw new DOMException('TTS stream is obsolete', 'AbortError');
            }
        }

        function refreshStreamingStatus() {
            if (!stream.started) {
                return;
            }
            var elapsedMs = performance.now() - stream.playbackStartedAt;
            var nextText = voiceTurnPolicy.speechStatusTextAt(text, elapsedMs, estimatedMaxPlayMs);
            if (nextText && nextText !== stream.lastStatusText) {
                stream.lastStatusText = nextText;
                showStatus(nextText, 'speech');
                updateVoiceChatText(nextText);
            }
        }

        function startStreamPlayback() {
            if (stream.started) {
                return;
            }
            stream.started = true;
            stream.playbackStartedAt = performance.now();
            clientLog('raw tts stream playback started', {
                owner: owner,
                modelKey: modelKey,
                textChars: text.length,
                prepareMs: Math.round(performance.now() - ttsRequestedAt)
            });
            setAssistantSpeechText(text);
            setVoicePhase('speaking', 'Speaking response', 0.7);
            if (shouldProtectFixedSpeechFromVoice(options.eventType)) {
                muteVoiceDetectionForSelfSpeech(3500);
                markFixedSpeechGuard(owner, 3500 + fixedSpeechPostGuardMs);
            } else {
                clearSelfSpeechMuteNow('interruptible fixed speech');
            }
            stream.lipSyncToken = startExternalLipSync();
            refreshStreamingStatus();
            stream.statusTimer = setInterval(refreshStreamingStatus, 250);
        }

        function schedulePcmChunk(bytes, sampleRate) {
            assertCurrent();
            if (!bytes || bytes.length < 2) {
                return;
            }
            var buffer = pcm16BytesToAudioBuffer(ctx, bytes, sampleRate || 24000);
            var source = ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(stream.gain);
            source.onended = function () {
                var index = stream.sources.indexOf(source);
                if (index >= 0) {
                    stream.sources.splice(index, 1);
                }
            };
            var earliest = ctx.currentTime + 0.02;
            var startAt = Math.max(earliest, stream.scheduledUntil || earliest);
            source.start(startAt);
            stream.sources.push(source);
            stream.scheduledUntil = startAt + buffer.duration;
            stream.chunkCount += 1;
            stream.totalBytes += bytes.length;
            if (shouldProtectFixedSpeechFromVoice(options.eventType)) {
                muteVoiceDetectionForSelfSpeech(2600);
                markFixedSpeechGuard(owner, 2600 + fixedSpeechPostGuardMs);
            }
            startStreamPlayback();
        }

        function cleanup(keepSubtitle) {
            if (activeFixedTtsStream === stream) {
                activeFixedTtsStream = null;
            }
            if (stream.statusTimer) {
                clearInterval(stream.statusTimer);
                stream.statusTimer = null;
            }
            if (stream.finishTimer) {
                clearTimeout(stream.finishTimer);
                stream.finishTimer = null;
            }
            if (stream.gain) {
                try {
                    stream.gain.disconnect();
                } catch (err) { }
            }
            releaseFixedSpeechGuardSoon(owner);
            statusMode = 'idle';
            if (stream.lipSyncToken) {
                stopLipSync(stream.lipSyncToken);
            }
            if (!keepSubtitle) {
                hideSubtitle();
            }
            if (isFixedSpeechOwner(owner)) {
                fixedSpeechPlaybackActive = false;
            }
            releaseShortSelfSpeechMuteSoon();
            forceReleaseLocalDialogAudio(owner);
            setVoicePhase('ready', 'Ready for next visitor', 0.18);
            clearStatusBeforeDeferredSpeech();
            clearVoiceChatText();
            setAssistantSpeechText('');
            releaseSpeechPriority(owner);
            scheduleAvatarEventPump(100);
        }

        function waitForScheduledAudio() {
            return new Promise(function (resolve) {
                var remainingMs = Math.max(0, (stream.scheduledUntil - ctx.currentTime) * 1000);
                stream.finishTimer = setTimeout(resolve, remainingMs + 120);
            });
        }

        var playTimeout = setTimeout(function () {
            stream.timedOut = true;
            cancelActiveFixedTtsStream('raw tts stream timeout');
        }, Math.max(15000, estimatedMaxPlayMs + 10000));

        try {
            var res = await fetch(audioUrl, { signal: abortController.signal });
            assertCurrent();
            if (!res.ok) {
                throw new Error('TTS stream HTTP ' + res.status);
            }
            if (!res.body || typeof res.body.getReader !== 'function') {
                throw new Error('TTS stream reader is unavailable');
            }
            var reader = res.body.getReader();
            var decoder = new TextDecoder('utf-8');
            var pending = '';
            var sampleRate = 24000;
            while (true) {
                assertCurrent();
                var read = await reader.read();
                if (read.done) {
                    break;
                }
                pending += decoder.decode(read.value, { stream: true });
                var lines = pending.split('\n');
                pending = lines.pop() || '';
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line) {
                        continue;
                    }
                    var message = JSON.parse(line);
                    if (message.type === 'start') {
                        sampleRate = Number(message.sampleRate) || sampleRate;
                    } else if (message.type === 'audio') {
                        sampleRate = Number(message.sampleRate) || sampleRate;
                        schedulePcmChunk(base64ToUint8Array(message.audio), sampleRate);
                    } else if (message.type === 'error') {
                        throw new Error(message.error || 'TTS stream failed');
                    }
                }
            }
            pending += decoder.decode();
            if (pending.trim()) {
                var trailing = JSON.parse(pending.trim());
                if (trailing.type === 'audio') {
                    schedulePcmChunk(base64ToUint8Array(trailing.audio), Number(trailing.sampleRate) || sampleRate);
                } else if (trailing.type === 'error') {
                    throw new Error(trailing.error || 'TTS stream failed');
                }
            }
            if (!stream.started || stream.chunkCount <= 0) {
                throw new Error('TTS stream returned no audio');
            }
            await waitForScheduledAudio();
            assertCurrent();
            clientLog('raw tts stream playback ended', {
                owner: owner,
                modelKey: modelKey,
                textChars: text.length,
                chunks: stream.chunkCount,
                audioBytes: stream.totalBytes,
                elapsedMs: Math.round(performance.now() - ttsRequestedAt)
            });
            cleanup(options.keepSubtitle);
        } catch (err) {
            if (err && err.name === 'AbortError') {
                if (stream.timedOut) {
                    cleanup(false);
                    throw new Error('TTS stream timeout');
                }
                cleanup(false);
                return;
            }
            cleanup(false);
            throw err;
        } finally {
            clearTimeout(playTimeout);
        }
    }

    function playRawTTS(text, options) {
        if (!text) return Promise.resolve();
        options = options || {};
        var owner = options.owner || 'local_dialog';
        var priority = Number.isFinite(Number(options.priority))
            ? Number(options.priority)
            : getLocalDialogPriority();
        if (!requestSpeechTurn(owner, priority, {
            force: Boolean(options.forceSpeech),
            lock: true,
            lockMs: options.lockMs || DIALOG_AUDIO_LOCK_MAX_MS
        })) {
            updateVoiceChatText('当前有更高优先级语音正在播放');
            return Promise.resolve();
        }
        if (isFixedSpeechOwner(owner)) {
            activeFixedSpeechEventType = String(options.eventType || '');
            fixedSpeechPlaybackActive = true;
        }
        var requestId = ++ttsRequestId;
        cancelActiveFixedTtsStream('new raw tts request');
        if (audio) {
            audio.pause();
            audio = null;
        }
        stopLipSync();

        var modelKey = options.modelKey || currentModelKey || DEFAULT_MODEL_KEY;
        var audioUrl = '/tts-raw?text=' + encodeURIComponent(text) + '&model=' + encodeURIComponent(modelKey);
        var estimatedMaxPlayMs = options.maxPlayMs || Math.min(45000, Math.max(10000, text.length * 450));
        var syncSpeechTextWithPlayback = options.syncSpeechTextWithPlayback !== false;
        var ttsRequestedAt = performance.now();
        if (owner === 'local_dialog') {
            activeLocalDialogPlaybackText = String(options.statusText || text || '').trim();
            activeLocalDialogPlaybackEstimatedMs = estimatedMaxPlayMs;
        }
        var initialSpeechStatusText = voiceTurnPolicy.speechStatusTextAt(
            options.statusText || text,
            0,
            estimatedMaxPlayMs
        );
        if (syncSpeechTextWithPlayback) {
            var preparingText = String(options.preparingText || '').trim();
            if (preparingText) {
                showStatus(voiceTurnPolicy.statusText('processing', preparingText), 'speech');
                updateVoiceChatText(preparingText);
            } else {
                clearStatusBeforeDeferredSpeech();
                clearVoiceChatText();
                setAssistantSpeechText('');
            }
        } else {
            showStatus(initialSpeechStatusText, 'speech');
            if (initialSpeechStatusText) {
                updateVoiceChatText(initialSpeechStatusText);
            }
            setAssistantSpeechText(text);
        }
        clientLog('raw tts request started', {
            owner: owner,
            modelKey: modelKey,
            textChars: text.length,
            syncSpeechTextWithPlayback: syncSpeechTextWithPlayback
        });
        var fetchOptions = {};
        if (options.signal) {
            fetchOptions.signal = options.signal;
        }

        if (shouldStreamRawTTS(owner)) {
            return playStreamingRawTTS(text, options, {
                owner: owner,
                modelKey: modelKey,
                requestId: requestId,
                estimatedMaxPlayMs: estimatedMaxPlayMs,
                syncSpeechTextWithPlayback: syncSpeechTextWithPlayback,
                ttsRequestedAt: ttsRequestedAt
            }).catch(function (err) {
                if (err && err.name === 'AbortError') {
                    if (isFixedSpeechOwner(owner)) {
                        fixedSpeechPlaybackActive = false;
                    }
                    releaseFixedSpeechGuardSoon(owner);
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio(owner);
                    releaseSpeechPriority(owner);
                    scheduleAvatarEventPump(100);
                    console.info('Raw TTS stream aborted:', owner, modelKey);
                    return;
                }
                if (isFixedSpeechOwner(owner)) {
                    fixedSpeechPlaybackActive = false;
                }
                releaseFixedSpeechGuardSoon(owner);
                releaseShortSelfSpeechMuteSoon();
                forceReleaseLocalDialogAudio(owner);
                setVoicePhase('error', 'Recovering voice channel', 0.22);
                releaseSpeechPriority(owner);
                scheduleAvatarEventPump(100);
                throw err;
            });
        }

        return fetch(audioUrl, fetchOptions)
            .then(function (res) {
                if (!res.ok) {
                    throw new Error('TTS HTTP ' + res.status);
                }
                return res.blob();
            })
            .then(function (blob) {
                if (requestId !== ttsRequestId) {
                    if (isFixedSpeechOwner(owner)) {
                        fixedSpeechPlaybackActive = false;
                    }
                    releaseFixedSpeechGuardSoon(owner);
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio(owner);
                    releaseSpeechPriority(owner);
                    return;
                }
                var objectUrl = URL.createObjectURL(blob);
                var playbackAudio = new Audio(objectUrl);
                applyVoiceOutputVolume(playbackAudio);
                audio = playbackAudio;
                return new Promise(function (resolve, reject) {
                    var settled = false;
                    var lastRawSpeechStatusText = '';
                    var playbackStarted = false;
                    var playbackStartTimer = setTimeout(function () {
                        finish(function () {
                            clientLog('raw tts playback start timeout', {
                                owner: owner,
                                modelKey: modelKey,
                                textChars: text.length,
                                readyState: playbackAudio.readyState,
                                networkState: playbackAudio.networkState,
                                duration: Number.isFinite(playbackAudio.duration) ? playbackAudio.duration : null
                            });
                            cleanup(false);
                            reject(new Error('audio playback did not start'));
                        });
                    }, options.playStartTimeoutMs || 5000);
                    var playTimer = setTimeout(function () {
                        finish(function () {
                            cleanup(false);
                            reject(new Error('audio playback timeout'));
                        });
                    }, estimatedMaxPlayMs);

                    function finish(fn) {
                        if (settled) return;
                        settled = true;
                        clearTimeout(playbackStartTimer);
                        clearTimeout(playTimer);
                        fn();
                    }

                    function cleanup(keepSubtitle) {
                        URL.revokeObjectURL(objectUrl);
                        if (isFixedSpeechOwner(owner)) {
                            fixedSpeechPlaybackActive = false;
                        }
                        releaseFixedSpeechGuardSoon(owner);
                        if (audio === playbackAudio) {
                            audio = null;
                        }
                        statusMode = 'idle';
                        if (lipSyncAudioElement === playbackAudio) {
                            stopLipSync();
                        }
                        if (!keepSubtitle) {
                            hideSubtitle();
                        }
                        if (owner === 'local_dialog') {
                            releaseSelfSpeechMuteSoon();
                            releaseLocalDialogAudio(owner);
                            activeLocalDialogPlaybackText = '';
                            activeLocalDialogPlaybackEstimatedMs = 0;
                        } else {
                            releaseShortSelfSpeechMuteSoon();
                            forceReleaseLocalDialogAudio(owner);
                            setVoicePhase('ready', 'Ready for next visitor', 0.18);
                            clearStatusBeforeDeferredSpeech();
                            clearVoiceChatText();
                            setAssistantSpeechText('');
                        }
                        releaseSpeechPriority(owner);
                        scheduleAvatarEventPump(100);
                    }

                    function refreshRawSpeechStatus() {
                        var nextText = speechStatusTextForAudio(text, playbackAudio, estimatedMaxPlayMs);
                        if (nextText && nextText !== lastRawSpeechStatusText) {
                            lastRawSpeechStatusText = nextText;
                            showStatus(nextText, 'speech');
                            updateVoiceChatText(nextText);
                        }
                    }

                    playbackAudio.addEventListener('playing', function () {
                        playbackStarted = true;
                        clearTimeout(playbackStartTimer);
                        clientLog('raw tts playback started', {
                            owner: owner,
                            modelKey: modelKey,
                            textChars: text.length,
                            prepareMs: Math.round(performance.now() - ttsRequestedAt),
                            duration: Number.isFinite(playbackAudio.duration) ? playbackAudio.duration : null
                        });
                        setAssistantSpeechText(text);
                        var selfMuteMs = estimateSelfSpeechMuteMs(playbackAudio, 12000);
                        setVoicePhase('speaking', 'Speaking response', 0.7);
                        if (shouldProtectFixedSpeechFromVoice(options.eventType)) {
                            muteVoiceDetectionForSelfSpeech(selfMuteMs);
                            markFixedSpeechGuard(owner, selfMuteMs + fixedSpeechPostGuardMs);
                        } else {
                            clearSelfSpeechMuteNow('interruptible fixed speech');
                        }
                        startLipSync(playbackAudio);
                        refreshRawSpeechStatus();
                    });
                    playbackAudio.addEventListener('loadedmetadata', function () {
                        clientLog('raw tts metadata loaded', {
                            owner: owner,
                            modelKey: modelKey,
                            textChars: text.length,
                            duration: Number.isFinite(playbackAudio.duration) ? playbackAudio.duration : null
                        });
                    });
                    playbackAudio.addEventListener('canplay', function () {
                        if (!playbackStarted) {
                            clientLog('raw tts canplay before start', {
                                owner: owner,
                                modelKey: modelKey,
                                textChars: text.length,
                                readyState: playbackAudio.readyState,
                                networkState: playbackAudio.networkState
                            });
                        }
                    });
                    playbackAudio.addEventListener('timeupdate', refreshRawSpeechStatus);
                    playbackAudio.addEventListener('ended', function () {
                        finish(function () {
                            cleanup(options.keepSubtitle);
                            if (owner === 'local_dialog') {
                                if (options.showCompletionTextOnEnd) {
                                    updateVoiceChatText('播放完成');
                                } else if (options.clearSpeechDisplayOnEnd) {
                                    clearStreamingSpeechDisplay();
                                } else {
                                    clearVoiceChatText();
                                    setAssistantSpeechText('');
                                }
                            }
                            resolve();
                        });
                    });
                    playbackAudio.addEventListener('error', function () {
                        finish(function () {
                            clientLog('raw tts playback error', {
                                owner: owner,
                                modelKey: modelKey,
                                textChars: text.length,
                                readyState: playbackAudio.readyState,
                                networkState: playbackAudio.networkState,
                                errorCode: playbackAudio.error && playbackAudio.error.code || null
                            });
                            cleanup(false);
                            reject(new Error('audio playback failed'));
                        });
                    });
                    playbackAudio.play().catch(function (err) {
                        finish(function () {
                            clientLog('raw tts play promise rejected', {
                                owner: owner,
                                modelKey: modelKey,
                                textChars: text.length,
                                error: err && err.message ? err.message : String(err || '')
                            });
                            cleanup(false);
                            reject(err);
                        });
                    });
                });
            })
            .catch(function (err) {
                if (err && err.name === 'AbortError') {
                    if (isFixedSpeechOwner(owner)) {
                        fixedSpeechPlaybackActive = false;
                    }
                    releaseFixedSpeechGuardSoon(owner);
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio(owner);
                    releaseSpeechPriority(owner);
                    scheduleAvatarEventPump(100);
                    console.info('Raw TTS aborted:', owner, modelKey);
                    return;
                }
                if (owner === 'local_dialog') {
                    releaseSelfSpeechMuteSoon();
                    releaseLocalDialogAudio(owner);
                    activeLocalDialogPlaybackText = '';
                    activeLocalDialogPlaybackEstimatedMs = 0;
                } else {
                    releaseFixedSpeechGuardSoon(owner);
                    releaseShortSelfSpeechMuteSoon();
                    forceReleaseLocalDialogAudio(owner);
                }
                if (isFixedSpeechOwner(owner)) {
                    fixedSpeechPlaybackActive = false;
                }
                setVoicePhase('error', 'Recovering voice channel', 0.22);
                releaseSpeechPriority(owner);
                scheduleAvatarEventPump(100);
                if (owner.indexOf('model_switch') === 0) {
                    updateVoiceChatText('切换话术播放失败：' + (err && err.message ? err.message : err), 4000);
                }
                throw err;
            });
    }

    function requestSpeechTurn(owner, priority, options) {
        options = options || {};
        owner = owner || 'legacy_tts';
        priority = normalizeSpeechPriority(priority, SPEECH_PRIORITY_FIXED_DEFAULT);
        pruneDialogAudioLocks();

        if (activeSpeechPriority > priority) {
            return false;
        }
        var lockedByOtherOwner = activeSpeechOwner
            && activeSpeechOwner !== owner
            && isAudioLockedForOtherOwner(owner);
        if (lockedByOtherOwner && activeSpeechPriority >= priority) {
            return false;
        }

        var shouldPreempt = voiceTurnPolicy.shouldPreemptSpeechTurn({
            activeOwner: activeSpeechOwner,
            incomingOwner: owner,
            activePriority: activeSpeechPriority,
            incomingPriority: priority,
            force: options.force
        });
        if (shouldPreempt) {
            clientLog('preempt speech turn by priority', {
                activeOwner: activeSpeechOwner,
                incomingOwner: owner,
                activePriority: activeSpeechPriority,
                incomingPriority: priority
            });
            stopCurrentAudio();
        }

        activeSpeechOwner = owner;
        activeSpeechPriority = priority;
        if (options.lock !== false) {
            lockLocalDialogAudio(options.lockMs || DIALOG_AUDIO_LOCK_MAX_MS, owner);
        }
        return true;
    }

    function acquireSpeechPriority(owner, priority) {
        return requestSpeechTurn(owner, priority, { lock: false });
    }

    function normalizeSpeechPriority(value, fallback) {
        var priority = Number(value);
        if (Number.isFinite(priority)) {
            return priority;
        }
        return fallback;
    }

    function releaseSpeechPriority(owner) {
        if (!owner || activeSpeechOwner === owner) {
            if (isFixedSpeechOwner(activeSpeechOwner) || isFixedSpeechOwner(owner)) {
                activeFixedSpeechEventType = '';
            }
            activeSpeechOwner = '';
            activeSpeechPriority = 0;
        }
    }

    function muteVoiceDetectionForSelfSpeech(holdMs) {
        selfSpeechMutedUntil = Math.max(selfSpeechMutedUntil, performance.now() + Math.max(0, holdMs || 0));
    }

    function estimateSelfSpeechMuteMs(audioElement, fallbackMs) {
        var durationMs = audioElement && Number.isFinite(audioElement.duration)
            ? Math.round(audioElement.duration * 1000)
            : 0;
        if (durationMs > 0) {
            return Math.min(20000, Math.max(2500, durationMs + 1200));
        }
        return Math.max(2500, Math.min(12000, fallbackMs || 6000));
    }

    function speechStatusTextForAudio(text, audioElement, fallbackDurationMs) {
        var progressMs = audioElement
            ? Math.max(0, Math.round((audioElement.currentTime || 0) * 1000))
            : 0;
        var durationMs = audioElement && Number.isFinite(audioElement.duration)
            ? Math.round(audioElement.duration * 1000)
            : Number(fallbackDurationMs || 0);
        return voiceTurnPolicy.speechStatusTextAt(text, progressMs, durationMs);
    }

    function speechStatusTextForStreamingAudio(text, audioElement, fallbackDurationMs, turnId) {
        var progressMs = audioElement
            ? Math.max(0, Math.round((audioElement.currentTime || 0) * 1000))
            : 0;
        var durationMs = audioElement && Number.isFinite(audioElement.duration)
            ? Math.round(audioElement.duration * 1000)
            : Number(fallbackDurationMs || 0);
        var isDialogSilenceFeedback = Boolean(
            voiceDialogSilenceFeedbackActive
            && voiceDialogSilenceFeedbackTurnId === turnId
            && voiceDialogSilenceFeedbackText
        );
        var statusText = isDialogSilenceFeedback
            ? voiceDialogSilenceFeedbackText
            : text;
        return voiceTurnPolicy.speechStatusTextAt(
            statusText,
            progressMs,
            durationMs,
            { keepFullText: isDialogSilenceFeedback }
        );
    }

    function remainingSpeechTextForAudio(text, audioElement, fallbackDurationMs) {
        var value = String(text || '').replace(/\s+/g, ' ').trim();
        if (!value) return '';
        var segments = voiceTurnPolicy.speechStatusSegments(value);
        if (segments.length <= 1) return value;
        var progressMs = audioElement
            ? Math.max(0, Math.round((audioElement.currentTime || 0) * 1000))
            : 0;
        var durationMs = audioElement && Number.isFinite(audioElement.duration)
            ? Math.round(audioElement.duration * 1000)
            : Number(fallbackDurationMs || 0);
        if (durationMs <= 0 || progressMs <= 0) {
            return value;
        }
        var totalWeight = segments.reduce(function (sum, segment) {
            return sum + Math.max(1, segment.length);
        }, 0);
        var cursor = Math.min(0.999, progressMs / durationMs) * totalWeight;
        var accumulated = 0;
        for (var i = 0; i < segments.length; i += 1) {
            accumulated += Math.max(1, segments[i].length);
            if (cursor < accumulated) {
                return segments.slice(i).join('').trim();
            }
        }
        return segments[segments.length - 1] || value;
    }

    function shouldStreamRawTTS(owner) {
        return isFixedSpeechOwner(owner);
    }

    function cancelActiveFixedTtsStream(reason) {
        var stream = activeFixedTtsStream;
        if (!stream) {
            return;
        }
        activeFixedTtsStream = null;
        stream.cancelled = true;
        if (stream.finishTimer) {
            clearTimeout(stream.finishTimer);
        }
        if (stream.statusTimer) {
            clearInterval(stream.statusTimer);
        }
        if (stream.abortController) {
            try {
                stream.abortController.abort();
            } catch (err) { }
        }
        (stream.sources || []).forEach(function (source) {
            try {
                source.stop();
            } catch (err) { }
        });
        if (stream.gain) {
            try {
                stream.gain.disconnect();
            } catch (err) { }
        }
        clientLog('raw tts stream cancelled locally', {
            owner: stream.owner,
            reason: reason || '',
            chunks: stream.chunkCount || 0,
            bytes: stream.totalBytes || 0
        });
    }

    function base64ToUint8Array(value) {
        var binary = atob(value || '');
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes;
    }

    function pcm16BytesToAudioBuffer(ctx, bytes, sampleRate) {
        var sampleCount = Math.floor(bytes.length / 2);
        var buffer = ctx.createBuffer(1, sampleCount, sampleRate);
        var channel = buffer.getChannelData(0);
        for (var i = 0; i < sampleCount; i++) {
            var sample = bytes[i * 2] | (bytes[i * 2 + 1] << 8);
            if (sample >= 0x8000) {
                sample -= 0x10000;
            }
            channel[i] = Math.max(-1, Math.min(1, sample / 32768));
        }
        return buffer;
    }

    function releaseSelfSpeechMuteSoon() {
        muteVoiceDetectionForSelfSpeech(SELF_SPEECH_RELEASE_GRACE_MS);
    }

    function clearSelfSpeechMuteNow(reason) {
        var previousMutedMs = Math.max(0, Math.round(selfSpeechMutedUntil - performance.now()));
        selfSpeechMutedUntil = 0;
        if (previousMutedMs > 0) {
            clientLog('self speech mute cleared', {
                reason: reason || 'voice turn start',
                previousMutedMs: previousMutedMs
            });
        }
    }

    function releaseStreamingSelfSpeechMuteSoon() {
        selfSpeechMutedUntil = Math.min(
            selfSpeechMutedUntil,
            performance.now() + STREAMING_SELF_SPEECH_RELEASE_GRACE_MS
        );
    }

    function releaseShortSelfSpeechMuteSoon() {
        selfSpeechMutedUntil = Math.min(
            selfSpeechMutedUntil,
            performance.now() + STREAMING_SELF_SPEECH_RELEASE_GRACE_MS
        );
    }

    function isFixedSpeechOwner(owner) {
        return owner === 'legacy_tts';
    }

    function canUserBargeInFixedSpeech(eventType) {
        return voiceTurnPolicy.canUserBargeInFixedSpeech(eventType);
    }

    function shouldProtectFixedSpeechFromVoice(eventType) {
        return !canUserBargeInFixedSpeech(eventType);
    }

    function markFixedSpeechGuard(owner, holdMs) {
        if (!fixedSpeechNoiseGuardEnabled || !isFixedSpeechOwner(owner)) {
            return;
        }
        var guardMs = Math.max(0, holdMs || 0);
        var nextGuardUntil = performance.now() + guardMs;
        if (!fixedSpeechActive || nextGuardUntil > fixedSpeechGuardUntil + 250) {
            clientLog('fixed speech noise guard active', {
                owner: owner,
                holdMs: Math.round(guardMs),
                postGuardMs: fixedSpeechPostGuardMs
            });
        }
        fixedSpeechActive = true;
        fixedSpeechGuardUntil = Math.max(
            fixedSpeechGuardUntil,
            nextGuardUntil
        );
    }

    function releaseFixedSpeechGuardSoon(owner) {
        if (!isFixedSpeechOwner(owner)) {
            return;
        }
        fixedSpeechActive = false;
        restoreDialogSilenceStatusIfNeeded();
        if (canUserBargeInFixedSpeech(activeFixedSpeechEventType)) {
            fixedSpeechGuardUntil = 0;
            return;
        }
        if (fixedSpeechNoiseGuardEnabled) {
            clientLog('fixed speech noise guard tail', {
                owner: owner,
                postGuardMs: fixedSpeechPostGuardMs
            });
            fixedSpeechGuardUntil = Math.max(
                fixedSpeechGuardUntil,
                performance.now() + Math.max(0, fixedSpeechPostGuardMs)
            );
        }
    }

    function isFixedSpeechGuardActive() {
        return Boolean(
            fixedSpeechNoiseGuardEnabled
            && (fixedSpeechActive || performance.now() < fixedSpeechGuardUntil)
        );
    }

    function applyFixedSpeechNoiseGuardSettings(data) {
        data = data || {};
        fixedSpeechNoiseGuardEnabled = data.fixedSpeechNoiseGuardEnabled !== false;
        fixedSpeechPostGuardMs = Math.max(0, Number(data.fixedSpeechPostGuardMs) || 1200);
        if (!fixedSpeechNoiseGuardEnabled) {
            fixedSpeechActive = false;
            fixedSpeechGuardUntil = 0;
        }
    }

    function isSelfSpeechActive() {
        var fixedSpeechAllowsBargeIn = canUserBargeInFixedSpeech(activeFixedSpeechEventType);
        if (isFixedSpeechGuardActive() && !fixedSpeechAllowsBargeIn) {
            return true;
        }
        if (performance.now() < selfSpeechMutedUntil && !fixedSpeechAllowsBargeIn) {
            return true;
        }
        if (isAssistantResponseActive()) {
            return true;
        }
        if (isFixedSpeechOwner(activeSpeechOwner)) {
            return !fixedSpeechAllowsBargeIn;
        }
        return activeSpeechOwner && activeSpeechOwner !== 'local_dialog';
    }

    function isAssistantResponseActive() {
        return voiceTurnPolicy.isRealtimeDialogResponseActive({
            activeSpeechOwner: activeSpeechOwner,
            isDialogBusy: isDialogBusy,
            isListening: isListening,
            streamingAudioPlaying: streamingAudioPlaying,
            streamingAudioQueueLength: streamingAudioQueue.length,
            streamingAudioDone: streamingAudioDone,
            streamingPlaybackStarted: streamingPlaybackStarted,
            hasAudio: Boolean(audio)
        });
    }

    function isDialogSilenceFeedbackProtected() {
        return Boolean(voiceDialogSilenced && voiceDialogSilenceFeedbackActive);
    }

    function isInterruptibleFixedSpeechActive() {
        return Boolean(
            isFixedSpeechOwner(activeSpeechOwner)
            && canUserBargeInFixedSpeech(activeFixedSpeechEventType)
            && (audio || (activeFixedTtsStream && activeFixedTtsStream.started))
        );
    }

    function lockLocalDialogAudio(holdMs, owner) {
        owner = owner || 'local_dialog';
        holdMs = Math.max(1000, Math.min(DIALOG_AUDIO_LOCK_MAX_MS, holdMs || DIALOG_AUDIO_LOCK_MAX_MS));
        dialogAudioLockOwners[owner] = Math.max(dialogAudioLockOwners[owner] || 0, performance.now() + holdMs);
        dialogAudioLockedUntil = getDialogAudioLockedUntil();
        ttsMutedUntil = Math.max(ttsMutedUntil, dialogAudioLockedUntil);
        postDialogAudioLock(true, holdMs, owner);
    }

    function releaseLocalDialogAudio(owner) {
        owner = owner || 'local_dialog';
        if (dialogAudioLockTimers[owner]) {
            clearTimeout(dialogAudioLockTimers[owner]);
        }
        dialogAudioLockOwners[owner] = performance.now() + DIALOG_AUDIO_RELEASE_GRACE_MS;
        dialogAudioLockedUntil = getDialogAudioLockedUntil();
        ttsMutedUntil = Math.max(ttsMutedUntil, dialogAudioLockedUntil);
        postDialogAudioLock(false, DIALOG_AUDIO_RELEASE_GRACE_MS, owner);
        dialogAudioLockTimers[owner] = setTimeout(function () {
            delete dialogAudioLockTimers[owner];
            pruneDialogAudioLocks();
            releaseSpeechPriority(owner);
            scheduleAvatarEventPump(100);
        }, DIALOG_AUDIO_RELEASE_GRACE_MS);
    }

    function forceReleaseLocalDialogAudio(owner) {
        owner = owner || 'local_dialog';
        if (dialogAudioLockTimers[owner]) {
            clearTimeout(dialogAudioLockTimers[owner]);
            delete dialogAudioLockTimers[owner];
        }
        delete dialogAudioLockOwners[owner];
        dialogAudioLockedUntil = getDialogAudioLockedUntil();
        postDialogAudioLock(false, 0, owner);
        releaseSpeechPriority(owner);
        scheduleAvatarEventPump(100);
    }

    function forceResetVoiceLayer(reason, options) {
        options = options || {};
        console.warn('Voice layer force reset:', reason || 'unknown');
        if (!options.preserveEmptyBargeResume) {
            clearEmptyBargeResume(reason || 'voice layer reset');
        }
        clearStreamingDialogWatchdog();
        clearVoiceAsrFinalWatchdog();
        clearExternalSpeechWatchdog();
        streamingAudioQueue.forEach(function (item) {
            if (item.url) URL.revokeObjectURL(item.url);
        });
        if (streamingAudioActiveItem && streamingAudioActiveItem.url) {
            URL.revokeObjectURL(streamingAudioActiveItem.url);
        }
        streamingAudioQueue = [];
        streamingAudioPlaying = false;
        streamingAudioDone = true;
        streamingPlaybackStarted = false;
        streamingAudioActiveItem = null;
        streamingPlayedMsByReply = {};
        streamingPlaybackAckSent = false;
        if (streamingAudioProgressTimer) {
            clearInterval(streamingAudioProgressTimer);
            streamingAudioProgressTimer = null;
        }
        voicePendingInputFrames = [];
        voicePcmPacketRemainder = new Uint8Array(0);
        voiceSentBytesThisTurn = 0;
        voiceUserSpeechDetectedThisTurn = false;
        if (audio) {
            audio.pause();
            audio = null;
        }
        activeLocalDialogPlaybackText = '';
        activeLocalDialogPlaybackEstimatedMs = 0;
        finishDialogSilenceFeedback('force_reset');
        cancelActiveFixedTtsStream('force reset voice layer');
        stopLipSync();
        hideSubtitle();
        isListening = false;
        isDialogBusy = false;
        voiceStopRequested = false;
        emptyBargeResumePlaybackActive = false;
        if (voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
            voiceStreamWs.close();
        }
        voiceStreamWs = null;
        voiceStreamKeepOpen = false;
        voicePersonSession = null;
        Object.keys(dialogAudioLockTimers).forEach(function (owner) {
            clearTimeout(dialogAudioLockTimers[owner]);
        });
        dialogAudioLockTimers = {};
        var ownersToRelease = Object.keys(dialogAudioLockOwners).concat([
            'local_dialog',
            'doubao_realtime',
            'legacy_tts',
            'model_switch'
        ]);
        ownersToRelease.forEach(function (owner, index) {
            if (owner && ownersToRelease.indexOf(owner) === index) {
                forceReleaseLocalDialogAudio(owner);
            }
        });
        activeSpeechOwner = '';
        activeSpeechPriority = 0;
        dialogAudioLockOwners = {};
        dialogAudioLockedUntil = 0;
        releaseSelfSpeechMuteSoon();
        clearStreamingSpeechDisplay();
        setVoicePhase('ready', 'Ready for next visitor', 0.18);
    }

    function handleAvatarSessionUnavailable(message, detail) {
        avatarSessionValid = false;
        voiceStreamUrl = '';
        voiceDeviceId = '';
        voiceTenantId = '';
        voiceSiteId = '';
        if (voiceStreamWs || isListening || isDialogBusy || streamingAudioPlaying || audio) {
            forceResetVoiceLayer('avatar session unavailable');
        }
        if (voiceChatButton) {
            safeBtn(voiceChatButton, 'disabled', true);
            safeBtn(voiceChatButton, 'textContent', '设备会话失效');
        }
        var text = message || '设备会话失效，请从客户端重新打开前台';
        updateVoiceChatText(text);
        showStatus(text, 'speech');
        setVoicePhase('error', 'Avatar device session unavailable', 0.2);
        clientLog('avatar session unavailable', detail || null);
    }

    function applyDialogSettingsData(data) {
        data = data || {};
        avatarSessionValid = data.avatarSessionValid !== false && Boolean(data.tenantId && data.deviceId);
        if (!avatarSessionValid) {
            handleAvatarSessionUnavailable('设备会话失效，请从客户端重新打开前台', {
                tenantId: data.tenantId || '',
                deviceId: data.deviceId || ''
            });
            return data;
        }
        dialogPriorityMode = Number.isFinite(Number(data.priorityMode))
            ? Number(data.priorityMode)
            : 0;
        realtimeDialogEnabled = Boolean(data.realtimeDialogEnabled);
        realtimeRagEnabled = Boolean(data.realtimeRagEnabled);
        voiceStreamUrl = data.voiceStreamUrl || '';
        voiceStreamBackend = data.voiceBackend || 'cascade';
        voiceVadSilenceMs = Math.max(1000, Number(data.voiceClientVadSilenceMs) || 1400);
        voiceDeviceId = data.deviceId || '';
        voiceTenantId = data.tenantId || '';
        voiceSiteId = data.siteId || '';
        applyFixedSpeechNoiseGuardSettings(data);
        if (data.interactionMode) {
            interactionMode = data.interactionMode;
        }
        if (voiceChatButton) {
            safeBtn(voiceChatButton, 'disabled', false);
            safeBtn(voiceChatButton, 'textContent', '开始说话');
        }
        return data;
    }

    function handleDialogSettingsError(err) {
        handleAvatarSessionUnavailable(avatarSessionUnavailableText(err), {
            status: err && err.status,
            error: err && err.message ? err.message : String(err || 'unknown'),
            payload: err && err.payload
        });
    }

    function isLocalDialogAudioLocked() {
        dialogAudioLockedUntil = getDialogAudioLockedUntil();
        return performance.now() < dialogAudioLockedUntil || activeSpeechOwner === 'local_dialog';
    }

    function isAudioLockedForOtherOwner(owner) {
        if (owner === 'local_dialog' || owner === 'doubao_realtime') {
            return false;
        }
        pruneDialogAudioLocks();
        var now = performance.now();
        var lockedByOtherOwner = Object.keys(dialogAudioLockOwners).some(function (lockOwner) {
            return lockOwner !== owner && (dialogAudioLockOwners[lockOwner] || 0) > now;
        });
        return lockedByOtherOwner || activeSpeechOwner === 'local_dialog';
    }

    function isStreamingDialogIdle() {
        return voiceTurnPolicy.isStreamingDialogIdle({
            streamingAudioDone: streamingAudioDone,
            isListening: isListening,
            streamingAudioPlaying: streamingAudioPlaying,
            streamingAudioQueueLength: streamingAudioQueue.length,
            voiceStreamOpen: Boolean(voiceStreamWs),
            voiceStreamKeepOpen: voiceStreamKeepOpen
        });
    }

    function releaseStreamingDialogIfIdle(statusText) {
        acknowledgeStreamingPlaybackIfReady();
        if (!isStreamingDialogIdle()) {
            return false;
        }
        isDialogBusy = false;
        if (statusText) {
            updateVoiceChatText(statusText);
            showStatus(statusText, 'speech');
            setVisitorSpeechText('');
            setAssistantSpeechText('');
        } else {
            clearStreamingSpeechDisplay();
        }
        setVoicePhase('ready', 'Ready for next visitor', 0.18);
        releaseLocalDialogAudio('local_dialog');
        scheduleIdle(800);
        scheduleAvatarEventPump(400);
        return true;
    }

    function acknowledgeStreamingPlaybackIfReady() {
        if (
            streamingPlaybackAckSent
            || !streamingAudioDone
            || isListening
            || streamingAudioPlaying
            || streamingAudioQueue.length > 0
        ) {
            return false;
        }
        streamingPlaybackAckSent = true;
        if (streamingAudioProgressTimer) {
            clearInterval(streamingAudioProgressTimer);
            streamingAudioProgressTimer = null;
        }
        rememberDialogTurn(currentUserText, currentAnswerText);
        if (voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
            voiceStreamWs.send(JSON.stringify({
                type: 'playback_complete',
                turnId: activeVoiceTurnId
            }));
            clientLog('voice playback committed', {
                turnId: activeVoiceTurnId,
                userChars: currentUserText.length,
                answerChars: currentAnswerText.length
            });
            if (!voiceStreamKeepOpen) {
                voiceStreamWs.close(1000, 'turn playback complete');
            }
        }
        return true;
    }

    function clearStreamingDialogWatchdog() {
        if (streamingDialogWatchdogTimer) {
            clearTimeout(streamingDialogWatchdogTimer);
            streamingDialogWatchdogTimer = null;
        }
    }

    function clearVoiceAsrFinalWatchdog() {
        if (voiceAsrFinalWatchdogTimer) {
            clearTimeout(voiceAsrFinalWatchdogTimer);
            voiceAsrFinalWatchdogTimer = null;
        }
    }

    function scheduleVoiceAsrFinalWatchdog(turnId) {
        clearVoiceAsrFinalWatchdog();
        var timeoutMs = isEmptyBargeResumeTurnId(turnId)
            ? Math.min(VOICE_ASR_FINAL_WATCHDOG_MS, EMPTY_BARGE_ASR_FINAL_WATCHDOG_MS)
            : VOICE_ASR_FINAL_WATCHDOG_MS;
        var emptyBargeWatchdog = timeoutMs < VOICE_ASR_FINAL_WATCHDOG_MS;
        voiceAsrFinalWatchdogTimer = setTimeout(function () {
            voiceAsrFinalWatchdogTimer = null;
            if (
                turnId !== activeVoiceTurnId
                || !isDialogBusy
                || !voiceStopRequested
            ) {
                return;
            }
            if (emptyBargeWatchdog && !isEmptyBargeResumeTurnId(turnId)) {
                scheduleVoiceAsrFinalWatchdog(turnId);
                return;
            }
            clientLog('voice asr final watchdog fired', {
                turnId: turnId,
                sentBytes: voiceSentBytesThisTurn,
                websocketState: voiceStreamWs ? voiceStreamWs.readyState : -1,
                timeoutMs: timeoutMs,
                emptyBargeResumeCandidate: isEmptyBargeResumeTurnId(turnId)
            });
            finalizeStreamingDialogTurn(
                turnId,
                '没有收到识别结果，已恢复监听',
                { suppressUserStatus: true }
            );
        }, timeoutMs);
    }

    function scheduleStreamingDialogWatchdog(turnId) {
        clearStreamingDialogWatchdog();
        streamingDialogWatchdogTimer = setTimeout(function () {
            streamingDialogWatchdogTimer = null;
            if (turnId !== activeVoiceTurnId || !isDialogBusy) {
                return;
            }
            console.warn('Streaming voice turn watchdog fired');
            finalizeStreamingDialogTurn(turnId, '语音链路超时，已重置');
        }, 120000);
    }

    function finalizeStreamingDialogTurn(turnId, statusText, options) {
        options = options || {};
        if (turnId && turnId !== activeVoiceTurnId) {
            return;
        }
        var completedTurnId = activeVoiceTurnId;
        var shouldResumeEmptyBarge = isEmptyBargeResumeTurnId(completedTurnId);
        activeVoiceTurnId = ++voiceTurnId;
        if (shouldResumeEmptyBarge) {
            forceResetVoiceLayer(statusText || 'streaming dialog finalize', {
                preserveEmptyBargeResume: true
            });
            isDialogBusy = false;
            if (resumeInterruptedSpeechAfterEmptyAsr(completedTurnId)) {
                return;
            }
        }
        forceResetVoiceLayer(statusText || 'streaming dialog finalize');
        if (statusText && !options.suppressUserStatus) {
            updateVoiceChatText(statusText);
            showStatus(statusText, 'speech');
            setVisitorSpeechText('');
            setAssistantSpeechText('');
        } else {
            clearStreamingSpeechDisplay();
        }
    }

    function getDialogAudioLockedUntil() {
        pruneDialogAudioLocks();
        return Object.keys(dialogAudioLockOwners).reduce(function (maxUntil, owner) {
            return Math.max(maxUntil, dialogAudioLockOwners[owner] || 0);
        }, 0);
    }

    function pruneDialogAudioLocks() {
        var now = performance.now();
        Object.keys(dialogAudioLockOwners).forEach(function (owner) {
            if ((dialogAudioLockOwners[owner] || 0) <= now) {
                delete dialogAudioLockOwners[owner];
            }
        });
    }

    function postDialogAudioLock(active, holdMs, owner) {
        fetch('/dialog-audio-lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                active: Boolean(active),
                holdMs: Math.max(0, Math.floor(holdMs || 0)),
                owner: owner || 'local_dialog'
            }),
            keepalive: true
        }).catch(function () { });
    }

    function stopCurrentAudio() {
        var owner = activeSpeechOwner;
        ttsRequestId++;
        if (audio) {
            audio.pause();
            audio = null;
        }
        activeLocalDialogPlaybackText = '';
        activeLocalDialogPlaybackEstimatedMs = 0;
        cancelActiveFixedTtsStream('stop current audio');
        statusMode = 'idle';
        stopLipSync();
        hideSubtitle();
        if (owner) {
            releaseFixedSpeechGuardSoon(owner);
            releaseLocalDialogAudio(owner);
            releaseSpeechPriority(owner);
        }
    }

    function setupVoiceChat() {
        if (!voiceChatText) return;
        if (!avatarSessionValid) {
            handleAvatarSessionUnavailable('设备会话失效，请从客户端重新打开前台');
            return;
        }
        if (voiceStreamUrl) {
            setupStreamingVoiceChat();
            return;
        }
        if (realtimeDialogEnabled) {
            updateVoiceChatText(realtimeRagEnabled ? '实时语音 RAG 已接管，可以直接说话' : '实时语音已接管，可以直接说话');
            return;
        }
        if (interactionMode === 'quotes_only') {
            updateVoiceChatText('语录模式');
            return;
        }
        if (!voiceChatButton) {
            updateVoiceChatText('未启用流式语音服务');
            return;
        }

        var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Recognition) {
            safeBtn(voiceChatButton, 'disabled', true);
            updateVoiceChatText('当前浏览器不支持语音识别，请用 Chrome 或 Edge');
            return;
        }

        speechRecognition = new Recognition();
        speechRecognition.lang = 'zh-CN';
        speechRecognition.interimResults = true;
        speechRecognition.continuous = false;

        var startedAt = 0;
        var finalText = '';

        speechRecognition.onstart = function () {
            isListening = true;
            finalText = '';
            startedAt = performance.now();
            setVisitorSpeechText('');
            setAssistantSpeechText('');
            lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS);
            safeCls(voiceChatButton, 'listening', 'add');
            safeBtn(voiceChatButton, 'textContent', '正在听');
            updateVoiceChatText('请说话');
        };

        speechRecognition.onresult = function (event) {
            var interim = '';
            for (var i = event.resultIndex; i < event.results.length; i++) {
                var text = event.results[i][0].transcript.trim();
                if (event.results[i].isFinal) {
                    finalText += text;
                } else {
                    interim += text;
                }
            }
            setVisitorSpeechText(finalText || interim);
            updateVoiceChatText(finalText || interim || '正在识别');
        };

        speechRecognition.onerror = function (event) {
            isListening = false;
            safeCls(voiceChatButton, 'listening', 'remove');
            safeBtn(voiceChatButton, 'textContent', '开始说话');
            isDialogBusy = false;
            safeBtn(voiceChatButton, 'disabled', false);
            updateVoiceChatText('语音识别失败：' + (event.error || 'unknown'));
        };

        speechRecognition.onend = function () {
            isListening = false;
            safeCls(voiceChatButton, 'listening', 'remove');
            safeBtn(voiceChatButton, 'textContent', '开始说话');
            if (finalText.trim()) {
                setVisitorSpeechText(finalText.trim());
                runDialogChat(finalText.trim(), startedAt);
            } else {
                isDialogBusy = false;
                safeBtn(voiceChatButton, 'disabled', false);
                releaseLocalDialogAudio('local_dialog');
                updateVoiceChatText('没有识别到内容');
            }
        };

        if (voiceChatButton) voiceChatButton.onclick = function () {
            unlockAudio();
            if (isDialogBusy) return;
            if (isListening) {
                speechRecognition.stop();
                return;
            }
            isDialogBusy = true;
            safeBtn(voiceChatButton, 'disabled', false);
            lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS);
            try {
                speechRecognition.start();
            } catch (err) {
                isDialogBusy = false;
                releaseLocalDialogAudio('local_dialog');
                updateVoiceChatText('启动语音识别失败：' + err.message);
            }
        };
    }

    function setupStreamingVoiceChat() {
        if (!avatarSessionValid) {
            handleAvatarSessionUnavailable('设备会话失效，请从客户端重新打开前台');
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            updateVoiceChatText('当前浏览器不支持麦克风采集');
            clientLog('mediaDevices unavailable');
            return;
        }
        if (voiceChatButton) {
            safeBtn(voiceChatButton, 'disabled', false);
            safeBtn(voiceChatButton, 'textContent', '开始说话');
            voiceChatButton.onclick = function () {
                unlockAudio();
                if (!voiceMonitorReady) {
                    updateVoiceChatText('麦克风还在启动中');
                    clientLog('manual voice click before monitor ready');
                    return;
                }
                if (isListening && voiceStreamWs) {
                    finishVoiceTurn();
                    return;
                }
                startVoiceTurn(new Float32Array(0), performance.now());
            };
        }
        if (voiceMonitorReady) {
            updateVoiceChatText('我在听，你直接说话', 3000);
            return;
        }
        if (voiceMonitorStarting) {
            updateVoiceChatText('麦克风还在启动中');
            return;
        }
        updateVoiceChatText('正在请求麦克风权限');
        clientLog('request microphone', { voiceStreamUrl: voiceStreamUrl, isSecureContext: window.isSecureContext });
        startContinuousVoiceMonitor().catch(function (err) {
            autoVoiceChatEnabled = false;
            updateVoiceChatText('麦克风启动失败：' + (err && err.message ? err.message : err));
            clientLog('microphone start failed', { message: err && err.message ? err.message : String(err), isSecureContext: window.isSecureContext });
        });
    }

    async function startContinuousVoiceMonitor() {
        if (voiceMonitorReady || voiceMonitorStarting) return;
        voiceMonitorStarting = true;
        try {
            voiceMediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            var AudioContextClass = window.AudioContext || window.webkitAudioContext;
            voiceInputContext = new AudioContextClass({ sampleRate: 48000 });
            voiceInputRate = voiceInputContext.sampleRate;
            voiceSource = voiceInputContext.createMediaStreamSource(voiceMediaStream);
            voiceProcessor = voiceInputContext.createScriptProcessor(2048, 1, 1);
            voiceProcessor.onaudioprocess = handleVoiceMonitorAudio;
            voiceSource.connect(voiceProcessor);
            voiceProcessor.connect(voiceInputContext.destination);
            voiceMonitorReady = true;
            updateVoiceChatText('我在听，你直接说话');
            clientLog('microphone monitor ready', { sampleRate: voiceInputRate, isSecureContext: window.isSecureContext });
        } finally {
            voiceMonitorStarting = false;
        }
    }

    function handleVoiceMonitorAudio(event) {
        if (!autoVoiceChatEnabled || !avatarSessionValid) return;
        var input = event.inputBuffer.getChannelData(0);
        var now = performance.now();
        var rms = computeRms(input);
        var startThreshold = Math.max(VOICE_VAD_START_MIN, voiceNoiseFloor * VOICE_VAD_START_RATIO);
        var endThreshold = Math.max(VOICE_VAD_END_MIN, voiceNoiseFloor * VOICE_VAD_END_RATIO);

        var assistantResponseActive = isAssistantResponseActive();
        var interruptibleFixedSpeechActive = isInterruptibleFixedSpeechActive();
        if (isDialogSilenceFeedbackProtected()) {
            voiceNoiseFloor = voiceNoiseFloor * 0.98 + Math.min(rms, 0.05) * 0.02;
            resetVoiceVadCandidate();
            if (now - lastVoiceVadRejectLogAt >= 2500) {
                lastVoiceVadRejectLogAt = now;
                clientLog('vad ignored during dialog silence feedback', {
                    rms: rms,
                    playing: streamingAudioPlaying,
                    queueLength: streamingAudioQueue.length,
                    hasAudio: Boolean(audio)
                });
            }
            return;
        }
        if (isSelfSpeechActive() && !assistantResponseActive && !interruptibleFixedSpeechActive) {
            voiceNoiseFloor = voiceNoiseFloor * 0.98 + Math.min(rms, 0.05) * 0.02;
            resetVoiceVadCandidate();
            return;
        }

        if (!voiceSpeechStarted) {
            if (isListening) {
                if (rms >= startThreshold) {
                    voiceUserSpeechDetectedThisTurn = true;
                }
                queueVoiceInputFrame(input);
                return;
            }
            if (assistantResponseActive || interruptibleFixedSpeechActive) {
                var bargeThreshold = Math.max(
                    VOICE_BARGE_IN_START_MIN,
                    voiceNoiseFloor * VOICE_BARGE_IN_START_RATIO
                );
                pushVoiceVadPreRoll(input);
                if (rms < bargeThreshold) {
                    if (now - lastVoiceVadRejectLogAt >= 2500) {
                        lastVoiceVadRejectLogAt = now;
                        clientLog('vad barge below threshold', {
                            rms: rms,
                            peak: voiceVadCandidatePeak,
                            threshold: bargeThreshold,
                            noiseFloor: voiceNoiseFloor,
                            playing: streamingAudioPlaying,
                            fixedSpeechEventType: interruptibleFixedSpeechActive ? activeFixedSpeechEventType : '',
                            queueLength: streamingAudioQueue.length,
                            hasAudio: Boolean(audio)
                        });
                    }
                    resetVoiceVadCandidate();
                    return;
                }
                trackVoiceVadCandidate(rms, now);
                var bargeStats = getVoiceVadCandidateStats(now);
                if (!voiceTurnPolicy.canBargeIn({
                    playing: streamingAudioPlaying || Boolean(audio),
                    responseActive: assistantResponseActive || interruptibleFixedSpeechActive,
                    rms: rms,
                    peak: voiceVadCandidatePeak,
                    threshold: bargeThreshold,
                    frames: voiceVadCandidateFrames,
                    minFrames: VOICE_BARGE_IN_START_FRAMES,
                    avgRms: bargeStats.avgRms,
                    durationMs: bargeStats.durationMs,
                    minDurationMs: VOICE_BARGE_IN_MIN_MS,
                    minAverageRatio: VOICE_BARGE_IN_MIN_AVG_RATIO,
                    maxPeakToAverage: VOICE_BARGE_IN_PEAK_AVG_MAX
                })) {
                    if (now - lastVoiceVadRejectLogAt >= 1000) {
                        lastVoiceVadRejectLogAt = now;
                        clientLog('vad barge candidate rejected', {
                            rms: rms,
                            peak: voiceVadCandidatePeak,
                            avgRms: bargeStats.avgRms,
                            peakToAverage: bargeStats.peakToAverage,
                            threshold: bargeThreshold,
                            frames: voiceVadCandidateFrames,
                            durationMs: bargeStats.durationMs,
                            minFrames: VOICE_BARGE_IN_START_FRAMES,
                            minDurationMs: VOICE_BARGE_IN_MIN_MS,
                            noiseFloor: voiceNoiseFloor,
                            reason: getVoiceBargeInRejectReason(rms, bargeThreshold, bargeStats)
                        });
                    }
                    return;
                }
                var bargeInput = mergeVoiceVadPreRoll();
                var progress = getStreamingPlaybackProgress();
                clientLog('vad barge in confirmed', {
                    turnId: activeVoiceTurnId,
                    rms: rms,
                    peak: voiceVadCandidatePeak,
                    avgRms: bargeStats.avgRms,
                    peakToAverage: bargeStats.peakToAverage,
                    threshold: bargeThreshold,
                    frames: voiceVadCandidateFrames,
                    durationMs: bargeStats.durationMs,
                    replyId: progress.replyId,
                    playedMs: progress.playedMs,
                    fixedSpeechEventType: interruptibleFixedSpeechActive ? activeFixedSpeechEventType : ''
                });
                resetVoiceVadCandidate();
                startVoiceTurn(bargeInput, now, { userSpeechDetected: true });
                return;
            }
            var canStartFreshTurn = voiceTurnPolicy.canStartVoiceTurn({
                isDialogBusy: isDialogBusy,
                streamingAudioPlaying: streamingAudioPlaying,
                streamingAudioDone: streamingAudioDone
            });
            var canInterruptPendingResponse = voiceTurnPolicy.canInterruptPendingResponse({
                isDialogBusy: isDialogBusy,
                isListening: isListening,
                voiceStopRequested: voiceStopRequested,
                streamingAudioPlaying: streamingAudioPlaying,
                streamingAudioQueueLength: streamingAudioQueue.length,
                hasAudio: Boolean(audio)
            });
            if (!canStartFreshTurn && !canInterruptPendingResponse) {
                resetVoiceVadCandidate();
                return;
            }
            voiceNoiseFloor = voiceNoiseFloor * 0.96 + Math.min(rms, 0.08) * 0.04;
            pushVoiceVadPreRoll(input);
            if (rms < startThreshold) {
                resetVoiceVadCandidate();
                if (!isDialogBusy && !streamingAudioPlaying) {
                    updateVoiceChatText('我在听，你直接说话');
                }
                return;
            }
            if (!acceptVoiceVadCandidate(rms, startThreshold, now)) {
                if (now - lastVoiceVadRejectLogAt >= 2500) {
                    lastVoiceVadRejectLogAt = now;
                    clientLog('vad candidate rejected', {
                        rms: rms,
                        peak: voiceVadCandidatePeak,
                        frames: voiceVadCandidateFrames,
                        startThreshold: startThreshold,
                        noiseFloor: voiceNoiseFloor
                    });
                }
                return;
            }
            if (!canStartFreshTurn && canInterruptPendingResponse) {
                var pendingBargeThreshold = Math.max(
                    VOICE_PENDING_INTERRUPT_START_MIN,
                    voiceNoiseFloor * VOICE_PENDING_INTERRUPT_START_RATIO
                );
                var pendingBargeStats = getVoiceVadCandidateStats(now);
                if (!voiceTurnPolicy.canInterruptPendingResponse({
                    isDialogBusy: isDialogBusy,
                    isListening: isListening,
                    voiceStopRequested: voiceStopRequested,
                    streamingAudioPlaying: streamingAudioPlaying,
                    streamingAudioQueueLength: streamingAudioQueue.length,
                    hasAudio: Boolean(audio),
                    requiresStrongVoice: true,
                    rms: rms,
                    peak: voiceVadCandidatePeak,
                    threshold: pendingBargeThreshold,
                    frames: voiceVadCandidateFrames,
                    minFrames: VOICE_PENDING_INTERRUPT_START_FRAMES,
                    avgRms: pendingBargeStats.avgRms,
                    durationMs: pendingBargeStats.durationMs,
                    minDurationMs: VOICE_PENDING_INTERRUPT_MIN_MS,
                    minAverageRatio: VOICE_PENDING_INTERRUPT_MIN_AVG_RATIO,
                    maxPeakToAverage: VOICE_PENDING_INTERRUPT_PEAK_AVG_MAX
                })) {
                    if (now - lastVoiceVadRejectLogAt >= 1000) {
                        lastVoiceVadRejectLogAt = now;
                        clientLog('pending response interrupt candidate rejected', {
                            rms: rms,
                            peak: voiceVadCandidatePeak,
                            avgRms: pendingBargeStats.avgRms,
                            peakToAverage: pendingBargeStats.peakToAverage,
                            threshold: pendingBargeThreshold,
                            frames: voiceVadCandidateFrames,
                            durationMs: pendingBargeStats.durationMs,
                            minFrames: VOICE_PENDING_INTERRUPT_START_FRAMES,
                            minDurationMs: VOICE_PENDING_INTERRUPT_MIN_MS,
                            noiseFloor: voiceNoiseFloor,
                            reason: getVoiceBargeInRejectReason(rms, pendingBargeThreshold, pendingBargeStats)
                        });
                    }
                    return;
                }
            }
            var initialInput = mergeVoiceVadPreRoll();
            clientLog('vad speech start', {
                rms: rms,
                peak: voiceVadCandidatePeak,
                frames: voiceVadCandidateFrames,
                startThreshold: startThreshold,
                noiseFloor: voiceNoiseFloor,
                interruptsPendingResponse: canInterruptPendingResponse
            });
            resetVoiceVadCandidate();
            startVoiceTurn(initialInput, now, { userSpeechDetected: true });
            return;
        }

        if (rms >= endThreshold) {
            voiceUserSpeechDetectedThisTurn = true;
            voiceLastSpeechAt = now;
        }
        sendVoiceInput(input);

        if (
            isListening
            && now - voiceSpeechStartedAt >= VOICE_VAD_MIN_SPEECH_MS
            && now - voiceLastSpeechAt >= getEffectiveVoiceVadSilenceMs()
        ) {
            finishVoiceTurn();
        }
    }

    function isEmptyBargeResumeTurnId(turnId) {
        return Boolean(
            pendingEmptyBargeResume
            && pendingEmptyBargeResume.resumeTurnId === turnId
            && !hasMeaningfulAsrText(currentUserText)
        );
    }

    function isEmptyBargeResumeTurn() {
        return isEmptyBargeResumeTurnId(activeVoiceTurnId);
    }

    function getEffectiveVoiceVadSilenceMs() {
        if (isEmptyBargeResumeTurn()) {
            return Math.min(voiceVadSilenceMs, EMPTY_BARGE_RESUME_SILENCE_MS);
        }
        return voiceVadSilenceMs;
    }

    async function startVoiceTurn(initialInput, now, options) {
        options = options || {};
        if (!avatarSessionValid || !voiceDeviceId || !voiceTenantId) {
            handleAvatarSessionUnavailable('设备会话失效，请从客户端重新打开前台', {
                avatarSessionValid: avatarSessionValid,
                voiceDeviceId: voiceDeviceId,
                voiceTenantId: voiceTenantId
            });
            return;
        }
        if (isDialogSilenceFeedbackProtected()) {
            clientLog('voice turn blocked during dialog silence feedback', {
                streamingAudioPlaying: streamingAudioPlaying,
                queueLength: streamingAudioQueue.length,
                hasAudio: Boolean(audio)
            });
            return;
        }
        clearVoiceAsrFinalWatchdog();
        var canReuseAfterBargeIn = Boolean(
            voiceStreamWs
            && voiceStreamWs.readyState === WebSocket.OPEN
            && voiceStreamKeepOpen
            && isAssistantResponseActive()
        );
        var fixedSpeechInterruptedForListening = isInterruptibleFixedSpeechActive();
        var localDialogAudioInterruptedForListening = Boolean(
            !canReuseAfterBargeIn
            && !fixedSpeechInterruptedForListening
            && isAssistantResponseActive()
        );
        var shouldShowInterruptedListeningStatus = Boolean(
            canReuseAfterBargeIn
            || fixedSpeechInterruptedForListening
            || localDialogAudioInterruptedForListening
        );
        var interruptedListeningReason = canReuseAfterBargeIn
            ? 'realtime_barge_in'
            : (
                fixedSpeechInterruptedForListening
                    ? 'fixed_speech_barge_in'
                    : (localDialogAudioInterruptedForListening ? 'local_dialog_audio_barge_in' : '')
            );
        if (canReuseAfterBargeIn) {
            interruptCurrentVoiceTurnForBargeIn();
        }
        var canReuseVoiceSession = Boolean(
            voiceStreamWs
            && voiceStreamWs.readyState === WebSocket.OPEN
            && voiceStreamKeepOpen
            && !isDialogBusy
            && !streamingAudioPlaying
            && !audio
        );
        if (isDialogBusy || streamingAudioPlaying || audio || (voiceStreamWs && !canReuseVoiceSession)) {
            cancelCurrentVoiceTurn();
        }
        if (shouldShowInterruptedListeningStatus) {
            showInterruptedListeningStatus(interruptedListeningReason);
        }
        var turnId = ++voiceTurnId;
        activeVoiceTurnId = turnId;
        bindEmptyBargeResumeToTurn(turnId);
        var owner = 'local_dialog';
        var priority = getLocalDialogPriority();
        if (!acquireSpeechPriority(owner, priority)) {
            clearEmptyBargeResume('speech priority unavailable');
            updateVoiceChatText('当前有更高优先级语音正在播放');
            return;
        }

        var queuedBeforeTurn = avatarEventQueue.length;
        avatarEventQueue = voiceTurnPolicy.removeStaleDialogEvents(avatarEventQueue);
        if (avatarEventQueue.length !== queuedBeforeTurn) {
            clientLog('drop stale repeat events before realtime turn', {
                removed: queuedBeforeTurn - avatarEventQueue.length,
                remaining: avatarEventQueue.length
            });
        }

        isDialogBusy = true;
        isListening = true;
        streamingAudioQueue = [];
        streamingAudioPlaying = false;
        streamingAudioDone = false;
        streamingPlaybackStarted = false;
        streamingAudioActiveItem = null;
        streamingPlayedMsByReply = {};
        streamingPlaybackAckSent = false;
        voiceSpeechStarted = false;
        voiceUserSpeechDetectedThisTurn = Boolean(options.userSpeechDetected);
        voiceSpeechStartedAt = 0;
        voiceLastSpeechAt = 0;
        resetVoiceVadCandidate();
        voiceStopRequested = false;
        voicePendingInputFrames = [];
        voicePcmPacketRemainder = new Uint8Array(0);
        voiceSentBytesThisTurn = 0;
        currentUserText = '';
        currentAnswerText = '';
        clearConversationDisplayText();
        clearSelfSpeechMuteNow(canReuseAfterBargeIn ? 'barge in new turn' : 'voice turn start');
        lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS);
        updateVoiceChatText(shouldShowInterruptedListeningStatus ? INTERRUPTED_LISTENING_STATUS_TEXT : '正在听你说话');
        setVoicePhase('listening', 'Listening to visitor intent', 0.42);
        if (shouldShowInterruptedListeningStatus) {
            showStatus(voiceTurnPolicy.statusText('listening', INTERRUPTED_LISTENING_STATUS_TEXT), 'speech');
        } else {
            clearStatusBeforeDeferredSpeech();
        }
        clientLog('voice turn start', {
            turnId: turnId,
            voiceStreamUrl: voiceStreamUrl,
            interruptedSpeechStatus: shouldShowInterruptedListeningStatus
        });
        scheduleStreamingDialogWatchdog(turnId);

        if (canReuseVoiceSession) {
            voiceSpeechStarted = true;
            voiceSpeechStartedAt = now;
            voiceLastSpeechAt = now;
            voiceStreamWs.send(JSON.stringify({
                type: 'turn_start',
                turnId: turnId,
                metadata: buildVoiceStreamMetadata()
            }));
            queueVoiceInputFrame(initialInput);
            flushPendingVoiceInput();
            clientLog('voice persistent session reused', {
                turnId: turnId,
                conversationId: voiceConversationId,
                person: voicePersonSession && voicePersonSession.owner
            });
            return;
        }

        var voiceTicket = '';
        try {
            var ticketPayload = await fetchJsonWithError('/voice-ticket', {
                method: 'POST',
                headers: {
                    'X-Avatar-Client-Id': avatarRuntimeClientId,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    frontdeskSurface: getCurrentFrontdeskSurface(),
                    modelKey: currentModelKey || DEFAULT_MODEL_KEY
                })
            });
            voiceTicket = ticketPayload.data && ticketPayload.data.ticket || '';
            if (!voiceTicket) {
                throw new Error(ticketPayload.error || 'voice ticket missing in response');
            }
            if (turnId !== activeVoiceTurnId) return;
        } catch (err) {
            var ticketPayloadError = (err && err.payload) || {};
            clientLog('voice ticket request failed', {
                turnId: turnId,
                status: err && err.status,
                reason: ticketPayloadError.reason || '',
                error: err && err.message ? err.message : String(err || 'unknown'),
                payload: ticketPayloadError
            });
            cancelCurrentVoiceTurn();
            if (err && (err.status === 401 || err.status === 403)) {
                handleAvatarSessionUnavailable(avatarSessionUnavailableText(err), {
                    status: err.status,
                    error: err.message,
                    payload: ticketPayloadError
                });
            } else {
                updateVoiceChatText('语音连接认证失败：' + (err && err.message ? err.message : 'unknown'));
            }
            return;
        }

        var voiceSocket = new WebSocket(voiceStreamUrl);
        voiceStreamWs = voiceSocket;
        voiceSocket.binaryType = 'arraybuffer';
        voiceSocket.onopen = function () {
            if (voiceSocket !== voiceStreamWs || turnId !== activeVoiceTurnId) return;
            voiceSpeechStarted = true;
            voiceSpeechStartedAt = now;
            voiceLastSpeechAt = now;
            clientLog('voice websocket open', { turnId: turnId, conversationId: voiceConversationId });
            voiceSocket.send(JSON.stringify({
                type: 'context',
                turnId: turnId,
                items: dialogHistory.slice(-6),
                metadata: Object.assign(buildVoiceStreamMetadata(), {
                    conversation_id: voiceConversationId,
                    voice_ticket: voiceTicket
                })
            }));
            queueVoiceInputFrame(initialInput);
            flushPendingVoiceInput();
        };
        voiceSocket.onmessage = function (event) {
            if (voiceSocket !== voiceStreamWs) return;
            handleVoiceStreamMessage(event, activeVoiceTurnId);
        };
        voiceSocket.onerror = function () {
            if (voiceSocket !== voiceStreamWs) return;
            updateVoiceChatText('流式语音连接异常');
            clientLog('voice websocket error', {
                turnId: activeVoiceTurnId,
                sentBytes: voiceSentBytesThisTurn,
                pendingFrames: voicePendingInputFrames.length,
                streamingAudioDone: streamingAudioDone
            });
        };
        voiceSocket.onclose = function () {
            if (voiceSocket !== voiceStreamWs) return;
            var closeTurnId = activeVoiceTurnId;
            var pendingFrames = voicePendingInputFrames.length;
            var closedBeforeAudioSent = !streamingAudioDone
                && voiceSentBytesThisTurn === 0
                && pendingFrames > 0
                && !streamingAudioPlaying
                && streamingAudioQueue.length === 0;
            clientLog('voice websocket close', {
                turnId: closeTurnId,
                streamingAudioDone: streamingAudioDone,
                sentBytes: voiceSentBytesThisTurn,
                pendingFrames: pendingFrames
            });
            voiceStreamWs = null;
            isListening = false;
            voicePendingInputFrames = [];
            voiceStreamKeepOpen = false;
            voicePersonSession = null;
            if (closedBeforeAudioSent) {
                clientLog('voice websocket closed before audio sent', {
                    turnId: closeTurnId,
                    pendingFrames: pendingFrames
                });
                finalizeStreamingDialogTurn(
                    closeTurnId,
                    '语音连接中断，已恢复监听'
                );
                return;
            }
            if (!streamingAudioPlaying && streamingAudioQueue.length === 0 && streamingAudioDone) {
                clearStreamingDialogWatchdog();
            }
            releaseStreamingDialogIfIdle();
        };
    }

    function sendVoiceInput(input) {
        if (!isListening) return;
        if (!voiceStreamWs || voiceStreamWs.readyState !== WebSocket.OPEN) {
            queueVoiceInputFrame(input);
            return;
        }
        var pcm = resampleFloatTo16BitPcm(input, voiceInputRate, 16000);
        if (pcm.byteLength > 0) {
            var pcmBytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
            var combined = new Uint8Array(voicePcmPacketRemainder.byteLength + pcmBytes.byteLength);
            combined.set(voicePcmPacketRemainder, 0);
            combined.set(pcmBytes, voicePcmPacketRemainder.byteLength);
            var offset = 0;
            while (offset + VOICE_PCM_PACKET_BYTES <= combined.byteLength) {
                var packet = combined.slice(offset, offset + VOICE_PCM_PACKET_BYTES);
                voiceStreamWs.send(packet.buffer);
                voiceSentBytesThisTurn += packet.byteLength;
                offset += VOICE_PCM_PACKET_BYTES;
            }
            voicePcmPacketRemainder = combined.slice(offset);
        }
    }

    function queueVoiceInputFrame(input) {
        if (!input || input.length === 0) return;
        voicePendingInputFrames.push(new Float32Array(input));
        while (voicePendingInputFrames.length > VOICE_PENDING_INPUT_MAX_FRAMES) {
            voicePendingInputFrames.shift();
        }
    }

    function flushPendingVoiceInput() {
        if (!voiceStreamWs || voiceStreamWs.readyState !== WebSocket.OPEN || !isListening) return;
        var frames = voicePendingInputFrames;
        voicePendingInputFrames = [];
        var peak = 0;
        var sumSquares = 0;
        var sampleCount = 0;
        frames.forEach(function (frame) {
            var frameRms = computeRms(frame);
            peak = Math.max(peak, frameRms);
            for (var i = 0; i < frame.length; i += 1) {
                sumSquares += frame[i] * frame[i];
            }
            sampleCount += frame.length;
            sendVoiceInput(frame);
        });
        clientLog('voice input flushed', {
            frames: frames.length,
            sentBytes: voiceSentBytesThisTurn,
            rms: sampleCount > 0 ? Math.sqrt(sumSquares / sampleCount) : 0,
            peak: peak
        });
    }

    function finishVoiceTurn(status) {
        if (voiceStopRequested) return;
        voiceStopRequested = true;
        isListening = false;
        if (voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
            flushVoicePcmPacketRemainder();
            voiceStreamWs.send('stop');
            if (status) {
                updateVoiceChatText(status);
            }
        }
        if (status) {
            showStatus(voiceTurnPolicy.statusText('processing', status), 'speech');
        }
        setVoicePhase('understanding', 'Understanding request', 0.34);
        voiceSpeechStarted = false;
        resetVoiceVadCandidate();
        scheduleVoiceAsrFinalWatchdog(activeVoiceTurnId);
    }

    function stopVoiceInputAfterServerVad() {
        clearVoiceAsrFinalWatchdog();
        voiceStopRequested = true;
        isListening = false;
        voiceSpeechStarted = false;
        voicePendingInputFrames = [];
        voicePcmPacketRemainder = new Uint8Array(0);
        resetVoiceVadCandidate();
        setVoicePhase('understanding', 'Understanding request', 0.34);
        clientLog('voice input stopped by server vad', {
            backend: voiceStreamBackend,
            sentBytes: voiceSentBytesThisTurn
        });
    }

    function setFaceNameDialogStatus(text) {
        if (faceNameStatus) {
            faceNameStatus.textContent = text || '';
        }
    }

    function setFaceNameDialogBusy(busy) {
        faceNameSubmitting = Boolean(busy);
        safeBtn(faceNameInput, 'disabled', faceNameSubmitting);
        safeBtn(faceNameCancel, 'disabled', faceNameSubmitting);
        safeBtn(faceNameSubmit, 'disabled', faceNameSubmitting);
    }

    function showFaceNameDialog(payload) {
        if (!faceNameDialog || !faceNameInput) {
            clientLog('face name dialog unavailable', { payload: payload || null });
            updateVoiceChatText('请到控制台输入员工姓名后下发人脸录入');
            return;
        }
        setFaceNameDialogBusy(false);
        faceNameInput.value = '';
        setFaceNameDialogStatus('准备下发到当前数字人客户端');
        faceNameDialog.hidden = false;
        updateVoiceChatText('请输入员工姓名');
        showStatus(voiceTurnPolicy.statusText('processing', '请输入员工姓名'), 'speech');
        window.setTimeout(function () {
            faceNameInput.focus();
        }, 50);
        clientLog('face name dialog opened', {
            source: payload && payload.source,
            rawText: payload && payload.rawText
        });
    }

    function hideFaceNameDialog(statusText) {
        if (faceNameDialog) {
            faceNameDialog.hidden = true;
        }
        setFaceNameDialogBusy(false);
        if (statusText) {
            updateVoiceChatText(statusText);
            showStatus(voiceTurnPolicy.statusText('processing', statusText), 'speech');
        }
    }

    function submitFaceNameDialog() {
        if (faceNameSubmitting || !faceNameInput) return;
        var name = faceNameInput.value.trim();
        if (!name) {
            setFaceNameDialogStatus('请先输入员工姓名');
            faceNameInput.focus();
            return;
        }
        setFaceNameDialogBusy(true);
        setFaceNameDialogStatus('正在下发人脸录入任务');
        fetch('/avatar/faces/capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || ('HTTP ' + res.status));
                    }
                    return data;
                });
            })
            .then(function (data) {
                var taskId = data.task && data.task.id || '';
                clientLog('face capture task dispatched from avatar', {
                    name: name,
                    taskId: taskId
                });
                hideFaceNameDialog(name + ' 的人脸录入已下发');
            })
            .catch(function (err) {
                setFaceNameDialogBusy(false);
                setFaceNameDialogStatus('下发失败: ' + err.message);
                clientLog('face capture task dispatch failed from avatar', {
                    name: name,
                    error: err.message
                });
            });
    }

    function setupFaceNameDialog() {
        if (!faceNameForm) return;
        faceNameForm.addEventListener('submit', function (event) {
            event.preventDefault();
            submitFaceNameDialog();
        });
        if (faceNameCancel) {
            faceNameCancel.addEventListener('click', function () {
                hideFaceNameDialog('已取消人脸录入');
                clientLog('face name dialog cancelled');
            });
        }
    }

    function flushVoicePcmPacketRemainder() {
        if (
            voicePcmPacketRemainder.byteLength === 0
            || !voiceStreamWs
            || voiceStreamWs.readyState !== WebSocket.OPEN
        ) {
            voicePcmPacketRemainder = new Uint8Array(0);
            return;
        }
        var packet = voicePcmPacketRemainder;
        voicePcmPacketRemainder = new Uint8Array(0);
        voiceStreamWs.send(packet.buffer);
        voiceSentBytesThisTurn += packet.byteLength;
    }

    function buildVoiceInterruptionContext(progress, mode) {
        progress = progress || {};
        var activeText = streamingAudioActiveItem && streamingAudioActiveItem.text
            ? String(streamingAudioActiveItem.text).trim()
            : '';
        var localDialogPlaybackText = remainingSpeechTextForAudio(
            activeLocalDialogPlaybackText,
            audio,
            activeLocalDialogPlaybackEstimatedMs
        );
        return {
            mode: mode || 'cancel',
            userText: String(currentUserText || '').trim().slice(0, 500),
            assistantText: String(currentAnswerText || activeText || localDialogPlaybackText || '').trim().slice(0, 900),
            activeSentence: String(activeText || localDialogPlaybackText || '').trim().slice(0, 500),
            replyId: String(progress.replyId || '').slice(0, 120),
            playedMs: Math.max(0, Math.floor(Number(progress.playedMs) || 0))
        };
    }

    function hasMeaningfulAsrText(text) {
        return /[\p{L}\p{N}]/u.test(String(text || ''));
    }

    function compactSpeechResumeText(parts) {
        var text = '';
        (parts || []).forEach(function (part) {
            part = String(part || '').replace(/\s+/g, ' ').trim();
            if (!part) return;
            if (text && text.indexOf(part) >= 0) return;
            if (part.indexOf(text) >= 0) {
                text = part;
                return;
            }
            text += part;
        });
        text = text.trim();
        if (text.length > EMPTY_BARGE_RESUME_MAX_CHARS) {
            text = text.slice(0, EMPTY_BARGE_RESUME_MAX_CHARS).replace(/[，,。！？!?；;、]*$/, '');
        }
        return text;
    }

    function stripEmptyBargeResumePreamble(text) {
        text = String(text || '').replace(/\s+/g, ' ').trim();
        var previous = '';
        while (text && text !== previous) {
            previous = text;
            text = text
                .replace(/^(刚才我接着说|刚才还没来得及回答，我继续说|我继续说)[，,。:：\s]*/g, '')
                .trim();
        }
        return text;
    }

    function captureEmptyBargeResume(progress, interruption) {
        progress = progress || {};
        interruption = interruption || {};
        var parts = [];
        var promptText = String(interruption.userText || currentUserText || '').trim();
        var activeText = String(interruption.activeSentence || '').trim();
        if (activeText) {
            parts.push(activeText);
        }
        var localDialogPlaybackText = remainingSpeechTextForAudio(
            activeLocalDialogPlaybackText,
            audio,
            activeLocalDialogPlaybackEstimatedMs
        );
        if (localDialogPlaybackText) {
            parts.push(localDialogPlaybackText);
        }
        streamingAudioQueue.forEach(function (item) {
            if (item && item.text) {
                parts.push(item.text);
            }
        });
        if (parts.length === 0 && interruption.assistantText) {
            parts.push(interruption.assistantText);
        }
        var text = stripEmptyBargeResumePreamble(compactSpeechResumeText(parts));
        if (!text && !promptText) {
            pendingEmptyBargeResume = null;
            return false;
        }
        pendingEmptyBargeResume = {
            text: text,
            promptText: promptText.slice(0, 500),
            sourceTurnId: activeVoiceTurnId,
            resumeTurnId: 0,
            replyId: String(progress.replyId || ''),
            playedMs: Math.max(0, Math.floor(Number(progress.playedMs) || 0)),
            createdAt: performance.now()
        };
        clientLog('empty barge resume captured', {
            sourceTurnId: pendingEmptyBargeResume.sourceTurnId,
            textChars: text.length,
            promptChars: pendingEmptyBargeResume.promptText.length,
            replyId: pendingEmptyBargeResume.replyId,
            playedMs: pendingEmptyBargeResume.playedMs,
            duringResumePlayback: emptyBargeResumePlaybackActive
        });
        return true;
    }

    function bindEmptyBargeResumeToTurn(turnId) {
        if (pendingEmptyBargeResume) {
            pendingEmptyBargeResume.resumeTurnId = turnId;
        }
    }

    function clearEmptyBargeResume(reason) {
        if (!pendingEmptyBargeResume) return;
        clientLog('empty barge resume cleared', {
            reason: reason || '',
            resumeTurnId: pendingEmptyBargeResume.resumeTurnId || 0,
            textChars: String(pendingEmptyBargeResume.text || '').length
        });
        pendingEmptyBargeResume = null;
    }

    function resumeInterruptedSpeechAfterEmptyAsr(turnId) {
        var resume = pendingEmptyBargeResume;
        if (!resume || resume.resumeTurnId !== turnId) {
            return false;
        }
        var playbackTurnId = activeVoiceTurnId;
        pendingEmptyBargeResume = null;
        if (performance.now() - resume.createdAt > EMPTY_BARGE_RESUME_TTL_MS) {
            clientLog('empty barge resume expired', {
                turnId: turnId,
                ageMs: Math.round(performance.now() - resume.createdAt)
            });
            return false;
        }
        var resumeBody = stripEmptyBargeResumePreamble(resume.text);
        if (!resumeBody) {
            return resumeInterruptedPromptAfterEmptyAsr(turnId, resume, playbackTurnId);
        }
        isDialogBusy = true;
        streamingAudioDone = true;
        streamingPlaybackAckSent = true;
        emptyBargeResumePlaybackActive = true;
        setVoicePhase('understanding', 'Waiting for resumed audio', 0.42);
        clearStatusBeforeDeferredSpeech();
        clearVoiceChatText();
        clientLog('empty barge resumes interrupted speech', {
            turnId: turnId,
            playbackTurnId: playbackTurnId,
            sourceTurnId: resume.sourceTurnId,
            textChars: resumeBody.length,
            playedMs: resume.playedMs
        });
        fetchDialogSceneReply({
            scene: 'empty_barge_resume_speech',
            userText: resume.promptText,
            requiredFacts: [resumeBody],
            responseGoal: '在上一轮回答被空打断后，自然继续把未播完的内容说完。',
            constraints: [
                '不要使用固定前缀。',
                '保留未播完内容的核心含义。',
                '不要重新回答用户问题，只承接刚才没播完的部分。'
            ],
            context: dialogHistory.slice(-6)
        })
            .then(function (spokenText) {
                if (activeVoiceTurnId !== playbackTurnId || isListening) {
                    return null;
                }
                spokenText = String(spokenText || '').trim();
                if (!spokenText) {
                    throw new Error('empty scene reply');
                }
                return playRawTTS(spokenText, {
                    owner: 'local_dialog',
                    priority: getLocalDialogPriority(),
                    forceSpeech: true,
                    statusText: spokenText,
                    preparingText: EMPTY_BARGE_RESUME_PREPARING_TEXT,
                    clearVoiceChatOnEnd: true,
                    clearSpeechDisplayOnEnd: true,
                    lockMs: Math.min(DIALOG_AUDIO_LOCK_MAX_MS, Math.max(10000, spokenText.length * 450))
                });
            })
            .catch(function (err) {
                clientLog('empty barge resume playback failed', {
                    turnId: turnId,
                    error: err && err.message ? err.message : String(err || '')
                });
                updateVoiceChatText('继续回答失败：' + (err && err.message ? err.message : 'unknown'));
            })
            .finally(function () {
                emptyBargeResumePlaybackActive = false;
                if (activeVoiceTurnId === playbackTurnId && !isListening && !streamingAudioPlaying && streamingAudioQueue.length === 0) {
                    isDialogBusy = false;
                    streamingAudioDone = true;
                    setVoicePhase('ready', 'Ready for next visitor', 0.18);
                    clearStreamingSpeechDisplay();
                    scheduleAvatarEventPump(400);
                }
            });
        return true;
    }

    function resumeInterruptedPromptAfterEmptyAsr(turnId, resume, playbackTurnId) {
        playbackTurnId = playbackTurnId || activeVoiceTurnId;
        var promptText = String(resume && resume.promptText || '').trim();
        if (!promptText) {
            return false;
        }
        isDialogBusy = true;
        streamingAudioDone = true;
        streamingPlaybackAckSent = true;
        emptyBargeResumePlaybackActive = true;
        setVisitorSpeechText('');
        setAssistantSpeechText('');
        setVoicePhase('understanding', 'Regenerating interrupted response', 0.42);
        updateVoiceChatText(EMPTY_BARGE_RESUME_PREPARING_TEXT);
        showStatus(voiceTurnPolicy.statusText('processing', EMPTY_BARGE_RESUME_PREPARING_TEXT), 'speech');
        lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS, 'local_dialog');
        clientLog('empty barge regenerates interrupted answer', {
            turnId: turnId,
            playbackTurnId: playbackTurnId,
            sourceTurnId: resume.sourceTurnId,
            promptChars: promptText.length,
            playedMs: resume.playedMs
        });

        fetch('/dialog/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: promptText })
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || data.detail || 'dialog chat failed');
                    }
                    return data;
                });
            })
            .then(function (data) {
                if (playbackTurnId !== activeVoiceTurnId || isListening) {
                    return null;
                }
                var answer = data.data && data.data.answer;
                answer = String(answer || '').trim();
                if (!answer) {
                    throw new Error('empty answer');
                }
                return fetchDialogSceneReply({
                    scene: 'empty_barge_resume_regenerated_answer',
                    userText: promptText,
                    requiredFacts: [answer],
                    responseGoal: '上一轮被空打断且没有可续播文本时，自然补上重新生成的回答。',
                    constraints: [
                        '不要使用固定前缀。',
                        '保留重新生成答案的事实与建议。',
                        '可以轻描淡写地承接刚才中断的语境。'
                    ],
                    context: dialogHistory.slice(-6)
                });
            })
            .then(function (spokenAnswer) {
                if (playbackTurnId !== activeVoiceTurnId || isListening) {
                    return null;
                }
                spokenAnswer = String(spokenAnswer || '').trim();
                if (!spokenAnswer) {
                    throw new Error('empty scene reply');
                }
                return playRawTTS(spokenAnswer, {
                    owner: 'local_dialog',
                    priority: getLocalDialogPriority(),
                    forceSpeech: true,
                    statusText: spokenAnswer,
                    preparingText: EMPTY_BARGE_RESUME_PREPARING_TEXT,
                    clearVoiceChatOnEnd: true,
                    clearSpeechDisplayOnEnd: true,
                    lockMs: Math.min(DIALOG_AUDIO_LOCK_MAX_MS, Math.max(10000, spokenAnswer.length * 450))
                });
            })
            .catch(function (err) {
                clientLog('empty barge regenerated answer failed', {
                    turnId: turnId,
                    error: err && err.message ? err.message : String(err || '')
                });
                updateVoiceChatText('继续回答失败：' + (err && err.message ? err.message : 'unknown'));
                showStatus(voiceTurnPolicy.statusText('processing', '继续回答失败'), 'speech');
            })
            .finally(function () {
                emptyBargeResumePlaybackActive = false;
                if (activeVoiceTurnId === playbackTurnId && !isListening && !streamingAudioPlaying && streamingAudioQueue.length === 0) {
                    isDialogBusy = false;
                    streamingAudioDone = true;
                    releaseLocalDialogAudio('local_dialog');
                    setVoicePhase('ready', 'Ready for next visitor', 0.18);
                    clearStreamingSpeechDisplay();
                    scheduleAvatarEventPump(400);
                }
            });
        return true;
    }

    function fetchDialogSceneReply(payload) {
        payload = payload || {};
        return fetch('/dialog/scene-reply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || data.detail || 'dialog scene reply failed');
                    }
                    return data;
                });
            })
            .then(function (data) {
                return data.data && data.data.answer;
            });
    }

    function rememberInterruptedDialogContext(context) {
        context = context || {};
        var userText = String(context.userText || '').trim();
        var assistantText = String(context.assistantText || context.activeSentence || '').trim();
        if (!userText || !assistantText) {
            return;
        }
        var playedMs = Math.max(0, Math.floor(Number(context.playedMs) || 0));
        var note = '（上一轮回答被用户打断';
        if (playedMs > 0) {
            note += '，已播放约 ' + playedMs + 'ms';
        }
        note += '。后续回答要优先理解用户的补充或纠正。）';
        dialogHistory.push({ role: 'user', content: userText.slice(0, 500) });
        dialogHistory.push({
            role: 'assistant',
            content: (assistantText + note).slice(0, 500)
        });
        dialogHistory = dialogHistory.slice(-6);
        clientLog('voice interrupted context kept locally', {
            userChars: userText.length,
            assistantChars: assistantText.length,
            playedMs: playedMs,
            mode: context.mode || ''
        });
    }

    function sendVoiceInterruptMessage(progress, mode) {
        if (!voiceStreamWs || voiceStreamWs.readyState !== WebSocket.OPEN) {
            return false;
        }
        var interruption = buildVoiceInterruptionContext(progress, mode);
        voiceStreamWs.send(JSON.stringify({
            type: 'interrupt',
            turnId: activeVoiceTurnId,
            replyId: progress.replyId,
            playedMs: progress.playedMs,
            mode: mode || 'cancel',
            interruption: interruption
        }));
        return true;
    }

    function interruptCurrentVoiceTurnForBargeIn() {
        var progress = getStreamingPlaybackProgress();
        var interruption = buildVoiceInterruptionContext(progress, 'barge_in');
        captureEmptyBargeResume(progress, interruption);
        sendVoiceInterruptMessage(progress, 'barge_in');
        rememberInterruptedDialogContext(interruption);
        clientLog('voice turn interrupted in persistent session', {
            turnId: activeVoiceTurnId,
            userChars: currentUserText.length,
            answerChars: currentAnswerText.length,
            replyId: progress.replyId,
            playedMs: progress.playedMs
        });
        clearStreamingDialogWatchdog();
        clearVoiceAsrFinalWatchdog();
        streamingAudioQueue.forEach(function (item) {
            if (item.url) URL.revokeObjectURL(item.url);
        });
        streamingAudioQueue = [];
        if (streamingAudioActiveItem && streamingAudioActiveItem.url) {
            URL.revokeObjectURL(streamingAudioActiveItem.url);
        }
        if (audio) {
            audio.pause();
            audio = null;
        }
        activeLocalDialogPlaybackText = '';
        activeLocalDialogPlaybackEstimatedMs = 0;
        cancelActiveFixedTtsStream('interrupt current voice turn');
        stopLipSync();
        hideSubtitle();
        streamingAudioPlaying = false;
        streamingAudioDone = true;
        streamingPlaybackStarted = false;
        streamingAudioActiveItem = null;
        streamingPlayedMsByReply = {};
        streamingPlaybackAckSent = true;
        if (streamingAudioProgressTimer) {
            clearInterval(streamingAudioProgressTimer);
            streamingAudioProgressTimer = null;
        }
        finishDialogSilenceFeedback('barge_in');
        clearStreamingSpeechDisplay();
        setVoicePhase('listening', 'Listening to visitor intent', 0.42);
        voicePendingInputFrames = [];
        voicePcmPacketRemainder = new Uint8Array(0);
        voiceSentBytesThisTurn = 0;
        voiceUserSpeechDetectedThisTurn = false;
        isListening = false;
        isDialogBusy = false;
        voiceStopRequested = false;
        emptyBargeResumePlaybackActive = false;
        selfSpeechMutedUntil = performance.now();
        currentUserText = '';
        currentAnswerText = '';
    }

    function cancelCurrentVoiceTurn() {
        var cancellingFixedSpeech = isFixedSpeechOwner(activeSpeechOwner);
        var progress = getStreamingPlaybackProgress();
        var interruption = buildVoiceInterruptionContext(progress, 'cancel');
        var preserveEmptyBargeResume = false;
        if (voiceTurnPolicy.canCaptureInterruptedSpeechForResume({
            activeSpeechOwner: activeSpeechOwner,
            streamingAudioPlaying: streamingAudioPlaying,
            streamingAudioQueueLength: streamingAudioQueue.length,
            hasAudio: Boolean(audio),
            hasAssistantText: Boolean(String(interruption.assistantText || interruption.activeSentence || '').trim()),
            hasUserText: Boolean(String(interruption.userText || '').trim())
        })) {
            preserveEmptyBargeResume = captureEmptyBargeResume(progress, interruption);
        }
        if (cancellingFixedSpeech) {
            clearEmptyBargeResume('fixed speech cancelled');
            clientLog('fixed speech cancelled without resume', {
                eventType: activeFixedSpeechEventType,
                hasAudio: Boolean(audio),
                playedMs: progress.playedMs
            });
        }
        clientLog('voice turn cancelled', {
            turnId: activeVoiceTurnId,
            userChars: currentUserText.length,
            answerChars: currentAnswerText.length,
            voiceStopRequested: voiceStopRequested,
            streamingAudioPlaying: streamingAudioPlaying,
            replyId: progress.replyId,
            playedMs: progress.playedMs
        });
        if (!cancellingFixedSpeech) {
            sendVoiceInterruptMessage(progress, 'cancel');
            rememberInterruptedDialogContext(interruption);
        }
        activeVoiceTurnId = ++voiceTurnId;
        forceResetVoiceLayer('cancel current voice turn', {
            preserveEmptyBargeResume: preserveEmptyBargeResume
        });
        currentUserText = '';
        currentAnswerText = '';
    }

    function computeRms(samples) {
        var sum = 0;
        for (var i = 0; i < samples.length; i++) {
            sum += samples[i] * samples[i];
        }
        return Math.sqrt(sum / Math.max(1, samples.length));
    }

    function cleanupVoiceCapture() {
        voiceMonitorStarting = false;
        if (voiceProcessor) {
            voiceProcessor.disconnect();
            voiceProcessor.onaudioprocess = null;
            voiceProcessor = null;
        }
        if (voiceSource) {
            voiceSource.disconnect();
            voiceSource = null;
        }
        if (voiceInputContext) {
            voiceInputContext.close().catch(function () { });
            voiceInputContext = null;
        }
        if (voiceMediaStream) {
            voiceMediaStream.getTracks().forEach(function (track) { track.stop(); });
            voiceMediaStream = null;
        }
    }

    function resampleFloatTo16BitPcm(input, inputRate, outputRate) {
        if (!input || input.length === 0) {
            return new Int16Array(0);
        }
        if (inputRate === outputRate) {
            return floatTo16BitPcm(input);
        }
        var ratio = inputRate / outputRate;
        var outputLength = Math.max(1, Math.floor(input.length / ratio));
        var output = new Float32Array(outputLength);
        for (var i = 0; i < outputLength; i++) {
            var start = Math.floor(i * ratio);
            var end = Math.min(input.length, Math.floor((i + 1) * ratio));
            var sum = 0;
            var count = Math.max(1, end - start);
            for (var j = start; j < end; j++) {
                sum += input[j];
            }
            output[i] = sum / count;
        }
        return floatTo16BitPcm(output);
    }

    function floatTo16BitPcm(input) {
        var output = new Int16Array(input.length);
        for (var i = 0; i < input.length; i++) {
            var sample = Math.max(-1, Math.min(1, input[i]));
            output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        return output;
    }

    function handleVoiceStreamMessage(event, turnId) {
        if (turnId !== activeVoiceTurnId) return;
        var message = null;
        try {
            message = JSON.parse(event.data);
        } catch (err) {
            console.error('Voice stream message parse failed:', err);
            return;
        }
        if (
            voiceTurnPolicy.isTurnScopedVoiceMessage(message)
            && String(message.turnId) !== String(activeVoiceTurnId)
        ) {
            clientLog('drop stale voice response', {
                expectedTurnId: activeVoiceTurnId,
                receivedTurnId: message.turnId,
                type: message.type
            });
            return;
        }

        switch (message.type) {
            case 'ready':
                voiceStreamBackend = message.backend || voiceStreamBackend;
                clientLog('voice backend ready', {
                    backend: voiceStreamBackend,
                    serverVad: Boolean(message.serverVad),
                    endSmoothWindowMs: message.endSmoothWindowMs
                });
                break;
            case 'person_session':
                voiceStreamKeepOpen = Boolean(message.keepOpen);
                voicePersonSession = message;
                if (message.conversation_id) {
                    if (message.conversation_id !== voiceConversationId) {
                        dialogHistory = [];
                    }
                    voiceConversationId = message.conversation_id;
                }
                clientLog('person voice session bound', {
                    state: message.state,
                    conversationId: message.conversation_id,
                    owner: message.owner,
                    participants: message.participants,
                    keepOpen: voiceStreamKeepOpen,
                    restoredContextMessages: message.restoredContextMessages
                });
                break;
            case 'asr_partial':
                var partialHasMeaningfulText = hasMeaningfulAsrText(message.text);
                if (partialHasMeaningfulText) {
                    clearEmptyBargeResume('asr_partial');
                    clearInterruptedListeningStatus('asr_partial');
                } else if (isInterruptedListeningStatusProtected()) {
                    setVoicePhase('listening', 'Listening to visitor intent', 0.48);
                    updateVoiceChatText(INTERRUPTED_LISTENING_STATUS_TEXT);
                    showStatus(
                        voiceTurnPolicy.statusText('listening', INTERRUPTED_LISTENING_STATUS_TEXT),
                        'speech'
                    );
                    break;
                }
                currentUserText = message.text || currentUserText;
                setVisitorSpeechText(currentUserText);
                updateVoiceChatText(message.text || '正在识别');
                setVoicePhase('listening', 'Listening to visitor intent', 0.48);
                showStatus(
                    voiceTurnPolicy.statusText('recognizing', message.text),
                    'speech'
                );
                break;
            case 'asr_final':
                clearVoiceAsrFinalWatchdog();
                var finalHasMeaningfulText = hasMeaningfulAsrText(message.text);
                if (finalHasMeaningfulText) {
                    clearEmptyBargeResume('asr_final');
                    clearInterruptedListeningStatus('asr_final');
                } else if (isInterruptedListeningStatusProtected()) {
                    setVoicePhase('listening', 'Listening to visitor intent', 0.48);
                    updateVoiceChatText(INTERRUPTED_LISTENING_STATUS_TEXT);
                    showStatus(
                        voiceTurnPolicy.statusText('listening', INTERRUPTED_LISTENING_STATUS_TEXT),
                        'speech'
                    );
                    if (message.serverVad && isListening) {
                        stopVoiceInputAfterServerVad();
                    }
                    break;
                }
                currentUserText = message.text || currentUserText;
                setVisitorSpeechText(currentUserText);
                updateVoiceChatText('识别完成：' + message.text);
                setVoicePhase('understanding', 'Understanding request', 0.36);
                showStatus(
                    voiceTurnPolicy.statusText('recognizing', message.text),
                    'speech'
                );
                if (message.serverVad && isListening) {
                    stopVoiceInputAfterServerVad();
                }
                break;
            case 'llm_start':
                if (voiceDialogSilenceFeedbackActive && voiceDialogSilenceFeedbackDynamic) {
                    setVoicePhase('understanding', 'Understanding request', 0.42);
                    break;
                }
                var thinkingText = voiceTurnPolicy.statusText('processing');
                showStatus(voiceTurnPolicy.statusText('processing', thinkingText), 'speech');
                updateVoiceChatText(thinkingText);
                setVoicePhase('understanding', 'Understanding request', 0.42);
                break;
            case 'llm_delta':
                if (message.text) {
                    currentAnswerText += message.text;
                    setAssistantSpeechText(currentAnswerText);
                    hydrateStreamingAudioText(message.text);
                    updateDialogSilenceFeedbackText(currentAnswerText, turnId, 'llm_delta');
                }
                break;
            case 'tts_start':
                setVoicePhase('understanding', 'Understanding request', 0.5);
                updateDialogSilenceFeedbackText(message.text, turnId, 'tts_start');
                break;
            case 'tts_audio':
                var speechText = message.text || currentAnswerText || '';
                updateDialogSilenceFeedbackText(speechText, turnId, 'tts_audio');
                enqueueStreamingAudio(message.audio, message.mime || 'audio/wav', speechText, turnId, {
                    bytes: message.bytes,
                    chunkCount: message.chunkCount,
                    durationMs: message.durationMs,
                    replyId: message.replyId
                });
                markDialogSilenceFeedbackAudioSeen(turnId, 'tts_audio');
                break;
            case 'llm_end':
                currentAnswerText = message.text || currentAnswerText;
                setAssistantSpeechText(currentAnswerText);
                hydrateStreamingAudioText(currentAnswerText);
                break;
            case 'command_executed':
                clientLog('voice command executed', {
                    action: message.action,
                    status: message.status,
                    source: message.source,
                    confidence: message.confidence,
                    taskId: message.task_id
                });
                if (message.action === 'adjust_volume' && message.status === 'executed') {
                    adjustVoiceOutputVolume(message.payload || {});
                }
                if (
                    message.action === 'capture_face_enroll'
                    && (
                        message.status === 'input_required'
                        || (message.payload && message.payload.requiresBrowserInput)
                    )
                ) {
                    showFaceNameDialog(message.payload || {});
                }
                break;
            case 'agent_signal':
                clientLog('voice agent signal', {
                    intent: message.intent,
                    status: message.status,
                    visibility: message.visibility,
                    targets: message.target_agents
                });
                break;
            case 'dialog_silence':
                applyDialogSilenceState(message, turnId);
                break;
            case 'done':
                if (turnId !== activeVoiceTurnId) return;
                if (voiceTurnPolicy.shouldIgnoreCompletionMessage(message)) {
                    clientLog('drop interrupted voice completion', {
                        activeTurnId: activeVoiceTurnId,
                        messageTurnId: message.turnId,
                        reason: message.reason || ''
                    });
                    return;
                }
                clearVoiceAsrFinalWatchdog();
                streamingAudioDone = true;
                var dialogSilenceTurn = Boolean(
                    message.dialogSilenced
                    || message.reason === 'dialog_silenced'
                    || message.reason === 'dialog_resumed'
                );
                if (message.dialogSilenced || message.reason === 'dialog_silenced') {
                    if (message.statusText) {
                        voiceDialogSilenceStatusText = String(message.statusText || '');
                    }
                    voiceDialogSilenced = true;
                } else if (message.reason === 'dialog_resumed') {
                    voiceDialogSilenced = false;
                    voiceDialogSilenceStatusText = '';
                }
                if (dialogSilenceTurn) {
                    markDialogSilenceFeedbackDoneSeen(turnId, message.reason || '');
                }
                if (message.dialogSilenced || message.reason === 'dialog_silenced') {
                    if (!voiceDialogSilenceFeedbackActive) {
                        restoreDialogSilenceStatusIfNeeded();
                    }
                }
                var completionStatusText = voiceTurnPolicy.completionStatusText(
                    message.reason || 'ok'
                );
                if (
                    message.reason
                    && message.reason !== 'ok'
                    && !(dialogSilenceTurn && voiceDialogSilenceFeedbackActive)
                ) {
                    updateVoiceChatText(completionStatusText);
                }
                if (message.reason === 'empty_asr') {
                    clearStreamingDialogWatchdog();
                    isDialogBusy = false;
                    acknowledgeStreamingPlaybackIfReady();
                    if (resumeInterruptedSpeechAfterEmptyAsr(turnId)) {
                        break;
                    }
                    showStatus(completionStatusText, 'speech');
                    setVisitorSpeechText('');
                    setAssistantSpeechText('');
                    releaseLocalDialogAudio('local_dialog');
                    setVoicePhase('ready', 'Ready for next visitor', 0.18);
                    window.setTimeout(function () {
                        if (!isDialogBusy && activeVoiceTurnId === turnId) {
                            clearStreamingSpeechDisplay();
                        }
                    }, 1600);
                } else if (
                    !streamingAudioPlaying
                    && streamingAudioQueue.length === 0
                    && !isDialogSilenceFeedbackAwaitingAudio()
                ) {
                    clearStreamingDialogWatchdog();
                    releaseStreamingDialogIfIdle(
                        message.reason && message.reason !== 'ok'
                            ? completionStatusText
                            : ''
                    );
                }
                break;
            case 'session_end':
                clientLog('person voice session ended', {
                    reason: message.reason,
                    conversationId: voiceConversationId
                });
                voiceStreamKeepOpen = false;
                voicePersonSession = null;
                dialogHistory = [];
                voiceConversationId = createVoiceConversationId();
                if (voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
                    voiceStreamWs.close(1000, message.reason || 'person session ended');
                }
                break;
            case 'error':
                var voiceErrorText = voiceStreamErrorStatusText(message);
                updateVoiceChatText(voiceErrorText, 6000);
                setVoicePhase('error', 'Recovering voice channel', 0.22);
                finalizeStreamingDialogTurn(
                    turnId,
                    voiceErrorText
                );
                break;
        }
    }

    function voiceStreamErrorStatusText(message) {
        var detail = String(message && message.message || '').trim();
        if (/403|handshake|credential|credentials|not configured|unauthor/i.test(detail)) {
            return '火山实时语音认证失败，已重置';
        }
        if (detail) {
            return ('对话失败：' + detail).slice(0, 80);
        }
        return '对话失败，已重置';
    }

    function pushVoiceVadPreRoll(input) {
        if (!input || input.length === 0) return;
        voiceVadPreRoll.push(new Float32Array(input));
        while (voiceVadPreRoll.length > VOICE_VAD_PREROLL_FRAMES) {
            voiceVadPreRoll.shift();
        }
    }

    function mergeVoiceVadPreRoll() {
        if (voiceVadPreRoll.length === 0) {
            return new Float32Array(0);
        }
        var total = voiceVadPreRoll.reduce(function (sum, item) { return sum + item.length; }, 0);
        var merged = new Float32Array(total);
        var offset = 0;
        voiceVadPreRoll.forEach(function (item) {
            merged.set(item, offset);
            offset += item.length;
        });
        voiceVadPreRoll = [];
        return merged;
    }

    function trackVoiceVadCandidate(rms, now) {
        if (!voiceVadCandidateStartedAt || now - voiceVadCandidateStartedAt > VOICE_VAD_START_WINDOW_MS) {
            voiceVadCandidateStartedAt = now;
            voiceVadCandidateFrames = 0;
            voiceVadCandidatePeak = 0;
            voiceVadCandidateRmsSum = 0;
        }
        voiceVadCandidateFrames += 1;
        voiceVadCandidatePeak = Math.max(voiceVadCandidatePeak, rms);
        voiceVadCandidateRmsSum += Math.max(0, Number(rms) || 0);
    }

    function getVoiceVadCandidateStats(now) {
        var frames = Math.max(0, voiceVadCandidateFrames);
        var avgRms = frames > 0 ? voiceVadCandidateRmsSum / frames : 0;
        var durationMs = voiceVadCandidateStartedAt
            ? Math.max(0, now - voiceVadCandidateStartedAt)
            : 0;
        var peakToAverage = avgRms > 0
            ? voiceVadCandidatePeak / Math.max(avgRms, 0.000001)
            : 0;
        return {
            avgRms: avgRms,
            durationMs: durationMs,
            peakToAverage: peakToAverage
        };
    }

    function getVoiceBargeInRejectReason(rms, threshold, stats) {
        if (voiceVadCandidateFrames < VOICE_BARGE_IN_START_FRAMES) {
            return 'too_few_frames';
        }
        if ((stats && stats.durationMs || 0) < VOICE_BARGE_IN_MIN_MS) {
            return 'too_short';
        }
        if (rms < threshold) {
            return 'below_threshold';
        }
        if ((stats && stats.avgRms || 0) < threshold * VOICE_BARGE_IN_MIN_AVG_RATIO) {
            return 'weak_average';
        }
        if ((stats && stats.peakToAverage || 0) > VOICE_BARGE_IN_PEAK_AVG_MAX) {
            return 'impulse_noise';
        }
        return 'policy';
    }

    function acceptVoiceVadCandidate(rms, startThreshold, now) {
        trackVoiceVadCandidate(rms, now);
        var peakThreshold = Math.max(VOICE_VAD_PEAK_MIN, startThreshold * 1.25);
        var fastPeakThreshold = Math.max(VOICE_VAD_FAST_PEAK_MIN, startThreshold * 1.9);
        if (voiceVadCandidateFrames >= 2 && voiceVadCandidatePeak >= fastPeakThreshold) {
            return true;
        }
        return voiceVadCandidateFrames >= VOICE_VAD_START_FRAMES
            && voiceVadCandidatePeak >= peakThreshold;
    }

    function resetVoiceVadCandidate() {
        voiceVadCandidateFrames = 0;
        voiceVadCandidateStartedAt = 0;
        voiceVadCandidatePeak = 0;
        voiceVadCandidateRmsSum = 0;
    }

    function rememberDialogTurn(userText, answerText) {
        userText = (userText || '').trim();
        answerText = (answerText || '').trim();
        if (!userText) return;
        dialogHistory.push({ role: 'user', content: userText });
        if (answerText) {
            dialogHistory.push({ role: 'assistant', content: answerText });
        }
        dialogHistory = dialogHistory.slice(-6);
    }

    function enqueueStreamingAudio(base64Audio, mime, text, turnId, metadata) {
        if (!base64Audio) return;
        if (turnId !== activeVoiceTurnId) return;
        text = String(text || '').trim();
        lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS, 'local_dialog');
        scheduleStreamingDialogWatchdog(turnId);
        streamingPlaybackStarted = true;
        streamingAudioQueue.push({
            url: URL.createObjectURL(base64ToBlob(base64Audio, mime)),
            text: text,
            turnId: turnId,
            mime: mime,
            bytes: metadata && metadata.bytes,
            chunkCount: metadata && metadata.chunkCount,
            durationMs: metadata && metadata.durationMs,
            replyId: metadata && metadata.replyId
        });
        playNextStreamingAudio();
    }

    function hydrateStreamingAudioText(text) {
        text = String(text || '').trim();
        if (!text) return;
        var changed = false;
        if (streamingAudioActiveItem && !String(streamingAudioActiveItem.text || '').trim()) {
            streamingAudioActiveItem.text = text;
            changed = true;
        }
        streamingAudioQueue.forEach(function (item) {
            if (item && !String(item.text || '').trim()) {
                item.text = text;
            }
        });
        if (changed && typeof streamingSpeechStatusRefresh === 'function') {
            streamingSpeechStatusRefresh();
        }
    }

    function playNextStreamingAudio() {
        if (streamingAudioPlaying || streamingAudioQueue.length === 0) {
            if (!streamingAudioPlaying && streamingAudioDone) {
                clearStreamingDialogWatchdog();
            }
            releaseStreamingDialogIfIdle();
            return;
        }
        streamingAudioPlaying = true;
        lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS, 'local_dialog');
        var item = streamingAudioQueue.shift();
        if (item.turnId !== activeVoiceTurnId) {
            URL.revokeObjectURL(item.url);
            streamingAudioPlaying = false;
            playNextStreamingAudio();
            return;
        }
        streamingAudioActiveItem = item;
        hydrateStreamingAudioText(currentAnswerText);
        if (audio) {
            audio.pause();
            audio = null;
        }
        var playbackAudio = new Audio(item.url);
        audio = playbackAudio;
        applyVoiceOutputVolume(playbackAudio);
        var finished = false;
        var progressTimer = null;
        var lastAudioTime = 0;
        var lastProgressAt = performance.now();
        var lastSpeechStatusText = '';
        function updateStreamingSpeechStatus() {
            var speechText = item.text || currentAnswerText || '';
            var nextText = speechStatusTextForStreamingAudio(
                speechText,
                playbackAudio,
                item.durationMs,
                item.turnId
            );
            if (nextText && nextText !== lastSpeechStatusText) {
                lastSpeechStatusText = nextText;
                showStatus(nextText, 'speech');
                updateVoiceChatText(nextText);
            }
        }
        streamingSpeechStatusRefresh = updateStreamingSpeechStatus;
        updateStreamingSpeechStatus();
        function finishItem() {
            if (finished) return;
            finished = true;
            if (progressTimer) {
                clearInterval(progressTimer);
                if (streamingAudioProgressTimer === progressTimer) {
                    streamingAudioProgressTimer = null;
                }
                progressTimer = null;
            }
            URL.revokeObjectURL(item.url);
            if (item.replyId) {
                streamingPlayedMsByReply[item.replyId] =
                    (streamingPlayedMsByReply[item.replyId] || 0)
                    + Math.max(0, Math.round((playbackAudio.currentTime || 0) * 1000));
            }
            if (audio === playbackAudio) {
                playbackAudio.pause();
                audio = null;
            } else {
                playbackAudio.pause();
            }
            if (lipSyncAudioElement === playbackAudio) {
                stopLipSync();
            }
            if (streamingAudioActiveItem === item) {
                streamingAudioActiveItem = null;
            }
            if (streamingSpeechStatusRefresh === updateStreamingSpeechStatus) {
                streamingSpeechStatusRefresh = null;
            }
            streamingAudioPlaying = false;
            releaseStreamingSelfSpeechMuteSoon();
            if (streamingAudioDone && streamingAudioQueue.length === 0) {
                clearStreamingDialogWatchdog();
            }
            completeDialogSilenceFeedbackIfPlaybackIdle();
            releaseStreamingDialogIfIdle();
            playNextStreamingAudio();
        }
        playbackAudio.addEventListener('loadedmetadata', function () {
            console.debug('Streaming audio metadata loaded:', {
                mime: item.mime,
                backendBytes: item.bytes,
                backendChunkCount: item.chunkCount,
                backendDurationMs: item.durationMs,
                browserDurationMs: Number.isFinite(playbackAudio.duration) ? Math.round(playbackAudio.duration * 1000) : null
            });
        });
        playbackAudio.addEventListener('canplay', function () {
            console.debug('Streaming audio canplay:', {
                mime: item.mime,
                currentTime: playbackAudio.currentTime,
                duration: playbackAudio.duration
            });
        });
        playbackAudio.addEventListener('playing', function () {
            if (item.turnId !== activeVoiceTurnId) {
                finishItem();
                return;
            }
            muteVoiceDetectionForSelfSpeech(60000);
            if (item.durationMs) {
                selfSpeechMutedUntil = Math.min(
                    selfSpeechMutedUntil,
                    performance.now() + Math.min(20000, Math.max(2500, item.durationMs + 1200))
                );
            }
            lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS, 'local_dialog');
            setVoicePhase('speaking', 'Speaking response', 0.74);
            startLipSync(playbackAudio);
            lastAudioTime = playbackAudio.currentTime || 0;
            lastProgressAt = performance.now();
            updateStreamingSpeechStatus();
            progressTimer = setInterval(function () {
                if (finished || audio !== playbackAudio) return;
                updateStreamingSpeechStatus();
                var currentTime = playbackAudio.currentTime || 0;
                if (currentTime > lastAudioTime + 0.05) {
                    lastAudioTime = currentTime;
                    lastProgressAt = performance.now();
                    return;
                }
                if (!playbackAudio.paused && !playbackAudio.ended && performance.now() - lastProgressAt > STREAMING_AUDIO_STALL_MS) {
                    console.warn('Streaming audio progress stalled; force finishing current item', {
                        currentTime: playbackAudio.currentTime,
                        duration: playbackAudio.duration,
                        readyState: playbackAudio.readyState,
                        networkState: playbackAudio.networkState,
                        backendBytes: item.bytes,
                        backendChunkCount: item.chunkCount,
                        backendDurationMs: item.durationMs
                    });
                    finishItem();
                }
            }, 250);
            streamingAudioProgressTimer = progressTimer;
        });
        playbackAudio.addEventListener('timeupdate', updateStreamingSpeechStatus);
        playbackAudio.addEventListener('waiting', function () {
            console.warn('Streaming audio waiting:', {
                currentTime: playbackAudio.currentTime,
                duration: playbackAudio.duration,
                readyState: playbackAudio.readyState,
                networkState: playbackAudio.networkState
            });
        });
        playbackAudio.addEventListener('stalled', function () {
            console.warn('Streaming audio stalled event:', {
                currentTime: playbackAudio.currentTime,
                duration: playbackAudio.duration,
                readyState: playbackAudio.readyState,
                networkState: playbackAudio.networkState
            });
        });
        playbackAudio.addEventListener('abort', function () {
            finishItem();
        });
        playbackAudio.addEventListener('ended', function () {
            finishItem();
        });
        playbackAudio.addEventListener('error', function () {
            console.error('Streaming audio error:', {
                code: playbackAudio.error && playbackAudio.error.code,
                message: playbackAudio.error && playbackAudio.error.message,
                mime: item.mime,
                backendBytes: item.bytes,
                backendChunkCount: item.chunkCount,
                backendDurationMs: item.durationMs
            });
            finishItem();
        });
        playbackAudio.play().catch(function (err) {
            console.error('Streaming audio play failed:', err);
            finishItem();
        });
    }

    function getStreamingPlaybackProgress() {
        var item = streamingAudioActiveItem;
        if (!item || !item.replyId) {
            return { replyId: '', playedMs: 0 };
        }
        var completedMs = streamingPlayedMsByReply[item.replyId] || 0;
        var activeMs = audio ? Math.max(0, Math.round((audio.currentTime || 0) * 1000)) : 0;
        return {
            replyId: item.replyId,
            playedMs: completedMs + activeMs
        };
    }

    function base64ToBlob(base64, mime) {
        var binary = atob(base64);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return new Blob([bytes], { type: mime || 'audio/wav' });
    }

    function runDialogChat(text, speechStartedAt) {
        var asrMs = Math.round(performance.now() - speechStartedAt);
        var chatStartedAt = performance.now();
        safeBtn(voiceChatButton, 'disabled', true);
        updateVoiceChatText('ASR ' + asrMs + 'ms，正在思考：' + text);

        fetch('/dialog/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || data.detail || 'dialog chat failed');
                    }
                    return data;
                });
            })
            .then(function (data) {
                var answer = data.data && data.data.answer;
                var llmMs = Math.round(performance.now() - chatStartedAt);
                if (!answer) {
                    throw new Error('empty answer');
                }
                setAssistantSpeechText(answer);
                updateVoiceChatText('ASR ' + asrMs + 'ms，LLM ' + llmMs + 'ms');
                return playRawTTS(answer).then(function () {
                    var totalMs = Math.round(performance.now() - speechStartedAt);
                    updateVoiceChatText('总耗时 ' + totalMs + 'ms');
                });
            })
            .catch(function (err) {
                console.error('Dialog chat failed:', err);
                updateVoiceChatText('对话失败：' + err.message);
                hideSubtitle();
                releaseLocalDialogAudio('local_dialog');
            })
            .finally(function () {
                isDialogBusy = false;
                safeBtn(voiceChatButton, 'disabled', false);
                safeBtn(voiceChatButton, 'textContent', '开始说话');
            });
    }

    function updateVoiceChatText(text, autoClearMs) {
        var nextText = String(text || '');
        if (shouldProtectDialogSilenceFeedbackText(nextText)) {
            nextText = voiceDialogSilenceFeedbackText;
            autoClearMs = 0;
        }
        if (shouldProtectDialogSilenceStatus(nextText)) {
            nextText = voiceDialogSilenceStatusText;
            autoClearMs = 0;
        }
        if (shouldProtectInterruptedListeningUi(nextText)) {
            nextText = INTERRUPTED_LISTENING_STATUS_TEXT;
            autoClearMs = 0;
        }
        if (voiceChatText) {
            voiceChatText.textContent = nextText;
        }
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({ voiceChatText: nextText });
        }
        if (voiceChatTextTimer) {
            clearTimeout(voiceChatTextTimer);
            voiceChatTextTimer = null;
        }
        if (autoClearMs > 0 && nextText && voiceChatText) {
            voiceChatTextTimer = setTimeout(function () {
                clearVoiceChatText();
                voiceChatTextTimer = null;
            }, autoClearMs);
        }
    }

    function clearVoiceChatText() {
        if (voiceChatTextTimer) {
            clearTimeout(voiceChatTextTimer);
            voiceChatTextTimer = null;
        }
        if (shouldProtectDialogSilenceFeedbackText('')) {
            updateVoiceChatText(voiceDialogSilenceFeedbackText);
            return;
        }
        if (shouldProtectDialogSilenceStatus('')) {
            updateVoiceChatText(voiceDialogSilenceStatusText);
            return;
        }
        if (shouldProtectInterruptedListeningUi('')) {
            updateVoiceChatText(INTERRUPTED_LISTENING_STATUS_TEXT);
            return;
        }
        if (voiceChatText) {
            voiceChatText.textContent = '';
        }
        if (typeof broadcastStateToControl === 'function') {
            broadcastStateToControl({ voiceChatText: '' });
        }
    }

    function shouldProtectDialogSilenceStatus(nextText) {
        if (!voiceDialogSilenced || !voiceDialogSilenceStatusText) {
            return false;
        }
        if (fixedSpeechActive || fixedSpeechPlaybackActive || voiceDialogSilenceFeedbackActive) {
            return false;
        }
        return String(nextText || '') !== voiceDialogSilenceStatusText;
    }

    function shouldProtectDialogSilenceFeedbackText(nextText) {
        if (
            !voiceDialogSilenceFeedbackActive
            || voiceDialogSilenceFeedbackAudioSeen
            || !voiceDialogSilenceFeedbackText
        ) {
            return false;
        }
        return String(nextText || '') !== voiceDialogSilenceFeedbackText;
    }

    function restoreDialogSilenceStatusIfNeeded() {
        if (
            !voiceDialogSilenced
            || !voiceDialogSilenceStatusText
            || fixedSpeechActive
            || fixedSpeechPlaybackActive
            || voiceDialogSilenceFeedbackActive
        ) {
            return;
        }
        updateVoiceChatText(voiceDialogSilenceStatusText);
        showStatus(voiceDialogSilenceStatusText, 'speech');
    }

    function completeDialogSilenceFeedbackIfPlaybackIdle() {
        if (!voiceDialogSilenceFeedbackActive) {
            return;
        }
        if (!voiceDialogSilenceFeedbackAudioSeen) {
            return;
        }
        if (streamingAudioPlaying || streamingAudioQueue.length > 0) {
            return;
        }
        finishDialogSilenceFeedback('playback_idle');
    }

    function finishDialogSilenceFeedback(reason) {
        if (!voiceDialogSilenceFeedbackActive) {
            return false;
        }
        if (voiceDialogSilenceFeedbackTimer) {
            clearTimeout(voiceDialogSilenceFeedbackTimer);
            voiceDialogSilenceFeedbackTimer = null;
        }
        var restoresSilence = voiceDialogSilenceFeedbackRestoresSilence;
        var statusText = voiceDialogSilenceFeedbackStatusText;
        if (!restoresSilence) {
            voiceDialogSilenced = false;
            voiceDialogSilenceStatusText = '';
        }
        voiceDialogSilenceFeedbackActive = false;
        voiceDialogSilenceFeedbackTurnId = 0;
        voiceDialogSilenceFeedbackAudioSeen = false;
        voiceDialogSilenceFeedbackDoneSeen = false;
        voiceDialogSilenceFeedbackRestoresSilence = false;
        voiceDialogSilenceFeedbackStatusText = '';
        voiceDialogSilenceFeedbackText = '';
        voiceDialogSilenceFeedbackDynamic = false;
        clientLog('dialog silence feedback finished', {
            reason: reason || '',
            restoresSilence: restoresSilence
        });
        if (restoresSilence) {
            restoreDialogSilenceStatusIfNeeded();
        } else if (statusText) {
            updateVoiceChatText(statusText, 1600);
            showStatus(statusText, 'speech');
        }
        if (streamingAudioDone && !streamingAudioPlaying && streamingAudioQueue.length === 0) {
            releaseStreamingDialogIfIdle(restoresSilence ? '' : statusText);
        }
        return true;
    }

    function beginDialogSilenceFeedback(message, turnId, active, statusText) {
        var feedbackText = String(message && message.responseText || '').trim();
        var dynamicFeedback = Boolean(message && message.dynamicFeedback);
        if (!feedbackText && !dynamicFeedback) {
            return false;
        }
        if (voiceDialogSilenceFeedbackTimer) {
            clearTimeout(voiceDialogSilenceFeedbackTimer);
            voiceDialogSilenceFeedbackTimer = null;
        }
        voiceDialogSilenceFeedbackActive = true;
        voiceDialogSilenceFeedbackTurnId = turnId || activeVoiceTurnId;
        voiceDialogSilenceFeedbackAudioSeen = false;
        voiceDialogSilenceFeedbackDoneSeen = false;
        voiceDialogSilenceFeedbackRestoresSilence = Boolean(active);
        voiceDialogSilenceFeedbackStatusText = statusText || feedbackText;
        voiceDialogSilenceFeedbackText = feedbackText;
        voiceDialogSilenceFeedbackDynamic = dynamicFeedback;
        if (!active) {
            voiceDialogSilenced = false;
            voiceDialogSilenceStatusText = '';
        }
        if (feedbackText) {
            updateVoiceChatText(feedbackText);
            showStatus(feedbackText, 'speech');
        }
        clientLog('dialog silence feedback started', {
            active: Boolean(active),
            turnId: voiceDialogSilenceFeedbackTurnId,
            feedbackChars: feedbackText.length,
            dynamicFeedback: dynamicFeedback
        });
        voiceDialogSilenceFeedbackTimer = window.setTimeout(function () {
            if (!voiceDialogSilenceFeedbackActive) {
                return;
            }
            clientLog('dialog silence feedback audio timeout', {
                turnId: voiceDialogSilenceFeedbackTurnId,
                audioSeen: voiceDialogSilenceFeedbackAudioSeen,
                doneSeen: voiceDialogSilenceFeedbackDoneSeen
            });
            finishDialogSilenceFeedback('audio_timeout');
        }, 12000);
        return true;
    }

    function updateDialogSilenceFeedbackText(text, turnId, source) {
        var nextText = String(text || '').trim();
        if (
            !nextText
            || !voiceDialogSilenceFeedbackActive
            || voiceDialogSilenceFeedbackTurnId !== turnId
        ) {
            return false;
        }
        if (nextText === voiceDialogSilenceFeedbackText) {
            return false;
        }
        voiceDialogSilenceFeedbackText = nextText;
        if (!voiceDialogSilenceFeedbackRestoresSilence) {
            voiceDialogSilenceFeedbackStatusText = nextText;
        }
        updateVoiceChatText(nextText);
        showStatus(nextText, 'speech');
        clientLog('dialog silence feedback text updated', {
            turnId: turnId,
            source: source || '',
            chars: nextText.length,
            dynamicFeedback: voiceDialogSilenceFeedbackDynamic
        });
        return true;
    }

    function markDialogSilenceFeedbackAudioSeen(turnId, source) {
        if (
            !voiceDialogSilenceFeedbackActive
            || voiceDialogSilenceFeedbackTurnId !== turnId
        ) {
            return;
        }
        if (!voiceDialogSilenceFeedbackAudioSeen) {
            voiceDialogSilenceFeedbackAudioSeen = true;
            if (voiceDialogSilenceFeedbackTimer) {
                clearTimeout(voiceDialogSilenceFeedbackTimer);
                voiceDialogSilenceFeedbackTimer = null;
            }
            clientLog('dialog silence feedback audio received', {
                turnId: turnId,
                source: source || ''
            });
        }
        completeDialogSilenceFeedbackIfPlaybackIdle();
    }

    function markDialogSilenceFeedbackDoneSeen(turnId, reason) {
        if (
            !voiceDialogSilenceFeedbackActive
            || voiceDialogSilenceFeedbackTurnId !== turnId
        ) {
            return;
        }
        voiceDialogSilenceFeedbackDoneSeen = true;
        clientLog('dialog silence feedback done seen', {
            turnId: turnId,
            reason: reason || '',
            audioSeen: voiceDialogSilenceFeedbackAudioSeen,
            queueLength: streamingAudioQueue.length,
            playing: streamingAudioPlaying
        });
        completeDialogSilenceFeedbackIfPlaybackIdle();
    }

    function isDialogSilenceFeedbackAwaitingAudio() {
        return Boolean(
            voiceDialogSilenceFeedbackActive
            && !voiceDialogSilenceFeedbackAudioSeen
        );
    }

    function applyDialogSilenceState(message, turnId) {
        var active = Boolean(message && message.active);
        var statusText = String(message && message.statusText || '').trim();
        var hasFeedback = Boolean(message && String(message.responseText || '').trim());
        voiceDialogSilenced = active;
        voiceDialogSilenceStatusText = active ? statusText : '';
        clientLog('dialog silence state changed', {
            active: active,
            assistantName: message && message.assistantName || '',
            hasFeedback: hasFeedback
        });
        if (beginDialogSilenceFeedback(message, turnId, active, statusText)) {
            return;
        }
        if (active) {
            restoreDialogSilenceStatusIfNeeded();
            return;
        }
        if (statusText) {
            updateVoiceChatText(statusText, 1600);
            showStatus(statusText, 'speech');
        }
    }

    function clearStreamingSpeechDisplay() {
        clearStatusBeforeDeferredSpeech();
        clearVoiceChatText();
        setVisitorSpeechText('');
        setAssistantSpeechText('');
    }

    function clearSpeechUi() {
        clearExternalSpeechWatchdog();
        statusMode = 'idle';
        stopLipSync();
        hideSubtitle();
        clearStreamingSpeechDisplay();
        setVoicePhase('ready', 'Ready for next visitor', 0.18);
    }

    function scheduleExternalSpeechWatchdog(text) {
        clearExternalSpeechWatchdog();
        var textLength = (text || '').length;
        var timeoutMs = Math.min(90000, Math.max(12000, textLength * 450 + 6000));
        externalSpeechWatchdogTimer = setTimeout(function () {
            externalSpeechWatchdogTimer = null;
            if (activeSpeechOwner !== 'doubao_realtime') {
                return;
            }
            console.warn('Realtime speech_end watchdog fired');
            forceResetVoiceLayer('doubao realtime speech_end watchdog');
            scheduleIdle(800);
        }, timeoutMs);
    }

    function clearExternalSpeechWatchdog() {
        if (externalSpeechWatchdogTimer) {
            clearTimeout(externalSpeechWatchdogTimer);
            externalSpeechWatchdogTimer = null;
        }
    }

    function unlockAudio() {
        if (audioUnlocked) return;
        audioUnlocked = true;
        var silentAudio = new Audio();
        silentAudio.muted = true;
        silentAudio.play().catch(function () { });
        ensureAudioContext();
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume().catch(function () { });
        }
    }

    function ensureAudioContext() {
        if (!audioContext) {
            var AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (AudioContextClass) {
                audioContext = new AudioContextClass();
            }
        }
        return audioContext;
    }

    function startLipSync(audioElement) {
        if (!model || !audioElement) return;
        stopLipSync();
        var token = ++lipSyncToken;
        lipSyncAudioElement = audioElement;
        lipSyncMode = 'audio';
        lipStartedAt = performance.now();
        setMouthOpen(0.28);

        var ctx = ensureAudioContext();
        if (!ctx) {
            startFallbackLipSync(audioElement, token);
            return;
        }

        try {
            if (ctx.state === 'suspended') {
                ctx.resume().catch(function () { });
            }
            var source = ctx.createMediaElementSource(audioElement);
            lipSourceNode = source;
            lipGainNode = ctx.createGain();
            lipGainNode.gain.value = voiceOutputVolume;
            lipAnalyser = ctx.createAnalyser();
            lipAnalyser.fftSize = 256;
            lipData = new Uint8Array(lipAnalyser.fftSize);
            source.connect(lipGainNode);
            lipGainNode.connect(lipAnalyser);
            lipAnalyser.connect(ctx.destination);
            animateLipByAudio(audioElement, token);
        } catch (e) {
            clientLog('lip sync analyser unavailable, fallback animation used', {
                error: e && e.message ? e.message : String(e || '')
            });
            startFallbackLipSync(audioElement, token);
        }
    }

    function animateLipByAudio(audioElement, token) {
        if (token !== lipSyncToken || audioElement !== lipSyncAudioElement || lipSyncMode !== 'audio') {
            return;
        }
        if (!lipAnalyser || !lipData || !audioElement || audioElement.paused || audioElement.ended) {
            stopLipSync(token);
            return;
        }

        lipAnalyser.getByteTimeDomainData(lipData);
        var sum = 0;
        for (var i = 0; i < lipData.length; i++) {
            var normalized = (lipData[i] - 128) / 128;
            sum += normalized * normalized;
        }
        var rms = Math.sqrt(sum / lipData.length);
        var elapsed = performance.now() - lipStartedAt;
        var target = Math.max(0, Math.min(1, (rms - 0.012) * 6.4));
        if (elapsed < 520 && target < 0.22) {
            target = 0.24 + Math.abs(Math.sin(elapsed / 42)) * 0.28;
        }
        lipValue = lipValue * 0.58 + target * 0.42;
        setMouthOpen(lipValue);
        lipFrame = requestAnimationFrame(function () {
            animateLipByAudio(audioElement, token);
        });
    }

    function startFallbackLipSync(audioElement, token) {
        if (token !== lipSyncToken || audioElement !== lipSyncAudioElement || lipSyncMode !== 'audio') {
            return;
        }
        if (!audioElement || audioElement.paused || audioElement.ended) {
            stopLipSync(token);
            return;
        }
        var t = performance.now() / 1000;
        var target = 0.18 + Math.abs(Math.sin(t * 13.5)) * 0.62 + Math.abs(Math.sin(t * 6.2)) * 0.16;
        lipValue = lipValue * 0.45 + Math.min(1, target) * 0.55;
        setMouthOpen(lipValue);
        lipFrame = requestAnimationFrame(function () {
            startFallbackLipSync(audioElement, token);
        });
    }

    function startExternalLipSync(token) {
        if (!model) return 0;
        if (!token) {
            stopLipSync();
            token = ++lipSyncToken;
            lipSyncAudioElement = null;
            lipSyncMode = 'external';
        }
        if (token !== lipSyncToken || lipSyncMode !== 'external') {
            return 0;
        }
        var now = performance.now();

        if (!lipFrame || externalLipNextChangeAt <= 0) {
            lipValue = 0.18;
            externalLipTarget = 0.42;
            externalLipNextChangeAt = now;
            externalLipPauseUntil = 0;
            externalLipNextPauseAt = now + 650 + Math.random() * 950;
            setMouthOpen(lipValue);
        }

        if (now >= externalLipNextPauseAt) {
            externalLipPauseUntil = now + 70 + Math.random() * 170;
            externalLipNextPauseAt = now + 760 + Math.random() * 1200;
        }

        if (now < externalLipPauseUntil) {
            externalLipTarget = 0.03 + Math.random() * 0.08;
        } else if (now >= externalLipNextChangeAt) {
            var r = Math.random();
            if (r < 0.16) {
                externalLipTarget = 0.02 + Math.random() * 0.08;
            } else if (r < 0.42) {
                externalLipTarget = 0.16 + Math.random() * 0.16;
            } else if (r < 0.82) {
                externalLipTarget = 0.34 + Math.random() * 0.24;
            } else {
                externalLipTarget = 0.58 + Math.random() * 0.24;
            }
            externalLipNextChangeAt = now + 55 + Math.random() * 95;
        }

        var target = Math.max(0, Math.min(1, externalLipTarget));
        var smoothing = target > lipValue ? 0.46 : 0.34;
        lipValue = lipValue * (1 - smoothing) + target * smoothing;
        if (lipValue < 0.035) lipValue = 0;
        setMouthOpen(lipValue);
        lipFrame = requestAnimationFrame(function () {
            startExternalLipSync(token);
        });
        return token;
    }

    function stopLipSync(expectedToken) {
        if (expectedToken !== undefined && expectedToken !== lipSyncToken) {
            return;
        }
        lipSyncToken++;
        if (lipFrame) {
            cancelAnimationFrame(lipFrame);
            lipFrame = null;
        }
        if (lipSourceNode) {
            try {
                lipSourceNode.disconnect();
            } catch (e0) { }
        }
        if (lipGainNode) {
            try {
                lipGainNode.disconnect();
            } catch (e1) { }
        }
        if (lipAnalyser) {
            try {
                lipAnalyser.disconnect();
            } catch (e2) { }
        }
        lipAnalyser = null;
        lipGainNode = null;
        lipSourceNode = null;
        lipData = null;
        lipSyncAudioElement = null;
        lipSyncMode = '';
        lipValue = 0;
        externalLipTarget = 0;
        externalLipNextChangeAt = 0;
        externalLipPauseUntil = 0;
        externalLipNextPauseAt = 0;
        lipStartedAt = 0;
        setMouthOpen(0);
    }

    function setMouthOpen(value) {
        mouthOpenValue = Math.max(0, Math.min(1, value || 0));
        applyMouthOpen();
    }

    function applyMouthOpen() {
        if (!model || !model.internalModel || !model.internalModel.coreModel) return;
        var coreModel = model.internalModel.coreModel;
        var v = mouthOpenValue;
        var ids = [];
        try {
            var settings = model.internalModel.settings;
            if (settings && typeof settings.getLipSyncParameters === 'function') {
                ids = settings.getLipSyncParameters() || [];
            }
        } catch (e0) { }

        ['PARAM_MOUTH_OPEN_Y', 'ParamMouthOpenY'].forEach(function (id) {
            if (ids.indexOf(id) < 0) ids.push(id);
        });

        ids.forEach(function (id) {
            try {
                coreModel.setParameterValueById(id, v);
            } catch (e) { }
        });
    }

    function bindMouthOpen(modelInstance) {
        if (!modelInstance || !modelInstance.internalModel || mouthBoundModel === modelInstance) return;
        mouthBoundModel = modelInstance;
        modelInstance.internalModel.on('beforeModelUpdate', applyMouthOpen);
    }

    function loadSubtitleText(name, type, variant) {
        var url = '/tts-text?name=' + encodeURIComponent(name) + '&type=' + type + '&variant=' + variant;
        return fetch(url)
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) {
                return data && data.text ? data.text : '';
            })
            .catch(function () { return ''; });
    }

    function showSubtitle(text) {
        if (!subtitleEl) return;
        if (subtitleTimer) {
            clearTimeout(subtitleTimer);
            subtitleTimer = null;
        }
        subtitleEl.textContent = text;
        subtitleEl.classList.add('visible');
        var duration = Math.max(3600, Math.min(7600, text.length * 220));
        subtitleTimer = setTimeout(function () {
            hideSubtitle();
        }, duration);
    }

    function hideSubtitle(delay) {
        if (!subtitleEl) return;
        if (subtitleTimer) {
            clearTimeout(subtitleTimer);
            subtitleTimer = null;
        }
        subtitleTimer = setTimeout(function () {
            subtitleEl.classList.remove('visible');
        }, delay || 0);
    }

    function pick(items) {
        return items[Math.floor(Math.random() * items.length)];
    }

    function getBehaviorConfig(name) {
        var base = BEHAVIORS[name];
        if (!base) return null;

        var modelOverrides = MODEL_BEHAVIOR_OVERRIDES[currentModelKey] || {};
        var override = modelOverrides[name];
        if (!override) return base;

        var config = {};
        Object.keys(base).forEach(function (key) {
            config[key] = base[key];
        });
        Object.keys(override).forEach(function (key) {
            config[key] = override[key];
        });
        return config;
    }

    function resolveBehaviorExpression(behavior) {
        if (behavior.expressionPool === 'all') {
            var buttons = (currentModelConfig && currentModelConfig.expressionButtons) || [];
            return buttons.length > 0 ? pick(buttons) : (behavior.expression || 'Normal');
        }
        if (Array.isArray(behavior.expression)) {
            return pick(behavior.expression);
        }
        return behavior.expression || 'Normal';
    }

    function resolveBehaviorMotions(behavior) {
        if (behavior.motionPool === 'all' || behavior.motionPool === 'visible') {
            var counts = (currentModelConfig && currentModelConfig.motionCounts) || {};
            var motions = [];
            Object.keys(counts).forEach(function (group) {
                if (behavior.motionPool === 'visible' && group === 'Idle') return;
                for (var i = 0; i < counts[group]; i++) {
                    motions.push([group, i]);
                }
            });
            return motions.length > 0 ? motions : (behavior.motions || []);
        }
        return behavior.motions || [];
    }

    function runBehavior(name, options) {
        if (!model) return;

        options = options || {};
        var behavior = getBehaviorConfig(name);
        if (!behavior) return;

        lastBehaviorName = name;
        lastBehaviorAt = performance.now();
        idleState = name;
        stopIdleCycle();
        clearIdleTimer();

        setExpression(resolveBehaviorExpression(behavior));

        var motions = resolveBehaviorMotions(behavior);
        if (motions.length > 0) {
            var motion = pick(motions);
            setTimeout(function () {
                playMotion(motion[0], motion[1]);
            }, 80);
        }

        if (behavior.tts && options.silent !== true) {
            playTTS(options.name || '访客', options.tts || behavior.tts);
        }

        scheduleIdle(options.idleDelay || behavior.idleDelay || 4000);
    }

    function normalizeSpeechBehaviorType(type) {
        if (type === 'first_time') return 'first_time';
        if (type === 'returning') return 'returning';
        if (type === 'check_in') return 'check_in';
        if (type === 'check_out') return 'check_out';
        if (type === 'stranger' || type === 'returning_stranger') return 'stranger';
        if (type === 'stranger_stare') return 'stranger_stare';
        if (type === 'repeat') return 'repeat';
        if (type === 'checked_in_stare') return 'checked_in_stare';
        if (type === 'gesture_wave') return 'gesture_wave';
        if (type === 'gesture_thumbs_up') return 'gesture_thumbs_up';
        if (type === 'gesture_heart') return 'gesture_heart';
        if (type === 'gesture_ok') return 'gesture_ok';
        if (type === 'gesture_peace') return 'gesture_peace';
        if (type === 'gesture_middle_finger') return 'gesture_middle_finger';
        return '';
    }

    function maybeRunSpeechVisualFallback(msg) {
        var behaviorName = normalizeSpeechBehaviorType(msg.event_type || msg.type);
        if (!behaviorName) return;
        var now = performance.now();
        if (behaviorName !== 'first_time' && lastBehaviorName === behaviorName && now - lastBehaviorAt < 1400) {
            return;
        }
        setTimeout(function () {
            runBehavior(behaviorName, { name: msg.name || '访客', silent: true });
        }, behaviorName === 'first_time' ? 260 : 0);
    }

    function doAction(action) {
        switch (action) {
            case 'wave':
                runBehavior('wave', { silent: true });
                break;
            case 'greet':
                runBehavior('greet', { name: '访客' });
                break;
            case 'bye':
                runBehavior('bye', { name: '访客' });
                break;
            case 'surprise':
                runBehavior('stranger', { name: '访客', silent: true });
                break;
            case 'smile':
                setExpression('Smile');
                break;
        }
    }

    function buildModelSwitcher() {
        if (!modelSwitcherEl) return;
        modelSwitcherEl.innerHTML = '';

        Object.keys(MODEL_REGISTRY).forEach(function (key) {
            var config = MODEL_REGISTRY[key];
            var button = document.createElement('button');
            button.type = 'button';
            button.dataset.model = key;
            button.classList.toggle('active', key === currentModelKey);
            button.addEventListener('click', function () {
                requestSwitchModel(key);
            });

            var avatarEl = document.createElement('div');
            avatarEl.className = 'model-avatar';
            avatarEl.textContent = config.label.charAt(0);

            var infoEl = document.createElement('div');
            infoEl.className = 'model-info';

            var nameEl = document.createElement('div');
            nameEl.className = 'model-name';
            nameEl.textContent = config.label;

            var roleEl = document.createElement('div');
            roleEl.className = 'model-role';
            roleEl.textContent = config.role || '';

            infoEl.appendChild(nameEl);
            infoEl.appendChild(roleEl);
            button.appendChild(avatarEl);
            button.appendChild(infoEl);
            modelSwitcherEl.appendChild(button);
        });
    }

    function setModelSwitcherBusy(isBusy) {
        if (!modelSwitcherEl) return;
        modelSwitcherEl.querySelectorAll('button').forEach(function (button) {
            button.disabled = isBusy;
            button.classList.toggle('active', button.dataset.model === currentModelKey);
        });
    }

    function buildInteractionModeSwitcher() {
        if (!interactionModeSwitcherEl) return;
        interactionModeSwitcherEl.innerHTML = '';
        interactionModes.forEach(function (mode) {
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = mode.label || mode.key;
            button.title = mode.description || '';
            button.dataset.mode = mode.key;
            button.classList.toggle('active', mode.key === interactionMode);
            button.addEventListener('click', function () {
                requestInteractionMode(mode.key);
            });
            interactionModeSwitcherEl.appendChild(button);
        });
    }

    function setInteractionModeSwitcherBusy(isBusy) {
        if (!interactionModeSwitcherEl) return;
        interactionModeSwitcherEl.querySelectorAll('button').forEach(function (button) {
            button.disabled = isBusy;
            button.classList.toggle('active', button.dataset.mode === interactionMode);
        });
    }

    function applyInteractionMode(modeKey, modes) {
        interactionMode = modeKey || interactionMode;
        if (Array.isArray(modes)) {
            interactionModes = modes;
        }
        var selected = interactionModes.find(function (item) { return item.key === interactionMode; }) || {};
        realtimeDialogEnabled = Boolean(selected.realtimeDialog);
        realtimeRagEnabled = Boolean(selected.realtimeRag);
        buildInteractionModeSwitcher();
        if (voiceChatText) {
            if (!avatarSessionValid) {
                updateVoiceChatText('设备会话失效，请从客户端重新打开前台', 3000);
            } else if (voiceStreamUrl) {
                updateVoiceChatText('我在听，你直接说话', 3000);
            } else if (realtimeDialogEnabled) {
                updateVoiceChatText(realtimeRagEnabled ? '实时语音 RAG 已接管，可以直接说话' : '实时语音已接管，可以直接说话', 3000);
            } else {
                updateVoiceChatText('语录模式', 3000);
            }
        }
    }

    function refreshDialogSettings() {
        return fetchJsonWithError('/dialog-settings', { cache: 'no-store' })
            .then(function (data) {
                applyDialogSettingsData(data);
                if (!avatarSessionValid) return;
                if (!voiceStreamUrl && (realtimeDialogEnabled || interactionMode === 'quotes_only')) {
                    activeVoiceTurnId = ++voiceTurnId;
                    if (voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
                        voiceStreamWs.close();
                    }
                    voiceStreamWs = null;
                    isListening = false;
                    voiceSpeechStarted = false;
                    streamingAudioQueue.forEach(function (item) {
                        if (item.url) URL.revokeObjectURL(item.url);
                    });
                    if (streamingAudioActiveItem && streamingAudioActiveItem.url) {
                        URL.revokeObjectURL(streamingAudioActiveItem.url);
                    }
                    streamingAudioQueue = [];
                    streamingAudioPlaying = false;
                    streamingAudioActiveItem = null;
                    streamingPlayedMsByReply = {};
                    if (streamingAudioProgressTimer) {
                        clearInterval(streamingAudioProgressTimer);
                        streamingAudioProgressTimer = null;
                    }
                    releaseLocalDialogAudio('local_dialog');
                    cleanupVoiceCapture();
                    voiceMonitorReady = false;
                }
                setupVoiceChat();
            })
            .catch(handleDialogSettingsError);
    }

    function loadInteractionMode() {
        return fetch('/interaction-mode')
            .then(function (res) { return res.ok ? res.json() : {}; })
            .then(function (data) {
                applyInteractionMode(data.mode, data.modes || []);
            })
            .catch(function () {
                interactionModes = [];
                buildInteractionModeSwitcher();
            });
    }

    function requestInteractionMode(modeKey) {
        if (!modeKey || modeKey === interactionMode) return;
        setInteractionModeSwitcherBusy(true);
        fetch('/interaction-mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: modeKey })
        })
            .then(function (res) {
                if (!res.ok) throw new Error('mode switch failed');
                return res.json();
            })
            .then(function (data) {
                applyInteractionMode(data.mode, data.modes || interactionModes);
                return refreshDialogSettings();
            })
            .catch(function (err) {
                console.error('Interaction mode switch failed:', err);
                updateVoiceChatText('链路切换失败', 3000);
            })
            .finally(function () {
                setInteractionModeSwitcherBusy(false);
            });
    }

    function notifyAvatarReady() {
        fetch('/avatar-ready', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: currentModelKey,
                label: currentModelConfig && currentModelConfig.label,
                voice: currentModelConfig && currentModelConfig.voice,
                handoffText: currentModelConfig && getModelHandoffText(currentModelConfig)
            })
        }).catch(function () { });
    }

    function buildDebugPanel() {
        if (!model || !currentModelConfig) return;
        var exprContainer = document.getElementById('expression-buttons');
        var motionContainer = document.getElementById('motion-buttons');
        if (!exprContainer && !motionContainer) return;
        if (exprContainer) exprContainer.innerHTML = '';
        if (motionContainer) motionContainer.innerHTML = '';

        var expressions = currentModelConfig.expressionButtons || [];
        if (exprContainer) {
            if (expressions.length === 0) {
                var empty = document.createElement('button');
                empty.textContent = '无表情';
                empty.disabled = true;
                exprContainer.appendChild(empty);
            }

            expressions.forEach(function (name) {
                var expression = resolveExpression(name);
                if (!expression) return;
                var button = document.createElement('button');
                button.textContent = getExpressionLabel(name);
                button.dataset.name = expression;
                button.addEventListener('click', function () {
                    setExpression(expression);
                });
                exprContainer.appendChild(button);
            });
        }

        var motionLabels = {
            '': '动作',
            Idle: '待机',
            Tap: '轻点',
            Flick: '轻弹',
            FlickUp: '上弹',
            FlickDown: '下弹',
            Flick3: '三连弹',
            FlickRight: '右弹',
            FlickLeft: '左弹',
            Shake: '摇头',
            'FlickUp@Head': '头部上弹',
            'Flick@Body': '身体轻弹',
            'FlickDown@Body': '身体下弹',
            'Tap@Head': '头部轻点',
            'Tap@Body': '身体轻点'
        };

        var motionCounts = currentModelConfig.motionCounts || {};
        if (motionContainer) {
            for (var internalName in motionCounts) {
                var count = motionCounts[internalName] || 1;
                for (var i = 0; i < count; i++) {
                    (function (name, index) {
                        var indexLabels = (currentModelConfig.motionIndexLabels && currentModelConfig.motionIndexLabels[name]) || {};
                        var motionLabel = indexLabels[index] || motionLabels[name] || name || '动作';
                        var button = document.createElement('button');
                        button.textContent = motionLabel + (count > 1 ? '[' + index + ']' : '');
                        button.addEventListener('click', function () {
                            playMotion(name, index);
                        });
                        motionContainer.appendChild(button);
                    })(internalName, i);
                }
            }

            var mouthOpenButton = document.createElement('button');
            mouthOpenButton.textContent = '张嘴';
            mouthOpenButton.addEventListener('click', function () {
                stopLipSync();
                setMouthOpen(1);
            });
            motionContainer.appendChild(mouthOpenButton);

            var mouthCloseButton = document.createElement('button');
            mouthCloseButton.textContent = '闭嘴';
            mouthCloseButton.addEventListener('click', function () {
                stopLipSync();
                setMouthOpen(0);
            });
            motionContainer.appendChild(mouthCloseButton);
        }
    }

    function getInitialModelKey() {
        var params = new URLSearchParams(location.search);
        var fromUrl = params.get('model');
        if (fromUrl && MODEL_REGISTRY[fromUrl]) {
            return fromUrl;
        }

        try {
            var stored = localStorage.getItem('avatarModel');
            if (stored && MODEL_REGISTRY[stored]) {
                return stored;
            }
        } catch (e) { }

        return DEFAULT_MODEL_KEY;
    }

    function persistAvatarModelKey(key) {
        if (!key || !MODEL_REGISTRY[key]) return;
        try {
            localStorage.setItem('avatarModel', key);
        } catch (e) { }
    }

    function sleep(ms) {
        return new Promise(function (resolve) {
            setTimeout(resolve, ms);
        });
    }

    async function loadLive2DModelWithRetry(config) {
        if (modelLoadCache.has(config.path)) {
            return modelLoadCache.get(config.path);
        }
        if (modelLoadPromises.has(config.path)) {
            return modelLoadPromises.get(config.path);
        }
        var loadPromise = (async function () {
            var lastError = null;
            var startedAt = performance.now();
            for (var attempt = 1; attempt <= MODEL_LOAD_ATTEMPTS; attempt++) {
                try {
                    var loadedModel = await Live2DModel.from(config.path);
                    modelLoadCache.set(config.path, loadedModel);
                    console.info('Live2D model loaded:', config.path, Math.round(performance.now() - startedAt) + 'ms');
                    return loadedModel;
                } catch (err) {
                    lastError = err;
                    console.error('Model load failed:', config.path, err);
                    if (attempt < MODEL_LOAD_ATTEMPTS) {
                        await sleep(700 * attempt);
                    }
                }
            }
            throw lastError || new Error('model load failed');
        })();
        modelLoadPromises.set(config.path, loadPromise);
        loadPromise.then(function () {
            modelLoadPromises.delete(config.path);
        }, function () {
            modelLoadPromises.delete(config.path);
        });
        return loadPromise;
    }

    function startModelPreload() {
        if (modelPreloadStarted) return;
        modelPreloadStarted = true;
        var keys = Object.keys(MODEL_REGISTRY).filter(function (key) {
            return key !== currentModelKey;
        });
        var index = 0;
        var active = 0;

        function loadNext() {
            while (active < MODEL_PRELOAD_CONCURRENCY && index < keys.length) {
                let key = keys[index++];
                active += 1;
                loadLive2DModelWithRetry(MODEL_REGISTRY[key])
                    .then(function (loadedModel) {
                        if (loadedModel && loadedModel.visible !== false) {
                            loadedModel.visible = false;
                        }
                    })
                    .catch(function (err) {
                        console.warn('Model preload failed:', key, err);
                    })
                    .finally(function () {
                        active -= 1;
                        setTimeout(loadNext, 80);
                    });
            }
        }

        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(loadNext, { timeout: 2500 });
        } else {
            setTimeout(loadNext, 1200);
        }
    }

    function getFallbackModelKeys(preferredKey) {
        var keys = [preferredKey, DEFAULT_MODEL_KEY].concat(Object.keys(MODEL_REGISTRY));
        return keys.filter(function (key, index) {
            return MODEL_REGISTRY[key] && keys.indexOf(key) === index;
        });
    }

    async function loadStartupModel(preferredKey) {
        var lastError = null;
        var keys = getFallbackModelKeys(preferredKey);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            try {
                var loadedModel = await loadLive2DModelWithRetry(MODEL_REGISTRY[key]);
                return { key: key, model: loadedModel };
            } catch (err) {
                lastError = err;
            }
        }
        throw lastError || new Error('all models failed');
    }

    function easeInOutCubic(t) {
        return t < 0.5
            ? 4 * t * t * t
            : 1 - Math.pow(-2 * t + 2, 3) / 2;
    }

    function crossfadeModels(previousModel, nextModel, durationMs) {
        durationMs = Math.max(120, durationMs || MODEL_SWITCH_FADE_MS);
        if (!previousModel || !nextModel) {
            if (nextModel) nextModel.alpha = 1;
            return Promise.resolve();
        }

        previousModel.alpha = 1;
        nextModel.alpha = 0;
        return new Promise(function (resolve) {
            var startedAt = performance.now();

            function tick(now) {
                var progress = Math.min(1, (now - startedAt) / durationMs);
                var eased = easeInOutCubic(progress);
                previousModel.alpha = 1 - eased;
                nextModel.alpha = eased;
                if (progress < 1) {
                    requestAnimationFrame(tick);
                    return;
                }
                previousModel.alpha = 0;
                nextModel.alpha = 1;
                resolve();
            }

            requestAnimationFrame(tick);
        });
    }

    function getModelHandoffText(config) {
        if (!config) return '角色已切换。';
        return config.handoffText || (config.label + '已接棒，我们继续。');
    }

    function showModelTransition(config, text) {
        if (!modelTransitionEl) return;
        if (modelTransitionNameEl) {
            modelTransitionNameEl.textContent = config && config.label ? config.label : '角色切换';
        }
        if (modelTransitionTextEl) {
            modelTransitionTextEl.textContent = text || '';
        }
        modelTransitionEl.classList.add('visible');
    }

    function hideModelTransition() {
        if (modelTransitionEl) {
            modelTransitionEl.classList.remove('visible');
        }
    }

    function playRoleEntry(config) {
        if (!config) return;
        var expression = config.enterExpression || 'Smile';
        if (resolveExpression(expression)) {
            setExpression(expression);
        } else {
            setExpression('Normal');
        }
        var motion = config.enterMotion || ['Idle', 0];
        playMotion(motion[0], motion[1] || 0);
    }

    async function requestSwitchModel(key) {
        if (!MODEL_REGISTRY[key]) return;
        var now = performance.now();
        if (now - lastModelSwitchRequestAt < MODEL_SWITCH_MIN_INTERVAL_MS) {
            queuedModelKey = key;
            return;
        }
        lastModelSwitchRequestAt = now;
        if (isSwitchingModel) {
            queuedModelKey = key;
            return;
        }

        isSwitchingModel = true;
        try {
            await switchModel(key);
            while (queuedModelKey && queuedModelKey !== currentModelKey) {
                var nextKey = queuedModelKey;
                queuedModelKey = null;
                await switchModel(nextKey);
            }
        } finally {
            isSwitchingModel = false;
            queuedModelKey = null;
        }
    }

    async function switchModel(key, options) {
        if (!MODEL_REGISTRY[key]) return;
        options = options || {};

        if (model && key === currentModelKey && options.force !== true) {
            return;
        }

        var switchGeneration = ++modelSwitchGeneration;
        var switchStartedAt = performance.now();

        stopIdleCycle();
        clearIdleTimer();
        cancelModelHandoff('new model switch');
        stopCurrentAudio();
        ttsMutedUntil = performance.now() + 3000;
        lockLocalDialogAudio(DIALOG_AUDIO_LOCK_MAX_MS, 'model_switch');

        var previousModel = model;
        var previousKey = currentModelKey;
        var previousConfig = currentModelConfig;
        var nextConfig = MODEL_REGISTRY[key];
        var handoffText = getModelHandoffText(nextConfig);
        currentModelKey = key;
        currentModelConfig = nextConfig;
        if (window.BackgroundManager) {
            window.BackgroundManager.applyThemeForModel(key);
        }
        setModelSwitcherBusy(true);
        showModelTransition(nextConfig, handoffText);
        loadingEl.innerHTML = '<div class="spinner"></div><div>正在准备 ' + nextConfig.label + '...</div>';
        loadingEl.classList.toggle('compact', Boolean(previousModel));
        loadingEl.style.display = 'block';
        loadingEl.style.opacity = '1';

        try {
            var loaded = previousModel
                ? { key: key, model: await loadLive2DModelWithRetry(currentModelConfig) }
                : await loadStartupModel(key);
            var nextModel = loaded.model;
            currentModelKey = loaded.key;
            currentModelConfig = MODEL_REGISTRY[currentModelKey];
            model = nextModel;
            applyModelFit(nextModel, currentModelConfig);
            bindMouthOpen(nextModel);
            nextModel.visible = true;
            nextModel.alpha = previousModel ? 0 : 1;
            app.stage.addChild(nextModel);
            if (previousModel) {
                await crossfadeModels(previousModel, nextModel, MODEL_SWITCH_FADE_MS);
                app.stage.removeChild(previousModel);
                previousModel.visible = false;
                previousModel.alpha = 1;
            }

            persistAvatarModelKey(currentModelKey);

            playRoleEntry(currentModelConfig);
            enterIdle();
            buildDebugPanel();
            buildModelSwitcher();
            notifyAvatarReady();

            loadingEl.style.opacity = '0';
            setTimeout(function () {
                loadingEl.style.display = 'none';
                loadingEl.classList.remove('compact');
            }, 180);
            hideModelTransition();
            releaseLocalDialogAudio('model_switch');
            setModelSwitcherBusy(false);
            console.info(
                'Model switch visual ready:',
                currentModelKey,
                Math.round(performance.now() - switchStartedAt) + 'ms'
            );
            startModelPreload();

            if (previousModel) {
                runModelHandoff(currentModelConfig, handoffText, switchGeneration, currentModelKey);
            }
        } catch (err) {
            console.error('Model switch failed:', err);
            currentModelKey = previousKey;
            currentModelConfig = previousConfig;
            model = previousModel;
            if (previousModel) {
                previousModel.alpha = 1;
            }
            loadingEl.classList.remove('compact');
            hideModelTransition();
            loadingEl.innerHTML = '<div>模型加载失败</div><div style="font-size:14px;margin-top:8px;color:#ff6b6b">' + err.message + '</div>';
        } finally {
            if (switchGeneration === modelSwitchGeneration) {
                releaseLocalDialogAudio('model_switch');
                setModelSwitcherBusy(false);
            }
        }
    }

    function cancelModelHandoff(reason) {
        if (modelHandoffAbortController) {
            console.info('Cancel model handoff:', reason || 'unknown', modelHandoffOwner);
            modelHandoffAbortController.abort();
            modelHandoffAbortController = null;
        }
        if (modelHandoffOwner) {
            forceReleaseLocalDialogAudio(modelHandoffOwner);
            modelHandoffOwner = '';
        }
    }

    function runModelHandoff(config, handoffText, switchGeneration, modelKey) {
        setTimeout(function () {
            if (switchGeneration !== modelSwitchGeneration || config !== currentModelConfig) {
                return;
            }
            cancelModelHandoff('replace handoff');
            var owner = 'model_switch_' + switchGeneration;
            var controller = window.AbortController ? new AbortController() : null;
            modelHandoffOwner = owner;
            modelHandoffAbortController = controller;
            showSubtitle(handoffText);
            playRawTTS(handoffText, {
                modelKey: modelKey,
                owner: owner,
                priority: SPEECH_PRIORITY_MODEL_SWITCH,
                forceSpeech: true,
                statusText: handoffText,
                keepSubtitle: true,
                lockMs: MODEL_HANDOFF_LOCK_MS,
                signal: controller && controller.signal
            })
                .then(function () {
                    return sleep(MODEL_TRANSITION_HOLD_MS);
                })
                .catch(function (err) {
                    if (!err || err.name !== 'AbortError') {
                        console.warn('Model handoff TTS failed:', err);
                    }
                })
                .finally(function () {
                    if (modelHandoffOwner === owner) {
                        modelHandoffOwner = '';
                        modelHandoffAbortController = null;
                    }
                });
        }, 0);
    }

    function connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = protocol + '//' + location.host;
        ws = new WebSocket(wsUrl);

        ws.onopen = function () {
            console.log('WebSocket connected');
            registerWebSocketClient('avatar');
        };

        ws.onmessage = function (event) {
            try {
                const msg = JSON.parse(event.data);
                if (msg.target === 'avatar' && msg.type) {
                    handleControlCommand(msg);
                    return;
                }
                if (msg.type === 'interaction_mode_changed') {
                    applyInteractionMode(msg.mode, msg.modes || interactionModes);
                    refreshDialogSettings();
                    return;
                }
                handleEvent(msg);
            } catch (e) {
                console.error('WS message error:', e);
            }
        };

        ws.onclose = function () {
            setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = function (err) {
            console.error('WebSocket error:', err);
        };
    }

    function registerWebSocketClient(role) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({
            target: 'server',
            type: 'REGISTER',
            role: role,
            clientId: avatarRuntimeClientId,
            path: location.pathname,
            ts: Date.now()
        }));
    }

    function handleEvent(msg) {
        enqueueAvatarEvent(msg);
    }

    function enqueueAvatarEvent(msg) {
        var scheduled = normalizeAvatarEvent(msg);
        if (!scheduled) {
            runAvatarEventNow(msg);
            return;
        }
        if (scheduled.drop) {
            clientLog('drop stale avatar event during voice mode', {
                type: scheduled.type,
                eventType: scheduled.eventType,
                priority: scheduled.priority
            });
            return;
        }
        if (scheduled.immediate || canRunScheduledAvatarEvent(scheduled)) {
            runAvatarEventNow(msg);
            return;
        }
        var now = performance.now();
        var lastAt = lastScheduledEventAtByKey[scheduled.key] || 0;
        if (now - lastAt < AVATAR_EVENT_DEDUP_MS) {
            clientLog('dedupe queued avatar event', {
                key: scheduled.key,
                priority: scheduled.priority
            });
            return;
        }
        lastScheduledEventAtByKey[scheduled.key] = now;
        var replaced = false;
        if (scheduled.eventType !== 'repeat') {
            avatarEventQueue = avatarEventQueue.filter(function (event) {
                if (event.key !== scheduled.key) {
                    return true;
                }
                replaced = true;
                return false;
            });
        }
        avatarEventQueue.push(scheduled);
        sortAvatarEventQueue();
        clientLog(replaced ? 'replace queued avatar event' : 'queue avatar event', {
            key: scheduled.key,
            priority: scheduled.priority,
            queueSize: avatarEventQueue.length
        });
        scheduleAvatarEventPump(isExpeditedFixedSpeechEvent(scheduled) ? 50 : 250);
    }

    function sortAvatarEventQueue() {
        avatarEventQueue.sort(function (a, b) {
            if (b.priority !== a.priority) {
                return b.priority - a.priority;
            }
            if (shouldPrioritizeSpeechBeforeAction(a, b)) {
                return -1;
            }
            if (shouldPrioritizeSpeechBeforeAction(b, a)) {
                return 1;
            }
            return a.createdAt - b.createdAt;
        });
    }

    function shouldPrioritizeSpeechBeforeAction(candidate, other) {
        return Boolean(
            candidate
            && other
            && candidate.type === 'speech'
            && other.type !== 'speech'
            && candidate.eventType === other.eventType
            && isExpeditedFixedSpeechEvent(candidate)
        );
    }

    function isExpeditedFixedSpeechEvent(event) {
        return Boolean(
            event
            && event.type === 'speech'
            && event.priority >= SPEECH_PRIORITY_FIXED_DEFAULT
            && isProtectedFixedSpeechEvent(event.eventType)
        );
    }

    function nextAvatarEventPumpDelay() {
        return avatarEventQueue.some(isExpeditedFixedSpeechEvent) ? 50 : 500;
    }

    function normalizeAvatarEvent(msg) {
        if (!msg || !msg.type) {
            return null;
        }
        if (!voiceStreamUrl) {
            return null;
        }
        if (msg.type === 'speech_end') {
            return { message: msg, immediate: true, priority: 100, createdAt: performance.now() };
        }
        if (msg.type === 'speech' && msg.listening) {
            return { message: msg, immediate: true, priority: 100, createdAt: performance.now() };
        }
        var eventType = msg.type === 'speech'
            ? String(msg.event_type || '')
            : String(msg.type || '');
        var priority = getAvatarEventPriority(eventType, msg);
        if (priority <= 0) {
            return null;
        }
        var isRealtimeSpeech = msg.type === 'speech'
            && (msg.event_type === 'realtime_dialog' || msg.external_audio);
        if (isRealtimeSpeech) {
            return { message: msg, immediate: true, priority: 100, createdAt: performance.now() };
        }
        var interruptibleListening = canFixedSpeechInterruptIdleListening(eventType, priority);
        var lowPriorityNoise = isLowPriorityFixedEvent(eventType, priority)
            && isVoiceInteractionBusyForFixedSpeech()
            && !interruptibleListening;
        var staleFixedEvent = voiceTurnPolicy.shouldDropFixedEvent({
            eventType: eventType,
            voiceInteractionBusy: isVoiceInteractionBusyForFixedSpeech(),
            voiceStreamOpen: Boolean(voiceStreamWs),
            interruptibleListening: interruptibleListening
        });
        var keyPrefix = msg.type === 'speech' ? 'speech' : 'event';
        return {
            message: msg,
            type: msg.type,
            eventType: eventType,
            priority: priority,
            drop: lowPriorityNoise || staleFixedEvent,
            key: keyPrefix + ':' + eventType + ':' + String(msg.name || msg.visitor_label || msg.text || '').slice(0, 80),
            createdAt: performance.now()
        };
    }

    function getAvatarEventPriority(eventType, msg) {
        if (eventType === 'realtime_dialog' || (msg && msg.external_audio)) return SPEECH_PRIORITY_REALTIME_DIALOG;
        if (eventType === 'check_in') return 85;
        if (eventType === 'check_out') return 85;
        if (eventType === 'arrival_task') return 88;
        if (eventType === 'first_time') return 82;
        if (eventType === 'returning') return 82;
        if (eventType === 'repeat') return SPEECH_PRIORITY_FIXED_DEFAULT;
        if (eventType.indexOf('gesture_') === 0) return 60;
        if (eventType === 'stranger' || eventType === 'returning_stranger') return 30;
        if (eventType === 'stranger_stare' || eventType === 'checked_in_stare') return 15;
        if (eventType === 'idle_long' || eventType === 'crowd') return 10;
        return 0;
    }

    function isLowPriorityFixedEvent(eventType, priority) {
        if (priority > 30) {
            return false;
        }
        return [
            'stranger',
            'returning_stranger',
            'stranger_stare',
            'checked_in_stare',
            'idle_long',
            'crowd'
        ].indexOf(eventType) >= 0;
    }

    function canRunScheduledAvatarEvent(event) {
        if (!event) return false;
        if (event.priority >= SPEECH_PRIORITY_REALTIME_DIALOG) return true;
        var allowDuringSelfMute = event.priority >= SPEECH_PRIORITY_FIXED_DEFAULT
            || isProtectedFixedSpeechEvent(event.eventType);
        var interruptsIdleListening = canFixedSpeechInterruptIdleListening(event.eventType, event.priority);
        var speechSlotAvailable = interruptsIdleListening
            || activeSpeechPriority <= 0
            || activeSpeechPriority < event.priority;
        var audioLockAvailable = interruptsIdleListening
            || !isLocalDialogAudioLocked()
            || activeSpeechPriority < event.priority;
        return voiceTurnPolicy.canRunFixedSpeechEvent({
            priority: event.priority,
            realtimePriority: SPEECH_PRIORITY_REALTIME_DIALOG,
            isListening: isListening,
            isDialogBusy: isDialogBusy,
            streamingAudioPlaying: streamingAudioPlaying,
            streamingAudioQueueLength: streamingAudioQueue.length,
            voiceStreamOpen: Boolean(voiceStreamWs),
            voiceStreamKeepOpen: Boolean(voiceStreamKeepOpen),
            hasAudio: Boolean(audio),
            speechSlotAvailable: speechSlotAvailable,
            allowDuringSelfMute: allowDuringSelfMute,
            selfSpeechMuted: performance.now() < selfSpeechMutedUntil,
            audioLockAvailable: audioLockAvailable,
            interruptsIdleListening: interruptsIdleListening,
            userSpeechDetected: voiceUserSpeechDetectedThisTurn,
            voiceStopRequested: voiceStopRequested,
            currentUserText: currentUserText
        });
    }

    function isProtectedFixedSpeechEvent(eventType) {
        return voiceTurnPolicy.isProtectedFixedSpeechEvent(eventType);
    }

    function hasUserSpeechEvidenceInCurrentTurn() {
        return Boolean(
            voiceUserSpeechDetectedThisTurn
            || voiceStopRequested
            || String(currentUserText || '').trim()
        );
    }

    function isInterruptibleIdleListeningTurn() {
        return Boolean(
            activeSpeechOwner === 'local_dialog'
            && isListening
            && isDialogBusy
            && !hasUserSpeechEvidenceInCurrentTurn()
            && !streamingAudioPlaying
            && streamingAudioQueue.length === 0
            && !audio
            && !String(currentUserText || '').trim()
            && !String(currentAnswerText || '').trim()
        );
    }

    function canFixedSpeechInterruptIdleListening(eventType, priority) {
        return Boolean(
            isProtectedFixedSpeechEvent(eventType)
            && Number(priority || 0) > 0
            && isInterruptibleIdleListeningTurn()
        );
    }

    function interruptIdleListeningForFixedSpeech(eventType, priority) {
        if (!canFixedSpeechInterruptIdleListening(eventType, priority)) {
            logFixedSpeechPreservesActiveVoice(eventType, priority);
            return false;
        }
        clientLog('fixed speech interrupts idle listening turn', {
            eventType: eventType,
            priority: priority,
            activeSpeechPriority: activeSpeechPriority,
            voiceStreamOpen: Boolean(voiceStreamWs),
            sentBytes: voiceSentBytesThisTurn
        });
        cancelCurrentVoiceTurn();
        return true;
    }

    function logFixedSpeechPreservesActiveVoice(eventType, priority) {
        if (
            !isProtectedFixedSpeechEvent(eventType)
            || !isListening
            || !isDialogBusy
            || !hasUserSpeechEvidenceInCurrentTurn()
        ) {
            return;
        }
        var now = performance.now();
        if (now - lastFixedSpeechPreserveVoiceLogAt < 3000) {
            return;
        }
        lastFixedSpeechPreserveVoiceLogAt = now;
        clientLog('fixed speech preserves active voice turn', {
            eventType: eventType,
            priority: priority,
            activeSpeechPriority: activeSpeechPriority,
            voiceStreamOpen: Boolean(voiceStreamWs),
            userSpeechDetected: voiceUserSpeechDetectedThisTurn,
            voiceStopRequested: voiceStopRequested,
            sentBytes: voiceSentBytesThisTurn,
            pendingFrames: voicePendingInputFrames.length,
            currentUserChars: String(currentUserText || '').length
        });
    }

    function isVoiceInteractionBusy() {
        return (
            isListening
            || isDialogBusy
            || streamingAudioPlaying
            || streamingAudioQueue.length > 0
            || Boolean(voiceStreamWs && !voiceStreamKeepOpen)
            || isAssistantResponseActive()
            || performance.now() < selfSpeechMutedUntil
        );
    }

    function isVoiceInteractionBusyForFixedSpeech() {
        return (
            isVoiceInteractionBusy()
            || isLocalDialogAudioLocked()
            || Boolean(audio)
        );
    }

    function scheduleAvatarEventPump(delayMs) {
        if (avatarEventPumpTimer) {
            return;
        }
        avatarEventPumpTimer = setTimeout(function () {
            avatarEventPumpTimer = null;
            pumpAvatarEventQueue();
        }, Math.max(50, delayMs || 250));
    }

    function pumpAvatarEventQueue() {
        if (avatarEventQueue.length === 0) {
            return;
        }
        avatarEventQueue = avatarEventQueue.filter(function (event) {
            var expired = performance.now() - event.createdAt >= 15000;
            if (expired) {
                return false;
            }
            if (
                isLowPriorityFixedEvent(event.eventType, event.priority)
                && isVoiceInteractionBusyForFixedSpeech()
                && !canFixedSpeechInterruptIdleListening(event.eventType, event.priority)
            ) {
                clientLog('drop queued low priority avatar event during voice mode', {
                    key: event.key,
                    eventType: event.eventType,
                    priority: event.priority
                });
                return false;
            }
            return true;
        });
        if (avatarEventQueue.length === 0) {
            return;
        }
        var next = avatarEventQueue[0];
        if (!canRunScheduledAvatarEvent(next)) {
            logAvatarEventBlocked(next);
            scheduleAvatarEventPump(300);
            return;
        }
        avatarEventQueue.shift();
        clientLog('run queued avatar event', {
            key: next.key,
            priority: next.priority,
            queueSize: avatarEventQueue.length
        });
        runAvatarEventNow(next.message);
        if (avatarEventQueue.length > 0) {
            scheduleAvatarEventPump(nextAvatarEventPumpDelay());
        }
    }

    function logAvatarEventBlocked(event) {
        var now = performance.now();
        if (now - lastAvatarEventBlockedLogAt < 3000) {
            return;
        }
        lastAvatarEventBlockedLogAt = now;
        clientLog('wait queued avatar event', {
            key: event && event.key,
            priority: event && event.priority,
            isListening: isListening,
            isDialogBusy: isDialogBusy,
            streamingAudioPlaying: streamingAudioPlaying,
            streamingAudioQueue: streamingAudioQueue.length,
            voiceStreamOpen: Boolean(voiceStreamWs),
            voiceStreamKeepOpen: Boolean(voiceStreamKeepOpen),
            hasAudio: Boolean(audio),
            activeSpeechOwner: activeSpeechOwner,
            activeSpeechPriority: activeSpeechPriority,
            selfMutedMs: Math.max(0, Math.round(selfSpeechMutedUntil - performance.now())),
            audioLockedMs: Math.max(0, Math.round(getDialogAudioLockedUntil() - performance.now()))
        });
    }

    function runAvatarEventNow(msg) {
        if (msg.type === 'speech') {
            if (msg.listening) {
                var listeningText = msg.text || '我在听呢';
                updateVoiceChatText(listeningText);
                if (msg.text) {
                    showStatus(listeningText, 'speech');
                } else {
                    clearStatusBeforeDeferredSpeech();
                }
                hideSubtitle();
                return;
            }
            var speechOwner = getIncomingSpeechOwner(msg);
            var speechPriority = getIncomingSpeechPriority(msg);
            if (msg.text && !msg.external_audio && speechOwner !== 'doubao_realtime') {
                interruptIdleListeningForFixedSpeech(msg.event_type, speechPriority);
                clearIdleTimer();
                if (msg.visual_fallback !== false) {
                    maybeRunSpeechVisualFallback(msg);
                }
                playRawTTS(msg.text, {
                    owner: speechOwner,
                    priority: speechPriority,
                    forceSpeech: true,
                    eventType: msg.event_type,
                    statusText: msg.text
                }).catch(function (err) {
                    console.error('Incoming speech TTS failed:', err);
                    clearSpeechUi();
                    updateVoiceChatText('播报失败：' + (err && err.message ? err.message : err), 4000);
                });
                return;
            }
            if (!requestSpeechTurn(speechOwner, speechPriority, {
                force: true,
                lock: false
            })) {
                return;
            }
            muteVoiceDetectionForSelfSpeech(60000);
            clearIdleTimer();
            if (msg.text) {
                showStatus(msg.text, 'speech');
                hideSubtitle();
            }
            if (msg.external_audio || msg.text) {
                stopLipSync();
                setVoicePhase('speaking', 'Speaking response', 0.72);
                startExternalLipSync();
                if (speechOwner === 'doubao_realtime') {
                    scheduleExternalSpeechWatchdog(msg.text || '');
                }
            }
            if (msg.visual_fallback !== false) {
                maybeRunSpeechVisualFallback(msg);
            }
            return;
        }

        if (msg.type === 'speech_end') {
            if (msg.listening) {
                updateVoiceChatText('');
                scheduleIdle(800);
                return;
            }
            var endOwner = getIncomingSpeechOwner(msg);
            if (isAudioLockedForOtherOwner(endOwner)) {
                return;
            }
            if (activeSpeechPriority > getIncomingSpeechPriority(msg)) {
                return;
            }
            if (endOwner === 'doubao_realtime') {
                clearExternalSpeechWatchdog();
            }
            forceReleaseLocalDialogAudio(endOwner);
            releaseSpeechPriority(endOwner);
            clearSpeechUi();
            updateVoiceChatText('');
            releaseSelfSpeechMuteSoon();
            scheduleIdle(800);
            return;
        }

        interruptIdleListeningForFixedSpeech(msg.type, getAvatarEventPriority(msg.type, msg));
        if (activeSpeechPriority > 10 || isLocalDialogAudioLocked()) {
            return;
        }

        clearIdleTimer();
        switch (msg.type) {
            case 'check_in':
                if (msg.is_first === true || msg.is_first === 'true' || msg.event_type === 'first_time') {
                    runBehavior('first_time', { name: msg.name || '访客', silent: true });
                } else if (msg.is_returning === true || msg.is_returning === 'true' || msg.event_type === 'returning') {
                    runBehavior('returning', { name: msg.name || '访客', silent: true });
                } else {
                    runBehavior('check_in', { name: msg.name || '访客', silent: true });
                }
                break;
            case 'first_time':
                runBehavior('first_time', { name: msg.name || '访客', silent: true });
                break;
            case 'returning':
                runBehavior('returning', { name: msg.name || '访客', silent: true });
                break;
            case 'check_out':
                runBehavior('check_out', { name: msg.name || '访客', silent: true });
                break;
            case 'stranger':
                runBehavior('stranger', { name: '', silent: true });
                break;
            case 'stranger_stare':
                runBehavior('stranger_stare', { name: '', silent: true });
                break;
            case 'repeat':
                runBehavior('repeat', { name: msg.name || '访客', silent: true });
                break;
            case 'checked_in_stare':
                runBehavior('checked_in_stare', { name: msg.name || '访客', silent: true });
                break;
            case 'attention':
                if (idleState === 'idle') {
                    runBehavior('attention', { silent: true });
                }
                break;
            case 'idle_long':
                runBehavior('idle_long', { name: '', silent: true });
                break;
            case 'crowd':
                runBehavior('crowd', { name: '', silent: true });
                break;
            case 'gesture_wave':
            case 'gesture_thumbs_up':
            case 'gesture_heart':
            case 'gesture_ok':
            case 'gesture_peace':
            case 'gesture_middle_finger':
                if (idleState === 'idle') {
                    runBehavior(msg.type, { name: '', silent: true });
                }
                break;
        }
    }

    function getIncomingSpeechOwner(msg) {
        if (msg.event_type === 'realtime_dialog' || msg.external_audio) {
            return 'doubao_realtime';
        }
        return 'legacy_tts';
    }

    function getIncomingSpeechPriority(msg) {
        if (msg.event_type === 'realtime_dialog' || msg.external_audio) {
            return SPEECH_PRIORITY_REALTIME_DIALOG;
        }
        var explicitPriority = Number(msg.priority);
        if (Number.isFinite(explicitPriority)) {
            return explicitPriority;
        }
        return SPEECH_PRIORITY_FIXED_DEFAULT;
    }

    function getLocalDialogPriority() {
        return dialogPriorityMode === 0
            ? SPEECH_PRIORITY_LOCAL_DIALOG_HIGH
            : SPEECH_PRIORITY_LOCAL_DIALOG_NORMAL;
    }

    function clearIdleTimer() {
        if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
    }

    function scheduleIdle(delay) {
        clearIdleTimer();
        idleTimer = setTimeout(enterIdle, delay || 3000);
    }

    function enterIdle() {
        if (
            isListening
            || isDialogBusy
            || streamingAudioPlaying
            || streamingAudioQueue.length > 0
            || audio
            || (activeSpeechPriority > 0 && activeSpeechOwner !== 'local_dialog')
        ) {
            clientLog('skip idle while speech active', {
                isListening: isListening,
                isDialogBusy: isDialogBusy,
                streamingAudioPlaying: streamingAudioPlaying,
                streamingAudioQueueLength: streamingAudioQueue.length,
                hasAudio: Boolean(audio),
                activeSpeechOwner: activeSpeechOwner,
                activeSpeechPriority: activeSpeechPriority
            });
            return;
        }
        idleState = 'idle';
        statusMode = 'idle';
        setExpression('Normal');
        playMotion('Idle', 0);
        clearStatusBeforeDeferredSpeech();
        clearVoiceChatText();
        setAssistantSpeechText('');
        startIdleCycle();
    }

    function startIdleCycle() {
        stopIdleCycle();
        scheduleMicroExpression();
        scheduleFidget();
    }

    function stopIdleCycle() {
        if (microTimer) {
            clearTimeout(microTimer);
            microTimer = null;
        }
        if (fidgetTimer) {
            clearTimeout(fidgetTimer);
            fidgetTimer = null;
        }
    }

    function scheduleMicroExpression() {
        if (idleState !== 'idle') return;

        var delay = 8000 + Math.random() * 7000;
        microTimer = setTimeout(function () {
            if (idleState !== 'idle') return;

            var exps = ['Normal', 'f01', 'f02'];
            var exp = exps[Math.floor(Math.random() * exps.length)];
            setExpression(exp + '.exp3.json');
            setTimeout(function () {
                if (idleState === 'idle') setExpression('Normal.exp3.json');
            }, 2000);
            scheduleMicroExpression();
        }, delay);
    }

    function scheduleFidget() {
        if (idleState !== 'idle') return;

        var delay = 30000 + Math.random() * 30000;
        fidgetTimer = setTimeout(function () {
            if (idleState !== 'idle') return;

            var motions = [
                function () { playMotion('Flick', Math.floor(Math.random() * 2)); },
                function () { playMotion('FlickUp', 0); },
                function () { playMotion('FlickDown', 0); }
            ];
            motions[Math.floor(Math.random() * motions.length)]();
            scheduleFidget();
        }, delay);
    }

    async function init() {
        try {
            const rect = canvas.getBoundingClientRect();
            const isDisplayMode = new URLSearchParams(location.search).has('display');

            if (isDisplayMode) {
                document.body.classList.add('display-mode');
            }

            app = new PIXI.Application({
                view: canvas,
                width: rect.width,
                height: rect.height,
                backgroundColor: 0x000000,
                backgroundAlpha: 0,
                antialias: true,
                resolution: window.devicePixelRatio || 1,
                autoDensity: true
            });
            window.addEventListener('resize', resize);
            document.addEventListener('fullscreenchange', function () {
                requestAnimationFrame(resize);
            });
            if (window.visualViewport) {
                window.visualViewport.addEventListener('resize', resize);
            }

            fetch('/tts-manifest')
                .then(function (res) { return res.ok ? res.json() : {}; })
                .then(function (manifest) { ttsManifest = manifest || {}; })
                .catch(function () { ttsManifest = {}; });

            fetch('/tts-voices')
                .then(function (res) { return res.ok ? res.json() : {}; })
                .then(function (data) {
                    ttsVoiceByModel = (data && data.byModel) || {};
                    Object.keys(MODEL_REGISTRY).forEach(function (key) {
                        if (ttsVoiceByModel[key]) {
                            MODEL_REGISTRY[key].voice = ttsVoiceByModel[key];
                        }
                    });
                })
                .catch(function () { ttsVoiceByModel = {}; });

            dialogSettingsPromise = fetchJsonWithError('/dialog-settings', { cache: 'no-store' })
                .then(function (data) {
                    applyDialogSettingsData(data);
                })
                .catch(function (err) {
                    dialogPriorityMode = 0;
                    realtimeDialogEnabled = false;
                    handleDialogSettingsError(err);
                });

            currentModelKey = getInitialModelKey();
            currentModelConfig = MODEL_REGISTRY[currentModelKey];
            buildModelSwitcher();
            if (dialogSettingsPromise) {
                await dialogSettingsPromise;
            }
            await loadInteractionMode();
            window.setInterval(function () {
                fetchJsonWithError('/dialog-settings', { cache: 'no-store' })
                    .then(function (data) {
                        applyDialogSettingsData(data);
                        clientLog('avatar device session refreshed', {
                            tenantId: data.tenantId || '',
                            deviceId: data.deviceId || ''
                        });
                    })
                    .catch(function (err) {
                        clientLog('avatar device session refresh error', { error: err.message || String(err) });
                        handleDialogSettingsError(err);
                    });
            }, 6 * 60 * 60 * 1000);
            buildInteractionModeSwitcher();
            await switchModel(currentModelKey, { force: true });

            canvas.addEventListener('click', function (e) {
                unlockAudio();
                const rect = canvas.getBoundingClientRect();
                const y = (e.clientY - rect.top) / rect.height;
                if (y < 0.5) {
                    playMotion('Tap', Math.floor(Math.random() * 4));
                } else {
                    playMotion('Flick', Math.floor(Math.random() * 2));
                }
            });
            document.addEventListener('pointerdown', unlockAudio, { once: true });
            setupFaceNameDialog();
            setupVoiceChat();

            if (avatarSessionValid) {
                connectWebSocket();
            } else {
                clientLog('skip avatar websocket without valid device session');
            }
        } catch (err) {
            console.error('Init failed:', err);
            loadingEl.innerHTML = '<div>加载失败</div><div style="font-size:14px;margin-top:8px;color:#ff6b6b">' + err.message + '</div>';
        }
    }

    window.doAction = doAction;
    window.setExpression = setExpression;
    window.playMotion = playMotion;
    window.switchModel = requestSwitchModel;
    window.__avatarDebug = {
        setMouthOpen: setMouthOpen,
        startExternalLipSync: startExternalLipSync,
        stopLipSync: stopLipSync,
        getMouthOpen: function () { return mouthOpenValue; }
    };

    /* ============================================
       控制面板通信层
       通过 WebSocket 服务端中继
       ============================================ */
    function broadcastStateToControl(extra) {
        var state = {
            modelKey: currentModelKey,
            frontdeskSurface: getCurrentFrontdeskSurface(),
            interactionMode: interactionMode,
            interactionModes: interactionModes,
            isSwitchingModel: isSwitchingModel,
            isListening: isListening,
            voicePhase: voicePhase,
            voicePhaseText: voicePhaseText,
            voiceActivityLevel: voiceActivityLevel,
            voiceMuted: !autoVoiceChatEnabled,
            avatarSessionValid: avatarSessionValid,
            voiceTenantId: voiceTenantId,
            voiceDeviceId: voiceDeviceId,
            voiceChatText: voiceChatText ? voiceChatText.textContent : '',
            speechStatusText: speechStatusText,
            visitorSpeechText: visitorSpeechText,
            assistantSpeechText: assistantSpeechText,
            ts: Date.now()
        };
        if (currentModelConfig) {
            state.expressionButtons = currentModelConfig.expressionButtons || [];
            state.motionCounts = currentModelConfig.motionCounts || {};
        }
        if (extra) {
            Object.keys(extra).forEach(function (k) { state[k] = extra[k]; });
        }
        var msg = { target: 'control', type: 'STATE_SYNC', payload: state, ts: Date.now() };
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                source: 'avatar-runtime',
                type: 'STATE_SYNC',
                payload: state,
                ts: Date.now()
            }, window.location.origin);
        }
    }

    function handleControlCommand(data) {
        switch (data.type) {
            case 'SWITCH_MODEL':
                if (data.payload && data.payload.key) {
                    requestSwitchModel(data.payload.key);
                }
                break;
            case 'SET_INTERACTION_MODE':
                if (data.payload && data.payload.mode) {
                    requestInteractionMode(data.payload.mode);
                }
                break;
            case 'DO_ACTION':
                if (data.payload && data.payload.action) {
                    doAction(data.payload.action);
                }
                break;
            case 'SET_EXPRESSION':
                if (data.payload && data.payload.name) {
                    setExpression(data.payload.name);
                }
                break;
            case 'PLAY_MOTION':
                if (data.payload) {
                    playMotion(data.payload.group, data.payload.index);
                }
                break;
            case 'VOICE_CHAT_TOGGLE':
                if (voiceChatButton) {
                    voiceChatButton.click();
                }
                break;
            case 'VOICE_MUTE_SET':
                setVoiceRuntimeMuted(data.payload && data.payload.muted);
                break;
            case 'VOICE_END_CALL':
                endCurrentVoiceRuntimeTurn();
                break;
            case 'REQUEST_STATE':
                broadcastStateToControl();
                break;
            case 'PING':
                broadcastStateToControl();
                break;
        }
    }

    function getCurrentFrontdeskSurface() {
        return 'avatar';
    }

    function buildVoiceStreamMetadata() {
        return {
            device_id: voiceDeviceId,
            tenant_id: voiceTenantId,
            site_id: voiceSiteId,
            frontdesk_surface: getCurrentFrontdeskSurface(),
            model_key: currentModelKey || DEFAULT_MODEL_KEY
        };
    }

    function setVoiceRuntimeMuted(muted) {
        var nextMuted = Boolean(muted);
        autoVoiceChatEnabled = !nextMuted;
        if (nextMuted) {
            if (isListening || isDialogBusy || streamingAudioPlaying || audio) {
                cancelCurrentVoiceTurn();
                stopCurrentAudio();
            }
            updateVoiceChatText('麦克风已静音');
            setVoicePhase('ready', 'Ready for next visitor', 0.12);
        } else {
            setupVoiceChat();
            updateVoiceChatText(voiceMonitorReady ? '我在听，你直接说话' : '正在请求麦克风权限');
            setVoicePhase('ready', 'Ready for next visitor', 0.18);
        }
        broadcastStateToControl({ voiceMuted: nextMuted });
    }

    function isFrontdeskDisplayMode() {
        var params = new URLSearchParams(location.search || '');
        return params.has('display');
    }

    function endCurrentVoiceRuntimeTurn() {
        var hasActiveRuntimeTurn = isListening || isDialogBusy || streamingAudioPlaying || audio || voiceStreamWs;
        if (hasActiveRuntimeTurn) {
            if (isListening && voiceStreamWs && voiceStreamWs.readyState === WebSocket.OPEN) {
                finishVoiceTurn('已结束当前通话');
            } else {
                cancelCurrentVoiceTurn();
            }
            stopCurrentAudio();
        }
        updateVoiceChatText('已结束当前通话');
        setVoicePhase('ready', 'Ready for next visitor', 0.18);
        broadcastStateToControl({ voiceMuted: !autoVoiceChatEnabled });
    }

    var _origSetModelSwitcherBusy = setModelSwitcherBusy;
    setModelSwitcherBusy = function (busy) {
        _origSetModelSwitcherBusy(busy);
        broadcastStateToControl({ isSwitchingModel: busy });
    };

    var _origApplyInteractionMode = applyInteractionMode;
    applyInteractionMode = function (modeKey, modes) {
        _origApplyInteractionMode(modeKey, modes);
        broadcastStateToControl();
    };

    var _origUpdateVoiceChatText = updateVoiceChatText;
    updateVoiceChatText = function (text, duration) {
        _origUpdateVoiceChatText(text, duration);
        broadcastStateToControl({ voiceChatText: text });
    };

    init();
})();
