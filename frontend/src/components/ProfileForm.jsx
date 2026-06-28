import { useState } from 'react'
import { ChevronDown, Loader2 } from 'lucide-react'

const STRATEGIES = [
  { value: 'balanced', label: '综合平衡', desc: '兼顾学校、专业与城市' },
  { value: 'school', label: '院校优先', desc: '优先学校层次与牌子' },
  { value: 'major', label: '专业优先', desc: '优先专业实力与兴趣' },
  { value: 'city', label: '城市优先', desc: '优先地域与实习机会' },
  { value: 'employment', label: '就业优先', desc: '优先就业率和薪资' },
  { value: 'academic', label: '升学优先', desc: '优先保研率与学科评估' },
]

export default function ProfileForm({ onSubmit, loading }) {
  const [form, setForm] = useState({
    name: '',
    province: '湖北',
    subject_type: '物理',
    score: '',
    rank: '',
    preferred_major: '',
    preferred_city: '武汉',
    strategy: 'balanced',
    accept_adjustment: true,
  })

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setForm((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit({
      ...form,
      score: parseInt(form.score, 10),
      rank: parseInt(form.rank, 10),
    })
  }

  return (
    <form onSubmit={handleSubmit} className="brutal-card-accent p-6 md:p-8">
      <div className="grid md:grid-cols-2 gap-6">
        <div className="md:col-span-2">
          <h3 className="font-serif text-2xl font-bold mb-1">考生画像</h3>
          <p className="font-mono text-xs text-muted">请填写真实信息，系统将基于位次法生成推荐。</p>
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">姓名（可选）</label>
          <input
            name="name"
            value={form.name}
            onChange={handleChange}
            placeholder="用于标识本次方案"
            className="brutal-input"
          />
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">省份</label>
          <div className="relative">
            <select name="province" value={form.province} onChange={handleChange} className="brutal-select">
              <option value="湖北">湖北</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" size={18} />
          </div>
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">科类</label>
          <div className="flex gap-4">
            {['物理', '历史'].map((type) => (
              <label
                key={type}
                className={`flex-1 cursor-pointer px-4 py-3 border-3 border-ink text-center font-bold transition-all ${
                  form.subject_type === type
                    ? 'bg-accent text-white shadow-brutal-sm translate-x-[2px] translate-y-[2px] shadow-none'
                    : 'bg-white hover:bg-paper'
                }`}
              >
                <input
                  type="radio"
                  name="subject_type"
                  value={type}
                  checked={form.subject_type === type}
                  onChange={handleChange}
                  className="sr-only"
                />
                {type}
              </label>
            ))}
          </div>
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
          <p className="text-[11px] text-muted mt-1">位次是核心依据，比分数更稳定。</p>
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">高考总分（仅作参考）</label>
          <input
            name="score"
            type="number"
            min="0"
            max="750"
            value={form.score}
            onChange={handleChange}
            placeholder="例如 580"
            className="brutal-input"
          />
          <p className="text-[11px] text-muted mt-1">不用于推荐计算，仅显示。</p>
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">意向专业（用顿号分隔）</label>
          <input
            name="preferred_major"
            value={form.preferred_major}
            onChange={handleChange}
            placeholder="例如 计算机、电子信息、电气"
            className="brutal-input"
          />
        </div>

        <div>
          <label className="block font-bold text-sm mb-2">意向城市</label>
          <input
            name="preferred_city"
            value={form.preferred_city}
            onChange={handleChange}
            placeholder="例如 武汉、南京、杭州"
            className="brutal-input"
          />
        </div>

        <div className="md:col-span-2">
          <label className="block font-bold text-sm mb-2">填报策略</label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {STRATEGIES.map((s) => (
              <label
                key={s.value}
                className={`cursor-pointer p-4 border-3 border-ink transition-all ${
                  form.strategy === s.value
                    ? 'bg-accent text-white shadow-brutal-sm translate-x-[2px] translate-y-[2px] shadow-none'
                    : 'bg-white hover:bg-paper'
                }`}
              >
                <input
                  type="radio"
                  name="strategy"
                  value={s.value}
                  checked={form.strategy === s.value}
                  onChange={handleChange}
                  className="sr-only"
                />
                <div className="font-bold text-sm">{s.label}</div>
                <div className={`text-xs mt-1 ${form.strategy === s.value ? 'text-white/80' : 'text-muted'}`}>
                  {s.desc}
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="md:col-span-2 flex items-start gap-3">
          <input
            id="adjustment"
            name="accept_adjustment"
            type="checkbox"
            checked={form.accept_adjustment}
            onChange={handleChange}
            className="mt-1 w-5 h-5 accent-accent border-3 border-ink"
          />
          <label htmlFor="adjustment" className="text-sm leading-relaxed">
            <span className="font-bold">接受专业组内调剂</span>
            <span className="text-muted block">
              勾选表示愿意接受该院校专业组内其他专业调剂；不勾选时，系统会优先推荐组内专业均为可接受志愿。
            </span>
          </label>
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
