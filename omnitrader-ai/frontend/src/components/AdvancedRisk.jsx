import React, { useState, useCallback } from 'react';
import { advancedRiskApi } from '../api';

// ─── Utility helpers ──────────────────────────────────────────────────────────

function Badge({ label, level }) {
    const colors = {
        OK:            'bg-green-500/20 text-green-400 border border-green-500/40',
        NORMAL:        'bg-green-500/20 text-green-400 border border-green-500/40',
        WARNING:       'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40',
        ELEVATED:      'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40',
        CRITICAL:      'bg-orange-500/20 text-orange-400 border border-orange-500/40',
        CRASH_WARNING: 'bg-red-500/20 text-red-400 border border-red-500/40',
        HALT:          'bg-red-600/30 text-red-300 border border-red-500/60',
        ITM:           'bg-green-500/20 text-green-400 border border-green-500/40',
        ATM:           'bg-blue-500/20 text-blue-400 border border-blue-500/40',
        OTM:           'bg-slate-500/20 text-slate-400 border border-slate-500/40',
        NONE:          'bg-green-500/20 text-green-400 border border-green-500/40',
        LIGHT:         'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40',
        MODERATE:      'bg-orange-500/20 text-orange-300 border border-orange-500/40',
        HEAVY:         'bg-red-500/20 text-red-300 border border-red-500/40',
        DEFENSIVE:     'bg-red-700/30 text-red-200 border border-red-500/60',
    };
    const cls = colors[level] || 'bg-slate-700 text-slate-300 border border-slate-600';
    return (
        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>
            {label || level}
        </span>
    );
}

function Card({ title, value, sub, accent }) {
    const accentCls = accent === 'green' ? 'text-green-400'
        : accent === 'red' ? 'text-red-400'
        : accent === 'yellow' ? 'text-yellow-400'
        : 'text-slate-200';
    return (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 flex flex-col gap-1">
            <span className="text-xs text-slate-500 uppercase tracking-wider">{title}</span>
            <span className={`text-2xl font-bold font-mono ${accentCls}`}>{value}</span>
            {sub && <span className="text-xs text-slate-500">{sub}</span>}
        </div>
    );
}

function ErrorBox({ msg }) {
    if (!msg) return null;
    return (
        <div className="bg-red-900/40 border border-red-700 text-red-300 text-sm px-4 py-3 rounded-lg mt-2">
            {msg}
        </div>
    );
}

function LoadingSpinner() {
    return (
        <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
        </div>
    );
}

const TABS = [
    { id: 'drawdown',    label: 'Drawdown Monitor' },
    { id: 'greeks',      label: 'Options Greeks' },
    { id: 'correlation', label: 'Correlation Monitor' },
    { id: 'tailrisk',    label: 'Tail Risk Score' },
];

// ─── 1. Drawdown Monitor ──────────────────────────────────────────────────────

