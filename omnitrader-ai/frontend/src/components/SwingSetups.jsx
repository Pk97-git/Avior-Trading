import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi, aiApi, ingestionApi } from '../api';
import { RefreshCw, Loader2, TrendingUp, Target, ShieldAlert, ArrowUpRight,
         Sparkles, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { SignalBadge } from './shared/SignalCard';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(val, decimals = 2) {
    if (val == null) return '—';
    return Number(val).toFixed(decimals);
}

function fmtDate(iso) {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleString(undefined, {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return iso;
    }
}

/**
 * Try to parse structured levels from the thesis array.
 * Looks for lines like "Entry: 123.45", "Stop: 120", "Target: 135" etc.
 * Returns { entry, stop, target } — any can be null.
 */
function parseLevels(thesis = []) {
    const levels = { entry: null, stop: null, target: null };
    const patterns = [
        { key: 'entry',  re: /entry[:\s]+\$?([\d,.]+)/i },
        { key: 'stop',   re: /stop[\s-]*(loss)?[:\s]+\$?([\d,.]+)/i },
        { key: 'target', re: /(take[- ]profit|target|tp)[:\s]+\$?([\d,.]+)/i },
    ];
    for (const bullet of thesis) {
        for (const { key, re } of patterns) {
            if (levels[key] !== null) continue;
            const m = bullet.match(re);
            if (m) {
                // Last capture group contains the number
                levels[key] = m[m.length - 1].replace(',', '');
            }
        }
    }
    return levels;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function CountryBadge({ country }) {
    const isIN = country === 'IN';
    return (
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${
            isIN ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'
        }`}>
            {country || 'US'}
        </span>
    );
}

function ScorePill({ score }) {
    const pct = Math.max(0, Math.min(100, score ?? 0));
    const color = pct >= 70
        ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
        : pct >= 50
            ? 'bg-purple-500/20 text-purple-400 border-purple-500/30'
            : 'bg-muted/30 text-muted-foreground border-border';
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border tabular-nums ${color}`}>
            {pct}
        </span>
    );
}

function LevelRow({ icon: Icon, label, value, color = 'text-foreground' }) {
    return (
        <div className="flex items-center gap-1.5">
            <Icon size={12} className="text-muted-foreground shrink-0" />
            <span className="text-[11px] text-muted-foreground w-20 shrink-0">{label}</span>
            <span className={`text-[11px] font-semibold tabular-nums ${color}`}>{value}</span>
        </div>
    );
}

// ── Data Freshness Banner ──────────────────────────────────────────────────

export function FreshnessBanner() {
    const [stale, setStale] = useState(null);

    useEffect(() => {
        ingestionApi.getFreshness()
            .then(r => { if (r.data.is_stale) setStale(r.data); })
            .catch(() => {});
    }, []);

    if (!stale) return null;

    const h = stale.hours_stale != null ? Math.round(stale.hours_stale) : '?';
    return (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs text-amber-400">
            <AlertTriangle size={13} className="shrink-0" />
            <span>
                Price data is <strong>{h}h old</strong> — quotes may be stale.
                Go to <strong>Data Ingestion</strong> and trigger a price refresh.
            </span>
        </div>
    );
}

// ── Explain Simply panel ───────────────────────────────────────────────────

function ExplainPanel({ ticker, context }) {
    const [open, setOpen]     = useState(false);
    const [loading, setLoading] = useState(false);
    const [result, setResult]  = useState(null);
    const [err, setErr]        = useState(null);

    async function fetchExplanation() {
        if (result) { setOpen(v => !v); return; }
        setOpen(true);
        setLoading(true);
        setErr(null);
        try {
            const res = await aiApi.explain(ticker, context, 'Explain this trade setup in plain English for a non-trader. What is happening, why is this a buy, what is the risk?');
            setResult(res.data);
        } catch (e) {
            setErr(e?.response?.data?.detail || 'AI explanation unavailable');
        } finally {
            setLoading(false);
        }
    }

    return (
        <div>
            <button
                onClick={fetchExplanation}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium
                    text-purple-400 bg-purple-500/10 border border-purple-500/20
                    hover:bg-purple-500/20 transition-colors"
            >
                <Sparkles size={11} />
                Explain Simply
                {result && (open ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
            </button>

            {open && (
                <div className="mt-2 rounded-lg bg-slate-800/60 border border-slate-700/50 p-3 space-y-2.5 text-xs">
                    {loading && (
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 size={12} className="animate-spin" />
                            Asking AI…
                        </div>
                    )}
                    {err && <p className="text-amber-400">{err}</p>}
                    {result && (
                        <>
                            <p className="text-slate-200 leading-relaxed">{result.explanation}</p>
                            {result.key_factors?.length > 0 && (
                                <ul className="space-y-1">
                                    {result.key_factors.map((f, i) => (
                                        <li key={i} className="flex gap-1.5 text-slate-400">
                                            <span className="text-purple-400 mt-0.5">•</span>
                                            {f}
                                        </li>
                                    ))}
                                </ul>
                            )}
                            {result.risk_note && (
                                <div className="flex gap-1.5 text-amber-400/80 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1.5">
                                    <ShieldAlert size={11} className="shrink-0 mt-0.5" />
                                    <span>{result.risk_note}</span>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

function SwingCard({ item, onNavigate }) {
    const {
        ticker, name, country, signal, final_score,
        current_price, entry_price, stop_loss, take_profit,
        signal_thesis, image_url, generated_at,
    } = item;

    // Derive levels: prefer DB columns, fall back to parsing thesis
    const parsed = parseLevels(signal_thesis || []);
    const entry  = entry_price  ?? parsed.entry  ?? null;
    const stop   = stop_loss    ?? parsed.stop   ?? null;
    const target = take_profit  ?? parsed.target ?? null;

    const top3 = (signal_thesis || []).slice(0, 3);

    const explainContext = {
        signal, ai_score: final_score,
        entry_price: entry, stop_loss: stop, take_profit: target,
        current_price,
    };

    return (
        <div className="rounded-xl border border-purple-500/20 bg-card/50 flex flex-col overflow-hidden
            hover:border-purple-500/40 hover:shadow-lg hover:shadow-purple-500/5 transition-all">

            {/* Chart image */}
            {image_url && (
                <div className="w-full h-36 bg-muted overflow-hidden shrink-0">
                    <img
                        src={image_url}
                        alt={`${ticker} chart`}
                        className="w-full h-full object-cover"
                        loading="lazy"
                    />
                </div>
            )}

            <div className="p-4 flex flex-col gap-3 flex-1">
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-bold text-sm">{ticker}</span>
                            <CountryBadge country={country} />
                        </div>
                        {name && (
                            <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[180px]">{name}</p>
                        )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <ScorePill score={final_score} />
                        <SignalBadge signal={signal} size="sm" />
                    </div>
                </div>

                {/* Current price */}
                {current_price != null && (
                    <div className="text-xs text-muted-foreground">
                        Price: <span className="text-foreground font-semibold tabular-nums">${fmt(current_price)}</span>
                    </div>
                )}

                {/* Trade levels */}
                {(entry || stop || target) && (
                    <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1.5">
                        {entry  && <LevelRow icon={Target}      label="Entry"       value={`$${fmt(entry)}`}  color="text-blue-400" />}
                        {stop   && <LevelRow icon={ShieldAlert} label="Stop Loss"   value={`$${fmt(stop)}`}   color="text-red-400" />}
                        {target && <LevelRow icon={TrendingUp}  label="Take Profit" value={`$${fmt(target)}`} color="text-emerald-400" />}
                    </div>
                )}

                {/* Thesis bullets */}
                {top3.length > 0 && (
                    <ul className="space-y-1 flex-1">
                        {top3.map((bullet, i) => (
                            <li key={i} className="flex gap-1.5 text-xs text-muted-foreground">
                                <span className="mt-0.5 shrink-0 text-purple-400">•</span>
                                <span className="line-clamp-2">{bullet}</span>
                            </li>
                        ))}
                    </ul>
                )}

                {/* Explain Simply */}
                <ExplainPanel ticker={ticker} context={explainContext} />

                {/* Footer */}
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2 pt-2 border-t border-border/40 mt-auto">
                    <span className="text-[10px] text-muted-foreground/60">{fmtDate(generated_at)}</span>
                    <button
                        onClick={() => onNavigate('hub', ticker)}
                        className="inline-flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium
                            bg-primary/10 text-primary border border-primary/20
                            hover:bg-primary/20 hover:border-primary/40 transition-colors
                            w-full sm:w-auto"
                    >
                        Deep Dive
                        <ArrowUpRight size={11} />
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Main component ─────────────────────────────────────────────────────────

const COUNTRY_FILTERS = [
    { key: 'ALL', label: 'All' },
    { key: 'US',  label: 'US'  },
    { key: 'IN',  label: 'IN'  },
];

export default function SwingSetups({ onNavigate }) {
    const [items, setItems]       = useState([]);
    const [loading, setLoading]   = useState(true);
    const [error, setError]       = useState(null);
    const [country, setCountry]   = useState('ALL');

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getSignals({ signal: 'PROACTIVE_SWING', limit: 50 });
            setItems(res.data?.signals ?? res.data ?? []);
        } catch (err) {
            setError(err?.response?.data?.detail || 'Failed to load swing setups.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const filtered = country === 'ALL'
        ? items
        : items.filter(i => (i.country ?? 'US') === country);

    return (
        <div className="space-y-4">
            {/* Freshness warning */}
            <FreshnessBanner />

            {/* Toolbar */}
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
                    {COUNTRY_FILTERS.map(f => (
                        <button
                            key={f.key}
                            onClick={() => setCountry(f.key)}
                            className={`shrink-0 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                                country === f.key
                                    ? 'bg-primary text-primary-foreground'
                                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                    {!loading && (
                        <span className="text-xs text-muted-foreground hidden sm:inline">
                            {filtered.length} setup{filtered.length !== 1 ? 's' : ''}
                        </span>
                    )}
                    <button
                        onClick={load}
                        disabled={loading}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                            border border-border bg-card/50 text-muted-foreground
                            hover:bg-accent hover:text-accent-foreground transition-colors
                            disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {loading
                            ? <Loader2 size={13} className="animate-spin" />
                            : <RefreshCw size={13} />
                        }
                        Refresh
                    </button>
                </div>
            </div>

            {/* States */}
            {loading && (
                <div className="flex items-center justify-center h-48 text-muted-foreground gap-2">
                    <Loader2 size={18} className="animate-spin" />
                    <span className="text-sm">Loading swing setups…</span>
                </div>
            )}

            {!loading && error && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-center">
                    <p className="text-sm text-red-400">{error}</p>
                    <button
                        onClick={load}
                        className="mt-3 text-xs text-muted-foreground underline hover:text-foreground"
                    >
                        Try again
                    </button>
                </div>
            )}

            {!loading && !error && filtered.length === 0 && (
                <div className="flex flex-col items-center justify-center h-48 gap-3 text-muted-foreground">
                    <TrendingUp size={32} className="opacity-30" />
                    <p className="text-sm">No swing setups found{country !== 'ALL' ? ` for ${country}` : ''}.</p>
                    <p className="text-xs opacity-60">
                        Swing setups appear when the system generates a PROACTIVE_SWING signal.
                    </p>
                </div>
            )}

            {!loading && !error && filtered.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                    {filtered.map(item => (
                        <SwingCard
                            key={`${item.ticker}-${item.generated_at ?? item.analysis_date}`}
                            item={item}
                            onNavigate={onNavigate}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
