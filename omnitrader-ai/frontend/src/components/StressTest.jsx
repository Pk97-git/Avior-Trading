import React, { useState, useCallback } from 'react';
import { ShieldAlert, RefreshCw, AlertTriangle, TrendingDown, Info, Loader2, Activity } from 'lucide-react';
import { stressTestApi } from '../api';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n, digits = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtCcy(n, symbol = '₹') {
    if (n == null) return '—';
    const abs = Math.abs(n);
    const sign = n < 0 ? '−' : '';
    if (abs >= 1_00_000) return `${sign}${symbol}${(abs / 1_00_000).toFixed(2)}L`;
    if (abs >= 1_000)    return `${sign}${symbol}${(abs / 1_000).toFixed(1)}K`;
    return `${sign}${symbol}${fmt(abs)}`;
}

// ─── Scenario Card ────────────────────────────────────────────────────────────

function ScenarioCard({ scenario, isWorst }) {
    const lossPct = Math.abs(scenario.portfolio_loss_pct);
    const isGreen  = lossPct < 10;
    const isAmber  = lossPct >= 10 && lossPct < 20;
    const isRed    = lossPct >= 20;

    const colorBorder = isRed ? 'border-red-500/40' : isAmber ? 'border-yellow-500/40' : 'border-green-500/20';
    const colorBg     = isRed ? 'bg-red-500/5'      : isAmber ? 'bg-yellow-500/5'      : 'bg-green-500/5';
    const colorText   = isRed ? 'text-red-400'       : isAmber ? 'text-yellow-400'       : 'text-green-400';

    return (
        <div className={`rounded-lg border p-4 ${colorBorder} ${colorBg} ${isWorst ? 'ring-1 ring-red-500/50' : ''}`}>
            {isWorst && (
                <span className="inline-block text-[10px] bg-red-500/20 text-red-400 rounded px-1.5 py-0.5 mb-2 font-semibold uppercase tracking-wide">
                    Worst Case
                </span>
            )}
            <p className="text-xs text-muted-foreground mb-1">{scenario.scenario_label}</p>
            <p className={`text-2xl font-bold ${colorText}`}>
                {fmtCcy(scenario.total_raw_loss)}
            </p>
            <p className={`text-sm font-medium ${colorText}`}>
                {scenario.portfolio_loss_pct >= 0 ? '+' : ''}{fmt(scenario.portfolio_loss_pct)}% of portfolio
            </p>
            {scenario.stops_saved !== 0 && (
                <p className="text-xs text-muted-foreground mt-1">
                    Stops save: <span className="text-green-400">{fmtCcy(Math.abs(scenario.stops_saved))}</span>
                </p>
            )}
        </div>
    );
}

// ─── Position Table ───────────────────────────────────────────────────────────

