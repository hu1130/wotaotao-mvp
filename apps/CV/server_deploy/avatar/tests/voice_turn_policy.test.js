const test = require('node:test');
const assert = require('node:assert/strict');

const policy = require('../voice_turn_policy');


test('streaming dialog stays busy until the server completes the whole turn', () => {
    const baseState = {
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        voiceStreamOpen: true,
        voiceStreamKeepOpen: true
    };

    assert.equal(policy.isStreamingDialogIdle({
        ...baseState,
        streamingAudioDone: false
    }), false);
    assert.equal(policy.isStreamingDialogIdle({
        ...baseState,
        streamingAudioDone: true
    }), true);
});


test('vad cannot open a new turn while the previous turn is processing', () => {
    assert.equal(policy.canStartVoiceTurn({
        isDialogBusy: true,
        streamingAudioPlaying: false,
        streamingAudioDone: false
    }), false);
    assert.equal(policy.canStartVoiceTurn({
        isDialogBusy: false,
        streamingAudioPlaying: false,
        streamingAudioDone: true
    }), true);
});


test('new speech can interrupt a pending response before playback starts', () => {
    const pending = {
        isDialogBusy: true,
        isListening: false,
        voiceStopRequested: true,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        hasAudio: false
    };

    assert.equal(policy.canInterruptPendingResponse(pending), true);
    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        isListening: true
    }), false);
    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        streamingAudioPlaying: true
    }), false);
    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        streamingAudioQueueLength: 1
    }), false);
    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        voiceStopRequested: false
    }), false);
});


test('long streaming responses stay barge-in active between audio chunks', () => {
    assert.equal(policy.isRealtimeDialogResponseActive({
        activeSpeechOwner: 'local_dialog',
        isDialogBusy: true,
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        streamingAudioDone: false,
        streamingPlaybackStarted: true,
        hasAudio: false
    }), true);

    assert.equal(policy.isRealtimeDialogResponseActive({
        activeSpeechOwner: 'local_dialog',
        isDialogBusy: true,
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        streamingAudioDone: false,
        streamingPlaybackStarted: false,
        hasAudio: false
    }), false);

    assert.equal(policy.isRealtimeDialogResponseActive({
        activeSpeechOwner: 'legacy_tts',
        isDialogBusy: true,
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        streamingAudioDone: false,
        streamingPlaybackStarted: true,
        hasAudio: false
    }), false);
});


test('local resumed dialog audio stays barge-in active after empty interruption reset', () => {
    assert.equal(policy.isRealtimeDialogResponseActive({
        activeSpeechOwner: 'local_dialog',
        isDialogBusy: false,
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        streamingAudioDone: true,
        streamingPlaybackStarted: false,
        hasAudio: true
    }), true);

    assert.equal(policy.isRealtimeDialogResponseActive({
        activeSpeechOwner: 'legacy_tts',
        isDialogBusy: false,
        isListening: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        streamingAudioDone: true,
        streamingPlaybackStarted: false,
        hasAudio: true
    }), false);
});


test('pending response interruption needs strong voice evidence when requested', () => {
    const pending = {
        isDialogBusy: true,
        isListening: false,
        voiceStopRequested: true,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        hasAudio: false,
        requiresStrongVoice: true,
        threshold: 0.04,
        minFrames: 4,
        minDurationMs: 120,
        minAverageRatio: 0.92,
        maxPeakToAverage: 3.2
    };

    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        rms: 0.05,
        peak: 0.07,
        frames: 3,
        avgRms: 0.048,
        durationMs: 90
    }), false);
    assert.equal(policy.canInterruptPendingResponse({
        ...pending,
        rms: 0.052,
        peak: 0.066,
        frames: 4,
        avgRms: 0.049,
        durationMs: 140
    }), true);
});


