import { useState, useRef } from 'react'
import { Download, RotateCcw, Loader2 } from 'lucide-react'
import ProfileForm from '../components/ProfileForm'
import { generateReport } from '../api'

export default function RecommendPage() {
  const [loading, setLoading] = useState(false)
  const [reportHtml, setReportHtml] = useState(null)
  const [error, setError] = useState(null)
  const iframeRef = useRef(null)

  const handleSubmit = async ({ text, rank, province, subject_type }) => {
    setLoading(true)
    setError(null)
    setReportHtml(null)
    try {
      const html = await generateReport(text, rank, province, subject_type)
      setReportHtml(html)
    } catch (err) {
      console.error(err)
      setError(err.response?.data?.detail || '生成报告失败，请检查后端服务是否启动（端口 11678）。')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = () => {
    if (!reportHtml) return
    const blob = new Blob([reportHtml], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Spiral_志愿报告_${Date.now()}.html`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleReset = () => {
    setReportHtml(null)
    setError(null)
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
      <div>
        <h1 className="section-title">智能填报</h1>
        <p className="section-subtitle">填写画像 → 生成报告 → 预览下载</p>
      </div>

      {!reportHtml && <ProfileForm onSubmit={handleSubmit} loading={loading} />}

      {loading && (
        <div className="brutal-card p-8 text-center">
          <Loader2 className="animate-spin mx-auto mb-4 text-accent" size={32} />
          <p className="font-bold">正在解析画像并生成报告，请稍候…</p>
          <p className="text-sm text-muted mt-2">首次运行需要加载模型与数据，可能需要 10-30 秒。</p>
        </div>
      )}

      {error && (
        <div className="brutal-card p-4 border-l-[6px] border-l-warn bg-warn/5">
          <p className="text-sm font-bold text-warn">{error}</p>
        </div>
      )}

      {reportHtml && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="font-serif text-2xl font-bold">志愿报告预览</h2>
            <div className="flex gap-3">
              <button onClick={handleReset} className="brutal-btn-secondary gap-2">
                <RotateCcw size={18} />
                重新填报
              </button>
              <button onClick={handleDownload} className="brutal-btn gap-2">
                <Download size={18} />
                下载 HTML 报告
              </button>
            </div>
          </div>

          <div className="brutal-card p-2 bg-white">
            <iframe
              ref={iframeRef}
              title="志愿报告"
              srcDoc={reportHtml}
              className="w-full h-[800px] border-2 border-ink"
              sandbox="allow-scripts allow-same-origin"
            />
          </div>
        </div>
      )}
    </div>
  )
}
