import axios from 'axios'

const API = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Report generation needs longer timeout (backend LLM processing takes ~100s)
const REPORT_TIMEOUT = 180000

export const getHealth = () => API.get('/health')
export const getSystemInfo = () => API.get('/system/info')

export const createProfile = (data) => API.post('/profiles', data)
export const listProfiles = () => API.get('/profiles')
export const getProfile = (id) => API.get(`/profiles/${id}`)

export const generateRecommendation = (profileId) => API.post(`/recommendations/${profileId}`)

export const listSchools = (params) => API.get('/schools', { params })
export const getSchool = (id) => API.get(`/schools/${id}`)
export const searchMajors = (q, category) => API.get('/majors/search', { params: { q, category } })

export const generateReport = (text, rank, province, subjectType) =>
  API.post('/reports/from-text', { text, rank, province, subject_type: subjectType }, { responseType: 'text', timeout: REPORT_TIMEOUT }).then((res) => res.data)

export default API
