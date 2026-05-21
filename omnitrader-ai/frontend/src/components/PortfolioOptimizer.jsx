import React, { useState, useCallback } from 'react';
import { portfolioOptimizerApi } from '../api';
import { PlusCircle, X, Loader2, TrendingUp, Shield, BarChart2, ChevronDown, ChevronUp } from 'lucide-react';

// ─── Shared ticker input with chips ────────────────────────────────────────────

function TickerInput({ tickers, setTickers, maxTickers = 15 }) {
    const [inputVal, setInputVal] = useState('');

    const addTicker = useCallback(() => {
        const t = inputVal.trim().toUpperCase();
        if (!t || tickers.includes(t) || tickers.length >= maxTickers) return;
        setTickers(prev => [...prev, t]);
        setInputVal('');
    }, [inputVal, tickers, setTickers, maxTickers]);

    const removeTicker = useCallback((t) => {
        setTickers(prev => prev.filter(x => x !== t));
    }, [setTickers]);

    const handleKey = (e) => {
        if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTicker(); }
    };

    return (
        <div className="space-y-2">
            <div className="flex gap-2">
                <input
                    type="text"
                    value={inputVal}
                    onChange={e => setInputVal(e.target.value)}
                    onKeyDown={handleKey}
                    placeholder="e.g. RELIANCE.NS or AAPL"
                    className="flex-1 px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                    onClick={addTicker}
                    disabled={tickers.length >= maxTickers}
                    className="flex items-center gap-1 px-3 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                >
                    <PlusCircle size={14} /> Add
                </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
                {tickers.map(t => (
                    <span key={t} className="flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary border border-primary/20">
                        {t}
                        <button onClick={() => removeTicker(t)} className="hover:text-destructive ml-0.5">
                            <X size={11} />
                        </button>
                    </span>
                ))}
                {tickers.length === 0 && (
                    <span className="text-xs text-muted-foreground">Add at least 2 tickers</span>
                )}
            </div>
        </div>
    );
}

// ─── Period selector ────────────────────────────────────────────────────────────

function PeriodSelector({ value, onChange }) {
    return (
        <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Period:</span>
            {['6mo', '1y', '2y'].map(p => (
                <button
                    key={p}
                    onClick={() => onChange(p)}
                    className={`px-3 py-1 text-xs rounded-md border transition-colors ${value === p
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'border-border text-muted-foreground hover:bg-accent'}`}
                >
                    {p}
                </button>
            ))}
        </div>
    );
}

// ─── Weight bar ─────────────────────────────────────────────────────────────────

function WeightBar({ label, pct, color = 'bg-primary' }) {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-28 truncate text-muted-foreground">{label}</span>
            <div className="flex-1 h-1.5 rounded-full bg-muted">
                <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
            <span className="w-10 text-right font-mono">{pct.toFixed(1)}%</span>
        </div>
    );
}

// ─── Portfolio card ─────────────────────────────────────────────────────────────

