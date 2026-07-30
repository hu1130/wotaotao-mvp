import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as THREE from 'three';
import './styles.css';

const STATUS_COPY = {
    listening: 'Listening to visitor intent',
    speaking: 'Listening to visitor intent',
    idle: 'Listening to visitor intent'
};

function App() {
    const [mode, setMode] = useState('listening');
    const [muted, setMuted] = useState(false);
    const visualStateRef = useRef({ mode: 'listening', muted: false });

    useEffect(() => {
        visualStateRef.current = { mode, muted };
    }, [mode, muted]);

    return (
        <main className="frontdesk-stage" data-mode={mode} data-muted={muted ? 'true' : 'false'}>
            <header className="topbar">
                <a className="brand" href="/" aria-label="返回数字人页面">
                    <span className="brand-mark" aria-hidden="true" />
                    <span>Logo</span>
                </a>
                <nav className="nav-links" aria-label="展示页导航">
                    <a href="/" title="返回数字人">Avatar</a>
                    <a className="active" href="/speech-showcase.html">Features</a>
                    <a href="/control.html">History</a>
                </nav>
                <button className="profile-button" type="button" aria-label="用户资料" />
            </header>

            <section className="hero-shell" aria-label="企业数字人前台展示">
                <div className="ambient-room" aria-hidden="true">
                    <span className="ceiling-ring" />
                    <span className="floor-wash" />
                    <span className="lounge-shadow" />
                    <span className="light-veil" />
                </div>
                <div className="glass-grid" aria-hidden="true" />
                <ThreeShowcase visualStateRef={visualStateRef} />

                <div className="title-wrap">
                    <p className="eyebrow">Enterprise AI Reception Hall</p>
                    <h1>AI Frontdesk</h1>
                    <div className="voice-caption" aria-live="polite">
                        <span className="caption-dot" />
                        <span>{STATUS_COPY[mode]}</span>
                    </div>
                </div>

                <div className="capability-strip" aria-label="AI 能力展示">
                    <span>访客识别</span>
                    <span>实时语音</span>
                    <span>企业知识库</span>
                    <span>业务引导</span>
                </div>
            </section>

            <footer className="call-console" aria-label="语音控制台">
                <button
                    className="soft-control"
                    type="button"
                    aria-pressed={muted}
                    onClick={() => setMuted((value) => !value)}
                >
                    <span className="mute-icon" aria-hidden="true" />
                    <span>Mute</span>
                </button>
                <Meter />
                <button
                    className="mic-button"
                    type="button"
                    aria-label="切换语音展示状态"
                    onClick={() => setMode((value) => (value === 'listening' ? 'speaking' : 'listening'))}
                >
                    <span aria-hidden="true" />
                </button>
                <Meter tone="berry" />
                <button className="end-call" type="button" onClick={() => setMode('idle')}>
                    <span className="phone-icon" aria-hidden="true" />
                    <span>End Call</span>
                </button>
                <div className="live-time" aria-label="当前展示状态">00:15 / Live</div>
            </footer>
        </main>
    );
}

function Meter({ tone = 'gold' }) {
    return (
        <div className={`center-meter ${tone}`} aria-hidden="true">
            <span /><span /><span /><span /><span />
        </div>
    );
}

function ThreeShowcase({ visualStateRef }) {
    const mountRef = useRef(null);

    useEffect(() => {
        if (!mountRef.current) return undefined;
        return createThreeScene(mountRef.current, visualStateRef);
    }, [visualStateRef]);

    return <div ref={mountRef} className="three-stage" aria-hidden="true" />;
}

