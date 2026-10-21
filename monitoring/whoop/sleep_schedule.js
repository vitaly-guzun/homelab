// PostgreSQL supplies integer seconds, local clock labels and period averages.
// The renderer only draws intervals and formats axis ticks; it has no lookup table.
const text = context.grafana.theme.isDark ? '#CCCCDC' : '#202226';
const frame = context.panel.data.series.find((s) => s.fields.some((f) => f.name === 'observed_at'));
if (!frame || !frame.length) {
  context.panel.chart.clear();
  return { title: { text: 'No main sleep in selected period', left: 'center', textStyle: { color: text } } };
}
const fields = Object.fromEntries(frame.fields.map((f) => [f.name, f.values]));
const rows = Array.from({ length: frame.length }, (_, i) =>
  Object.fromEntries(Object.entries(fields).map(([name, values]) => [name, values[i]])));
const first = rows[0];
const clock = (seconds) => {
  const minutes = Math.floor(seconds / 60);
  return `${String((Math.floor(minutes / 60) % 24 + 24) % 24).padStart(2, '0')}:${String((minutes % 60 + 60) % 60).padStart(2, '0')}`;
};
const timezone = context.grafana.replaceVariables('${__timezone}');
const dates = new Intl.DateTimeFormat('en-GB', { timeZone: timezone, day: '2-digit', month: '2-digit' });
const range = context.panel.data.timeRange;
const gaps = rows.slice(1).map((r, i) => r.observed_at - rows[i].observed_at).filter((gap) => gap > 0);
const widthMs = Math.min(86400000, ...gaps) * 0.72;
return {
  animation: false,
  title: { text: `Average time in bed: ${first.avg_time_in_bed_local ?? 'N/A'}`, left: 'center',
    textStyle: { fontSize: 14, fontWeight: 'normal', color: text } },
  grid: { top: 44, bottom: 40, left: 72, right: 24 },
  xAxis: { type: 'time', min: range.from.valueOf(), max: range.to.valueOf(),
    axisLabel: { formatter: (value) => dates.format(value), hideOverlap: true, color: text }, splitLine: { show: false } },
  yAxis: { type: 'value', inverse: true, interval: 14400,
    min: Math.min(68400, Math.floor(Math.min(...rows.map((r) => r.bedtime_seconds)) / 3600) * 3600),
    max: Math.max(126000, Math.ceil(Math.max(...rows.map((r) => r.wake_seconds)) / 3600) * 3600),
    axisLabel: { formatter: clock, color: text },
    splitLine: { lineStyle: { color: 'rgba(128,128,128,0.2)' } } },
  tooltip: { trigger: 'item', confine: true, formatter: (p) => {
    const r = rows[p.dataIndex];
    return `${r.wake_date}<br/>Bedtime: <b>${r.bedtime_local}</b><br/>Wake: <b>${r.wake_local}</b>`
      + `<br/>Time in bed: <b>${r.time_in_bed_local ?? 'N/A'}</b>`;
  } },
  series: [{ type: 'custom', name: 'Main sleep', encode: { x: 0, y: [1, 2] },
    data: rows.map((r) => [r.observed_at, r.bedtime_seconds, r.wake_seconds]),
    renderItem: (params, api) => {
      const start = api.coord([api.value(0), api.value(1)]);
      const end = api.coord([api.value(0), api.value(2)]);
      const width = Math.max(1, Math.min(28, api.size([widthMs, 0])[0]));
      const shape = context.echarts.graphic.clipRectByRect({ x: start[0] - width / 2,
        y: start[1], width, height: Math.max(1, end[1] - start[1]) }, params.coordSys);
      return shape && { type: 'rect', shape: { ...shape, r: Math.min(3, width / 4) }, style: { fill: '#8FB7CF' } };
    },
    markLine: { silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: text, width: 1.5 },
      label: { position: 'start', color: '#111217', backgroundColor: '#FFFFFF', padding: [4, 6], borderRadius: 3 },
      data: [
        { name: 'Average bedtime', yAxis: first.avg_bedtime_seconds, label: { formatter: first.avg_bedtime_local } },
        { name: 'Average wake', yAxis: first.avg_wake_seconds, label: { formatter: first.avg_wake_local } },
      ] },
  }],
};
