import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// Auth token — set by App.jsx when session changes
let _authToken = null
export function setAuthToken(token) {
  _authToken = token
}

// Watchlist axios instance — always sends auth header
const watchlistApi = axios.create({ baseURL: '/api' })
watchlistApi.interceptors.request.use((config) => {
  if (_authToken) config.headers['Authorization'] = `Bearer ${_authToken}`
  return config
})

// In-session cache for large list endpoints — keyed by URL string.
// Stores the promise itself so concurrent callers share one in-flight request.
const _cache = new Map()
function cached(key, fetcher) {
  if (!_cache.has(key)) _cache.set(key, fetcher())
  return _cache.get(key)
}
export function bustCache(key) { _cache.delete(key) }

// Companies
export const getCompanies = (params) => {
  // Only cache the full 2000-record list used by the table and sidebar.
  if (params?.limit === 2000) return cached('companies:2000', () => api.get('/companies', { params }))
  return api.get('/companies', { params })
}
export const getCompany = (id) => api.get(`/companies/${id}`)
export const getCompanyDetail = (id) => api.get(`/companies/${id}/detail`)
export const getCompaniesMap = () => cached('companies:map', () => api.get('/companies/map'))
export const getCompaniesNetwork = () => cached('companies:network', () => api.get('/companies/network'))
export const researchCompany = (company_name) =>
  api.post('/companies/research', { company_name })
export const chatWithCompany = (company_id, message) =>
  api.post(`/companies/${company_id}/chat`, { message })
export const customSearch = (query) =>
  api.post('/companies/search/custom', { query })
export const discoverCompanies = (segment, count = 10, custom_query = '') =>
  api.post('/companies/discover', { segment, count, custom_query })
export const bulkResearch = (company_names) =>
  api.post('/companies/bulk-research', { company_names })
export const updateCompany = (id, updates, mark_as_manual = true) =>
  api.put(`/companies/${id}`, { updates, mark_as_manual })

// Partnerships
export const getPartnerships = (params) => api.get('/partnerships', { params })
export const getPartnership = (id) => api.get(`/partnerships/${id}`)
export const createPartnership = (data) => api.post('/partnerships', data)
export const getPartnershipGraph = () => cached('partnerships:graph', () => api.get('/partnerships/graph'))
export const enrichPartnershipNetwork = () => {
  // A successful enrichment mutates node/link types; invalidate the cache so
  // the next Network-tab open fetches fresh classifications.
  bustCache('partnerships:graph')
  return api.post('/partnerships/enrich')
}

// Facilities & Metrics
export const getCompanyFacilities = (id) => api.get(`/companies/${id}/facilities`)
export const getCompanyMetrics = (id) => api.get(`/companies/${id}/metrics`)

// News
export const getNews = (params) => api.get('/news', { params })
export const searchNews = (company_name) => api.post('/news/search', { company_name })
export const getArticleThumbnail = (url) => api.get('/news/thumbnail', { params: { url } })

// Uploads
export const uploadCSV = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload/csv', form)
}
export const uploadDocument = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload/document', form)
}
export const uploadPartnerships = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload/partnerships', form)
}

// Jobs
export const getJob = (id) => api.get(`/jobs/${id}`)
export const listJobs = () => api.get('/jobs')

// Watchlist (requires auth)
export const getWatchlist = () => watchlistApi.get('/watchlist')
export const addToWatchlist = (companyId) => watchlistApi.post(`/watchlist/${companyId}`)
export const removeFromWatchlist = (companyId) => watchlistApi.delete(`/watchlist/${companyId}`)
export const getWatchlistDigest = () => watchlistApi.get('/watchlist/digest/latest')
export const triggerWatchlistDigest = () => watchlistApi.post('/watchlist/digest/run')
export const triggerCompanyDigest = (companyId) => watchlistApi.post(`/watchlist/digest/run/${companyId}`)

// Sync/Seed
export const getSyncStatus = () => api.get('/sync/status')
export const triggerSync = () => api.post('/sync/naatbatt')
export const getSeedStatus = () => api.get('/seed/status')
export const triggerSeed = () => api.post('/seed')

export default api
