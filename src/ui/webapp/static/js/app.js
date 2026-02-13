// CinemaCal Webapp - JavaScript

class CinemaCalApp {
    constructor() {
        this.screenings = [];
        this.filteredScreenings = [];
        this.selectedIds = new Set();
        this.expandedGroups = new Set();  // movie titles that are expanded; default all minimized
        this.currentJobId = null;
        this.pollInterval = null;
        this.googleCalendarConfigured = false;
        this.currentView = 'table';  // 'table' | 'calendar'
        this.calendarEvents = [];
        this.screeningIdToEventId = {};
        this.eventIdToScreeningId = {};
        this.calendarWeekStart = null;  // Sunday 00:00 of the displayed week
        this.calendarEventsRange = null;  // { timeMin, timeMax } for cached events (days ahead)
        this.CALENDAR_HOUR_HEIGHT = 48;
        this.MINUTES_PER_DAY = 24 * 60;
        this.calendarList = [];
        this.selectedCalendarIds = [];
        this.targetCalendarId = null;
        this.targetCalendarSummary = '';
        this.CALENDAR_IDS_STORAGE_KEY = 'cinemacal_selected_calendar_ids';
        this.CALENDAR_DEFAULT_ALL_VERSION = 2;
        this.overlapGroupPrimary = {};  // groupKey -> index of primary in sorted group
        this.overlapGroupBack = {};     // groupKey -> index to put at very back (previous primary after a click)

        this.init();
    }
    
    getStartOfWeek(date) {
        const d = new Date(date);
        d.setHours(0, 0, 0, 0);
        const day = d.getDay();
        d.setDate(d.getDate() - day);
        return d;
    }
    
    getDateKey(d) {
        const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    }

    init() {
        this.setupEventListeners();
        this.checkConfig();
    }

    setupEventListeners() {
        // Scrape button
        document.getElementById('btn-scrape').addEventListener('click', () => this.startScrape());
        
        // Export buttons
        document.getElementById('btn-export-ics').addEventListener('click', () => this.exportICS());
        document.getElementById('btn-export-google').addEventListener('click', () => this.exportGoogle());
        
        // Filters
        document.getElementById('filter-venue').addEventListener('change', () => this.applyFilters());
        document.getElementById('filter-search').addEventListener('input', () => this.applyFilters());
        document.getElementById('filter-remove-regular-coolidge').addEventListener('change', () => this.applyFilters());
        
        // Selection
        document.getElementById('btn-select-all').addEventListener('click', () => this.selectAll());
        document.getElementById('btn-deselect-all').addEventListener('click', () => this.deselectAll());
        document.getElementById('select-all-checkbox').addEventListener('change', (e) => {
            if (e.target.checked) {
                this.selectAll();
            } else {
                this.deselectAll();
            }
        });
        
        // Modal
        document.getElementById('modal-close').addEventListener('click', () => this.closeModal());
        document.getElementById('modal-ok').addEventListener('click', () => this.closeModal());
        
        // View toggle
        document.getElementById('view-table').addEventListener('click', () => this.switchView('table'));
        document.getElementById('view-calendar').addEventListener('click', () => this.switchView('calendar'));
    }
    
    switchView(view) {
        this.currentView = view;
        const tableView = document.getElementById('table-view');
        const calendarView = document.getElementById('calendar-view');
        const btnTable = document.getElementById('view-table');
        const btnCalendar = document.getElementById('view-calendar');
        if (view === 'table') {
            tableView.style.display = 'block';
            calendarView.style.display = 'none';
            btnTable.classList.add('active');
            btnTable.setAttribute('aria-pressed', 'true');
            btnCalendar.classList.remove('active');
            btnCalendar.setAttribute('aria-pressed', 'false');
        } else {
            tableView.style.display = 'none';
            calendarView.style.display = 'block';
            btnTable.classList.remove('active');
            btnTable.setAttribute('aria-pressed', 'false');
            btnCalendar.classList.add('active');
            btnCalendar.setAttribute('aria-pressed', 'true');
            this.fetchCalendarEventsAndRender();
        }
    }
    
    getCalendarDateRange() {
        if (!this.calendarWeekStart) {
            this.calendarWeekStart = this.getStartOfWeek(new Date());
        }
        const start = new Date(this.calendarWeekStart);
        const end = new Date(start);
        end.setDate(end.getDate() + 7);
        return { start, end };
    }
    
    calendarPrevWeek() {
        const w = new Date(this.calendarWeekStart);
        w.setDate(w.getDate() - 7);
        this.calendarWeekStart = w;
        this.fetchCalendarEventsAndRender();
    }
    
    calendarNextWeek() {
        const w = new Date(this.calendarWeekStart);
        w.setDate(w.getDate() + 7);
        this.calendarWeekStart = w;
        this.fetchCalendarEventsAndRender();
    }
    
    async fetchCalendarListAndTarget() {
        if (!this.googleCalendarConfigured) return;
        try {
            const [listRes, targetRes] = await Promise.all([
                fetch('/api/calendar/list'),
                fetch('/api/calendar/target'),
            ]);
            const listData = await listRes.json();
            const targetData = await targetRes.json();
            if (listRes.ok && listData.calendars) this.calendarList = listData.calendars;
            if (targetRes.ok && targetData.calendar_id) {
                this.targetCalendarId = targetData.calendar_id;
                this.targetCalendarSummary = targetData.summary || targetData.calendar_id;
            }
            const stored = localStorage.getItem(this.CALENDAR_IDS_STORAGE_KEY);
            const versionKey = this.CALENDAR_IDS_STORAGE_KEY + '_version';
            const version = parseInt(localStorage.getItem(versionKey), 10) || 1;
            if (version < this.CALENDAR_DEFAULT_ALL_VERSION && this.calendarList.length) {
                this.selectedCalendarIds = this.calendarList.map(c => c.id);
                this.persistSelectedCalendarIds();
                try { localStorage.setItem(versionKey, String(this.CALENDAR_DEFAULT_ALL_VERSION)); } catch (_) {}
            } else if (stored) {
                try {
                    const ids = JSON.parse(stored);
                    if (Array.isArray(ids) && ids.length) this.selectedCalendarIds = ids;
                } catch (_) {}
            }
            if (this.selectedCalendarIds.length === 0 && this.calendarList.length) {
                this.selectedCalendarIds = this.calendarList.map(c => c.id);
                this.persistSelectedCalendarIds();
                try { localStorage.setItem(this.CALENDAR_IDS_STORAGE_KEY + '_version', String(this.CALENDAR_DEFAULT_ALL_VERSION)); } catch (_) {}
            }
        } catch (err) {
            console.error('Error fetching calendar list/target:', err);
        }
    }

