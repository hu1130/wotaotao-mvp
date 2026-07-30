(function () {
    'use strict';

    var state = {
        session: null,
        clients: [],
        selectedTenantId: '',
        details: {
            admins: [],
            activations: [],
            devices: []
        }
    };

    var statusEl = document.getElementById('page-status');
    var refreshButton = document.getElementById('refresh-button');
    var logoutButton = document.getElementById('logout-button');
    var createForm = document.getElementById('create-client-form');
    var filterInput = document.getElementById('client-filter');
    var clientTableBody = document.getElementById('client-table-body');
    var detailModal = document.getElementById('client-detail-modal');
    var detailCloseButton = document.getElementById('client-detail-close');
    var detailTitle = document.getElementById('detail-title');
    var adminList = document.getElementById('admin-list');
    var activationList = document.getElementById('activation-list');
    var deviceList = document.getElementById('device-list');
    var secretPanel = document.getElementById('secret-panel');
    var secretOutput = document.getElementById('secret-output');

    function setStatus(message, kind) {
        if (!statusEl) return;
        statusEl.textContent = message || '';
        statusEl.className = 'page-status' + (kind ? ' ' + kind : '');
    }

    function requestJson(url, options) {
        return fetch(url, options || {})
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    if (!res.ok || data.ok === false) {
                        var error = new Error(data.error || data.detail || '请求失败');
                        error.status = res.status;
                        throw error;
                    }
                    return data;
                });
            });
    }

    function h(value) {
        return String(value === null || value === undefined ? '' : value);
    }

    function formatDate(value) {
        if (!value) return '--';
        var date = new Date(value);
        if (Number.isNaN(date.getTime())) return h(value);
        return date.toLocaleString('zh-CN', { hour12: false });
    }

    function badge(text, kind) {
        var el = document.createElement('span');
        el.className = 'badge' + (kind ? ' ' + kind : '');
        el.textContent = text;
        return el;
    }

    function clear(el) {
        while (el && el.firstChild) el.removeChild(el.firstChild);
    }

    function setSession(session) {
        state.session = session;
        document.getElementById('platform-admin-name').textContent =
            session.displayName || session.username || '平台管理员';
        document.getElementById('platform-tenant-id').textContent = session.tenantId || '--';
    }

    function loadSession() {
        return requestJson('/control-auth/status')
            .then(function (data) {
                if (!data.authenticated || !data.session) {
                    window.location.replace('/control-login.html?next=' + encodeURIComponent(location.pathname));
                    return Promise.reject(new Error('authentication required'));
                }
                if (!data.session.capabilities || !data.session.capabilities.platformOperations) {
                    setStatus('当前账号不是超级管理员', 'error');
                    return Promise.reject(new Error('platform administrator required'));
                }
                setSession(data.session);
                return data.session;
            });
    }

    function loadClients() {
        setStatus('正在读取客户端', '');
        return requestJson('/platform-admin/clients')
            .then(function (data) {
                state.clients = Array.isArray(data.data) ? data.data : [];
                renderClients();
                renderMetrics();
                setStatus('已读取 ' + state.clients.length + ' 个客户端', 'ok');
            })
            .catch(function (err) {
                setStatus(err.message || '客户端读取失败', 'error');
            });
    }

    function renderMetrics() {
        var deviceCount = state.clients.reduce(function (sum, item) {
            return sum + (Number(item.activeDeviceCount) || 0);
        }, 0);
        var activationCount = state.clients.reduce(function (sum, item) {
            return sum + (Number(item.availableActivationCount) || 0);
        }, 0);
        document.getElementById('metric-client-count').textContent = String(state.clients.length);
        document.getElementById('metric-device-count').textContent = String(deviceCount);
        document.getElementById('metric-activation-count').textContent = String(activationCount);
    }

    function renderClients() {
        clear(clientTableBody);
        var filter = filterInput ? filterInput.value.trim().toLowerCase() : '';
        var clients = state.clients.filter(function (item) {
            return !filter
                || h(item.tenantId).toLowerCase().includes(filter)
                || h(item.tenantName).toLowerCase().includes(filter);
        });
        if (!clients.length) {
            var emptyRow = document.createElement('tr');
            var emptyCell = document.createElement('td');
            emptyCell.colSpan = 6;
            emptyCell.textContent = '暂无客户端';
            emptyRow.appendChild(emptyCell);
            clientTableBody.appendChild(emptyRow);
            return;
        }
        clients.forEach(function (item) {
            var tr = document.createElement('tr');
            var tenantCell = document.createElement('td');
            tenantCell.className = 'tenant-cell';
            var name = document.createElement('strong');
            name.textContent = item.tenantName || item.tenantId;
            var id = document.createElement('code');
            id.textContent = item.tenantId;
            tenantCell.append(name, id);
            tr.appendChild(tenantCell);
            appendTextCell(tr, (item.activeAdminCount || 0) + ' / ' + (item.adminCount || 0));
            appendTextCell(tr, (item.activeDeviceCount || 0) + ' / ' + (item.deviceCount || 0));
            appendTextCell(tr, (item.availableActivationCount || 0) + ' / ' + (item.activationCount || 0));
            appendTextCell(tr, formatDate(item.lastDeviceSeenAt));

            var actions = document.createElement('td');
            var actionWrap = document.createElement('div');
            actionWrap.className = 'row-actions';
            var selectButton = document.createElement('button');
            selectButton.type = 'button';
            selectButton.textContent = '查看';
            selectButton.addEventListener('click', function () { selectClient(item.tenantId); });
            var activationButton = document.createElement('button');
            activationButton.type = 'button';
            activationButton.textContent = '新增激活码';
            activationButton.addEventListener('click', function () { createActivation(item.tenantId); });
            var deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'danger-button';
            deleteButton.textContent = '删除';
            deleteButton.addEventListener('click', function () { deleteClient(item.tenantId); });
            actionWrap.append(selectButton, activationButton, deleteButton);
            actions.appendChild(actionWrap);
            tr.appendChild(actions);
            clientTableBody.appendChild(tr);
        });
    }

    function appendTextCell(row, text) {
        var td = document.createElement('td');
        td.textContent = h(text);
        row.appendChild(td);
    }

    function openDetailModal() {
        if (!detailModal) return;
        detailModal.hidden = false;
        document.body.classList.add('modal-open');
    }

    function closeDetailModal() {
        if (!detailModal) return;
        detailModal.hidden = true;
        document.body.classList.remove('modal-open');
    }

    function selectClient(tenantId) {
        state.selectedTenantId = tenantId;
        if (detailTitle) detailTitle.textContent = '客户端详情 · ' + tenantId;
        openDetailModal();
        setStatus('正在读取 ' + tenantId + ' 详情', '');
        return Promise.all([
            requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId) + '/admins'),
            requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId) + '/activations'),
            requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId) + '/devices')
        ])
            .then(function (results) {
                state.details.admins = Array.isArray(results[0].data) ? results[0].data : [];
                state.details.activations = Array.isArray(results[1].data) ? results[1].data : [];
                state.details.devices = Array.isArray(results[2].data) ? results[2].data : [];
                renderDetails();
                setStatus('详情已更新', 'ok');
            })
            .catch(function (err) {
                setStatus(err.message || '详情读取失败', 'error');
            });
    }

    function renderDetails() {
        renderAdmins();
        renderActivations();
        renderDevices();
    }

    function renderAdmins() {
        clear(adminList);
        if (!state.details.admins.length) {
            appendEmpty(adminList, '暂无管理员');
            return;
        }
        state.details.admins.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'list-item';
            var title = document.createElement('strong');
            title.textContent = item.displayName || item.username;
            var meta = document.createElement('div');
            meta.className = 'list-meta';
            meta.append(
                textSpan('用户名 ' + item.username),
                textSpan('登录 ' + formatDate(item.lastLoginAt)),
                badge(item.status === 'active' ? '启用' : '停用', item.status === 'active' ? '' : 'danger')
            );
            var actions = document.createElement('div');
            actions.className = 'row-actions';
            var resetButton = document.createElement('button');
            resetButton.type = 'button';
            resetButton.textContent = '重置密码';
            resetButton.addEventListener('click', function () {
                resetPassword(state.selectedTenantId, item.username);
            });
            actions.appendChild(resetButton);
            card.append(title, meta, actions);
            adminList.appendChild(card);
        });
    }

    function renderActivations() {
        clear(activationList);
        if (!state.details.activations.length) {
            appendEmpty(activationList, '暂无激活码');
            return;
        }
        state.details.activations.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'list-item';
            card.title = '右键删除该激活码';
            card.addEventListener('contextmenu', function (event) {
                event.preventDefault();
                deleteActivation(item);
            });
            var title = document.createElement('strong');
            title.textContent = item.label || '未命名激活码';
            var claimed = Boolean(item.claimedAt);
            var expired = item.expiresAt && new Date(item.expiresAt).getTime() <= Date.now();
            var meta = document.createElement('div');
            meta.className = 'list-meta';
            meta.append(
                textSpan('前缀 ' + item.codePrefix),
                textSpan('到期 ' + formatDate(item.expiresAt)),
                claimed ? textSpan('设备 ' + item.claimedDeviceId) : textSpan('未使用'),
                badge(claimed ? '已使用' : expired ? '已过期' : '可用', claimed || expired ? 'warn' : '')
            );
            card.append(title, meta);
            if (!claimed && item.activationCode) {
                card.appendChild(createActivationCodeViewer(item.activationCode));
            } else if (!claimed) {
                var unavailable = document.createElement('div');
                unavailable.className = 'activation-unavailable';
                unavailable.textContent = '完整码仅对新建未使用激活码可见';
                card.appendChild(unavailable);
            }
            activationList.appendChild(card);
        });
    }

    function deleteActivation(item) {
        if (!item || !item.activationId || !state.selectedTenantId) return;
        var label = item.label || item.codePrefix || item.activationId;
        if (!window.confirm('是否删除该激活码？\n' + label)) return;
        setStatus('正在删除激活码', '');
        requestJson(
            '/platform-admin/clients/'
            + encodeURIComponent(state.selectedTenantId)
            + '/activations/'
            + encodeURIComponent(item.activationId),
            { method: 'DELETE' }
        )
            .then(function () {
                setStatus('激活码已删除', 'ok');
                return Promise.all([loadClients(), selectClient(state.selectedTenantId)]);
            })
            .catch(function (err) {
                setStatus(err.message || '激活码删除失败', 'error');
            });
    }

    function maskActivationCode(value) {
        var text = h(value);
        if (text.length <= 10) return text;
        return text.slice(0, 6) + '••••••••••' + text.slice(-4);
    }

    function createActivationCodeViewer(activationCode) {
        var row = document.createElement('div');
        row.className = 'activation-secret';

        var code = document.createElement('code');
        code.textContent = maskActivationCode(activationCode);

        var revealButton = document.createElement('button');
        revealButton.type = 'button';
        revealButton.className = 'icon-button eye-button';
        revealButton.title = '查看完整激活码';
        revealButton.setAttribute('aria-label', '查看完整激活码');
        revealButton.appendChild(createEyeIcon());
        revealButton.addEventListener('click', function () {
            var revealing = row.dataset.revealed !== 'true';
            row.dataset.revealed = revealing ? 'true' : 'false';
            code.textContent = revealing ? activationCode : maskActivationCode(activationCode);
            revealButton.title = revealing ? '隐藏完整激活码' : '查看完整激活码';
            revealButton.setAttribute('aria-label', revealButton.title);
        });

        var copyButton = document.createElement('button');
        copyButton.type = 'button';
        copyButton.textContent = '复制';
        copyButton.addEventListener('click', function () {
            copyText(activationCode)
                .then(function () { setStatus('激活码已复制', 'ok'); })
                .catch(function (err) { setStatus(err.message || '复制失败', 'error'); });
        });

        row.append(code, revealButton, copyButton);
        return row;
    }

    function createEyeIcon() {
        var icon = document.createElement('span');
        icon.className = 'eye-icon';
        icon.setAttribute('aria-hidden', 'true');
        return icon;
    }

    function copyText(value) {
        var text = h(value);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var input = document.createElement('textarea');
            input.value = text;
            input.setAttribute('readonly', 'readonly');
            input.style.position = 'fixed';
            input.style.left = '-9999px';
            document.body.appendChild(input);
            input.select();
            try {
                if (!document.execCommand('copy')) {
                    throw new Error('浏览器拒绝复制');
                }
                resolve();
            } catch (err) {
                reject(err);
            } finally {
                document.body.removeChild(input);
            }
        });
    }

    function renderDevices() {
        clear(deviceList);
        if (!state.details.devices.length) {
            appendEmpty(deviceList, '暂无注册机器');
            return;
        }
        state.details.devices.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'list-item';
            var title = document.createElement('strong');
            title.textContent = item.displayName || item.deviceId;
            var meta = document.createElement('div');
            meta.className = 'list-meta';
            meta.append(
                textSpan(item.deviceId),
                textSpan('安装 ' + item.installationId),
                textSpan('在线 ' + formatDate(item.lastSeenAt)),
                badge(item.status === 'active' ? '启用' : '停用', item.status === 'active' ? '' : 'danger')
            );
            var actions = document.createElement('div');
            actions.className = 'row-actions';
            var nextStatus = item.status === 'active' ? 'revoked' : 'active';
            var statusButton = document.createElement('button');
            statusButton.type = 'button';
            statusButton.textContent = nextStatus === 'revoked' ? '停用' : '启用';
            statusButton.addEventListener('click', function () {
                setDeviceStatus(item.deviceId, nextStatus);
            });
            var deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'danger-button';
            deleteButton.textContent = '删除机器';
            deleteButton.addEventListener('click', function () { deleteDevice(item.deviceId); });
            actions.append(statusButton, deleteButton);
            card.append(title, meta, actions);
            deviceList.appendChild(card);
        });
    }

    function textSpan(text) {
        var span = document.createElement('span');
        span.textContent = text;
        return span;
    }

    function appendEmpty(parent, text) {
        var empty = document.createElement('div');
        empty.className = 'list-item muted';
        empty.textContent = text;
        parent.appendChild(empty);
    }

    function showSecrets(values) {
        clear(secretOutput);
        Object.keys(values).forEach(function (label) {
            var value = values[label];
            if (!value) return;
            var row = document.createElement('div');
            var dt = document.createElement('dt');
            var dd = document.createElement('dd');
            dt.textContent = label;
            dd.textContent = value;
            row.append(dt, dd);
            secretOutput.appendChild(row);
        });
        if (secretPanel) secretPanel.hidden = !secretOutput.children.length;
    }

    function handleCreateClient(event) {
        event.preventDefault();
        var payload = {
            tenantId: document.getElementById('new-tenant-id').value.trim(),
            tenantName: document.getElementById('new-tenant-name').value.trim(),
            username: document.getElementById('new-admin-username').value.trim(),
            displayName: document.getElementById('new-admin-display-name').value.trim(),
            deviceLabel: document.getElementById('new-device-label').value.trim(),
            ttlHours: Number(document.getElementById('new-ttl-hours').value) || 24,
            resetExistingPassword: document.getElementById('new-reset-existing').checked
        };
        if (!payload.tenantId || !payload.username) {
            setStatus('租户 ID 和管理员用户名不能为空', 'error');
            return;
        }
        setStatus('正在创建客户端', '');
        requestJson('/platform-admin/clients', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (data) {
                var result = data.data || {};
                var consoleInfo = result.console || {};
                var activation = result.activation || {};
                showSecrets({
                    '租户 ID': result.tenantId,
                    '管理员用户名': consoleInfo.username,
                    '管理员密码': consoleInfo.password,
                    '设备激活码': activation.activationCode
                });
                state.selectedTenantId = result.tenantId || payload.tenantId;
                return loadClients();
            })
            .then(function () {
                if (state.selectedTenantId) selectClient(state.selectedTenantId);
            })
            .catch(function (err) {
                setStatus(err.message || '客户端创建失败', 'error');
            });
    }

    function resetPassword(tenantId, username) {
        if (!tenantId || !username) return;
        if (!window.confirm('确认重置 ' + tenantId + ' / ' + username + ' 的控制台密码？')) return;
        setStatus('正在重置密码', '');
        requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId) + '/admins/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username })
        })
            .then(function (data) {
                var result = data.data || {};
                showSecrets({
                    '租户 ID': result.tenantId,
                    '管理员用户名': result.username,
                    '管理员新密码': result.newPassword
                });
                setStatus('密码已重置', 'ok');
                return selectClient(tenantId);
            })
            .catch(function (err) { setStatus(err.message || '密码重置失败', 'error'); });
    }

    function createActivation(tenantId) {
        tenantId = tenantId || state.selectedTenantId;
        if (!tenantId) return;
        var label = window.prompt('激活码标签', tenantId + '前台');
        if (label === null) return;
        setStatus('正在生成新激活码', '');
        requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId) + '/activations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: label, ttlHours: 24 })
        })
            .then(function (data) {
                var result = data.data || {};
                showSecrets({
                    '租户 ID': result.tenantId,
                    '设备激活码': result.activationCode,
                    '激活码前缀': result.codePrefix
                });
                setStatus('新激活码已生成', 'ok');
                return Promise.all([loadClients(), selectClient(tenantId)]);
            })
            .catch(function (err) { setStatus(err.message || '激活码生成失败', 'error'); });
    }

    function setDeviceStatus(deviceId, status) {
        if (!window.confirm('确认' + (status === 'revoked' ? '停用' : '启用') + '设备 ' + deviceId + '？')) return;
        requestJson('/platform-admin/devices/' + encodeURIComponent(deviceId) + '/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status })
        })
            .then(function () {
                setStatus('设备状态已更新', 'ok');
                return Promise.all([loadClients(), selectClient(state.selectedTenantId)]);
            })
            .catch(function (err) { setStatus(err.message || '设备状态更新失败', 'error'); });
    }

    function deleteDevice(deviceId) {
        var confirmDeviceId = window.prompt('输入完整设备 ID 以确认删除', '');
        if (confirmDeviceId !== deviceId) {
            if (confirmDeviceId !== null) setStatus('设备确认值不匹配', 'error');
            return;
        }
        requestJson('/platform-admin/devices/' + encodeURIComponent(deviceId), {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmDeviceId: confirmDeviceId })
        })
            .then(function () {
                setStatus('注册机器已删除', 'ok');
                return Promise.all([loadClients(), selectClient(state.selectedTenantId)]);
            })
            .catch(function (err) { setStatus(err.message || '注册机器删除失败', 'error'); });
    }

    function deleteClient(tenantId) {
        tenantId = tenantId || state.selectedTenantId;
        if (!tenantId) return;
        var confirmTenantId = window.prompt('输入完整租户 ID 以确认删除客户端控制面数据', '');
        if (confirmTenantId !== tenantId) {
            if (confirmTenantId !== null) setStatus('租户确认值不匹配', 'error');
            return;
        }
        requestJson('/platform-admin/clients/' + encodeURIComponent(tenantId), {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmTenantId: confirmTenantId, disableConsoleAdmins: true })
        })
            .then(function (data) {
                var result = data.data || {};
                showSecrets({
                    '已删除激活码': String(result.activationCodesDeleted || 0),
                    '已删除注册机器': String(result.devicesDeleted || 0),
                    '已清理会话': String(result.redisSessionsDeleted || 0),
                    '已停用管理员': String(result.consoleAdminsDisabled || 0)
                });
                state.selectedTenantId = '';
                closeDetailModal();
                return loadClients();
            })
            .catch(function (err) { setStatus(err.message || '客户端删除失败', 'error'); });
    }

    function logout() {
        requestJson('/control-auth/logout', { method: 'POST' })
            .finally(function () {
                window.location.replace('/control-login.html');
            });
    }

    if (refreshButton) refreshButton.addEventListener('click', loadClients);
    if (logoutButton) logoutButton.addEventListener('click', logout);
    if (createForm) createForm.addEventListener('submit', handleCreateClient);
    if (filterInput) filterInput.addEventListener('input', renderClients);
    if (detailCloseButton) detailCloseButton.addEventListener('click', closeDetailModal);
    if (detailModal) {
        detailModal.addEventListener('click', function (event) {
            if (event.target === detailModal) closeDetailModal();
        });
    }
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && detailModal && !detailModal.hidden) {
            closeDetailModal();
        }
    });

    loadSession()
        .then(loadClients)
        .catch(function (err) {
            if (err.message !== 'authentication required') {
                console.warn(err.message || err);
            }
        });
})();
