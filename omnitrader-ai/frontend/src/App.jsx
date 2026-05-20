import React, { useState } from 'react';
import {
    LayoutDashboard, Database, Activity, Settings, Globe, Zap,
    Award, Star, BarChart2, TrendingUp, FlaskConical, Briefcase,
    ShoppingCart, Calendar, Layers, ShieldAlert, BarChart, Newspaper, Users,
} from 'lucide-react';
import IngestionDashboard from './components/IngestionDashboard';
import StockUniverse from './components/StockUniverse';
import Dashboard from './components/Dashboard';
import MarketAnalysis from './components/MarketAnalysis';
import IntelligenceHub from './components/IntelligenceHub';
import Compounders from './components/Compounders';
import LiveJobsView from './components/LiveJobsView';
import Watchlist from './components/Watchlist';
import Portfolio from './components/Portfolio';
import Orders from './components/Orders';
import SignalPerformance from './components/SignalPerformance';
import SettingsPage from './components/Settings';
import SwingSetups from './components/SwingSetups';
import Backtest from './components/Backtest';
import EarningsCalendar from './components/EarningsCalendar';
import OptionsFlow from './components/OptionsFlow';
import SectorRotation from './components/SectorRotation';
import RiskDashboard from './components/RiskDashboard';
import DailyBriefing from './components/DailyBriefing';
import InsiderActivity from './components/InsiderActivity';
import AnalystRatings from './components/AnalystRatings';
import EconomicCalendar from './components/EconomicCalendar';
import Charts from './components/Charts';

const TABS = [
    // ── Core ──────────────────────────────────────────────────
    { id: 'briefing',     label: 'Daily Briefing',      icon: Newspaper },
    { id: 'dashboard',    label: 'Dashboard',           icon: LayoutDashboard },
    { id: 'hub',          label: 'Intelligence Hub',    icon: Zap },
    { id: 'swing',        label: 'Swing Setups',        icon: TrendingUp },
    // ── Positions ─────────────────────────────────────────────
    { id: 'watchlist',    label: 'Watchlist',           icon: Star },
    { id: 'portfolio',    label: 'Portfolio',           icon: Briefcase },
    { id: 'orders',       label: 'Orders',              icon: ShoppingCart },
    // ── Alpha ─────────────────────────────────────────────────
    { id: 'earnings',     label: 'Earnings Calendar',   icon: Calendar },
    { id: 'options',      label: 'Options Flow',        icon: Layers },
    { id: 'insiders',     label: 'Insider Activity',    icon: Users },
    { id: 'analysts',     label: 'Analyst Ratings',     icon: Star },
    { id: 'econCalendar', label: 'Economic Calendar',   icon: Calendar },
    { id: 'sectors',      label: 'Sector Rotation',     icon: BarChart },
    // ── Risk & Analytics ──────────────────────────────────────
    { id: 'risk',         label: 'Risk Dashboard',      icon: ShieldAlert },
    { id: 'performance',  label: 'Signal Performance',  icon: BarChart2 },
    { id: 'backtest',     label: 'Backtest',             icon: FlaskConical },
    // ── Research ──────────────────────────────────────────────
    { id: 'market',       label: 'Market Analysis',     icon: Activity },
    { id: 'compounders',  label: 'Compounders',         icon: Award },
    { id: 'charts',       label: 'Charts',              icon: BarChart2 },
    // ── Data ──────────────────────────────────────────────────
    { id: 'data',         label: 'Data Ingestion',      icon: Database },
    { id: 'jobs',         label: 'Active Jobs',         icon: Activity },
    { id: 'universe',     label: 'Stock Universe',      icon: Globe },
];

const TAB_LABELS = Object.fromEntries(TABS.map(t => [t.id, t.label]));

// Grouped sidebar sections for visual clarity
const NAV_GROUPS = [
    { label: 'Core',           ids: ['briefing', 'dashboard', 'hub', 'swing'] },
    { label: 'Positions',      ids: ['watchlist', 'portfolio', 'orders'] },
    { label: 'Alpha',          ids: ['earnings', 'options', 'insiders', 'analysts', 'econCalendar', 'sectors'] },
    { label: 'Risk & Analytics', ids: ['risk', 'performance', 'backtest'] },
    { label: 'Research',       ids: ['market', 'compounders', 'charts'] },
    { label: 'Data',           ids: ['data', 'jobs', 'universe'] },
];