test('sustained near-end speech can interrupt active playback', () => {
    const state = {
        playing: true,
        rms: 0.072,
        peak: 0.081,
        threshold: 0.06,
        frames: 3,
        minFrames: 3
    };

    assert.equal(policy.canBargeIn(state), true);
    assert.equal(policy.canBargeIn({ ...state, frames: 1 }), false);
    assert.equal(policy.canBargeIn({ ...state, rms: 0.04 }), false);
    assert.equal(policy.canBargeIn({ ...state, playing: false }), false);
    assert.equal(policy.canBargeIn({ ...state, playing: false, responseActive: true }), true);
    assert.equal(policy.canBargeIn({
        playing: true,
        rms: 0.038,
        peak: 0.037,
        threshold: 0.035,
        frames: 2,
        minFrames: 2
    }), true);
    assert.equal(policy.canBargeIn({
        playing: true,
        rms: 0.09,
        peak: 0.16,
        threshold: 0.035,
        frames: 2,
        minFrames: 4,
        avgRms: 0.045,
        durationMs: 43,
        minDurationMs: 120,
        minAverageRatio: 0.92,
        maxPeakToAverage: 3.2
    }), false);
    assert.equal(policy.canBargeIn({
        playing: true,
        rms: 0.058,
        peak: 0.08,
        threshold: 0.035,
        frames: 4,
        minFrames: 4,
        avgRms: 0.052,
        durationMs: 130,
        minDurationMs: 120,
        minAverageRatio: 0.92,
        maxPeakToAverage: 3.2
    }), true);
    assert.equal(policy.canBargeIn({
        playing: true,
        rms: 0.04,
        peak: 0.22,
        threshold: 0.035,
        frames: 4,
        minFrames: 4,
        avgRms: 0.05,
        durationMs: 130,
        minDurationMs: 120,
        minAverageRatio: 0.92,
        maxPeakToAverage: 3.2
    }), false);
    assert.equal(policy.canBargeIn({
        playing: true,
        rms: 0.038,
        peak: 0.055,
        threshold: 0.03,
        frames: 3,
        minFrames: 3,
        avgRms: 0.034,
        durationMs: 96,
        minDurationMs: 90,
        minAverageRatio: 0.78,
        maxPeakToAverage: 4.0
    }), true);
});


test('protected fixed speech events cannot be interrupted by user barge-in', () => {
    const protectedEvents = [
        'check_in',
        'check_out',
        'arrival_task',
        'first_time',
        'returning',
        'repeat',
        'stranger',
        'returning_stranger'
    ];

    protectedEvents.forEach((eventType) => {
        assert.equal(policy.isProtectedFixedSpeechEvent(eventType), true, eventType);
        assert.equal(policy.canUserBargeInFixedSpeech(eventType), false, eventType);
    });

    ['stranger_stare', 'checked_in_stare', 'idle_long', 'crowd', 'gesture_wave'].forEach((eventType) => {
        assert.equal(policy.isProtectedFixedSpeechEvent(eventType), false, eventType);
        assert.equal(policy.canUserBargeInFixedSpeech(eventType), true, eventType);
    });

    assert.equal(policy.canUserBargeInFixedSpeech(''), false);
});


test('only realtime dialog speech can be captured for empty-barge resume', () => {
    assert.equal(policy.canCaptureInterruptedSpeechForResume({
        activeSpeechOwner: 'local_dialog',
        streamingAudioPlaying: true
    }), true);
    assert.equal(policy.canCaptureInterruptedSpeechForResume({
        activeSpeechOwner: 'local_dialog',
        hasUserText: true
    }), true);
    assert.equal(policy.canCaptureInterruptedSpeechForResume({
        activeSpeechOwner: 'legacy_tts',
        hasAudio: true,
        hasAssistantText: true
    }), false);
    assert.equal(policy.canCaptureInterruptedSpeechForResume({
        activeSpeechOwner: '',
        hasAudio: true,
        hasAssistantText: true
    }), false);
});


