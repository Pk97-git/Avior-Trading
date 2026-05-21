import React, { useState } from 'react';
import { alphaApi } from '../api';

// ── Helpers ───────────────────────────────────────────────────────────────────

const QUALITY_CONFIG = {
    HIGH:     { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40', label: 'HIGH QUALITY' },
    NORMAL:   { bg: 'bg-blue-500/20',    text: 'text-blue-400',    border: 'border-blue-500/40',    label: 'NORMAL' },
    MODERATE: { bg: 'bg-amber-500/20',   text: 'text-amber-400',   border: 'border-amber-500/40',   label: 'MODERATE' },
    LOW:      { bg: 'bg-orange-500/20',  text: 'text-orange-400',  border: 'border-orange-500/40',  label: 'LOW QUALITY' },
    WARNING:  { bg: 'bg-red-500/20',     text: 'text-red-400',     border: 'border-red-500/40',     label: 'WARNING' },
    UNKNOWN:  { bg: 'bg-slate-500/20',   text: 'text-slate-400',   border: 'border-slate-500/40',   label: 'UNKNOWN' },
    NO_DATA:  { bg: 'bg-slate-500/20',   text: 'text-slate-400',   border: 'border-slate-500/40',   label: 'NO DATA' },
};

const QUALITY_PLAIN = {
    HIGH:    'This company\'s reported profits are backed by real cash. That\'s rare and valuable. Hedge funds specifically hunt for this.',
    NORMAL:  'Earnings quality is adequate. Cash flow reasonably tracks reported profits.',
    MODERATE:'Earnings quality is below average. Cash conversion is weaker than ideal.',
    LOW:     'Earnings quality is weak. The company is booking profits but not collecting cash — a common precursor to earnings disappointments.',
    WARNING: 'Serious red flag. Reported earnings far exceed cash generation — a hallmark of aggressive or possibly manipulated accounting. Sloan (1996) showed these stocks underperform by 10%/year.',
};

const TONE_CONFIG = {
    BULLISH:       { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40' },
    MILDLY_BULLISH:{ bg: 'bg-green-500/20',   text: 'text-green-400',   border: 'border-green-500/40' },
    NEUTRAL:       { bg: 'bg-slate-500/20',   text: 'text-slate-300',   border: 'border-slate-500/40' },
    CAUTIOUS:      { bg: 'bg-amber-500/20',   text: 'text-amber-400',   border: 'border-amber-500/40' },
    BEARISH:       { bg: 'bg-red-500/20',     text: 'text-red-400',     border: 'border-red-500/40' },
};

const SIGNAL_CONFIG = {
    STRONG_LONG:  { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
    LONG:         { bg: 'bg-green-500/20',   text: 'text-green-400' },
    NEUTRAL:      { bg: 'bg-slate-500/20',   text: 'text-slate-300' },
    AVOID:        { bg: 'bg-orange-500/20',  text: 'text-orange-400' },
    SHORT:        { bg: 'bg-red-500/20',     text: 'text-red-400' },
    STRONG_SHORT: { bg: 'bg-red-700/30',     text: 'text-red-300' },
};

function Badge({ label, config }) {
    const c = config || { bg: 'bg-slate-500/20', text: 'text-slate-300' };
    return (
        <span className={`px-2 py-0.5 rounded text-xs font-bold ${c.bg} ${c.text}`}>
            {label}
        </span>
    );
}

function Card({ children, className = '' }) {
    return (
        <div className={`rounded-xl border border-border bg-card/60 p-4 ${className}`}>
            {children}
        </div>
    );
}

// ── Traffic-light bar for accruals ratio ─────────────────────────────────────
function AccrualsBar({ ratio }) {
    if (ratio === null || ratio === undefined) return null;
    // Map ratio to 0-100 position: -0.15 → 0, +0.15 → 100, 0 → 50
    const clamped = Math.max(-0.15, Math.min(0.15, ratio));
    const pct = ((clamped + 0.15) / 0.30) * 100;
    const color = ratio < -0.05 ? '#10b981' : ratio <= 0.05 ? '#3b82f6' : ratio <= 0.10 ? '#f59e0b' : '#ef4444';

    return (
        <div className="mt-2">
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
                <span>-0.15 (best)</span>
                <span>0</span>
                <span>+0.15 (worst)</span>
            </div>
            <div className="relative h-3 rounded-full bg-slate-700/60">
                {/* Zone colours */}
                <div className="absolute inset-0 rounded-full overflow-hidden flex">
                    <div className="h-full bg-emerald-500/30" style={{ width: '33%' }} />
                    <div className="h-full bg-blue-500/20" style={{ width: '17%' }} />
                    <div className="h-full bg-amber-500/20" style={{ width: '17%' }} />
                    <div className="h-full bg-orange-500/20" style={{ width: '16%' }} />
                    <div className="h-full bg-red-500/20" style={{ width: '17%' }} />
                </div>
                {/* Marker */}
                <div
                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 border-white shadow"
                    style={{ left: `calc(${pct}% - 6px)`, backgroundColor: color }}
                />
            </div>
            <p className="text-xs text-muted-foreground mt-1 text-center">
                Accruals ratio: <span className="font-mono font-bold">{ratio.toFixed(4)}</span>
            </p>
        </div>
    );
}

// ── Net tone bar (-10 to +10) ─────────────────────────────────────────────────
function ToneBar({ netTone }) {
    const clamped = Math.max(-10, Math.min(10, netTone));
    const pct = ((clamped + 10) / 20) * 100;
    const color = netTone > 2 ? '#10b981' : netTone > 0 ? '#34d399' : netTone > -2 ? '#94a3b8' : netTone > -4 ? '#f59e0b' : '#ef4444';

    return (
        <div className="mt-2">
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
                <span>-10 (bearish)</span>
                <span>0</span>
                <span>+10 (bullish)</span>
            </div>
            <div className="relative h-3 rounded-full bg-slate-700/60">
                <div className="absolute inset-0 rounded-full overflow-hidden flex">
                    <div className="h-full bg-red-500/30"    style={{ width: '40%' }} />
                    <div className="h-full bg-amber-500/20"  style={{ width: '20%' }} />
                    <div className="h-full bg-emerald-500/30" style={{ width: '40%' }} />
                </div>
                <div
                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 border-white shadow"
                    style={{ left: `calc(${pct}% - 6px)`, backgroundColor: color }}
                />
            </div>
            <p className="text-xs text-muted-foreground mt-1 text-center">
                Net tone: <span className="font-mono font-bold">{netTone > 0 ? '+' : ''}{netTone.toFixed(3)}</span>
            </p>
        </div>
    );
}


// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — EARNINGS QUALITY
// ══════════════════════════════════════════════════════════════════════════════

function EarningsQualityTab() {
    const [ticker, setTicker] = useState('');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    const handleAnalyse = async () => {
        if (!ticker.trim()) return;
        setLoading(true);
        setError(null);
        setData(null);
        try {
            const res = await alphaApi.earningsQuality(ticker.trim());
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const qc = data ? (QUALITY_CONFIG[data.quality] || QUALITY_CONFIG.UNKNOWN) : null;

    return (
        <div className="space-y-4 max-w-2xl">
            {/* Search */}
            <div className="flex gap-2">
                <input
                    value={ticker}
                    onChange={e => setTicker(e.target.value.toUpperCase())}
                    onKeyDown={e => e.key === 'Enter' && handleAnalyse()}
                    placeholder="e.g. RELIANCE.NS or AAPL"
                    className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <button
                    onClick={handleAnalyse}
                    disabled={loading || !ticker.trim()}
                    className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
                >
                    {loading ? 'Analysing…' : 'Analyse'}
                </button>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                    {error}
                </div>
            )}

            {data && (
                <div className="space-y-4">
                    {/* Plain-English card */}
                    {data.quality !== 'NO_DATA' && data.quality !== 'UNKNOWN' && (
                        <Card className={`border ${qc.border} ${qc.bg}`}>
                            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                                What this means
                            </p>
                            <div className="flex items-start gap-3">
                                <span className={`text-3xl font-black ${qc.text}`}>{qc.label}</span>
                            </div>
                            <p className="text-sm text-foreground/80 mt-2">
                                {QUALITY_PLAIN[data.quality] || ''}
                            </p>
                        </Card>
                    )}

                    {/* Score badge */}
                    <Card>
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wider">Earnings Quality Score</p>
                                <p className="text-xs text-muted-foreground">{data.ticker}</p>
                            </div>
                            <div className="text-right">
                                {data.score !== null ? (
                                    <span className={`text-5xl font-black ${qc.text}`}>{data.score}</span>
                                ) : (
                                    <span className="text-2xl text-muted-foreground">N/A</span>
                                )}
                                <p className="text-xs text-muted-foreground">/ 100</p>
                            </div>
                        </div>

                        {/* CFO / NI ratio */}
                        {data.cfo_to_ni !== null && data.cfo_to_ni !== undefined && (
                            <div className="rounded-lg bg-slate-800/50 p-3 mb-3">
                                <p className="text-xs text-muted-foreground mb-0.5">Cash Flow Quality</p>
                                <p className="text-lg font-bold text-foreground">
                                    {data.cfo_to_ni < 0
                                        ? 'Negative cash flow'
                                        : `${data.cfo_to_ni.toFixed(2)}x`}
                                </p>
                                <p className="text-xs text-muted-foreground mt-0.5">
                                    {data.cfo_to_ni >= 0
                                        ? `For every ₹1 of reported earnings, the company generates ₹${data.cfo_to_ni.toFixed(2)} in real cash.`
                                        : 'Operations consume more cash than they generate.'}
                                </p>
                            </div>
                        )}

                        {/* Accruals ratio bar */}
                        {data.accruals_ratio !== null && data.accruals_ratio !== undefined && (
                            <AccrualsBar ratio={data.accruals_ratio} />
                        )}

                        {/* Raw numbers */}
                        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                            {data.net_income !== null && (
                                <div className="rounded bg-slate-800/40 p-2">
                                    <p className="text-muted-foreground">Net Income</p>
                                    <p className="font-mono font-bold">{Number(data.net_income).toLocaleString()}</p>
                                </div>
                            )}
                            {data.cfo !== null && (
                                <div className="rounded bg-slate-800/40 p-2">
                                    <p className="text-muted-foreground">Cash from Ops</p>
                                    <p className="font-mono font-bold">{Number(data.cfo).toLocaleString()}</p>
                                </div>
                            )}
                            {data.accruals !== null && (
                                <div className="rounded bg-slate-800/40 p-2">
                                    <p className="text-muted-foreground">Accruals</p>
                                    <p className={`font-mono font-bold ${data.accruals > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                                        {Number(data.accruals).toLocaleString()}
                                    </p>
                                </div>
                            )}
                            {data.accruals_ratio !== null && (
                                <div className="rounded bg-slate-800/40 p-2">
                                    <p className="text-muted-foreground">Accruals / Assets</p>
                                    <p className="font-mono font-bold">{(data.accruals_ratio * 100).toFixed(2)}%</p>
                                </div>
                            )}
                        </div>
                    </Card>

                    {/* Notes */}
                    {data.notes && data.notes.length > 0 && (
                        <Card>
                            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Analysis Notes</p>
                            <ul className="space-y-1">
                                {data.notes.map((n, i) => (
                                    <li key={i} className="text-sm text-foreground/80 flex gap-2">
                                        <span className="text-primary shrink-0 mt-0.5">•</span>
                                        <span>{n}</span>
                                    </li>
                                ))}
                            </ul>
                        </Card>
                    )}

                    {data.note && (
                        <Card>
                            <p className="text-sm text-muted-foreground">{data.note}</p>
                        </Card>
                    )}

                    {/* Methodology */}
                    <p className="text-xs text-muted-foreground px-1">
                        Based on Sloan (1996): high accruals predict future earnings disappointments.
                        Stocks with low accruals outperform by ~10%/year across all markets studied.
                    </p>
                </div>
            )}
        </div>
    );
}


// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — MOMENTUM RANKINGS
// ══════════════════════════════════════════════════════════════════════════════

function MomentumRankingsTab() {
    const [country, setCountry] = useState('IN');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    const handleLoad = async () => {
        setLoading(true);
        setError(null);
        setData(null);
        try {
            const res = await alphaApi.momentumRankings({ country, limit: 100 });
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const MomentumTable = ({ rows, title, colorClass }) => (
        <Card>
            <p className={`text-xs font-semibold uppercase tracking-wider mb-3 ${colorClass}`}>{title}</p>
            {rows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No data</p>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="border-b border-border text-muted-foreground">
                                <th className="pb-2 text-left">Rank</th>
                                <th className="pb-2 text-left">Ticker</th>
                                <th className="pb-2 text-right">12-1M Return</th>
                                <th className="pb-2 text-right">Price</th>
                                <th className="pb-2 text-right">Decile</th>
                                <th className="pb-2 text-right">Signal</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border/40">
                            {rows.map(r => {
                                const sc = SIGNAL_CONFIG[r.signal] || SIGNAL_CONFIG.NEUTRAL;
                                const retColor = r.momentum_pct >= 0 ? 'text-emerald-400' : 'text-red-400';
                                return (
                                    <tr key={r.ticker} className="hover:bg-accent/30">
                                        <td className="py-1.5 text-muted-foreground">#{r.rank}</td>
                                        <td className="py-1.5 font-mono font-bold">{r.ticker}</td>
                                        <td className={`py-1.5 text-right font-mono font-bold ${retColor}`}>
                                            {r.momentum_pct > 0 ? '+' : ''}{r.momentum_pct.toFixed(1)}%
                                        </td>
                                        <td className="py-1.5 text-right text-muted-foreground">
                                            {r.current_price?.toFixed(2)}
                                        </td>
                                        <td className="py-1.5 text-right text-muted-foreground">D{r.decile}</td>
                                        <td className="py-1.5 text-right">
                                            <Badge label={r.signal} config={sc} />
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </Card>
    );

    return (
        <div className="space-y-4">
            {/* Controls */}
            <div className="flex gap-2 items-center flex-wrap">
                <select
                    value={country}
                    onChange={e => setCountry(e.target.value)}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                >
                    <option value="IN">India (IN)</option>
                    <option value="US">US</option>
                    <option value="ALL">All Countries</option>
                </select>
                <button
                    onClick={handleLoad}
                    disabled={loading}
                    className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
                >
                    {loading ? 'Loading…' : 'Get Rankings'}
                </button>
                {data && (
                    <span className="text-xs text-muted-foreground">
                        {data.total_ranked} stocks ranked
                    </span>
                )}
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                    {error}
                </div>
            )}

            {data && data.message && (
                <Card>
                    <p className="text-sm text-muted-foreground">{data.message}</p>
                </Card>
            )}

            {data && data.top_momentum && (
                <MomentumTable
                    rows={data.top_momentum}
                    title="Top Momentum — LONG Candidates"
                    colorClass="text-emerald-400"
                />
            )}

            {data && data.bottom_momentum && (
                <MomentumTable
                    rows={data.bottom_momentum}
                    title="Bottom Momentum — SHORT / AVOID"
                    colorClass="text-red-400"
                />
            )}

            {/* Methodology note */}
            <Card className="border-dashed">
                <p className="text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground/70">Methodology:</span>{' '}
                    Jegadeesh-Titman (1993) — one of the most robust factors in all of finance.
                    Ranks stocks by their 12-1 month return (skipping last month to avoid short-term reversal).
                    Works in every market, every time period studied. Long top decile, short bottom decile.
                </p>
            </Card>
        </div>
    );
}


// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — FILING TONE
// ══════════════════════════════════════════════════════════════════════════════

function FilingToneTab() {
    const [text, setText] = useState('');
    const [ticker, setTicker] = useState('');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    const handleAnalyse = async () => {
        if (text.trim().length < 20) return;
        setLoading(true);
        setError(null);
        setData(null);
        try {
            const res = await alphaApi.filingTone({ text: text.trim(), ticker: ticker.trim() });
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const tc = data ? (TONE_CONFIG[data.tone] || TONE_CONFIG.NEUTRAL) : null;

    return (
        <div className="space-y-4 max-w-2xl">
            {/* Input area */}
            <div className="space-y-2">
                <textarea
                    value={text}
                    onChange={e => setText(e.target.value)}
                    placeholder="Paste any earnings release, management commentary, or news text here…"
                    rows={8}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary resize-y"
                />
                <div className="flex gap-2">
                    <input
                        value={ticker}
                        onChange={e => setTicker(e.target.value.toUpperCase())}
                        placeholder="Ticker (optional)"
                        className="w-40 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                    <button
                        onClick={handleAnalyse}
                        disabled={loading || text.trim().length < 20}
                        className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
                    >
                        {loading ? 'Analysing…' : 'Analyse Tone'}
                    </button>
                    <span className="text-xs text-muted-foreground self-center">
                        {text.split(/\s+/).filter(Boolean).length} words
                    </span>
                </div>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                    {error}
                </div>
            )}

            {data && (
                <div className="space-y-4">
                    {/* Tone badge */}
                    <Card className={`border ${tc.border} ${tc.bg}`}>
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
                                    {data.ticker ? `${data.ticker} — ` : ''}Tone Analysis
                                </p>
                                <span className={`text-4xl font-black ${tc.text}`}>
                                    {data.tone.replace('_', ' ')}
                                </span>
                            </div>
                            <div className="text-right">
                                <p className="text-3xl font-black text-foreground">{data.tone_score}</p>
                                <p className="text-xs text-muted-foreground">/ 100</p>
                            </div>
                        </div>
                    </Card>

                    {/* Stats */}
                    <Card>
                        <div className="grid grid-cols-3 gap-3 text-center mb-4">
                            <div>
                                <p className="text-xs text-muted-foreground mb-1">Word Count</p>
                                <p className="text-xl font-bold">{data.word_count.toLocaleString()}</p>
                            </div>
                            <div>
                                <p className="text-xs text-muted-foreground mb-1">Positive %</p>
                                <p className="text-xl font-bold text-emerald-400">{data.positive_pct.toFixed(1)}%</p>
                            </div>
                            <div>
                                <p className="text-xs text-muted-foreground mb-1">Uncertainty %</p>
                                <p className="text-xl font-bold text-amber-400">{data.uncertainty_pct.toFixed(1)}%</p>
                            </div>
                        </div>

                        <ToneBar netTone={data.net_tone} />
                    </Card>

                    {/* Word chips */}
                    <div className="grid grid-cols-2 gap-3">
                        <Card>
                            <p className="text-xs font-semibold text-emerald-400 mb-2">Positive Words Found</p>
                            {data.matched_positive.length > 0 ? (
                                <div className="flex flex-wrap gap-1">
                                    {data.matched_positive.map(w => (
                                        <span key={w} className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-xs font-medium">
                                            {w}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-xs text-muted-foreground">None detected</p>
                            )}
                        </Card>
                        <Card>
                            <p className="text-xs font-semibold text-amber-400 mb-2">Uncertainty Words Found</p>
                            {data.matched_uncertainty.length > 0 ? (
                                <div className="flex flex-wrap gap-1">
                                    {data.matched_uncertainty.map(w => (
                                        <span key={w} className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-xs font-medium">
                                            {w}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-xs text-muted-foreground">None detected</p>
                            )}
                        </Card>
                    </div>

                    {/* Plain English */}
                    {data.plain_english && (
                        <Card>
                            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Summary</p>
                            <ul className="space-y-1">
                                {data.plain_english.map((line, i) => (
                                    <li key={i} className="text-sm text-foreground/80 flex gap-2">
                                        <span className="text-primary shrink-0 mt-0.5">•</span>
                                        <span>{line}</span>
                                    </li>
                                ))}
                            </ul>
                        </Card>
                    )}

                    {/* Methodology */}
                    <Card className="border-dashed">
                        <p className="text-xs text-muted-foreground">
                            <span className="font-semibold text-foreground/70">Methodology:</span>{' '}
                            Based on the Loughran-McDonald financial dictionary — the standard in academic finance.
                            Counts positive and uncertainty/negative words from a domain-specific financial lexicon,
                            calculating net tone as a quantifiable signal. Used by hedge funds to systematically
                            process earnings calls and press releases at scale.
                        </p>
                    </Card>
                </div>
            )}
        </div>
    );
}


// ══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

const TABS = [
    { id: 'earnings-quality', label: 'Earnings Quality' },
    { id: 'momentum',         label: 'Momentum Rankings' },
    { id: 'filing-tone',      label: 'Filing Tone' },
];

export default function AlphaSignals() {
    const [activeTab, setActiveTab] = useState('earnings-quality');

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <h2 className="text-lg font-bold">Alpha Signals</h2>
                <p className="text-sm text-muted-foreground">
                    Institutional-grade quantitative signals. Sloan accruals, Jegadeesh-Titman momentum, Loughran-McDonald tone analysis.
                </p>
            </div>

            {/* Tab bar */}
            <div className="flex gap-1 border-b border-border">
                {TABS.map(t => (
                    <button
                        key={t.id}
                        onClick={() => setActiveTab(t.id)}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                            activeTab === t.id
                                ? 'border-primary text-foreground'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Content */}
            {activeTab === 'earnings-quality' && <EarningsQualityTab />}
            {activeTab === 'momentum'         && <MomentumRankingsTab />}
            {activeTab === 'filing-tone'      && <FilingToneTab />}
        </div>
    );
}
