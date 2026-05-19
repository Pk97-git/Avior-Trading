import React, { useEffect, useState } from 'react';
import { ingestionApi } from '../api';
import { AlertCircle, CheckCircle, RefreshCw, Database, Clock, Activity, Loader2, Filter, Globe } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card" // Assuming shadcn or similar, but used raw div below to be safe
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

// --- DATA PREVIEW COMPONENT ---
const DataPreview = ({ type, data, loading, onRowClick }) => {
    if (loading) return <div className="p-8 text-center text-muted-foreground"><Loader2 className="animate-spin inline mr-2" /> Loading data...</div>;
    if (!data || data.length === 0) return <div className="p-8 text-center text-muted-foreground">No data available for this view.</div>;

    const headers = Object.keys(data[0]);

    return (
        <div className="rounded-md border border-border overflow-hidden">
            <div className="overflow-x-auto max-h-[500px]">
                <table className="w-full text-sm text-left">
                    <thead className="bg-muted/50 text-muted-foreground border-b border-border sticky top-0 backdrop-blur-sm">
                        <tr>
                            {headers.map(h => (
                                <th key={h} className="px-4 py-3 font-medium capitalize whitespace-nowrap">{h.replace(/_/g, ' ')}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {data.map((row, i) => (
                            <tr
                                key={i}
                                onClick={() => onRowClick && onRowClick(row)}
                                className={`transition-colors ${onRowClick ? 'cursor-pointer hover:bg-muted/50' : 'hover:bg-muted/30'}`}
                            >
                                {headers.map(h => (
                                    <td key={h} className="px-4 py-2 font-mono text-xs whitespace-nowrap">{
                                        row[h] === null ? '-' :
                                            typeof row[h] === 'number' && h.includes('time') ? row[h] :
                                                typeof row[h] === 'number' ? row[h].toLocaleString() :
                                                    String(row[h])
                                    }</td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// --- STATUS CARD COMPONENT ---
// --- HELPER ---
const getStatusIcon = (status) => {
    if (status === 'OK') return <CheckCircle className="text-green-500 h-5 w-5" />;
    if (status === 'STALE') return <Clock className="text-yellow-500 h-5 w-5" />;
    if (status === 'ERROR') return <AlertCircle className="text-red-500 h-5 w-5" />;
    return <AlertCircle className="text-muted-foreground h-5 w-5" />;
};

const StatusCard = ({ source, label, status, row_count, stock_count, us_count, india_count, staleness, onSelect, active }) => {
    const isStale = status === 'STALE';
    const isEmpty = status === 'EMPTY';

    // Logic: If we have stock counts, show that as primary. Else row count.
    const hasStocks = stock_count !== undefined && stock_count > 0;
    const mainCount = hasStocks ? stock_count : (row_count || 0);
    const mainLabel = hasStocks ? "Stocks" : "Records";

    return (
        <Card
            className={`cursor-pointer transition-all hover:shadow-md ${active ? 'ring-2 ring-primary border-primary' : ''} ${isEmpty ? 'opacity-70' : ''}`}
            onClick={() => onSelect(source)}
        >
            <CardContent className="p-5">
                <div className="flex justify-between items-start mb-2">
                    <h3 className="font-medium text-sm text-muted-foreground">{label}</h3>
                    {getStatusIcon(status)}
                </div>

                <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-2xl font-bold">{mainCount?.toLocaleString()}</span>
                    <span className="text-sm font-normal text-muted-foreground">{mainLabel}</span>
                </div>

                {hasStocks && (us_count > 0 || india_count > 0) && (
                    <div className="flex gap-2 text-[10px] font-medium uppercase tracking-wider mb-3">
                        {us_count > 0 && <span className="text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">US: {us_count}</span>}
                        {india_count > 0 && <span className="text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded">IN: {india_count}</span>}
                    </div>
                )}

                <div className="text-xs text-muted-foreground flex items-center gap-3 mt-auto pt-2 border-t border-border/50">
                    {hasStocks && <span title="Total Rows">{row_count?.toLocaleString()} rows</span>}
                    {staleness !== null && (
                        <span className={`flex items-center gap-1 ${isStale ? 'text-yellow-600' : ''}`}>
                            <Clock size={10} /> {staleness}h ago
                        </span>
                    )}
                </div>
            </CardContent>
        </Card>
    );
};


// --- DATA PROGRESS WIDGET ---
const DataProgressWidget = ({ progressData }) => {
    if (!progressData) return null;
    const { total_universe, ingested, current_to_date, not_yet_ingested, by_years, by_country } = progressData;
    const pct = (v) => total_universe > 0 ? ((v / total_universe) * 100).toFixed(1) : 0;

    const bars = [
        { label: '10+ yrs', value: by_years['10yr_plus'], color: 'bg-emerald-500' },
        { label: '5–10 yrs', value: by_years['5_to_10yr'], color: 'bg-blue-500' },
        { label: '3–5 yrs', value: by_years['3_to_5yr'], color: 'bg-indigo-400' },
        { label: '1–3 yrs', value: by_years['1_to_3yr'], color: 'bg-amber-400' },
        { label: '<1 yr', value: by_years.lt_1yr, color: 'bg-orange-400' },
        { label: 'Pending', value: not_yet_ingested, color: 'bg-muted' },
    ];

    return (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="p-4 border-b border-border bg-muted/20">
                <h3 className="font-semibold flex items-center gap-2">
                    <Database className="h-4 w-4 text-primary" />
                    Ingestion Progress
                </h3>
            </div>
            <div className="p-4 space-y-5">
                {/* Summary Numbers */}
                <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-muted/30 rounded-md p-2">
                        <div className="text-lg font-bold text-emerald-500">{current_to_date.toLocaleString()}</div>
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Current</div>
                    </div>
                    <div className="bg-muted/30 rounded-md p-2">
                        <div className="text-lg font-bold">{ingested.toLocaleString()}</div>
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Ingested</div>
                    </div>
                    <div className="bg-muted/30 rounded-md p-2">
                        <div className="text-lg font-bold text-muted-foreground">{not_yet_ingested.toLocaleString()}</div>
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wide">Pending</div>
                    </div>
                </div>

                {/* Stacked bar by history depth */}
                <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">Coverage by Years of History</div>
                    <div className="flex h-3 rounded-full overflow-hidden w-full gap-px">
                        {bars.map((b) => (
                            b.value > 0 && (
                                <div
                                    key={b.label}
                                    title={`${b.label}: ${b.value.toLocaleString()} (${pct(b.value)}%)`}
                                    className={`${b.color} transition-all duration-700`}
                                    style={{ width: `${pct(b.value)}%` }}
                                />
                            )
                        ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
                        {bars.filter(b => b.value > 0).map((b) => (
                            <div key={b.label} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                                <div className={`w-2 h-2 rounded-sm ${b.color}`} />
                                {b.label} ({b.value.toLocaleString()})
                            </div>
                        ))}
                    </div>
                </div>

                {/* Country breakdown */}
                <div className="flex gap-3">
                    <div className="flex items-center gap-1.5 text-xs">
                        <span className="font-mono bg-blue-500/10 text-blue-500 border border-blue-500/20 px-2 py-0.5 rounded-full">US {by_country.US.toLocaleString()}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs">
                        <span className="font-mono bg-orange-500/10 text-orange-500 border border-orange-500/20 px-2 py-0.5 rounded-full">IN {by_country.IN.toLocaleString()}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

import StockDetailView from './shared/StockDetailView';

// --- MAIN DASHBOARD ---
export default function IngestionDashboard({ onNavigate }) {
    const [statusData, setStatusData] = useState(null);
    const [healthData, setHealthData] = useState(null);
    const [progressData, setProgressData] = useState(null);
    const [selectedSource, setSelectedSource] = useState('prices');
    const [previewData, setPreviewData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [regionFilter, setRegionFilter] = useState('ALL'); // ALL, US, IN
    const [searchTerm, setSearchTerm] = useState('');

    // DETAIL VIEW STATE
    const [selectedTicker, setSelectedTicker] = useState(null);

    // Load Status & Health
    const loadStatus = async () => {
        try {
            setRefreshing(true);
            const [statusRes, healthRes, progressRes] = await Promise.all([
                ingestionApi.getStatus(),
                ingestionApi.getHealth(),
                ingestionApi.getDataProgress()
            ]);
            setStatusData(statusRes.data);
            setHealthData(healthRes.data);
            setProgressData(progressRes.data);
        } catch (err) {
            console.error("Failed to load status/health:", err);
        } finally {
            setRefreshing(false);
        }
    };

    // Auto-polling for live status
    useEffect(() => {
        let interval;
        const startPolling = async () => {
            // Initial load
            await loadStatus();
            // Poll every 10 seconds
            interval = setInterval(() => {
                loadStatus();
            }, 10000);
        };
        startPolling();
        return () => clearInterval(interval);
    }, []);

    // Load Preview Data when source or filter changes
    useEffect(() => {
        const loadPreview = async () => {
            setLoading(true);
            try {
                let res;
                // Backend expects country code 'US' or 'IN'
                const ctry = regionFilter === 'ALL' ? undefined : regionFilter;

                // For Institutional, market is 'US' or 'INDIA'
                const market = regionFilter === 'ALL' ? undefined : (regionFilter === 'IN' ? 'INDIA' : 'US');

                switch (selectedSource) {
                    case 'prices': res = await ingestionApi.getPrices(null, ctry); break;
                    case 'fundamentals': res = await ingestionApi.getFundamentals(null, ctry); break;
                    case 'macro_us': // Always US
                    case 'macro_global': res = await ingestionApi.getMacro(); break;
                    case 'institutional': res = await ingestionApi.getInstitutional(market); break;
                    case 'sentiment': res = await ingestionApi.getSentiment(null, ctry); break;
                    case 'promoter': res = await ingestionApi.getPromoter(null, ctry); break;
                    case 'universe': res = await ingestionApi.getTickers(); break;
                    default: res = { data: [] };
                }
                setPreviewData(res.data);
            } catch (err) {
                console.error("Failed preview:", err);
                setPreviewData([]);
            } finally {
                setLoading(false);
            }
        };

        if (selectedSource && selectedSource !== 'universe') {
            loadPreview();
        }
    }, [selectedSource, regionFilter]);

    if (!statusData) return <div className="p-10 flex justify-center"><Loader2 className="animate-spin" /></div>;

    return (
        <div className="space-y-8 animate-in fade-in duration-500 relative">
            {/* DETAIL VIEW OVERLAY */}
            {selectedTicker && (
                <StockDetailView
                    ticker={selectedTicker}
                    onClose={() => setSelectedTicker(null)}
                />
            )}

            {/* Header Stats */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {statusData.sources.map((s) => (
                    <StatusCard
                        key={s.source}
                        {...s}
                        active={selectedSource === s.source}
                        onSelect={(source) => {
                            if (source === 'universe' && onNavigate) {
                                onNavigate('universe');
                            } else {
                                setSelectedSource(source);
                            }
                        }}
                    />
                ))}
            </div>

            {/* Main Content Area */}
            {/* Main Content Area */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left: Controls & Details */}
                <div className="space-y-6">
                    <div className="rounded-lg border border-border bg-card p-4">
                        <h3 className="font-semibold mb-4 flex items-center gap-2">
                            <Database className="h-4 w-4 text-primary" />
                            Source Control
                        </h3>

                        <div className="space-y-4">
                            <div className="p-3 rounded bg-muted/30 text-sm">
                                <span className="font-medium">Selected:</span> <span className="uppercase text-primary">{selectedSource}</span>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Click 'Trigger Update' to manually queue a fetch job for this source.
                                </p>
                            </div>

                            <button
                                onClick={async () => {
                                    if (confirm(`Trigger fetch for ${selectedSource}?`)) {
                                        await ingestionApi.triggerFetch(selectedSource);
                                        alert('Job queued!');
                                    }
                                }}
                                className="w-full py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 font-medium transition-colors"
                            >
                                Trigger Update Now
                            </button>

                            <button
                                onClick={loadStatus}
                                disabled={refreshing}
                                className="w-full py-2 border border-border rounded-md hover:bg-accent flex items-center justify-center gap-2 transition-colors"
                            >
                                <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                                Refresh Status
                            </button>
                        </div>
                    </div>

                    {/* Data Progress Widget */}
                    <DataProgressWidget progressData={progressData} />
                </div>

                {/* Right: Data Table */}
                <div className="lg:col-span-2 space-y-4">
                    <div className="flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold flex items-center gap-2">
                                Latest Data Preview <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">v2.1</span>
                            </h3>
                            <div className="text-xs text-muted-foreground">
                                {loading ? 'Fetching...' : `Showing most recent records (Click row for details)`}
                            </div>
                        </div>

                        {/* Region Filter */}
                        <div className="flex items-center gap-1 bg-card border border-border rounded-lg p-1">
                            <span className="px-2 text-xs font-medium text-muted-foreground flex items-center gap-1">
                                <Filter size={12} /> Region
                            </span>
                            <button
                                onClick={() => setRegionFilter('ALL')}
                                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${regionFilter === 'ALL' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                            >
                                ALL
                            </button>
                            <button
                                onClick={() => setRegionFilter('US')}
                                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${regionFilter === 'US' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                            >
                                US
                            </button>
                            <button
                                onClick={() => setRegionFilter('IN')}
                                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${regionFilter === 'IN' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                            >
                                INDIA
                            </button>
                        </div>
                    </div>

                    {/* Search Input */}
                    <div className="relative">
                        <input
                            type="text"
                            placeholder="Search ticker or name..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="w-full px-4 py-2 border border-border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
                        />
                        {searchTerm && (
                            <button
                                onClick={() => setSearchTerm('')}
                                className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground"
                            >
                                ✕
                            </button>
                        )}
                    </div>

                    <DataPreview
                        type={selectedSource}
                        data={previewData.filter(row => {
                            if (!searchTerm) return true;
                            const term = searchTerm.toLowerCase();
                            // Safely search all values in the row regardless of schema
                            return Object.values(row).some(val =>
                                String(val || '').toLowerCase().includes(term)
                            );
                        })}
                        loading={loading}
                        onRowClick={(row) => {
                            if (!row.ticker) {
                                return; // E.g., Macro or Institutional data has no specific ticker
                            }
                            setSelectedTicker(row.ticker);
                        }}
                    />
                </div>
            </div>
        </div >
    );
}