    persistSelectedCalendarIds() {
        try {
            localStorage.setItem(this.CALENDAR_IDS_STORAGE_KEY, JSON.stringify(this.selectedCalendarIds));
        } catch (_) {}
    }

    async fetchCalendarEventsAndRender() {
        const content = document.getElementById('calendar-view-content');
        if (this.screenings.length === 0) {
            content.innerHTML = '<p class="calendar-placeholder">Scrape screenings first, then switch to Calendar view.</p>';
            return;
        }
        await this.fetchCalendarListAndTarget();
        const { start: weekStart, end: weekEnd } = this.getCalendarDateRange();
        const weekStartStr = weekStart.toISOString().slice(0, 10);
        const weekEndDate = new Date(weekEnd);
        weekEndDate.setDate(weekEndDate.getDate() - 1);
        const weekEndStr = weekEndDate.toISOString().slice(0, 10);
        const daysAhead = parseInt(document.getElementById('days-ahead').value, 10) || 30;
        const rangeStart = new Date();
        rangeStart.setHours(0, 0, 0, 0);
        const rangeEnd = new Date(rangeStart);
        rangeEnd.setDate(rangeEnd.getDate() + daysAhead);
        const rangeTimeMin = rangeStart.toISOString().slice(0, 10);
        const rangeTimeMax = rangeEnd.toISOString().slice(0, 10);
        const inRange = this.calendarEventsRange &&
            weekStartStr >= this.calendarEventsRange.timeMin &&
            weekEndStr <= this.calendarEventsRange.timeMax;
        const needFetch = this.googleCalendarConfigured && (!this.calendarEventsRange || !inRange);

        if (this.googleCalendarConfigured && needFetch) {
            content.innerHTML = '<p class="calendar-placeholder">Loading calendar events…</p>';
            try {
                let url = `/api/calendar/events?time_min=${encodeURIComponent(rangeTimeMin)}&time_max=${encodeURIComponent(rangeTimeMax)}`;
                if (this.selectedCalendarIds.length) {
                    url += '&calendar_ids=' + encodeURIComponent(this.selectedCalendarIds.join(','));
                }
                const response = await fetch(url);
                const data = await response.json();
                if (!response.ok) {
                    content.innerHTML = `<p class="calendar-placeholder calendar-error">${this.escapeHtml(data.error || 'Failed to load calendar events')}</p>`;
                    return;
                }
                this.calendarEvents = data.events || [];
                this.calendarEventsRange = { timeMin: rangeTimeMin, timeMax: rangeTimeMax };
                this.screeningIdToEventId = {};
                this.eventIdToScreeningId = {};
                this.calendarEvents.forEach(ev => {
                    const sid = ev.cinemacal_screening_id;
                    if (sid && ev.id) {
                        this.screeningIdToEventId[sid] = ev.id;
                        this.eventIdToScreeningId[ev.id] = sid;
                    }
                });
                this.renderCalendarView();
            } catch (err) {
                content.innerHTML = `<p class="calendar-placeholder calendar-error">${this.escapeHtml(err.message || 'Failed to load calendar events')}</p>`;
            }
        } else {
            if (this.googleCalendarConfigured) {
                this.screeningIdToEventId = {};
                this.eventIdToScreeningId = {};
                this.calendarEvents.forEach(ev => {
                    const sid = ev.cinemacal_screening_id;
                    if (sid && ev.id) {
                        this.screeningIdToEventId[sid] = ev.id;
                        this.eventIdToScreeningId[ev.id] = sid;
                    }
                });
            } else {
                this.calendarEvents = [];
                this.screeningIdToEventId = {};
                this.eventIdToScreeningId = {};
            }
            this.renderCalendarView();
        }
    }
    
    isAllDayEvent(ev) {
        const start = ev.start && ev.start.trim();
        if (!start) return true;
        return start.length <= 10 || !start.includes('T');
    }
    
    eventToBlock(ev) {
        const start = new Date(ev.start);
        const endStr = ev.end && ev.end.trim();
        const end = endStr ? new Date(endStr) : new Date(start.getTime() + 60 * 60 * 1000);
        const dayKey = this.getDateKey(start);
        const startM = start.getHours() * 60 + start.getMinutes() + start.getSeconds() / 60;
        const duration = Math.max(15, (end.getTime() - start.getTime()) / (60 * 1000));
        const endMinutes = startM + duration;
        const sublabel = ev.calendar_summary ? ev.calendar_summary : '';
        return { start, end: new Date(start.getTime() + duration * 60 * 1000), summary: ev.summary || '', sublabel, type: 'user', eventId: ev.id, calendarId: ev.calendar_id || 'primary', dayKey, startMinutes: startM, endMinutes };
    }
    
    screeningToBlock(s) {
        const start = new Date(s.date + 'T' + s.time);
        const durationMin = s.runtime_minutes || 120;
        const end = new Date(start.getTime() + durationMin * 60 * 1000);
        const startM = start.getHours() * 60 + start.getMinutes() + start.getSeconds() / 60;
        const endMinutes = startM + durationMin;
        const sublabel = (s.venue || '') + (s.special_attributes && s.special_attributes.length ? ' (' + s.special_attributes.join(', ') + ')' : '');
        const eventId = this.screeningIdToEventId[s.unique_id];
        const calEv = eventId ? this.calendarEvents.find(e => e.id === eventId) : null;
        const calendarId = calEv && calEv.calendar_id ? calEv.calendar_id : (this.targetCalendarId || 'primary');
        return { start, end, summary: s.title, sublabel, type: 'screening', screening: s, uniqueId: s.unique_id, eventId, calendarId, dayKey: this.getDateKey(start), startMinutes: startM, endMinutes };
    }
    
