import { useState } from 'react'
import { FileText, Sparkles } from 'lucide-react'

export default function ReportPage() {
  const [text, setText] = useState('')
  const [rank, setRank] = useState('')

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
      <div>
        <h1 className="section-title">生成填报报告</h1>
        <p className="section-subtitle">FREE-TEXT → STRUCTURED PROFILE → HTML REPORT</p>
      </div>

      <div className="brutal-card p-6 space-y-6">
        <div className="flex items-start gap-4">
          <Sparkles className="text-accent shrink-0" size={28} />
          <div>
            <h3 className="font-serif text-xl font-bold">自由描述你的需求</h3>
            <p className="text-sm text-muted mt-1">
              像和朋友聊天一样写下你的分数、位次、意向专业、城市、家庭考量，无需填写固定表单。
              Spiral 会自动解析并生成一份可下载的 HTML 志愿填报报告。
            </p>
          </div>
        </div>

        <form
          action="/api/reports/from-text"
          method="POST"
          target="_blank"
          className="space-y-5"
        >
          <div>
            <label className="block text-sm font-bold mb-2">志愿意向描述</label>
            <textarea
              name="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={6}
              className="brutal-input"
              placeholder="例如：我是湖北考生，物理类，全省排名25000名左右，想读计算机或电子信息，以后想留武汉或长三角就业，比较看重专业和学校层次..."
              required
            />
          </div>

          <div>
            <label className="block text-sm font-bold mb-2">全省位次</label>
            <input
              type="number"
              name="rank"
              value={rank}
              onChange={(e) => setRank(e.target.value)}
              className="brutal-input"
              placeholder="25000"
              required
            />
          </div>

          <p className="text-xs text-muted">
            提交后将在新标签页打开 Spiral HTML 报告。报告由后端基于真实湖北投档数据与 LLM 画像解析生成。
          </p>

          <button type="submit" className="brutal-btn w-full sm:w-auto gap-2">
            <FileText size={18} />
            生成 HTML 报告
          </button>
        </form>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="brutal-card p-5">
          <div className="font-serif font-bold text-lg mb-2">01 · 自由输入</div>
          <p className="text-sm text-muted">无需预设表单，用自然语言描述你的分数、位次、专业与城市偏好。</p>
        </div>
        <div className="brutal-card p-5">
          <div className="font-serif font-bold text-lg mb-2">02 · 智能解析</div>
          <p className="text-sm text-muted">LLM + 规则双保险解析画像，透明展示每一步推断依据。</p>
        </div>
        <div className="brutal-card p-5">
          <div className="font-serif font-bold text-lg mb-2">03 · 报告输出</div>
          <p className="text-sm text-muted">生成带图表、冲稳保分布、风险提示的 45 志愿 HTML 报告。</p>
        </div>
      </div>
    </div>
  )
}
