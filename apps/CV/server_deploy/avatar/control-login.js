(function () {
    'use strict';

    var form = document.getElementById('control-login-form');
    var tenantInput = document.getElementById('control-login-tenant');
    var usernameInput = document.getElementById('control-login-username');
    var passwordInput = document.getElementById('control-login-password');
    var submitButton = document.getElementById('control-login-button');
    var statusEl = document.getElementById('control-login-status');

    function nextUrl() {
        var params = new URLSearchParams(window.location.search);
        var next = params.get('next') || '/control.html';
        if (!next.startsWith('/') || next.startsWith('//')) {
            return '/control.html';
        }
        return next;
    }

    function setStatus(message, kind) {
        if (!statusEl) return;
        statusEl.textContent = message || '';
        statusEl.className = kind || '';
    }

    function setBusy(busy) {
        if (submitButton) {
            submitButton.disabled = busy;
            submitButton.textContent = busy ? '登录中' : '登录控制台';
        }
    }

    function formatLoginError(data, status) {
        if (status === 429) {
            var seconds = Number(data && data.retryAfterSeconds) || 0;
            return seconds > 0
                ? '密码错误次数过多，请 ' + seconds + ' 秒后再试'
                : '密码错误次数过多，请稍后再试';
        }
        if (data && data.attempts && data.maxAttempts) {
            return '账号或密码不正确，已失败 ' + data.attempts + '/' + data.maxAttempts + ' 次';
        }
        return '租户 ID、账号或密码不正确';
    }

    function submitLogin(event) {
        event.preventDefault();
        var tenantId = tenantInput ? tenantInput.value.trim() : '';
        var username = usernameInput ? usernameInput.value.trim() : '';
        var password = passwordInput ? passwordInput.value : '';
        if (!tenantId || !username || !password) {
            setStatus('请输入租户 ID、用户名和密码', 'error');
            return;
        }

        setBusy(true);
        setStatus('正在验证', '');
        fetch('/control-auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tenantId: tenantId, username: username, password: password })
        })
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    if (!res.ok || data.ok === false) {
                        throw { data: data, status: res.status };
                    }
                    return data;
                });
            })
            .then(function () {
                try { window.localStorage.setItem('cv-control-tenant-id', tenantId); } catch (e) { /* ignore */ }
                setStatus('登录成功，正在进入控制台', 'ok');
                window.location.replace(nextUrl());
            })
            .catch(function (err) {
                setStatus(formatLoginError(err.data || {}, err.status), 'error');
                if (passwordInput) {
                    passwordInput.value = '';
                    passwordInput.focus();
                }
            })
            .finally(function () {
                setBusy(false);
            });
    }

    if (form) {
        form.addEventListener('submit', submitLogin);
    }
    if (tenantInput) {
        try { tenantInput.value = window.localStorage.getItem('cv-control-tenant-id') || 'default'; } catch (e) { tenantInput.value = 'default'; }
        tenantInput.focus();
    } else if (usernameInput) {
        usernameInput.focus();
    }
})();