    assignOverlapColumns(blocks) {
        blocks.sort((a, b) => a.startMinutes - b.startMinutes);
        for (let i = 0; i < blocks.length; i++) {
            const b = blocks[i];
            const usedCols = new Set();
            for (let j = 0; j < i; j++) {
                const other = blocks[j];
                if (other.endMinutes > b.startMinutes && other.startMinutes < b.endMinutes)
                    usedCols.add(other.col);
            }
            let col = 0;
            while (usedCols.has(col)) col++;
            b.col = col;
        }
        blocks.forEach(b => {
            let maxColInGroup = b.col ?? 0;
            for (const other of blocks) {
                if (other === b) continue;
                if (other.endMinutes > b.startMinutes && other.startMinutes < b.endMinutes)
                    maxColInGroup = Math.max(maxColInGroup, other.col ?? 0);
            }
            b.totalCols = maxColInGroup + 1;
        });
    }

    getOverlappingBlocks(block, blocks) {
        return blocks.filter(other =>
            other.endMinutes > block.startMinutes && other.startMinutes < block.endMinutes
        ).sort((a, b) => a.startMinutes - b.startMinutes);
    }

    getOverlapGroupKey(blocks, group) {
        const parts = group.map(b => (b.uniqueId || b.eventId || '') + '_' + b.startMinutes);
        parts.sort();
        const dayKey = group[0] && group[0].dayKey ? group[0].dayKey : '';
        return dayKey + '_' + parts.join('|');
    }

    getStackOrder(group, primaryIndex, backIndex) {
        if (primaryIndex < 0 || primaryIndex >= group.length) return group.slice();
        const primary = group[primaryIndex];
        if (backIndex == null || backIndex === primaryIndex || backIndex < 0 || backIndex >= group.length) {
            const rest = group.filter((_, i) => i !== primaryIndex);
            return [...rest, primary];
        }
        const back = group[backIndex];
        const middle = group.filter((_, i) => i !== primaryIndex && i !== backIndex);
        return [back, ...middle, primary];
    }

