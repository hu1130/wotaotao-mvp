const test = require('node:test');
const assert = require('node:assert/strict');

const {
    TenantAvatarStateStore,
    resolveWsRoleBinding,
    shouldDeliverBroadcastToRole
} = require('../tenant_state');

test('audio locks are isolated by trusted tenant binding', () => {
    const store = new TenantAvatarStateStore();
    const deviceA = { tenantId: 'tenant-a', deviceId: 'frontdesk-a' };
    const deviceB = { tenantId: 'tenant-b', deviceId: 'frontdesk-b' };
    store.updateAudioLock(deviceA, { active: true, holdMs: 5000, owner: 'voice' }, 1000);

    assert.equal(store.getAudioLock(deviceA, 2000).active, true);
    assert.equal(store.getAudioLock(deviceB, 2000).active, false);
    assert.equal(
        store.getAudioLock({ tenantId: 'tenant-a', deviceId: 'frontdesk-2' }, 2000).active,
        false
    );
});

test('avatar ready state is isolated by tenant', () => {
    const store = new TenantAvatarStateStore();
    const deviceA = { tenantId: 'tenant-a', deviceId: 'frontdesk-a' };
    const deviceB = { tenantId: 'tenant-b', deviceId: 'frontdesk-b' };
    store.updateReadyState(deviceA, { model: 'epsilon', label: 'A' }, new Date(0));

    assert.equal(store.getReadyState(deviceA).model, 'epsilon');
    assert.equal(store.getReadyState(deviceB).ready, false);
    assert.equal(store.getReadyState(deviceB).model, '');
});

test('websocket roles cannot fall back to a default tenant', () => {
    assert.throws(
        () => resolveWsRoleBinding('avatar', null, null),
        /avatar device session required/
    );
    assert.throws(
        () => resolveWsRoleBinding('control', null, null),
        /tenant administrator session required/
    );
    assert.throws(
        () => resolveWsRoleBinding('unknown', { tenantId: 'a' }, null),
        /registered websocket role is required/
    );
    assert.equal(
        resolveWsRoleBinding('avatar', { tenantId: 'a' }, null).tenantId,
        'a'
    );
});

test('event broadcasts only reach active avatar client and controls', () => {
    assert.equal(
        shouldDeliverBroadcastToRole(
            { role: 'avatar', tenantId: 'tenant-a', authPending: false },
            'tenant-a',
            true
        ),
        true
    );
    assert.equal(
        shouldDeliverBroadcastToRole(
            { role: 'avatar', tenantId: 'tenant-a', authPending: false },
            'tenant-a',
            false
        ),
        false
    );
    assert.equal(
        shouldDeliverBroadcastToRole(
            { role: 'control', tenantId: 'tenant-a', authPending: false },
            'tenant-a',
            false
        ),
        true
    );
    assert.equal(
        shouldDeliverBroadcastToRole(
            { role: 'avatar', tenantId: 'tenant-b', authPending: false },
            'tenant-a',
            true
        ),
        false
    );
});
