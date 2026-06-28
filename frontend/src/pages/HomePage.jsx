import { Link } from 'react-router-dom'
import { ArrowRight, Shield, Search, BarChart3 } from 'lucide-react'

export default function HomePage() {
  return (
    <div className="space-y-16 pb-16">
      {/* Hero */}
      <section className="relative pt-16 pb-24 px-4">
        <div className="max-w-5xl mx-auto">
          <div className="inline-block px-3 py-1 bg-accent text-white text-xs font-bold border-2 border-ink mb-6">
            AGENT + RAG · 2026 ACADEMIC EDITION
          </div>
          <h1 className="font-serif text-5xl md:text-7xl font-bold leading-[1.1] mb-6 text-balance">
            用结构化推理
            <br />
            <span className="text-accent">填一份可解释的志愿表</span>
          </h1>
          <p className="text-lg md:text-xl text-muted max-w-2xl leading-relaxed mb-10">
            拒绝黑盒推荐。基于位次法、历史录取数据与学科评估，为湖北考生生成 45 个院校专业组志愿，
            每一步都标注数据来源与置信度。
          </p>
          <div className="flex flex-wrap gap-4">
            <Link to="/recommend" className="brutal-btn text-lg">
              开始填报 <ArrowRight size={20} className="ml-2" />
            </Link>
            <Link to="/data" className="brutal-btn-secondary text-lg">
              浏览院校数据
            </Link>
          </div>
        </div>
      </section>

      {/* 特性 */}
      <section className="px-4">
        <div className="max-w-6xl mx-auto">
          <div className="mb-10">
            <h2 className="section-title">为什么不同</h2>
            <p className="section-subtitle">DESIGN PRINCIPLES</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            <div className="brutal-card p-6">
              <div className="w-12 h-12 bg-accent text-white flex items-center justify-center border-3 border-ink mb-4">
                <BarChart3 size={24} />
              </div>
              <h3 className="font-serif text-xl font-bold mb-2">位次优先，非分数算命</h3>
              <p className="text-muted text-sm leading-relaxed">
                每年试卷难度不同，但位次相对稳定。系统以考生全省位次为核心，换算往年等位分，避免只看分数导致的偏差。
              </p>
            </div>
            <div className="brutal-card p-6">
              <div className="w-12 h-12 bg-teal text-white flex items-center justify-center border-3 border-ink mb-4">
                <Search size={24} />
              </div>
              <h3 className="font-serif text-xl font-bold mb-2">缺失数据实时补全</h3>
              <p className="text-muted text-sm leading-relaxed">
                非 985/211 院校专业分数线常不完整。Agent 会主动触发 Web 搜索补数据，并对估算结果标注置信等级。
              </p>
            </div>
            <div className="brutal-card p-6">
              <div className="w-12 h-12 bg-burgundy text-white flex items-center justify-center border-3 border-ink mb-4">
                <Shield size={24} />
              </div>
              <h3 className="font-serif text-xl font-bold mb-2">风险控制与可解释</h3>
              <p className="text-muted text-sm leading-relaxed">
                每个志愿都给出录取概率、推荐理由、风险提示。保底不足时系统会拒绝生成方案，强制用户补全安全垫。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 流程 */}
      <section className="px-4">
        <div className="max-w-6xl mx-auto">
          <div className="mb-10">
            <h2 className="section-title">使用流程</h2>
            <p className="section-subtitle">FOUR STEPS</p>
          </div>
          <div className="grid md:grid-cols-4 gap-4">
            {[
              { n: '01', t: '填写画像', d: '省份、科类、分数、位次、意向专业与城市' },
              { n: '02', t: '选择策略', d: '院校优先 / 专业优先 / 城市优先 / 综合平衡' },
              { n: '03', t: '生成方案', d: 'Agent 检索数据、计算概率、分档排序' },
              { n: '04', t: '人工复核', d: '查看置信度与风险提示，调整后导出' },
            ].map((step) => (
              <div key={step.n} className="brutal-card p-5">
                <div className="font-mono text-3xl font-bold text-accent mb-3">{step.n}</div>
                <h4 className="font-serif text-lg font-bold mb-2">{step.t}</h4>
                <p className="text-muted text-sm">{step.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
