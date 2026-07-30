(function () {
    'use strict';

    var MODEL_REGISTRY = {
        epsilon: { label: 'Epsilon', role: '活力助手' },
        haruGreeter: { label: 'Haru', role: '迎宾小姐' },
        haru: { label: 'Hiyori', role: '元气少女' },
        chitose: { label: 'Chitose', role: '沉稳伙伴' },
        natori: { label: 'Natori', role: '从容顾问' }
    };
    var currentModelKey = '';
    var interactionMode = '';
    var interactionModes = [];
    var isSwitchingModel = false;
    var isSwitchingMode = false;
    var connectedAtLeastOnce = false;
    var controlSession = null;
    var tenantDevices = [];
    var knowledgeDocuments = [];
    var avatarPersona = null;
    var ws = null;
    var wsReconnectTimer = null;

    var controlTabs = Array.prototype.slice.call(document.querySelectorAll('#control-tabs button'));
    var tabPanels = Array.prototype.slice.call(document.querySelectorAll('[data-tab-panel]'));
    var modelSwitcherEl = document.getElementById('model-switcher');
    var modeSwitcherEl = document.getElementById('interaction-mode-switcher');
    var gestureStatusEl = document.getElementById('gesture-status');
    var gestureDetailEl = document.getElementById('gesture-detail');
    var faceCaptureNameInput = document.getElementById('face-capture-name');
    var faceCaptureDeviceSelect = document.getElementById('face-capture-device');
    var faceCaptureButton = document.getElementById('face-capture-button');
    var faceCaptureStatusEl = document.getElementById('face-capture-status');
    var employeeFaceSelect = document.getElementById('employee-face-select');
    var employeeRefreshButton = document.getElementById('employee-refresh-button');
    var employeeDeleteButton = document.getElementById('employee-delete-button');
    var employeeFaceStatusEl = document.getElementById('employee-face-status');
    var dailyTtsGenerateButton = document.getElementById('daily-tts-generate-button');
    var dailyTtsStatusEl = document.getElementById('daily-tts-status');
    var knowledgeSummaryEl = document.getElementById('knowledge-summary');
    var knowledgeStatsButton = document.getElementById('knowledge-stats-button');
    var knowledgeIndexButton = document.getElementById('knowledge-index-button');
    var knowledgeResetIndex = document.getElementById('knowledge-reset-index');
    var knowledgeTopKInput = document.getElementById('knowledge-top-k');
    var knowledgeMinScoreInput = document.getElementById('knowledge-min-score');
    var knowledgeStatusEl = document.getElementById('knowledge-status');
    var knowledgeQueryInput = document.getElementById('knowledge-query');
    var knowledgeSearchButton = document.getElementById('knowledge-search-button');
    var knowledgeAskButton = document.getElementById('knowledge-ask-button');
    var knowledgeResultEl = document.getElementById('knowledge-result');
    var knowledgeDocumentInput = document.getElementById('knowledge-document-input');
    var knowledgeDocumentUpload = document.getElementById('knowledge-document-upload');
    var knowledgeDocumentStatus = document.getElementById('knowledge-document-status');
    var knowledgeDocumentToggle = document.getElementById('knowledge-document-toggle');
    var knowledgeDocumentToggleText = document.getElementById('knowledge-document-toggle-text');
    var knowledgeDocumentList = document.getElementById('knowledge-document-list');
    var avatarPersonaNameInput = document.getElementById('avatar-persona-name');
    var avatarPersonaAliasesInput = document.getElementById('avatar-persona-aliases');
    var avatarPersonaPersonalityInput = document.getElementById('avatar-persona-personality');
    var avatarPersonaToneInput = document.getElementById('avatar-persona-tone');
    var avatarPersonaExtraInput = document.getElementById('avatar-persona-extra');
    var avatarPersonaOpenButton = document.getElementById('avatar-persona-open');
    var avatarPersonaModal = document.getElementById('avatar-persona-modal');
    var avatarPersonaCloseButton = document.getElementById('avatar-persona-close');
    var avatarPersonaCancelButton = document.getElementById('avatar-persona-cancel');
    var avatarPersonaSaveButton = document.getElementById('avatar-persona-save');
    var avatarPersonaResetButton = document.getElementById('avatar-persona-reset');
    var avatarPersonaStatusEl = document.getElementById('avatar-persona-status');
    var tenantDeviceList = document.getElementById('tenant-device-list');
    var connectionStatusEl = document.getElementById('connection-status');
    var currentModelNameEl = document.getElementById('current-model-name');
    var controlLogoutButton = document.getElementById('control-logout-button');
    var logContentEl = document.getElementById('log-content');
    var tenantScopeTitle = document.getElementById('tenant-scope-title');
    var tenantScopeId = document.getElementById('tenant-scope-id');
    var tenantAdminName = document.getElementById('tenant-admin-name');
    var tenantDeviceCount = document.getElementById('tenant-device-count');
    var headerTenantId = document.getElementById('header-tenant-id');
    var workspaceTitle = document.getElementById('workspace-title');
    var metricEmployeeCount = document.getElementById('metric-employee-count');
    var metricDeviceCount = document.getElementById('metric-device-count');
    var metricDocumentCount = document.getElementById('metric-document-count');
    var faceCapturePollTimer = null;
    var faceCaptureWasRunning = false;
    var employeeListBusy = false;
    var employeeDeleteBusy = false;
    var dailyTtsPollTimer = null;
    var dailyTtsWasRunning = false;
    var avatarPersonaQuotePollTimer = null;
    var knowledgeIndexPollTimer = null;
    var knowledgeIndexWasRunning = false;
    var knowledgeDocumentsExpanded = false;

    function switchControlTab(tabKey) {
        var nextKey = tabKey || 'overview';
        var titles = { overview: '运行控制', faces: '人员与设备', content: '企业知识', logs: '操作记录' };
        if (workspaceTitle) workspaceTitle.textContent = titles[nextKey] || '企业控制台';
        controlTabs.forEach(function (button) {
            var active = button.dataset.tab === nextKey;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        tabPanels.forEach(function (panel) {
            var active = panel.dataset.tabPanel === nextKey;
            panel.classList.toggle('active', active);
            panel.hidden = !active;
        });
    }

    function loadControlIdentity() {
        return requestJson('/control-auth/status')
            .then(function (data) {
                if (!data.authenticated || !data.session) {
                    window.location.replace('/control-login.html?next=' + encodeURIComponent(location.pathname));
                    throw new Error('控制台会话已过期');
                }
                controlSession = data.session;
                renderControlIdentity();
                return controlSession;
            });
    }

    function renderControlIdentity() {
        var session = controlSession || {};
        var tenantName = session.tenantName || session.tenantId || '--';
        var tenantId = session.tenantId || '--';
        if (tenantScopeTitle) tenantScopeTitle.textContent = tenantName;
        if (tenantScopeId) tenantScopeId.textContent = tenantId;
        if (headerTenantId) headerTenantId.textContent = tenantId;
        if (tenantAdminName) tenantAdminName.textContent = session.displayName || session.username || '--';
        document.title = tenantName + ' · 企业数字人控制台';
        var platformAllowed = Boolean(session.capabilities && session.capabilities.platformOperations);
        document.querySelectorAll('[data-platform-only]').forEach(function (element) {
            element.hidden = !platformAllowed;
        });
    }

    function setupControlTabs() {
        controlTabs.forEach(function (button) {
            button.setAttribute('role', 'tab');
            button.setAttribute('aria-selected', button.classList.contains('active') ? 'true' : 'false');
            button.addEventListener('click', function () {
                switchControlTab(button.dataset.tab);
            });
        });
        tabPanels.forEach(function (panel) {
            panel.setAttribute('role', 'tabpanel');
        });
        switchControlTab('overview');
    }

    function sendCommand(type, payload) {
        var msg = { target: 'avatar', type: type, payload: payload || {}, ts: Date.now() };
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
        if (type !== 'PING') logCommand(type, payload);
    }

    function setupControlLogout() {
        if (!controlLogoutButton) return;
        controlLogoutButton.addEventListener('click', function () {
            fetch('/control-auth/logout', { method: 'POST' })
                .finally(function () {
                    window.location.replace('/control-login.html');
                });
        });
    }

    function logCommand(type, detail) {
        var now = new Date();
        var time = now.toLocaleTimeString('zh-CN', { hour12: false });
        var entry = document.createElement('div');
        entry.className = 'log-entry';
        var timeEl = document.createElement('span');
        timeEl.className = 'log-time';
        timeEl.textContent = time;
        var commandEl = document.createElement('span');
        commandEl.className = 'log-cmd';
        commandEl.textContent = String(type || 'EVENT');
        var detailEl = document.createElement('span');
        detailEl.className = 'log-detail';
        detailEl.textContent = detail ? JSON.stringify(detail) : '';
        entry.appendChild(timeEl);
        entry.appendChild(commandEl);
        entry.appendChild(document.createTextNode(' '));
        entry.appendChild(detailEl);
        if (logContentEl) logContentEl.appendChild(entry);
        var panel = document.getElementById('log-panel');
        if (panel) panel.scrollTop = panel.scrollHeight;
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

    function setModelSwitcherBusy(busy) {
        if (!modelSwitcherEl) return;
        isSwitchingModel = busy;
        modelSwitcherEl.querySelectorAll('button').forEach(function (btn) {
            btn.disabled = busy;
            btn.classList.toggle('active', btn.dataset.model === currentModelKey);
        });
    }

    function requestSwitchModel(key) {
        if (isSwitchingModel || key === currentModelKey) return;
        setModelSwitcherBusy(true);
        sendCommand('SWITCH_MODEL', { key: key });
    }

    function buildInteractionModeSwitcher() {
        if (!modeSwitcherEl) return;
        modeSwitcherEl.innerHTML = '';
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
            modeSwitcherEl.appendChild(button);
        });
    }

    function setModeSwitcherBusy(busy) {
        if (!modeSwitcherEl) return;
        isSwitchingMode = busy;
        modeSwitcherEl.querySelectorAll('button').forEach(function (btn) {
            btn.disabled = busy;
            btn.classList.toggle('active', btn.dataset.mode === interactionMode);
        });
    }

    function requestInteractionMode(modeKey) {
        if (isSwitchingMode || modeKey === interactionMode) return;
        setModeSwitcherBusy(true);
        sendCommand('SET_INTERACTION_MODE', { mode: modeKey });
    }

    function updateConnectionStatus(online) {
        if (!connectionStatusEl) return;
        if (online) {
            connectedAtLeastOnce = true;
            connectionStatusEl.className = 'status-dot online';
            connectionStatusEl.textContent = '已连接';
        } else {
            connectionStatusEl.className = 'status-dot offline';
            connectionStatusEl.textContent = '未连接';
        }
    }

    function updateModelDisplay(key) {
        currentModelKey = key;
        var config = MODEL_REGISTRY[key];
        if (currentModelNameEl) {
            var personaName = avatarPersona && avatarPersona.assistantName;
            var modelText = config ? config.label + ' · ' + config.role : key;
            currentModelNameEl.textContent = personaName ? personaName + ' / ' + modelText : modelText;
        }
        if (modelSwitcherEl) {
            modelSwitcherEl.querySelectorAll('button').forEach(function (btn) {
                btn.classList.toggle('active', btn.dataset.model === key);
            });
        }
    }

    function openAvatarPersonaModal() {
        if (!avatarPersonaModal) return;
        avatarPersonaModal.hidden = false;
        document.body.classList.add('modal-open');
        window.setTimeout(function () {
            if (avatarPersonaNameInput) avatarPersonaNameInput.focus();
        }, 0);
    }

    function closeAvatarPersonaModal() {
        if (!avatarPersonaModal) return;
        avatarPersonaModal.hidden = true;
        document.body.classList.remove('modal-open');
        if (avatarPersonaOpenButton) avatarPersonaOpenButton.focus();
    }

    function setAvatarPersonaStatus(message, state) {
        if (!avatarPersonaStatusEl) return;
        avatarPersonaStatusEl.textContent = message || '待命';
        avatarPersonaStatusEl.classList.toggle('running', state === 'running');
        avatarPersonaStatusEl.classList.toggle('error', state === 'error');
        avatarPersonaStatusEl.classList.toggle('ok', state === 'ok');
    }

    function setAvatarPersonaBusy(busy) {
        [
            avatarPersonaNameInput,
            avatarPersonaAliasesInput,
            avatarPersonaPersonalityInput,
            avatarPersonaToneInput,
            avatarPersonaExtraInput,
            avatarPersonaOpenButton,
            avatarPersonaSaveButton,
            avatarPersonaResetButton
        ].forEach(function (element) {
            if (element) element.disabled = busy;
        });
    }

    function renderAvatarPersona(persona) {
        avatarPersona = persona || {};
        if (avatarPersonaNameInput) avatarPersonaNameInput.value = avatarPersona.assistantName || '';
        if (avatarPersonaAliasesInput) {
            avatarPersonaAliasesInput.value = (
                avatarPersona.customWakeAliases
                || avatarPersona.savedWakeAliases
                || []
            ).join('、');
        }
        if (avatarPersonaPersonalityInput) avatarPersonaPersonalityInput.value = avatarPersona.personality || '';
        if (avatarPersonaToneInput) avatarPersonaToneInput.value = avatarPersona.speakingTone || '';
        if (avatarPersonaExtraInput) avatarPersonaExtraInput.value = avatarPersona.extraInstructions || '';
        updateModelDisplay(currentModelKey);
        setAvatarPersonaStatus(
            avatarPersona.customized
                ? '已启用企业人设'
                : '使用系统默认人设',
            avatarPersona.customized ? 'ok' : ''
        );
    }

    function applyAvatarPersonaQuoteStatus(status) {
        status = status || {};
        if (!status.status || status.status === 'idle') return false;
        if (status.running || status.status === 'running') {
            setAvatarPersonaStatus(status.message || '正在为数字人生成新人设语录', 'running');
            return true;
        }
        if (status.status === 'generated') {
            setAvatarPersonaStatus(status.message || '新语录生成成功', 'ok');
            return false;
        }
        if (status.status === 'default') {
            setAvatarPersonaStatus(status.message || '已恢复默认人设，继续使用默认语录', 'ok');
            return false;
        }
        if (status.status === 'failed' || status.error) {
            setAvatarPersonaStatus(
                (status.message || '新人设已保存，但新语录生成失败')
                    + (status.error ? ': ' + status.error : ''),
                'error'
            );
            return false;
        }
        return false;
    }

    function stopAvatarPersonaQuotePolling() {
        if (avatarPersonaQuotePollTimer) {
            clearTimeout(avatarPersonaQuotePollTimer);
            avatarPersonaQuotePollTimer = null;
        }
    }

    function scheduleAvatarPersonaQuotePolling(delayMs) {
        stopAvatarPersonaQuotePolling();
        avatarPersonaQuotePollTimer = window.setTimeout(pollAvatarPersonaQuoteStatus, delayMs || 1500);
    }

    function pollAvatarPersonaQuoteStatus() {
        requestJson('/tenant/avatar-persona/quote-status')
            .then(function (data) {
                var status = data.data || {};
                var keepPolling = applyAvatarPersonaQuoteStatus(status);
                if (keepPolling) {
                    scheduleAvatarPersonaQuotePolling(2000);
                } else {
                    stopAvatarPersonaQuotePolling();
                }
            })
            .catch(function (err) {
                stopAvatarPersonaQuotePolling();
                setAvatarPersonaStatus('语录生成状态读取失败: ' + err.message, 'error');
                logCommand('AVATAR_PERSONA_QUOTE_STATUS_ERROR', { message: err.message });
            });
    }

    function parsePersonaAliases(value) {
        return String(value || '')
            .split(/[、,，\n]/)
            .map(function (item) { return item.trim(); })
            .filter(Boolean)
            .filter(function (item, index, list) { return list.indexOf(item) === index; })
            .slice(0, 8);
    }

    function collectAvatarPersonaForm() {
        return {
            assistantName: avatarPersonaNameInput ? avatarPersonaNameInput.value.trim() : '',
            wakeAliases: parsePersonaAliases(avatarPersonaAliasesInput && avatarPersonaAliasesInput.value),
            personality: avatarPersonaPersonalityInput ? avatarPersonaPersonalityInput.value.trim() : '',
            speakingTone: avatarPersonaToneInput ? avatarPersonaToneInput.value.trim() : '',
            extraInstructions: avatarPersonaExtraInput ? avatarPersonaExtraInput.value.trim() : ''
        };
    }

    function hasCustomAvatarPersona(payload) {
        return Boolean(
            (payload.assistantName || '').trim()
            || (payload.personality || '').trim()
            || (payload.speakingTone || '').trim()
            || (payload.extraInstructions || '').trim()
            || (payload.wakeAliases || []).length
        );
    }

    function loadAvatarPersona() {
        if (!avatarPersonaStatusEl) return Promise.resolve();
        setAvatarPersonaBusy(true);
        setAvatarPersonaStatus('读取数字人人设中', 'running');
        return requestJson('/tenant/avatar-persona')
            .then(function (data) {
                renderAvatarPersona(data.data || {});
                pollAvatarPersonaQuoteStatus();
                logCommand('AVATAR_PERSONA_LOAD', {
                    customized: Boolean(data.data && data.data.customized),
                    version: data.data && data.data.version
                });
            })
            .catch(function (err) {
                setAvatarPersonaStatus('读取失败: ' + err.message, 'error');
                logCommand('AVATAR_PERSONA_LOAD_ERROR', { message: err.message });
            })
            .finally(function () {
                setAvatarPersonaBusy(false);
            });
    }

    function saveAvatarPersona(payload, actionName) {
        var isCustomPersona = hasCustomAvatarPersona(payload || {});
        setAvatarPersonaBusy(true);
        setAvatarPersonaStatus(
            isCustomPersona
                ? '正在保存人设，正在为数字人生成新人设语录'
                : '正在恢复默认人设和默认语录',
            'running'
        );
        closeAvatarPersonaModal();
        return requestJson('/tenant/avatar-persona', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (data) {
                var persona = data.data || {};
                var quoteGeneration = persona.quoteGeneration || {};
                renderAvatarPersona(persona);
                if (applyAvatarPersonaQuoteStatus(quoteGeneration)) {
                    scheduleAvatarPersonaQuotePolling(1000);
                } else if (!quoteGeneration.status || quoteGeneration.status === 'idle') {
                    setAvatarPersonaStatus('已保存', 'ok');
                }
                logCommand(actionName || 'AVATAR_PERSONA_SAVE', {
                    name: persona.assistantName,
                    version: persona.version,
                    aliases: persona.wakeAliases,
                    quoteStatus: quoteGeneration.status || ''
                });
            })
            .catch(function (err) {
                setAvatarPersonaStatus('保存失败: ' + err.message, 'error');
                logCommand('AVATAR_PERSONA_SAVE_ERROR', { message: err.message });
            })
            .finally(function () {
                setAvatarPersonaBusy(false);
            });
    }

    function setupAvatarPersonaPanel() {
        if (!avatarPersonaStatusEl) return;
        if (avatarPersonaOpenButton) {
            avatarPersonaOpenButton.addEventListener('click', openAvatarPersonaModal);
        }
        if (avatarPersonaCloseButton) {
            avatarPersonaCloseButton.addEventListener('click', closeAvatarPersonaModal);
        }
        if (avatarPersonaCancelButton) {
            avatarPersonaCancelButton.addEventListener('click', closeAvatarPersonaModal);
        }
        if (avatarPersonaModal) {
            avatarPersonaModal.addEventListener('click', function (event) {
                if (event.target === avatarPersonaModal) closeAvatarPersonaModal();
            });
        }
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && avatarPersonaModal && !avatarPersonaModal.hidden) {
                closeAvatarPersonaModal();
            }
        });
        if (avatarPersonaSaveButton) {
            avatarPersonaSaveButton.addEventListener('click', function () {
                saveAvatarPersona(collectAvatarPersonaForm(), 'AVATAR_PERSONA_SAVE');
            });
        }
        if (avatarPersonaResetButton) {
            avatarPersonaResetButton.addEventListener('click', function () {
                if (!window.confirm('确认恢复系统默认数字人人设吗？')) return;
                saveAvatarPersona({
                    assistantName: '',
                    wakeAliases: [],
                    personality: '',
                    speakingTone: '',
                    extraInstructions: ''
                }, 'AVATAR_PERSONA_RESET');
            });
        }
        loadAvatarPersona();
    }

    function handleStateSync(data) {
        if (data.modelKey) {
            updateModelDisplay(data.modelKey);
            setModelSwitcherBusy(false);
        }
        if (data.interactionMode !== undefined) {
            interactionMode = data.interactionMode;
        }
        if (data.interactionModes) {
            interactionModes = data.interactionModes;
            buildInteractionModeSwitcher();
        }
        if (data.isSwitchingModel !== undefined) {
            setModelSwitcherBusy(data.isSwitchingModel);
        }
        if (data.isSwitchingMode !== undefined) {
            setModeSwitcherBusy(data.isSwitchingMode);
        }
        updateConnectionStatus(true);
    }

    function loadInteractionModes() {
        fetch('/interaction-mode')
            .then(function (res) { return res.ok ? res.json() : {}; })
            .then(function (data) {
                interactionMode = data.mode || '';
                interactionModes = data.modes || [];
                buildInteractionModeSwitcher();
            })
            .catch(function () {
                interactionModes = [];
                buildInteractionModeSwitcher();
            });
    }

    function formatGestureName(name) {
        var names = {
            wave: '招手',
            thumbs_up: '点赞',
            heart: '比心',
            ok: 'OK',
            peace: '剪刀手',
            middle_finger: '竖中指',
            none: '未识别'
        };
        return names[name] || name || '未识别';
    }

    function renderGestureStatus(status) {
        if (!gestureStatusEl || !gestureDetailEl) return;
        var candidate = status && status.candidate;
        var stableCandidate = status && status.stableCandidate;
        var event = status && status.event;
        var enabled = Boolean(status && status.enabled);
        var running = Boolean(status && status.running);
        var error = status && status.error;
        gestureStatusEl.classList.toggle('running', running && !status.stale);
        gestureStatusEl.classList.toggle('error', Boolean(error));
        if (error) {
            gestureStatusEl.textContent = '异常: ' + error;
        } else if (!enabled) {
            gestureStatusEl.textContent = '未启用';
        } else if (!running || status.stale) {
            gestureStatusEl.textContent = '等待识别数据';
        } else {
            gestureStatusEl.textContent = '识别中 · ' + (status.stage || 'observe');
        }

        var parts = [];
        if (stableCandidate) {
            parts.push('稳定: ' + formatGestureName(stableCandidate.name));
            parts.push('置信度: ' + Math.round((stableCandidate.confidence || 0) * 100) + '%');
            parts.push('手: ' + (stableCandidate.hand || '--'));
        } else if (candidate) {
            parts.push('观察中: ' + formatGestureName(candidate.name));
            parts.push('置信度: ' + Math.round((candidate.confidence || 0) * 100) + '%');
            parts.push('未稳定');
        }
        if (event) {
            parts.push('最近事件: ' + formatGestureName(event.name));
        }
        gestureDetailEl.textContent = parts.length ? parts.join(' / ') : '--';
    }

    function pollGestureStatus() {
        fetch('/gesture/status')
            .then(function (res) { return res.ok ? res.json() : {}; })
            .then(renderGestureStatus)
            .catch(function (err) {
                renderGestureStatus({ enabled: false, error: err.message });
            });
    }

    function setFaceCaptureStatus(status, message) {
        if (!faceCaptureStatusEl || !faceCaptureButton) return;
        var running = Boolean(status && status.running);
        var error = status && status.error;
        faceCaptureButton.disabled = running || !getSelectedCaptureDeviceId();
        if (faceCaptureDeviceSelect) faceCaptureDeviceSelect.disabled = running;
        faceCaptureButton.textContent = running ? '任务执行中' : '下发采集任务';
        faceCaptureStatusEl.classList.toggle('running', running);
        faceCaptureStatusEl.classList.toggle('error', Boolean(error && !running));
        if (message) {
            faceCaptureStatusEl.textContent = message;
        } else if (running) {
            faceCaptureStatusEl.textContent = (status.name || '员工') + ' 拍摄注册中';
        } else if (status && status.clientTaskDispatched) {
            faceCaptureStatusEl.textContent = (status.name || '员工') + ' 任务已下发，等待前台客户端打开窗口';
        } else if (error) {
            faceCaptureStatusEl.textContent = '失败: ' + error;
        } else if (status && status.finishedAt) {
            faceCaptureStatusEl.textContent = (status.name || '员工') + ' 注册流程已结束';
        } else {
            faceCaptureStatusEl.textContent = '待命';
        }
    }

    function summarizeFaceCaptureResult(status) {
        if (!status) return {};
        var output = String(status.stdout || '').split(/\r?\n/).filter(Boolean).slice(-4);
        var errors = String(status.stderr || '').split(/\r?\n/).filter(Boolean).slice(-4);
        return {
            name: status.name,
            exitCode: status.exitCode,
            error: status.error || '',
            output: output.join(' | '),
            stderr: errors.join(' | ')
        };
    }

    function pollFaceCaptureStatus() {
        fetch('/faces/capture-status')
            .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error('状态接口异常')); })
            .then(function (data) {
                var status = data || {};
                setFaceCaptureStatus(status);
                if (status.running) {
                    faceCaptureWasRunning = true;
                    if (!faceCapturePollTimer) {
                        faceCapturePollTimer = setInterval(pollFaceCaptureStatus, 2000);
                    }
                    return;
                }
                if (faceCaptureWasRunning) {
                    logCommand(status.error ? 'FACE_CAPTURE_FAILED' : 'FACE_CAPTURE_DONE', summarizeFaceCaptureResult(status));
                    if (!status.error && faceCaptureNameInput) {
                        faceCaptureNameInput.value = '';
                    }
                    faceCaptureWasRunning = false;
                }
                if (faceCapturePollTimer) {
                    clearInterval(faceCapturePollTimer);
                    faceCapturePollTimer = null;
                }
            })
            .catch(function (err) {
                setFaceCaptureStatus(null, '状态获取失败: ' + err.message);
            });
    }

    function startFaceCapture() {
        if (!faceCaptureNameInput || !faceCaptureButton) return;
        var name = faceCaptureNameInput.value.trim();
        var deviceId = getSelectedCaptureDeviceId();
        if (!deviceId) {
            setFaceCaptureStatus(null, '请先选择本企业的活动设备');
            if (faceCaptureDeviceSelect) faceCaptureDeviceSelect.focus();
            return;
        }
        if (!name) {
            setFaceCaptureStatus(null, '请先输入员工姓名');
            faceCaptureNameInput.focus();
            return;
        }

        setFaceCaptureStatus({ running: true, name: name }, name + ' 拍摄注册启动中');
        fetch('/faces/capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, deviceId: deviceId })
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
                var status = data.status || {};
                setFaceCaptureStatus(status);
                logCommand('FACE_CAPTURE_START', { name: name, deviceId: deviceId });
                if (status.running) {
                    pollFaceCaptureStatus();
                }
            })
            .catch(function (err) {
                setFaceCaptureStatus({ error: err.message }, '启动失败: ' + err.message);
                logCommand('FACE_CAPTURE_ERROR', { message: err.message });
            });
    }

    function setupFaceCapture() {
        if (!faceCaptureButton) return;
        faceCaptureButton.addEventListener('click', startFaceCapture);
        if (faceCaptureNameInput) {
            faceCaptureNameInput.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    startFaceCapture();
                }
            });
        }
        if (faceCaptureDeviceSelect) {
            faceCaptureDeviceSelect.addEventListener('change', function () {
                setFaceCaptureStatus(null, getSelectedCaptureDeviceId() ? '设备已选择，可以下发采集任务' : '请选择活动设备');
            });
        }
        pollFaceCaptureStatus();
    }

    function getSelectedCaptureDeviceId() {
        return faceCaptureDeviceSelect ? faceCaptureDeviceSelect.value.trim() : '';
    }

    function loadTenantDevices() {
        return requestJson('/tenant/devices')
            .then(function (data) {
                tenantDevices = Array.isArray(data.data) ? data.data : [];
                renderTenantDevices();
                return tenantDevices;
            })
            .catch(function (err) {
                tenantDevices = [];
                renderTenantDevices(err.message);
                logCommand('TENANT_DEVICE_LIST_ERROR', { message: err.message });
                return [];
            });
    }

    function renderTenantDevices(errorMessage) {
        var activeDevices = tenantDevices.filter(function (device) { return device.status === 'active'; });
        if (tenantDeviceCount) tenantDeviceCount.textContent = activeDevices.length + ' / ' + tenantDevices.length;
        if (metricDeviceCount) metricDeviceCount.textContent = String(tenantDevices.length);

        if (faceCaptureDeviceSelect) {
            var previous = faceCaptureDeviceSelect.value;
            faceCaptureDeviceSelect.innerHTML = '';
            if (!activeDevices.length) {
                var emptyOption = document.createElement('option');
                emptyOption.value = '';
                emptyOption.textContent = errorMessage ? '设备读取失败' : '暂无活动设备';
                faceCaptureDeviceSelect.appendChild(emptyOption);
            } else {
                activeDevices.forEach(function (device) {
                    var option = document.createElement('option');
                    option.value = device.deviceId;
                    option.textContent = (device.displayName || '未命名设备') + ' · ' + device.deviceId;
                    faceCaptureDeviceSelect.appendChild(option);
                });
                if (previous && activeDevices.some(function (item) { return item.deviceId === previous; })) {
                    faceCaptureDeviceSelect.value = previous;
                }
            }
        }
        setFaceCaptureStatus(null, activeDevices.length ? '选择设备并填写员工姓名' : '当前企业没有可用设备');

        if (!tenantDeviceList) return;
        tenantDeviceList.innerHTML = '';
        if (errorMessage || !tenantDevices.length) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = errorMessage ? '设备读取失败：' + errorMessage : '当前企业尚未绑定设备';
            tenantDeviceList.appendChild(empty);
            return;
        }
        tenantDevices.forEach(function (device) {
            var row = document.createElement('article');
            row.className = 'device-row';
            var info = document.createElement('div');
            var title = document.createElement('strong');
            title.textContent = device.displayName || '未命名设备';
            var meta = document.createElement('span');
            meta.textContent = device.deviceId + ' · 最近在线 ' + formatDateTime(device.lastSeenAt);
            info.appendChild(title);
            info.appendChild(meta);
            var status = document.createElement('span');
            status.className = 'resource-status ' + (device.status === 'active' ? 'active' : 'disabled');
            status.textContent = device.status === 'active' ? '活动' : '已停用';
            var button = document.createElement('button');
            button.type = 'button';
            button.className = device.status === 'active' ? 'danger-link' : 'text-button';
            button.textContent = device.status === 'active' ? '停用' : '启用';
            button.addEventListener('click', function () {
                updateTenantDeviceStatus(device, device.status === 'active' ? 'revoked' : 'active', button);
            });
            row.appendChild(info);
            row.appendChild(status);
            row.appendChild(button);
            tenantDeviceList.appendChild(row);
        });
    }

    function updateTenantDeviceStatus(device, nextStatus, button) {
        if (nextStatus === 'revoked' && !window.confirm('确认停用设备“' + (device.displayName || device.deviceId) + '”吗？')) return;
        button.disabled = true;
        requestJson('/tenant/devices/' + encodeURIComponent(device.deviceId) + '/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: nextStatus })
        })
            .then(function () {
                logCommand('TENANT_DEVICE_STATUS', { deviceId: device.deviceId, status: nextStatus });
                return loadTenantDevices();
            })
            .catch(function (err) {
                logCommand('TENANT_DEVICE_STATUS_ERROR', { deviceId: device.deviceId, message: err.message });
                window.alert('设备状态修改失败：' + err.message);
            })
            .finally(function () { button.disabled = false; });
    }

    function formatDateTime(value) {
        if (!value) return '从未';
        var date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
    }

    function requestJson(url, options) {
        return fetch(url, options || {})
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    if (!res.ok || data.ok === false) {
                        var error = new Error(data.error || data.detail || ('HTTP ' + res.status));
                        error.status = res.status;
                        error.data = data;
                        if (res.status === 401 && url !== '/control-auth/status') {
                            window.location.replace('/control-login.html?next=' + encodeURIComponent(location.pathname));
                        }
                        throw error;
                    }
                    return data;
                });
            });
    }

    function setEmployeeFaceStatus(message, state) {
        if (!employeeFaceStatusEl) return;
        employeeFaceStatusEl.textContent = message || '待命';
        employeeFaceStatusEl.classList.toggle('running', state === 'running');
        employeeFaceStatusEl.classList.toggle('error', state === 'error');
    }

    function setEmployeeFaceBusy(busy) {
        if (employeeRefreshButton) employeeRefreshButton.disabled = busy;
        if (employeeDeleteButton) employeeDeleteButton.disabled = busy || !getSelectedEmployeeName();
        if (employeeFaceSelect) employeeFaceSelect.disabled = busy;
    }

    function getSelectedEmployeeName() {
        return employeeFaceSelect ? employeeFaceSelect.value.trim() : '';
    }

    function renderEmployeeOptions(names) {
        if (!employeeFaceSelect) return;
        var previous = getSelectedEmployeeName();
        employeeFaceSelect.innerHTML = '';
        if (!names.length) {
            var emptyOption = document.createElement('option');
            emptyOption.value = '';
            emptyOption.textContent = '暂无员工';
            employeeFaceSelect.appendChild(emptyOption);
            return;
        }

        names.forEach(function (name) {
            var option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            employeeFaceSelect.appendChild(option);
        });
        if (previous && names.indexOf(previous) !== -1) {
            employeeFaceSelect.value = previous;
        }
    }

    function loadEmployees() {
        if (employeeListBusy) return;
        employeeListBusy = true;
        setEmployeeFaceBusy(true);
        setEmployeeFaceStatus('读取员工列表中', 'running');
        requestJson('/employees')
            .then(function (data) {
                var names = data.names || data.data && data.data.names || [];
                renderEmployeeOptions(names);
                if (metricEmployeeCount) metricEmployeeCount.textContent = String(names.length);
                setEmployeeFaceStatus('员工 ' + names.length + ' 人', '');
                logCommand('EMPLOYEE_LIST', { count: names.length });
            })
            .catch(function (err) {
                renderEmployeeOptions([]);
                if (metricEmployeeCount) metricEmployeeCount.textContent = '!';
                setEmployeeFaceStatus('读取失败: ' + err.message, 'error');
                logCommand('EMPLOYEE_LIST_ERROR', { message: err.message });
            })
            .finally(function () {
                employeeListBusy = false;
                setEmployeeFaceBusy(employeeDeleteBusy);
            });
    }

    function deleteSelectedEmployee() {
        var name = getSelectedEmployeeName();
        if (!name || employeeDeleteBusy) {
            setEmployeeFaceStatus('请先选择员工', 'error');
            return;
        }
        var confirmed = window.confirm('确认删除“' + name + '”的员工记录和人脸向量吗？');
        if (!confirmed) return;

        employeeDeleteBusy = true;
        setEmployeeFaceBusy(true);
        setEmployeeFaceStatus('删除 ' + name + ' 的人脸数据中', 'running');
        requestJson('/employees/' + encodeURIComponent(name), { method: 'DELETE' })
            .then(function (data) {
                setEmployeeFaceStatus('已删除: ' + name, '');
                logCommand('EMPLOYEE_DELETE_DONE', {
                    name: name,
                    deleted: data.deleted,
                    employeeTable: data.deletedFromEmployeeTable,
                    faceDb: data.deletedFromFaceDb
                });
                loadEmployees();
            })
            .catch(function (err) {
                setEmployeeFaceStatus('删除失败: ' + err.message, 'error');
                logCommand('EMPLOYEE_DELETE_ERROR', { name: name, message: err.message });
            })
            .finally(function () {
                employeeDeleteBusy = false;
                setEmployeeFaceBusy(employeeListBusy);
            });
    }

    function setupEmployeeFacePanel() {
        if (employeeRefreshButton) {
            employeeRefreshButton.addEventListener('click', loadEmployees);
        }
        if (employeeDeleteButton) {
            employeeDeleteButton.addEventListener('click', deleteSelectedEmployee);
        }
        if (employeeFaceSelect) {
            employeeFaceSelect.addEventListener('change', function () {
                setEmployeeFaceBusy(employeeListBusy || employeeDeleteBusy);
            });
        }
        loadEmployees();
    }

    function setDailyTtsStatus(status, message) {
        if (!dailyTtsStatusEl || !dailyTtsGenerateButton) return;
        var running = Boolean(status && status.running);
        var error = status && status.error;
        dailyTtsGenerateButton.disabled = running;
        dailyTtsGenerateButton.textContent = running ? '生成中' : '重新生成今日语录';
        dailyTtsStatusEl.classList.toggle('running', running);
        dailyTtsStatusEl.classList.toggle('error', Boolean(error && !running));
        if (message) {
            dailyTtsStatusEl.textContent = message;
        } else if (running) {
            dailyTtsStatusEl.textContent = '今日语录生成中';
        } else if (error) {
            dailyTtsStatusEl.textContent = '失败: ' + error;
        } else if (status && status.finishedAt) {
            dailyTtsStatusEl.textContent = '已生成，清理旧语音 ' + (status.clearedCacheFiles || 0) + ' 个';
        } else {
            dailyTtsStatusEl.textContent = '待命';
        }
    }

    function pollDailyTtsStatus() {
        requestJson('/daily-tts/status')
            .then(function (status) {
                setDailyTtsStatus(status);
                if (status.running) {
                    dailyTtsWasRunning = true;
                    if (!dailyTtsPollTimer) {
                        dailyTtsPollTimer = setInterval(pollDailyTtsStatus, 2000);
                    }
                    return;
                }
                if (dailyTtsWasRunning) {
                    logCommand(status.error ? 'DAILY_TTS_FAILED' : 'DAILY_TTS_DONE', {
                        error: status.error || '',
                        clearedCacheFiles: status.clearedCacheFiles || 0
                    });
                    dailyTtsWasRunning = false;
                }
                if (dailyTtsPollTimer) {
                    clearInterval(dailyTtsPollTimer);
                    dailyTtsPollTimer = null;
                }
            })
            .catch(function (err) {
                setDailyTtsStatus({ error: err.message }, '状态获取失败: ' + err.message);
            });
    }

    function startDailyTtsGeneration() {
        setDailyTtsStatus({ running: true }, '今日语录生成启动中');
        requestJson('/daily-tts/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        })
            .then(function (data) {
                setDailyTtsStatus(data.status || {});
                logCommand('DAILY_TTS_START');
                pollDailyTtsStatus();
            })
            .catch(function (err) {
                setDailyTtsStatus({ error: err.message }, '启动失败: ' + err.message);
                logCommand('DAILY_TTS_ERROR', { message: err.message });
            });
    }

    function setupDailyTts() {
        if (!dailyTtsGenerateButton) return;
        dailyTtsGenerateButton.addEventListener('click', startDailyTtsGeneration);
        pollDailyTtsStatus();
    }

    function setKnowledgeStatus(message, state) {
        if (!knowledgeStatusEl) return;
        knowledgeStatusEl.textContent = message || '待命';
        knowledgeStatusEl.classList.toggle('running', state === 'running');
        knowledgeStatusEl.classList.toggle('error', state === 'error');
    }

    function setKnowledgeBusy(busy) {
        [knowledgeStatsButton, knowledgeIndexButton, knowledgeSearchButton, knowledgeAskButton].forEach(function (btn) {
            if (btn) btn.disabled = busy;
        });
    }

    function getKnowledgeTopK() {
        var topK = Number(knowledgeTopKInput && knowledgeTopKInput.value);
        if (!Number.isFinite(topK)) return 6;
        return Math.max(1, Math.min(20, Math.floor(topK)));
    }

    function getKnowledgeMinScore() {
        var score = Number(knowledgeMinScoreInput && knowledgeMinScoreInput.value);
        if (!Number.isFinite(score)) return 0.12;
        return Math.max(0, Math.min(1, score));
    }

    function updateKnowledgeSummary(stats) {
        if (!knowledgeSummaryEl) return;
        if (!stats) {
            knowledgeSummaryEl.textContent = '未读取统计';
            return;
        }
        var parts = [
            '后端: ' + (stats.backend || '未知'),
            '文档: ' + (stats.documents || 0),
            '片段: ' + (stats.chunks || 0)
        ];
        if (stats.embeddingDim) {
            parts.push('向量维度: ' + stats.embeddingDim);
        }
        if (stats.updatedAt) {
            parts.push('更新时间: ' + new Date(Number(stats.updatedAt) * 1000).toLocaleString('zh-CN'));
        }
        knowledgeSummaryEl.textContent = parts.join(' / ');
    }

    function formatKnowledgeValue(value) {
        if (Array.isArray(value)) {
            return value.map(function (item, index) {
                var retrieval = item.metadata && item.metadata.retrieval || {};
                return [
                    '[' + (index + 1) + '] ' + (item.citation || item.title || item.sourcePath || ''),
                    'score=' + item.score +
                    ' vector=' + (retrieval.vectorScore || 0) +
                    ' lexical=' + (retrieval.lexicalScore || 0),
                    String(item.content || '').trim()
                ].join('\n');
            }).join('\n\n');
        }
        if (value && typeof value === 'object' && value.answer) {
            return [
                value.answer,
                '',
                '来源:',
                (value.sources || []).map(function (item, index) {
                    return (index + 1) + '. ' + (item.citation || item.title || item.sourcePath || '') +
                        ' score=' + item.score;
                }).join('\n')
            ].join('\n');
        }
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }

    function showKnowledgeResult(value) {
        if (!knowledgeResultEl) return;
        knowledgeResultEl.classList.add('visible');
        knowledgeResultEl.textContent = formatKnowledgeValue(value);
    }

    function loadKnowledgeStats() {
        setKnowledgeBusy(true);
        setKnowledgeStatus('读取知识库统计中', 'running');
        requestJson('/knowledge/stats')
            .then(function (data) {
                setKnowledgeStatus('统计已更新', '');
                updateKnowledgeSummary(data.data || {});
                showKnowledgeResult(data.data || {});
                logCommand('KNOWLEDGE_STATS', data.data || {});
            })
            .catch(function (err) {
                setKnowledgeStatus('统计失败: ' + err.message, 'error');
                logCommand('KNOWLEDGE_STATS_ERROR', { message: err.message });
            })
            .finally(function () {
                if (!knowledgeIndexWasRunning) {
                    setKnowledgeBusy(false);
                }
            });
    }

    function rebuildKnowledgeIndex() {
        var resetIndex = Boolean(knowledgeResetIndex && knowledgeResetIndex.checked);
        startKnowledgeIndex(resetIndex, 'manual');
    }

    function startKnowledgeIndex(resetIndex, source) {
        source = source || 'manual';
        setKnowledgeBusy(true);
        setKnowledgeStatus(resetIndex ? '知识库全量索引任务提交中' : '知识库增量索引任务提交中', 'running');
        return requestJson('/knowledge/index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reset: resetIndex })
        })
            .then(function (data) {
                knowledgeIndexWasRunning = true;
                setKnowledgeStatus(resetIndex ? '知识库索引后台全量重建中' : '知识库索引后台增量更新中', 'running');
                showKnowledgeResult(data.status || data.data || {});
                logCommand('KNOWLEDGE_INDEX_START', {
                    source: source,
                    reset: resetIndex,
                    status: data.status || {}
                });
                pollKnowledgeIndexStatus();
                if (!knowledgeIndexPollTimer) {
                    knowledgeIndexPollTimer = setInterval(pollKnowledgeIndexStatus, 2000);
                }
            })
            .catch(function (err) {
                if (err.status === 409) {
                    knowledgeIndexWasRunning = true;
                    setKnowledgeStatus('已有知识库索引任务运行中，继续等待结果', 'running');
                    showKnowledgeResult(err.data && err.data.status || {});
                    logCommand('KNOWLEDGE_INDEX_ALREADY_RUNNING', { source: source, reset: resetIndex });
                    pollKnowledgeIndexStatus();
                    if (!knowledgeIndexPollTimer) {
                        knowledgeIndexPollTimer = setInterval(pollKnowledgeIndexStatus, 2000);
                    }
                    return;
                }
                setKnowledgeStatus('索引失败: ' + err.message, 'error');
                logCommand('KNOWLEDGE_INDEX_ERROR', { source: source, message: err.message });
            })
            .finally(function () {
                if (!knowledgeIndexWasRunning) {
                    setKnowledgeBusy(false);
                }
            });
    }

    function autoUpdateKnowledgeIndex(reason) {
        setKnowledgeStatus('文档已变化，正在自动增量更新索引', 'running');
        return startKnowledgeIndex(false, reason || 'document_changed');
    }

    function pollKnowledgeIndexStatus() {
        requestJson('/knowledge/index-status')
            .then(function (data) {
                var status = data || {};
                if (status.running) {
                    knowledgeIndexWasRunning = true;
                    setKnowledgeBusy(true);
                    setKnowledgeStatus(status.reset ? '知识库索引后台全量重建中' : '知识库索引后台增量更新中', 'running');
                    showKnowledgeResult(status);
                    return;
                }

                if (knowledgeIndexWasRunning) {
                    if (status.error) {
                        setKnowledgeStatus('索引失败: ' + status.error, 'error');
                        logCommand('KNOWLEDGE_INDEX_ERROR', { message: status.error });
                    } else {
                        setKnowledgeStatus(status.reset ? '索引已全量重建' : '索引已增量更新', '');
                        updateKnowledgeSummary(status.result && status.result.stats);
                        showKnowledgeResult(status.result || status);
                        logCommand('KNOWLEDGE_INDEX_DONE', status.result || {});
                    }
                    knowledgeIndexWasRunning = false;
                }
                setKnowledgeBusy(false);
                if (knowledgeIndexPollTimer) {
                    clearInterval(knowledgeIndexPollTimer);
                    knowledgeIndexPollTimer = null;
                }
            })
            .catch(function (err) {
                setKnowledgeStatus('索引状态获取失败: ' + err.message, 'error');
                logCommand('KNOWLEDGE_INDEX_STATUS_ERROR', { message: err.message });
                setKnowledgeBusy(false);
            });
    }

    function runKnowledgeQuery(kind) {
        if (!knowledgeQueryInput) return;
        var query = knowledgeQueryInput.value.trim();
        if (!query) {
            setKnowledgeStatus('请先输入问题或关键词', 'error');
            knowledgeQueryInput.focus();
            return;
        }

        var isAsk = kind === 'ask';
        setKnowledgeBusy(true);
        setKnowledgeStatus(isAsk ? '知识库问答中' : '知识库检索中', 'running');
        var topK = getKnowledgeTopK();
        var minScore = getKnowledgeMinScore();
        requestJson(isAsk ? '/knowledge/ask' : '/knowledge/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(
                isAsk
                    ? { question: query, topK: topK }
                    : { query: query, topK: topK, minScore: minScore }
            )
        })
            .then(function (data) {
                setKnowledgeStatus(isAsk ? '问答完成' : '检索完成', '');
                showKnowledgeResult(data.data || {});
                logCommand(isAsk ? 'KNOWLEDGE_ASK_DONE' : 'KNOWLEDGE_SEARCH_DONE', {
                    query: query,
                    topK: topK,
                    minScore: isAsk ? undefined : minScore
                });
            })
            .catch(function (err) {
                setKnowledgeStatus((isAsk ? '问答失败: ' : '检索失败: ') + err.message, 'error');
                logCommand(isAsk ? 'KNOWLEDGE_ASK_ERROR' : 'KNOWLEDGE_SEARCH_ERROR', { message: err.message });
            })
            .finally(function () {
                setKnowledgeBusy(false);
            });
    }

    function loadKnowledgeDocuments() {
        return requestJson('/api/v1/tenant-admin/knowledge-documents')
            .then(function (data) {
                knowledgeDocuments = Array.isArray(data.data) ? data.data : [];
                renderKnowledgeDocuments();
                return knowledgeDocuments;
            })
            .catch(function (err) {
                knowledgeDocuments = [];
                renderKnowledgeDocuments(err.message);
                logCommand('KNOWLEDGE_DOCUMENT_LIST_ERROR', { message: err.message });
                return [];
            });
    }

    function renderKnowledgeDocuments(errorMessage) {
        if (metricDocumentCount) metricDocumentCount.textContent = errorMessage ? '!' : String(knowledgeDocuments.length);
        if (!knowledgeDocumentList) return;
        updateKnowledgeDocumentToggle(errorMessage);
        knowledgeDocumentList.innerHTML = '';
        if (errorMessage || !knowledgeDocuments.length) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = errorMessage ? '文档读取失败：' + errorMessage : '尚未上传企业文档';
            knowledgeDocumentList.appendChild(empty);
            knowledgeDocumentList.hidden = false;
            return;
        }
        knowledgeDocumentList.hidden = !knowledgeDocumentsExpanded;
        knowledgeDocuments.forEach(function (documentInfo) {
            var row = document.createElement('article');
            row.className = 'document-row';
            var extension = document.createElement('span');
            extension.className = 'document-extension';
            extension.textContent = String(documentInfo.extension || 'FILE').replace('.', '').toUpperCase();
            var info = document.createElement('div');
            var title = document.createElement('strong');
            title.textContent = documentInfo.name || documentInfo.relativePath;
            var meta = document.createElement('span');
            meta.textContent = formatBytes(documentInfo.size) + ' · ' + formatDateTime(Number(documentInfo.modifiedAt || 0) * 1000);
            info.appendChild(title);
            info.appendChild(meta);
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'danger-link';
            remove.textContent = '删除';
            remove.addEventListener('click', function () { deleteKnowledgeDocument(documentInfo, remove); });
            row.appendChild(extension);
            row.appendChild(info);
            row.appendChild(remove);
            knowledgeDocumentList.appendChild(row);
        });
    }

    function updateKnowledgeDocumentToggle(errorMessage) {
        if (!knowledgeDocumentToggle) return;
        var hasDocuments = knowledgeDocuments.length > 0;
        knowledgeDocumentToggle.hidden = Boolean(errorMessage) || !hasDocuments;
        knowledgeDocumentToggle.disabled = !hasDocuments;
        knowledgeDocumentToggle.setAttribute('aria-expanded', knowledgeDocumentsExpanded ? 'true' : 'false');
        knowledgeDocumentToggle.classList.toggle('expanded', knowledgeDocumentsExpanded);
        if (knowledgeDocumentToggleText) {
            knowledgeDocumentToggleText.textContent = knowledgeDocumentsExpanded
                ? '收起 ' + knowledgeDocuments.length + ' 个文档'
                : '展开 ' + knowledgeDocuments.length + ' 个文档';
        }
    }

    function uploadKnowledgeDocuments() {
        var files = knowledgeDocumentInput && knowledgeDocumentInput.files;
        if (!files || !files.length) {
            setKnowledgeDocumentStatus('请先选择企业文档', 'error');
            return;
        }
        var formData = new FormData();
        Array.prototype.forEach.call(files, function (file) { formData.append('files', file, file.name); });
        setKnowledgeDocumentBusy(true);
        setKnowledgeDocumentStatus('正在上传 ' + files.length + ' 个文档', 'running');
        requestJson('/api/v1/tenant-admin/knowledge-documents', { method: 'POST', body: formData })
            .then(function (data) {
                setKnowledgeDocumentStatus('上传完成，正在自动更新知识索引', 'ok');
                logCommand('KNOWLEDGE_DOCUMENT_UPLOAD', { count: (data.data || []).length });
                knowledgeDocumentInput.value = '';
                return loadKnowledgeDocuments().then(function () {
                    return autoUpdateKnowledgeIndex('document_upload');
                });
            })
            .catch(function (err) {
                setKnowledgeDocumentStatus('上传失败：' + err.message, 'error');
                logCommand('KNOWLEDGE_DOCUMENT_UPLOAD_ERROR', { message: err.message });
            })
            .finally(function () { setKnowledgeDocumentBusy(false); });
    }

    function deleteKnowledgeDocument(documentInfo, button) {
        if (!window.confirm('确认删除企业文档“' + documentInfo.name + '”吗？删除后需要重建索引。')) return;
        button.disabled = true;
        requestJson(
            '/api/v1/tenant-admin/knowledge-documents/' + encodeURIComponent(documentInfo.relativePath),
            { method: 'DELETE' }
        )
            .then(function () {
                setKnowledgeDocumentStatus('文档已删除，正在自动更新知识索引', 'ok');
                logCommand('KNOWLEDGE_DOCUMENT_DELETE', { path: documentInfo.relativePath });
                return loadKnowledgeDocuments().then(function () {
                    return autoUpdateKnowledgeIndex('document_delete');
                });
            })
            .catch(function (err) {
                setKnowledgeDocumentStatus('删除失败：' + err.message, 'error');
                button.disabled = false;
            });
    }

    function setupKnowledgeDocuments() {
        if (knowledgeDocumentInput) {
            knowledgeDocumentInput.addEventListener('change', function () {
                var count = knowledgeDocumentInput.files ? knowledgeDocumentInput.files.length : 0;
                setKnowledgeDocumentStatus(count ? '已选择 ' + count + ' 个文档' : '尚未选择文件', '');
            });
        }
        if (knowledgeDocumentUpload) knowledgeDocumentUpload.addEventListener('click', uploadKnowledgeDocuments);
        if (knowledgeDocumentToggle) {
            knowledgeDocumentToggle.addEventListener('click', function () {
                knowledgeDocumentsExpanded = !knowledgeDocumentsExpanded;
                renderKnowledgeDocuments();
            });
        }
        loadKnowledgeDocuments();
    }

    function setKnowledgeDocumentBusy(busy) {
        if (knowledgeDocumentInput) knowledgeDocumentInput.disabled = busy;
        if (knowledgeDocumentUpload) knowledgeDocumentUpload.disabled = busy;
    }

    function setKnowledgeDocumentStatus(message, state) {
        if (!knowledgeDocumentStatus) return;
        knowledgeDocumentStatus.textContent = message || '';
        knowledgeDocumentStatus.className = state || '';
    }

    function formatBytes(value) {
        var size = Math.max(0, Number(value) || 0);
        if (size < 1024) return size + ' B';
        if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB';
        return (size / 1024 / 1024).toFixed(1) + ' MB';
    }

    function setupKnowledgePanel() {
        if (knowledgeStatsButton) {
            knowledgeStatsButton.addEventListener('click', loadKnowledgeStats);
        }
        if (knowledgeIndexButton) {
            knowledgeIndexButton.addEventListener('click', rebuildKnowledgeIndex);
        }
        if (knowledgeSearchButton) {
            knowledgeSearchButton.addEventListener('click', function () { runKnowledgeQuery('search'); });
        }
        if (knowledgeAskButton) {
            knowledgeAskButton.addEventListener('click', function () { runKnowledgeQuery('ask'); });
        }
        if (knowledgeQueryInput) {
            knowledgeQueryInput.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    runKnowledgeQuery('ask');
                }
            });
        }
        pollKnowledgeIndexStatus();
        loadKnowledgeStats();
    }

    function connectWebSocket() {
        if (wsReconnectTimer) {
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = null;
        }

        var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = protocol + '//' + location.host;

        try {
            ws = new WebSocket(wsUrl);
        } catch (e) {
            logCommand('WS_ERROR', { message: e.message });
            scheduleReconnect();
            return;
        }

        ws.onopen = function () {
            logCommand('WS_OPEN', { message: 'WebSocket 已连接' });
            registerWebSocketClient('control');
            sendCommand('REQUEST_STATE');
        };

        ws.onmessage = function (event) {
            try {
                var msg = JSON.parse(event.data);
                if (msg.target === 'control' && msg.type === 'STATE_SYNC') {
                    handleStateSync(msg.payload || {});
                } else if (msg.type === 'interaction_mode_changed') {
                    interactionMode = msg.mode || interactionMode;
                    interactionModes = msg.modes || interactionModes;
                    buildInteractionModeSwitcher();
                    setModeSwitcherBusy(false);
                }
            } catch (e) {
                console.error('WS message parse error:', e);
            }
        };

        ws.onclose = function () {
            logCommand('WS_CLOSE', { message: 'WebSocket 断开' });
            updateConnectionStatus(false);
            scheduleReconnect();
        };

        ws.onerror = function (err) {
            logCommand('WS_ERROR', { message: 'WebSocket 连接失败' });
        };
    }

    function registerWebSocketClient(role) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({
            target: 'server',
            type: 'REGISTER',
            role: role,
            clientId: role + ':' + Date.now().toString(36) + ':' + Math.random().toString(36).slice(2, 8),
            path: location.pathname,
            ts: Date.now()
        }));
    }

    function scheduleReconnect() {
        if (wsReconnectTimer) return;
        wsReconnectTimer = setTimeout(function () {
            wsReconnectTimer = null;
            connectWebSocket();
        }, 3000);
    }

    function init() {
        setupControlTabs();
        setupControlLogout();
        updateConnectionStatus(false);
        loadControlIdentity()
            .then(function () {
                var platformAllowed = Boolean(
                    controlSession.capabilities && controlSession.capabilities.platformOperations
                );
                buildModelSwitcher();
                setupAvatarPersonaPanel();
                if (platformAllowed) {
                    loadInteractionModes();
                    pollGestureStatus();
                    setInterval(pollGestureStatus, 1000);
                    setupDailyTts();
                }
                setupFaceCapture();
                setupEmployeeFacePanel();
                setupKnowledgePanel();
                setupKnowledgeDocuments();
                loadTenantDevices();
                connectWebSocket();

                setInterval(function () {
                    if (ws && ws.readyState === WebSocket.OPEN) sendCommand('PING');
                }, 5000);

                logCommand('CONTROL_INIT', {
                    message: '租户控制台已启动',
                    tenantId: controlSession.tenantId,
                    channel: 'WebSocket',
                    protocol: location.protocol,
                    origin: location.origin
                });
            })
            .catch(function (err) {
                if (tenantScopeTitle) tenantScopeTitle.textContent = '控制台暂不可用';
                if (tenantScopeId) tenantScopeId.textContent = err.message || '会话读取失败';
            });
    }

    init();
})();