function PositionTable({ positions }) {
    if (!positions?.length) return null;
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm">
                <thead>
                    <tr className="text-xs text-muted-foreground uppercase border-b border-border">
                        <th className="text-left pb-2">Ticker</th>
                        <th className="text-right pb-2">Beta</th>
                        <th className="text-right pb-2">Current</th>
                        <th className="text-right pb-2">Simulated</th>
                        <th className="text-right pb-2">Shock %</th>
                        <th className="text-right pb-2">Raw Loss</th>
                        <th className="text-right pb-2">w/ Stop</th>
                        <th className="text-center pb-2">Stop?</th>
                    </tr>
                </thead>
                <tbody>
                    {positions.map((p) => (
                        <tr key={p.ticker} className="border-b border-border/40 hover:bg-muted/20">
                            <td className="py-1.5 font-semibold">{p.ticker}</td>
                            <td className={`py-1.5 text-right text-xs ${p.beta > 1.3 ? 'text-yellow-400' : 'text-muted-foreground'}`}>
                                {fmt(p.beta)}
                            </td>
                            <td className="py-1.5 text-right font-mono text-xs">{fmt(p.current_price)}</td>
                            <td className="py-1.5 text-right font-mono text-xs text-red-400">{fmt(p.simulated_price)}</td>
                            <td className="py-1.5 text-right text-xs text-red-400">{fmt(p.stock_shock_pct)}%</td>
                            <td className="py-1.5 text-right text-xs text-red-400">{fmtCcy(p.raw_loss)}</td>
                            <td className="py-1.5 text-right text-xs text-muted-foreground">{fmtCcy(p.protected_loss)}</td>
                            <td className="py-1.5 text-center">
                                {p.has_stop
                                    ? <span className="text-green-400 text-xs">✓</span>
                                    : <span className="text-red-400 text-xs">✗</span>}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ─── Concentration Bar ────────────────────────────────────────────────────────

function ConcentrationBars({ data }) {
    if (!data?.length) return null;
    return (
        <div className="space-y-1.5">
            {data.map((d) => (
                <div key={d.ticker} className="flex items-center gap-2 text-xs">
                    <span className="w-16 text-right font-medium text-muted-foreground">{d.ticker}</span>
                    <div className="flex-1 h-3 bg-muted rounded overflow-hidden">
                        <div
                            className={`h-full rounded transition-all ${d.weight_pct > 30 ? 'bg-yellow-500' : 'bg-primary'}`}
                            style={{ width: `${Math.min(d.weight_pct, 100)}%` }}
                        />
                    </div>
                    <span className="w-10 text-muted-foreground">{fmt(d.weight_pct, 1)}%</span>
                </div>
            ))}
        </div>
    );
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function Skeleton() {
    return (
        <div className="space-y-4 animate-pulse">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {[...Array(6)].map((_, i) => (
                    <div key={i} className="h-24 bg-muted rounded-lg" />
                ))}
            </div>
            <div className="h-48 bg-muted rounded-lg" />
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function StressTest({ onNavigate }) {
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [worstExpanded, setWorstExpanded] = useState(false);
    const [customShock, setCustomShock] = useState('');

    const runTest = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const body = {};
            if (customShock && !isNaN(parseFloat(customShock))) {
                body.custom_shock = parseFloat(customShock) / 100;
            }
            const res = await stressTestApi.run(body);
            if (res.data?.error) {
                setError(res.data.error);
            } else {
                setResult(res.data);
                setWorstExpanded(false);
            }
        } catch (e) {
            setError(e?.response?.data?.detail || 'Stress test failed. Make sure you have open positions.');
        } finally {
            setLoading(false);
        }
    }, [customShock]);

    const worstScenario = result?.scenarios
        ? result.scenarios.reduce((a, b) => a.total_raw_loss < b.total_raw_loss ? a : b)
        : null;

    return (
        <div className="space-y-6 max-w-screen-xl">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-2">
                    <ShieldAlert size={20} className="text-primary" />
                    <h2 className="text-lg font-bold text-foreground">Stress Test</h2>
                    <span className="text-xs text-muted-foreground">Portfolio crash simulation</span>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                        <label className="text-xs text-muted-foreground">Custom shock %:</label>
                        <input
                            type="number"
                            className="w-20 bg-muted/40 border border-border rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                            placeholder="e.g. -35"
                            value={customShock}
                            onChange={e => setCustomShock(e.target.value)}
                        />
                    </div>
                    <button
                        onClick={runTest}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                        {loading
                            ? <><Loader2 size={14} className="animate-spin" /> Running…</>
                            : <><RefreshCw size={14} /> Run Stress Test</>
                        }
                    </button>
                </div>
            </div>

            {loading && <Skeleton />}

            {!loading && error && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-center">
                    <AlertTriangle size={32} className="mx-auto text-red-400 mb-3 opacity-60" />
                    <p className="text-sm text-red-400">{error}</p>
                    <p className="text-xs text-muted-foreground mt-1">Make sure you have open positions in your portfolio, or try the Run button again.</p>
                </div>
            )}

            {!loading && !result && !error && (
                <div className="rounded-xl border border-border bg-card/50 p-10 text-center">
                    <ShieldAlert size={40} className="mx-auto text-muted-foreground mb-3 opacity-30" />
                    <p className="text-base font-medium text-muted-foreground">Run a stress test to see how your portfolio holds up in market crashes.</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">Loads your open positions automatically from the portfolio.</p>
                    <button
                        onClick={runTest}
                        className="mt-4 px-5 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-semibold hover:bg-primary/90 transition-colors"
                    >
                        Run Stress Test
                    </button>
                </div>
            )}

            {result && (
                <>
                    {/* Portfolio stats */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="rounded-lg border border-border bg-card p-4">
                            <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1"><Activity size={11} /> Portfolio Value</p>
                            <p className="text-xl font-bold">{fmtCcy(result.portfolio_value)}</p>
                            <p className="text-xs text-muted-foreground">{result.position_count} positions</p>
                        </div>
                        <div className="rounded-lg border border-border bg-card p-4">
                            <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1"><TrendingDown size={11} /> Worst Case Loss</p>
                            <p className="text-xl font-bold text-red-400">{fmtCcy(result.worst_case_loss)}</p>
                            <p className="text-xs text-muted-foreground">{fmt(result.worst_case_loss_pct)}% of portfolio</p>
                        </div>
                        <div className={`rounded-lg border p-4 ${result.avg_portfolio_beta > 1.3 ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border bg-card'}`}>
                            <p className="text-xs text-muted-foreground mb-1">Avg Portfolio Beta</p>
                            <p className={`text-xl font-bold ${result.avg_portfolio_beta > 1.3 ? 'text-yellow-400' : ''}`}>
                                {fmt(result.avg_portfolio_beta)}
                            </p>
                            <p className="text-xs text-muted-foreground">vs. market</p>
                        </div>
                        <div className={`rounded-lg border p-4 ${result.is_concentrated ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border bg-card'}`}>
                            <p className="text-xs text-muted-foreground mb-1">Concentration</p>
                            <p className={`text-xl font-bold ${result.is_concentrated ? 'text-yellow-400' : 'text-green-400'}`}>
                                {result.is_concentrated ? 'Concentrated' : 'Diversified'}
                            </p>
                            <p className="text-xs text-muted-foreground">Top: {result.concentration?.[0]?.weight_pct}% in {result.concentration?.[0]?.ticker}</p>
                        </div>
                    </div>

                    {/* Scenario cards */}
                    <div>
                        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                            <TrendingDown size={14} className="text-primary" />
                            Scenario Results
                        </h3>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                            {result.scenarios.map((s) => (
                                <ScenarioCard
                                    key={s.scenario_id}
                                    scenario={s}
                                    isWorst={s.scenario_id === worstScenario?.scenario_id}
                                />
                            ))}
                        </div>
                    </div>

                    {/* Worst scenario positions */}
                    {worstScenario && (
                        <div className="rounded-lg border border-border bg-card p-4">
                            <button
                                onClick={() => setWorstExpanded(e => !e)}
                                className="w-full flex items-center justify-between text-sm font-semibold text-left"
                            >
                                <span>Per-Position Breakdown — {worstScenario.scenario_label}</span>
                                <span className="text-xs text-muted-foreground">{worstExpanded ? '▲ Hide' : '▼ Show'}</span>
                            </button>
                            {worstExpanded && (
                                <div className="mt-4">
                                    <PositionTable positions={worstScenario.positions} />
                                </div>
                            )}
                        </div>
                    )}

                    {/* Concentration bars */}
                    {result.concentration?.length > 0 && (
                        <div className="rounded-lg border border-border bg-card p-4">
                            <h3 className="text-sm font-semibold mb-3">Portfolio Concentration</h3>
                            <ConcentrationBars data={result.concentration} />
                        </div>
                    )}

                    {/* Risk notes */}
                    {result.risk_notes?.length > 0 && (
                        <div className="space-y-2">
                            <h3 className="text-sm font-semibold flex items-center gap-2">
                                <AlertTriangle size={14} className="text-yellow-400" />
                                Risk Warnings
                            </h3>
                            {result.risk_notes.map((note, i) => (
                                <div key={i} className="flex items-start gap-2 p-2.5 rounded-lg text-xs bg-yellow-500/10 border border-yellow-500/20 text-yellow-400">
                                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                                    {note}
                                </div>
                            ))}
                        </div>
                    )}

                    {result.risk_notes?.length === 0 && (
                        <div className="flex items-center gap-2 p-3 rounded-lg text-xs bg-green-500/10 border border-green-500/20 text-green-400">
                            <Info size={13} />
                            No major risk warnings. Portfolio appears well-structured with stops in place.
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
