import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// In-session cache for large list endpoints — keyed by URL string.
// Stores the promise itself so concurrent callers share one in-flight request.
const _cache = new Map()
function cached(key, fetcher) {
  if (!_cache.has(key)) _cache.set(key, fetcher())
  return _cache.get(key)
}
export function bustCache(key) { _cache.delete(key) }

// Auth token — set on Supabase session changes
let _authToken = null
export function setAuthToken(token) { _authToken = token }

// Watchlist API instance that attaches the auth token on every request
const watchlistApi = axios.create({ baseURL: '/api' })
watchlistApi.interceptors.request.use((config) => {
  if (_authToken) config.headers['Authorization'] = `Bearer ${_authToken}`
  return config
})

// Companies
export const getCompanies = (params) => {
  // Only cache the full 2000-record list used by the table and sidebar.
  if (params?.limit === 0) return cached('companies:all', () => api.get('/companies', { params }))
  return api.get('/companies', { params })
}
export const getCompany = (id) => api.get(`/companies/${id}`)
export const getCompanyDetail = (id) =>
  cached(`company:${id}:detail`, () => api.get(`/companies/${id}/detail`))
export const refreshCompanyDetail = (id) => {
  bustCache(`company:${id}:detail`)
  return api.get(`/companies/${id}/detail`)
}
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
export const updateCompany = (id, updates, mark_as_manual = true) => {
  bustCache(`company:${id}:detail`)
  return api.put(`/companies/${id}`, { updates, mark_as_manual })
}

// Partnerships
export const getPartnerships = (params) => api.get('/partnerships', { params })
export const getPartnership = (id) => api.get(`/partnerships/${id}`)
export const createPartnership = (data) => api.post('/partnerships', data)
export const getPartnershipGraph = () => cached('partnerships:graph', () => api.get('/partnerships/graph'))
export const enrichPartnershipNetwork = () => {
  bustCache('partnerships:graph')
  return api.post('/partnerships/enrich')
}
export const enrichPartnershipEmployees = () => {
  bustCache('partnerships:graph')
  return api.post('/partnerships/enrich-employees')
}

// Facilities & Metrics
export const getCompanyFacilities = (id) => api.get(`/companies/${id}/facilities`)
export const getCompanyMetrics = (id) => api.get(`/companies/${id}/metrics`)

// News
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

// Watchlist — uses watchlistApi so the Bearer token is included
export const getWatchlist = (listId) =>
  watchlistApi.get('/watchlist', listId != null ? { params: { list_id: listId } } : undefined)
export const addToWatchlist = (companyId, listId) =>
  watchlistApi.post(`/watchlist/${companyId}`, listId != null ? { list_id: listId } : {})
export const removeFromWatchlist = (companyId, listId) =>
  watchlistApi.delete(`/watchlist/${companyId}`, listId != null ? { params: { list_id: listId } } : undefined)
export const getWatchlistDigest = () => watchlistApi.get('/watchlist/digest/latest')
export const triggerWatchlistDigest = () => watchlistApi.post('/watchlist/digest/run')
export const triggerCompanyDigest = (companyId) => watchlistApi.post(`/watchlist/digest/run/${companyId}`)

// Watchlist lists
export const getWatchlistLists = () => watchlistApi.get('/watchlist/lists')
export const createWatchlistList = (name) => watchlistApi.post('/watchlist/lists', { name })
export const renameWatchlistList = (listId, name) => watchlistApi.patch(`/watchlist/lists/${listId}`, { name })
export const deleteWatchlistList = (listId) => watchlistApi.delete(`/watchlist/lists/${listId}`)

// Sector Research
export const getSectorCategories = () => api.get('/sector-research/categories')
export const runSectorResearch = (category) => api.post('/sector-research/run', { category })
export const getSectorJob = (jobId) => api.get(`/sector-research/jobs/${jobId}`)
export const verifySectorUrls = (urls) => api.post('/sector-research/verify-urls', { urls })
export const approveSectorResearch = (companies, news) =>
  api.post('/sector-research/approve', { companies, news })
export const chatWithSector = (message, category, companies, news) =>
  api.post('/sector-research/chat', { message, category, companies, news })

// Sync/Seed
export const getSyncStatus = () => api.get('/sync/status')
export const triggerSync = () => api.post('/sync/naatbatt')
export const getSeedStatus = () => api.get('/seed/status')
export const triggerSeed = () => api.post('/seed')

export default api
