import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

const LEVEL_COLORS = {
  冲: '#7C2D12',
  稳: '#1E3A5A',
  保: '#0F766E',
}

const SCHOOL_LEVEL_COLORS = {
  '985': '#1E3A5A',
  '211': '#2E5A8C',
  '双一流': '#0F766E',
  '普通本科': '#5F6F52',
  '民办本科': '#7C2D12',
}

export default function RecommendationCharts({ data }) {
  if (!data || !data.recommendations) return null

  const { 冲_count, 稳_count, 保_count, recommendations } = data

  const levelData = [
    { name: '冲', value: 冲_count, color: LEVEL_COLORS.冲 },
    { name: '稳', value: 稳_count, color: LEVEL_COLORS.稳 },
    { name: '保', value: 保_count, color: LEVEL_COLORS.保 },
  ]

  const probBuckets = [
    { name: '20-35%', count: 0, level: '冲' },
    { name: '35-50%', count: 0, level: '冲' },
    { name: '50-65%', count: 0, level: '稳' },
    { name: '65-85%', count: 0, level: '稳' },
    { name: '85-95%', count: 0, level: '保' },
    { name: '95%+', count: 0, level: '保' },
  ]

  recommendations.forEach((r) => {
    const p = r.probability * 100
    if (p < 35) probBuckets[0].count += 1
    else if (p < 50) probBuckets[1].count += 1
    else if (p < 65) probBuckets[2].count += 1
    else if (p < 85) probBuckets[3].count += 1
    else if (p < 95) probBuckets[4].count += 1
    else probBuckets[5].count += 1
  })

  const schoolLevelMap = {}
  recommendations.forEach((r) => {
    const level = r.school_level || '普通本科'
    schoolLevelMap[level] = (schoolLevelMap[level] || 0) + 1
  })

  const schoolLevelData = Object.entries(schoolLevelMap)
    .map(([name, value]) => ({
      name,
      value,
      color: SCHOOL_LEVEL_COLORS[name] || '#5C5C5C',
    }))
    .sort((a, b) => b.value - a.value)

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white border-2 border-ink p-2 shadow-brutal-sm text-xs">
          <p className="font-bold">{label || payload[0].name}</p>
          <p className="font-mono">{payload[0].value} 个</p>
        </div>
      )
    }
    return null
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* 冲稳保分布 */}
      <div className="brutal-card p-5 space-y-3">
        <h3 className="font-serif font-bold text-lg">冲稳保分布</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={levelData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={45}
                outerRadius={70}
                paddingAngle={3}
                stroke="#1A1A1A"
                strokeWidth={2}
              >
                {levelData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend
                verticalAlign="bottom"
                height={24}
                iconType="square"
                formatter={(value) => (
                  <span className="text-xs font-bold">{value}</span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 概率区间分布 */}
      <div className="brutal-card p-5 space-y-3">
        <h3 className="font-serif font-bold text-lg">录取概率区间</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={probBuckets} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#D4D4D4" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: '#1A1A1A', fontFamily: 'JetBrains Mono' }}
                axisLine={{ stroke: '#1A1A1A', strokeWidth: 2 }}
                tickLine={{ stroke: '#1A1A1A' }}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#1A1A1A', fontFamily: 'JetBrains Mono' }}
                axisLine={{ stroke: '#1A1A1A', strokeWidth: 2 }}
                tickLine={{ stroke: '#1A1A1A' }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="count" stroke="#1A1A1A" strokeWidth={2} radius={[2, 2, 0, 0]}>
                {probBuckets.map((entry, index) => (
                  <Cell key={`bar-${index}`} fill={LEVEL_COLORS[entry.level]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 院校层次分布 */}
      <div className="brutal-card p-5 space-y-3">
        <h3 className="font-serif font-bold text-lg">院校层次分布</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={schoolLevelData}
              margin={{ top: 10, right: 30, left: 40, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#D4D4D4" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fontSize: 10, fill: '#1A1A1A', fontFamily: 'JetBrains Mono' }}
                axisLine={{ stroke: '#1A1A1A', strokeWidth: 2 }}
                tickLine={{ stroke: '#1A1A1A' }}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 11, fill: '#1A1A1A', fontWeight: 700 }}
                axisLine={{ stroke: '#1A1A1A', strokeWidth: 2 }}
                tickLine={{ stroke: '#1A1A1A' }}
                width={70}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" stroke="#1A1A1A" strokeWidth={2} radius={[0, 2, 2, 0]}>
                {schoolLevelData.map((entry, index) => (
                  <Cell key={`level-${index}`} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
