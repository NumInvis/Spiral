import { useEffect, useState } from 'react'
import { listSchools, searchMajors } from '../api'
import SchoolCard from '../components/SchoolCard'
import { Search, Loader2 } from 'lucide-react'

export default function DataPage() {
  const [schools, setSchools] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [majors, setMajors] = useState([])

  useEffect(() => {
    listSchools({ province: '湖北' })
      .then((res) => setSchools(res.data))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (query.length < 2) {
      setMajors([])
      return
    }
    const timer = setTimeout(() => {
      searchMajors(query).then((res) => setMajors(res.data))
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
      <div>
        <h1 className="section-title">院校与专业数据</h1>
        <p className="section-subtitle">INSTITUTION & MAJOR DATABASE</p>
      </div>

      <div className="brutal-card p-4 flex flex-col md:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索专业名称，例如：计算机、法学、临床医学…"
            className="brutal-input pl-10"
          />
        </div>
      </div>

      {majors.length > 0 && (
        <div className="brutal-card p-4">
          <h3 className="font-serif text-lg font-bold mb-3">专业搜索结果</h3>
          <div className="overflow-x-auto">
            <table className="brutal-table">
              <thead>
                <tr>
                  <th>专业</th>
                  <th>门类</th>
                  <th>所属院校</th>
                </tr>
              </thead>
              <tbody>
                {majors.map((m) => (
                  <tr key={m.id}>
                    <td className="font-bold">{m.name}</td>
                    <td>{m.category}</td>
                    <td>{m.school}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin mr-2" size={24} />
          <span className="font-mono text-muted">加载院校数据中…</span>
        </div>
      ) : (
        <div>
          <h3 className="font-serif text-lg font-bold mb-4">湖北本科院校（{schools.length} 所）</h3>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {schools.map((school) => (
              <SchoolCard key={school.id} school={school} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
