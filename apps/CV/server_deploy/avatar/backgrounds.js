(function () {
    'use strict';

    var MODEL_THEME_MAP = {
        epsilon: 'company-wall',
        haruGreeter: 'company-wall',
        haru: 'company-wall',
        chitose: 'company-wall',
        natori: 'company-wall'
    };

    var currentTheme = null;
    var container = null;

    function init() {
        container = document.getElementById('bg-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'bg-container';
            container.className = 'bg-layer';
            document.body.insertBefore(container, document.body.firstChild);
        }
    }

    function clearBackground() {
        if (!container) return;
        container.innerHTML = '';
        container.className = 'bg-layer';
        var bodyClasses = document.body.className.split(' ').filter(function (c) {
            return c.indexOf('theme-') !== 0;
        });
        document.body.className = bodyClasses.join(' ');
    }

    function applyTheme(themeName) {
        themeName = 'company-wall';
        if (themeName === currentTheme) return;
        clearBackground();
        currentTheme = themeName;
        document.body.classList.add('theme-' + themeName);

        switch (themeName) {
            case 'company-wall': buildCompanyWall(); break;
            case 'epsilon': buildEpsilon(); break;
            case 'haru': buildHaru(); break;
            case 'hiyori': buildHiyori(); break;
            case 'chitose': buildChitose(); break;
            case 'natori': buildNatori(); break;
            default: break;
        }
    }

    function buildCompanyWall() {
        container.classList.add('company-wall-stage');
        container.appendChild(createElement('div', 'wall-screen-wash'));
        container.appendChild(createElement('div', 'wall-floor-shadow'));
        container.appendChild(createElement('div', 'wall-edge-mask'));
    }

    function applyThemeForModel(modelKey) {
        var theme = MODEL_THEME_MAP[modelKey];
        if (theme) {
            applyTheme(theme);
        }
    }

    function rand(min, max) {
        return min + Math.random() * (max - min);
    }

    function randInt(min, max) {
        return Math.floor(rand(min, max + 1));
    }

    function createElement(tag, className, styles) {
        var el = document.createElement(tag || 'div');
        if (className) el.className = className;
        if (styles) {
            Object.keys(styles).forEach(function (k) {
                el.style[k] = styles[k];
            });
        }
        return el;
    }

    /* ============================================
       Epsilon - 梦幻校园·活力青春
       层级：光晕 → 光斑 → 流星 → 气泡 → 波纹
       ============================================ */
    function buildEpsilon() {
        var i, el;

        // 光晕底层
        ['g1', 'g2', 'g3'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-glow ' + cls));
        });

        // 漂浮光斑 ×6
        for (i = 0; i < 6; i++) {
            el = createElement('div', 'epsilon-orb o' + (i + 1));
            el.style.animationDelay = '-' + rand(0, 8).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 流星 ×3
        for (i = 0; i < 3; i++) {
            el = createElement('div', 'epsilon-star');
            el.style.top = rand(5, 35) + '%';
            el.style.left = rand(-10, 30) + '%';
            el.style.animationDuration = rand(3, 5.5).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 6).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 漂浮气泡 ×8
        for (i = 0; i < 8; i++) {
            el = createElement('div', 'epsilon-bubble');
            var size = rand(10, 28);
            el.style.width = size + 'px';
            el.style.height = size + 'px';
            el.style.left = rand(5, 90) + '%';
            el.style.bottom = rand(-5, 15) + '%';
            el.style.animationDuration = rand(5, 9).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 7).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 底部波纹
        container.appendChild(createElement('div', 'bg-wave'));
    }

    /* ============================================
       Haru - 温馨和风·樱花祭典
       层级：光晕 → 樱花 → 光点 → 灯笼 → 雾气
       ============================================ */
    function buildHaru() {
        var i, el;

        // 光晕底层
        ['g1', 'g2', 'g3'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-glow ' + cls));
        });

        // 樱花花瓣 ×35
        for (i = 0; i < 35; i++) {
            el = createElement('div', 'haru-sakura');
            var scale = rand(0.5, 1.3);
            el.style.left = rand(-5, 105) + 'vw';
            el.style.animationDuration = rand(4, 8).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 8).toFixed(1) + 's';
            el.style.transform = 'scale(' + scale.toFixed(2) + ')';
            container.appendChild(el);
        }

        // 金色光点 ×12
        for (i = 0; i < 12; i++) {
            el = createElement('div', 'haru-sparkle');
            el.style.top = rand(5, 85) + '%';
            el.style.left = rand(5, 90) + '%';
            el.style.animationDuration = rand(2, 4.5).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 4).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 和风灯笼
        ['l1', 'l2'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-lantern ' + cls));
        });

        // 底部雾气
        container.appendChild(createElement('div', 'bg-mist'));
    }

    /* ============================================
       Hiyori - 清新治愈·星空物语
       层级：极光 → 星云 → 星星 → 萤火虫 → 粒子 → 月光
       ============================================ */
    function buildHiyori() {
        var i, el;

        // 极光带
        container.appendChild(createElement('div', 'bg-aurora'));

        // 星云光晕
        ['g1', 'g2', 'g3'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-glow ' + cls));
        });

        // 闪烁星星 ×40
        var starSizes = ['', 's-small', 's-large'];
        for (i = 0; i < 40; i++) {
            var sizeClass = starSizes[randInt(0, 2)];
            el = createElement('div', 'hiyori-star ' + sizeClass);
            el.style.top = rand(2, 70) + '%';
            el.style.left = rand(2, 98) + '%';
            el.style.animationDuration = rand(2, 5).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 5).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 萤火虫 ×8
        for (i = 0; i < 8; i++) {
            el = createElement('div', 'hiyori-firefly');
            el.style.top = rand(30, 80) + '%';
            el.style.left = rand(10, 85) + '%';
            el.style.animationDuration = rand(8, 16).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 10).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 微风粒子 ×15
        for (i = 0; i < 15; i++) {
            el = createElement('div', 'hiyori-particle');
            el.style.top = rand(5, 60) + '%';
            el.style.left = rand(5, 85) + '%';
            el.style.animationDuration = rand(10, 20).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 12).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 底部月光反射
        container.appendChild(createElement('div', 'bg-moonlight'));
    }

    /* ============================================
       Chitose - 现代都市·沉稳可靠
       层级：光晕 → 光斑 → 几何线 → 粒子 → 雾气
       ============================================ */
    function buildChitose() {
        var i, el;

        // 城市霓虹光晕
        ['g1', 'g2', 'g3'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-glow ' + cls));
        });

        // 城市光斑（窗户反射）×5
        for (i = 0; i < 5; i++) {
            el = createElement('div', 'chitose-bokeh b' + (i + 1));
            el.style.animationDelay = '-' + rand(0, 10).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 几何装饰线 ×3
        for (i = 0; i < 3; i++) {
            el = createElement('div', 'chitose-line l' + (i + 1));
            el.style.animationDelay = '-' + rand(0, 8).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 数据粒子流 ×18
        for (i = 0; i < 18; i++) {
            el = createElement('div', 'chitose-particle');
            el.style.left = rand(5, 95) + '%';
            el.style.animationDuration = rand(8, 18).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 14).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 底部城市剪影雾气
        container.appendChild(createElement('div', 'bg-mist'));
    }

    /* ============================================
       Natori - 雅致书房·知性从容
       层级：光晕 → 书页 → 墨迹 → 尘埃 → 灯光 → 书架
       ============================================ */
    function buildNatori() {
        var i, el;

        // 温暖灯光光晕
        ['g1', 'g2', 'g3'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-glow ' + cls));
        });

        // 书页飘落 ×12
        for (i = 0; i < 12; i++) {
            el = createElement('div', 'natori-page');
            var scale = rand(0.6, 1.2);
            el.style.left = rand(-5, 105) + 'vw';
            el.style.animationDuration = rand(6, 12).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 10).toFixed(1) + 's';
            el.style.transform = 'scale(' + scale.toFixed(2) + ')';
            container.appendChild(el);
        }

        // 墨迹粒子 ×10
        for (i = 0; i < 10; i++) {
            el = createElement('div', 'natori-ink');
            el.style.top = rand(20, 75) + '%';
            el.style.left = rand(10, 85) + '%';
            el.style.animationDuration = rand(10, 20).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 14).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 金色尘埃 ×16
        for (i = 0; i < 16; i++) {
            el = createElement('div', 'natori-dust');
            el.style.top = rand(5, 85) + '%';
            el.style.left = rand(5, 95) + '%';
            el.style.animationDuration = rand(6, 14).toFixed(1) + 's';
            el.style.animationDelay = rand(0, 10).toFixed(1) + 's';
            container.appendChild(el);
        }

        // 台灯光影
        ['lp1', 'lp2'].forEach(function (cls) {
            container.appendChild(createElement('div', 'bg-lamp ' + cls));
        });

        // 底部书架暗影
        container.appendChild(createElement('div', 'bg-shelf'));
    }

    /* ============================================
       全局初始化
       ============================================ */
    init();

    // 默认使用公司墙背景
    applyTheme('company-wall');

    // 暴露全局接口，供 avatar.js 模型切换时调用
    window.BackgroundManager = {
        applyTheme: applyTheme,
        applyThemeForModel: applyThemeForModel,
        getCurrentTheme: function () { return currentTheme; }
    };
})();