function createThreeScene(mount, visualStateRef) {
    const prefersReducedMotion = window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
        preserveDrawingBuffer: true
    });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 80);
    camera.position.set(0, 0.15, 13.2);

    const root = new THREE.Group();
    scene.add(root);

    scene.add(new THREE.AmbientLight(0xffe5dc, 1.4));
    const keyLight = new THREE.PointLight(0xffcdbb, 4.8, 24);
    keyLight.position.set(-4, 2.8, 6);
    scene.add(keyLight);
    const rimLight = new THREE.PointLight(0xff4ca4, 3.4, 20);
    rimLight.position.set(5, 1.5, 5);
    scene.add(rimLight);

    const orb = createEnergyOrb();
    root.add(orb.group);

    const waves = createFluidSoundWaves();
    root.add(waves.group);
    const tendrils = createGooeyTendrils();
    root.add(tendrils.group);

    const halo = createHaloField();
    root.add(halo.group);
    const particles = createParticleField();
    root.add(particles.points);

    const pointer = { x: 0, y: 0 };
    const handlePointer = (event) => {
        const rect = mount.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width) - 0.5) * 2;
        pointer.y = ((event.clientY - rect.top) / Math.max(1, rect.height) - 0.5) * -2;
    };
    window.addEventListener('pointermove', handlePointer);

    function resize() {
        const rect = mount.getBoundingClientRect();
        const width = Math.max(1, rect.width);
        const height = Math.max(1, rect.height);
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        root.scale.setScalar(width < 620 ? 0.66 : 1);
        root.position.y = width < 620 ? -0.35 : -0.2;
    }

    let frameId = 0;
    const clock = new THREE.Clock();

    function animate() {
        const elapsed = clock.getElapsedTime();
        const state = visualStateRef.current || {};
        const active = state.mode === 'listening' || state.mode === 'speaking';
        const voicePower = state.muted ? 0.18 : state.mode === 'speaking' ? 1.25 : active ? 0.82 : 0.36;
        const pulse = 1 + Math.sin(elapsed * 1.45) * 0.035 * voicePower;

        root.rotation.y += (pointer.x * 0.055 - root.rotation.y) * 0.045;
        root.rotation.x += (pointer.y * 0.035 - root.rotation.x) * 0.045;

        orb.group.scale.setScalar(pulse);
        orb.inner.material.uniforms.uTime.value = elapsed;
        orb.inner.material.uniforms.uPower.value = voicePower;
        orb.blobs.children.forEach((blob, index) => {
            const meta = blob.userData;
            const phase = elapsed * meta.speed + meta.phase;
            blob.position.set(
                meta.origin.x + Math.sin(phase) * meta.drift.x * voicePower,
                meta.origin.y + Math.cos(phase * 0.86) * meta.drift.y * voicePower,
                meta.origin.z + Math.sin(phase * 0.7) * meta.drift.z
            );
            const stretch = 1 + Math.sin(phase * 1.3) * 0.12 * voicePower;
            blob.scale.set(meta.scale.x * stretch, meta.scale.y / Math.max(0.88, stretch), meta.scale.z * (1 + Math.cos(phase) * 0.08));
        });
        orb.currents.children.forEach((line, index) => {
            line.rotation.z = elapsed * (0.16 + index * 0.025);
            line.material.opacity = (state.muted ? 0.18 : 0.46) + Math.sin(elapsed * 1.4 + index) * 0.08;
        });
        orb.ring.rotation.z = elapsed * 0.08;
        orb.ring.rotation.x = 0.12 + Math.sin(elapsed * 0.33) * 0.035;
        orb.ring.rotation.y = -0.10 + Math.cos(elapsed * 0.29) * 0.025;
        orb.ring.material.opacity = state.muted ? 0.38 : 0.72;
        orb.sweep.rotation.z = -elapsed * 0.34;
        orb.sweep.rotation.x = 0.10;
        orb.sweep.rotation.y = -0.08;
        orb.sweep.material.opacity = state.muted ? 0.24 : 0.62;
        orb.spark.rotation.y = elapsed * 0.48;

        waves.group.children.forEach((wave, index) => {
            const meta = wave.userData;
            wave.rotation.z = Math.sin(elapsed * 0.4 + meta.phase) * 0.018;
            wave.position.y = meta.baseY + Math.sin(elapsed * meta.speed + meta.phase) * meta.float * voicePower;
            wave.scale.y = 1 + Math.sin(elapsed * 1.2 + meta.phase) * 0.08 * voicePower;
            wave.material.opacity = meta.opacity * (state.muted ? 0.42 : 1);
        });
        tendrils.group.rotation.y = Math.sin(elapsed * 0.32) * 0.04;
        tendrils.group.children.forEach((tendril, index) => {
            const meta = tendril.userData;
            tendril.rotation.z = Math.sin(elapsed * meta.speed + meta.phase) * 0.045;
            tendril.scale.setScalar(1 + Math.sin(elapsed * 1.18 + meta.phase) * 0.045 * voicePower);
            tendril.material.opacity = meta.opacity * (state.muted ? 0.36 : 1);
        });
        halo.group.rotation.z = elapsed * 0.04;
        halo.group.children.forEach((ring, index) => {
            ring.material.opacity = 0.12 + Math.sin(elapsed * 0.9 + index) * 0.035;
            ring.rotation.z = elapsed * (0.02 + index * 0.007);
        });
        particles.material.opacity = state.muted ? 0.22 : 0.48 + Math.sin(elapsed * 1.4) * 0.1;
        particles.points.rotation.y = elapsed * 0.035;

        renderer.render(scene, camera);
        if (!prefersReducedMotion) frameId = window.requestAnimationFrame(animate);
    }

    resize();
    window.addEventListener('resize', resize);
    animate();

    return () => {
        window.removeEventListener('resize', resize);
        window.removeEventListener('pointermove', handlePointer);
        if (frameId) window.cancelAnimationFrame(frameId);
        renderer.dispose();
        mount.removeChild(renderer.domElement);
        disposeObject(root);
    };
}

