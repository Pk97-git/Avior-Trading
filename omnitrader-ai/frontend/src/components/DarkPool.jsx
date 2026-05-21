import React, { useState } from 'react';
import { darkPoolApi } from '../api';
import {
    Search, Loader2, RefreshCw, AlertTriangle, ChevronDown, ChevronUp,
    Eye, TrendingUp, TrendingDown, BarChart2, Star,
} from 'lucide-react';

// ── Signal config ──────────────────────────────────────────────────────────────

const OVERALL_SIGNAL_CONFIG = {
    ACCUMULATION_PATTERN: {
        label: 'Accumulation Pattern',
        bg:    'bg-emerald-500/15',
        text:  'text-emerald-400',
        border:'border-emerald-500/40',
    },
    DISTRIBUTION_PATTERN: {
        label: 'Distribution Pattern',
        bg:    'bg-red-500/15',
        text:  'text-red-400',
        border:'border-red-500/40',
    },
    MIXED_SIGNALS: {
        label: 'Mixed Signals',
        bg:    'bg-amber-500/15',
        text:  'text-amber-400',
        border:'border-amber-500/40',
    },
    NO_UNUSUAL_ACTIVITY: {
        label: 'No Unusual Activity',
        bg:    'bg-slate-500/15',
        text:  'text-slate-400',
        border:'border-slate-500/40',
    },
};

const EVENT_TYPE_CONFIG = {
    ACCUMULATION: {
        label: 'Accumulation',
        bg:    'bg-emerald-500/15',
        text:  'text-emerald-400',
        border:'border-emerald-500/30',
    },
    DISTRIBUTION: {
        label: 'Distribution',
        bg:    'bg-red-500/15',
        text:  'text-red-400',
        border:'border-red-500/30',
    },
    BREAKOUT_CONFIRMATION: {
        label: 'Breakout',
        bg:    'bg-blue-500/15',
        text:  'text-blue-400',
        border:'border-blue-500/30',
    },
    INSTITUTIONAL_INTEREST: {
        label: 'Institutional',
        bg:    'bg-purple-500/15',
        text:  'text-purple-400',
        border:'border-purple-500/30',
    },
    ELEVATED_VOLUME: {
        label: 'Elevated Vol',
        bg:    'bg-slate-500/15',
        text:  'text-slate-400',
        border:'border-slate-500/30',
    },
};

