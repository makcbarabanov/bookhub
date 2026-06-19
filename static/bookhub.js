/**
 * BookHub v0.2 — API, autosave, export, chapters
 */
(function () {
    'use strict';

    var DEBOUNCE_MS = 1500;
    var LS_ACTIVE = 'bookhub_active_ch';
    var LS_OFFLINE = 'bookhub_offline_queue';
    var CHAPTER_MARKERS = ['🟢', '🟡', '⚪'];
    var loggedIn = false;
    var activeMarkerMenu = null;

    var state = {
        book: null,
        chapters: [],
        activeChId: null,
        locked: true,
        saveTimer: null,
        saving: false,
        dirty: false,
        service: null,
        serviceDirty: false,
        serviceSaveTimer: null,
        activeServicePanel: null,
        aiAnalysis: null,
        aiLoading: false,
        chatLoading: false,
        chatSending: false,
    };

    function apiFetch(path, options) {
        options = options || {};
        var headers = options.headers || {};
        if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }
        options.headers = headers;
        options.credentials = 'include';
        return fetch(path, options).then(function (res) {
            if (res.status === 401) {
                loggedIn = false;
                showLogin();
                throw new Error('unauthorized');
            }
            if (!res.ok) {
                return res.text().then(function (t) {
                    throw new Error(t || res.statusText);
                });
            }
            var ct = res.headers.get('content-type') || '';
            if (ct.indexOf('application/json') >= 0) return res.json();
            return res.text();
        });
    }

    function setSaveStatus(mode) {
        /* status badge removed */
    }

    function showLogin() {
        var overlay = document.getElementById('login-overlay');
        if (overlay) overlay.style.display = 'flex';
    }

    function hideLogin() {
        var overlay = document.getElementById('login-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    /**
     * Стилизованное уведомление вместо window.alert.
     * opts: { title?, message, variant?: 'info'|'success'|'danger' }
     */
    function showAppNotice(opts) {
        opts = opts || {};
        var modal = document.getElementById('app-notice-modal');
        var box = modal && modal.querySelector('.modal-box');
        var titleEl = document.getElementById('app-notice-title');
        var msgEl = document.getElementById('app-notice-message');
        var okBtn = document.getElementById('app-notice-ok');
        if (!modal || !titleEl || !msgEl || !okBtn) {
            window.alert(opts.message || opts.title || '');
            return Promise.resolve();
        }
        var variant = opts.variant || 'info';
        if (box) {
            box.classList.remove('modal-box--danger', 'modal-box--success');
            if (variant === 'danger') box.classList.add('modal-box--danger');
            if (variant === 'success') box.classList.add('modal-box--success');
        }
        if (opts.title) {
            titleEl.textContent = opts.title;
        } else if (variant === 'danger') {
            titleEl.textContent = 'Ошибка';
        } else if (variant === 'success') {
            titleEl.textContent = 'Готово';
        } else {
            titleEl.textContent = 'Сообщение';
        }
        msgEl.textContent = opts.message || '';
        return new Promise(function (resolve) {
            function close() {
                modal.style.display = 'none';
                okBtn.removeEventListener('click', onOk);
                modal.removeEventListener('click', onBackdrop);
                resolve();
            }
            function onOk() { close(); }
            function onBackdrop(e) { if (e.target === modal) close(); }
            okBtn.addEventListener('click', onOk);
            modal.addEventListener('click', onBackdrop);
            modal.style.display = 'flex';
            okBtn.focus();
        });
    }

    function bindLogin() {
        var form = document.getElementById('login-form');
        if (!form || form.__bound) return;
        form.__bound = true;
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var user = document.getElementById('login-user').value.trim();
            var pass = document.getElementById('login-pass').value;
            fetch('/api/v1/login', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login: user, password: pass }),
            }).then(function (res) {
                if (res.status === 429) throw new Error('rate limit');
                if (!res.ok) throw new Error('login failed');
                return res.json();
            }).then(function () {
                loggedIn = true;
                hideLogin();
                return loadBook();
            }).catch(function (err) {
                loggedIn = false;
                showLogin();
                if (err && err.message === 'rate limit') {
                    alert('Слишком много попыток. Подождите минуту.');
                } else {
                    alert('Неверный логин или пароль');
                }
            });
        });
        checkSession();
    }

    function checkSession() {
        fetch('/api/v1/session', { credentials: 'include' })
            .then(function (res) {
                if (!res.ok) throw new Error('no session');
                loggedIn = true;
                hideLogin();
                return loadBook();
            })
            .catch(function () {
                loggedIn = false;
                showLogin();
            });
    }

    function formatServiceDate(iso) {
        if (!iso) return '';
        try {
            var d = new Date(iso);
            if (isNaN(d.getTime())) return '';
            return d.toLocaleString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch (e) {
            return '';
        }
    }

    function setServiceUpdatedLabels(service) {
        var heroesEl = document.getElementById('heroes-updated');
        var plotEl = document.getElementById('plot-updated');
        if (heroesEl) {
            heroesEl.textContent = service && service.heroes_updated_at
                ? ('обновлено ' + formatServiceDate(service.heroes_updated_at))
                : '';
        }
        if (plotEl) {
            plotEl.textContent = service && service.plot_updated_at
                ? ('обновлено ' + formatServiceDate(service.plot_updated_at))
                : '';
        }
    }

    function collectChecklistHtml() {
        var panel = document.getElementById('checklist');
        if (!panel) return '';
        var parts = [];
        panel.querySelectorAll(':scope > .atlas-note, :scope > .max-text').forEach(function (node) {
            parts.push(node.outerHTML);
        });
        return parts.join('\n');
    }

    function applyChecklistHtml(html) {
        var panel = document.getElementById('checklist');
        if (!panel) return;
        var header = panel.querySelector('.checklist-header');
        panel.querySelectorAll(':scope > .atlas-note, :scope > .max-text').forEach(function (node) {
            node.remove();
        });
        var wrap = document.createElement('div');
        wrap.innerHTML = html || '<div class="max-text"></div>';
        while (wrap.firstChild) {
            if (header && header.nextSibling) {
                panel.insertBefore(wrap.firstChild, header.nextSibling);
            } else {
                panel.appendChild(wrap.firstChild);
            }
        }
        normalizeChapterContent(panel);
    }

    function applyHeroesText(text) {
        var body = document.getElementById('heroes-body');
        if (!body) return;
        body.textContent = text || 'Нажмите «Обновить», чтобы извлечь героев из текста глав.';
    }

    function applyServiceData(service) {
        state.service = service || null;
        if (!service) return;
        applyChecklistHtml(service.checklist_html || '');
        applyHeroesText(service.heroes_text || '');
        setServiceUpdatedLabels(service);
        if (window.__book1445 && window.__book1445.applyPlotFromApi) {
            window.__book1445.applyPlotFromApi(service.plot || {});
        }
        applyEditableState();
    }

    function scheduleServiceSave() {
        if (state.locked) return;
        state.serviceDirty = true;
        clearTimeout(state.serviceSaveTimer);
        state.serviceSaveTimer = setTimeout(flushServiceSave, DEBOUNCE_MS);
    }

    function flushServiceSave() {
        if (!state.serviceDirty || state.locked) return Promise.resolve();
        var panel = state.activeServicePanel;
        var chain = Promise.resolve();

        if (panel === 'checklist') {
            chain = apiFetch('/api/v1/book/service/checklist', {
                method: 'PATCH',
                body: { checklist_html: collectChecklistHtml() },
            }).then(function (data) {
                if (data.service) state.service = data.service;
            });
        } else if (panel === 'heroes') {
            var body = document.getElementById('heroes-body');
            chain = apiFetch('/api/v1/book/service/heroes', {
                method: 'PATCH',
                body: { heroes_text: body ? body.textContent : '' },
            }).then(function (data) {
                if (data.service) state.service = data.service;
            });
        } else {
            return Promise.resolve();
        }

        return chain.then(function () {
            state.serviceDirty = false;
            setServiceUpdatedLabels(state.service);
        }).catch(function () {
            alert('Не удалось сохранить служебную вкладку');
        });
    }

    function refreshHeroesFromText(btn) {
        if (btn) btn.disabled = true;
        return flushServiceSave().then(function () {
            return apiFetch('/api/v1/book/service/heroes/refresh', { method: 'POST' });
        }).then(function (data) {
            if (data.service) applyServiceData(data.service);
        }).catch(function () {
            alert('Не удалось обновить героев');
        }).finally(function () {
            if (btn) btn.disabled = false;
        });
    }

    function refreshPlotFromText(btn) {
        if (btn) btn.disabled = true;
        return apiFetch('/api/v1/book/service/plot/refresh', { method: 'POST' })
            .then(function (data) {
                if (data.service) applyServiceData(data.service);
                if (window.__book1445 && window.__book1445.syncChaptersFromApi) {
                    window.__book1445.syncChaptersFromApi(state.chapters);
                }
            }).catch(function () {
                alert('Не удалось обновить сюжетную линию');
            }).finally(function () {
                if (btn) btn.disabled = false;
            });
    }

    function bindServicePanels() {
        var heroesBtn = document.getElementById('btn-refresh-heroes');
        var plotBtn = document.getElementById('btn-refresh-plot');
        var aiBtn = document.getElementById('btn-refresh-ai');
        var toolbarAi = document.getElementById('btn-ai');
        if (heroesBtn && !heroesBtn.__bound) {
            heroesBtn.__bound = true;
            heroesBtn.addEventListener('click', function () {
                refreshHeroesFromText(heroesBtn);
            });
        }
        if (plotBtn && !plotBtn.__bound) {
            plotBtn.__bound = true;
            plotBtn.addEventListener('click', function () {
                refreshPlotFromText(plotBtn);
            });
        }
        if (aiBtn && !aiBtn.__bound) {
            aiBtn.__bound = true;
            aiBtn.addEventListener('click', function () {
                refreshAiAnalysis(aiBtn);
            });
        }
        if (toolbarAi && !toolbarAi.__bound) {
            toolbarAi.__bound = true;
            toolbarAi.addEventListener('click', function () {
                var nav = document.getElementById('nav-ai-advice');
                if (typeof window.openTab === 'function') {
                    window.openTab('ai-advice', nav);
                }
                switchAiTab('secretary');
                loadChatHistory();
            });
        }

        document.querySelectorAll('.ai-tab').forEach(function (tab) {
            if (tab.__bound) return;
            tab.__bound = true;
            tab.addEventListener('click', function () {
                switchAiTab(tab.getAttribute('data-ai-tab'));
            });
        });

        if (window.__openTabWrapped) return;
        var origOpenTab = window.openTab;
        if (!origOpenTab) return;
        window.openTab = function (tabId, element) {
            if (state.dirty && state.activeChId) flushSave();
            if (state.serviceDirty) flushServiceSave();
            state.activeChId = null;
            state.activeServicePanel = null;
            if (tabId === 'checklist' || tabId === 'heroes' || tabId === 'plotline') {
                state.activeServicePanel = tabId === 'plotline' ? null : tabId;
            }
            if (tabId === 'ai-advice') {
                loadAiAnalysis();
                loadChatHistory();
            }
            if (tabId === 'book-notes') {
                loadBookNotes();
            }
            origOpenTab(tabId, element);
        };
        window.__openTabWrapped = true;
        bindChatUi();
    }

    function switchAiTab(name) {
        document.querySelectorAll('.ai-tab').forEach(function (t) {
            t.classList.toggle('active', t.getAttribute('data-ai-tab') === name);
        });
        document.querySelectorAll('#ai-advice .ai-panel-section').forEach(function (s) {
            var tab = s.id.replace('ai-section-', '');
            s.classList.toggle('active', tab === name);
        });
        var tools = document.getElementById('ai-analysis-tools');
        var hint = document.getElementById('ai-analysis-hint');
        var isAnalysis = name !== 'secretary';
        if (tools) tools.classList.toggle('visible', isAnalysis);
        if (hint) hint.classList.toggle('visible', isAnalysis);
        document.querySelectorAll('.analysis-panel-tools').forEach(function (el) {
            if (el.id === 'ai-analysis-tools' || el.id === 'ai-analysis-hint') return;
            if (!isAnalysis) {
                el.style.display = 'none';
            }
        });
        if (isAnalysis && state.aiAnalysis && state.aiAnalysis.analysis) {
            document.querySelectorAll('.analysis-panel-tools').forEach(function (el) {
                if (el.id === 'ai-analysis-tools' || el.id === 'ai-analysis-hint') return;
                el.style.display = '';
            });
        }
        if (name === 'secretary') {
            loadChatHistory();
        }
    }

    function typeLabel(t) {
        var map = { language: 'Язык', plot: 'Сюжет', character: 'Персонаж', fact: 'Факт' };
        return map[t] || t;
    }

    function openChapterFromAi(chId) {
        var nav = document.querySelector(
            '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + chId + '"] .nav-chapter-main'
        );
        if (nav) openChapter(chId, nav);
    }

    function escapeHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function parseFixOptions(err) {
        if (err.fix_options && err.fix_options.length) {
            return err.fix_options.slice();
        }
        var options = [];
        if (err.new_text) options.push(err.new_text);
        var finding = err.finding || '';
        var tail = finding;
        var arrow = finding.indexOf('→');
        if (arrow >= 0) tail = finding.slice(arrow);
        else {
            var idx = finding.toLowerCase().indexOf('должно быть');
            if (idx >= 0) tail = finding.slice(idx);
        }
        var re = /«([^»]+)»/g;
        var m;
        while ((m = re.exec(tail))) {
            if (m[1] !== err.old_text && options.indexOf(m[1]) < 0) options.push(m[1]);
        }
        return options;
    }

    function showAiFixModal(errItem) {
        return new Promise(function (resolve) {
            var modal = document.getElementById('ai-fix-modal');
            var quoteEl = document.getElementById('ai-fix-quote');
            var diffEl = document.getElementById('ai-fix-diff');
            var optionsLabel = document.getElementById('ai-fix-options-label');
            var optionsEl = document.getElementById('ai-fix-options');
            var customWrap = document.getElementById('ai-fix-custom-wrap');
            var customInput = document.getElementById('ai-fix-custom');
            var cancelBtn = document.getElementById('ai-fix-cancel');
            var confirmBtn = document.getElementById('ai-fix-confirm');
            if (!modal || !optionsEl) {
                resolve(window.confirm('Исправить текст в главе?') ? { ok: true, newText: errItem.new_text } : null);
                return;
            }

            var options = parseFixOptions(errItem);
            var selectedText = options.length === 1 ? options[0] : (errItem.new_text || options[0] || '');

            if (quoteEl) {
                quoteEl.textContent = errItem.context || errItem.finding || '';
            }
            if (diffEl) {
                diffEl.style.display = options.length <= 1 ? 'block' : 'none';
                diffEl.innerHTML =
                    '<div class="old">' + escapeHtml(errItem.old_text) + '</div>' +
                    '<div class="new">' + escapeHtml(selectedText) + '</div>';
            }
            if (optionsLabel) optionsLabel.style.display = options.length > 1 ? 'block' : 'none';
            optionsEl.innerHTML = '';
            if (customWrap) customWrap.style.display = options.length > 1 ? 'block' : 'none';
            if (customInput) {
                customInput.value = '';
                customInput.classList.remove('selected');
            }

            function pickOption(text, btn) {
                selectedText = text;
                optionsEl.querySelectorAll('.ai-fix-option').forEach(function (b) {
                    b.classList.toggle('selected', b === btn);
                });
                if (customInput) customInput.classList.remove('selected');
            }

            options.forEach(function (opt) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'ai-fix-option' + (opt === selectedText ? ' selected' : '');
                btn.textContent = opt;
                btn.addEventListener('click', function () { pickOption(opt, btn); });
                optionsEl.appendChild(btn);
            });

            function close(result) {
                modal.style.display = 'none';
                cancelBtn.removeEventListener('click', onCancel);
                confirmBtn.removeEventListener('click', onConfirm);
                modal.removeEventListener('click', onBackdrop);
                if (customInput) customInput.removeEventListener('input', onCustomInput);
                resolve(result);
            }
            function onCancel() { close(null); }
            function onCustomInput() {
                selectedText = customInput.value;
                optionsEl.querySelectorAll('.ai-fix-option').forEach(function (b) {
                    b.classList.remove('selected');
                });
                customInput.classList.add('selected');
            }
            function onConfirm() {
                var text = (customInput && customInput.classList.contains('selected'))
                    ? customInput.value.trim()
                    : selectedText;
                if (!text) return;
                close({ ok: true, newText: text });
            }
            function onBackdrop(e) { if (e.target === modal) close(null); }
            cancelBtn.addEventListener('click', onCancel);
            confirmBtn.addEventListener('click', onConfirm);
            modal.addEventListener('click', onBackdrop);
            if (customInput) customInput.addEventListener('input', onCustomInput);
            modal.style.display = 'flex';
            confirmBtn.focus();
        });
    }

    function applyAiFix(errItem) {
        if (state.locked) {
            showAppNotice({
                variant: 'info',
                title: 'Редактирование заблокировано',
                message: 'Разблокируйте редактирование (🔓), чтобы применить исправление.',
            });
            return;
        }
        showAiFixModal(errItem).then(function (result) {
            if (!result || !result.ok) return;
            apiFetch('/api/v1/book/ai-analysis/apply', {
                method: 'POST',
                body: {
                    ch_id: errItem.ch_id,
                    old_text: errItem.old_text,
                    new_text: result.newText,
                    context: errItem.context || '',
                    finding: errItem.finding || '',
                },
            }).then(function (data) {
                if (data.content) renderChapterBody(data.ch_id, data.content);
                if (data.ai_analysis) {
                    state.aiAnalysis = data.ai_analysis;
                    renderAiAnalysis(state.aiAnalysis);
                }
            }).then(function () {
                showAppNotice({
                    variant: 'success',
                    message: 'Исправлено.',
                });
            }).catch(function () {
                showAppNotice({
                    variant: 'danger',
                    message: 'Не удалось применить исправление. Возможно, текст главы уже изменился.',
                });
            });
        });
    }

    function dismissAiError(errItem, opts) {
        opts = opts || {};
        return apiFetch('/api/v1/book/ai-analysis/dismiss-error', {
            method: 'POST',
            body: {
                ch_id: errItem.ch_id || '',
                finding: errItem.finding || '',
                old_text: errItem.old_text || '',
            },
        }).then(function (data) {
            state.aiAnalysis = data.ai_analysis;
            renderAiAnalysis(state.aiAnalysis);
        }).catch(function () {
            if (!opts.silent) {
                showAppNotice({
                    variant: 'danger',
                    message: 'Не удалось убрать замечание из списка.',
                });
            }
        });
    }

    function dismissAiPlotIdea(ideaItem) {
        var ideaText = typeof ideaItem === 'object' ? (ideaItem.idea || '') : String(ideaItem || '');
        return apiFetch('/api/v1/book/ai-analysis/dismiss-idea', {
            method: 'POST',
            body: { idea: ideaText },
        }).then(function (data) {
            state.aiAnalysis = data.ai_analysis;
            renderAiAnalysis(state.aiAnalysis);
        }).catch(function () {
            showAppNotice({
                variant: 'danger',
                message: 'Не удалось удалить идею.',
            });
        });
    }

    function addAiPlotIdeaToChecklist(ideaItem) {
        var ideaText = typeof ideaItem === 'object' ? (ideaItem.idea || '') : String(ideaItem || '');
        var chIds = (ideaItem && ideaItem.related_ch_ids) || [];
        return apiFetch('/api/v1/book/ai-analysis/idea-to-checklist', {
            method: 'POST',
            body: { idea: ideaText, related_ch_ids: chIds },
        }).then(function (data) {
            state.aiAnalysis = data.ai_analysis;
            renderAiAnalysis(state.aiAnalysis);
            if (data.service) applyServiceData(data.service);
            showAppNotice({
                variant: 'success',
                message: 'Идея добавлена в чек-лист.',
            });
        }).catch(function () {
            showAppNotice({
                variant: 'danger',
                message: 'Не удалось добавить идею в заметки.',
            });
        });
    }

    function renderAiAnalysis(payload) {
        var emptyEl = document.getElementById('ai-analysis-empty');
        var metaEl = document.getElementById('ai-analysis-meta');
        var updatedEl = document.getElementById('ai-analysis-updated');
        if (!emptyEl) return;

        if (!payload || !payload.analysis) {
            emptyEl.style.display = 'block';
            if (metaEl) metaEl.textContent = '';
            if (updatedEl) updatedEl.textContent = '';
            var errClear = document.getElementById('ai-section-errors-list');
            if (errClear) errClear.innerHTML = '';
            var plotClear = document.getElementById('ai-section-plot');
            if (plotClear) plotClear.innerHTML = '';
            var radarClear = document.getElementById('ai-section-radar');
            if (radarClear) radarClear.innerHTML = '';
            return;
        }

        var a = payload.analysis;
        emptyEl.style.display = 'none';
        if (updatedEl) {
            updatedEl.textContent = payload.updated_at
                ? ('обновлено ' + formatServiceDate(payload.updated_at)) : '';
        }
        if (metaEl) {
            var parts = [];
            if (payload.model) parts.push('модель: ' + payload.model);
            if (payload.tokens_in) parts.push('вход: ' + payload.tokens_in + ' ток.');
            if (payload.tokens_out) parts.push('выход: ' + payload.tokens_out + ' ток.');
            metaEl.textContent = parts.join(' · ');
        }

        var errSec = document.getElementById('ai-section-errors-list');
        if (errSec) {
            errSec.innerHTML = '';
            var errors = a.errors || [];
            if (!errors.length) {
                errSec.innerHTML = '<div class="ai-empty">Замечаний не найдено.</div>';
            }
            errors.forEach(function (err) {
                var card = document.createElement('div');
                card.className = 'ai-card sev-' + (err.severity || 'medium');
                card.innerHTML =
                    '<div class="ai-card-head"><span>' + typeLabel(err.type) + ' · ' +
                    escapeHtml(err.ch_id) + '</span><span>' + escapeHtml(err.severity) + '</span></div>' +
                    '<div class="ai-card-finding">' + escapeHtml(err.finding) + '</div>';
                if (err.context) {
                    var quote = document.createElement('div');
                    quote.className = 'ai-card-quote';
                    quote.textContent = err.context;
                    card.appendChild(quote);
                }
                var actions = document.createElement('div');
                actions.className = 'ai-card-actions';
                if (err.ch_id) {
                    var openBtn = document.createElement('button');
                    openBtn.type = 'button';
                    openBtn.className = 'btn-ai-open-ch';
                    openBtn.textContent = 'Открыть главу';
                    openBtn.addEventListener('click', function () { openChapterFromAi(err.ch_id); });
                    actions.appendChild(openBtn);
                }
                var canFix = err.type === 'language' && (err.old_text || (err.fix_options && err.fix_options.length) || err.new_text);
                if (canFix) {
                    var applyBtn = document.createElement('button');
                    applyBtn.type = 'button';
                    applyBtn.className = 'btn-ai-apply';
                    applyBtn.textContent = '✓ Исправить';
                    applyBtn.addEventListener('click', function () { applyAiFix(err); });
                    actions.appendChild(applyBtn);
                }
                var leaveBtn = document.createElement('button');
                leaveBtn.type = 'button';
                leaveBtn.className = 'btn-ai-leave';
                leaveBtn.textContent = 'Оставить';
                leaveBtn.title = 'Оставить текст как есть и убрать замечание';
                leaveBtn.addEventListener('click', function () { dismissAiError(err); });
                actions.appendChild(leaveBtn);
                card.appendChild(actions);
                errSec.appendChild(card);
            });
        }

        var plotSec = document.getElementById('ai-section-plot');
        if (plotSec) {
            plotSec.innerHTML = '';
            var strengths = a.strengths || [];
            if (strengths.length) {
                var sh = document.createElement('h4');
                sh.textContent = 'Сильные стороны';
                plotSec.appendChild(sh);
                strengths.forEach(function (s) {
                    var el = document.createElement('div');
                    el.className = 'ai-idea-item';
                    el.textContent = s;
                    plotSec.appendChild(el);
                });
            }
            var ph = document.createElement('h4');
            ph.textContent = 'Идеи развития сюжета';
            ph.style.marginTop = '16px';
            plotSec.appendChild(ph);
            var ideas = a.plot_ideas || [];
            if (!ideas.length) plotSec.appendChild(document.createTextNode('Пока нет идей.'));
            ideas.forEach(function (item) {
                var ideaText = item.idea || item;
                var el = document.createElement('div');
                el.className = 'ai-idea-item';

                var textEl = document.createElement('div');
                textEl.className = 'ai-idea-text';
                textEl.textContent = ideaText;
                el.appendChild(textEl);

                var ideaActions = document.createElement('div');
                ideaActions.className = 'ai-idea-actions';

                var noteBtn = document.createElement('button');
                noteBtn.type = 'button';
                noteBtn.className = 'btn-icon';
                noteBtn.setAttribute('aria-label', 'Добавить в заметки');
                noteBtn.title = 'Добавить в заметки';
                noteBtn.textContent = '📝';
                noteBtn.addEventListener('click', function () { addAiPlotIdeaToChecklist(item); });
                ideaActions.appendChild(noteBtn);

                var delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'btn-icon btn-icon--danger';
                delBtn.setAttribute('aria-label', 'Удалить идею');
                delBtn.title = 'Удалить идею';
                delBtn.textContent = '×';
                delBtn.addEventListener('click', function () { dismissAiPlotIdea(item); });
                ideaActions.appendChild(delBtn);

                el.appendChild(ideaActions);
                plotSec.appendChild(el);
            });
        }

        var radarSec = document.getElementById('ai-section-radar');
        if (radarSec) {
            radarSec.innerHTML = '';
            var radar = a.radar || {};
            var grid = document.createElement('div');
            grid.className = 'ai-radar-grid';
            grid.innerHTML =
                '<div class="ai-radar-stat"><div class="val">' + (radar.tension != null ? radar.tension : '—') +
                '%</div><div class="lbl">Напряжение</div></div>' +
                '<div class="ai-radar-stat"><div class="val">' + escapeHtml(radar.pacing || '—') +
                '</div><div class="lbl">Динамика</div></div>' +
                '<div class="ai-radar-stat"><div class="val" style="font-size:14px">' + escapeHtml(radar.atmosphere || '—') +
                '</div><div class="lbl">Атмосфера</div></div>';
            radarSec.appendChild(grid);
            if (radar.summary) {
                var sum = document.createElement('p');
                sum.textContent = radar.summary;
                radarSec.appendChild(sum);
            }
            (a.chapter_radar || []).forEach(function (cr) {
                var el = document.createElement('div');
                el.className = 'ai-card';
                el.innerHTML =
                    '<div class="ai-card-head"><span>' + escapeHtml(cr.ch_id) + '</span><span>' +
                    escapeHtml(String(cr.tension)) + '%</span></div>' +
                    '<div class="ai-card-finding">' + escapeHtml(cr.note || '') + '</div>';
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn-ai-open-ch';
                btn.textContent = 'Открыть главу';
                btn.addEventListener('click', function () { openChapterFromAi(cr.ch_id); });
                el.appendChild(btn);
                radarSec.appendChild(el);
            });
        }
    }

    function setAiLoading(on) {
        state.aiLoading = on;
        var el = document.getElementById('ai-analysis-loading');
        var btn = document.getElementById('btn-refresh-ai');
        if (el) el.style.display = on ? 'block' : 'none';
        if (btn) btn.disabled = !!on;
    }

    var chatToastTimer = null;

    function showToast(text) {
        var existing = document.querySelector('.ai-toast');
        if (existing) existing.remove();
        if (chatToastTimer) clearTimeout(chatToastTimer);
        var el = document.createElement('div');
        el.className = 'ai-toast';
        el.textContent = text;
        document.body.appendChild(el);
        chatToastTimer = setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 4500);
    }

    function scrollChatToBottom() {
        var box = document.getElementById('ai-chat-messages');
        if (box) box.scrollTop = box.scrollHeight;
    }

    function renderChatMessage(msg) {
        var box = document.getElementById('ai-chat-messages');
        if (!box || !msg) return;
        var div = document.createElement('div');
        div.className = 'ai-chat-bubble ' + (msg.sender === 'user' ? 'user' : 'ai');
        if (msg.id) div.dataset.msgId = String(msg.id);
        div.textContent = msg.message || '';
        box.appendChild(div);
        scrollChatToBottom();
    }

    function showOffTopicBanner(show) {
        var el = document.getElementById('ai-chat-offtopic');
        if (el) el.style.display = show ? 'block' : 'none';
    }

    function loadChatHistory() {
        if (state.chatLoading) return Promise.resolve();
        var bookId = state.book && state.book.id;
        if (!bookId) return Promise.resolve();
        state.chatLoading = true;
        var box = document.getElementById('ai-chat-messages');
        return apiFetch('/api/v1/book/chat').then(function (data) {
            if (!state.book || state.book.id !== bookId) return;
            if (box) box.innerHTML = '';
            (data.messages || []).forEach(function (m) {
                renderChatMessage(m);
            });
            showOffTopicBanner(false);
        }).catch(function () {
        }).finally(function () {
            state.chatLoading = false;
        });
    }

    function setChatSending(on) {
        state.chatSending = on;
        var btn = document.getElementById('ai-chat-send');
        var input = document.getElementById('ai-chat-input');
        if (btn) btn.disabled = !!on;
        if (input) input.disabled = !!on;
    }

    function sendChat() {
        if (state.chatSending) return;
        var input = document.getElementById('ai-chat-input');
        if (!input) return;
        var text = (input.value || '').trim();
        if (!text) return;
        setChatSending(true);
        showOffTopicBanner(false);
        apiFetch('/api/v1/book/chat/send', { method: 'POST', body: { message: text } })
            .then(function (data) {
                input.value = '';
                if (data.user_message) renderChatMessage(data.user_message);
                if (data.ai_message) {
                    renderChatMessage(data.ai_message);
                    showOffTopicBanner(!!data.ai_message.off_topic);
                }
                if (data.note_created && data.note_created.title) {
                    showToast('Добавлена новая заметка: ' + data.note_created.title + ' 📓');
                }
            })
            .catch(function (err) {
                var msg = (err && err.message) || '';
                if (msg.indexOf('429') >= 0 || msg.indexOf('limit') >= 0 || msg.indexOf('Chat limit') >= 0) {
                    showAppNotice({
                        variant: 'info',
                        title: 'Лимит сообщений',
                        message: 'Не больше 45 сообщений в час. Подождите немного.',
                    });
                } else {
                    showAppNotice({
                        variant: 'danger',
                        message: 'Не удалось отправить сообщение. Попробуйте позже.',
                    });
                }
            })
            .finally(function () {
                setChatSending(false);
                input.focus();
            });
    }

    function openLastChapterFromStorage() {
        var chId = null;
        try { chId = sessionStorage.getItem(LS_ACTIVE); } catch (e) {}
        if (chId) {
            openChapterFromAi(chId);
            showOffTopicBanner(false);
            return;
        }
        if (state.chapters && state.chapters.length) {
            openChapterFromAi(state.chapters[0].ch_id);
            showOffTopicBanner(false);
        }
    }

    function loadBookNotes() {
        var listEl = document.getElementById('book-notes-list');
        var viewEl = document.getElementById('book-note-view');
        if (viewEl) viewEl.style.display = 'none';
        if (listEl) listEl.style.display = '';
        if (!listEl) return Promise.resolve();
        listEl.innerHTML = '<div class="ai-empty">Загрузка…</div>';
        return apiFetch('/api/v1/book/notes').then(function (data) {
            var notes = data.notes || [];
            listEl.innerHTML = '';
            if (!notes.length) {
                listEl.innerHTML = '<div class="ai-empty">Заметок пока нет. Попроси Морфеуса записать идею в чате.</div>';
                return;
            }
            notes.forEach(function (note) {
                var item = document.createElement('div');
                item.className = 'book-note-item';
                var preview = (note.content || '').replace(/\s+/g, ' ').trim();
                if (preview.length > 120) preview = preview.slice(0, 117) + '…';
                item.innerHTML = '<h4>' + escapeHtml(note.title) + '</h4><p>' + escapeHtml(preview) + '</p>';
                item.addEventListener('click', function () { showBookNote(note.id); });
                listEl.appendChild(item);
            });
        }).catch(function () {
            listEl.innerHTML = '<div class="ai-empty">Не удалось загрузить заметки.</div>';
        });
    }

    function showBookNote(noteId) {
        var listEl = document.getElementById('book-notes-list');
        var viewEl = document.getElementById('book-note-view');
        var titleEl = document.getElementById('book-note-view-title');
        var bodyEl = document.getElementById('book-note-view-body');
        if (!viewEl || !titleEl || !bodyEl) return;
        apiFetch('/api/v1/book/notes/' + noteId).then(function (data) {
            var note = data.note;
            if (!note) return;
            if (listEl) listEl.style.display = 'none';
            titleEl.textContent = note.title || '';
            bodyEl.textContent = note.content || '';
            viewEl.style.display = 'block';
        }).catch(function () {
            showAppNotice({ variant: 'danger', message: 'Не удалось открыть заметку.' });
        });
    }

    function bindChatUi() {
        var sendBtn = document.getElementById('ai-chat-send');
        var input = document.getElementById('ai-chat-input');
        var backBtn = document.getElementById('ai-chat-back-book');
        var contBtn = document.getElementById('ai-chat-continue');
        var noteBack = document.getElementById('book-note-back');
        if (sendBtn && !sendBtn.__bound) {
            sendBtn.__bound = true;
            sendBtn.addEventListener('click', sendChat);
        }
        if (input && !input.__bound) {
            input.__bound = true;
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendChat();
                }
            });
        }
        if (backBtn && !backBtn.__bound) {
            backBtn.__bound = true;
            backBtn.addEventListener('click', openLastChapterFromStorage);
        }
        if (contBtn && !contBtn.__bound) {
            contBtn.__bound = true;
            contBtn.addEventListener('click', function () { showOffTopicBanner(false); });
        }
        if (noteBack && !noteBack.__bound) {
            noteBack.__bound = true;
            noteBack.addEventListener('click', function () {
                var view = document.getElementById('book-note-view');
                var list = document.getElementById('book-notes-list');
                if (view) view.style.display = 'none';
                if (list) list.style.display = '';
            });
        }
    }

    function loadAiAnalysis() {
        if (state.aiLoading) return Promise.resolve();
        var bookId = state.book && state.book.id;
        if (!bookId) {
            state.aiAnalysis = null;
            renderAiAnalysis(null);
            return Promise.resolve();
        }
        return apiFetch('/api/v1/book/ai-analysis').then(function (data) {
            if (!state.book || state.book.id !== bookId) return;
            if (data.book_id && data.book_id !== bookId) return;
            state.aiAnalysis = data.ai_analysis || null;
            renderAiAnalysis(state.aiAnalysis);
        }).catch(function () {
            if (state.book && state.book.id === bookId) {
                state.aiAnalysis = null;
                renderAiAnalysis(null);
            }
        });
    }

    function refreshAiAnalysis(btn) {
        if (state.aiLoading) return;
        var bookId = state.book && state.book.id;
        if (!bookId) return;
        setAiLoading(true);
        apiFetch('/api/v1/book/ai-analysis/refresh', { method: 'POST' })
            .then(function (data) {
                if (!state.book || state.book.id !== bookId) return;
                state.aiAnalysis = data.ai_analysis || null;
                renderAiAnalysis(state.aiAnalysis);
            })
            .catch(function (err) {
                var msg = (err && err.message) || '';
                if (msg.indexOf('429') >= 0 || msg.indexOf('rate') >= 0) {
                    showAppNotice({
                        variant: 'info',
                        title: 'OpenRouter перегружен',
                        message: 'Модель временно недоступна. Подождите минуту и повторите, или смените OPENROUTER_MODEL в .env.',
                    });
                } else if (state.aiAnalysis) {
                    showAppNotice({
                        variant: 'danger',
                        message: 'Не удалось обновить анализ. Показан сохранённый отчёт.',
                    });
                } else {
                    showAppNotice({
                        variant: 'danger',
                        message: 'Не удалось выполнить анализ ИИ. Проверьте ключ OpenRouter и модель.',
                    });
                }
            })
            .finally(function () {
                setAiLoading(false);
            });
    }

    function bindAppVersion() {
        fetch('/api/v1/version', { credentials: 'include' })
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) {
                if (data && data.version) {
                    var el = document.getElementById('app-version');
                    if (el) el.textContent = data.version;
                }
            })
            .catch(function () {});
    }

    function actLabel(n) {
        var map = {
            1: 'Акт I: Приговор',
            2: 'Акт II: Подъём',
            3: 'Акт III: Сочи',
            4: 'Акт IV: 14:46',
        };
        return map[n] || ('Акт ' + n);
    }

    function chapterIndex(chId) {
        for (var i = 0; i < state.chapters.length; i++) {
            if (state.chapters[i].ch_id === chId) return i;
        }
        return -1;
    }

    function stripTitleNumber(text) {
        return (text || '').replace(/^\d+\.\s*/, '').replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
    }

    function ensureMaxText(container) {
        if (!container) return null;
        var body = container.querySelector('.max-text');
        if (!body) {
            body = document.createElement('div');
            body.className = 'max-text';
            container.appendChild(body);
        }
        return body;
    }

    function focusChapterBody(chId) {
        if (state.locked) return;
        var container = getChapterContainer(chId);
        var body = ensureMaxText(container);
        if (!body) return;
        applyEditableState();
        body.focus();
        var range = document.createRange();
        range.selectNodeContents(body);
        range.collapse(true);
        var sel = window.getSelection();
        if (!sel) return;
        sel.removeAllRanges();
        sel.addRange(range);
    }

    function commitChapterTitle(chId, rawTitle, source) {
        setChapterTitle(chId, rawTitle, source);
        var container = getChapterContainer(chId);
        var h2 = container && container.querySelector('h2');
        if (h2) {
            var idx = chapterIndex(chId);
            h2.textContent = formatChapterTitle(idx >= 0 ? idx : 0, state.chapters[chapterIndex(chId)].title);
        }
        return flushSave();
    }

    function formatChapterTitle(idx, title) {
        return (idx + 1) + '. ' + (title || 'Глава');
    }

    function finishTitleEdit(chId, source) {
        var container = getChapterContainer(chId);
        var h2 = container && container.querySelector('h2');
        var nav = document.querySelector(
            '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + chId + '"] .nav-chapter-main'
        );
        var raw = source === 'nav' && nav ? nav.textContent : (h2 ? h2.textContent : '');
        return commitChapterTitle(chId, raw, source).then(function () {
            focusChapterBody(chId);
        });
    }

    function setChapterTitle(chId, rawTitle, source) {
        var idx = chapterIndex(chId);
        if (idx < 0) return;
        var title = stripTitleNumber(rawTitle) || 'Глава';
        var changed = state.chapters[idx].title !== title;
        state.chapters[idx].title = title;

        var container = getChapterContainer(chId);
        if (container) {
            container.setAttribute('data-chapter-title', title);
        }

        var h2 = container && container.querySelector('h2');
        if (h2 && source !== 'h2') {
            h2.textContent = formatChapterTitle(idx, title);
        }

        var nav = document.querySelector(
            '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + chId + '"] .nav-chapter-main'
        );
        if (nav && source !== 'nav') {
            nav.textContent = formatChapterTitle(idx, title);
        }

        if (changed) {
            state.dirty = true;
            scheduleSave();
        }
    }

    function getChapterContainer(chId) {
        return document.getElementById(chId);
    }

    function collectChapterContent(chId) {
        var el = getChapterContainer(chId);
        if (!el) return '';
        var parts = [];
        el.querySelectorAll('.max-text, .atlas-note').forEach(function (node) {
            parts.push(node.outerHTML);
        });
        if (!parts.length) {
            var h2 = el.querySelector('h2');
            if (h2) {
                var sib = h2.nextElementSibling;
                while (sib) {
                    parts.push(sib.outerHTML);
                    sib = sib.nextElementSibling;
                }
            }
        }
        return parts.join('\n');
    }

    function normalizeChapterContent(root) {
        if (!root) return;
        root.querySelectorAll('.max-text [style], .atlas-note [style]').forEach(function (el) {
            el.removeAttribute('style');
        });
        root.querySelectorAll('.max-text [class*="ng-"], .atlas-note [class*="ng-"]').forEach(function (el) {
            el.removeAttribute('class');
        });
    }

    function renderChapterBody(chId, contentHtml) {
        var el = getChapterContainer(chId);
        if (!el) return;
        var h2 = el.querySelector('h2');
        el.innerHTML = '';
        if (h2) el.appendChild(h2);
        var wrap = document.createElement('div');
        wrap.innerHTML = contentHtml || '<div class="max-text"></div>';
        while (wrap.firstChild) el.appendChild(wrap.firstChild);
        ensureMaxText(el);
        normalizeChapterContent(el);
        applyEditableState();
    }

    function normalizeMarker(marker) {
        return CHAPTER_MARKERS.indexOf(marker) !== -1 ? marker : '🟢';
    }

    function closeMarkerMenu() {
        if (activeMarkerMenu) {
            activeMarkerMenu.remove();
            activeMarkerMenu = null;
        }
    }

    function setChapterEmoji(chId, emoji) {
        emoji = normalizeMarker(emoji);
        var idx = chapterIndex(chId);
        if (idx >= 0) state.chapters[idx].emoji = emoji;

        var wrap = document.querySelector('#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + chId + '"]');
        var marker = wrap && wrap.querySelector('.nav-chapter-marker');
        if (marker) marker.textContent = emoji;

        var container = getChapterContainer(chId);
        if (container) container.setAttribute('data-nav-emoji', emoji);

        return apiFetch('/api/v1/chapters/' + encodeURIComponent(chId), {
            method: 'PATCH',
            body: { emoji: emoji },
        }).catch(function () {
            alert('Не удалось сохранить маркер');
        });
    }

    function openMarkerMenu(anchor, chId) {
        closeMarkerMenu();
        var menu = document.createElement('div');
        menu.className = 'marker-picker-menu';
        menu.setAttribute('role', 'listbox');
        CHAPTER_MARKERS.forEach(function (m) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = m;
            btn.setAttribute('role', 'option');
            if (anchor.textContent === m) btn.classList.add('active');
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                setChapterEmoji(chId, m);
                closeMarkerMenu();
            });
            menu.appendChild(btn);
        });
        document.body.appendChild(menu);
        var rect = anchor.getBoundingClientRect();
        menu.style.left = Math.max(8, rect.left) + 'px';
        menu.style.top = (rect.bottom + 6) + 'px';
        activeMarkerMenu = menu;
    }

    function bindMarkerPicker(marker, chId) {
        marker.title = 'Цвет маркера';
        marker.setAttribute('role', 'button');
        marker.tabIndex = 0;
        marker.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            openMarkerMenu(marker, chId);
        });
    }

    function refreshChapterNumbers() {
        state.chapters.forEach(function (ch, idx) {
            ch.sort_order = idx + 1;
            var h2 = document.querySelector('#' + ch.ch_id + ' h2');
            if (h2) h2.textContent = formatChapterTitle(idx, ch.title);
            var nav = document.querySelector(
                '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + ch.ch_id + '"] .nav-chapter-main'
            );
            if (nav && nav.contentEditable !== 'true') {
                nav.textContent = formatChapterTitle(idx, ch.title);
            }
        });
    }

    function moveChapterInState(fromId, toId, before) {
        var fromIdx = chapterIndex(fromId);
        var toIdx = chapterIndex(toId);
        if (fromIdx < 0 || toIdx < 0 || fromIdx === toIdx) return false;

        var moved = state.chapters.splice(fromIdx, 1)[0];
        var insertAt = toIdx;
        if (fromIdx < toIdx) {
            insertAt = before ? toIdx - 1 : toIdx;
        } else {
            insertAt = before ? toIdx : toIdx + 1;
        }
        if (insertAt < 0) insertAt = 0;
        if (insertAt > state.chapters.length) insertAt = state.chapters.length;
        state.chapters.splice(insertAt, 0, moved);
        return true;
    }

    function persistChapterOrder() {
        var ids = state.chapters.map(function (ch) { return ch.ch_id; });
        setSaveStatus('saving');
        return apiFetch('/api/v1/chapters/reorder', {
            method: 'PUT',
            body: { chapter_ids: ids },
        }).then(function () {
            renderNavigation();
            refreshChapterNumbers();
            setSaveStatus('saved');
        }).catch(function () {
            setSaveStatus('error');
            alert('Не удалось сохранить порядок глав');
            return loadBook();
        });
    }

    function bindChapterDnD() {
        var sidebar = document.getElementById('sidebar-panel');
        if (!sidebar || sidebar.__chapterDnDBound) return;
        sidebar.__chapterDnDBound = true;

        var draggedWrap = null;

        sidebar.addEventListener('dragstart', function (e) {
            if (state.locked) {
                e.preventDefault();
                return;
            }
            var handle = e.target.closest('.nav-drag');
            if (!handle) return;
            var wrap = handle.closest('.nav-chapter-wrap');
            if (!wrap || !wrap.dataset.chId) return;
            draggedWrap = wrap;
            e.dataTransfer.setData('text/plain', wrap.dataset.chId);
            e.dataTransfer.effectAllowed = 'move';
            wrap.classList.add('dragging');
        });

        sidebar.addEventListener('dragend', function () {
            if (draggedWrap) draggedWrap.classList.remove('dragging');
            draggedWrap = null;
            sidebar.querySelectorAll('.nav-chapter-wrap.drag-over').forEach(function (w) {
                w.classList.remove('drag-over');
            });
        });

        sidebar.addEventListener('dragover', function (e) {
            if (!draggedWrap) return;
            var over = e.target.closest('#nav-chapters-root .nav-chapter-wrap');
            if (!over || over === draggedWrap) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            sidebar.querySelectorAll('.nav-chapter-wrap.drag-over').forEach(function (w) {
                w.classList.remove('drag-over');
            });
            over.classList.add('drag-over');
        });

        sidebar.addEventListener('dragleave', function (e) {
            var over = e.target.closest('.nav-chapter-wrap');
            if (over && !over.contains(e.relatedTarget)) {
                over.classList.remove('drag-over');
            }
        });

        sidebar.addEventListener('drop', function (e) {
            if (!draggedWrap) return;
            var over = e.target.closest('#nav-chapters-root .nav-chapter-wrap');
            if (!over || over === draggedWrap) return;
            e.preventDefault();

            var rect = over.getBoundingClientRect();
            var before = e.clientY < rect.top + rect.height / 2;
            var fromId = draggedWrap.dataset.chId;
            var toId = over.dataset.chId;

            if (!moveChapterInState(fromId, toId, before)) return;
            renderNavigation();
            refreshChapterNumbers();
            persistChapterOrder();
        });
    }

    function showDeleteChapterModal(chapterLabel) {
        return new Promise(function (resolve) {
            var modal = document.getElementById('delete-modal');
            var nameEl = document.getElementById('delete-modal-chapter');
            var cancelBtn = document.getElementById('delete-modal-cancel');
            var confirmBtn = document.getElementById('delete-modal-confirm');
            if (!modal || !cancelBtn || !confirmBtn) {
                resolve(window.confirm('Удалить главу «' + chapterLabel + '»?'));
                return;
            }

            if (nameEl) nameEl.textContent = chapterLabel;

            function close(result) {
                modal.style.display = 'none';
                cancelBtn.removeEventListener('click', onCancel);
                confirmBtn.removeEventListener('click', onConfirm);
                modal.removeEventListener('click', onBackdrop);
                document.removeEventListener('keydown', onKey);
                resolve(result);
            }

            function onCancel() { close(false); }
            function onConfirm() { close(true); }
            function onBackdrop(e) {
                if (e.target === modal) close(false);
            }
            function onKey(e) {
                if (e.key === 'Escape') close(false);
            }

            cancelBtn.addEventListener('click', onCancel);
            confirmBtn.addEventListener('click', onConfirm);
            modal.addEventListener('click', onBackdrop);
            document.addEventListener('keydown', onKey);

            modal.style.display = 'flex';
            cancelBtn.focus();
        });
    }

    function deleteChapter(chId) {
        if (state.locked) {
            alert('Разблокируйте редактирование (🔓), чтобы удалить главу');
            return;
        }
        if (state.chapters.length <= 1) {
            alert('Нельзя удалить единственную главу книги');
            return;
        }

        var idx = chapterIndex(chId);
        if (idx < 0) return;
        var title = state.chapters[idx].title;
        var label = formatChapterTitle(idx, title);

        showDeleteChapterModal(label).then(function (ok) {
            if (!ok) return;

            setSaveStatus('saving');
            var chain = state.activeChId === chId ? Promise.resolve() : flushSave();
            chain.then(function () {
                return apiFetch('/api/v1/chapters/' + encodeURIComponent(chId), {
                    method: 'DELETE',
                });
            }).then(function () {
                var container = getChapterContainer(chId);
                if (container) container.remove();
                try {
                    if (sessionStorage.getItem(LS_ACTIVE) === chId) {
                        sessionStorage.removeItem(LS_ACTIVE);
                    }
                } catch (e) {}
                return loadBook();
            }).then(function () {
                setSaveStatus('saved');
            }).catch(function (err) {
                setSaveStatus('error');
                if (err && err.message && err.message.indexOf('last chapter') >= 0) {
                    alert('Нельзя удалить единственную главу');
                } else {
                    alert('Не удалось удалить главу');
                }
            });
        });
    }

    function renderNavigation() {
        var root = document.getElementById('nav-chapters-root');
        if (!root) return;
        root.innerHTML = '';
        var lastAct = null;
        state.chapters.forEach(function (ch, idx) {
            if (ch.act_number !== lastAct) {
                lastAct = ch.act_number;
                var group = document.createElement('div');
                group.className = 'nav-group';
                group.textContent = actLabel(ch.act_number);
                root.appendChild(group);
            }
            var wrap = document.createElement('div');
            wrap.className = 'nav-chapter-wrap';
            wrap.dataset.chId = ch.ch_id;
            var drag = document.createElement('span');
            drag.className = 'nav-drag';
            drag.draggable = !state.locked;
            drag.title = 'Перетащить';
            drag.textContent = '⠿';
            drag.setAttribute('aria-hidden', 'true');
            var marker = document.createElement('span');
            marker.className = 'nav-chapter-marker';
            marker.textContent = normalizeMarker(ch.emoji || '🟢');
            bindMarkerPicker(marker, ch.ch_id);
            var main = document.createElement('div');
            main.className = 'nav-item nav-chapter-main' + (ch.ch_id === state.activeChId ? ' active' : '');
            main.textContent = formatChapterTitle(idx, ch.title);
            main.addEventListener('click', function () {
                openChapter(ch.ch_id, main);
            });
            main.addEventListener('dblclick', function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (state.locked) return;
                main.contentEditable = 'true';
                main.focus();
                document.execCommand('selectAll', false, null);
            });
            main.addEventListener('blur', function () {
                main.contentEditable = 'false';
                if (state.locked) return;
                setChapterTitle(ch.ch_id, main.textContent, 'nav');
            });
            main.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    main.contentEditable = 'false';
                    finishTitleEdit(ch.ch_id, 'nav');
                }
            });
            var delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'nav-chapter-delete';
            delBtn.title = 'Удалить главу';
            delBtn.setAttribute('aria-label', 'Удалить главу');
            delBtn.textContent = '×';
            delBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                deleteChapter(ch.ch_id);
            });
            wrap.appendChild(drag);
            wrap.appendChild(marker);
            wrap.appendChild(main);
            wrap.appendChild(delBtn);
            root.appendChild(wrap);
        });
    }

    function ensureChapterDom(ch) {
        var scroll = document.getElementById('content-scroll');
        if (!scroll) return;
        var el = document.getElementById(ch.ch_id);
        if (el) return el;
        el = document.createElement('div');
        el.id = ch.ch_id;
        el.className = 'chapter-container';
        el.style.display = 'none';
        el.setAttribute('data-chapter-title', ch.title);
        el.setAttribute('data-nav-emoji', ch.emoji || '🟢');
        var h2 = document.createElement('h2');
        var idx = chapterIndex(ch.ch_id);
        h2.textContent = formatChapterTitle(idx >= 0 ? idx : 0, ch.title);
        el.appendChild(h2);
        var body = document.createElement('div');
        body.className = 'max-text';
        el.appendChild(body);
        scroll.appendChild(el);
        return el;
    }

    function openChapter(chId, navEl) {
        if (state.serviceDirty) flushServiceSave();
        if (state.dirty && state.activeChId) flushSave();
        state.activeServicePanel = null;
        state.activeChId = chId;
        try { sessionStorage.setItem(LS_ACTIVE, chId); } catch (e) {}

        document.querySelectorAll('.chapter-container').forEach(function (el) {
            el.style.display = 'none';
            el.classList.remove('active');
        });
        document.querySelectorAll('.sidebar .nav-item').forEach(function (el) {
            el.classList.remove('active');
        });

        var target = document.getElementById(chId);
        if (target) {
            target.style.display = 'block';
            setTimeout(function () { target.classList.add('active'); }, 10);
        }
        if (navEl) navEl.classList.add('active');

        var pane = document.getElementById('content-scroll');
        if (pane) pane.scrollTop = 0;

        loadChapterContent(chId);
    }

    function loadChapterContent(chId) {
        return apiFetch('/api/v1/book?active_ch=' + encodeURIComponent(chId)).then(function (data) {
            var ch = data.active_chapter;
            ensureChapterDom(ch);
            var idx = chapterIndex(chId);
            var h2 = document.querySelector('#' + chId + ' h2');
            if (h2) h2.textContent = formatChapterTitle(idx >= 0 ? idx : 0, ch.title);
            renderChapterBody(chId, ch.content);
            bindAutosave();
        });
    }

    function loadBook() {
        var active = null;
        try { active = sessionStorage.getItem(LS_ACTIVE); } catch (e) {}
        var q = active ? '?active_ch=' + encodeURIComponent(active) : '';
        return apiFetch('/api/v1/book' + q).then(function (data) {
            state.book = data.book;
            state.chapters = data.chapters;
            state.activeChId = data.active_chapter.ch_id;

            var titleEl = document.getElementById('book-title');
            if (titleEl) titleEl.textContent = data.book.title;

            state.chapters.forEach(ensureChapterDom);
            renderNavigation();
            renderChapterBody(data.active_chapter.ch_id, data.active_chapter.content);
            var activeIdx = chapterIndex(data.active_chapter.ch_id);
            var activeH2 = document.querySelector('#' + data.active_chapter.ch_id + ' h2');
            if (activeH2) {
                activeH2.textContent = formatChapterTitle(
                    activeIdx >= 0 ? activeIdx : 0,
                    data.active_chapter.title
                );
            }

            var nav = document.querySelector(
                '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + data.active_chapter.ch_id + '"] .nav-chapter-main'
            );
            document.querySelectorAll('.chapter-container').forEach(function (el) {
                el.style.display = 'none';
                el.classList.remove('active');
            });
            var target = document.getElementById(data.active_chapter.ch_id);
            if (target) {
                target.style.display = 'block';
                target.classList.add('active');
            }
            if (nav) nav.classList.add('active');

            if (data.service) {
                applyServiceData(data.service);
            }
            if (window.__book1445 && window.__book1445.syncChaptersFromApi) {
                window.__book1445.syncChaptersFromApi(state.chapters);
            }
            state.aiAnalysis = null;
            renderAiAnalysis(null);
            var chatBox = document.getElementById('ai-chat-messages');
            if (chatBox) chatBox.innerHTML = '';
            showOffTopicBanner(false);

            bindAutosave();
            flushOfflineQueue();
            setSaveStatus('saved');
        });
    }

    function applyEditableState() {
        var editable = !state.locked;
        document.querySelectorAll('.content .max-text, .content .atlas-note, .content .chapter-container > h2').forEach(function (el) {
            el.contentEditable = editable ? 'true' : 'false';
            el.spellcheck = editable;
        });
        var heroesBody = document.getElementById('heroes-body');
        if (heroesBody) {
            heroesBody.contentEditable = editable ? 'true' : 'false';
            heroesBody.spellcheck = editable;
        }
        document.body.classList.toggle('bookhub-locked', state.locked);
        document.body.classList.toggle('admin-mode', editable);
        document.querySelectorAll('.nav-drag').forEach(function (el) {
            el.draggable = editable;
        });
    }

    function bindLock() {
        var btn = document.getElementById('btn-lock');
        if (!btn || btn.__bound) return;
        btn.__bound = true;
        state.locked = false;
        btn.addEventListener('click', function () {
            state.locked = !state.locked;
            btn.textContent = state.locked ? '🔒' : '🔓';
            btn.title = state.locked ? 'Разблокировать редактирование' : 'Заблокировать редактирование';
            applyEditableState();
        });
        btn.textContent = '🔓';
        btn.title = 'Заблокировать редактирование';
        applyEditableState();
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        var btn = document.getElementById('btn-theme');
        if (btn) {
            btn.textContent = theme === 'light' ? '🌙' : '☀️';
            btn.title = theme === 'light' ? 'Тёмная тема' : 'Светлая тема';
        }
    }

    function bindTheme() {
        var btn = document.getElementById('btn-theme');
        if (!btn || btn.__bound) return;
        btn.__bound = true;
        var saved = 'dark';
        try { saved = localStorage.getItem('bookhub_theme') || 'dark'; } catch (e) {}
        applyTheme(saved);
        btn.addEventListener('click', function () {
            var next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
            applyTheme(next);
            try { localStorage.setItem('bookhub_theme', next); } catch (e) {}
        });
    }

    function bindSidebarEdge() {
        var btn = document.getElementById('sidebar-edge-toggle');
        if (!btn || btn.__bound) return;
        btn.__bound = true;
        var LS_SIDEBAR = 'bookhub_sidebar_collapsed';

        function setCollapsed(collapsed) {
            document.body.classList.toggle('sidebar-collapsed', collapsed);
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.title = collapsed ? 'Развернуть панель' : 'Свернуть панель';
            btn.textContent = collapsed ? '▶' : '◀';
            try { localStorage.setItem(LS_SIDEBAR, collapsed ? '1' : '0'); } catch (e) {}
        }

        try {
            if (localStorage.getItem(LS_SIDEBAR) === '1') setCollapsed(true);
        } catch (e) {}

        btn.addEventListener('click', function () {
            setCollapsed(!document.body.classList.contains('sidebar-collapsed'));
        });
    }

    function bindBookAccordion() {
        var box = document.getElementById('sidebar-book');
        var toggle = document.getElementById('book-toggle');
        if (!box || !toggle || toggle.__bound) return;
        toggle.__bound = true;
        var LS = 'bookhub_book_collapsed';
        try {
            if (localStorage.getItem(LS) === '1') {
                box.classList.add('collapsed');
                toggle.setAttribute('aria-expanded', 'false');
            }
        } catch (e) {}
        toggle.addEventListener('click', function () {
            var collapsed = box.classList.toggle('collapsed');
            toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            try { localStorage.setItem(LS, collapsed ? '1' : '0'); } catch (e) {}
        });
    }

    function scheduleSave() {
        if (state.locked || !state.activeChId) return;
        state.dirty = true;
        clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(flushSave, DEBOUNCE_MS);
    }

    function flushSave() {
        if (!state.dirty || !state.activeChId || state.locked) return Promise.resolve();
        if (!navigator.onLine) {
            queueOffline();
            setSaveStatus('offline');
            return Promise.resolve();
        }
        var chId = state.activeChId;
        var container = getChapterContainer(chId);
        if (container) normalizeChapterContent(container);
        var content = collectChapterContent(chId);
        var idx = chapterIndex(chId);
        var title = idx >= 0 ? state.chapters[idx].title : null;
        state.saving = true;
        setSaveStatus('saving');
        return apiFetch('/api/v1/chapters/' + encodeURIComponent(chId), {
            method: 'PATCH',
            body: { content: content, title: title },
        }).then(function () {
            state.dirty = false;
            state.saving = false;
            setSaveStatus('saved');
        }).catch(function (err) {
            state.saving = false;
            if (!navigator.onLine || (err && err.message === 'Failed to fetch')) {
                queueOffline();
                setSaveStatus('offline');
            } else {
                setSaveStatus('error');
            }
        });
    }

    function queueOffline() {
        var chId = state.activeChId;
        if (!chId) return;
        var queue = [];
        try { queue = JSON.parse(localStorage.getItem(LS_OFFLINE) || '[]'); } catch (e) {}
        var content = collectChapterContent(chId);
        var found = false;
        queue = queue.map(function (item) {
            if (item.ch_id === chId) {
                found = true;
                return { ch_id: chId, content: content, at: new Date().toISOString() };
            }
            return item;
        });
        if (!found) queue.push({ ch_id: chId, content: content, at: new Date().toISOString() });
        try { localStorage.setItem(LS_OFFLINE, JSON.stringify(queue)); } catch (e) {}
    }

    function flushOfflineQueue() {
        if (!navigator.onLine) return;
        var queue = [];
        try { queue = JSON.parse(localStorage.getItem(LS_OFFLINE) || '[]'); } catch (e) {}
        if (!queue.length) return;
        var chain = Promise.resolve();
        queue.forEach(function (item) {
            chain = chain.then(function () {
                return apiFetch('/api/v1/chapters/' + encodeURIComponent(item.ch_id), {
                    method: 'PATCH',
                    body: { content: item.content },
                });
            });
        });
        chain.then(function () {
            localStorage.removeItem(LS_OFFLINE);
            setSaveStatus('saved');
        }).catch(function () {
            setSaveStatus('offline');
        });
    }

    function bindAutosave() {
        var scroll = document.getElementById('content-scroll');
        if (!scroll || scroll.__autosaveBound) return;
        scroll.__autosaveBound = true;
        scroll.addEventListener('input', function (e) {
            var h2 = e.target.closest('.chapter-container[id^="ch"] > h2');
            if (h2 && state.activeChId) {
                setChapterTitle(state.activeChId, h2.textContent, 'h2');
                return;
            }
            if (e.target.id === 'heroes-body' || e.target.closest('#checklist')) {
                scheduleServiceSave();
                return;
            }
            if (!e.target.closest('.max-text, .atlas-note')) return;
            scheduleSave();
        });
        scroll.addEventListener('keydown', function (e) {
            var h2 = e.target.closest('.chapter-container[id^="ch"] > h2');
            if (!h2 || !state.activeChId) return;
            if (e.key === 'Enter') {
                e.preventDefault();
                h2.blur();
                finishTitleEdit(state.activeChId, 'h2');
            }
        });
        window.addEventListener('online', function () {
            flushOfflineQueue();
            if (state.dirty) flushSave();
        });
        window.addEventListener('offline', function () {
            if (state.dirty) {
                queueOffline();
                setSaveStatus('offline');
            }
        });
    }

    function downloadBlob(blob, filename) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    }

    function exportBook(format) {
        setSaveStatus('saving');
        return flushSave().then(function () {
            return fetch('/api/v1/export?format=' + encodeURIComponent(format), {
                credentials: 'include',
            });
        }).then(function (res) {
            if (res.status === 401) {
                loggedIn = false;
                showLogin();
                throw new Error('unauthorized');
            }
            if (!res.ok) throw new Error('export failed');
            var disposition = res.headers.get('content-disposition') || '';
            var match = disposition.match(/filename=\"?([^\";]+)\"?/i);
            var filename = match ? match[1] : ('bookhub-export.' + format);
            return res.blob().then(function (blob) {
                downloadBlob(blob, filename);
                setSaveStatus('saved');
            });
        }).catch(function () {
            setSaveStatus('error');
            alert('Экспорт не удался');
        });
    }

    function closeExportMenu() {
        var menu = document.getElementById('export-menu');
        if (menu) menu.classList.remove('open');
    }

    function bindExport() {
        var btn = document.getElementById('btn-export');
        var menu = document.getElementById('export-menu');
        if (!btn || !menu || btn.__bound) return;
        btn.__bound = true;

        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            var open = menu.classList.contains('open');
            closeExportMenu();
            if (!open) {
                var rect = btn.getBoundingClientRect();
                menu.style.left = Math.max(8, rect.left - 60) + 'px';
                menu.style.top = (rect.bottom + 6) + 'px';
                menu.classList.add('open');
            }
        });

        menu.querySelectorAll('[data-format]').forEach(function (item) {
            item.addEventListener('click', function () {
                var format = item.getAttribute('data-format');
                closeExportMenu();
                exportBook(format);
            });
        });

        document.addEventListener('click', function (e) {
            if (!menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
                closeExportMenu();
            }
            if (activeMarkerMenu && !activeMarkerMenu.contains(e.target) &&
                !e.target.closest('.nav-chapter-marker')) {
                closeMarkerMenu();
            }
        });
    }

    function addChapterViaApi() {
        if (state.locked) {
            alert('Разблокируйте редактирование (🔓), чтобы добавить главу');
            return;
        }
        setSaveStatus('saving');
        flushSave().then(function () {
            return apiFetch('/api/v1/chapters', {
                method: 'POST',
                body: { title: 'Новая глава', emoji: '🟢' },
            });
        }).then(function (data) {
            var ch = data.chapter;
            return loadBook().then(function () {
                var nav = document.querySelector(
                    '#nav-chapters-root .nav-chapter-wrap[data-ch-id="' + ch.ch_id + '"] .nav-chapter-main'
                );
                openChapter(ch.ch_id, nav);
                setTimeout(function () { focusChapterBody(ch.ch_id); }, 100);
                setSaveStatus('saved');
            });
        }).catch(function () {
            setSaveStatus('error');
            alert('Не удалось создать главу');
        });
    }

    function bindAddChapter() {
        var btn = document.getElementById('btn-add-chapter');
        if (!btn || btn.__bookhubBound) return;
        btn.__bookhubBound = true;
        btn.__boundAdd = true;
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            addChapterViaApi();
        }, true);
    }

    function bindImport() {
        var openBtn = document.getElementById('btn-import-draft');
        var modal = document.getElementById('import-modal');
        var form = document.getElementById('import-form');
        var cancel = document.getElementById('import-cancel');
        if (!openBtn || !modal || !form) return;

        openBtn.addEventListener('click', function () {
            modal.style.display = 'flex';
        });
        if (cancel) cancel.addEventListener('click', function () {
            modal.style.display = 'none';
            form.reset();
        });
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var fileInput = document.getElementById('import-file');
            if (!fileInput || !fileInput.files.length) return;
            var fd = new FormData();
            fd.append('file', fileInput.files[0]);
            setSaveStatus('saving');
            fetch('/api/v1/import?replace=false', {
                method: 'POST',
                credentials: 'include',
                body: fd,
            })
                .then(function (res) {
                    if (!res.ok) throw new Error('import failed');
                    return res.json();
                })
                .then(function () {
                    modal.style.display = 'none';
                    form.reset();
                    return loadBook();
                })
                .then(function () { setSaveStatus('saved'); })
                .catch(function () {
                    setSaveStatus('error');
                    alert('Импорт не удался');
                });
        });
    }

    function formatProfileDate(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleDateString('ru-RU', {
                day: 'numeric', month: 'long', year: 'numeric',
            });
        } catch (e) {
            return iso;
        }
    }

    function formatNumber(n) {
        return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
    }

    function refreshProfileModal() {
        return apiFetch('/api/v1/me/profile').then(function (data) {
            renderProfileModal(data);
            return data;
        });
    }

    function showDeleteBookModal(bookTitle) {
        return new Promise(function (resolve) {
            var modal = document.getElementById('delete-book-modal');
            var nameEl = document.getElementById('delete-book-modal-name');
            var cancelBtn = document.getElementById('delete-book-modal-cancel');
            var confirmBtn = document.getElementById('delete-book-modal-confirm');
            if (!modal || !cancelBtn || !confirmBtn) {
                resolve(window.confirm('Удалить книгу «' + bookTitle + '»?'));
                return;
            }
            if (nameEl) nameEl.textContent = bookTitle;

            function close(result) {
                modal.style.display = 'none';
                cancelBtn.removeEventListener('click', onCancel);
                confirmBtn.removeEventListener('click', onConfirm);
                modal.removeEventListener('click', onBackdrop);
                document.removeEventListener('keydown', onKey);
                resolve(result);
            }
            function onCancel() { close(false); }
            function onConfirm() { close(true); }
            function onBackdrop(e) { if (e.target === modal) close(false); }
            function onKey(e) { if (e.key === 'Escape') close(false); }

            cancelBtn.addEventListener('click', onCancel);
            confirmBtn.addEventListener('click', onConfirm);
            modal.addEventListener('click', onBackdrop);
            document.addEventListener('keydown', onKey);
            modal.style.display = 'flex';
            cancelBtn.focus();
        });
    }

    function switchActiveBook(bookId) {
        return apiFetch('/api/v1/me/active-book', {
            method: 'PATCH',
            body: { bookId: bookId },
        }).then(function () {
            try { sessionStorage.removeItem(LS_ACTIVE); } catch (e) {}
            return loadBook();
        }).then(function () {
            return refreshProfileModal();
        });
    }

    function addBookFromProfile() {
        var input = document.getElementById('profile-new-book-title');
        var title = input ? input.value.trim() : '';
        if (!title) title = 'Новая книга';
        return apiFetch('/api/v1/books', {
            method: 'POST',
            body: { title: title },
        }).then(function () {
            if (input) input.value = '';
            return loadBook();
        }).then(function () {
            return refreshProfileModal();
        }).catch(function () {
            alert('Не удалось создать книгу');
        });
    }

    function deleteBookFromProfile(bookId, bookTitle, booksCount) {
        if (booksCount <= 1) {
            alert('Нельзя удалить единственную книгу');
            return;
        }
        showDeleteBookModal(bookTitle).then(function (ok) {
            if (!ok) return;
            apiFetch('/api/v1/books/' + bookId, { method: 'DELETE' })
                .then(function () {
                    try { sessionStorage.removeItem(LS_ACTIVE); } catch (e) {}
                    return loadBook();
                })
                .then(function () {
                    return refreshProfileModal();
                })
                .catch(function () {
                    alert('Не удалось удалить книгу');
                });
        });
    }

    function renderProfileModal(data) {
        var p = data.profile || {};
        var s = data.stats || {};
        document.getElementById('profile-last-name').value = p.last_name || '';
        document.getElementById('profile-first-name').value = p.first_name || '';
        document.getElementById('profile-patronymic').value = p.patronymic || '';

        var meta = document.getElementById('profile-meta');
        if (meta) {
            meta.innerHTML =
                '<div><strong>Логин:</strong> ' + (p.login || '—') + '</div>' +
                '<div><strong>Телефон:</strong> ' + (p.phone_e164 || '—') + '</div>' +
                '<div><strong>В BookHub с:</strong> ' + formatProfileDate(p.registered_at) + '</div>' +
                '<div><strong>Пишу с:</strong> ' + formatProfileDate(p.writing_started_at) + '</div>' +
                '<div><strong>Последнее сохранение:</strong> ' + formatProfileDate(s.last_edited_at) + '</div>';
        }

        var statsEl = document.getElementById('profile-stats');
        if (statsEl) {
            statsEl.innerHTML =
                '<div class="profile-stat"><span class="profile-stat-value">' + formatNumber(s.pages || 0) + '</span><span class="profile-stat-label">страниц</span></div>' +
                '<div class="profile-stat"><span class="profile-stat-value">' + formatNumber(s.words || 0) + '</span><span class="profile-stat-label">слов</span></div>' +
                '<div class="profile-stat"><span class="profile-stat-value">' + formatNumber(s.characters || 0) + '</span><span class="profile-stat-label">знаков</span></div>' +
                '<div class="profile-stat"><span class="profile-stat-value">' + (s.books_count || 0) + '</span><span class="profile-stat-label">книг</span></div>' +
                '<div class="profile-stat"><span class="profile-stat-value">' + (s.chapters_count || 0) + '</span><span class="profile-stat-label">глав</span></div>';
        }

        var booksEl = document.getElementById('profile-books-list');
        if (booksEl) {
            booksEl.innerHTML = '';
            var books = data.books || [];
            books.forEach(function (b) {
                var item = document.createElement('div');
                item.className = 'profile-book-item' + (b.is_active ? ' active' : '');

                var main = document.createElement('div');
                main.className = 'profile-book-main';
                main.innerHTML =
                    '<div class="profile-book-title">' + (b.is_active ? '● ' : '') + b.title + '</div>' +
                    '<div class="profile-book-meta">' +
                    b.chapters_count + ' глав · ' + formatNumber(b.pages) + ' стр. · ' +
                    formatNumber(b.words) + ' сл. · ' + formatNumber(b.characters) + ' зн.' +
                    '</div>';
                main.addEventListener('click', function () {
                    if (b.is_active) return;
                    switchActiveBook(b.id).catch(function () {
                        alert('Не удалось переключить книгу');
                    });
                });

                item.appendChild(main);

                if (b.role === 'owner' && books.length > 1) {
                    var delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = 'profile-book-delete';
                    delBtn.title = 'Удалить книгу';
                    delBtn.setAttribute('aria-label', 'Удалить книгу');
                    delBtn.textContent = '×';
                    delBtn.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        deleteBookFromProfile(b.id, b.title, books.length);
                    });
                    item.appendChild(delBtn);
                }

                booksEl.appendChild(item);
            });
            if (!books.length) {
                booksEl.innerHTML = '<div class="profile-book-meta">Книг пока нет</div>';
            }
        }
    }

    function openProfileModal() {
        var modal = document.getElementById('profile-modal');
        if (!modal) return;
        apiFetch('/api/v1/me/profile').then(function (data) {
            renderProfileModal(data);
            modal.style.display = 'flex';
        }).catch(function () {
            alert('Не удалось загрузить профиль');
        });
    }

    function closeProfileModal() {
        var modal = document.getElementById('profile-modal');
        if (modal) modal.style.display = 'none';
    }

    function bindProfile() {
        var btn = document.getElementById('btn-profile');
        var modal = document.getElementById('profile-modal');
        var form = document.getElementById('profile-form');
        var cancel = document.getElementById('profile-cancel');
        if (!btn || !modal || !form || btn.__bound) return;
        btn.__bound = true;

        btn.addEventListener('click', function () {
            closeExportMenu();
            openProfileModal();
        });

        if (cancel) {
            cancel.addEventListener('click', function () {
                closeProfileModal();
            });
        }

        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeProfileModal();
        });

        var addBookBtn = document.getElementById('profile-add-book');
        var newBookInput = document.getElementById('profile-new-book-title');
        if (addBookBtn && !addBookBtn.__bound) {
            addBookBtn.__bound = true;
            addBookBtn.addEventListener('click', function () {
                addBookFromProfile();
            });
        }
        if (newBookInput && !newBookInput.__bound) {
            newBookInput.__bound = true;
            newBookInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    addBookFromProfile();
                }
            });
        }

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            apiFetch('/api/v1/me/profile', {
                method: 'PATCH',
                body: {
                    last_name: document.getElementById('profile-last-name').value.trim(),
                    first_name: document.getElementById('profile-first-name').value.trim(),
                    patronymic: document.getElementById('profile-patronymic').value.trim(),
                },
            }).then(function (data) {
                renderProfileModal(data);
                closeProfileModal();
            }).catch(function () {
                alert('Не удалось сохранить профиль');
            });
        });
    }

    function init() {
        bindLogin();
        bindTheme();
        bindSidebarEdge();
        bindBookAccordion();
        bindLock();
        bindChapterDnD();
        bindExport();
        bindImport();
        bindAddChapter();
        bindProfile();
        bindServicePanels();
        bindAppVersion();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.BookHub = {
        loadBook: loadBook,
        openChapter: openChapter,
        getState: function () { return state; },
    };
})();
