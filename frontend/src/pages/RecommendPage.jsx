import { useState } from 'react'
import ProfileForm from '../components/ProfileForm'
import RecommendationTable from '../components/RecommendationTable'
import RecommendationCharts from '../components/RecommendationCharts'
import { createProfile, generateRecommendation } from '../api'

export default function RecommendPage() {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleSubmit = async (formData) => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const profileRes = await createProfile(formData)
      const recRes = await generateRecommendation(profileRes.data.id)
      setResult(recRes.data)
    } catch (err) {
      console.error(err)
      setError(err.response?.data?.detail || '生成方案失败，请检查后端服务是否启动（端口 11678）。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
      <div>
        <h1 className="section-title">智能填报</h1>
        <p className="section-subtitle">INTELLIGENT RECOMMENDATION</p>
      </div>

      <ProfileForm onSubmit={handleSubmit} loading={loading} />

      {error && (
        <div className="brutal-card p-4 border-l-[6px] border-l-warn bg-warn/5">
          <p className="text-sm font-bold text-warn">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-2xl font-bold">推荐志愿表</h2>
            <div className="font-mono text-sm text-muted">
              考生：{result.profile.name || '未命名'} · {result.profile.subject_type} · {result.profile.score} 分 · 位次 {result.profile.rank}
            </div>
          </div>
          <RecommendationCharts data={result} />
          <RecommendationTable data={result} />
        </div>
      )}
    </div>
  )
}