function createEnergyOrb() {
    const group = new THREE.Group();
    const liquidMetal = new THREE.MeshPhysicalMaterial({
        color: 0xd74a7f,
        roughness: 0.18,
        metalness: 0.46,
        clearcoat: 1,
        clearcoatRoughness: 0.08,
        transmission: 0.12,
        thickness: 0.55,
        transparent: true,
        opacity: 0.92,
        emissive: 0x5c0f35,
        emissiveIntensity: 0.22
    });

    const outer = new THREE.Mesh(
        new THREE.SphereGeometry(1.18, 96, 96),
        new THREE.MeshPhysicalMaterial({
            color: 0xffefe6,
            roughness: 0.02,
            metalness: 0,
            transmission: 0.72,
            thickness: 1.4,
            transparent: true,
            opacity: 0.18,
            depthWrite: false,
            clearcoat: 1,
            clearcoatRoughness: 0.02,
            ior: 1.52,
            iridescence: 0.52,
            iridescenceIOR: 1.5,
            emissive: 0xffb8a6,
            emissiveIntensity: 0.08
        })
    );
    group.add(outer);

    const innerMaterial = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: {
            uTime: { value: 0 },
            uPower: { value: 1 }
        },
        vertexShader: `
            varying vec3 vNormal;
            varying vec3 vPosition;
            uniform float uTime;
            uniform float uPower;

            void main() {
                vNormal = normalize(normalMatrix * normal);
                vPosition = position;
                float n = sin(position.x * 5.8 + uTime * 1.4)
                    + sin(position.y * 6.4 - uTime * 1.1)
                    + sin(position.z * 7.2 + uTime * 0.8);
                vec3 displaced = position + normal * n * 0.045 * uPower;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced, 1.0);
            }
        `,
        fragmentShader: `
            varying vec3 vNormal;
            varying vec3 vPosition;
            uniform float uTime;
            uniform float uPower;

            float field(vec3 p) {
                vec3 a = vec3(sin(uTime * 0.73), cos(uTime * 0.51), sin(uTime * 0.37)) * 0.32;
                vec3 b = vec3(cos(uTime * 0.61 + 1.2), sin(uTime * 0.47), cos(uTime * 0.43)) * 0.28;
                float f = 0.0;
                f += 0.32 / max(0.05, length(p - a));
                f += 0.26 / max(0.05, length(p + b));
                f += 0.18 / max(0.05, length(p - vec3(-a.y, a.z, a.x) * 0.75));
                return f;
            }

            void main() {
                vec3 n = normalize(vNormal);
                float fresnel = pow(1.0 - abs(dot(n, vec3(0.0, 0.0, 1.0))), 2.4);
                float angle = atan(vPosition.y, vPosition.x);
                float radius = length(vPosition.xy);
                float swirl = sin(angle * 3.0 + radius * 8.0 - uTime * 1.25)
                    + sin((vPosition.x - vPosition.z) * 5.0 + uTime * 0.82);
                float goo = smoothstep(0.62, 1.32, field(vPosition * 0.85));
                vec3 roseGold = vec3(1.0, 0.54, 0.42);
                vec3 hotPink = vec3(0.98, 0.18, 0.56);
                vec3 deepInk = vec3(0.34, 0.02, 0.17);
                vec3 color = mix(deepInk, hotPink, smoothstep(-0.8, 1.0, swirl));
                color = mix(color, roseGold, goo * 0.55 + fresnel * 0.38);
                color += fresnel * vec3(1.0, 0.74, 0.42) * 0.38;
                float alpha = 0.72 + fresnel * 0.22 + goo * 0.08 * uPower;
                gl_FragColor = vec4(color, alpha);
            }
        `
    });
    const inner = new THREE.Mesh(new THREE.SphereGeometry(0.74, 128, 128), innerMaterial);
    group.add(inner);

    const blobs = new THREE.Group();
    const blobSeeds = [
        { origin: [-0.32, 0.16, 0.12], scale: [0.56, 0.44, 0.48], drift: [0.13, 0.08, 0.05], phase: 0.2, speed: 0.86 },
        { origin: [0.31, -0.12, -0.08], scale: [0.48, 0.60, 0.44], drift: [0.10, 0.12, 0.06], phase: 1.7, speed: 0.78 },
        { origin: [0.06, 0.35, 0.06], scale: [0.34, 0.28, 0.38], drift: [0.08, 0.06, 0.08], phase: 3.1, speed: 0.94 },
        { origin: [-0.08, -0.36, -0.04], scale: [0.38, 0.32, 0.34], drift: [0.07, 0.10, 0.05], phase: 4.4, speed: 0.82 }
    ];
    blobSeeds.forEach((seed) => {
        const blob = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 64), liquidMetal.clone());
        blob.position.set(...seed.origin);
        blob.scale.set(...seed.scale);
        blob.userData = {
            origin: new THREE.Vector3(...seed.origin),
            scale: new THREE.Vector3(...seed.scale),
            drift: new THREE.Vector3(...seed.drift),
            phase: seed.phase,
            speed: seed.speed
        };
        blobs.add(blob);
    });
    group.add(blobs);

    const ring = new THREE.Mesh(
        new THREE.TorusGeometry(1.86, 0.032, 28, 240),
        new THREE.MeshPhysicalMaterial({
            color: 0xffe0ad,
            roughness: 0.04,
            metalness: 0.18,
            transmission: 0.46,
            thickness: 0.75,
            transparent: true,
            opacity: 0.78,
            clearcoat: 1,
            clearcoatRoughness: 0.03,
            ior: 1.62,
            emissive: 0xffb45f,
            emissiveIntensity: 0.22,
            blending: THREE.AdditiveBlending
        })
    );
    ring.rotation.x = 0.12;
    ring.rotation.y = -0.10;
    group.add(ring);

    const sweep = new THREE.Mesh(
        new THREE.TorusGeometry(2.02, 0.014, 14, 190, Math.PI * 1.38),
        new THREE.MeshBasicMaterial({
            color: 0xfff1ce,
            transparent: true,
            opacity: 0.66,
            blending: THREE.AdditiveBlending
        })
    );
    sweep.rotation.x = 0.10;
    sweep.rotation.y = -0.08;
    group.add(sweep);

    const spark = new THREE.Group();
    for (let i = 0; i < 11; i += 1) {
        const curve = new THREE.CatmullRomCurve3(
            Array.from({ length: 22 }, (_, step) => {
                const t = step / 21;
                const angle = t * Math.PI * 2.4 + i * 0.62;
                return new THREE.Vector3(
                    Math.cos(angle) * (0.30 + t * 0.38),
                    Math.sin(angle * 1.6 + i) * 0.24,
                    Math.sin(angle) * (0.30 + t * 0.32)
                );
            })
        );
        spark.add(createTube(curve.getPoints(90), 0.01, i % 2 ? '#ffe7d6' : '#ff5ca8', 0.42));
    }
    group.add(spark);

    const currents = new THREE.Group();
    for (let i = 0; i < 6; i += 1) {
        const points = [];
        const phase = i * 0.9;
        for (let step = 0; step < 72; step += 1) {
            const t = step / 71;
            const angle = t * Math.PI * 2 + phase;
            points.push(new THREE.Vector3(
                Math.cos(angle) * (0.54 + Math.sin(t * Math.PI * 3 + phase) * 0.07),
                Math.sin(angle * 1.4) * 0.22,
                Math.sin(angle) * 0.52
            ));
        }
        currents.add(createTube(points, 0.012, i % 2 ? '#ffd6c4' : '#ff2e8f', 0.44));
    }
    group.add(currents);

    return { group, inner, blobs, ring, sweep, spark, currents };
}

