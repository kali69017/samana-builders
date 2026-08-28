// ============================================================
        // THEME SWITCHER — per-user server preference
        // ============================================================
        (function() {
            var serverTheme = window.SAMANA_THEME || 'professional-blue';
            var isAuthed = window.SAMANA_IS_AUTHED === true;
            var savedTheme = isAuthed ? serverTheme : (localStorage.getItem('samana-theme') || serverTheme);
            document.documentElement.setAttribute('data-theme', savedTheme);

            document.querySelectorAll('.theme-btn').forEach(function(btn) {
                btn.addEventListener('click', function() {
                    setTheme(this.getAttribute('data-theme'));
                });
            });

            function setTheme(theme) {
                document.documentElement.classList.add('theme-transitioning');
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('samana-theme', theme);

                document.querySelectorAll('.theme-btn').forEach(function(b) {
                    b.classList.toggle('active', b.getAttribute('data-theme') === theme);
                });

                setTimeout(function() {
                    document.documentElement.classList.remove('theme-transitioning');
                }, 500);

                // Persist to server
                try {
                    var xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/save-theme/', true);
                    xhr.setRequestHeader('Content-Type', 'application/json');
                    xhr.setRequestHeader('X-CSRFToken', getCookie('csrftoken'));
                    xhr.send(JSON.stringify({theme: theme}));
                } catch(e) {}
            }

            function getCookie(name) {
                var v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
                return v ? v.pop() : '';
            }

            document.querySelectorAll('.theme-btn').forEach(function(b) {
                if (b.getAttribute('data-theme') === savedTheme) b.classList.add('active');
            });
        })();

        // ============================================================
        // SIDEBAR TOGGLE (mobile)
        // ============================================================
        function toggleSidebar() {
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.querySelector('.sidebar-overlay');
            sidebar.classList.toggle('active');
            if (overlay) overlay.classList.toggle('active');
        }

        function closeSidebar() {
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.querySelector('.sidebar-overlay');
            sidebar.classList.remove('active');
            if (overlay) overlay.classList.remove('active');
        }

        // ============================================================
        // AUTO-HIDE ALERTS
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.toast').forEach(function(toast) {
                setTimeout(function() {
                    toast.classList.add('removing');
                    setTimeout(function() { toast.remove(); }, 400);
                }, 4000);
            });
        });

        // ============================================================
        // ANIMATED COUNTERS
        // ============================================================
        function animateCounter(el) {
            const target = parseInt(el.getAttribute('data-target'));
            if (!target || isNaN(target)) return;
            const duration = 1000;
            const start = 0;
            const startTime = performance.now();

            function update(currentTime) {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                // Ease out cubic
                const eased = 1 - Math.pow(1 - progress, 3);
                const current = Math.floor(start + (target - start) * eased);
                el.textContent = current.toLocaleString();
                if (progress < 1) {
                    requestAnimationFrame(update);
                } else {
                    el.textContent = target.toLocaleString();
                }
            }
            requestAnimationFrame(update);
        }

        // Intersection Observer for counters
        document.addEventListener('DOMContentLoaded', function() {
            const counterObserver = new IntersectionObserver(function(entries) {
                entries.forEach(function(entry) {
                    if (entry.isIntersecting) {
                        animateCounter(entry.target);
                        counterObserver.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.5 });

            document.querySelectorAll('.stat-value[data-target]').forEach(function(el) {
                counterObserver.observe(el);
            });
        });

        // ============================================================
        // TABLE SORTING
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('table.sortable').forEach(function(table) {
                const headers = table.querySelectorAll('thead th');
                headers.forEach(function(header, index) {
                    if (header.classList.contains('no-sort')) return;
                    header.style.cursor = 'pointer';
                    header.innerHTML += ' <span class="sort-icon">&#8597;</span>';
                    header.addEventListener('click', function() {
                        sortTable(table, index, header);
                    });
                });
            });
        });

        function sortTable(table, colIndex, header) {
            const tbody = table.querySelector('tbody');
            if (!tbody) return;
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const isAsc = header.classList.contains('sorted-asc');

            // Clear sorting
            table.querySelectorAll('thead th').forEach(function(th) {
                th.classList.remove('sorted', 'sorted-asc', 'sorted-desc');
            });

            rows.sort(function(a, b) {
                const aVal = a.cells[colIndex]?.textContent.trim() || '';
                const bVal = b.cells[colIndex]?.textContent.trim() || '';
                const aNum = parseFloat(aVal.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bVal.replace(/[^0-9.-]/g, ''));
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAsc ? bNum - aNum : aNum - bNum;
                }
                return isAsc ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
            });

            if (isAsc) {
                header.classList.add('sorted', 'sorted-desc');
            } else {
                header.classList.add('sorted', 'sorted-asc');
            }

            rows.forEach(function(row) { tbody.appendChild(row); });
        }

        // ============================================================
        // FORM SUBMIT WITH LOADING SPINNER
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('form').forEach(function(form) {
                form.addEventListener('submit', function() {
                    const submitBtn = form.querySelector('button[type="submit"]');
                    if (submitBtn && !submitBtn.classList.contains('no-loading')) {
                        submitBtn.classList.add('loading');
                        const spinner = submitBtn.querySelector('.spinner');
                        if (!spinner) {
                            const s = document.createElement('span');
                            s.className = 'spinner';
                            submitBtn.insertBefore(s, submitBtn.firstChild);
                        }
                    }
                });
            });
        });

        // ============================================================
        // TABS
        // ============================================================
        function switchTab(tabGroup, tabName) {
            const container = tabGroup.closest('.tabs') || tabGroup.parentElement;
            const tabs = container.querySelectorAll('.tab');
            const contents = container.parentElement.querySelectorAll('.tab-content');

            tabs.forEach(function(t) { t.classList.remove('active'); });
            tabGroup.classList.add('active');

            contents.forEach(function(c) {
                c.classList.remove('active');
                if (c.id === tabName || c.getAttribute('data-tab') === tabName) {
                    c.classList.add('active');
                }
            });
        }

        // ============================================================
        // TOAST HELPER
        // ============================================================
        function showToast(message, type) {
            type = type || 'info';
            const container = document.getElementById('toastContainer');
            if (!container) return;
            const toast = document.createElement('div');
            toast.className = 'toast';
            const colors = {
                success: 'var(--accent-green)',
                error: 'var(--accent-red)',
                warning: 'var(--accent-amber)',
                info: 'var(--primary)'
            };
            toast.style.background = colors[type] || colors.info;
            toast.style.color = 'white';
            toast.innerHTML = '<span>' + message + '</span><button class="close-btn" onclick="this.parentElement.remove()" style="margin-left:auto; background:none; border:none; color:white; cursor:pointer; font-size:18px;">&times;</button>';
            container.appendChild(toast);
            setTimeout(function() {
                toast.classList.add('removing');
                setTimeout(function() { toast.remove(); }, 400);
            }, 4000);
        }

        // ============================================================
        // CONFIRM DIALOG HELPER
        // ============================================================
        function showConfirm(message, onConfirm) {
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            overlay.innerHTML = '<div class="modal">' +
                '<div class="modal-icon">⚠️</div>' +
                '<h3>Confirm Action</h3>' +
                '<p>' + message + '</p>' +
                '<div class="modal-actions">' +
                '<button class="btn btn-danger" id="confirmYes">Yes, Proceed</button>' +
                '<button class="btn btn-secondary" id="confirmNo">Cancel</button>' +
                '</div></div>';
            document.body.appendChild(overlay);
            document.getElementById('confirmYes').addEventListener('click', function() {
                document.body.removeChild(overlay);
                if (onConfirm) onConfirm();
            });
            document.getElementById('confirmNo').addEventListener('click', function() {
                document.body.removeChild(overlay);
            });
            overlay.addEventListener('click', function(e) {
                if (e.target === overlay) document.body.removeChild(overlay);
            });
        }

        // ============================================================
        // SEARCH FILTER FOR TABLES
        // ============================================================
        function filterTable(inputId, tableId) {
            const input = document.getElementById(inputId);
            const table = document.getElementById(tableId);
            if (!input || !table) return;
            const filter = input.value.toLowerCase();
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(function(row) {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(filter) ? '' : 'none';
            });
        }

        // ============================================================
        // FORMAT CURRENCY
        // ============================================================
        function formatCurrency(amount) {
            return 'Rs. ' + Number(amount).toLocaleString('en-IN');
        }

        // ============================================================
        // FLOATING LABEL FALLBACK (reliable across all browsers)
        // ============================================================
        function syncFloatingLabels() {
            document.querySelectorAll('.floating-group').forEach(function(group) {
                var control = group.querySelector('input, textarea, select');
                if (!control) return;
                group.classList.toggle('filled', control.value.trim() !== '');
            });
        }
        document.addEventListener('input', syncFloatingLabels);
        document.addEventListener('change', syncFloatingLabels);
        document.addEventListener('DOMContentLoaded', syncFloatingLabels);
        if (document.readyState !== 'loading') syncFloatingLabels();

        console.log('Samana Builders ERP — Theme System Active');
        console.log('Current theme:', document.documentElement.getAttribute('data-theme'));

