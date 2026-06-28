export default function Footer() {
  return (
    <footer className="bg-ink text-paper py-10 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid md:grid-cols-3 gap-8 border-b-2 border-paper/20 pb-8">
          <div>
            <h4 className="font-serif text-lg font-bold mb-2">高考志愿 Agent</h4>
            <p className="text-paper/70 text-sm leading-relaxed">
              基于 Agent + RAG 的志愿填报辅助系统，强调数据透明、可解释性与风险控制。
            </p>
          </div>
          <div>
            <h4 className="font-serif text-lg font-bold mb-2">数据来源</h4>
            <ul className="text-paper/70 text-sm space-y-1">
              <li>湖北省教育考试院</li>
              <li>阳光高考平台</li>
              <li>高校本科招生网</li>
              <li>教育部学科评估</li>
            </ul>
          </div>
          <div>
            <h4 className="font-serif text-lg font-bold mb-2">重要声明</h4>
            <p className="text-paper/70 text-sm leading-relaxed">
              本系统输出仅供参考，最终志愿填报请以各省招生考试机构官方信息为准。AI 不承诺录取结果。
            </p>
          </div>
        </div>
        <div className="pt-6 flex flex-col md:flex-row justify-between items-center gap-4 text-xs font-mono text-paper/50">
          <span>Backend :11678 · Frontend :1678</span>
          <span>© 2026 Academic Gaokao Agent. Open for research.</span>
        </div>
      </div>
    </footer>
  )
}
