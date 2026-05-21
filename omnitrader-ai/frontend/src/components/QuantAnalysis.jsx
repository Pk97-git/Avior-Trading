import React, { useState } from 'react';
import { quantApi } from '../api';

// ── Utility helpers ────────────────────────────────────────────────────────────

function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function fmtPct(n, decimals = 1) {
    if (n == null) return '—';
    return `${Number(n).toFixed(decimals)}%`;
}

function Card({ children, className = '' }) {
    return (
        <div className={`bg-card border border-border rounded-lg p-4 ${className}`}>
            {children}
        </div>
    );
}

function SectionTitle({ children }) {
    return <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">{children}</h3>;
}

function Spinner() {
    return (
        <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
    );
}

function ErrorBox({ msg }) {
    return (
        <div className="bg-red-950/40 border border-red-800 rounded-lg p-4 text-red-300 text-sm">{msg}</div>
    );
}

function PlainEnglishBox({ lines }) {
    if (!lines || lines.length === 0) return null;
    return (
        <Card className="bg-sky-950/30 border-sky-800/50">
            <SectionTitle>Plain English Summary</SectionTitle>
            <ul className="space-y-1.5">
                {lines.map((l, i) => (
                    <li key={i} className="text-sm text-sky-200 flex gap-2">
                        <span className="text-sky-500 shrink-0">›</span>
                        <span>{l}</span>
                    </li>
                ))}
            </ul>
        </Card>
    );
}

// ── Tab: Monte Carlo ───────────────────────────────────────────────────────────

