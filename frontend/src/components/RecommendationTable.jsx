import { useState } from 'react'
import { ChevronDown, ChevronUp, AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import ConfidenceBadge from './ConfidenceBadge'

export default function RecommendationTable({ data }) {
  const [expanded, setExpanded] = useState({})

  const toggle = (idx) => {
    setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }))
  }

  if (!data || !data.recommendations) return null

  const { 冲_count, 稳_count, 保_count, recommendations, warnings } = data

  return (
    <div className="space-y-6">
      {/* 统计面板 */}
      <div className="grid grid-cols-3 gap-4">
        <div className="brutal-card p-4 text-center">
          <div className="text-3xl font-serif font-bold text-burgundy">{冲_count}</div>
          <div className="text-xs font-bold uppercase tracking-wider">冲</div>
          <div className="text-[10px] text-muted mt-1">概率 20%-50%</div>
        </div>
        <div className="brutal-card p-4 text-center">
          <div className="text-3xl font-serif font-bold text-accent">{稳_count}</div>
          <div className="text-xs font-bold uppercase tracking-wider">稳</div>
          <div className="text-[10px] text-muted mt-1">概率 50%-85%</div>
        </div>
        <div className="brutal-card p-4 text-center">
          <div className="text-3xl font-serif font-bold text-teal">{保_count}</div>
          <div className="text-xs font-bold uppercase tracking-wider">保</div>
          <div className="text-[10px] text-muted mt-1">概率 85%+</div>
        </div>
      </div>

      {/* 警告 */}
      {warnings.length > 0 && (
        <div className="brutal-card p-4 border-l-[6px] border-l-warn">
          <div className="flex items-start gap-3">
            <AlertTriangle className="text-warn shrink-0" size={22} />
            <div className="space-y-1">
              {warnings.map((w, i) => (
                <p key={i} className="text-sm font-medium">{w}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 志愿表 */}
      <div className="overflow-x-auto">
        <table className="brutal-table">
          <thead>
            <tr>
              <th className="w-16 text-center">序号</th>
              <th>档位</th>
              <th>院校</th>
              <th>专业组</th>
              <th>录取概率</th>
              <th>数据置信</th>
              <th className="w-20">详情</th>
            </tr>
          </thead>
          <tbody>
            {recommendations.map((item, idx) => {
              const isOpen = expanded[idx]
              const levelBadge =
                item.level === '冲' ? 'badge-chong' : item.level === '稳' ? 'badge-wen' : 'badge-bao'
              return (
                <>
                  <tr key={item.group_index} className="hover:bg-accent/5 transition-colors">
                    <td className="text-center font-mono font-bold">{item.group_index}</td>
                    <td><span className={levelBadge}>{item.level}</span></td>
                    <td>
                      <div className="font-bold">{item.school_name}</div>
                      <div className="text-xs text-muted font-mono">{item.school_code} · {item.city}</div>
                    </td>
                    <td>
                      <div className="font-mono text-sm">{item.group_code}</div>
                      <div className="text-xs text-muted">{item.majors.length} 个专业</div>
                    </td>
                    <td>
                      <div className="font-serif font-bold text-lg">{(item.probability * 100).toFixed(0)}%</div>
          <div className="text-[10px] text-muted font-mono">按位次估算</div>
                    </td>
                    <td><ConfidenceBadge level={item.data_confidence} /></td>
                    <td>
                      <button
                        onClick={() => toggle(idx)}
                        className="p-2 border-2 border-ink hover:bg-accent hover:text-white transition-colors"
                      >
                        {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                      </button>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={7} className="bg-white">
                        <div className="p-4 space-y-4">
                          <div className="flex items-start gap-2">
                            <Info size={18} className="text-accent shrink-0 mt-0.5" />
                            <p className="text-sm"><span className="font-bold">推荐理由：</span>{item.reason}</p>
                          </div>

                          {item.risk_notes.length > 0 && (
                            <div className="flex items-start gap-2">
                              <AlertTriangle size={18} className="text-warn shrink-0 mt-0.5" />
                              <ul className="text-sm space-y-1">
                                {item.risk_notes.map((note, i) => (
                                  <li key={i}>· {note}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          <table className="w-full border-2 border-ink text-sm">
                            <thead>
                              <tr className="bg-paper">
                                <th className="border-2 border-ink px-3 py-2 text-left">专业</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">门类</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">学科评估</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">往年最低位次</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">往年最低分（参考）</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">概率</th>
                                <th className="border-2 border-ink px-3 py-2 text-left">置信</th>
                              </tr>
                            </thead>
                            <tbody>
                              {item.majors.map((m, mi) => (
                                <tr key={mi}>
                                  <td className="border-2 border-ink px-3 py-2 font-medium">{m.name}</td>
                                  <td className="border-2 border-ink px-3 py-2 text-muted">{m.category}</td>
                                  <td className="border-2 border-ink px-3 py-2">{m.discipline_eval || '-'}</td>
                                  <td className="border-2 border-ink px-3 py-2 font-mono font-bold">{m.ref_rank ? m.ref_rank.toLocaleString() : '-'}</td>
                                  <td className="border-2 border-ink px-3 py-2 font-mono text-muted">{m.ref_score || '-'}</td>
                                  <td className="border-2 border-ink px-3 py-2 font-bold">{(m.probability * 100).toFixed(0)}%</td>
                                  <td className="border-2 border-ink px-3 py-2"><ConfidenceBadge level={m.data_confidence} /></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="brutal-card p-4 flex items-start gap-3">
        <CheckCircle2 className="text-teal shrink-0" size={22} />
        <p className="text-sm text-muted">
          本表按湖北省本科普通批 45 个院校专业组志愿生成。请结合自身情况、家庭经济条件、体检限制及 2026 年最新招生计划调整，最终方案以省招办系统填报为准。
        </p>
      </div>
    </div>
  )
}