    blockInnerContentHtml(block) {
        const durationMin = block.endMinutes - block.startMinutes;
        const timeStr = block.start.getHours() === 0 && block.start.getMinutes() === 0 ? '' : block.start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) + (durationMin >= 60 ? ' – ' + block.end.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '');
        let html = `<div class="calendar-block-title">${this.escapeHtml(block.summary)}</div>`;
        if (timeStr) html += `<div class="calendar-block-time">${this.escapeHtml(timeStr)}</div>`;
        if (block.sublabel) html += `<div class="calendar-block-sublabel">${this.escapeHtml(block.sublabel)}</div>`;
        if (block.type === 'screening') {
            const isOnCalendar = !!block.eventId;
            const btnClass = isOnCalendar ? 'btn-calendar-remove' : 'btn-calendar-add';
            const btnLabel = isOnCalendar ? 'Remove' : 'Add';
            const dataAttrs = isOnCalendar && block.calendarId
                ? `data-event-id="${this.escapeHtml(block.eventId)}" data-calendar-id="${this.escapeHtml(block.calendarId)}"`
                : (block.eventId ? `data-event-id="${this.escapeHtml(block.eventId)}"` : '');
            html += `<button type="button" class="btn btn-small ${btnClass} calendar-block-btn" data-unique-id="${this.escapeHtml(block.uniqueId)}" ${dataAttrs}>${this.escapeHtml(btnLabel)}</button>`;
        }
        return html;
    }
    
    renderCalendarView() {
        const content = document.getElementById('calendar-view-content');
        if (this.screenings.length === 0) {
            content.innerHTML = '<p class="calendar-placeholder">Scrape screenings first, then switch to Calendar view.</p>';
            return;
        }
        const { start: weekStart } = this.getCalendarDateRange();
        const dayDates = [];
        for (let i = 0; i < 7; i++) {
            const d = new Date(weekStart);
            d.setDate(d.getDate() + i);
            dayDates.push(d);
        }
        const dayKeys = dayDates.map(d => this.getDateKey(d));
        const blocksByDay = {};
        dayKeys.forEach(k => { blocksByDay[k] = []; });
        this.calendarEvents.forEach(ev => {
            if (this.isAllDayEvent(ev)) return;
            // Skip calendar events that are screenings we added — we show those as screening blocks only (with Add/Remove)
            if (ev.cinemacal_screening_id) return;
            const b = this.eventToBlock(ev);
            if (blocksByDay[b.dayKey]) blocksByDay[b.dayKey].push(b);
        });
        this.filteredScreenings.forEach(s => {
            if (!dayKeys.includes(s.date)) return;
            blocksByDay[s.date].push(this.screeningToBlock(s));
        });
        dayKeys.forEach(k => this.assignOverlapColumns(blocksByDay[k]));
        const DEFAULT_CALENDAR_START_HOUR = 8;
        let earliestStartMinutes = 24 * 60;
        dayKeys.forEach(k => {
            (blocksByDay[k] || []).forEach(b => {
                if (b.startMinutes < earliestStartMinutes) earliestStartMinutes = b.startMinutes;
            });
        });
        const startHour = earliestStartMinutes < DEFAULT_CALENDAR_START_HOUR * 60
            ? Math.floor(earliestStartMinutes / 60)
            : DEFAULT_CALENDAR_START_HOUR;
        const totalHours = 24 - startHour;
        const totalMinutes = totalHours * 60;
        const weekLabel = weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        const sunLabel = weekStart.toLocaleDateString('en-US', { weekday: 'short' });
        let html = '';
        if (this.googleCalendarConfigured && this.calendarList.length) {
            html += '<div class="calendar-selector">';
            html += '<span class="calendar-selector-label">Calendars to show:</span>';
            html += '<div class="calendar-selector-list">';
            this.calendarList.forEach(cal => {
                const name = cal.summaryOverride || cal.summary || cal.id;
                const checked = this.selectedCalendarIds.indexOf(cal.id) !== -1;
                html += `<label class="calendar-selector-item"><input type="checkbox" class="calendar-selector-checkbox" data-calendar-id="${this.escapeHtml(cal.id)}" ${checked ? 'checked' : ''}> ${this.escapeHtml(name)}</label>`;
            });
            html += '</div>';
            if (this.targetCalendarSummary) {
                html += `<p class="calendar-target-note">New events are added to: <strong>${this.escapeHtml(this.targetCalendarSummary)}</strong></p>`;
            }
            html += '</div>';
        }
        html += '<div class="calendar-week-nav">';
        html += `<button type="button" class="btn btn-small btn-week-nav" id="calendar-prev-week">← Previous week</button>`;
        html += `<span class="calendar-week-label">Week of ${this.escapeHtml(sunLabel + ' ' + weekLabel)}</span>`;
        html += `<button type="button" class="btn btn-small btn-week-nav" id="calendar-next-week">Next week →</button>`;
        html += '</div>';
        html += '<div class="calendar-week-grid">';
        html += '<div class="calendar-time-column">';
        for (let h = startHour; h < 24; h++) {
            const label = h === 0 ? '12:00 AM' : h < 12 ? h + ':00 AM' : (h === 12 ? '12:00 PM' : (h - 12) + ':00 PM');
            html += `<div class="calendar-time-slot" style="height: ${this.CALENDAR_HOUR_HEIGHT}px">${this.escapeHtml(label)}</div>`;
        }
        html += '</div>';
        html += '<div class="calendar-days-columns">';
        dayDates.forEach((dayDate, dayIndex) => {
            const key = dayKeys[dayIndex];
            const dayHeader = dayDate.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
            const blocks = blocksByDay[key] || [];
            const totalHeight = totalHours * this.CALENDAR_HOUR_HEIGHT;
            html += `<div class="calendar-day-column" data-date="${this.escapeHtml(key)}">`;
            html += `<div class="calendar-day-header">${this.escapeHtml(dayHeader)}</div>`;
            html += `<div class="calendar-day-column-inner" style="height: ${totalHeight}px">`;
            const PEEK_WIDTH_PX = 12;
            const renderedOverlapGroups = new Set();
            blocks.forEach(block => {
                const startMin = startHour * 60;
                const blockTop = Math.max(block.startMinutes, startMin);
                const blockBottom = Math.min(block.endMinutes, 24 * 60);
                if (blockBottom <= startMin) return;
                const totalCols = block.totalCols || 1;
                const col = block.col !== undefined ? block.col : 0;

                if (totalCols >= 2 && col !== 0) return;
                if (totalCols >= 2 && col === 0) {
                    const group = this.getOverlappingBlocks(block, blocks);
                    const groupKey = this.getOverlapGroupKey(blocks, group);
                    if (renderedOverlapGroups.has(groupKey)) return;
                    renderedOverlapGroups.add(groupKey);
                    const primaryIndex = this.overlapGroupPrimary[groupKey] !== undefined
                        ? this.overlapGroupPrimary[groupKey] : 0;
                    const primaryIdx = Math.max(0, Math.min(primaryIndex, group.length - 1));
                    const backIdx = this.overlapGroupBack[groupKey];
                    const stackOrder = this.getStackOrder(group, primaryIdx, backIdx);
                    if (backIdx !== undefined) delete this.overlapGroupBack[groupKey];
                    const groupTop = Math.min(...group.map(b => Math.max(b.startMinutes, startMin)));
                    const groupBottom = Math.max(...group.map(b => Math.min(b.endMinutes, 24 * 60)));
                    const groupTopPct = ((groupTop - startMin) / totalMinutes) * 100;
                    const groupHeightPct = ((groupBottom - groupTop) / totalMinutes) * 100;
                    const n = stackOrder.length;
                    const stackStyle = `top: ${groupTopPct}%; height: ${groupHeightPct}%; left: 0; width: 100%;`;
                    html += `<div class="calendar-block-stack" style="${stackStyle}" data-group-key="${this.escapeHtml(groupKey)}">`;
                    stackOrder.forEach((b, i) => {
                        const isPrimary = i === n - 1;
                        const groupIndex = group.indexOf(b);
                        const leftPx = i * PEEK_WIDTH_PX;
                        const widthPx = isPrimary ? `calc(100% - ${(n - 1) * PEEK_WIDTH_PX}px)` : PEEK_WIDTH_PX;
                        const stripStyle = `left: ${leftPx}px; width: ${widthPx}; z-index: ${i + 1};`;
                        const typeClass = b.type === 'screening' ? 'calendar-block-screening' : 'calendar-block-user';
                        html += `<div class="calendar-stack-strip" data-group-index="${groupIndex}" style="${stripStyle}" role="button" tabindex="0" aria-label="Event ${groupIndex + 1} of ${n}, click to bring to front">`;
                        html += `<div class="calendar-block ${typeClass}" title="${this.escapeHtml(b.summary + (b.sublabel ? ' ' + b.sublabel : ''))}">`;
                        html += this.blockInnerContentHtml(b);
                        html += '</div></div>';
                    });
                    html += '</div>';
                    return;
                }

                const topPct = ((blockTop - startMin) / totalMinutes) * 100;
                const visibleDuration = Math.max(0, blockBottom - blockTop);
                const heightPct = (visibleDuration / totalMinutes) * 100;
                const widthPct = 100 / totalCols;
                const leftPct = col * widthPct;
                const typeClass = block.type === 'screening' ? 'calendar-block-screening' : 'calendar-block-user';
                const style = `top: ${topPct}%; height: ${heightPct}%; left: ${leftPct}%; width: ${widthPct}%;`;
                html += `<div class="calendar-block ${typeClass}" style="${style}" title="${this.escapeHtml(block.summary + (block.sublabel ? ' ' + block.sublabel : ''))}">`;
                html += this.blockInnerContentHtml(block);
                html += '</div>';
            });
            html += '</div></div>';
        });
        html += '</div></div>';
        content.innerHTML = html;
        content.querySelectorAll('.calendar-selector-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const id = cb.dataset.calendarId;
                if (cb.checked) {
                    if (this.selectedCalendarIds.indexOf(id) === -1) this.selectedCalendarIds.push(id);
                } else {
                    this.selectedCalendarIds = this.selectedCalendarIds.filter(cid => cid !== id);
                }
                this.persistSelectedCalendarIds();
                this.fetchCalendarEventsAndRender();
            });
        });
        const prevBtn = document.getElementById('calendar-prev-week');
        const nextBtn = document.getElementById('calendar-next-week');
        if (prevBtn) prevBtn.addEventListener('click', () => this.calendarPrevWeek());
        if (nextBtn) nextBtn.addEventListener('click', () => this.calendarNextWeek());
        content.querySelectorAll('.calendar-block-btn.btn-calendar-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const uniqueId = btn.dataset.uniqueId;
                const screening = this.filteredScreenings.find(s => s.unique_id === uniqueId);
                if (screening) this.addScreeningToCalendar(screening, btn);
            });
        });
        content.querySelectorAll('.calendar-block-btn.btn-calendar-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const eventId = btn.dataset.eventId;
                const calendarId = btn.dataset.calendarId;
                if (eventId && calendarId) this.removeScreeningFromCalendar(eventId, calendarId);
                else if (eventId) this.removeScreeningFromCalendar(eventId, this.targetCalendarId || 'primary');
            });
        });
        this.initOverlapStacks(content);
    }

    bringEventToTopOfColumn(element) {
        const column = element.closest('.calendar-day-column-inner');
        if (!column) return;
        const siblings = column.querySelectorAll(':scope > .calendar-block-stack, :scope > .calendar-block');
        siblings.forEach(el => {
            el.style.zIndex = el === element ? '100' : '1';
        });
    }

    initOverlapStacks(container) {
        container.querySelectorAll('.calendar-block-stack').forEach(stack => {
            const strips = stack.querySelectorAll('.calendar-stack-strip');
            const groupKey = stack.dataset.groupKey;
            if (!groupKey || strips.length === 0) return;

            const handleStackClick = (e) => {
                if (e.target.closest('button')) return;
                const x = e.clientX;
                const y = e.clientY;
                const stripsArray = Array.from(strips);
                const sortedByZ = stripsArray.slice().sort((a, b) => {
                    const za = parseInt(a.style.zIndex || '0', 10);
                    const zb = parseInt(b.style.zIndex || '0', 10);
                    return zb - za;
                });
                let strip = null;
                for (const s of sortedByZ) {
                    const rect = s.getBoundingClientRect();
                    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
                        strip = s;
                        break;
                    }
                }
                if (!strip) return;
                const groupIndex = parseInt(strip.dataset.groupIndex, 10);
                if (Number.isNaN(groupIndex)) return;
                const currentPrimary = this.overlapGroupPrimary[groupKey];
                if (currentPrimary !== undefined && currentPrimary !== groupIndex) {
                    this.overlapGroupBack[groupKey] = currentPrimary;
                }
                this.overlapGroupPrimary[groupKey] = groupIndex;
                this.renderCalendarView();
                e.preventDefault();
                e.stopPropagation();
            };

            stack.addEventListener('click', handleStackClick, true);

            strips.forEach((strip) => {
                strip.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        const groupIndex = parseInt(strip.dataset.groupIndex, 10);
                        if (!Number.isNaN(groupIndex)) {
                            const currentPrimary = this.overlapGroupPrimary[groupKey];
                            if (currentPrimary !== undefined && currentPrimary !== groupIndex) {
                                this.overlapGroupBack[groupKey] = currentPrimary;
                            }
                            this.overlapGroupPrimary[groupKey] = groupIndex;
                            this.renderCalendarView();
                        }
                    }
                });
            });
        });

        container.querySelectorAll('.calendar-day-column-inner').forEach(column => {
            column.querySelectorAll(':scope > .calendar-block').forEach(block => {
                block.addEventListener('click', (e) => {
                    if (!e.target.closest('button')) this.bringEventToTopOfColumn(block);
                });
            });
        });
    }

    async addScreeningToCalendar(screening, buttonEl) {
        if (!this.googleCalendarConfigured) return;
        buttonEl.disabled = true;
        buttonEl.textContent = 'Adding…';
        try {
            const response = await fetch('/api/calendar/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(screening),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to add');
            const eventId = data.event_id;
            if (eventId) {
                this.screeningIdToEventId[screening.unique_id] = eventId;
                this.eventIdToScreeningId[eventId] = screening.unique_id;
                const summary = this.formatEventSummary(screening);
                const start = new Date(screening.date + 'T' + screening.time);
                const durationMin = screening.runtime_minutes || 120;
                const end = new Date(start.getTime() + durationMin * 60 * 1000);
                const calendarId = this.targetCalendarId || 'primary';
                this.calendarEvents.push({ id: eventId, summary, start: screening.date + 'T' + screening.time, end: end.toISOString(), cinemacal_screening_id: screening.unique_id, calendar_id: calendarId, calendar_summary: this.targetCalendarSummary || '' });
            }
            this.renderCalendarView();
        } catch (err) {
            alert('Failed to add to calendar: ' + err.message);
        } finally {
            buttonEl.disabled = false;
        }
    }
    
    async removeScreeningFromCalendar(eventId, calendarId) {
        if (!calendarId) calendarId = this.targetCalendarId || 'primary';
        try {
            const url = `/api/calendar/events/${encodeURIComponent(eventId)}?calendar_id=${encodeURIComponent(calendarId)}`;
            const response = await fetch(url, { method: 'DELETE' });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || 'Failed to remove');
            }
            const sid = this.eventIdToScreeningId[eventId];
            if (sid) {
                delete this.screeningIdToEventId[sid];
                delete this.eventIdToScreeningId[eventId];
            }
            this.calendarEvents = this.calendarEvents.filter(ev => ev.id !== eventId);
            this.renderCalendarView();
        } catch (err) {
            alert('Failed to remove from calendar: ' + err.message);
        }
    }

    async checkConfig() {
        try {
            const response = await fetch('/api/config');
            const data = await response.json();
            
            const btnGoogle = document.getElementById('btn-export-google');
            if (!data.google_calendar_configured) {
                this.googleCalendarConfigured = false;
                btnGoogle.disabled = true;
                btnGoogle.title = 'Google Calendar API not configured';
            } else {
                this.googleCalendarConfigured = true;
                btnGoogle.title = '';
                this.updateExportButtons();
            }
        } catch (error) {
            console.error('Error checking config:', error);
        }
    }

    async startScrape() {
        const btnScrape = document.getElementById('btn-scrape');
        btnScrape.disabled = true;
        
        // Get configuration
        const config = {
            days_ahead: parseInt(document.getElementById('days-ahead').value) || 30,
            enable_screen_boston: document.getElementById('source-screen-boston').checked,
            enable_coolidge: document.getElementById('source-coolidge').checked,
            enable_hfa: document.getElementById('source-hfa').checked,
            enable_brattle: document.getElementById('source-brattle').checked,
        };
        
        try {
            const response = await fetch('/api/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            
            if (!response.ok) {
                throw new Error('Failed to start scrape');
            }
            
            const data = await response.json();
            this.currentJobId = data.job_id;
            
            // Show progress
            this.showProgress(0, 'Starting scrape...');
            
            // Start polling
            this.startPolling();
            
        } catch (error) {
            this.updateStatus('Error: ' + error.message, 'error');
            btnScrape.disabled = false;
        }
    }

    startPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
        
        this.pollInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/scrape/${this.currentJobId}/status`);
                const data = await response.json();
                
                this.showProgress(data.progress, data.message);
                
                if (data.status === 'complete') {
                    clearInterval(this.pollInterval);
                    this.pollInterval = null;
                    
                    this.screenings = data.screenings || [];
                    this.selectedIds.clear();
                    this.expandedGroups.clear();  // default all groups minimized
                    
                    // Update venue filter
                    await this.updateVenueFilter();
                    
                    // Refresh display
                    this.applyFilters();
                    
                    // Enable export buttons if we have screenings
                    this.updateExportButtons();
                    
                    this.hideProgress();
                    this.updateStatus(`Found ${data.count} screenings. Select items and click 'Export to .ics'.`);
                    
                    document.getElementById('btn-scrape').disabled = false;
                    
                } else if (data.status === 'error') {
                    clearInterval(this.pollInterval);
                    this.pollInterval = null;
                    
                    this.hideProgress();
                    this.updateStatus('Error: ' + (data.error || 'Unknown error'), 'error');
                    document.getElementById('btn-scrape').disabled = false;
                }
                
            } catch (error) {
                console.error('Error polling status:', error);
            }
        }, 1500); // Poll every 1.5 seconds
    }

    showProgress(percent, message) {
        const container = document.getElementById('progress-container');
        const fill = document.getElementById('progress-fill');
        const msg = document.getElementById('progress-message');
        
        container.style.display = 'block';
        fill.style.width = percent + '%';
        msg.textContent = message;
    }

    hideProgress() {
        document.getElementById('progress-container').style.display = 'none';
    }

    async updateVenueFilter() {
        try {
            const response = await fetch(`/api/venues?job_id=${this.currentJobId}`);
            const data = await response.json();
            
            const select = document.getElementById('filter-venue');
            select.innerHTML = '<option value="All">All</option>';
            
            data.venues.forEach(venue => {
                const option = document.createElement('option');
                option.value = venue;
                option.textContent = venue;
                select.appendChild(option);
            });
            
        } catch (error) {
            console.error('Error updating venue filter:', error);
        }
    }

    applyFilters() {
        const venueFilter = document.getElementById('filter-venue').value;
        const searchFilter = document.getElementById('filter-search').value.toLowerCase();
        const removeRegularCoolidge = document.getElementById('filter-remove-regular-coolidge').checked;

        this.filteredScreenings = this.screenings.filter(screening => {
            if (venueFilter !== 'All' && screening.venue !== venueFilter) {
                return false;
            }
            if (searchFilter && !screening.title.toLowerCase().includes(searchFilter)) {
                return false;
            }
            return true;
        });

        if (removeRegularCoolidge) {
            const COOLIDGE_VENUE_NAME = 'Coolidge Corner Theatre';
            const MIN_DAYS_REGULAR_COOLIDGE = 5;
            const MIN_SHOWTIMES_REGULAR_COOLIDGE = 10;
            const coolidge = this.screenings.filter(s => s.venue === COOLIDGE_VENUE_NAME);
            const byTitle = {};
            coolidge.forEach(s => {
                if (!byTitle[s.title]) byTitle[s.title] = [];
                byTitle[s.title].push(s);
            });
            const regularTitles = new Set();
            Object.keys(byTitle).forEach(title => {
                const group = byTitle[title];
                const distinctDates = new Set(group.map(s => s.date)).size;
                const totalShowtimes = group.length;
                if (distinctDates >= MIN_DAYS_REGULAR_COOLIDGE || totalShowtimes >= MIN_SHOWTIMES_REGULAR_COOLIDGE) {
                    regularTitles.add(title);
                }
            });
            this.filteredScreenings = this.filteredScreenings.filter(s =>
                !(s.venue === COOLIDGE_VENUE_NAME && regularTitles.has(s.title))
            );
        }

        this.renderTable();
        this.updateSelectedCount();
    }

    toggleGroup(title, tbody) {
        if (this.expandedGroups.has(title)) {
            this.expandedGroups.delete(title);
        } else {
            this.expandedGroups.add(title);
        }
        const isExpanded = this.expandedGroups.has(title);
        const chevron = isExpanded ? '▼' : '▶';
        const ariaLabel = isExpanded ? 'Collapse group' : 'Expand group';
        // Update header chevron
        tbody.querySelectorAll('tr.movie-group-header').forEach(header => {
            if (header.dataset.movieTitle === title) {
                const icon = header.querySelector('.group-toggle-icon');
                const btn = header.querySelector('.group-toggle');
                if (icon) icon.textContent = chevron;
                if (btn) btn.setAttribute('aria-label', ariaLabel);
            }
        });
        // Show/hide detail rows
        tbody.querySelectorAll('tr.movie-group-detail-row').forEach(tr => {
            if (tr.dataset.movieTitle === title) {
                tr.classList.toggle('group-minimized', !isExpanded);
            }
        });
    }

    renderTable() {
        const tbody = document.getElementById('screenings-tbody');
        tbody.innerHTML = '';
        
        if (this.filteredScreenings.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="11">No screenings match the current filters.</td></tr>';
            // Update select-all checkbox
            document.getElementById('select-all-checkbox').checked = false;
            return;
        }
        
        // Update select-all checkbox based on current selection
        const allSelected = this.filteredScreenings.length > 0 && 
                           this.filteredScreenings.every(s => this.selectedIds.has(s.unique_id));
        document.getElementById('select-all-checkbox').checked = allSelected;
        
        // Group screenings by title
        const grouped = {};
        this.filteredScreenings.forEach(screening => {
            const title = screening.title;
            if (!grouped[title]) {
                grouped[title] = [];
            }
            grouped[title].push(screening);
        });
        
        // Sort screenings within each group by earliest to latest
        Object.keys(grouped).forEach(title => {
            grouped[title].sort((a, b) => {
                const dtA = new Date(a.date + 'T' + a.time);
                const dtB = new Date(b.date + 'T' + b.time);
                return dtA - dtB;
            });
        });
        
        // Sort groups by earliest screening in each group (earliest first)
        const sortedTitles = Object.keys(grouped).sort((titleA, titleB) => {
            const earliestA = Math.min(...grouped[titleA].map(s => new Date(s.date + 'T' + s.time).getTime()));
            const earliestB = Math.min(...grouped[titleB].map(s => new Date(s.date + 'T' + s.time).getTime()));
            return earliestA - earliestB;
        });
        
        // Render each movie group (or single screening)
        sortedTitles.forEach(title => {
            const screenings = grouped[title];
            const isGroup = screenings.length > 1;
            const isExpanded = isGroup && this.expandedGroups.has(title);
            
            if (isGroup) {
                // Create header row for the movie group
                const headerRow = document.createElement('tr');
                headerRow.classList.add('movie-group-header');
                headerRow.dataset.movieTitle = title;
                
                const selectedCount = screenings.filter(s => this.selectedIds.has(s.unique_id)).length;
                const allSelected = selectedCount === screenings.length && screenings.length > 0;
                const chevron = isExpanded ? '▼' : '▶';
                
                headerRow.innerHTML = `
                    <td class="col-select">
                        <input type="checkbox" class="movie-group-checkbox" 
                               data-title="${this.escapeHtml(title)}"
                               ${allSelected ? 'checked' : ''}>
                    </td>
                    <td class="col-title" colspan="10">
                        <button type="button" class="group-toggle" data-title="${this.escapeHtml(title)}" aria-label="${isExpanded ? 'Collapse' : 'Expand'} group">
                            <span class="group-toggle-icon">${chevron}</span>
                        </button>
                        <strong>${this.escapeHtml(title)}</strong>
                        <span class="movie-group-count">(${screenings.length} screenings)</span>
                    </td>
                `;
                
                const groupCheckbox = headerRow.querySelector('.movie-group-checkbox');
                groupCheckbox.addEventListener('click', (e) => e.stopPropagation());
                groupCheckbox.addEventListener('change', (e) => {
                    e.stopPropagation();
                    const movieTitle = e.target.dataset.title;
                    const movieScreenings = grouped[movieTitle];
                    if (e.target.checked) {
                        movieScreenings.forEach(s => this.selectedIds.add(s.unique_id));
                    } else {
                        movieScreenings.forEach(s => this.selectedIds.delete(s.unique_id));
                    }
                    this.renderTable();
                    this.updateExportButtons();
                    this.updateSelectedCount();
                });
                
                const toggleBtn = headerRow.querySelector('.group-toggle');
                toggleBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleGroup(title, tbody);
                });
                
                headerRow.addEventListener('click', () => this.toggleGroup(title, tbody));
                headerRow.classList.add('group-row-clickable');
                
                tbody.appendChild(headerRow);
            }
            
            // Render screening(s) for this movie
            screenings.forEach((screening, index) => {
                const row = document.createElement('tr');
                const isLastInGroup = isGroup && index === screenings.length - 1;
                if (isGroup) {
                    row.classList.add('movie-group-detail-row');
                    row.dataset.movieTitle = title;
                    if (!isExpanded) row.classList.add('group-minimized');
                    if (isLastInGroup) row.classList.add('movie-group-last-row');
                }
                const isSelected = this.selectedIds.has(screening.unique_id);
                if (isSelected) row.classList.add('selected');
                
                const date = new Date(screening.date);
                const time = screening.time.split(':');
                const timeObj = new Date();
                timeObj.setHours(parseInt(time[0]), parseInt(time[1]), parseInt(time[2]));
                
                const dateStr = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                const timeStr = timeObj.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
                
                let runtimeStr = '';
                if (screening.runtime_minutes) {
                    const hours = Math.floor(screening.runtime_minutes / 60);
                    const mins = screening.runtime_minutes % 60;
                    runtimeStr = hours ? `${hours}h ${mins ? mins + 'm' : ''}` : `${mins}m`;
                }
                
                const directorStr = screening.director ? this.escapeHtml(screening.director) : '—';
                const yearStr = screening.year ? screening.year.toString() : '—';
                
                let linkCell = '—';
                if (screening.source_url) {
                    const escapedUrl = this.escapeHtml(screening.source_url);
                    linkCell = `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" class="screening-link">🔗</a>`;
                }
                
                row.innerHTML = `
                    <td class="col-select">
                        <input type="checkbox" class="screening-checkbox" 
                               data-id="${screening.unique_id}" 
                               ${isSelected ? 'checked' : ''}>
                    </td>
                    <td class="col-title">${this.escapeHtml(screening.title)}</td>
                    <td class="col-director">${directorStr}</td>
                    <td class="col-year">${yearStr}</td>
                    <td class="col-venue">${this.escapeHtml(screening.venue)}</td>
                    <td class="col-date">${dateStr}</td>
                    <td class="col-time">${timeStr}</td>
                    <td class="col-runtime">${runtimeStr}</td>
                    <td class="col-special">${(screening.special_attributes && screening.special_attributes.length) ? this.escapeHtml(screening.special_attributes.join(', ')) : '—'}</td>
                    <td class="col-source">${this.escapeHtml(screening.source_site)}</td>
                    <td class="col-link">${linkCell}</td>
                `;
                
                const checkbox = row.querySelector('.screening-checkbox');
                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation(); // Prevent row click from firing
                    const id = e.target.dataset.id;
                    if (e.target.checked) {
                        this.selectedIds.add(id);
                        row.classList.add('selected');
                    } else {
                        this.selectedIds.delete(id);
                        row.classList.remove('selected');
                    }
                    const movieTitle = screening.title;
                    const movieScreenings = grouped[movieTitle];
                    const selCount = movieScreenings.filter(s => this.selectedIds.has(s.unique_id)).length;
                    const allSel = selCount === movieScreenings.length && movieScreenings.length > 0;
                    tbody.querySelectorAll('.movie-group-checkbox').forEach(cb => {
                        if (cb.dataset.title === movieTitle) cb.checked = allSel;
                    });
                    this.updateExportButtons();
                    this.updateSelectedCount();
                });
                
                // Prevent checkbox clicks from triggering row toggle
                checkbox.addEventListener('click', (e) => {
                    e.stopPropagation();
                });
                
                // Add click listener to row for toggle selection
                row.addEventListener('click', (e) => {
                    // Don't toggle if clicking on checkbox or link
                    if (e.target.closest('.screening-checkbox') || e.target.closest('.screening-link')) {
                        return;
                    }
                    
                    const id = screening.unique_id;
                    const isSelected = this.selectedIds.has(id);
                    
                    if (isSelected) {
                        this.selectedIds.delete(id);
                        checkbox.checked = false;
                        row.classList.remove('selected');
                    } else {
                        this.selectedIds.add(id);
                        checkbox.checked = true;
                        row.classList.add('selected');
                    }
                    
                    // Update group checkbox state
                    const movieTitle = screening.title;
                    const movieScreenings = grouped[movieTitle];
                    const selCount = movieScreenings.filter(s => this.selectedIds.has(s.unique_id)).length;
                    const allSel = selCount === movieScreenings.length && movieScreenings.length > 0;
                    tbody.querySelectorAll('.movie-group-checkbox').forEach(cb => {
                        if (cb.dataset.title === movieTitle) cb.checked = allSel;
                    });
                    
                    this.updateExportButtons();
                    this.updateSelectedCount();
                });
                
                // Prevent link clicks from triggering row toggle
                const linkElement = row.querySelector('.screening-link');
                if (linkElement) {
                    linkElement.addEventListener('click', (e) => {
                        e.stopPropagation();
                    });
                }
                
                tbody.appendChild(row);
            });
        });
    }

    selectAll() {
        this.filteredScreenings.forEach(screening => {
            this.selectedIds.add(screening.unique_id);
        });
        document.getElementById('select-all-checkbox').checked = true;
        this.renderTable();
        this.updateExportButtons();
        this.updateSelectedCount();
    }

    deselectAll() {
        this.filteredScreenings.forEach(screening => {
            this.selectedIds.delete(screening.unique_id);
        });
        document.getElementById('select-all-checkbox').checked = false;
        this.renderTable();
        this.updateExportButtons();
        this.updateSelectedCount();
    }

    updateExportButtons() {
        const hasSelection = this.selectedIds.size > 0;
        document.getElementById('btn-export-ics').disabled = !hasSelection;
        
        const btnGoogle = document.getElementById('btn-export-google');
        if (this.googleCalendarConfigured) {
            btnGoogle.disabled = !hasSelection;
            btnGoogle.title = '';
        } else {
            btnGoogle.disabled = true;
            if (btnGoogle.title !== 'Google Calendar API not configured') {
                btnGoogle.title = 'Google Calendar API not configured';
            }
        }
    }

    updateSelectedCount() {
        const count = this.selectedIds.size;
        const countEl = document.getElementById('selected-count');
        if (count > 0) {
            countEl.textContent = `${count} selected`;
        } else {
            countEl.textContent = '';
        }
    }

    updateStatus(message, type = 'info') {
        document.getElementById('status-text').textContent = message;
    }

    async exportICS() {
        const selected = this.getSelectedScreenings();
        if (selected.length === 0) {
            alert('Please select at least one screening to export.');
            return;
        }
        
        try {
            const response = await fetch('/api/export/ics', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ screenings: selected })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Export failed');
            }
            
            // Download file
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'screenings.ics';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.updateStatus(`Exported ${selected.length} screenings to screenings.ics`);
            
            // Show import instructions
            const showInstructions = confirm(
                `Exported ${selected.length} screenings to screenings.ics\n\n` +
                'Would you like to see instructions for importing to Google Calendar?'
            );
            
            if (showInstructions) {
                this.showImportInstructions();
            }
            
        } catch (error) {
            alert('Export failed: ' + error.message);
            this.updateStatus('Export failed', 'error');
        }
    }

    async exportGoogle() {
        const selected = this.getSelectedScreenings();
        if (selected.length === 0) {
            alert('Please select at least one screening to export.');
            return;
        }
        
        if (!confirm(`Add ${selected.length} screenings to Google Calendar?\n\nThis will open a browser window to authorize access if needed.`)) {
            return;
        }
        
        try {
            this.updateStatus('Adding to Google Calendar...');
            
            const response = await fetch('/api/export/google', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ screenings: selected })
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                if (data.error === 'Google Calendar API not configured') {
                    const showInstructions = confirm(
                        'Google Calendar API is not configured.\n\n' +
                        'Would you like to see setup instructions?'
                    );
                    if (showInstructions) {
                        this.showGoogleSetupInstructions();
                    }
                } else {
                    throw new Error(data.error || 'Export failed');
                }
                return;
            }
            
            if (data.failed === 0) {
                alert(`Successfully added ${data.success} screenings to Google Calendar!`);
                this.updateStatus(`Added ${data.success} screenings to Google Calendar`);
            } else {
                alert(`Added ${data.success} screenings to Google Calendar.\n${data.failed} screenings failed to add.`);
                this.updateStatus(`Added ${data.success} screenings (${data.failed} failed)`);
            }
            
        } catch (error) {
            alert('Export failed: ' + error.message);
            this.updateStatus('Google Calendar export failed', 'error');
        }
    }

    getSelectedScreenings() {
        return this.screenings.filter(s => this.selectedIds.has(s.unique_id));
    }

    async showImportInstructions() {
        try {
            const response = await fetch('/api/instructions/import');
            const data = await response.json();
            this.showModal('Import Instructions', data.instructions);
        } catch (error) {
            console.error('Error fetching instructions:', error);
        }
    }

    async showGoogleSetupInstructions() {
        try {
            const response = await fetch('/api/instructions/google');
            const data = await response.json();
            this.showModal('Google Calendar API Setup', data.instructions);
        } catch (error) {
            console.error('Error fetching instructions:', error);
        }
    }

    showModal(title, text) {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-text').textContent = text;
        document.getElementById('modal').style.display = 'flex';
    }

    closeModal() {
        document.getElementById('modal').style.display = 'none';
    }

    formatEventSummary(screening) {
        let s = `${screening.title} @ ${screening.venue}`;
        const attrs = screening.special_attributes || [];
        const formatTags = attrs.filter(a => {
            const x = (a || '').trim();
            if (!x) return false;
            if (x.endsWith('mm') && x.length <= 5 && /^\d+mm$/.test(x)) return true;
            if (x === 'Screening on film') return true;
            return false;
        });
        if (formatTags.length) s += ' (' + formatTags.join(', ') + ')';
        return s;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new CinemaCalApp();
});
