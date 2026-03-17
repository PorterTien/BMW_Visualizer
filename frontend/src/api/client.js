import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getCompanies = (params) => api.get('/companies', { params })
export const getCompany = (id) => api.get(`/companies/${id}`)
export const getCompaniesMap = () => api.get('/companies/map')
export const getCompaniesNetwork = () => api.get('/companies/network')
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

export const getNews = (params) => api.get('/news', { params })
export const searchNews = (company_name) => api.post('/news/search', { company_name })

export const getProceedings = (params) => api.get('/proceedings', { params })

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

export const getJob = (id) => api.get(`/jobs/${id}`)
export const listJobs = () => api.get('/jobs')

export const getSyncStatus = () => api.get('/sync/status')
export const triggerSync = () => api.post('/sync/naatbatt')
export const getSeedStatus = () => api.get('/seed/status')
export const triggerSeed = () => api.post('/seed')

export default api
