import axios from 'axios'

const API = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export const getHealth = () => API.get('/health')
export const getSystemInfo = () => API.get('/system/info')

export const createProfile = (data) => API.post('/profiles', data)
export const listProfiles = () => API.get('/profiles')
export const getProfile = (id) => API.get(`/profiles/${id}`)

export const generateRecommendation = (profileId) => API.post(`/recommendations/${profileId}`)

export const listSchools = (params) => API.get('/schools', { params })
export const getSchool = (id) => API.get(`/schools/${id}`)
export const searchMajors = (q, category) => API.get('/majors/search', { params: { q, category } })

export default API