function PortfolioCard({ data, highlight = false }) {
    if (!data) return null;
    const weights = data.weights || {};
    const top = Object.entries(weights).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const colors = ['bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-violet-500'];

    return (
        <div className={`rounded-lg border p-4 space-y-3 ${highlight ? 'border-amber-500/50 bg-amber-500/5' : 'border-border bg-card'}`}>
            <div className="flex items-center justify-between">
                <span className="text-sm font-semibold">{data.label}</span>
                {highlight && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">Optimal</span>}
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                    <p className="text-xs text-muted-foreground">Return</p>
                    <p className="text-sm font-bold text-emerald-400">{data.annual_return_pct?.toFixed(1)}%</p>
                </div>
                <div>
                    <p className="text-xs text-muted-foreground">Vol</p>
                    <p className="text-sm font-bold text-blue-400">{data.annual_vol_pct?.toFixed(1)}%</p>
                </div>
                <div>
                    <p className="text-xs text-muted-foreground">Sharpe</p>
                    <p className="text-sm font-bold">{data.sharpe_ratio?.toFixed(2)}</p>
                </div>
            </div>
            <div className="space-y-1.5">
                {top.map(([t, w], i) => (
                    <WeightBar key={t} label={t} pct={w * 100} color={colors[i % colors.length]} />
                ))}
            </div>
        </div>
    );
}

// ─── Frontier scatter chart (pure SVG) ─────────────────────────────────────────

function FrontierChart({ frontier, maxSharpe, minVariance }) {
    if (!frontier || frontier.length === 0) return null;

    const W = 560, H = 300, PL = 48, PR = 16, PT = 16, PB = 36;
    const IW = W - PL - PR, IH = H - PT - PB;

    const allVols = frontier.map(p => p.annual_vol_pct);
    const allRets = frontier.map(p => p.annual_return_pct);

    const minVol = Math.min(...allVols) * 0.95;
    const maxVol = Math.max(...allVols) * 1.05;
    const minRet = Math.min(...allRets) * 0.95;
    const maxRet = Math.max(...allRets) * 1.05;

    const toX = v => PL + ((v - minVol) / (maxVol - minVol)) * IW;
    const toY = r => PT + IH - ((r - minRet) / (maxRet - minRet)) * IH;

    const pathD = frontier.map((p, i) =>
        `${i === 0 ? 'M' : 'L'} ${toX(p.annual_vol_pct).toFixed(1)} ${toY(p.annual_return_pct).toFixed(1)}`
    ).join(' ');

    const yTicks = 5;
    const xTicks = 5;

    return (
        <div className="w-full overflow-x-auto">
            <svg width={W} height={H} className="text-xs font-mono">
                {/* Grid lines */}
                {Array.from({ length: yTicks }, (_, i) => {
                    const r = minRet + (maxRet - minRet) * i / (yTicks - 1);
                    const y = toY(r);
                    return (
                        <g key={i}>
                            <line x1={PL} x2={PL + IW} y1={y} y2={y} stroke="currentColor" strokeOpacity={0.1} />
                            <text x={PL - 4} y={y + 4} textAnchor="end" fill="currentColor" opacity={0.5} fontSize={9}>
                                {r.toFixed(0)}%
                            </text>
                        </g>
                    );
                })}
                {Array.from({ length: xTicks }, (_, i) => {
                    const v = minVol + (maxVol - minVol) * i / (xTicks - 1);
                    const x = toX(v);
                    return (
                        <g key={i}>
                            <line x1={x} x2={x} y1={PT} y2={PT + IH} stroke="currentColor" strokeOpacity={0.1} />
                            <text x={x} y={PT + IH + 14} textAnchor="middle" fill="currentColor" opacity={0.5} fontSize={9}>
                                {v.toFixed(0)}%
                            </text>
                        </g>
                    );
                })}
                {/* Axis labels */}
                <text x={PL + IW / 2} y={H - 2} textAnchor="middle" fill="currentColor" opacity={0.4} fontSize={9}>
                    Volatility (%)
                </text>
                <text transform={`translate(10,${PT + IH / 2}) rotate(-90)`} textAnchor="middle" fill="currentColor" opacity={0.4} fontSize={9}>
                    Return (%)
                </text>
                {/* Frontier path */}
                <path d={pathD} fill="none" stroke="#6366f1" strokeWidth={2} />
                {/* Frontier dots */}
                {frontier.map((p, i) => (
                    <circle key={i} cx={toX(p.annual_vol_pct)} cy={toY(p.annual_return_pct)} r={3}
                        fill="#6366f1" opacity={0.6} />
                ))}
                {/* Max Sharpe star */}
                {maxSharpe && (() => {
                    const cx = toX(maxSharpe.annual_vol_pct);
                    const cy = toY(maxSharpe.annual_return_pct);
                    return (
                        <g>
                            <circle cx={cx} cy={cy} r={8} fill="#f59e0b" opacity={0.3} />
                            <text x={cx} y={cy + 4} textAnchor="middle" fontSize={12}>★</text>
                            <text x={cx + 10} y={cy - 6} fill="#f59e0b" fontSize={9}>Max Sharpe</text>
                        </g>
                    );
                })()}
                {/* Min Variance dot */}
                {minVariance && (() => {
                    const cx = toX(minVariance.annual_vol_pct);
                    const cy = toY(minVariance.annual_return_pct);
                    return (
                        <g>
                            <circle cx={cx} cy={cy} r={6} fill="#3b82f6" />
                            <text x={cx + 10} y={cy + 4} fill="#3b82f6" fontSize={9}>Min Var</text>
                        </g>
                    );
                })()}
            </svg>
        </div>
    );
}

// ─── Correlation matrix ────────────────────────────────────────────────────────

function CorrelationMatrix({ matrix, tickers }) {
    if (!matrix || !tickers) return null;

    const cellColor = (v) => {
        const abs = Math.abs(v);
        if (abs > 0.8) return 'bg-red-500/70';
        if (abs > 0.6) return 'bg-orange-500/50';
        if (abs > 0.4) return 'bg-yellow-500/30';
        return 'bg-emerald-500/20';
    };

    return (
        <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
                <thead>
                    <tr>
                        <th className="p-1 text-muted-foreground"></th>
                        {tickers.map(t => (
                            <th key={t} className="p-1 text-center text-muted-foreground font-normal max-w-[48px] truncate">{t.split('.')[0]}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {tickers.map(t1 => (
                        <tr key={t1}>
                            <td className="p-1 text-muted-foreground pr-2 whitespace-nowrap">{t1.split('.')[0]}</td>
                            {tickers.map(t2 => {
                                const v = matrix[t1]?.[t2] ?? 0;
                                return (
                                    <td key={t2} title={`${t1}/${t2}: ${v.toFixed(3)}`}
                                        className={`p-1 text-center rounded ${cellColor(v)} font-mono`}>
                                        {v.toFixed(2)}
                                    </td>
                                );
                            })}
                        </tr>
                    ))}
                </tbody>
            </table>
            <div className="flex gap-3 mt-2 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500/70 inline-block" /> &gt;0.8</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-orange-500/50 inline-block" /> 0.6-0.8</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-yellow-500/30 inline-block" /> 0.4-0.6</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-emerald-500/20 inline-block" /> &lt;0.4</span>
            </div>
        </div>
    );
}

// ─── Plain English bullets ─────────────────────────────────────────────────────

function PlainEnglish({ lines }) {
    if (!lines || lines.length === 0) return null;
    return (
        <div className="rounded-md border border-primary/20 bg-primary/5 p-3 space-y-1">
            {lines.map((l, i) => (
                <p key={i} className="text-sm text-muted-foreground flex gap-2">
                    <span className="text-primary mt-0.5">•</span>
                    <span>{l}</span>
                </p>
            ))}
        </div>
    );
}

// ─── TAB 1: Efficient Frontier ─────────────────────────────────────────────────

function EfficientFrontierTab() {
    const [tickers, setTickers] = useState(['RELIANCE.NS', 'INFY.NS', 'TCS.NS', 'HDFCBANK.NS']);
    const [period, setPeriod] = useState('1y');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [showFrontier, setShowFrontier] = useState(true);
    const [showCorr, setShowCorr] = useState(false);

    const run = async () => {
        if (tickers.length < 2) { setError('Add at least 2 tickers'); return; }
        setLoading(true); setError(null); setResult(null);
        try {
            const res = await portfolioOptimizerApi.frontier({ tickers, period, n_points: 30 });
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-5">
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
                <div className="flex-1 space-y-2">
                    <label className="text-sm font-medium">Tickers</label>
                    <TickerInput tickers={tickers} setTickers={setTickers} />
                </div>
                <div className="flex flex-col gap-2">
                    <PeriodSelector value={period} onChange={setPeriod} />
                    <button
                        onClick={run}
                        disabled={loading || tickers.length < 2}
                        className="flex items-center justify-center gap-2 px-6 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 text-sm font-medium"
                    >
                        {loading ? <><Loader2 size={14} className="animate-spin" /> Computing...</> : <><TrendingUp size={14} /> Optimize</>}
                    </button>
                </div>
            </div>

            {error && <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{error}</div>}

            {result && !result.error && (
                <div className="space-y-6">
                    {/* Three portfolio cards */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <PortfolioCard data={result.max_sharpe} highlight />
                        <PortfolioCard data={result.min_variance} />
                        <PortfolioCard data={result.equal_weight} />
                    </div>

                    {/* Frontier chart */}
                    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
                        <button
                            onClick={() => setShowFrontier(v => !v)}
                            className="flex items-center gap-2 text-sm font-semibold w-full"
                        >
                            Efficient Frontier
                            {showFrontier ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                        {showFrontier && (
                            <FrontierChart
                                frontier={result.frontier}
                                maxSharpe={result.max_sharpe}
                                minVariance={result.min_variance}
                            />
                        )}
                    </div>

                    {/* Correlation matrix */}
                    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
                        <button
                            onClick={() => setShowCorr(v => !v)}
                            className="flex items-center gap-2 text-sm font-semibold w-full"
                        >
                            Correlation Matrix
                            {showCorr ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                        {showCorr && (
                            <CorrelationMatrix matrix={result.correlation_matrix} tickers={result.tickers} />
                        )}
                    </div>

                    {/* Plain English */}
                    <PlainEnglish lines={result.plain_english} />
                </div>
            )}

            {result?.error && (
                <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{result.error}</div>
            )}
        </div>
    );
}

// ─── TAB 2: Risk Parity ───────────────────────────────────────────────────────

function RiskParityTab() {
    const [tickers, setTickers] = useState(['RELIANCE.NS', 'INFY.NS', 'TCS.NS', 'HDFCBANK.NS']);
    const [period, setPeriod] = useState('1y');
    const [useDB, setUseDB] = useState(false);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = async () => {
        setLoading(true); setError(null); setResult(null);
        try {
            let res;
            if (useDB) {
                res = await portfolioOptimizerApi.current();
                setResult(res.data?.risk_parity || res.data);
            } else {
                if (tickers.length < 2) { setError('Add at least 2 tickers'); setLoading(false); return; }
                res = await portfolioOptimizerApi.riskParity({ tickers, period });
                setResult(res.data);
            }
        } catch (e) {
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    };

    const holdings = result?.holdings || [];
    const n = holdings.length;
    const targetPct = n > 0 ? (100 / n).toFixed(1) : '—';

    return (
        <div className="space-y-5">
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
                <div className="flex-1 space-y-3">
                    <div className="flex items-center gap-3">
                        <label className="text-sm font-medium">Tickers</label>
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                            <input type="checkbox" checked={useDB} onChange={e => setUseDB(e.target.checked)} className="rounded" />
                            Use current portfolio from DB
                        </label>
                    </div>
                    {!useDB && <TickerInput tickers={tickers} setTickers={setTickers} />}
                </div>
                <div className="flex flex-col gap-2">
                    {!useDB && <PeriodSelector value={period} onChange={setPeriod} />}
                    <button
                        onClick={run}
                        disabled={loading || (!useDB && tickers.length < 2)}
                        className="flex items-center justify-center gap-2 px-6 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 text-sm font-medium"
                    >
                        {loading ? <><Loader2 size={14} className="animate-spin" /> Computing...</> : <><Shield size={14} /> Compute</>}
                    </button>
                </div>
            </div>

            {error && <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{error}</div>}

            {result && !result.error && holdings.length > 0 && (
                <div className="space-y-4">
                    {/* Callout */}
                    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-center">
                        <p className="text-2xl font-bold text-primary">{targetPct}%</p>
                        <p className="text-sm text-muted-foreground mt-1">
                            Each position contributes exactly {targetPct}% to total portfolio risk
                        </p>
                    </div>

                    {/* Stats row */}
                    <div className="grid grid-cols-3 gap-3">
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Annual Return</p>
                            <p className="text-lg font-bold text-emerald-400">{result.annual_return_pct?.toFixed(1)}%</p>
                        </div>
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Volatility</p>
                            <p className="text-lg font-bold text-blue-400">{result.annual_vol_pct?.toFixed(1)}%</p>
                        </div>
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Sharpe Ratio</p>
                            <p className="text-lg font-bold">{result.sharpe_ratio?.toFixed(2)}</p>
                        </div>
                    </div>

                    {/* Holdings table */}
                    <div className="rounded-lg border border-border bg-card overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/50">
                                <tr>
                                    <th className="text-left p-3 text-xs text-muted-foreground font-medium">Ticker</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Capital Weight</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Risk Contribution</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Daily Vol</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {holdings.map(h => (
                                    <tr key={h.ticker} className="hover:bg-muted/30">
                                        <td className="p-3 font-medium">{h.ticker}</td>
                                        <td className="p-3 text-right">
                                            <div className="flex items-center justify-end gap-2">
                                                <div className="w-20 h-1.5 rounded-full bg-muted">
                                                    <div className="h-1.5 rounded-full bg-primary" style={{ width: `${Math.min(100, h.weight_pct)}%` }} />
                                                </div>
                                                <span className="font-mono w-12 text-right">{h.weight_pct?.toFixed(1)}%</span>
                                            </div>
                                        </td>
                                        <td className="p-3 text-right font-mono text-muted-foreground">{h.risk_contribution_pct?.toFixed(1)}%</td>
                                        <td className="p-3 text-right font-mono text-muted-foreground">{h.daily_vol_pct?.toFixed(2)}%</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <PlainEnglish lines={result.plain_english} />
                </div>
            )}

            {result?.error && (
                <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{result.error}</div>
            )}
        </div>
    );
}

// ─── TAB 3: Black-Litterman ────────────────────────────────────────────────────

function BlackLittermanTab() {
    const [tickers, setTickers] = useState(['RELIANCE.NS', 'INFY.NS', 'TCS.NS', 'HDFCBANK.NS']);
    const [period, setPeriod] = useState('1y');
    const [views, setViews] = useState([]);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const addView = () => {
        if (tickers.length === 0) return;
        setViews(prev => [...prev, { assets: [tickers[0]], expected_return: 0.15, confidence: 0.5 }]);
    };

    const removeView = (i) => setViews(prev => prev.filter((_, idx) => idx !== i));

    const updateView = (i, field, val) => {
        setViews(prev => prev.map((v, idx) => idx === i ? { ...v, [field]: val } : v));
    };

    const run = async () => {
        if (tickers.length < 2) { setError('Add at least 2 tickers'); return; }
        setLoading(true); setError(null); setResult(null);
        try {
            const res = await portfolioOptimizerApi.blackLitterman({ tickers, period, views });
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-5">
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
                <div className="flex-1 space-y-2">
                    <label className="text-sm font-medium">Tickers</label>
                    <TickerInput tickers={tickers} setTickers={setTickers} />
                </div>
                <div className="flex flex-col gap-2">
                    <PeriodSelector value={period} onChange={setPeriod} />
                    <button
                        onClick={run}
                        disabled={loading || tickers.length < 2}
                        className="flex items-center justify-center gap-2 px-6 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 text-sm font-medium"
                    >
                        {loading ? <><Loader2 size={14} className="animate-spin" /> Computing...</> : <><BarChart2 size={14} /> Compute</>}
                    </button>
                </div>
            </div>

            {/* Views builder */}
            <div className="rounded-lg border border-border bg-card p-4 space-y-3">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">Investor Views</h3>
                    <button
                        onClick={addView}
                        disabled={tickers.length === 0}
                        className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md border border-border hover:bg-accent disabled:opacity-40"
                    >
                        <PlusCircle size={12} /> Add View
                    </button>
                </div>
                {views.length === 0 && (
                    <p className="text-xs text-muted-foreground">No views — will use market equilibrium only.</p>
                )}
                {views.map((v, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-background/50 p-3">
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">Asset:</span>
                            <select
                                value={v.assets[0] || ''}
                                onChange={e => updateView(i, 'assets', [e.target.value])}
                                className="text-xs rounded border border-border bg-background px-2 py-1"
                            >
                                {tickers.map(t => <option key={t} value={t}>{t}</option>)}
                            </select>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">Expected return:</span>
                            <input
                                type="number"
                                step="0.01"
                                min="-1"
                                max="5"
                                value={(v.expected_return * 100).toFixed(0)}
                                onChange={e => updateView(i, 'expected_return', parseFloat(e.target.value) / 100)}
                                className="w-16 text-xs rounded border border-border bg-background px-2 py-1 text-right"
                            />
                            <span className="text-xs text-muted-foreground">%</span>
                        </div>
                        <div className="flex items-center gap-2 flex-1 min-w-[140px]">
                            <span className="text-xs text-muted-foreground whitespace-nowrap">Confidence: {(v.confidence * 100).toFixed(0)}%</span>
                            <input
                                type="range"
                                min="10"
                                max="90"
                                step="5"
                                value={v.confidence * 100}
                                onChange={e => updateView(i, 'confidence', parseFloat(e.target.value) / 100)}
                                className="flex-1 accent-primary"
                            />
                        </div>
                        <button onClick={() => removeView(i)} className="text-muted-foreground hover:text-destructive">
                            <X size={14} />
                        </button>
                        <p className="w-full text-[10px] text-muted-foreground">
                            "I think <strong>{v.assets[0]}</strong> will return <strong>{(v.expected_return * 100).toFixed(0)}%</strong> annually — {v.confidence >= 0.7 ? 'high' : v.confidence >= 0.5 ? 'moderate' : 'low'} confidence"
                        </p>
                    </div>
                ))}
            </div>

            {error && <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{error}</div>}

            {result && !result.error && (
                <div className="space-y-4">
                    {/* Stats */}
                    <div className="grid grid-cols-3 gap-3">
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Annual Return</p>
                            <p className="text-lg font-bold text-emerald-400">{result.annual_return_pct?.toFixed(1)}%</p>
                        </div>
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Volatility</p>
                            <p className="text-lg font-bold text-blue-400">{result.annual_vol_pct?.toFixed(1)}%</p>
                        </div>
                        <div className="rounded-md border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground">Sharpe Ratio</p>
                            <p className="text-lg font-bold">{result.sharpe_ratio?.toFixed(2)}</p>
                        </div>
                    </div>

                    {/* Holdings table */}
                    <div className="rounded-lg border border-border bg-card overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/50">
                                <tr>
                                    <th className="text-left p-3 text-xs text-muted-foreground font-medium">Ticker</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Market Wt</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">BL Weight</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Tilt</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">Implied Ret</th>
                                    <th className="text-right p-3 text-xs text-muted-foreground font-medium">BL Ret</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {(result.holdings || []).map(h => (
                                    <tr key={h.ticker} className="hover:bg-muted/30">
                                        <td className="p-3 font-medium">{h.ticker}</td>
                                        <td className="p-3 text-right font-mono text-muted-foreground">{h.market_weight_pct?.toFixed(1)}%</td>
                                        <td className="p-3 text-right font-mono font-semibold">{h.bl_weight_pct?.toFixed(1)}%</td>
                                        <td className={`p-3 text-right font-mono font-semibold ${h.tilt_pct > 0 ? 'text-emerald-400' : h.tilt_pct < 0 ? 'text-red-400' : 'text-muted-foreground'}`}>
                                            {h.tilt_pct > 0 ? '+' : ''}{h.tilt_pct?.toFixed(1)}%
                                        </td>
                                        <td className="p-3 text-right font-mono text-muted-foreground">{h.implied_return_pct?.toFixed(1)}%</td>
                                        <td className="p-3 text-right font-mono">{h.bl_expected_return_pct?.toFixed(1)}%</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <PlainEnglish lines={result.plain_english} />
                </div>
            )}

            {result?.error && (
                <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">{result.error}</div>
            )}
        </div>
    );
}

// ─── Main component ────────────────────────────────────────────────────────────

const TABS = [
    { id: 'frontier',  label: 'Efficient Frontier', icon: TrendingUp },
    { id: 'riskparity', label: 'Risk Parity',       icon: Shield },
    { id: 'bl',        label: 'Black-Litterman',    icon: BarChart2 },
];

export default function PortfolioOptimizer() {
    const [activeTab, setActiveTab] = useState('frontier');

    return (
        <div className="space-y-5">
            {/* Header */}
            <div>
                <h2 className="text-lg font-bold">Portfolio Optimizer</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                    Markowitz mean-variance, risk parity, and Black-Litterman optimization
                </p>
            </div>

            {/* Tab bar */}
            <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1 w-fit">
                {TABS.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === tab.id
                            ? 'bg-primary text-primary-foreground'
                            : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'}`}
                    >
                        <tab.icon size={14} />
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                {activeTab === 'frontier'   && <EfficientFrontierTab />}
                {activeTab === 'riskparity' && <RiskParityTab />}
                {activeTab === 'bl'         && <BlackLittermanTab />}
            </div>
        </div>
    );
}
