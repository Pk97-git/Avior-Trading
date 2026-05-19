import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, AlertCircle, Calendar,
    AlertTriangle, Clock, Info, ChevronDown, ChevronUp,
} from 'lucide-react';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('en-US', {
            weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
        });
    } catch { return iso; }
}

function fmtDayOfWeek(iso) {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleDateString('en-US', { weekday: 'long' });
    } catch { return ''; }
}

// Group events by ISO week string "YYYY-WW"
function isoWeek(dateStr) {
    const d = new Date(dateStr);
    if (isNaN(d)) return 'Unknown Week';
    const jan1 = new Date(d.getFullYear(), 0, 1);
    const week = Math.ceil(((d - jan1) / 86_400_000 + jan1.getDay() + 1) / 7);
    return `${d.getFullYear()}-W${String(week).padStart(2, '0')}`;
}

function weekLabel(weekKey) {
    if (!weekKey || weekKey === 'Unknown Week') return 'Upcoming';
    try {
        // ISO week to monday
        const [year, wk] = weekKey.split('-W').map(Number);
        const jan1 = new Date(year, 0, 1);
        const days = (wk - 1) * 7;
        const monday = new Date(jan1.getTime() + days * 86_400_000);
        // Adjust to Monday
        const dow = monday.getDay();
        const diff = dow === 0 ? 1 : (dow === 1 ? 0 : 8 - dow);
        monday.setDate(monday.getDate() + diff);
        const friday = new Date(monday);
        friday.setDate(friday.getDate() + 4);
        const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return `Week of ${fmt(monday)} – ${fmt(friday)}`;
    } catch { return weekKey; }
}

function daysUntilLabel(n) {
    if (n == null) return null;
    if (n === 0)  return 'Today';
    if (n === 1)  return 'Tomorrow';
    return `${n}d`;
}

