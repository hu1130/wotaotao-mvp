(function (root, factory) {
    const policy = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = policy;
    }
    root.VoiceTurnPolicy = policy;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function isStreamingDialogIdle(state) {
        return Boolean(
            state
            && state.streamingAudioDone === true
            && !state.isListening
            && !state.streamingAudioPlaying
            && Number(state.streamingAudioQueueLength || 0) === 0
            && (!state.voiceStreamOpen || state.voiceStreamKeepOpen)
        );
    }

    function canStartVoiceTurn(state) {
        return Boolean(
            state
            && state.streamingAudioDone === true
            && !state.isDialogBusy
            && !state.streamingAudioPlaying
        );
    }

    function canInterruptPendingResponse(state) {
        var basicAllowed = Boolean(
            state
            && state.isDialogBusy === true
            && state.isListening === false
            && state.voiceStopRequested === true
            && state.streamingAudioPlaying === false
            && Number(state.streamingAudioQueueLength || 0) === 0
            && state.hasAudio === false
        );
        if (!basicAllowed) {
            return false;
        }
        if (state.requiresStrongVoice !== true) {
            return true;
        }
        return canBargeIn({
            playing: true,
            rms: state.rms,
            peak: state.peak,
            threshold: state.threshold,
            frames: state.frames,
            minFrames: state.minFrames,
            avgRms: state.avgRms,
            durationMs: state.durationMs,
            minDurationMs: state.minDurationMs,
            minAverageRatio: state.minAverageRatio,
            maxPeakToAverage: state.maxPeakToAverage
        });
    }

    function isRealtimeDialogResponseActive(state) {
        if (!state) {
            return false;
        }
        if (state.activeSpeechOwner && state.activeSpeechOwner !== 'local_dialog') {
            return false;
        }
        var hasRealtimeDialogAudio = Boolean(
            state.streamingAudioPlaying
            || Number(state.streamingAudioQueueLength || 0) > 0
            || state.hasAudio
            || (
                state.streamingAudioDone === false
                && state.streamingPlaybackStarted === true
            )
        );
        if (!hasRealtimeDialogAudio) {
            return false;
        }
        if (state.activeSpeechOwner === 'local_dialog' && state.hasAudio) {
            return true;
        }
        return Boolean(
            state.isDialogBusy === true
            && state.isListening === false
            && hasRealtimeDialogAudio
        );
    }

    function canBargeIn(state) {
        if (!state || (state.playing !== true && state.responseActive !== true)) {
            return false;
        }
        var threshold = Math.max(0, Number(state.threshold || 0));
        var rms = Math.max(0, Number(state.rms || 0));
        var peak = Math.max(0, Number(state.peak || 0));
        var frames = Math.max(0, Number(state.frames || 0));
        var minFrames = Math.max(2, Number(state.minFrames || 3));
        var avgRms = Math.max(0, Number(state.avgRms || rms));
        var durationMs = Math.max(0, Number(state.durationMs || 0));
        var minDurationMs = Math.max(0, Number(state.minDurationMs || 0));
        var minAverageRatio = Math.max(0, Number(state.minAverageRatio || 0));
        var maxPeakToAverage = Math.max(0, Number(state.maxPeakToAverage || 0));
        if (minDurationMs > 0 && durationMs < minDurationMs) {
            return false;
        }
        if (minAverageRatio > 0 && avgRms < threshold * minAverageRatio) {
            return false;
        }
        if (maxPeakToAverage > 0 && avgRms > 0 && peak / Math.max(avgRms, 0.000001) > maxPeakToAverage) {
            return false;
        }
        return frames >= minFrames
            && rms >= threshold
            && peak >= threshold * 1.03;
    }

    var PROTECTED_FIXED_SPEECH_EVENTS = Object.freeze([
        'check_in',
        'check_out',
        'arrival_task',
        'first_time',
        'returning',
        'repeat',
        'stranger',
        'returning_stranger'
    ]);

    function isProtectedFixedSpeechEvent(eventType) {
        return PROTECTED_FIXED_SPEECH_EVENTS.indexOf(String(eventType || '')) >= 0;
    }

    function canUserBargeInFixedSpeech(eventType) {
        var type = String(eventType || '').trim();
        return Boolean(type) && !isProtectedFixedSpeechEvent(type);
    }

    function canCaptureInterruptedSpeechForResume(state) {
        if (!state || state.activeSpeechOwner !== 'local_dialog') {
            return false;
        }
        return Boolean(
            state.streamingAudioPlaying
            || Number(state.streamingAudioQueueLength || 0) > 0
            || state.hasAudio
            || state.hasAssistantText
            || state.hasUserText
        );
    }

    function shouldDropFixedEvent(state) {
        if (!state || state.eventType !== 'repeat') {
            return false;
        }
        return false;
    }

    function canRunFixedSpeechEvent(state) {
        if (!state) {
            return false;
        }
        var priority = Number(state.priority || 0);
        var realtimePriority = Number(state.realtimePriority || 90);
        if (priority >= realtimePriority) {
            return true;
        }
        if (state.interruptsIdleListening) {
            return Boolean(
                state.userSpeechDetected !== true
                && state.voiceStopRequested !== true
                && !String(state.currentUserText || '').trim()
                && !state.streamingAudioPlaying
                && Number(state.streamingAudioQueueLength || 0) === 0
                && !state.hasAudio
                && state.speechSlotAvailable
                && state.audioLockAvailable
            );
        }
        return Boolean(
            !state.isListening
            && !state.isDialogBusy
            && !state.streamingAudioPlaying
            && Number(state.streamingAudioQueueLength || 0) === 0
            && (!state.voiceStreamOpen || state.voiceStreamKeepOpen)
            && !state.hasAudio
            && state.speechSlotAvailable
            && (state.allowDuringSelfMute || !state.selfSpeechMuted)
            && state.audioLockAvailable
        );
    }

    function shouldPreemptSpeechTurn(state) {
        if (!state || state.force === false) {
            return false;
        }
        var activeOwner = String(state.activeOwner || '');
        var incomingOwner = String(state.incomingOwner || '');
        var activePriority = Number(state.activePriority || 0);
        var incomingPriority = Number(state.incomingPriority || 0);
        return Boolean(
            activeOwner
            && activePriority > 0
            && incomingPriority > activePriority
            && (
                activeOwner !== incomingOwner
                || activeOwner === 'legacy_tts'
                || incomingOwner === 'legacy_tts'
            )
        );
    }

    function removeStaleDialogEvents(events) {
        return (events || []).filter(function (event) {
            return event && event.eventType !== 'repeat';
        });
    }

    function statusText(phase, text) {
        const value = String(text || '').trim();
        switch (phase) {
            case 'listening':
                return value || '我在听呢';
            case 'recognizing':
                return value || '正在识别';
            case 'processing':
                return value || '叮当正在努力思考中';
            case 'speaking':
                return value;
            default:
                return value || '待机中';
        }
    }

    function shouldProtectInterruptedListeningStatus(state) {
        if (!state || state.protected !== true) {
            return false;
        }
        var listeningText = statusText('listening', state.listeningText);
        var rawListeningText = String(state.listeningText || '').trim();
        var nextText = String(state.nextText || '').trim();
        return nextText !== listeningText && nextText !== rawListeningText;
    }

    function speechStatusSegments(text) {
        var value = String(text || '').replace(/\s+/g, ' ').trim();
        if (!value) return [];
        var sentenceMatches = value.match(/[^。！？!?；;]+[。！？!?；;]*/g) || [value];
        var segments = [];
        sentenceMatches.forEach(function (item) {
            splitLongSpeechSegment(item).forEach(function (segment) {
                if (segment) segments.push(segment);
            });
        });
        return segments.length ? segments : [value];
    }

    function splitLongSpeechSegment(text) {
        var value = String(text || '').trim();
        if (!value) return [];
        var maxChars = 28;
        if (value.length <= maxChars) return [value];
        var commaParts = value.match(/[^，,、]+[，,、]*/g) || [value];
        var result = [];
        var current = '';
        commaParts.forEach(function (part) {
            part = String(part || '').trim();
            if (!part) return;
            if (current && current.length + part.length > maxChars) {
                pushHardWrapped(result, current, maxChars);
                current = part;
            } else {
                current += part;
            }
        });
        if (current) pushHardWrapped(result, current, maxChars);
        return result;
    }

    function pushHardWrapped(target, text, maxChars) {
        var value = String(text || '').trim();
        while (value.length > maxChars) {
            target.push(value.slice(0, maxChars));
            value = value.slice(maxChars).trim();
        }
        if (value) target.push(value);
    }

    function speechStatusTextAt(text, progressMs, durationMs, options) {
        options = options || {};
        var fullText = String(text || '').replace(/\s+/g, ' ').trim();
        if (options.keepFullText) {
            return statusText('speaking', fullText);
        }
        var segments = speechStatusSegments(text);
        if (segments.length === 0) {
            return '';
        }
        var duration = Math.max(0, Number(durationMs) || 0);
        var progress = Math.max(0, Number(progressMs) || 0);
        if (duration <= 0) {
            return statusText('speaking', segments[0]);
        }
        var ratio = Math.min(0.999, progress / duration);
        var totalWeight = segments.reduce(function (sum, segment) {
            return sum + Math.max(1, segment.length);
        }, 0);
        var cursor = ratio * totalWeight;
        var accumulated = 0;
        for (var i = 0; i < segments.length; i += 1) {
            var weight = Math.max(1, segments[i].length);
            var nextAccumulated = accumulated + weight;
            if (cursor < nextAccumulated) {
                return statusText('speaking', segments[i]);
            }
            accumulated = nextAccumulated;
        }
        return statusText('speaking', segments[segments.length - 1]);
    }

    function progressiveSegmentText(segment, progress) {
        var value = String(segment || '').trim();
        return value;
    }

    function completionStatusText(reason) {
        switch (String(reason || 'ok')) {
            case 'asr_final_timeout':
                return '没有识别完整，我在听，请再说一次';
            case 'turn_completion_timeout':
                return '回答等待超时，我在听，请再说一次';
            case 'rag_first_audio_timeout':
            case 'rag_completion_timeout':
            case 'rag_tts_timeout':
            case 'route_timeout':
            case 'rag_no_external_audio':
            case 'rag_search_error':
            case 'rag_tts_error':
            case 'route_error':
                return '回答等待超时，我在听，请再说一次';
            case 'empty_asr':
                return '没有识别到内容';
            case 'dialog_resumed':
                return '已解除静音';
            case 'dialog_silenced':
                return '静音中';
            default:
                return '回答完成';
        }
    }

    function shouldIgnoreCompletionMessage(message) {
        return Boolean(
            message
            && message.type === 'done'
            && String(message.reason || '') === 'interrupted'
        );
    }

    function isTurnScopedVoiceMessage(message) {
        if (!message || message.turnId === undefined) {
            return false;
        }
        return String(message.type || '') !== 'dialog_silence';
    }

    return Object.freeze({
        isStreamingDialogIdle: isStreamingDialogIdle,
        isRealtimeDialogResponseActive: isRealtimeDialogResponseActive,
        canStartVoiceTurn: canStartVoiceTurn,
        canInterruptPendingResponse: canInterruptPendingResponse,
        canBargeIn: canBargeIn,
        isProtectedFixedSpeechEvent: isProtectedFixedSpeechEvent,
        canUserBargeInFixedSpeech: canUserBargeInFixedSpeech,
        canCaptureInterruptedSpeechForResume: canCaptureInterruptedSpeechForResume,
        shouldDropFixedEvent: shouldDropFixedEvent,
        canRunFixedSpeechEvent: canRunFixedSpeechEvent,
        shouldPreemptSpeechTurn: shouldPreemptSpeechTurn,
        removeStaleDialogEvents: removeStaleDialogEvents,
        statusText: statusText,
        speechStatusSegments: speechStatusSegments,
        speechStatusTextAt: speechStatusTextAt,
        progressiveSegmentText: progressiveSegmentText,
        completionStatusText: completionStatusText,
        shouldProtectInterruptedListeningStatus: shouldProtectInterruptedListeningStatus,
        shouldIgnoreCompletionMessage: shouldIgnoreCompletionMessage,
        isTurnScopedVoiceMessage: isTurnScopedVoiceMessage
    });
});
