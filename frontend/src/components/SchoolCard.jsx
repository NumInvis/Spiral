import { MapPin, GraduationCap, Award } from 'lucide-react'

const LEVEL_COLORS = {
  '985': 'bg-burgundy text-white border-burgundy',
  '211': 'bg-accent text-white border-accent',
  '双一流': 'bg-teal text-white border-teal',
  '普通本科': 'bg-ink text-white border-ink',
}

export default function SchoolCard({ school }) {
  return (
    <div className="brutal-card p-5 hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-none transition-all">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h3 className="font-serif text-xl font-bold">{school.name}</h3>
          <div className="font-mono text-xs text-muted mt-1">{school.code}</div>
        </div>
        <span className={`px-2 py-1 text-xs font-bold border-2 ${LEVEL_COLORS[school.level] || LEVEL_COLORS['普通本科']}`}>
          {school.level || '普通本科'}
        </span>
      </div>

      <div className="flex flex-wrap gap-3 text-sm text-muted mb-4">
        <div className="flex items-center gap-1">
          <MapPin size={14} />
          {school.city}
        </div>
        {school.has_master && (
          <div className="flex items-center gap-1">
            <GraduationCap size={14} />
            硕士点
          </div>
        )}
        {school.has_phd && (
          <div className="flex items-center gap-1">
            <Award size={14} />
            博士点
          </div>
        )}
      </div>

      {school.majors && school.majors.length > 0 && (
        <div className="border-t-2 border-ink pt-3">
          <div className="text-xs font-bold mb-2">在湖北招生专业示例</div>
          <div className="flex flex-wrap gap-2">
            {school.majors.slice(0, 6).map((m) => (
              <span key={m.id} className="px-2 py-1 text-xs bg-paper border-2 border-ink font-mono">
                {m.name}
              </span>
            ))}
            {school.majors.length > 6 && (
              <span className="px-2 py-1 text-xs text-muted">+{school.majors.length - 6}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