function impactStyle(impact) {
    const i = String(impact ?? '').toUpperCase();
    if (i === 'HIGH')   return { border: 'border-l-red-500',    dot: 'bg-red-500',    text: 'text-red-400',    badge: 'bg-red-500/15 text-red-400 border-red-500/30' };
    if (i === 'MEDIUM') return { border: 'border-l-yellow-500', dot: 'bg-yellow-500', text: 'text-yellow-400', badge: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30' };
    return { border: 'border-l-slate-500', dot: 'bg-slate-500', text: 'text-slate-400', badge: 'bg-muted/20 text-muted-foreground border-border' };
}

function countryFlag(country) {
    if (!country) return '';
    const flags = {
        US: '🇺🇸', IN: '🇮🇳', GB: '🇬🇧', EU: '🇪🇺', JP: '🇯🇵',
        CN: '🇨🇳', CA: '🇨🇦', AU: '🇦🇺', DE: '🇩🇪', FR: '🇫🇷',
    };
    return flags[country.toUpperCase()] ?? country;
}

// ── Blackout Banner ─────────────────────────────────────────────────────────

function BlackoutBanner({ blackout, loading }) {
    if (loading) {
        return (
            <div className="h-12 rounded-xl bg-muted/20 animate-pulse border border-border" />
        );
    }
    if (!blackout?.is_blackout) return null;

    const eventName = blackout.event_name ?? blackout.event ?? blackout.reason ?? 'High-Impact Event';

    return (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/15 border border-red-500/40 text-red-300 shadow-lg shadow-red-500/5">
            <AlertTriangle size={18} className="text-red-400 shrink-0 animate-pulse" />
            <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-red-300">
                    HIGH-IMPACT EVENT IN NEXT 24H — Consider reducing new positions.
                </p>
                <p className="text-xs text-red-400/80 truncate mt-0.5">{eventName}</p>
            </div>
            {blackout.event_time && (
                <div className="shrink-0 flex items-center gap-1.5 px-2 py-1 rounded-lg bg-red-500/20 text-red-400 text-xs font-medium">
                    <Clock size={11} />
                    {blackout.event_time}
                </div>
            )}
        </div>
    );
}

// ── Next Event Highlight ────────────────────────────────────────────────────

function NextEventCard({ event }) {
    if (!event) return null;
    const { border, badge, text } = impactStyle(event.impact ?? event.importance);
    const daysUntil = event.days_until ?? event.days_ahead ?? null;
    const isUrgent  = daysUntil != null && daysUntil <= 3;

    return (
        <div className={`rounded-xl border border-border bg-card/70 overflow-hidden border-l-4 ${border} p-4`}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1.5">
                        <Calendar size={14} className={text} />
                        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Next Event</span>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {daysUntil != null && (
                        <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold border ${
                            isUrgent
                                ? `bg-red-500/20 text-red-400 border-red-500/40 ${isUrgent ? 'animate-pulse' : ''}`
                                : 'bg-muted/20 text-muted-foreground border-border'
                        }`}>
                            <Clock size={10} />
                            {daysUntilLabel(daysUntil)}
                        </span>
                    )}
                    <span className={`inline-block px-2 py-0.5 rounded border text-[11px] font-semibold ${badge}`}>
                        {(event.impact ?? event.importance ?? 'MEDIUM').toUpperCase()}
                    </span>
                </div>
            </div>
            <div className="mt-3 space-y-1">
                <div className="flex items-center gap-2">
                    <span className="text-base">{countryFlag(event.country)}</span>
                    <h3 className="text-base font-bold text-foreground">{event.event_name ?? event.name ?? event.title ?? 'Economic Event'}</h3>
                </div>
                <p className="text-xs text-muted-foreground">{fmtDate(event.date ?? event.event_date)} · {fmtDayOfWeek(event.date ?? event.event_date)}</p>
                {(event.description ?? event.summary) && (
                    <p className="text-sm text-muted-foreground/80 leading-relaxed mt-2 max-w-2xl">
                        {event.description ?? event.summary}
                    </p>
                )}
                {(event.trading_advice ?? event.advice) && (
                    <p className="text-sm italic text-muted-foreground/70 mt-1 border-l-2 border-border pl-3">
                        {event.trading_advice ?? event.advice}
                    </p>
                )}
            </div>
        </div>
    );
}

// ── Event Card ──────────────────────────────────────────────────────────────

function EventCard({ event }) {
    const { border, dot, text, badge } = impactStyle(event.impact ?? event.importance);
    const daysUntil = event.days_until ?? event.days_ahead ?? null;
    const isUrgent  = daysUntil != null && daysUntil <= 3;

    return (
        <div className={`relative ml-6 rounded-xl border border-border/60 bg-card/50 overflow-hidden border-l-4 ${border} p-3 transition-all hover:border-border hover:bg-card/80 ${
            isUrgent ? 'shadow-md shadow-red-500/10 border-red-500/40' : ''
        }`}>
            {/* Connector dot */}
            <div className={`absolute -left-[1.55rem] top-4 w-3 h-3 rounded-full border-2 border-background ${dot} ${isUrgent ? 'animate-pulse' : ''}`} />

            <div className="flex items-start justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-base shrink-0">{countryFlag(event.country)}</span>
                    <h4 className="text-sm font-semibold text-foreground truncate">
                        {event.event_name ?? event.name ?? event.title ?? 'Event'}
                    </h4>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    {daysUntil != null && (
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold ${
                            isUrgent
                                ? 'bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse'
                                : daysUntil <= 7
                                    ? 'bg-yellow-500/15 text-yellow-400 border border-yellow-500/30'
                                    : 'bg-muted/20 text-muted-foreground border border-border'
                        }`}>
                            <Clock size={9} />
                            {daysUntilLabel(daysUntil)}
                        </span>
                    )}
                    <span className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-semibold ${badge}`}>
                        {(event.impact ?? event.importance ?? 'MED').toUpperCase().slice(0, 4)}
                    </span>
                </div>
            </div>

            <p className="text-[11px] text-muted-foreground mt-1">
                {fmtDate(event.date ?? event.event_date)}
                {event.time && <span className="ml-1.5 text-muted-foreground/60">{event.time}</span>}
            </p>

            {(event.description ?? event.summary) && (
                <p className="text-xs text-muted-foreground/75 mt-1.5 leading-relaxed">
                    {event.description ?? event.summary}
                </p>
            )}
            {(event.trading_advice ?? event.advice) && (
                <p className="text-xs italic text-muted-foreground/60 mt-1.5 border-l border-border/60 pl-2">
                    {event.trading_advice ?? event.advice}
                </p>
            )}
        </div>
    );
}

// ── Week Section ────────────────────────────────────────────────────────────

function WeekSection({ weekKey, events }) {
    const [collapsed, setCollapsed] = useState(false);
    const hasHighImpact = events.some(e => (e.impact ?? e.importance ?? '').toUpperCase() === 'HIGH');

    return (
        <div className="space-y-0">
            {/* Week header */}
            <button
                onClick={() => setCollapsed(c => !c)}
                className="w-full flex items-center gap-3 py-2 group"
            >
                <div className="flex-1 flex items-center gap-2">
                    <span className="text-xs font-bold text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">
                        {weekLabel(weekKey)}
                    </span>
                    {hasHighImpact && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-500/15 text-red-400 border border-red-500/25">
                            HIGH IMPACT
                        </span>
                    )}
                    <span className="text-[10px] text-muted-foreground/50">
                        {events.length} event{events.length !== 1 ? 's' : ''}
                    </span>
                </div>
                {collapsed ? <ChevronDown size={13} className="text-muted-foreground" /> : <ChevronUp size={13} className="text-muted-foreground" />}
            </button>

            {!collapsed && (
                /* Timeline container */
                <div className="relative ml-2 pl-4 border-l-2 border-border/40 space-y-3 pb-4">
                    {events.map((event, i) => (
                        <EventCard key={i} event={event} />
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Calendar Key ────────────────────────────────────────────────────────────

function CalendarKey() {
    const [open, setOpen] = useState(false);
    return (
        <div className="rounded-xl border border-border/60 bg-card/40 overflow-hidden">
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
                <div className="flex items-center gap-1.5">
                    <Info size={12} />
                    <span className="font-medium">Calendar Key — Impact Levels Explained</span>
                </div>
                {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {open && (
                <div className="px-4 py-3 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="flex items-start gap-2">
                        <div className="mt-1 w-3 h-3 rounded-full bg-red-500 shrink-0" />
                        <div>
                            <p className="font-semibold text-foreground">HIGH Impact</p>
                            <p className="text-muted-foreground mt-0.5">Major economic releases (CPI, NFP, Fed rate decision, GDP). Expect elevated volatility and wider spreads. Consider reducing leveraged positions ahead of release.</p>
                        </div>
                    </div>
                    <div className="flex items-start gap-2">
                        <div className="mt-1 w-3 h-3 rounded-full bg-yellow-500 shrink-0" />
                        <div>
                            <p className="font-semibold text-foreground">MEDIUM Impact</p>
                            <p className="text-muted-foreground mt-0.5">Secondary indicators (retail sales, PMI, housing data). Can move markets but typically less dramatic. Monitor for surprises vs consensus.</p>
                        </div>
                    </div>
                    <div className="sm:col-span-2 pt-1 border-t border-border/30 text-muted-foreground/70">
                        Events within <span className="text-red-400 font-medium">3 days</span> pulse red. All times are estimates — verify exact release times before trading.
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function EconomicCalendar() {
    const [events, setEvents]           = useState([]);
    const [blackout, setBlackout]       = useState(null);
    const [loading, setLoading]         = useState(true);
    const [blackoutLoading, setBlackoutLoading] = useState(true);
    const [error, setError]             = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [daysAhead, setDaysAhead]     = useState(30);

    const fetchEvents = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get('/api/v1/economic-calendar/events', {
                params: { days_ahead: daysAhead },
            });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.events ?? res.data?.results ?? res.data?.data ?? []);
            // Sort by date ascending
            raw.sort((a, b) => {
                const da = new Date(a.date ?? a.event_date ?? 0).getTime();
                const db = new Date(b.date ?? b.event_date ?? 0).getTime();
                return da - db;
            });
            setEvents(raw);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load economic calendar events.');
        } finally {
            setLoading(false);
        }
    }, [daysAhead]);

    const fetchBlackout = useCallback(async () => {
        setBlackoutLoading(true);
        try {
            const res = await axios.get('/api/v1/economic-calendar/events/blackout');
            setBlackout(res.data ?? null);
        } catch {
            setBlackout(null);
        } finally {
            setBlackoutLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchEvents();
        fetchBlackout();
    }, [fetchEvents, fetchBlackout]);

    const handleRefresh = () => { fetchEvents(); fetchBlackout(); };

    // Group into weeks
    const grouped = events.reduce((acc, event) => {
        const key = isoWeek(event.date ?? event.event_date ?? '');
        if (!acc[key]) acc[key] = [];
        acc[key].push(event);
        return acc;
    }, {});
    const weeks = Object.keys(grouped).sort();

    // Next event
    const nextEvent = events.find(e => {
        const d = e.days_until ?? e.days_ahead;
        return d != null ? d >= 0 : new Date(e.date ?? e.event_date ?? 0) >= Date.now() - 86400000;
    }) ?? events[0] ?? null;

    const totalHigh   = events.filter(e => (e.impact ?? e.importance ?? '').toUpperCase() === 'HIGH').length;
    const totalMedium = events.filter(e => (e.impact ?? e.importance ?? '').toUpperCase() === 'MEDIUM').length;

    return (
        <div className="space-y-5 p-5 min-h-screen">

            {/* ── Header ── */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Calendar size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Economic Calendar</h1>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {[14, 30, 60, 90].map(d => (
                            <button key={d} onClick={() => setDaysAhead(d)}
                                className={`px-3 py-1.5 transition-colors ${daysAhead === d ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {d}d
                            </button>
                        ))}
                    </div>
                    <button onClick={handleRefresh} disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50">
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Blackout Banner ── */}
            <BlackoutBanner blackout={blackout} loading={blackoutLoading} />

            {/* ── Event summary chips ── */}
            {!loading && events.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card border border-border text-xs">
                        <span className="font-medium text-foreground">{events.length}</span>
                        <span className="text-muted-foreground">events in next {daysAhead}d</span>
                    </div>
                    {totalHigh > 0 && (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs">
                            <div className="w-2 h-2 rounded-full bg-red-500" />
                            <span className="font-bold text-red-400">{totalHigh}</span>
                            <span className="text-muted-foreground">high impact</span>
                        </div>
                    )}
                    {totalMedium > 0 && (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-xs">
                            <div className="w-2 h-2 rounded-full bg-yellow-500" />
                            <span className="font-bold text-yellow-400">{totalMedium}</span>
                            <span className="text-muted-foreground">medium impact</span>
                        </div>
                    )}
                </div>
            )}

            {/* ── Error ── */}
            {error && (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                    <AlertCircle size={15} />
                    {error}
                </div>
            )}

            {/* ── Loading state ── */}
            {loading && (
                <div className="space-y-4">
                    {/* Next event skeleton */}
                    <div className="h-28 rounded-xl bg-muted/20 border border-border animate-pulse" />
                    {/* Calendar key skeleton */}
                    <div className="h-10 rounded-xl bg-muted/20 border border-border animate-pulse" />
                    {/* Timeline skeleton */}
                    <div className="space-y-3 ml-2 pl-4 border-l-2 border-border/40">
                        {[...Array(5)].map((_, i) => (
                            <div key={i} className="h-20 rounded-xl bg-muted/20 border border-border animate-pulse ml-6" />
                        ))}
                    </div>
                </div>
            )}

            {!loading && events.length === 0 && !error && (
                <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
                    <Calendar size={36} className="opacity-25" />
                    <p className="text-sm">No economic events found for the next {daysAhead} days.</p>
                    <p className="text-xs opacity-60">Try expanding the days range.</p>
                </div>
            )}

            {!loading && events.length > 0 && (
                <>
                    {/* ── Next Event Highlight ── */}
                    <NextEventCard event={nextEvent} />

                    {/* ── Calendar Key ── */}
                    <CalendarKey />

                    {/* ── Timeline ── */}
                    <div className="space-y-6">
                        {weeks.map(weekKey => (
                            <WeekSection
                                key={weekKey}
                                weekKey={weekKey}
                                events={grouped[weekKey]}
                            />
                        ))}
                    </div>

                    {/* ── Footer ── */}
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground/50 pt-2">
                        <Info size={10} />
                        Event dates and times are estimates. Verify exact release schedules before trading.
                    </div>
                </>
            )}
        </div>
    );
}