// ============================================================
// TOPBAR: sync page title + close user menu on outside click
// ============================================================
document.addEventListener('DOMContentLoaded', function() {
    var h1 = document.querySelector('.page-header h1');
    var title = document.querySelector('.topbar-title');
    if (h1 && title) title.textContent = h1.textContent.trim();

    // Close user menu on outside click
    document.addEventListener('click', function(e) {
        var menu = document.getElementById('userMenu');
        if (menu && menu.classList.contains('open') && !menu.contains(e.target)) {
            menu.classList.remove('open');
        }
    });

    // ============================================================
    // AUTO COLLAPSE: any table with more than 5 rows shows the
    // first 5 + a "View More / View Less" toggle in its card header.
    // Wires existing toggle buttons as well as creating new ones,
    // so templates can pre-mark tables (class="pr-collapsible")
    // and pre-place a button (id="*Toggle") without extra JS.
    // ============================================================
    document.querySelectorAll('table.sortable tbody').forEach(function(body) {
        var rows = body.querySelectorAll('tr').length;
        if (rows <= 5) return;
        if (body.dataset.collapseWired) return; // already bound

        var card = body.closest('.card');
        var header = card ? card.querySelector('.card-header') : null;

        // reuse an existing toggle button inside the card header if present
        var btn = header ? header.querySelector('.table-collapse-toggle, [id$="Toggle"]') : null;
        if (!btn) {
            btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-ghost table-collapse-toggle';
            btn.textContent = 'View More';
            if (header) {
                var actions = header.querySelector('.card-actions');
                if (actions) {
                    actions.appendChild(btn);
                } else {
                    var wrap = document.createElement('div');
                    wrap.className = 'card-actions';
                    wrap.appendChild(btn);
                    header.appendChild(wrap);
                }
            } else if (card) {
                var container = body.closest('.table-container') || body;
                container.parentNode.insertBefore(btn, container);
            }
        }

        // only collapse if not already marked
        if (!body.classList.contains('pr-collapsible')) {
            body.classList.add('pr-collapsible');
        }

        btn.addEventListener('click', function() {
            var expanded = body.classList.toggle('expanded');
            btn.textContent = expanded ? 'View Less' : 'View More';
        });
        body.dataset.collapseWired = '1';
    });
});