test('repeat greetings are not dropped before fixed speech arbitration', () => {
    assert.equal(policy.shouldDropFixedEvent({
        eventType: 'repeat',
        voiceInteractionBusy: true,
        voiceStreamOpen: true
    }), false);
    assert.equal(policy.shouldDropFixedEvent({
        eventType: 'repeat',
        voiceInteractionBusy: false,
        voiceStreamOpen: true
    }), false);
    assert.equal(policy.shouldDropFixedEvent({
        eventType: 'check_out',
        voiceInteractionBusy: false,
        voiceStreamOpen: false
    }), false);
    assert.equal(policy.shouldDropFixedEvent({
        eventType: 'repeat',
        voiceInteractionBusy: true,
        voiceStreamOpen: true,
        interruptibleListening: true
    }), false);
});


test('fixed speech can run while an idle persistent voice websocket is open', () => {
    const idlePersistent = {
        priority: 70,
        realtimePriority: 90,
        isListening: false,
        isDialogBusy: false,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        voiceStreamOpen: true,
        voiceStreamKeepOpen: true,
        hasAudio: false,
        speechSlotAvailable: true,
        allowDuringSelfMute: true,
        selfSpeechMuted: false,
        audioLockAvailable: true
    };

    assert.equal(policy.canRunFixedSpeechEvent(idlePersistent), true);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...idlePersistent,
        voiceStreamKeepOpen: false
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...idlePersistent,
        isDialogBusy: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...idlePersistent,
        streamingAudioPlaying: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...idlePersistent,
        hasAudio: true
    }), false);
});


test('fixed speech can interrupt an empty listening turn', () => {
    const emptyListening = {
        priority: 85,
        realtimePriority: 100,
        isListening: true,
        isDialogBusy: true,
        streamingAudioPlaying: false,
        streamingAudioQueueLength: 0,
        voiceStreamOpen: true,
        voiceStreamKeepOpen: false,
        hasAudio: false,
        speechSlotAvailable: true,
        allowDuringSelfMute: true,
        selfSpeechMuted: false,
        audioLockAvailable: true,
        interruptsIdleListening: true
    };

    assert.equal(policy.canRunFixedSpeechEvent(emptyListening), true);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        streamingAudioPlaying: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        hasAudio: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        userSpeechDetected: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        voiceStopRequested: true
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        currentUserText: '你好'
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        interruptsIdleListening: false
    }), false);
    assert.equal(policy.canRunFixedSpeechEvent({
        ...emptyListening,
        priority: 30
    }), true);
});

test('higher priority fixed speech can preempt active legacy fixed speech', () => {
    assert.equal(policy.shouldPreemptSpeechTurn({
        activeOwner: 'legacy_tts',
        incomingOwner: 'legacy_tts',
        activePriority: 70,
        incomingPriority: 85,
        force: true
    }), true);
    assert.equal(policy.shouldPreemptSpeechTurn({
        activeOwner: 'legacy_tts',
        incomingOwner: 'legacy_tts',
        activePriority: 85,
        incomingPriority: 70,
        force: true
    }), false);
    assert.equal(policy.shouldPreemptSpeechTurn({
        activeOwner: 'legacy_tts',
        incomingOwner: 'legacy_tts',
        activePriority: 70,
        incomingPriority: 85,
        force: false
    }), false);
});


test('queued repeat greetings are removed when a realtime turn starts', () => {
    const events = [
        { eventType: 'repeat', key: 'repeat-1' },
        { eventType: 'checked_in_stare', key: 'stare-1' },
        { eventType: 'repeat', key: 'repeat-2' }
    ];

    assert.deepEqual(
        policy.removeStaleDialogEvents(events),
        [{ eventType: 'checked_in_stare', key: 'stare-1' }]
    );
});


test('voice phases share one status text policy', () => {
    assert.equal(policy.statusText('listening'), '我在听呢');
    assert.equal(policy.statusText('recognizing', '你记得我吗'), '你记得我吗');
    assert.equal(policy.statusText('processing'), '叮当正在努力思考中');
    assert.equal(policy.statusText('speaking'), '');
    assert.equal(policy.statusText('speaking', '当然认识，你是小游。'), '当然认识，你是小游。');
});