function createFluidSoundWaves() {
    const group = new THREE.Group();
    const palette = ['#fff0ea', '#ffc8bd', '#ff6aa9', '#be155f', '#70143e'];
    for (let i = 0; i < 13; i += 1) {
        const points = [];
        const phase = i * 0.54;
        const thickness = i % 4 === 0 ? 0.022 : 0.014;
        const baseY = (i % 5 - 2) * 0.09;
        for (let step = 0; step < 130; step += 1) {
            const p = step / 129;
            const x = (p - 0.5) * 13.7;
            const envelope = Math.sin(p * Math.PI);
            const sideIntensity = smoothstepLike(Math.abs(p - 0.5), 0.03, 0.48);
            const y = baseY
                + Math.sin(p * 13.0 + phase) * 0.28 * envelope
                + Math.sin(p * 31.0 - phase) * 0.05 * sideIntensity;
            const z = Math.cos(p * 9.0 + phase) * 0.12 * envelope + (i % 3 - 1) * 0.055;
            points.push(new THREE.Vector3(x, y, z));
        }
        const tube = createTube(points, thickness, palette[i % palette.length], i < 6 ? 0.44 : 0.62);
        tube.userData = {
            baseY,
            phase,
            float: 0.065 + (i % 4) * 0.01,
            speed: 0.64 + (i % 5) * 0.07,
            opacity: tube.material.opacity
        };
        group.add(tube);
    }
    return { group };
}

