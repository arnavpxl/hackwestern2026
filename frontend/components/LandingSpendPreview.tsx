const legend = [
  { label: "Growth", color: "#4f46e5" },
  { label: "Platform", color: "#0891b2" },
  { label: "Research", color: "#d97706" },
  { label: "Support AI", color: "#db2777" },
];

export default function LandingSpendPreview() {
  return (
    <figure className="rounded-xl border border-line bg-surface p-4 shadow-sm sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink sm:text-base">Spend per minute, last hour</h2>
          <p className="mt-0.5 text-[10px] text-ink-3 sm:text-xs">Real-time aggregate · usage_1m · Eastern time</p>
        </div>
        <span className="pill bg-green-bg text-green">Live</span>
      </div>

      <svg className="mt-4 h-auto w-full" viewBox="0 0 760 330" role="img" aria-labelledby="landing-chart-title landing-chart-desc">
        <title id="landing-chart-title">Example spend per minute by team</title>
        <desc id="landing-chart-desc">A stacked area chart showing steady spend across Growth, Platform, Research, and Support AI, with a short Support AI spike.</desc>

        <g stroke="#dbe5ef" strokeDasharray="3 4" strokeWidth="1">
          <line x1="48" y1="42" x2="742" y2="42" />
          <line x1="48" y1="101" x2="742" y2="101" />
          <line x1="48" y1="160" x2="742" y2="160" />
          <line x1="48" y1="219" x2="742" y2="219" />
          <line x1="48" y1="278" x2="742" y2="278" />
          {[74, 126, 178, 230, 282, 334, 386, 438, 490, 542, 594, 646, 698].map((x) => (
            <line key={x} x1={x} y1="42" x2={x} y2="278" />
          ))}
        </g>

        <g fill="#6f7772" fontFamily="var(--font-inter), sans-serif" fontSize="10" textAnchor="end">
          <text x="41" y="46">$8</text>
          <text x="41" y="105">$6</text>
          <text x="41" y="164">$4</text>
          <text x="41" y="223">$2</text>
          <text x="41" y="282">$0</text>
        </g>

        {/* Draw cumulative areas from the top down so each lower band remains visible. */}
        <path d="M48 107 L83 105 L118 108 L153 106 L188 107 L223 105 L258 107 L293 106 L328 108 L363 107 L398 108 L433 107 L468 108 L503 108 L538 108 L573 106 L590 82 L607 108 L642 109 L677 108 L712 109 L742 122 L742 278 L48 278 Z" fill="#db2777" fillOpacity=".34" />
        <path d="M48 136 L83 135 L118 137 L153 136 L188 137 L223 135 L258 137 L293 136 L328 138 L363 138 L398 139 L433 138 L468 139 L503 139 L538 139 L573 138 L607 139 L642 139 L677 139 L712 140 L742 151 L742 278 L48 278 Z" fill="#d97706" fillOpacity=".34" />
        <path d="M48 211 L83 209 L118 212 L153 210 L188 211 L223 209 L258 211 L293 210 L328 212 L363 211 L398 212 L433 211 L468 212 L503 212 L538 212 L573 211 L607 212 L642 212 L677 212 L712 213 L742 219 L742 278 L48 278 Z" fill="#0891b2" fillOpacity=".34" />
        <path d="M48 249 L83 248 L118 250 L153 249 L188 250 L223 248 L258 250 L293 249 L328 251 L363 250 L398 251 L433 250 L468 251 L503 251 L538 251 L573 250 L607 251 L642 251 L677 251 L712 252 L742 256 L742 278 L48 278 Z" fill="#4f46e5" fillOpacity=".38" />

        <g fill="none" strokeWidth="1.5" strokeLinejoin="round">
          <path d="M48 107 L83 105 L118 108 L153 106 L188 107 L223 105 L258 107 L293 106 L328 108 L363 107 L398 108 L433 107 L468 108 L503 108 L538 108 L573 106 L590 82 L607 108 L642 109 L677 108 L712 109 L742 122" stroke="#db2777" />
          <path d="M48 136 L83 135 L118 137 L153 136 L188 137 L223 135 L258 137 L293 136 L328 138 L363 138 L398 139 L433 138 L468 139 L503 139 L538 139 L573 138 L607 139 L642 139 L677 139 L712 140 L742 151" stroke="#d97706" />
          <path d="M48 211 L83 209 L118 212 L153 210 L188 211 L223 209 L258 211 L293 210 L328 212 L363 211 L398 212 L433 211 L468 212 L503 212 L538 212 L573 211 L607 212 L642 212 L677 212 L712 213 L742 219" stroke="#0891b2" />
          <path d="M48 249 L83 248 L118 250 L153 249 L188 250 L223 248 L258 250 L293 249 L328 251 L363 250 L398 251 L433 250 L468 251 L503 251 L538 251 L573 250 L607 251 L642 251 L677 251 L712 252 L742 256" stroke="#4f46e5" />
        </g>

        <g stroke="#6f7772" strokeWidth="1.2">
          <line x1="48" y1="42" x2="48" y2="278" />
          <line x1="48" y1="278" x2="742" y2="278" />
        </g>
        <g fill="#6f7772" fontFamily="var(--font-inter), sans-serif" fontSize="9" textAnchor="middle">
          <text x="48" y="294">18:36</text><text x="187" y="294">18:48</text><text x="326" y="294">19:00</text>
          <text x="465" y="294">19:12</text><text x="604" y="294">19:24</text><text x="742" y="294">19:35</text>
        </g>

        <g transform="translate(180 316)" fontFamily="var(--font-inter), sans-serif" fontSize="10">
          {legend.map((item, index) => {
            const x = index * 104;
            return <g key={item.label} transform={`translate(${x} 0)`}><line x1="0" y1="-3" x2="13" y2="-3" stroke={item.color} strokeWidth="2" /><circle cx="6.5" cy="-3" r="2.5" fill="white" stroke={item.color} strokeWidth="2" /><text x="18" y="0" fill={item.color}>{item.label}</text></g>;
          })}
        </g>
      </svg>

      <figcaption className="sr-only">A representative preview of the synthetic demo dashboard.</figcaption>
      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3">
        {[["Month to date", "$184,290"], ["Current burn", "$391/h"], ["Open cases", "3"]].map(([label, value]) => (
          <div key={label} className="rounded-lg bg-surface-2 p-2.5"><div className="text-[9px] uppercase tracking-wide text-ink-3">{label}</div><div className="mt-0.5 text-sm font-semibold text-ink">{value}</div></div>
        ))}
      </div>
    </figure>
  );
}