test('speaking status is split into human sized sentences', () => {
    assert.deepEqual(
        policy.speechStatusSegments('第一句。第二句！第三句？'),
        ['第一句。', '第二句！', '第三句？']
    );

    const longText = '这是一个很长的回答，没有明显句号，但是中间有逗号，可以按照短一些的自然停顿显示出来，避免状态栏塞满整段文字';
    const segments = policy.speechStatusSegments(longText);
    assert.ok(segments.length > 1);
    assert.ok(segments.every((segment) => segment.length <= 34));
});


test('speaking status follows playback progress by sentence', () => {
    const text = '第一句。第二句比较长一些。第三句。';

    assert.equal(policy.speechStatusTextAt('', 0, 9000), '');
    assert.equal(policy.speechStatusTextAt(text, 0, 9000), '第一句。');
    assert.equal(policy.speechStatusTextAt(text, 4500, 9000), '第二句比较长一些。');
    assert.equal(policy.speechStatusTextAt(text, 8900, 9000), '第三句。');
});


test('speaking status can keep short control feedback complete', () => {
    const text = '好的，我先安静下来，喊小丑我再继续陪你聊。';

    assert.equal(
        policy.speechStatusTextAt(text, 5000, 9000, { keepFullText: true }),
        text
    );
});


test('speaking status keeps each sentence intact', () => {
    assert.equal(policy.progressiveSegmentText('当然认识，你是小游。', 0), '当然认识，你是小游。');
    assert.equal(policy.progressiveSegmentText('当然认识，你是小游。', 0.5), '当然认识，你是小游。');
    assert.equal(policy.progressiveSegmentText('当然认识，你是小游。', 1), '当然认识，你是小游。');
});


test('timeout completion text tells the user that listening recovered', () => {
    assert.equal(
        policy.completionStatusText('asr_final_timeout'),
        '没有识别完整，我在听，请再说一次'
    );
    assert.equal(
        policy.completionStatusText('rag_first_audio_timeout'),
        '回答等待超时，我在听，请再说一次'
    );
    assert.equal(
        policy.completionStatusText('route_timeout'),
        '回答等待超时，我在听，请再说一次'
    );
    assert.equal(policy.completionStatusText('empty_asr'), '没有识别到内容');
    assert.equal(policy.completionStatusText('dialog_resumed'), '已解除静音');
    assert.equal(policy.completionStatusText('dialog_silenced'), '静音中');
    assert.equal(policy.completionStatusText('ok'), '回答完成');
});


test('interrupted completion is only an old-turn acknowledgement', () => {
    assert.equal(
        policy.shouldIgnoreCompletionMessage({
            type: 'done',
            reason: 'interrupted'
        }),
        true
    );
    assert.equal(
        policy.shouldIgnoreCompletionMessage({
            type: 'done',
            reason: 'ok'
        }),
        false
    );
    assert.equal(
        policy.shouldIgnoreCompletionMessage({
            type: 'tts_end',
            reason: 'interrupted'
        }),
        false
    );
});


test('dialog silence state is not scoped to a single voice turn', () => {
    assert.equal(
        policy.isTurnScopedVoiceMessage({
            type: 'dialog_silence',
            turnId: 9,
            active: false
        }),
        false
    );
    assert.equal(
        policy.isTurnScopedVoiceMessage({
            type: 'audio',
            turnId: 9
        }),
        true
    );
    assert.equal(
        policy.isTurnScopedVoiceMessage({
            type: 'done',
            turnId: 9
        }),
        true
    );
});


test('interrupted listening status blocks stale speech text', () => {
    assert.equal(policy.shouldProtectInterruptedListeningStatus({
        protected: true,
        listeningText: '你说，我听着~',
        nextText: '上一句回答还在刷新。'
    }), true);
    assert.equal(policy.shouldProtectInterruptedListeningStatus({
        protected: true,
        listeningText: '你说，我听着~',
        nextText: '你说，我听着~'
    }), false);
    assert.equal(policy.shouldProtectInterruptedListeningStatus({
        protected: false,
        listeningText: '你说，我听着~',
        nextText: '上一句回答还在刷新。'
    }), false);
});