function createGooeyTendrils() {
    const group = new THREE.Group();
    const configs = [
        { side: -1, y: 0.22, z: 0.08, color: '#fff1e7', radius: 0.045, opacity: 0.72, phase: 0.2 },
        { side: -1, y: -0.15, z: -0.04, color: '#f7a7a6', radius: 0.035, opacity: 0.66, phase: 1.1 },
        { side: -1, y: 0.02, z: 0.16, color: '#ffd2be', radius: 0.026, opacity: 0.58, phase: 2.4 },
        { side: 1, y: 0.20, z: -0.02, color: '#c31762', radius: 0.050, opacity: 0.76, phase: 0.8 },
        { side: 1, y: -0.18, z: 0.10, color: '#ff4f9b', radius: 0.037, opacity: 0.68, phase: 1.9 },
        { side: 1, y: 0.03, z: -0.16, color: '#781340', radius: 0.030, opacity: 0.60, phase: 3.2 }
    ];
    configs.forEach((config) => {
        const points = [];
        for (let step = 0; step < 52; step += 1) {
            const t = step / 51;
            const x = config.side * (0.62 + t * 1.65);
            const curl = Math.sin(t * Math.PI * 2.2 + config.phase);
            const y = config.y * (1 - t * 0.4) + curl * 0.16 * Math.sin(t * Math.PI);
            const z = config.z + Math.cos(t * Math.PI * 2 + config.phase) * 0.12 * Math.sin(t * Math.PI);
            points.push(new THREE.Vector3(x, y, z));
        }
        const tendril = createTube(points, config.radius, config.color, config.opacity, true);
        tendril.userData = {
            phase: config.phase,
            speed: 0.68 + Math.abs(config.y) * 0.8,
            opacity: config.opacity
        };
        group.add(tendril);
    });
    return { group };
}

