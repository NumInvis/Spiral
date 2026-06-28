import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'

export default function HomePage() {
  return (
    <div className="space-y-16 pb-16">
      {/* Hero */}
      <section className="relative pt-16 pb-12 px-4">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-block px-3 py-1 bg-accent text-white text-xs font-bold border-2 border-ink mb-6">
            SPIRAL · 高考志愿 Agent
          </div>
          <h1 className="font-serif text-4xl md:text-6xl font-bold leading-[1.1] mb-6 text-balance">
            输入位次与要求
            <br />
            <span className="text-accent">生成可解释的志愿表</span>
          </h1>
          <p className="text-lg md:text-xl text-muted max-w-2xl mx-auto leading-relaxed mb-10">
            基于全省位次、等位分换算与 LLM 语义理解，为全国院校在各省的招生计划生成冲/稳/保三档推荐，每一步都标注数据来源与置信度。
          </p>
          <Link to="/recommend" className="brutal-btn text-lg inline-flex">
            开始填报 <ArrowRight size={20} className="ml-2" />
          </Link>
        </div>
      </section>

      {/* 流程 */}
      <section className="px-4">
        <div className="max-w-4xl mx-auto">
          <div className="grid md:grid-cols-3 gap-4">
            {[
              { n: '01', t: '填写画像', d: '省份、位次、以及自由描述的要求' },
              { n: '02', t: '生成报告', d: 'LLM 解析 + 位次法计算概率与分档' },
              { n: '03', t: '预览下载', d: '在页面内预览 HTML 报告并一键下载' },
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
