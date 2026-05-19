import axios from 'axios';

const api = axios.create({
    baseURL: '/api/v1',
    headers: { 'Content-Type': 'application/json' },
});

export const ingestionApi = {
    getStatus: () => api.get('/ingestion/status'),
    getPrices: (ticker, country, limit = 50) => api.get('/ingestion/prices', { params: { ticker: ticker?.toUpperCase(), country, limit } }),
    getFundamentals: (ticker, country) => api.get('/ingestion/fundamentals', { params: { ticker: ticker?.toUpperCase(), country } }),
    getMacro: (indicator) => api.get('/ingestion/macro', { params: { indicator } }),
    getInstitutional: (market, type) => api.get('/ingestion/institutional', { params: { market, entity_type: type } }),
    getSentiment: (ticker, country) => api.get('/ingestion/sentiment', { params: { ticker: ticker?.toUpperCase(), country } }),
    getPromoter: (ticker, country) => api.get('/ingestion/promoter', { params: { ticker: ticker?.toUpperCase(), country } }),
    getTickers: (page = 1, limit = 50, search = null, filters = {}) =>
        api.get('/ingestion/tickers', { params: { page, limit, search, ...filters } }),
    getSectorBreakdown: () => api.get('/ingestion/sector-breakdown'),
    triggerFetch: (source) => api.post(`/ingestion/trigger/${source}`),
    triggerNow: (flow) => api.post(`/ingestion/trigger-now/${flow}`),
    getHealth: () => api.get('/ingestion/health'),
    getDataProgress: () => api.get('/ingestion/data-progress'),
    getLiveJobs: () => api.get('/ingestion/active-jobs'),
};

export const agentsApi = {
    // Per-ticker analysis
    getAnalysis: (ticker) => api.get(`/agents/analysis/${ticker}`),
    triggerAnalysis: (ticker) => api.post(`/agents/analyze/${ticker}`),

    // Dashboard & signals
    getDashboard: () => api.get('/agents/dashboard'),
    getSignals: (params) => api.get('/agents/signals', { params }),
    getMarketAnalysis: () => api.get('/agents/market-analysis'),
    getCompounders: (params) => api.get('/agents/compounders', { params }),

    // Alert management
    markAlertsRead: (ids = []) => api.post('/agents/alerts/mark-read', ids),
};

export default api;