function createTube(points, radius, color, opacity, physical = false) {
    const curve = new THREE.CatmullRomCurve3(points);
    const geometry = new THREE.TubeGeometry(curve, Math.max(40, points.length * 2), radius, 14, false);
    const material = physical
        ? new THREE.MeshPhysicalMaterial({
            color,
            roughness: 0.16,
            metalness: 0.26,
            clearcoat: 1,
            clearcoatRoughness: 0.07,
            transparent: true,
            opacity,
            depthWrite: false,
            emissive: new THREE.Color(color).multiplyScalar(0.28),
            emissiveIntensity: 0.34
        })
        : new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity,
            depthWrite: false,
            blending: THREE.AdditiveBlending
        });
    return new THREE.Mesh(geometry, material);
}

function smoothstepLike(value, edge0, edge1) {
    const x = Math.max(0, Math.min(1, (value - edge0) / (edge1 - edge0)));
    return x * x * (3 - 2 * x);
}

function createHaloField() {
    const group = new THREE.Group();
    for (let i = 0; i < 4; i += 1) {
        const ring = new THREE.Mesh(
            new THREE.TorusGeometry(2.25 + i * 0.68, 0.006, 8, 180),
            new THREE.MeshBasicMaterial({
                color: i % 2 ? 0xffdfd1 : 0xffc582,
                transparent: true,
                opacity: 0.14,
                blending: THREE.AdditiveBlending
            })
        );
        ring.rotation.x = Math.PI * 0.5;
        ring.rotation.z = i * 0.44;
        group.add(ring);
    }
    return { group };
}

function createParticleField() {
    const count = 620;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const light = new THREE.Color('#fff2e8');
    const berry = new THREE.Color('#ff5fa4');
    const gold = new THREE.Color('#ffd487');

    for (let i = 0; i < count; i += 1) {
        const side = i % 2 === 0 ? -1 : 1;
        const spread = Math.random();
        positions[i * 3] = side * (1.2 + spread * 5.4) + (Math.random() - 0.5) * 0.35;
        positions[i * 3 + 1] = (Math.random() - 0.5) * (0.5 + spread * 1.6);
        positions[i * 3 + 2] = (Math.random() - 0.5) * 1.6;
        const color = i % 5 === 0 ? gold : side > 0 ? berry : light;
        colors[i * 3] = color.r;
        colors[i * 3 + 1] = color.g;
        colors[i * 3 + 2] = color.b;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({
        size: 0.035,
        vertexColors: true,
        transparent: true,
        opacity: 0.48,
        depthWrite: false,
        blending: THREE.AdditiveBlending
    });

    return { points: new THREE.Points(geometry, material), material };
}

function disposeObject(object) {
    object.traverse((child) => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) {
            if (Array.isArray(child.material)) {
                child.material.forEach((material) => material.dispose());
            } else {
                child.material.dispose();
            }
        }
    });
}

createRoot(document.getElementById('speech-showcase-root')).render(<App />);
