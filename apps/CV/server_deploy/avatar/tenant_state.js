'use strict';

const DEFAULT_READY_STATE = Object.freeze({
    ready: false,
    model: '',
    label: '',
    voice: '',
    handoffText: '',
    at: ''
});

function requireDeviceScope(binding) {
    const tenantId = String((binding && binding.tenantId) || '').trim();
    const deviceId = String((binding && binding.deviceId) || '').trim();
    if (!tenantId) throw new Error('trusted tenant binding is required');
    if (!deviceId) throw new Error('trusted device binding is required');
    return `${tenantId}\u0000${deviceId}`;
}

class TenantAvatarStateStore {
    constructor(maxHoldMs = 180000) {
        this.maxHoldMs = Math.max(0, Number(maxHoldMs) || 180000);
        this.audioLocks = new Map();
        this.readyStates = new Map();
    }

    getAudioLock(binding, now = Date.now()) {
        const scope = requireDeviceScope(binding);
        const state = this.audioLocks.get(scope) || {
            owner: '',
            owners: new Map(),
            updatedAt: 0
        };
        let lockedUntil = 0;
        const activeOwners = [];
        for (const [owner, untilValue] of state.owners.entries()) {
            const until = Number(untilValue) || 0;
            if (until > now) {
                activeOwners.push(owner);
                lockedUntil = Math.max(lockedUntil, until);
            } else {
                state.owners.delete(owner);
            }
        }
        state.owner = activeOwners[activeOwners.length - 1] || state.owner || '';
        if (state.owners.size || state.updatedAt) this.audioLocks.set(scope, state);
        return {
            active: lockedUntil > now,
            lockedUntil,
            owner: state.owner,
            owners: activeOwners,
            updatedAt: state.updatedAt
        };
    }

    updateAudioLock(binding, update, now = Date.now()) {
        const scope = requireDeviceScope(binding);
        const state = this.audioLocks.get(scope) || {
            owner: '',
            owners: new Map(),
            updatedAt: 0
        };
        const owner = String((update && update.owner) || 'local_dialog').slice(0, 64);
        const active = Boolean(update && update.active);
        const holdMs = Math.max(
            0,
            Math.min(this.maxHoldMs, Number(update && update.holdMs) || 0)
        );
        const currentUntil = Number(state.owners.get(owner)) || 0;
        if (active) {
            state.owners.set(owner, Math.max(currentUntil, now + holdMs));
        } else if (holdMs > 0) {
            state.owners.set(owner, now + holdMs);
        } else {
            state.owners.delete(owner);
        }
        state.owner = owner;
        state.updatedAt = now;
        this.audioLocks.set(scope, state);
        return this.getAudioLock(binding, now);
    }

    getReadyState(binding) {
        const scope = requireDeviceScope(binding);
        return { ...(this.readyStates.get(scope) || DEFAULT_READY_STATE) };
    }

    updateReadyState(binding, payload, now = new Date()) {
        const scope = requireDeviceScope(binding);
        const state = {
            ready: payload && Object.prototype.hasOwnProperty.call(payload, 'ready')
                ? Boolean(payload.ready)
                : true,
            model: String((payload && payload.model) || ''),
            label: String((payload && payload.label) || ''),
            voice: String((payload && payload.voice) || ''),
            handoffText: String((payload && payload.handoffText) || ''),
            at: now.toISOString()
        };
        this.readyStates.set(scope, state);
        return { ...state };
    }
}

function resolveWsRoleBinding(role, avatarBinding, controlBinding, controlAuthEnabled = true) {
    if (role === 'avatar') {
        if (!avatarBinding) throw new Error('avatar device session required');
        return avatarBinding;
    }
    if (role === 'control') {
        if (controlAuthEnabled && !controlBinding) {
            throw new Error('tenant administrator session required');
        }
        if (!controlBinding) throw new Error('control tenant binding required');
        return controlBinding;
    }
    throw new Error('registered websocket role is required');
}

function shouldDeliverBroadcastToRole(meta, tenantId, isActiveAvatar) {
    if (!meta || meta.authPending) return false;
    if (String(meta.tenantId || '') !== String(tenantId || '')) return false;
    if (meta.role === 'control') return true;
    if (meta.role === 'avatar') return Boolean(isActiveAvatar);
    return false;
}

module.exports = {
    TenantAvatarStateStore,
    resolveWsRoleBinding,
    shouldDeliverBroadcastToRole
};
