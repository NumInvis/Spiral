import { useState } from 'react'
import { Loader2 } from 'lucide-react'

const PROVINCES = [
  '湖北', '北京', '天津', '上海', '重庆',
  '河北', '山西', '辽宁', '吉林', '黑龙江',
  '江苏', '浙江', '安徽', '福建', '江西', '山东',
  '河南', '湖南', '广东', '海南',
  '四川', '贵州', '云南', '陕西', '甘肃', '青海',
  '内蒙古', '广西', '西藏', '宁夏', '新疆',
]

export default function ProfileForm({ onSubmit, loading }) {
  const [form, setForm] = useState({
    province: '湖北',
    rank: '',
    requirements: '',
  })

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const rank = parseInt(form.rank, 10)
    if (!rank || rank <= 0) return

    const text = `我是${form.province}考生，位次${rank}。${form.requirements}`
    onSubmit({
      province: form.province,
      rank,
      text,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="brutal-card-accent p-6 md:p-8">
      <div className="space-y-6">
        <div className="grid md:grid-cols-2 gap-6">
          <div>
            <label className="block font-bold text-sm mb-2">省份</label>
            <select
              name="province"
              value={form.province}
              onChange={handleChange}
              className="brutal-select w-full"
            >
              {PROVINCES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block font-bold text-sm mb-2">
              全省位次 <span className="text-burgundy">*</span>
            </label>
            <input
              name="rank"
              type="number"
              min="1"
              required
              value={form.rank}
              onChange={handleChange}
              placeholder="例如 25000"
              className="brutal-input"
            />
          </div>
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">
            填报要求 <span className="text-burgundy">*</span>
          </label>
          <textarea
            name="requirements"
            value={form.requirements}
            onChange={handleChange}
            rows={6}
            required
            className="brutal-input"
            placeholder="自由描述：科类、意向专业、意向城市、学校层次偏好、地域限制、是否接受特殊类型招生等。例如：物理类，想学计算机或电子信息，希望留在武汉或长三角，不想读预科/定向/采矿/护理。"
          />
          <p className="text-[11px] text-muted mt-2">
            LLM 会自动从这段描述中解析你的科类、专业意向、城市偏好等。
          </p>
        </div>
      </div>

      <div className="mt-8 flex justify-end">
        <button
          type="submit"
          disabled={loading}
          className="brutal-btn min-w-[160px] disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? <Loader2 className="animate-spin mr-2" size={18} /> : null}
          {loading ? '生成中…' : '生成志愿方案'}
        </button>
      </div>
    </form>
  )
}