function NavItem({ icon: Icon, label, active, onClick }) {
    return (
        <button
            onClick={onClick}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                }`}
        >
            <Icon size={16} />
            <span>{label}</span>
        </button>
    );
}

export default function App() {
    const [activeTab, setActiveTab] = useState('briefing');
    const [hubTicker, setHubTicker] = useState(null);

    const handleNavigate = (tab, extra = null) => {
        if (tab === 'hub' && extra) setHubTicker(extra);
        setActiveTab(tab);
    };

    const tabMap = Object.fromEntries(TABS.map(t => [t.id, t]));

    return (
        <div className="flex h-screen bg-background text-foreground font-sans">

            {/* ── Sidebar ── */}
            <aside className="w-52 border-r border-border bg-card/50 backdrop-blur-sm py-4 hidden md:flex flex-col shrink-0 overflow-y-auto">
                <div className="px-4 mb-4 flex items-center gap-2">
                    <Activity className="h-5 w-5 text-primary shrink-0" />
                    <h1 className="text-base font-bold tracking-tight">OmniTrader AI</h1>
                </div>

                <nav className="flex-1 px-2 space-y-4">
                    {NAV_GROUPS.map(group => (
                        <div key={group.label}>
                            <p className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                                {group.label}
                            </p>
                            <div className="space-y-0.5">
                                {group.ids.map(id => {
                                    const tab = tabMap[id];
                                    if (!tab) return null;
                                    return (
                                        <NavItem
                                            key={id}
                                            icon={tab.icon}
                                            label={tab.label}
                                            active={activeTab === id}
                                            onClick={() => handleNavigate(id)}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </nav>

                <div className="px-2 pt-3 border-t border-border mt-4">
                    <NavItem
                        icon={Settings}
                        label="Settings"
                        active={activeTab === 'settings'}
                        onClick={() => handleNavigate('settings')}
                    />
                </div>
            </aside>

            {/* ── Main ── */}
            <main className="flex-1 overflow-auto min-w-0">
                <header className="h-14 border-b border-border flex items-center px-6 bg-card/50 backdrop-blur-sm sticky top-0 z-10">
                    <h2 className="text-base font-semibold">
                        {TAB_LABELS[activeTab] || 'Settings'}
                    </h2>
                </header>

                <div className="p-6">
                    {activeTab === 'briefing'    && <DailyBriefing onNavigate={handleNavigate} />}
                    {activeTab === 'dashboard'   && <Dashboard onNavigate={handleNavigate} />}
                    {activeTab === 'hub'         && <IntelligenceHub key={hubTicker} initialTicker={hubTicker} />}
                    {activeTab === 'swing'       && <SwingSetups onNavigate={handleNavigate} />}
                    {activeTab === 'watchlist'   && <Watchlist onNavigate={handleNavigate} />}
                    {activeTab === 'portfolio'   && <Portfolio onNavigate={handleNavigate} />}
                    {activeTab === 'orders'      && <Orders onNavigate={handleNavigate} />}
                    {activeTab === 'earnings'    && <EarningsCalendar onNavigate={handleNavigate} />}
                    {activeTab === 'options'     && <OptionsFlow onNavigate={handleNavigate} />}
                    {activeTab === 'insiders'    && <InsiderActivity onNavigate={handleNavigate} />}
                    {activeTab === 'analysts'    && <AnalystRatings onNavigate={handleNavigate} />}
                    {activeTab === 'econCalendar' && <EconomicCalendar />}
                    {activeTab === 'sectors'     && <SectorRotation />}
                    {activeTab === 'risk'        && <RiskDashboard />}
                    {activeTab === 'performance' && <SignalPerformance />}
                    {activeTab === 'backtest'    && <Backtest />}
                    {activeTab === 'market'      && <MarketAnalysis />}
                    {activeTab === 'compounders' && <Compounders />}
                    {activeTab === 'charts'      && <Charts />}
                    {activeTab === 'data'        && <IngestionDashboard onNavigate={handleNavigate} />}
                    {activeTab === 'jobs'        && <LiveJobsView />}
                    {activeTab === 'universe'    && <StockUniverse onNavigate={handleNavigate} />}
                    {activeTab === 'settings'    && <SettingsPage />}
                </div>
            </main>
        </div>
    );
}