const UNIVERSE_SIGNAL_CONFIG = {
    BREAKOUT_VOLUME: { label: 'Breakout',  cls: 'text-blue-400 bg-blue-500/10 border border-blue-500/30' },
    SURGE:           { label: 'Surge',     cls: 'text-amber-400 bg-amber-500/10 border border-amber-500/30' },
    ELEVATED:        { label: 'Elevated',  cls: 'text-slate-400 bg-slate-500/10 border border-slate-500/30' },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function StrengthStars({ strength }) {
    return (
        <div className="flex items-center gap-0.5">
            {Array.from({ length: 5 }).map((_, i) => (
                <Star
                    key={i}
                    className={`h-3 w-3 ${i < strength ? 'text-amber-400 fill-amber-400' : 'text-slate-700'}`}
                />
            ))}
        </div>
    );
}

function EventCard({ event }) {
    const cfg = EVENT_TYPE_CONFIG[event.signal_type] || EVENT_TYPE_CONFIG.ELEVATED_VOLUME;
    return (
        <div className="p-3 rounded-lg border border-border bg-card hover:bg-accent/20 transition-colors">
            <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${cfg.bg} ${cfg.text} ${cfg.border}`}>
                        {cfg.label}
                    </span>
                    <span className="text-xs text-muted-foreground">{event.date}</span>
                </div>
                <StrengthStars strength={event.strength} />
            </div>

            <p className="text-sm text-foreground/80 mb-2">{event.description}</p>

            <div className="flex flex-wrap gap-3 text-xs">
                <div className="flex items-center gap-1">
                    <BarChart2 className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-semibold">{event.vol_ratio}x avg volume</span>
                </div>
                <div className={`flex items-center gap-1 font-semibold ${event.price_chg_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {event.price_chg_pct >= 0
                        ? <TrendingUp className="h-3.5 w-3.5" />
                        : <TrendingDown className="h-3.5 w-3.5" />
                    }
                    {event.price_chg_pct > 0 ? '+' : ''}{event.price_chg_pct}%
                </div>
                <div className="text-muted-foreground">
                    Close: <span className="text-foreground font-medium">${event.close}</span>
                </div>
                <div className="text-muted-foreground">
                    Vol: <span className="text-foreground font-medium">{(event.volume / 1e6).toFixed(2)}M</span>
                </div>
            </div>
        </div>
    );
}

function VolRatioBar({ ratio, max = 10 }) {
    const pct = Math.min(100, (ratio / max) * 100);
    const color = ratio >= 5 ? 'bg-blue-500' : ratio >= 3 ? 'bg-amber-500' : 'bg-slate-500';
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs font-semibold w-10 text-right">{ratio}x</span>
        </div>
    );
}

// ── Explainer ─────────────────────────────────────────────────────────────────

function Explainer() {
    const [open, setOpen] = useState(false);
    return (
        <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
                <span className="flex items-center gap-2">
                    <Eye className="h-4 w-4" />
                    What is Dark Pool Activity?
                </span>
                {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {open && (
                <div className="px-4 pb-4 text-sm text-muted-foreground leading-relaxed border-t border-border pt-3">
                    Hedge funds and institutions trade in "dark pools" — private exchanges where large orders don't move
                    the market. While we can't see those prints, we can detect their footprints: abnormally high volume on
                    flat price days is the classic sign that a large institution is accumulating or distributing quietly.
                    A volume surge of 3x or more with minimal price movement often precedes a breakout or breakdown as
                    the institution finishes building or exiting their position.
                </div>
            )}
        </div>
    );
}

// ── Tab: Ticker Analysis ───────────────────────────────────────────────────────

function TickerTab() {
    const [ticker,  setTicker]  = useState('');
    const [loading, setLoading] = useState(false);
    const [error,   setError]   = useState(null);
    const [data,    setData]    = useState(null);

    const handleSubmit = (e) => {
        e.preventDefault();
        const t = ticker.trim().toUpperCase();
        if (!t) return;
        setLoading(true);
        setError(null);
        setData(null);
        darkPoolApi.getTicker(t)
            .then(r => setData(r.data))
            .catch(e => setError(e.response?.data?.detail || e.message))
            .finally(() => setLoading(false));
    };

    const cfg = data ? (OVERALL_SIGNAL_CONFIG[data.overall_signal] || OVERALL_SIGNAL_CONFIG.NO_UNUSUAL_ACTIVITY) : null;

    return (
        <div className="space-y-4">
            <form onSubmit={handleSubmit} className="flex gap-2">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                        type="text"
                        value={ticker}
                        onChange={e => setTicker(e.target.value.toUpperCase())}
                        placeholder="Enter ticker (e.g. AAPL, TCS.NS)"
                        className="w-full pl-9 pr-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:border-primary"
                    />
                </div>
                <button
                    type="submit"
                    disabled={!ticker.trim() || loading}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium
                               hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {loading
                        ? <><Loader2 className="h-4 w-4 animate-spin" /> Scanning…</>
                        : <><RefreshCw className="h-4 w-4" /> Scan</>
                    }
                </button>
            </form>

            {loading && (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p className="text-sm">Scanning volume patterns for institutional footprints…</p>
                </div>
            )}

            {error && !loading && (
                <div className="text-red-400 text-sm p-4 bg-red-500/10 rounded-lg border border-red-500/30">
                    {error}
                </div>
            )}

            {data && !loading && (
                <div className="space-y-4">
                    {/* Overall signal */}
                    <div className={`p-4 rounded-xl border ${cfg.bg} ${cfg.border}`}>
                        <div className="flex flex-wrap items-center gap-3 mb-2">
                            <h3 className="font-bold text-base">{data.ticker}</h3>
                            <span className={`text-sm font-semibold px-3 py-1 rounded-full border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
                                {cfg.label}
                            </span>
                        </div>
                        <p className={`text-sm ${cfg.text}`}>{data.overall_note}</p>

                        <div className="flex gap-4 mt-3 text-xs text-muted-foreground">
                            <span>Events found: <strong className="text-foreground">{data.events_found}</strong></span>
                            <span>Accumulation: <strong className="text-emerald-400">{data.accumulation_count}</strong></span>
                            <span>Distribution: <strong className="text-red-400">{data.distribution_count}</strong></span>
                        </div>
                    </div>

                    {/* Events */}
                    {data.events?.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                Recent Events (newest first)
                            </h4>
                            {data.events.map((ev, i) => (
                                <EventCard key={i} event={ev} />
                            ))}
                        </div>
                    )}

                    {data.events?.length === 0 && (
                        <p className="text-muted-foreground text-sm text-center py-8">
                            No unusual volume events detected in the last 15 trading days.
                        </p>
                    )}

                    {/* Disclaimer */}
                    <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-400/70 text-xs">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                        <span>{data.disclaimer}</span>
                    </div>
                </div>
            )}

            {!data && !loading && !error && (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                    <Eye className="h-10 w-10 text-muted-foreground/30" />
                    <p className="text-sm">Enter a ticker to scan for institutional volume footprints</p>
                </div>
            )}
        </div>
    );
}

// ── Tab: Universe Scan ─────────────────────────────────────────────────────────

function UniverseTab() {
    const [country,      setCountry]      = useState('ALL');
    const [minVolRatio,  setMinVolRatio]  = useState(2.5);
    const [loading,      setLoading]      = useState(false);
    const [error,        setError]        = useState(null);
    const [data,         setData]         = useState(null);

    const handleScan = () => {
        setLoading(true);
        setError(null);
        setData(null);
        darkPoolApi.scanUniverse({ country, min_vol_ratio: minVolRatio, limit: 30 })
            .then(r => setData(r.data))
            .catch(e => setError(e.response?.data?.detail || e.message))
            .finally(() => setLoading(false));
    };

    return (
        <div className="space-y-4">
            {/* Controls */}
            <div className="flex flex-wrap gap-3 items-end">
                <div className="space-y-1">
                    <label className="text-xs text-muted-foreground font-medium">Country</label>
                    <select
                        value={country}
                        onChange={e => setCountry(e.target.value)}
                        className="text-sm bg-muted border border-border rounded px-2 py-1.5"
                    >
                        <option value="ALL">All</option>
                        <option value="IN">India</option>
                        <option value="US">US</option>
                    </select>
                </div>

                <div className="space-y-1 flex-1 min-w-[160px]">
                    <label className="text-xs text-muted-foreground font-medium">
                        Min Volume Ratio: <span className="text-foreground font-semibold">{minVolRatio}x</span>
                    </label>
                    <input
                        type="range"
                        min="1.5"
                        max="8"
                        step="0.5"
                        value={minVolRatio}
                        onChange={e => setMinVolRatio(parseFloat(e.target.value))}
                        className="w-full accent-primary"
                    />
                </div>

                <button
                    onClick={handleScan}
                    disabled={loading}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium
                               hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {loading
                        ? <><Loader2 className="h-4 w-4 animate-spin" /> Scanning…</>
                        : <><Eye className="h-4 w-4" /> Scan Universe</>
                    }
                </button>
            </div>

            {loading && (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-3">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p className="text-sm">Scanning universe for unusual volume…</p>
                </div>
            )}

            {error && !loading && (
                <div className="text-red-400 text-sm p-4 bg-red-500/10 rounded-lg border border-red-500/30">
                    {error}
                </div>
            )}

            {data && !loading && (
                <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>{data.count} stocks with unusual volume on {data.scan_date}</span>
                    </div>

                    {data.results?.length === 0 && (
                        <p className="text-muted-foreground text-sm text-center py-8">
                            No stocks meeting the {minVolRatio}x volume threshold found.
                        </p>
                    )}

                    {data.results?.length > 0 && (
                        <div className="overflow-x-auto rounded-lg border border-border">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border bg-muted/50">
                                        <th className="text-left px-3 py-2 text-xs font-semibold text-muted-foreground">Ticker</th>
                                        <th className="text-left px-3 py-2 text-xs font-semibold text-muted-foreground hidden sm:table-cell">Sector</th>
                                        <th className="text-left px-3 py-2 text-xs font-semibold text-muted-foreground">Vol Ratio</th>
                                        <th className="text-right px-3 py-2 text-xs font-semibold text-muted-foreground hidden md:table-cell">Volume</th>
                                        <th className="text-right px-3 py-2 text-xs font-semibold text-muted-foreground">Signal</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.results.map((row, i) => {
                                        const sigCfg = UNIVERSE_SIGNAL_CONFIG[row.signal] || UNIVERSE_SIGNAL_CONFIG.ELEVATED;
                                        return (
                                            <tr key={row.ticker} className={`border-b border-border/50 hover:bg-accent/20 ${i % 2 === 0 ? '' : 'bg-muted/10'}`}>
                                                <td className="px-3 py-2">
                                                    <div className="font-bold">{row.ticker}</div>
                                                    <div className="text-xs text-muted-foreground truncate max-w-[120px]">{row.name}</div>
                                                </td>
                                                <td className="px-3 py-2 text-xs text-muted-foreground hidden sm:table-cell">
                                                    {row.sector || '—'}
                                                </td>
                                                <td className="px-3 py-2 min-w-[100px]">
                                                    <VolRatioBar ratio={row.vol_ratio} />
                                                </td>
                                                <td className="px-3 py-2 text-right text-xs text-muted-foreground hidden md:table-cell">
                                                    {row.today_volume > 1e6
                                                        ? `${(row.today_volume / 1e6).toFixed(1)}M`
                                                        : `${(row.today_volume / 1e3).toFixed(0)}K`
                                                    }
                                                </td>
                                                <td className="px-3 py-2 text-right">
                                                    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${sigCfg.cls}`}>
                                                        {sigCfg.label}
                                                    </span>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* Disclaimer */}
                    <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-400/70 text-xs">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                        <span>{data.disclaimer}</span>
                    </div>
                </div>
            )}

            {!data && !loading && !error && (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                    <BarChart2 className="h-10 w-10 text-muted-foreground/30" />
                    <p className="text-sm">Click "Scan Universe" to find stocks with unusual volume activity</p>
                </div>
            )}
        </div>
    );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function DarkPool() {
    const [tab, setTab] = useState('ticker');

    return (
        <div className="space-y-4">
            <Explainer />

            {/* Tabs */}
            <div className="flex gap-1 bg-muted p-1 rounded-lg w-fit">
                {[
                    { id: 'ticker',   label: 'Ticker Analysis' },
                    { id: 'universe', label: 'Universe Scan' },
                ].map(t => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        className={`px-4 py-1.5 rounded text-sm font-medium transition-colors
                            ${tab === t.id
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground'
                            }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {tab === 'ticker'   && <TickerTab />}
            {tab === 'universe' && <UniverseTab />}
        </div>
    );
}
