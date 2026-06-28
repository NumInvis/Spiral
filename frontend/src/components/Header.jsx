import { Link, useLocation } from 'react-router-dom'
import { GraduationCap, BarChart3 } from 'lucide-react'

export default function Header() {
  const location = useLocation()
  const nav = [
    { path: '/', label: '首页', icon: GraduationCap },
    { path: '/recommend', label: '智能填报', icon: BarChart3 },
  ]

  return (
    <header className="sticky top-0 z-50 bg-paper border-b-3 border-ink">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link to="/" className="flex items-center gap-2 group">
            <div className="w-10 h-10 bg-accent text-white flex items-center justify-center border-3 border-ink shadow-brutal-sm group-hover:shadow-none group-hover:translate-x-[2px] group-hover:translate-y-[2px] transition-all">
              <GraduationCap size={22} strokeWidth={2.5} />
            </div>
            <div>
              <div className="font-serif font-bold text-xl leading-none">高考志愿 Agent</div>
              <div className="font-mono text-[10px] text-muted tracking-widest">ACADEMIC EDITION</div>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {nav.map((item) => {
              const active = location.pathname === item.path
              const Icon = item.icon
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-2 px-4 py-2 font-semibold border-3 transition-all ${
                    active
                      ? 'bg-accent text-white border-ink shadow-brutal-sm translate-x-[2px] translate-y-[2px] shadow-none'
                      : 'bg-paper text-ink border-transparent hover:border-ink hover:shadow-brutal-sm'
                  }`}
                >
                  <Icon size={18} strokeWidth={2.5} />
                  {item.label}
                </Link>
              )
            })}
          </nav>

          <div className="md:hidden">
            {/* 移动端简化：仅显示当前路径 */}
            <span className="font-mono text-xs text-muted">{location.pathname}</span>
          </div>
        </div>
      </div>
    </header>
  )
}
