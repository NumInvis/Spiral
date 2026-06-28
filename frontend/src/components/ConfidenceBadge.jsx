export default function ConfidenceBadge({ level }) {
  const map = {
    A: { cls: 'badge-conf-a', text: 'A 官方完整' },
    B: { cls: 'badge-conf-b', text: 'B 部分估算' },
    C: { cls: 'badge-conf-c', text: 'C 数据缺失' },
    D: { cls: 'badge bg-warn text-white border-warn', text: 'D 需核实' },
  }
  const conf = map[level] || map['D']
  return <span className={conf.cls}>{conf.text}</span>
}