function MonteCarloTab() {
    const [form, setForm] = useState({
        ticker: 'RELIANCE.NS',
        entry_price: 2500,
        stop_loss: 2400,
        take_profit: 2700,
        position_value: 100000,
        days_horizon: 10,
        n_simulations: 10000,
    });
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = async () => {
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const res = await quantApi.monteCarlotrade({
                ticker:         form.ticker.trim().toUpperCase(),
                entry_price:    Number(form.entry_price),
                stop_loss:      Number(form.stop_loss),
                take_profit:    Number(form.take_profit),
                position_value: Number(form.position_value),
                days_horizon:   Number(form.days_horizon),
                n_simulations:  Number(form.n_simulations),
            });
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const field = (key, label, type = 'text', extra = {}) => (
        <div>
            <label className="block text-xs text-muted-foreground mb-1">{label}</label>
            <input
                type={type}
                value={form[key]}
                onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                className="w-full bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                {...extra}
            />
        </div>
    );

    const maxCount = result ? Math.max(...result.histogram.map(b => b.count)) : 1;

    return (
        <div className="space-y-4">
            {/* Form */}
            <Card>
                <SectionTitle>Trade Setup</SectionTitle>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    {field('ticker', 'Ticker')}
                    {field('entry_price', 'Entry Price (₹)', 'number')}
                    {field('stop_loss', 'Stop Loss (₹)', 'number')}
                    {field('take_profit', 'Take Profit (₹)', 'number')}
                    {field('position_value', 'Position Value (₹)', 'number')}
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Days Horizon: {form.days_horizon}</label>
                        <input
                            type="range" min={1} max={60} value={form.days_horizon}
                            onChange={e => setForm(f => ({ ...f, days_horizon: Number(e.target.value) }))}
                            className="w-full accent-primary"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Simulations</label>
                        <div className="flex gap-2 flex-wrap">
                            {[5000, 10000, 50000].map(v => (
                                <button
                                    key={v}
                                    onClick={() => setForm(f => ({ ...f, n_simulations: v }))}
                                    className={`px-2 py-1 text-xs rounded border transition-colors ${form.n_simulations === v ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}
                                >
                                    {v.toLocaleString()}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
                <button
                    onClick={run}
                    disabled={loading}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium disabled:opacity-50"
                >
                    {loading ? 'Running…' : `Run ${Number(form.n_simulations).toLocaleString()} Simulations`}
                </button>
            </Card>

            {loading && <Spinner />}
            {error && <ErrorBox msg={error} />}

            {result && (
                <>
                    {/* Big probabilities */}
                    <div className="grid grid-cols-2 gap-4">
                        <Card className="text-center">
                            <p className="text-4xl font-bold text-green-400">{fmtPct(result.prob_profit_pct, 0)}</p>
                            <p className="text-sm text-muted-foreground mt-1">Chance of Profit</p>
                        </Card>
                        <Card className="text-center">
                            <p className="text-4xl font-bold text-red-400">{fmtPct(100 - result.prob_profit_pct, 0)}</p>
                            <p className="text-sm text-muted-foreground mt-1">Chance of Loss</p>
                        </Card>
                    </div>

                    {/* Outcome breakdown */}
                    <Card>
                        <SectionTitle>Outcome Breakdown</SectionTitle>
                        <div className="grid grid-cols-3 gap-4 text-center">
                            <div>
                                <p className="text-2xl font-bold text-red-400">{fmtPct(result.prob_hit_stop_pct, 0)}</p>
                                <p className="text-xs text-muted-foreground mt-1">Stop Hit</p>
                            </div>
                            <div>
                                <p className="text-2xl font-bold text-green-400">{fmtPct(result.prob_hit_target_pct, 0)}</p>
                                <p className="text-xs text-muted-foreground mt-1">Target Hit</p>
                            </div>
                            <div>
                                <p className="text-2xl font-bold text-amber-400">{fmtPct(result.prob_timeout_pct, 0)}</p>
                                <p className="text-xs text-muted-foreground mt-1">Timeout</p>
                            </div>
                        </div>
                        <p className="text-xs text-muted-foreground mt-3 text-center">
                            Annual vol: {fmtPct(result.annual_vol_pct)} &nbsp;|&nbsp; Mean P&L: ₹{fmt(result.mean_pnl)} &nbsp;|&nbsp; Std Dev: ₹{fmt(result.std_pnl)}
                        </p>
                    </Card>

                    {/* Percentile table */}
                    <Card>
                        <SectionTitle>P&L Percentiles</SectionTitle>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border">
                                        {['Worst 5%', '10th', '25th', 'Median', '75th', '90th', 'Best 5%'].map(h => (
                                            <th key={h} className="px-2 py-1.5 text-xs text-muted-foreground font-medium text-right first:text-left">{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        {['p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95'].map((k, i) => {
                                            const v = result.percentiles[k];
                                            return (
                                                <td key={k} className={`px-2 py-2 text-right first:text-left font-mono text-xs ${v >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                    {v >= 0 ? '+' : ''}₹{fmt(v)}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </Card>

                    {/* Histogram */}
                    <Card>
                        <SectionTitle>P&L Distribution (20 bins)</SectionTitle>
                        <div className="flex items-end gap-0.5 h-32">
                            {result.histogram.map((bin, i) => {
                                const heightPct = (bin.count / maxCount) * 100;
                                const isLoss = bin.to <= 0;
                                return (
                                    <div
                                        key={i}
                                        title={`₹${fmt(bin.from)} – ₹${fmt(bin.to)}\nCount: ${bin.count}`}
                                        style={{ height: `${heightPct}%`, flex: 1 }}
                                        className={`rounded-t-sm transition-all ${isLoss ? 'bg-red-500/70 hover:bg-red-400' : 'bg-green-500/70 hover:bg-green-400'}`}
                                    />
                                );
                            })}
                        </div>
                        <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                            <span>₹{fmt(result.histogram[0]?.from)}</span>
                            <span>₹0</span>
                            <span>₹{fmt(result.histogram[result.histogram.length - 1]?.to)}</span>
                        </div>
                    </Card>

                    <PlainEnglishBox lines={result.plain_english} />
                </>
            )}
        </div>
    );
}

// ── Tab: VaR/CVaR ─────────────────────────────────────────────────────────────

function VaRTab() {
    const [form, setForm] = useState({
        ticker: 'RELIANCE.NS',
        portfolio_value: 1000000,
        method: 'historical',
        period: '1y',
    });
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = async () => {
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const res = await quantApi.varCvar({
                ticker:           form.ticker.trim().toUpperCase(),
                portfolio_value:  Number(form.portfolio_value),
                method:           form.method,
                period:           form.period,
                confidence_levels: [0.90, 0.95, 0.99],
            });
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const METHODS = [
        { value: 'historical',    label: 'Historical' },
        { value: 'parametric',    label: 'Parametric' },
        { value: 'cornish_fisher', label: 'Cornish-Fisher' },
    ];

    const PERIODS = ['6mo', '1y', '2y', '3y'];

    const CL_LABELS = { '90pct': '90%', '95pct': '95%', '99pct': '99%' };

    return (
        <div className="space-y-4">
            <Card>
                <SectionTitle>VaR / CVaR Setup</SectionTitle>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Ticker</label>
                        <input
                            value={form.ticker}
                            onChange={e => setForm(f => ({ ...f, ticker: e.target.value }))}
                            className="w-full bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Portfolio Value (₹)</label>
                        <input
                            type="number"
                            value={form.portfolio_value}
                            onChange={e => setForm(f => ({ ...f, portfolio_value: e.target.value }))}
                            className="w-full bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Method</label>
                        <select
                            value={form.method}
                            onChange={e => setForm(f => ({ ...f, method: e.target.value }))}
                            className="w-full bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        >
                            {METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Period</label>
                        <div className="flex gap-2 flex-wrap">
                            {PERIODS.map(p => (
                                <button
                                    key={p}
                                    onClick={() => setForm(f => ({ ...f, period: p }))}
                                    className={`px-2 py-1 text-xs rounded border transition-colors ${form.period === p ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
                <button
                    onClick={run}
                    disabled={loading}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium disabled:opacity-50"
                >
                    {loading ? 'Computing…' : 'Compute VaR / CVaR'}
                </button>
            </Card>

            {loading && <Spinner />}
            {error && <ErrorBox msg={error} />}

            {result && (
                <>
                    {/* Stats row */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {[
                            { label: 'Daily Vol', value: fmtPct(result.daily_vol_pct, 2) },
                            { label: 'Annual Vol', value: fmtPct(result.annual_vol_pct, 1) },
                            { label: 'Skewness', value: Number(result.skewness).toFixed(3) },
                            { label: 'Excess Kurtosis', value: Number(result.excess_kurtosis).toFixed(3) },
                        ].map(s => (
                            <Card key={s.label} className="text-center py-3">
                                <p className="text-xl font-bold">{s.value}</p>
                                <p className="text-xs text-muted-foreground mt-1">{s.label}</p>
                            </Card>
                        ))}
                    </div>

                    {/* Fat tails warning */}
                    {result.fat_tails && (
                        <div className="bg-amber-950/40 border border-amber-700 rounded-lg p-3 text-amber-300 text-sm flex gap-2 items-start">
                            <span className="text-amber-500 font-bold shrink-0">⚠</span>
                            <span>Fat tails detected (excess kurtosis {Number(result.excess_kurtosis).toFixed(2)} &gt; 1.0). Extreme losses occur more frequently than a normal distribution predicts. Rely on CVaR rather than VaR.</span>
                        </div>
                    )}

                    {/* VaR/CVaR table */}
                    <Card>
                        <SectionTitle>VaR &amp; CVaR at Multiple Confidence Levels</SectionTitle>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border text-xs text-muted-foreground">
                                        <th className="px-3 py-2 text-left">Confidence</th>
                                        <th className="px-3 py-2 text-right">VaR (%)</th>
                                        <th className="px-3 py-2 text-right">VaR (₹)</th>
                                        <th className="px-3 py-2 text-right">CVaR (%)</th>
                                        <th className="px-3 py-2 text-right">CVaR (₹)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(result.var_cvar).map(([key, r]) => (
                                        <tr key={key} className="border-b border-border/50 hover:bg-accent/30">
                                            <td className="px-3 py-2 font-medium">{CL_LABELS[key] || key}</td>
                                            <td className="px-3 py-2 text-right text-red-400 font-mono">{Number(r.var_return_pct).toFixed(3)}%</td>
                                            <td className="px-3 py-2 text-right text-red-400 font-mono">₹{fmt(r.var_currency)}</td>
                                            <td className="px-3 py-2 text-right text-orange-400 font-mono">{Number(r.cvar_return_pct).toFixed(3)}%</td>
                                            <td className="px-3 py-2 text-right text-orange-400 font-mono">₹{fmt(r.cvar_currency)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <p className="text-xs text-muted-foreground mt-3">
                            Method: <span className="font-medium text-foreground">{result.method}</span> &nbsp;|&nbsp;
                            {result.return_days} trading days of data
                        </p>
                    </Card>

                    <PlainEnglishBox lines={result.plain_english} />
                </>
            )}
        </div>
    );
}

// ── Tab: GARCH ────────────────────────────────────────────────────────────────

function GARCHTab() {
    const [ticker, setTicker] = useState('RELIANCE.NS');
    const [period, setPeriod]  = useState('2y');
    const [loading, setLoading] = useState(false);
    const [result, setResult]   = useState(null);
    const [error, setError]     = useState(null);

    const run = async () => {
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const res = await quantApi.garch(ticker.trim(), period);
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const REGIME_COLOR = {
        HIGH_VOLATILITY:   'text-red-400 bg-red-950/40 border-red-800',
        NORMAL_VOLATILITY: 'text-green-400 bg-green-950/40 border-green-800',
        LOW_VOLATILITY:    'text-amber-400 bg-amber-950/40 border-amber-800',
    };

    const maxVol = result ? Math.max(...result.forecasts_21d.map(f => f.vol_annual_pct)) : 1;
    const minVol = result ? Math.min(...result.forecasts_21d.map(f => f.vol_annual_pct)) : 0;

    return (
        <div className="space-y-4">
            <Card>
                <SectionTitle>GARCH(1,1) Volatility Forecast</SectionTitle>
                <div className="flex gap-3 flex-wrap items-end">
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Ticker</label>
                        <input
                            value={ticker}
                            onChange={e => setTicker(e.target.value)}
                            className="bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary w-40"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Period</label>
                        <div className="flex gap-2">
                            {['1y', '2y', '3y'].map(p => (
                                <button
                                    key={p}
                                    onClick={() => setPeriod(p)}
                                    className={`px-2 py-1.5 text-xs rounded border transition-colors ${period === p ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                    <button
                        onClick={run}
                        disabled={loading}
                        className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium disabled:opacity-50"
                    >
                        {loading ? 'Fitting…' : 'Forecast Volatility'}
                    </button>
                </div>
            </Card>

            {loading && <Spinner />}
            {error && <ErrorBox msg={error} />}

            {result && (
                <>
                    {/* Current vol + regime */}
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                        <Card className="text-center">
                            <p className="text-4xl font-bold">{fmtPct(result.current_vol_annual, 1)}</p>
                            <p className="text-xs text-muted-foreground mt-1">Current Annual Vol</p>
                        </Card>
                        <Card className="text-center">
                            <p className="text-4xl font-bold text-muted-foreground">{fmtPct(result.hist_vol_annual, 1)}</p>
                            <p className="text-xs text-muted-foreground mt-1">Historical Avg Vol</p>
                        </Card>
                        <Card className={`text-center border ${REGIME_COLOR[result.vol_regime] || ''}`}>
                            <p className="text-lg font-bold">{result.vol_regime.replace(/_/g, ' ')}</p>
                            <p className="text-xs mt-1 opacity-80">Volatility Regime</p>
                        </Card>
                    </div>

                    {/* Current vs historical vol bar comparison */}
                    <Card>
                        <SectionTitle>Current vs Historical Volatility</SectionTitle>
                        <div className="space-y-3">
                            {[
                                { label: 'Current Annual Vol', val: result.current_vol_annual, color: 'bg-primary' },
                                { label: 'Historical Annual Vol', val: result.hist_vol_annual, color: 'bg-muted-foreground/50' },
                                { label: 'Long-Run Vol (GARCH)', val: result.long_run_vol_annual, color: 'bg-amber-500/70' },
                            ].map(row => {
                                const maxV = Math.max(result.current_vol_annual, result.hist_vol_annual, result.long_run_vol_annual) || 1;
                                const w = (row.val / maxV) * 100;
                                return (
                                    <div key={row.label}>
                                        <div className="flex justify-between text-xs mb-1">
                                            <span className="text-muted-foreground">{row.label}</span>
                                            <span className="font-medium">{fmtPct(row.val, 1)}</span>
                                        </div>
                                        <div className="h-3 bg-muted rounded-full overflow-hidden">
                                            <div className={`h-full ${row.color} rounded-full transition-all`} style={{ width: `${w}%` }} />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </Card>

                    {/* 21-day forecast chart using CSS bars */}
                    <Card>
                        <SectionTitle>21-Day Volatility Forecast</SectionTitle>
                        <div className="flex items-end gap-1 h-28 mt-2">
                            {result.forecasts_21d.map(f => {
                                const range = maxVol - minVol || 1;
                                const heightPct = ((f.vol_annual_pct - minVol) / range) * 80 + 20;
                                const isHigh = f.vol_annual_pct > result.hist_vol_annual;
                                return (
                                    <div key={f.day} className="flex flex-col items-center flex-1">
                                        <div
                                            title={`Day ${f.day}: ${f.vol_annual_pct}% annual vol`}
                                            style={{ height: `${heightPct}%` }}
                                            className={`w-full rounded-t transition-all ${isHigh ? 'bg-red-500/60 hover:bg-red-400' : 'bg-blue-500/60 hover:bg-blue-400'}`}
                                        />
                                        {f.day % 5 === 0 && (
                                            <span className="text-[9px] text-muted-foreground mt-1">D{f.day}</span>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                        <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                            <span>Day 1</span>
                            <span>Day 21</span>
                        </div>
                    </Card>

                    {/* GARCH parameters */}
                    <Card>
                        <SectionTitle>Model Parameters</SectionTitle>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {[
                                { label: 'α (Alpha)', value: result.parameters.alpha },
                                { label: 'β (Beta)', value: result.parameters.beta },
                                { label: 'Persistence (α+β)', value: result.persistence },
                                { label: 'Half-Life (days)', value: result.half_life_days ?? '∞' },
                            ].map(p => (
                                <div key={p.label} className="text-center">
                                    <p className="text-xl font-mono font-bold">{p.value}</p>
                                    <p className="text-xs text-muted-foreground mt-1">{p.label}</p>
                                </div>
                            ))}
                        </div>
                    </Card>

                    <PlainEnglishBox lines={result.plain_english} />
                </>
            )}
        </div>
    );
}

// ── Tab: Regime ───────────────────────────────────────────────────────────────

function RegimeTab() {
    const [ticker, setTicker] = useState('RELIANCE.NS');
    const [period, setPeriod]  = useState('2y');
    const [loading, setLoading] = useState(false);
    const [result, setResult]   = useState(null);
    const [error, setError]     = useState(null);

    const run = async () => {
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const res = await quantApi.regime(ticker.trim(), period);
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || e.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    const REGIME_STYLES = {
        BULL:    { bg: 'bg-green-950/50 border-green-700', text: 'text-green-400', dot: 'bg-green-500' },
        NEUTRAL: { bg: 'bg-amber-950/50 border-amber-700', text: 'text-amber-400', dot: 'bg-amber-500' },
        BEAR:    { bg: 'bg-red-950/50 border-red-700',     text: 'text-red-400',   dot: 'bg-red-500' },
    };

    return (
        <div className="space-y-4">
            <Card>
                <SectionTitle>HMM Regime Detection</SectionTitle>
                <div className="flex gap-3 flex-wrap items-end">
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Ticker</label>
                        <input
                            value={ticker}
                            onChange={e => setTicker(e.target.value)}
                            className="bg-background border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary w-40"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-muted-foreground mb-1">Period</label>
                        <div className="flex gap-2">
                            {['1y', '2y', '3y'].map(p => (
                                <button
                                    key={p}
                                    onClick={() => setPeriod(p)}
                                    className={`px-2 py-1.5 text-xs rounded border transition-colors ${period === p ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                    <button
                        onClick={run}
                        disabled={loading}
                        className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium disabled:opacity-50"
                    >
                        {loading ? 'Detecting…' : 'Detect Regime'}
                    </button>
                </div>
            </Card>

            {loading && <Spinner />}
            {error && <ErrorBox msg={error} />}

            {result && (() => {
                const cur = result.current_regime;
                const styles = REGIME_STYLES[cur] || REGIME_STYLES.NEUTRAL;
                const probs  = result.regime_probabilities;
                const stats  = result.state_statistics;
                const maxProb = Math.max(...Object.values(probs));

                return (
                    <>
                        {/* Current regime badge */}
                        <Card className={`border ${styles.bg} text-center py-6`}>
                            <p className={`text-5xl font-bold ${styles.text}`}>{cur}</p>
                            <p className="text-sm text-muted-foreground mt-2">Current Market Regime</p>
                            <p className="text-xs text-muted-foreground mt-1">{result.ticker} · {result.n_observations} observations</p>
                        </Card>

                        {/* Probability bars */}
                        <Card>
                            <SectionTitle>Regime Probabilities</SectionTitle>
                            <div className="space-y-3">
                                {['BULL', 'NEUTRAL', 'BEAR'].map(label => {
                                    const prob = probs[label] ?? 0;
                                    const s = REGIME_STYLES[label];
                                    return (
                                        <div key={label}>
                                            <div className="flex justify-between text-sm mb-1">
                                                <span className={`font-medium ${s.text}`}>{label}</span>
                                                <span className="font-mono">{fmtPct(prob, 1)}</span>
                                            </div>
                                            <div className="h-3 bg-muted rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full ${s.dot} rounded-full transition-all`}
                                                    style={{ width: `${prob}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </Card>

                        {/* 30-day regime history dots */}
                        <Card>
                            <SectionTitle>30-Day Regime History</SectionTitle>
                            <div className="flex flex-wrap gap-1">
                                {result.recent_regimes_30d.map((regime, i) => {
                                    const s = REGIME_STYLES[regime] || REGIME_STYLES.NEUTRAL;
                                    return (
                                        <div
                                            key={i}
                                            title={`Day -${result.recent_regimes_30d.length - i}: ${regime}`}
                                            className={`w-5 h-5 rounded-full ${s.dot} opacity-80 hover:opacity-100 transition-opacity`}
                                        />
                                    );
                                })}
                            </div>
                            <div className="flex gap-4 mt-3">
                                {['BULL', 'NEUTRAL', 'BEAR'].map(l => (
                                    <div key={l} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                        <div className={`w-3 h-3 rounded-full ${REGIME_STYLES[l].dot}`} />
                                        {l}
                                    </div>
                                ))}
                            </div>
                        </Card>

                        {/* State statistics table */}
                        <Card>
                            <SectionTitle>Regime Statistics</SectionTitle>
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-border text-xs text-muted-foreground">
                                            <th className="px-3 py-2 text-left">Regime</th>
                                            <th className="px-3 py-2 text-right">Mean Daily Return</th>
                                            <th className="px-3 py-2 text-right">Daily Vol</th>
                                            <th className="px-3 py-2 text-right">Days in State</th>
                                            <th className="px-3 py-2 text-right">% of Time</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {['BULL', 'NEUTRAL', 'BEAR'].map(label => {
                                            const s = stats[label];
                                            if (!s) return null;
                                            const st = REGIME_STYLES[label];
                                            return (
                                                <tr key={label} className="border-b border-border/50 hover:bg-accent/30">
                                                    <td className={`px-3 py-2 font-medium ${st.text}`}>{label}</td>
                                                    <td className={`px-3 py-2 text-right font-mono ${s.mean_daily_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                        {s.mean_daily_return_pct >= 0 ? '+' : ''}{fmtPct(s.mean_daily_return_pct, 3)}
                                                    </td>
                                                    <td className="px-3 py-2 text-right font-mono">{fmtPct(s.daily_vol_pct, 3)}</td>
                                                    <td className="px-3 py-2 text-right">{s.days_in_state}</td>
                                                    <td className="px-3 py-2 text-right">{fmtPct(s.pct_of_time, 1)}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </Card>

                        <PlainEnglishBox lines={result.plain_english} />
                    </>
                );
            })()}
        </div>
    );
}

// ── Main exported component ────────────────────────────────────────────────────

const TABS = [
    { id: 'monte-carlo', label: 'Monte Carlo' },
    { id: 'var',         label: 'VaR / CVaR' },
    { id: 'garch',       label: 'GARCH' },
    { id: 'regime',      label: 'Regime' },
];

export default function QuantAnalysis() {
    const [activeTab, setActiveTab] = useState('monte-carlo');

    return (
        <div className="space-y-4">
            {/* Tab bar */}
            <div className="flex gap-1 bg-muted/50 rounded-lg p-1 w-fit">
                {TABS.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                            activeTab === tab.id
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            {activeTab === 'monte-carlo' && <MonteCarloTab />}
            {activeTab === 'var'         && <VaRTab />}
            {activeTab === 'garch'       && <GARCHTab />}
            {activeTab === 'regime'      && <RegimeTab />}
        </div>
    );
}