function DrawdownMonitor() {
    const [returnsInput, setReturnsInput] = useState('0.01,-0.02,0.015,-0.008,0.012,-0.025,0.003,-0.018,0.022,-0.011');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');

    const run = useCallback(async () => {
        setError(''); setResult(null); setLoading(true);
        try {
            const returns = returnsInput.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
            if (returns.length < 2) { setError('Enter at least 2 comma-separated return values.'); setLoading(false); return; }
            const { data } = await advancedRiskApi.drawdown({ returns });
            setResult(data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally { setLoading(false); }
    }, [returnsInput]);

    const dd = result?.drawdown_series || [];
    const maxBar = dd.length ? Math.max(...dd.map(Math.abs), 0.01) : 1;

    return (
        <div className="space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
                <label className="block text-sm text-slate-400">Daily Returns (comma-separated, e.g. 0.01,-0.02,...)</label>
                <textarea
                    value={returnsInput}
                    onChange={e => setReturnsInput(e.target.value)}
                    rows={3}
                    className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 font-mono resize-none focus:outline-none focus:border-sky-500"
                />
                <button
                    onClick={run}
                    disabled={loading}
                    className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded transition-colors"
                >
                    {loading ? 'Computing…' : 'Analyze Drawdown'}
                </button>
            </div>

            {loading && <LoadingSpinner />}
            <ErrorBox msg={error} />

            {result && (
                <div className="space-y-4">
                    {/* Key metrics */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <Card
                            title="Current Drawdown"
                            value={`${result.current_drawdown_pct?.toFixed(2)}%`}
                            accent={result.current_drawdown_pct < -5 ? 'red' : 'green'}
                        />
                        <Card
                            title="Max Drawdown"
                            value={`${result.max_drawdown_pct?.toFixed(2)}%`}
                            accent="red"
                        />
                        <Card
                            title="Calmar Ratio"
                            value={result.calmar_ratio !== null ? result.calmar_ratio?.toFixed(2) : 'N/A'}
                            accent={result.calmar_ratio > 1 ? 'green' : 'yellow'}
                        />
                        <Card
                            title="Annual Return"
                            value={`${result.annual_return_pct?.toFixed(2)}%`}
                            accent={result.annual_return_pct >= 0 ? 'green' : 'red'}
                        />
                    </div>

                    {/* Alert + multiplier */}
                    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 flex flex-wrap items-center gap-4">
                        <div>
                            <span className="text-xs text-slate-500 mr-2">Alert Level</span>
                            <Badge level={result.alert_level} />
                        </div>
                        <div>
                            <span className="text-xs text-slate-500 mr-2">Position Size Multiplier</span>
                            <span className="font-mono font-bold text-sky-300 text-lg">
                                {(result.position_size_multiplier * 100).toFixed(0)}%
                            </span>
                        </div>
                        <div>
                            <span className="text-xs text-slate-500 mr-2">Recovery Est.</span>
                            <span className="font-mono text-slate-300">{result.recovery_days_estimate} days</span>
                        </div>
                    </div>

                    {/* Drawdown chart (SVG bar chart) */}
                    {dd.length > 0 && (
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                            <h3 className="text-sm font-semibold text-slate-300 mb-3">Drawdown Series (%)</h3>
                            <svg viewBox={`0 0 ${dd.length * 8} 80`} className="w-full h-24" preserveAspectRatio="none">
                                {dd.map((v, i) => {
                                    const barH = Math.abs(v) / maxBar * 70;
                                    return (
                                        <rect
                                            key={i}
                                            x={i * 8}
                                            y={70 - barH}
                                            width={7}
                                            height={barH}
                                            fill={v < -10 ? '#ef4444' : v < -5 ? '#f97316' : '#94a3b8'}
                                            opacity={0.85}
                                        />
                                    );
                                })}
                            </svg>
                        </div>
                    )}

                    {/* Bullets */}
                    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                        <h3 className="text-sm font-semibold text-slate-300 mb-2">Analysis</h3>
                        <ul className="space-y-1">
                            {result.bullets?.map((b, i) => (
                                <li key={i} className="text-sm text-slate-400 flex gap-2">
                                    <span className="text-sky-500 shrink-0">•</span>{b}
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}
        </div>
    );
}

// ─── 2. Options Greeks ────────────────────────────────────────────────────────

function OptionsGreeks() {
    const [form, setForm] = useState({ S: 150, K: 155, T_days: 30, sigma: 0.25, option_type: 'call', quantity: 1, r: 0.05 });
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

    const run = useCallback(async () => {
        setError(''); setResult(null); setLoading(true);
        try {
            const { data } = await advancedRiskApi.greeks({
                S: +form.S, K: +form.K, T_days: +form.T_days,
                sigma: +form.sigma, option_type: form.option_type,
                quantity: +form.quantity, r: +form.r,
            });
            setResult(data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally { setLoading(false); }
    }, [form]);

    const field = (label, key, type = 'number', step = '0.01') => (
        <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">{label}</label>
            <input
                type={type}
                step={step}
                value={form[key]}
                onChange={e => set(key, e.target.value)}
                className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
            />
        </div>
    );

    return (
        <div className="space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {field('Stock Price (S)', 'S')}
                    {field('Strike Price (K)', 'K')}
                    {field('Days to Expiry (T)', 'T_days', 'number', '1')}
                    {field('Implied Vol (σ)', 'sigma', 'number', '0.01')}
                    {field('Quantity', 'quantity', 'number', '1')}
                    {field('Risk-Free Rate (r)', 'r', 'number', '0.001')}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs text-slate-500">Option Type</label>
                        <select
                            value={form.option_type}
                            onChange={e => set('option_type', e.target.value)}
                            className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
                        >
                            <option value="call">Call</option>
                            <option value="put">Put</option>
                        </select>
                    </div>
                </div>
                <button
                    onClick={run}
                    disabled={loading}
                    className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded transition-colors"
                >
                    {loading ? 'Computing…' : 'Compute Greeks'}
                </button>
            </div>

            {loading && <LoadingSpinner />}
            <ErrorBox msg={error} />

            {result && (
                <div className="space-y-4">
                    {/* Main greeks grid */}
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        <Card title="Delta" value={result.delta?.toFixed(4)} accent={result.delta > 0 ? 'green' : 'red'} />
                        <Card title="Gamma" value={result.gamma?.toFixed(6)} />
                        <Card title="Theta /day" value={result.theta?.toFixed(4)} accent="red" sub="time decay" />
                        <Card title="Vega /1% vol" value={result.vega?.toFixed(4)} accent="yellow" />
                        <Card title="Rho" value={result.rho?.toFixed(4)} />
                    </div>

                    {/* Price breakdown */}
                    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
                        <div className="flex flex-wrap gap-4 items-center">
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Option Price</span>
                                <span className="font-mono text-sky-300 font-bold text-lg">${result.option_price?.toFixed(4)}</span>
                            </div>
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Intrinsic</span>
                                <span className="font-mono text-slate-300">${result.intrinsic_value?.toFixed(4)}</span>
                            </div>
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Time Value</span>
                                <span className="font-mono text-slate-300">${result.time_value?.toFixed(4)}</span>
                            </div>
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Breakeven</span>
                                <span className="font-mono text-slate-300">${result.breakeven?.toFixed(4)}</span>
                            </div>
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Delta $</span>
                                <span className="font-mono text-yellow-300 font-semibold">${result.delta_dollars?.toFixed(2)}</span>
                            </div>
                            <div>
                                <span className="text-xs text-slate-500 mr-2">Moneyness</span>
                                <Badge level={result.moneyness} />
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

// ─── 3. Correlation Monitor ───────────────────────────────────────────────────

const DEFAULT_TICKERS = 'AAPL,MSFT,GOOG,AMZN,META';

function CorrelationMonitor() {
    const [tickersInput, setTickersInput] = useState(DEFAULT_TICKERS);
    const [period, setPeriod] = useState('3mo');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');

    const run = useCallback(async () => {
        setError(''); setResult(null); setLoading(true);
        try {
            const { data } = await advancedRiskApi.correlation({ tickers: tickersInput, period });
            setResult(data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally { setLoading(false); }
    }, [tickersInput, period]);

    const breakdown = result?.breakdown;
    const rolling = result?.rolling_history?.history || [];
    const maxCorr = rolling.length ? Math.max(...rolling.map(r => Math.abs(r.avg_corr)), 0.01) : 1;

    const alertLevel = breakdown?.alert || 'NORMAL';

    return (
        <div className="space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="flex flex-col gap-1 md:col-span-2">
                        <label className="text-xs text-slate-500">Tickers (comma-separated)</label>
                        <input
                            value={tickersInput}
                            onChange={e => setTickersInput(e.target.value)}
                            className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
                            placeholder="AAPL,MSFT,GOOG,AMZN"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-xs text-slate-500">Period</label>
                        <select
                            value={period}
                            onChange={e => setPeriod(e.target.value)}
                            className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
                        >
                            {['1mo','3mo','6mo','1y','2y'].map(p => <option key={p} value={p}>{p}</option>)}
                        </select>
                    </div>
                </div>
                <button
                    onClick={run}
                    disabled={loading}
                    className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded transition-colors"
                >
                    {loading ? 'Fetching…' : 'Analyze Correlations'}
                </button>
            </div>

            {loading && <LoadingSpinner />}
            <ErrorBox msg={error} />

            {breakdown && (
                <div className="space-y-4">
                    {/* Summary stats */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <Card title="Avg Corr (Short)" value={breakdown.avg_corr_short?.toFixed(3)} />
                        <Card title="Avg Corr (Long)" value={breakdown.avg_corr_long?.toFixed(3)} />
                        <Card title="Spike Ratio" value={`${breakdown.spike_ratio?.toFixed(2)}x`}
                            accent={breakdown.spike_ratio > 1.5 ? 'red' : breakdown.spike_ratio > 1.2 ? 'yellow' : 'green'} />
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 flex flex-col gap-2">
                            <span className="text-xs text-slate-500 uppercase tracking-wider">Alert</span>
                            <Badge level={alertLevel} />
                        </div>
                    </div>

                    {/* Top 5 pairs */}
                    {breakdown.top5_spiking_pairs?.length > 0 && (
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                            <h3 className="text-sm font-semibold text-slate-300 mb-3">Top Spiking Pairs</h3>
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-xs text-slate-500 border-b border-slate-700">
                                        <th className="text-left py-1">Pair</th>
                                        <th className="text-right py-1">Short Corr</th>
                                        <th className="text-right py-1">Long Corr</th>
                                        <th className="text-right py-1">Delta</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {breakdown.top5_spiking_pairs.map((p, i) => (
                                        <tr key={i} className="border-b border-slate-700/50">
                                            <td className="py-1.5 text-slate-300 font-mono">{p.ticker_a} / {p.ticker_b}</td>
                                            <td className="text-right text-slate-300 font-mono">{p.corr_short?.toFixed(3)}</td>
                                            <td className="text-right text-slate-300 font-mono">{p.corr_long?.toFixed(3)}</td>
                                            <td className={`text-right font-mono font-semibold ${p.delta > 0 ? 'text-red-400' : 'text-green-400'}`}>
                                                {p.delta !== null ? `${p.delta > 0 ? '+' : ''}${p.delta?.toFixed(3)}` : 'N/A'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* Rolling correlation mini-chart (20 SVG dots) */}
                    {rolling.length > 0 && (
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                            <h3 className="text-sm font-semibold text-slate-300 mb-3">Rolling Avg Correlation History</h3>
                            <svg viewBox={`0 0 ${rolling.length * 12} 60`} className="w-full h-16" preserveAspectRatio="none">
                                {rolling.map((pt, i) => {
                                    const y = 55 - (pt.avg_corr / maxCorr) * 50;
                                    const color = pt.avg_corr > 0.7 ? '#ef4444' : pt.avg_corr > 0.5 ? '#f97316' : '#22c55e';
                                    return (
                                        <g key={i}>
                                            {i > 0 && (
                                                <line
                                                    x1={(i - 1) * 12 + 6}
                                                    y1={55 - (rolling[i - 1].avg_corr / maxCorr) * 50}
                                                    x2={i * 12 + 6}
                                                    y2={y}
                                                    stroke="#475569"
                                                    strokeWidth="1"
                                                />
                                            )}
                                            <circle cx={i * 12 + 6} cy={y} r="3" fill={color} />
                                        </g>
                                    );
                                })}
                            </svg>
                        </div>
                    )}

                    {/* Explanation */}
                    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                        <h3 className="text-sm font-semibold text-slate-300 mb-2">Analysis</h3>
                        <ul className="space-y-1">
                            {breakdown.explanation?.map((b, i) => (
                                <li key={i} className="text-sm text-slate-400 flex gap-2">
                                    <span className="text-sky-500 shrink-0">•</span>{b}
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}
        </div>
    );
}

// ─── 4. Tail Risk Score ───────────────────────────────────────────────────────

function TailRiskScore() {
    const [form, setForm] = useState({
        max_drawdown_pct: -12,
        current_drawdown_pct: -8,
        avg_correlation: 0.55,
        var_95_pct: 3.5,
        regime: 'NEUTRAL',
        vix_level: '',
        beta: '',
    });
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

    const run = useCallback(async () => {
        setError(''); setResult(null); setLoading(true);
        try {
            const body = {
                ...form,
                max_drawdown_pct: +form.max_drawdown_pct,
                current_drawdown_pct: +form.current_drawdown_pct,
                avg_correlation: +form.avg_correlation,
                var_95_pct: +form.var_95_pct,
                vix_level: form.vix_level !== '' ? +form.vix_level : null,
                beta: form.beta !== '' ? +form.beta : null,
            };
            const { data } = await advancedRiskApi.tailRisk(body);
            setResult(data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally { setLoading(false); }
    }, [form]);

    const score = result?.tail_risk_score ?? 0;
    const gaugeColor = score >= 80 ? '#ef4444' : score >= 60 ? '#f97316' : score >= 40 ? '#eab308' : score >= 20 ? '#84cc16' : '#22c55e';

    const field = (label, key, type = 'number', step = '0.01') => (
        <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">{label}</label>
            <input
                type={type}
                step={step}
                value={form[key]}
                onChange={e => set(key, e.target.value)}
                className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
            />
        </div>
    );

    return (
        <div className="space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {field('Max Drawdown %', 'max_drawdown_pct')}
                    {field('Current Drawdown %', 'current_drawdown_pct')}
                    {field('Avg Correlation', 'avg_correlation')}
                    {field('VaR 95% (%)', 'var_95_pct')}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs text-slate-500">Regime</label>
                        <select
                            value={form.regime}
                            onChange={e => set('regime', e.target.value)}
                            className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
                        >
                            {['BULL', 'NEUTRAL', 'BEAR'].map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                    </div>
                    {field('VIX Level (optional)', 'vix_level')}
                    {field('Portfolio Beta (optional)', 'beta')}
                </div>
                <button
                    onClick={run}
                    disabled={loading}
                    className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded transition-colors"
                >
                    {loading ? 'Computing…' : 'Compute Tail Risk'}
                </button>
            </div>

            {loading && <LoadingSpinner />}
            <ErrorBox msg={error} />

            {result && (
                <div className="space-y-4">
                    {/* Score gauge */}
                    <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 flex flex-col items-center gap-3">
                        <svg viewBox="0 0 200 110" className="w-48 h-24">
                            {/* Background arc */}
                            <path
                                d="M 20 100 A 80 80 0 0 1 180 100"
                                fill="none" stroke="#334155" strokeWidth="16" strokeLinecap="round"
                            />
                            {/* Score arc */}
                            <path
                                d="M 20 100 A 80 80 0 0 1 180 100"
                                fill="none"
                                stroke={gaugeColor}
                                strokeWidth="16"
                                strokeLinecap="round"
                                strokeDasharray={`${(score / 100) * 251.3} 251.3`}
                            />
                            <text x="100" y="95" textAnchor="middle" fontSize="28" fontWeight="bold" fill={gaugeColor} fontFamily="monospace">
                                {score.toFixed(0)}
                            </text>
                            <text x="100" y="110" textAnchor="middle" fontSize="10" fill="#94a3b8" fontFamily="sans-serif">
                                / 100
                            </text>
                        </svg>
                        <div className="flex items-center gap-3">
                            <span className="text-sm text-slate-400">Hedge Recommendation:</span>
                            <Badge level={result.hedge_recommendation} />
                        </div>
                    </div>

                    {/* Component breakdown */}
                    {result.components && (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <Card title="Drawdown Risk" value={result.components.drawdown_risk?.toFixed(1)} sub="/ 25 pts" />
                            <Card title="Correlation Risk" value={result.components.correlation_risk?.toFixed(1)} sub="/ 25 pts" />
                            <Card title="VaR Risk" value={result.components.var_risk?.toFixed(1)} sub="/ 25 pts" />
                            <Card title="Regime Risk" value={result.components.regime_risk?.toFixed(1)} sub="/ 25 pts" />
                        </div>
                    )}

                    {/* Specific actions */}
                    {result.specific_actions?.length > 0 && (
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                            <h3 className="text-sm font-semibold text-slate-300 mb-2">Recommended Actions</h3>
                            <ul className="space-y-2">
                                {result.specific_actions.map((a, i) => (
                                    <li key={i} className="flex gap-2 items-start">
                                        <input type="checkbox" className="mt-0.5 shrink-0 accent-sky-500" readOnly />
                                        <span className="text-sm text-slate-300">{a}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Reasoning */}
                    {result.reasoning?.length > 0 && (
                        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                            <h3 className="text-sm font-semibold text-slate-300 mb-2">Reasoning</h3>
                            <ul className="space-y-1">
                                {result.reasoning.map((r, i) => (
                                    <li key={i} className="text-sm text-slate-400 flex gap-2">
                                        <span className="text-sky-500 shrink-0">•</span>{r}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Main AdvancedRisk component ──────────────────────────────────────────────

export default function AdvancedRisk() {
    const [activeTab, setActiveTab] = useState('drawdown');

    const panels = {
        drawdown:    <DrawdownMonitor />,
        greeks:      <OptionsGreeks />,
        correlation: <CorrelationMonitor />,
        tailrisk:    <TailRiskScore />,
    };

    return (
        <div className="space-y-4">
            {/* Tab bar */}
            <div className="flex flex-wrap gap-1 bg-slate-800 border border-slate-700 rounded-lg p-1">
                {TABS.map(t => (
                    <button
                        key={t.id}
                        onClick={() => setActiveTab(t.id)}
                        className={`flex-1 min-w-[120px] px-3 py-2 rounded text-sm font-medium transition-colors ${
                            activeTab === t.id
                                ? 'bg-sky-600 text-white'
                                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                        }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Active panel */}
            {panels[activeTab]}
        </div>
    );
}
